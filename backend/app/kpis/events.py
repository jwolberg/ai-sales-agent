"""KPI event vocabulary (PRD §16).

Canonical ``KPIEvent.event_type`` values emitted during a call. The engine emits these at the
relevant decision points; metrics (`app/kpis/metrics.py`) roll them up across calls. Centralized
here so the emit side and the compute side can't drift.
"""

OBJECTION_RAISED = "objection_raised"
ESCALATION = "escalation"
CLOSE_ATTEMPT = "close_attempt"
DISCOVERY_COMPLETE = "discovery_complete"
CALL_COMPLETED = "call_completed"
# Captured when detection lands later; metrics already account for them.
UNSUPPORTED_CLAIM = "unsupported_claim"
FRUSTRATION = "frustration"

# Intent-router events (IR-1 / IR-5).
MIS_QUOTE_BLOCKED = "mis_quote_blocked"  # agent tried to state an off-table price; guard caught it
LEAF_REACHED = "leaf_reached"            # the brain reached a confident classification leaf
CLARIFY_ASKED = "clarify_asked"          # the brain asked a disambiguating question
