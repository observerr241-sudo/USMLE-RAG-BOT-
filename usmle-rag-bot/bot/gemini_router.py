"""Gemini access layer built on gemini-api-rotator."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Callable, Literal

import numpy as np
from google import genai
from google.genai import types
from gemini_rotator import ErrorType, GeminiAPIRotator, RotatorConfig, classify_error
from pydantic import BaseModel, Field, ValidationError

from bot import config
from bot.prompts import build_system_prompt, build_user_prompt

logger = logging.getLogger(__name__)


class USMLEQuestionItem(BaseModel):
    question_description: str = Field(
        description="The full self-contained USMLE clinical vignette plus single-sentence lead-in question in English."
    )
    options: list[str] = Field(
        description="Array of exactly 5 concise answer strings in English WITHOUT the letter prefix."
    )
    correct_answer_index: int = Field(description="0-based index of the correct answer (0 to 4).")
    correct_option: Literal["A", "B", "C", "D", "E"] = Field(
        description="Letter of the correct option ('A', 'B', 'C', 'D', or 'E') matching correct_answer_index."
    )
    explanation: str = Field(
        description="Plain prose explanation (400-600 characters, 2-4 sentences, no bullet points, no letter references) starting with why the correct concept is right, why top distractors are wrong, and ending with 'Pearl: ...'"
    )


class USMLEQuizResponse(BaseModel):
    questions: list[USMLEQuestionItem]


_rotator: GeminiAPIRotator | None = None


def get_rotator() -> GeminiAPIRotator:
    global _rotator
    if _rotator is not None:
        return _rotator
    if not config.GEMINI_API_KEYS:
        raise RuntimeError("GEMINI_API_KEYS is empty")

    db = None
    try:
        from gemini_rotator.adapters import SQLiteAdapter

        os.makedirs(os.path.dirname(os.path.abspath(config.ROTATOR_DB)), exist_ok=True)
        db = SQLiteAdapter(config.ROTATOR_DB)
    except Exception as exc:
        logger.warning("Rotator SQLite persistence disabled: %s", exc)

    n = len(config.GEMINI_API_KEYS)
    cfg = RotatorConfig(
        rpm_per_key=config.ROTATOR_RPM_PER_KEY,
        max_concurrent_per_key=config.ROTATOR_MAX_CONCURRENT_PER_KEY,
        max_retries=2,
        retry_delay_seconds=1.0,
    )
    _rotator = GeminiAPIRotator(
        config.GEMINI_API_KEYS,
        config=cfg,
        db=db,
        on_key_suspended=lambda k: logger.error("Gemini key suspended: ...%s", k[-6:]),
        on_key_recovered=lambda k: logger.info("Gemini key recovered: ...%s", k[-6:]),
    )
    return _rotator


async def revalidate_loop(interval_seconds: int = 6 * 3600) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            recovered = await get_rotator().revalidate_suspended_keys()
            logger.info("Rotator recheck: %s recovered | %s", recovered, get_rotator().summary())
        except Exception:
            logger.exception("Rotator revalidation failed")


async def call_with_rotation(fn: Callable[[genai.Client], Any], *, model: str, max_attempts: int | None = None) -> Any:
    rotator = get_rotator()
    attempts = max_attempts or max(4, min(len(config.GEMINI_API_KEYS) * 2, 10))
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        key = rotator.get_next_working_key()
        if key is None:
            raise RuntimeError("All Gemini API keys are suspended")
        rotator.acquire(key)
        t0 = time.perf_counter()
        try:
            client = genai.Client(api_key=key)
            result = await asyncio.get_running_loop().run_in_executor(None, lambda: fn(client))
            rotator.record_outcome(key, exc=None, latency=time.perf_counter() - t0, model=model)
            return result
        except Exception as exc:
            last_exc = exc
            rotator.record_outcome(key, exc=exc, model=model)
            if classify_error(exc) == ErrorType.UNKNOWN:
                raise
            logger.warning("Gemini call failed on attempt %d/%d (%s); rotating key", attempt, attempts, type(exc).__name__)
            await asyncio.sleep(min(1.5 * attempt, 8))
        finally:
            rotator.release(key)
    assert last_exc is not None
    raise last_exc


def _normalize(vecs: list[list[float]]) -> list[list[float]]:
    arr = np.asarray(vecs, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (arr / norms).tolist()


async def embed_texts(texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    if not texts:
        return []

    def _fn(client: genai.Client):
        return client.models.embed_content(
            model=config.EMBEDDING_MODEL,
            contents=texts,
            config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=config.EMBEDDING_DIM),
        )

    res = await call_with_rotation(_fn, model=config.EMBEDDING_MODEL)
    vecs = [list(e.values) for e in res.embeddings]
    if len(vecs) != len(texts):
        raise RuntimeError(f"Embedding count mismatch: got {len(vecs)} for {len(texts)} texts")
    return _normalize(vecs)


async def embed_query(text: str) -> list[float]:
    return (await embed_texts([text], task_type="RETRIEVAL_QUERY"))[0]


def _clean_questions(items: list[USMLEQuestionItem]) -> list[dict]:
    good: list[dict] = []
    seen: set[str] = set()
    for it in items:
        opts = [o.strip() for o in it.options if o and o.strip()]
        stem = it.question_description.strip()
        if len(opts) != 5 or len(set(o.lower() for o in opts)) != 5:
            continue
        if not 0 <= it.correct_answer_index <= 4 or not stem or not it.explanation.strip():
            continue
        if stem.lower() in seen:
            continue
        seen.add(stem.lower())
        idx = it.correct_answer_index
        good.append({
            "question_description": stem,
            "options": opts,
            "correct_answer_index": idx,
            "correct_option": "ABCDE"[idx],
            "explanation": it.explanation.strip(),
        })
    return good


# Fast low-latency models first so Windows sockets never hang for 80+ seconds
FALLBACK_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-2.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
]


async def generate_mcqs(topic: str, subtopic: str, count: int, chunks: str, segment_group: int) -> list[dict]:
    rotator = get_rotator()
    system = build_system_prompt(topic, subtopic, count)
    prompt = build_user_prompt(topic, subtopic, count, chunks)
    min_ok = max(1, int(count * 0.7))
    best: list[dict] = []
    last_error = "unknown error"

    models_to_try = list(dict.fromkeys([config.GENERATION_MODEL] + FALLBACK_MODELS))

    try:
        n = rotator.total_count()
        with rotator._lock:
            rotator._last_index = ((segment_group - 1) % n) - 1
    except Exception:
        pass

    for attempt, current_model in enumerate(models_to_try, start=1):
        key = rotator.get_next_working_key()
        if key is None:
            raise RuntimeError("All Gemini API keys are suspended")
        rotator.acquire(key)
        t0 = time.perf_counter()
        try:
            def _call() -> Any:
                # 25s HTTP timeout prevents Windows [WinError 10053] socket hang
                client = genai.Client(api_key=key, http_options={"timeout": 25000})
                return client.models.generate_content(
                    model=current_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        temperature=0.4,
                        max_output_tokens=8192,
                        response_mime_type="application/json",
                        response_schema=USMLEQuizResponse,
                    ),
                )

            response = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(None, _call),
                timeout=28,
            )
            rotator.record_outcome(key, exc=None, latency=time.perf_counter() - t0, model=current_model)
            parsed = USMLEQuizResponse.model_validate_json(response.text)
            good = _clean_questions(parsed.questions)[:count]
            if len(good) > len(best):
                best = good
            if len(good) >= count:
                logger.info("Generated %d MCQs using %s in %.1fs", len(good), current_model, time.perf_counter() - t0)
                return good
            last_error = f"{current_model} returned {len(good)}/{count} valid questions"
        except (ValidationError, ValueError) as exc:
            last_error = f"invalid JSON from {current_model}: {str(exc)[:120]}"
        except asyncio.TimeoutError:
            last_error = f"timeout on {current_model} (>28s) -> switching model"
            logger.warning("Attempt %d (%s) timed out -> switching model immediately", attempt, current_model)
        except Exception as exc:
            err_str = str(exc)
            if "503" not in err_str and "404" not in err_str and "10053" not in err_str and "timed out" not in err_str.lower():
                rotator.record_outcome(key, exc=exc, model=current_model)
            last_error = f"{type(exc).__name__} on {current_model}: {err_str[:120]}"
            logger.warning("Attempt %d (%s) failed: %s -> switching model immediately", attempt, current_model, last_error)
        finally:
            rotator.release(key)

        await asyncio.sleep(0.3)

    if len(best) >= min_ok:
        return best
    raise RuntimeError(last_error)
