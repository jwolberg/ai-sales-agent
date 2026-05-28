"""Brain tests (IR2-T2) — RuleBrain (offline) + OpenAIBrain with a fake client."""

from types import SimpleNamespace

from app.agent.brain import OpenAIBrain, RuleBrain, get_brain
from app.agent.contract import RouterAction
from app.config import Settings


def _rule_brain():
    return RuleBrain(Settings(_env_file=None))


# --- RuleBrain --------------------------------------------------------------------------


def test_rule_brain_asks_category_when_nothing_known():
    d = _rule_brain().decide(history=[("prospect", "Hi, I have a question.")])
    assert d.action is RouterAction.ASK
    assert d.leaf is None
    assert "test prep" in d.utterance.lower() or "tutoring" in d.utterance.lower()


def test_rule_brain_reaches_leaf_and_quotes_on_subject():
    d = _rule_brain().decide(history=[("prospect", "I need help with chemistry.")])
    assert d.action is RouterAction.QUOTE
    assert d.leaf == "tutoring/science/chemistry"
    assert d.quoted_amount == 80.0
    assert "80" in d.utterance


def test_rule_brain_disambiguates_then_quotes_over_turns():
    brain = _rule_brain()
    d1 = brain.decide(history=[("prospect", "I'm looking for tutoring.")])
    assert d1.action is RouterAction.ASK
    assert d1.slots.get("category") == "tutoring"
    # carry slots forward as the engine will
    d2 = brain.decide(
        history=[("prospect", "It's a science subject")], slots=d1.slots
    )
    assert d2.action is RouterAction.ASK  # still need which science
    d3 = brain.decide(history=[("prospect", "biology")], slots=d2.slots)
    assert d3.action is RouterAction.QUOTE
    assert d3.leaf == "tutoring/science/biology"


def test_rule_brain_test_prep_path():
    d = _rule_brain().decide(history=[("prospect", "I want to prep for the SAT.")])
    assert d.action is RouterAction.QUOTE
    assert d.leaf == "test_prep/SAT"


def test_rule_brain_escalates_on_discount_request():
    d = _rule_brain().decide(history=[("prospect", "Can you give me a discount?")])
    assert d.action is RouterAction.ESCALATE


def test_get_brain_factory():
    assert isinstance(get_brain(Settings(_env_file=None)), RuleBrain)
    assert isinstance(get_brain(Settings(_env_file=None, openai_api_key="sk-x")), OpenAIBrain)


# --- OpenAIBrain (fake client) ----------------------------------------------------------


def _tool_call(call_id, name, args_json):
    return SimpleNamespace(
        id=call_id, function=SimpleNamespace(name=name, arguments=args_json)
    )


class _FakeCompletions:
    def __init__(self, scripted):
        self._scripted = scripted
        self.calls = 0

    def create(self, **_kw):
        msg = self._scripted[self.calls]
        self.calls += 1
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


class _FakeClient:
    def __init__(self, scripted):
        self.chat = SimpleNamespace(completions=_FakeCompletions(scripted))


def test_openai_brain_tool_loop_quotes():
    # Turn 1: model fills subject + asks for a price. Turn 2: model composes the spoken reply.
    msg1 = SimpleNamespace(
        content="",
        tool_calls=[
            _tool_call("1", "slot_fill", '{"field": "subject", "value": "chemistry"}'),
            _tool_call("2", "quote_price", "{}"),
        ],
    )
    msg2 = SimpleNamespace(
        content="Chemistry tutoring is $80 an hour. Want me to connect you with a specialist?",
        tool_calls=None,
    )
    brain = OpenAIBrain(
        Settings(_env_file=None, openai_api_key="sk-x"), client=_FakeClient([msg1, msg2])
    )
    d = brain.decide(history=[("prospect", "I need chemistry help")])
    assert d.action is RouterAction.QUOTE
    assert d.leaf == "tutoring/science/chemistry"
    assert d.quoted_amount == 80.0
    assert d.slots.get("subject") == "chemistry"


def test_openai_brain_premature_quote_is_gated():
    # Model tries to quote before knowing the subject; the tool returns NOT_READY and the
    # model then asks. The engine-side gate prevents a price with no leaf (R5b/R6).
    msg1 = SimpleNamespace(
        content="", tool_calls=[_tool_call("1", "quote_price", "{}")]
    )
    msg2 = SimpleNamespace(content="Sure — which subject do you need help with?", tool_calls=None)
    brain = OpenAIBrain(
        Settings(_env_file=None, openai_api_key="sk-x"), client=_FakeClient([msg1, msg2])
    )
    d = brain.decide(history=[("prospect", "How much is tutoring?")])
    assert d.action is RouterAction.ASK
    assert d.leaf is None
    assert d.quoted_amount is None
