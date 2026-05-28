"""Tests for filler selection (P4.5-T6)."""

from app.voice.fillers import DEFAULT_ACKS, DEFAULT_WORKING, FillerBank


def test_question_gets_a_working_filler():
    assert FillerBank().pick("How does tutor matching work?") in DEFAULT_WORKING


def test_statement_gets_a_short_ack():
    assert FillerBank().pick("She's in 8th grade.") in DEFAULT_ACKS


def test_fillers_rotate_so_they_dont_loop():
    bank = FillerBank()
    picks = [bank.pick("ok") for _ in range(2)]
    assert picks[0] != picks[1]  # DEFAULT_ACKS has several; rotation advances


def test_neutral_acks_are_safe_prefixes():
    # Acks must be non-committal so they can't contradict the reply that follows.
    assert all(len(a) < 20 for a in DEFAULT_ACKS)
