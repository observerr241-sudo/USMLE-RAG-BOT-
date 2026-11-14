FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY bot ./bot

RUN useradd --create-home --uid 10001 botuser && mkdir -p /app/data && chown -R botuser /app
USER botuser

CMD ["python", "-m", "bot.main"]
