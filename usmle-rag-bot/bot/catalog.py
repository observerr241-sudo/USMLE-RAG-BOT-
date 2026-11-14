"""First Aid Step 1 hierarchy. Integer ids keep Telegram callback_data far below the 64-byte limit."""
from __future__ import annotations

from typing import TypedDict


class Topic(TypedDict):
    name: str
    short: str                       # button label
    segment_group: int               # 1..5, selects the starting Gemini key
    pages: tuple[int, int]           # printed page range in First Aid (inclusive)
    subtopics: dict[int, str]


def _t(name: str, short: str, group: int, pages: tuple[int, int], subs: list[str]) -> Topic:
    return {
        "name": name,
        "short": short,
        "segment_group": group,
        "pages": pages,
        "subtopics": {i: s for i, s in enumerate(subs)},
    }


_SYSTEM = ["Embryology", "Anatomy", "Physiology", "Pathology", "Pharmacology"]

FIRST_AID_CATALOG: dict[int, Topic] = {
    0: _t("Biochemistry", "Biochemistry", 1, (31, 92),
          ["Molecular", "Cellular", "Laboratory Techniques", "Genetics", "Nutrition", "Metabolism"]),
    1: _t("Immunology", "Immunology", 1, (93, 120),
          ["Lymphoid Structures", "Cellular Components", "Immune Responses", "Immunosuppressants"]),
    2: _t("Microbiology", "Microbiology", 1, (121, 200),
          ["Basic Bacteriology", "Clinical Bacteriology", "Mycology", "Parasitology", "Virology", "Systems", "Antimicrobials"]),
    3: _t("Pathology", "Pathology", 2, (201, 226),
          ["Cellular Injury", "Inflammation", "Neoplasia"]),
    4: _t("Pharmacology", "Pharmacology", 2, (227, 254),
          ["Pharmacokinetics & Pharmacodynamics", "Autonomic Drugs", "Toxicities & Side Effects"]),
    5: _t("Public Health Sciences", "Public Health", 2, (255, 278),
          ["Epidemiology & Biostatistics", "Ethics", "Healthcare Delivery", "Quality & Safety"]),
    6: _t("Cardiovascular", "Cardiovascular", 3, (283, 328), _SYSTEM),
    7: _t("Endocrine", "Endocrine", 3, (329, 362), _SYSTEM),
    8: _t("Gastrointestinal", "Gastrointestinal", 3, (363, 408), _SYSTEM),
    9: _t("Hematology and Oncology", "Hematology & Oncology", 4, (409, 448), _SYSTEM),
    10: _t("Musculoskeletal, Skin, and Connective Tissue", "MSK, Skin & Connective", 4, (449, 498),
           ["Embryology", "Anatomy", "Physiology", "Pathology", "Dermatology", "Pharmacology"]),
    11: _t("Neurology and Special Senses", "Neuro & Special Senses", 4, (499, 568),
           ["Embryology", "Anatomy & Physiology", "Pathology", "Otolaryngology", "Ophthalmology", "Pharmacology"]),
    12: _t("Psychiatry", "Psychiatry", 5, (569, 594),
           ["Psychology", "Pathology", "Pharmacology"]),
    13: _t("Renal", "Renal", 5, (595, 628),
           ["Embryology", "Anatomy", "Physiology", "Acid-Base & Electrolytes", "Pathology", "Pharmacology"]),
    14: _t("Reproductive", "Reproductive", 5, (629, 676), _SYSTEM),
    15: _t("Respiratory", "Respiratory", 5, (677, 706), _SYSTEM),
    16: _t("Rapid Review", "Rapid Review", 5, (707, 746),
           ["Classic Presentations", "Classic Labs & Findings", "Most Common Associations"]),
}


def get_topic(t_id: int) -> Topic | None:
    return FIRST_AID_CATALOG.get(t_id)


def get_subtopic_name(t_id: int, s_id: int) -> str | None:
    t = FIRST_AID_CATALOG.get(t_id)
    return t["subtopics"].get(s_id) if t else None


def section_label(t_id: int) -> str:
    if t_id == 16:
        return "Rapid Review"
    return "High-Yield General Principles" if FIRST_AID_CATALOG[t_id]["segment_group"] <= 2 else "High-Yield Organ Systems"


def topic_count() -> int:
    return len(FIRST_AID_CATALOG)


def subtopic_count() -> int:
    return sum(len(t["subtopics"]) for t in FIRST_AID_CATALOG.values())
