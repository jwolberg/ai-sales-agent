"""Router persona tests (IR5-T1) — ground-truth leaves cover the taxonomy."""

from app.agent import taxonomy as tx
from app.simulator.personas import get_personas


def test_router_personas_have_valid_leaves_and_openings():
    router = get_personas().router_personas()
    assert router, "expected intent-router personas with target_leaf"
    for p in router:
        assert tx.is_valid_leaf_id(p.target_leaf), f"{p.key}: bad leaf {p.target_leaf}"
        assert p.opening_line, f"{p.key}: missing opening_line"


def test_router_personas_cover_all_eight_leaves():
    covered = {p.target_leaf for p in get_personas().router_personas()}
    assert covered == set(tx.LEAF_IDS)


def test_legacy_personas_have_no_target_leaf():
    # The original discovery-to-close personas are untouched (still load, no leaf).
    assert get_personas().get("motivated_parent").target_leaf is None
