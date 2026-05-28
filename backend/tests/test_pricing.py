"""Pricing tests (IR1-T1) — exact leaf-keyed lookup, honest None for gaps."""

from app.agent import taxonomy as tx
from app.agent.pricing import PriceBook, get_pricebook, quote_price


def test_every_taxonomy_leaf_has_a_price():
    book = get_pricebook()
    for leaf in tx.ALL_LEAVES:
        rec = book.get(leaf.id)
        assert rec is not None, f"missing price for {leaf.id}"
        assert rec.amount > 0
        assert rec.unit
        assert rec.leaf_id == leaf.id


def test_quote_price_accepts_leaf_or_id():
    leaf = tx.leaf_from_id("tutoring/science/chemistry")
    by_leaf = quote_price(leaf)
    by_id = quote_price("tutoring/science/chemistry")
    assert by_leaf == by_id
    assert by_leaf is not None
    assert by_leaf.display.startswith("$")


def test_unknown_or_partial_leaf_returns_none():
    # not a valid leaf id -> no invented price (R6b)
    assert quote_price("test_prep/GRE") is None
    assert quote_price("tutoring/math") is None
    assert quote_price("") is None


def test_display_formats_whole_dollars():
    rec = quote_price("test_prep/SAT")
    assert rec is not None
    assert rec.display == f"${int(rec.amount)}"


def test_placeholder_prices_flagged_unapproved():
    rec = quote_price("test_prep/SAT")
    assert rec is not None
    # Placeholder content must not masquerade as approved (R6b / limitations).
    assert rec.approved is False


def test_loader_rejects_unknown_leaf_id(tmp_path):
    bad = tmp_path / "pricing.yaml"
    bad.write_text("currency: USD\nleaves:\n  bogus/leaf:\n    amount: 1\n    unit: per hour\n")
    try:
        PriceBook.load(bad)
        raised = False
    except ValueError:
        raised = True
    assert raised, "loader must reject a price keyed to an unknown leaf"
