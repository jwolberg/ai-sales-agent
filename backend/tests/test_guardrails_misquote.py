"""Mis-quote guardrail tests (IR1-T2, R6)."""

from app.agent.guardrails import check_mis_quote, extract_price_amounts
from app.agent.pricing import quote_price


def test_extract_price_amounts_variants():
    assert extract_price_amounts("It's $85 an hour") == [85.0]
    assert extract_price_amounts("about 39.99 dollars") == [39.99]
    assert extract_price_amounts("$6.99 to $9.99 per week") == [6.99, 9.99]
    assert extract_price_amounts("no numbers here") == []


def test_no_price_is_always_clean():
    # Talking about price without quoting one is fine, even with nothing authorized.
    assert check_mis_quote("Pricing depends on the plan.", allowed_amount=None) is False


def test_unauthorized_price_is_a_violation():
    # A dollar amount with no authorized leaf/price -> hard violation.
    assert check_mis_quote("It's $85 an hour.", allowed_amount=None) is True


def test_matching_authorized_price_is_clean():
    rec = quote_price("test_prep/SAT")
    assert rec is not None
    assert check_mis_quote(rec.summary, allowed_amount=rec.amount) is False
    assert check_mis_quote("That's $85 per hour.", allowed_amount=85.0) is False


def test_mismatched_authorized_price_is_a_violation():
    # Authorized $85 but the agent said $50 -> violation.
    assert check_mis_quote("I can do $50 an hour for you.", allowed_amount=85.0) is True
