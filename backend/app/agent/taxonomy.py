"""Intent taxonomy — the classification target for the voice intent-router (IR0-T3, R5).

The agent's whole job is to converse until it can name a **leaf** of this fixed tree, then quote
that leaf's price (IR-1). The tree::

    Caller intent
    ├── test_prep            (option 1)
    │   ├── SAT
    │   ├── ACT
    │   └── PSAT
    └── tutoring             (option 2)
        ├── math
        │   ├── algebra
        │   └── geometry
        └── science
            ├── chemistry
            ├── biology
            └── physics

This module is **pure** (no I/O, no LLM). The brain fills slots via a ``slot_fill(field, value)``
tool; the slot fields are ``category`` / ``test`` / ``subject_area`` / ``subject``. Children imply
their parents (``test=SAT`` ⇒ ``category=test_prep``; ``subject=chemistry`` ⇒
``subject_area=science`` ⇒ ``category=tutoring``), so the brain can slot whatever the caller
volunteers and :func:`resolve_leaf` fills in the rest. A leaf id looks like ``test_prep/SAT`` or
``tutoring/science/chemistry`` and is the key used by the price table.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# --- the tree, as data -----------------------------------------------------------------

TESTS: tuple[str, ...] = ("SAT", "ACT", "PSAT")

# subject_area -> subjects under it
SUBJECTS: dict[str, tuple[str, ...]] = {
    "math": ("algebra", "geometry"),
    "science": ("chemistry", "biology", "physics"),
}

SUBJECT_AREAS: tuple[str, ...] = tuple(SUBJECTS.keys())

# The ordered slot fields the brain fills.
SLOT_FIELDS: tuple[str, ...] = ("category", "test", "subject_area", "subject")


class Category(str, Enum):
    TEST_PREP = "test_prep"
    TUTORING = "tutoring"


# --- light normalization (the slot_fill tool enumerates canonical values, but callers/the
#     brain may pass close variants; keep this forgiving but bounded) --------------------

_CATEGORY_SYNONYMS = {
    "test_prep": Category.TEST_PREP,
    "test prep": Category.TEST_PREP,
    "test-prep": Category.TEST_PREP,
    "testprep": Category.TEST_PREP,
    "prep": Category.TEST_PREP,
    "tutoring": Category.TUTORING,
    "tutor": Category.TUTORING,
    "tutor help": Category.TUTORING,
    "subject help": Category.TUTORING,
}

_SUBJECT_SYNONYMS = {
    "algebra": "algebra",
    "geometry": "geometry",
    "chemistry": "chemistry",
    "chem": "chemistry",
    "biology": "biology",
    "bio": "biology",
    "physics": "physics",
}

_AREA_SYNONYMS = {
    "math": "math",
    "mathematics": "math",
    "maths": "math",
    "science": "science",
}

# subject -> its subject_area (derived from SUBJECTS)
_SUBJECT_TO_AREA = {s: area for area, subjects in SUBJECTS.items() for s in subjects}


def normalize(field: str, value: str) -> str | None:
    """Canonicalize a slot value, or return None if it isn't a valid value for the field."""
    if value is None:
        return None
    v = str(value).strip().lower()
    if not v:
        return None
    if field == "category":
        cat = _CATEGORY_SYNONYMS.get(v)
        return cat.value if cat else None
    if field == "test":
        upper = v.upper()
        return upper if upper in TESTS else None
    if field == "subject_area":
        return _AREA_SYNONYMS.get(v)
    if field == "subject":
        return _SUBJECT_SYNONYMS.get(v)
    return None


