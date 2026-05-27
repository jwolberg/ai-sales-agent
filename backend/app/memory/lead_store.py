"""Lead profile loading and cross-call memory (PRD §9.2: LM-1..LM-4).

Loads a lead at call start (full / partial / no info — Use Cases 1–3), reports which
required fields are known vs. missing (so the agent can skip-known and ask only for
gaps), and writes a call's outcome back onto the lead so the next call continues from
prior context.

The field-state helpers are pure (operate on a lead ORM object *or* a plain dict) so the
DB-free orchestrator can reuse them; :class:`LeadStore` is the DB-touching part.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Lead

# The discoverable lead profile (LM-1). These are the Lead columns the agent fills in.
PROFILE_FIELDS: tuple[str, ...] = (
    "student_name",
    "relationship_to_student",
    "subject",
    "grade_level",
    "goal",
    "urgency",
    "schedule_constraints",
    "decision_maker_status",
    "budget_sensitivity",
)

# The minimum needed for a productive conversation (DF-1: who needs tutoring, subject,
# grade). Their absence is what gates discovery; the rest are explored opportunistically.
REQUIRED_FIELDS: tuple[str, ...] = (
    "relationship_to_student",
    "subject",
    "grade_level",
)

INFO_FULL = "full"
INFO_PARTIAL = "partial"
INFO_NONE = "none"


def _value(source: Lead | Mapping[str, Any], name: str) -> Any:
    """Read ``name`` from a Lead ORM object or a plain mapping."""
    if isinstance(source, Mapping):
        return source.get(name)
    return getattr(source, name, None)


def known_fields(source: Lead | Mapping[str, Any]) -> dict[str, Any]:
    """Return the populated profile fields (non-empty values only)."""
    return {f: _value(source, f) for f in PROFILE_FIELDS if _value(source, f)}


def missing_required(source: Lead | Mapping[str, Any]) -> list[str]:
    """Return the required fields that are still unknown (in canonical order)."""
    return [f for f in REQUIRED_FIELDS if not _value(source, f)]


def info_level(source: Lead | Mapping[str, Any]) -> str:
    """Classify how much we know: ``full`` (all required known), ``none`` (nothing
    in the profile), or ``partial`` (something, but required gaps remain)."""
    if not known_fields(source):
        return INFO_NONE
    if not missing_required(source):
        return INFO_FULL
    return INFO_PARTIAL


class LeadStore:
    """Loads leads and persists per-call outcomes back to them (cross-call memory)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def load(self, lead_id: str) -> Lead | None:
        """Load a lead by id, or ``None`` if unknown (a no-info web session)."""
        return self._session.get(Lead, lead_id)

    def get_or_create(self, lead_id: str | None = None, **defaults: Any) -> Lead:
        """Return the existing lead, or create a fresh one (Use Case 3: no prior info)."""
        if lead_id is not None:
            existing = self._session.get(Lead, lead_id)
            if existing is not None:
                return existing
        lead = Lead(**({"lead_id": lead_id} if lead_id else {}), **defaults)
        self._session.add(lead)
        self._session.commit()
        return lead

    def apply_call_outcome(
        self,
        lead: Lead,
        *,
        collected: Mapping[str, Any] | None = None,
        objections: Iterable[str] | None = None,
        summary: str | None = None,
        status: str | None = None,
    ) -> Lead:
        """Write a finished call's results onto the lead so the next call has them (LM-4).

        - ``collected``: newly learned profile fields (only non-empty values are applied).
        - ``objections``: appended to ``prior_objections``, de-duplicated.
        - ``summary``: replaces ``prior_summary`` (the running cross-call summary).
        - ``status``: the lead's next-step / lifecycle status.
        """
        if collected:
            for key, value in collected.items():
                if key in PROFILE_FIELDS and value:
                    setattr(lead, key, value)
        if objections:
            merged = list(lead.prior_objections or [])
            for objection in objections:
                if objection not in merged:
                    merged.append(objection)
            lead.prior_objections = merged
        if summary is not None:
            lead.prior_summary = summary
        if status is not None:
            lead.status = status
        self._session.commit()
        return lead
