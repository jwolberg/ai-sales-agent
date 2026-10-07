"""Shared fixtures."""

import pytest

from app import limits


@pytest.fixture(autouse=True)
def _reset_limits():
    """The SMS budget and session slots are process-global; isolate every test from the others."""
    limits.reset()
    yield
    limits.reset()