# --- leaf ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Leaf:
    """A fully-specified caller need (a leaf of the tree)."""

    category: Category
    test: str | None = None            # set when category is test_prep
    subject_area: str | None = None    # set when category is tutoring
    subject: str | None = None         # set when category is tutoring

    @property
    def id(self) -> str:
        """Stable id used as the price-table key, e.g. 'test_prep/SAT'."""
        if self.category is Category.TEST_PREP:
            return f"{self.category.value}/{self.test}"
        return f"{self.category.value}/{self.subject_area}/{self.subject}"

    @property
    def label(self) -> str:
        """Human phrasing, e.g. 'SAT test prep' / 'chemistry tutoring'."""
        if self.category is Category.TEST_PREP:
            return f"{self.test} test prep"
        return f"{self.subject} tutoring"


def _all_leaves() -> tuple[Leaf, ...]:
    leaves = [Leaf(Category.TEST_PREP, test=t) for t in TESTS]
    for area, subjects in SUBJECTS.items():
        leaves += [Leaf(Category.TUTORING, subject_area=area, subject=s) for s in subjects]
    return tuple(leaves)


ALL_LEAVES: tuple[Leaf, ...] = _all_leaves()
LEAF_IDS: tuple[str, ...] = tuple(leaf.id for leaf in ALL_LEAVES)
_LEAVES_BY_ID = {leaf.id: leaf for leaf in ALL_LEAVES}


def leaf_from_id(leaf_id: str) -> Leaf:
    """Look up a Leaf by its id. Raises KeyError on an unknown id."""
    return _LEAVES_BY_ID[leaf_id]


def is_valid_leaf_id(leaf_id: str) -> bool:
    return leaf_id in _LEAVES_BY_ID


# --- slot resolution -------------------------------------------------------------------


def canonicalize(slots: dict) -> dict:
    """Return a normalized copy of ``slots`` with implied parents filled from children.

    Drops invalid values. ``test`` implies ``category=test_prep``; ``subject`` implies its
    ``subject_area`` and ``category=tutoring``.
    """
    out: dict[str, str] = {}
    for field in SLOT_FIELDS:
        if field in slots and slots[field] is not None:
            norm = normalize(field, slots[field])
            if norm is not None:
                out[field] = norm

    # children imply parents
    if "subject" in out:
        out.setdefault("subject_area", _SUBJECT_TO_AREA[out["subject"]])
    if "subject" in out or "subject_area" in out:
        out.setdefault("category", Category.TUTORING.value)
    if "test" in out:
        out.setdefault("category", Category.TEST_PREP.value)

    # drop slots that contradict a known category (e.g. a stray 'test' under tutoring)
    if out.get("category") == Category.TUTORING.value:
        out.pop("test", None)
    elif out.get("category") == Category.TEST_PREP.value:
        out.pop("subject_area", None)
        out.pop("subject", None)

    # drop a subject that doesn't belong to its area (contradiction)
    if "subject" in out and "subject_area" in out:
        if _SUBJECT_TO_AREA.get(out["subject"]) != out["subject_area"]:
            out.pop("subject")

    return out


def resolve_leaf(slots: dict) -> Leaf | None:
    """Return the Leaf if ``slots`` fully specify one valid leaf, else None."""
    c = canonicalize(slots)
    category = c.get("category")
    if category == Category.TEST_PREP.value:
        if c.get("test") in TESTS:
            return Leaf(Category.TEST_PREP, test=c["test"])
        return None
    if category == Category.TUTORING.value:
        area, subject = c.get("subject_area"), c.get("subject")
        if area in SUBJECTS and subject in SUBJECTS.get(area, ()):
            return Leaf(Category.TUTORING, subject_area=area, subject=subject)
        return None
    return None


def is_complete(slots: dict) -> bool:
    return resolve_leaf(slots) is not None


def next_unfilled(slots: dict) -> str | None:
    """The next slot field needed to reach a leaf, or None if already complete.

    This is the disambiguation order the brain should follow (R8): category first, then the
    branch-specific fields.
    """
    c = canonicalize(slots)
    if is_complete(c):
        return None
    category = c.get("category")
    if category is None:
        return "category"
    if category == Category.TEST_PREP.value:
        return "test"
    # tutoring
    if c.get("subject_area") is None:
        return "subject_area"
    return "subject"
