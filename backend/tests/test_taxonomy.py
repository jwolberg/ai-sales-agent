"""Taxonomy tests (IR0-T3) — slot validation, parent inference, leaf resolution."""

import pytest

from app.agent import taxonomy as tx
from app.agent.taxonomy import Category, Leaf


def test_eight_leaves_with_expected_ids():
    assert len(tx.ALL_LEAVES) == 8
    assert set(tx.LEAF_IDS) == {
        "test_prep/SAT",
        "test_prep/ACT",
        "test_prep/PSAT",
        "tutoring/math/algebra",
        "tutoring/math/geometry",
        "tutoring/science/chemistry",
        "tutoring/science/biology",
        "tutoring/science/physics",
    }


def test_leaf_id_and_label():
    leaf = Leaf(Category.TUTORING, subject_area="science", subject="chemistry")
    assert leaf.id == "tutoring/science/chemistry"
    assert leaf.label == "chemistry tutoring"
    assert Leaf(Category.TEST_PREP, test="SAT").label == "SAT test prep"


def test_leaf_roundtrip_by_id():
    for leaf in tx.ALL_LEAVES:
        assert tx.leaf_from_id(leaf.id) == leaf
    assert tx.is_valid_leaf_id("test_prep/ACT")
    assert not tx.is_valid_leaf_id("test_prep/GRE")
    with pytest.raises(KeyError):
        tx.leaf_from_id("nope")


def test_normalize_accepts_variants_and_rejects_junk():
    assert tx.normalize("category", "Test Prep") == "test_prep"
    assert tx.normalize("category", "tutor") == "tutoring"
    assert tx.normalize("test", "sat") == "SAT"
    assert tx.normalize("subject", "chem") == "chemistry"
    assert tx.normalize("subject_area", "mathematics") == "math"
    assert tx.normalize("test", "GRE") is None
    assert tx.normalize("subject", "history") is None
    assert tx.normalize("category", "") is None


def test_child_implies_parents():
    # subject implies its area and tutoring category
    leaf = tx.resolve_leaf({"subject": "chemistry"})
    assert leaf == Leaf(Category.TUTORING, subject_area="science", subject="chemistry")
    # test implies test_prep category
    assert tx.resolve_leaf({"test": "ACT"}) == Leaf(Category.TEST_PREP, test="ACT")


def test_resolve_requires_full_path():
    assert tx.resolve_leaf({}) is None
    assert tx.resolve_leaf({"category": "tutoring"}) is None
    assert tx.resolve_leaf({"category": "tutoring", "subject_area": "math"}) is None
    assert tx.resolve_leaf({"category": "test_prep"}) is None


def test_contradictions_are_dropped():
    # a stray test under tutoring is ignored; not a leaf yet
    assert tx.resolve_leaf({"category": "tutoring", "test": "SAT"}) is None
    # subject that doesn't match the stated area is dropped
    assert (
        tx.resolve_leaf({"category": "tutoring", "subject_area": "math", "subject": "chemistry"})
        is None
    )


def test_next_unfilled_disambiguation_order():
    assert tx.next_unfilled({}) == "category"
    assert tx.next_unfilled({"category": "test_prep"}) == "test"
    assert tx.next_unfilled({"category": "tutoring"}) == "subject_area"
    assert tx.next_unfilled({"category": "tutoring", "subject_area": "science"}) == "subject"
    assert tx.next_unfilled({"subject": "algebra"}) is None  # inferred complete
    assert tx.next_unfilled({"test": "PSAT"}) is None


def test_is_complete():
    assert tx.is_complete({"test": "SAT"})
    assert not tx.is_complete({"category": "test_prep"})
