"""Logging setup + PII helpers (ticket 0007).

Modules log via ``logging.getLogger(__name__)`` (the ``app.*`` namespace). Phone numbers are
masked to their last four digits wherever they're logged, and :func:`scrub` masks any that ride
along inside provider error text (Twilio's error bodies echo the destination number). Never log
API keys/tokens — log the outcome, not the request.
"""

from __future__ import annotations

import logging
import re

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
# A phone-ish run: optional +, then 10+ digits allowing common separators.
_PHONE_RE = re.compile(r"\+?\d(?:[\s().-]*\d){9,}")


def configure_logging(level: str = "INFO") -> None:
    """Route ``app.*`` records to stderr at ``level``. Idempotent; leaves uvicorn's loggers alone.

    ``basicConfig`` only installs a root handler if none exists, so it never doubles output, and
    the level is set on the ``app`` logger (not root) so third-party libraries keep their own."""
    logging.basicConfig(format=_FORMAT)
    logging.getLogger("app").setLevel(level.upper())


def mask_phone(number: str | None) -> str | None:
    if number is None:
        return None
    digits = re.sub(r"\D", "", number)
    return f"***{digits[-4:]}" if len(digits) > 4 else "***"


def scrub(text: str) -> str:
    """Mask phone numbers embedded in free text (e.g. a provider's error message)."""
    return _PHONE_RE.sub(lambda m: mask_phone(m.group()) or "***", text)
