"""The agent's persona: system prompt, greeting cue, and per-stage directives.

The system prompt is built once per call and reused for every turn so the persona
stays consistent (PRD VC-4). Identity (name/company) comes from config. Per-stage
directives give the orchestrator a short, stage-specific instruction it can surface
to the model as the call advances (wired into generation in P2-T4 / P3).
"""

from app.agent.stages import Stage
from app.config import Settings


def build_system_prompt(settings: Settings) -> str:
    """Persona prompt. Identity comes from config; stage-specific guidance is layered
    on top via :func:`stage_directive`."""
    return (
        f"You are {settings.agent_name}, a warm, consultative sales specialist for "
        f"{settings.company_name}. Your goal is to understand the caller's tutoring needs "
        "and help them take a sensible next step. Be concise and natural — this is a spoken "
        "phone call, so keep replies short and ask one question at a time. Never invent "
        "prices, guarantees, or policies; if you are unsure, say so. Do not claim to be human. "
        "Output ONLY the words you would say out loud — never include stage directions, "
        "narration, sound effects, or any text in asterisks or parentheses (e.g. do not write "
        "'*picks up call*')."
    )


def build_greeting_cue(settings: Settings) -> str:
    """First-turn cue so the agent speaks first (Anthropic needs a user turn to respond to)."""
    return (
        "The call has just connected. Greet the caller warmly, introduce yourself as "
        f"{settings.agent_name} from {settings.company_name}, and ask how you can help today."
    )


# Short, stage-specific instruction added on top of the persona as the call moves
# through the arc (docs/AGENT_FLOW.md §5). Kept terse — these are spoken-call cues.
_STAGE_DIRECTIVES: dict[Stage, str] = {
    Stage.GREETING: "Greet and identify yourself briefly. Do not over-explain.",
    Stage.CONTEXT_CONFIRMATION: (
        "Confirm what you already know about their need, then ask about what is still missing."
    ),
    Stage.DISCOVERY: (
        "Ask one required discovery question, phrased conversationally — not as a checklist."
    ),
    Stage.NEED_DEVELOPMENT: "Explore the pain, urgency, or motivation behind their need.",
    Stage.KNOWLEDGE_ANSWER: (
        "Answer briefly from approved information only, check that it helped, then bridge back."
    ),
    Stage.OBJECTION_HANDLING: (
        "Acknowledge and explore the concern before responding — do not immediately rebut."
    ),
    Stage.FIT_SUMMARY: "Summarize what you heard and confirm it is accurate.",
    Stage.CLOSE: "Recommend one concrete next step, matched to how ready they sound.",
    Stage.ESCALATION: "Warmly hand the caller off to a human specialist.",
    Stage.WRAP_UP: "Confirm the agreed next step and close the call politely.",
    Stage.DISQUALIFIED: "Politely stop selling and leave the door open.",
}


def stage_directive(stage: Stage) -> str:
    """Return the short stage-specific instruction for ``stage`` (empty if none)."""
    return _STAGE_DIRECTIVES.get(stage, "")
