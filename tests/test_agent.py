import pytest

import src.agent as agent_module
from src.agent import SpamAgent, _FallbackGraph
from src.schemas import ClassifierResult, EmailMessage, SenderReport, SpamExplanation, Verdict


@pytest.mark.asyncio
async def test_agent_preserves_classifier_label_for_phishing_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = SpamAgent()
    email = EmailMessage(
        message_id="agent1",
        sender="scam@unknown.invalid",
        subject="Urgent password verify",
        body="Verify your password at http://login-example.xyz",
    )
    classifier = ClassifierResult(
        verdict=Verdict.phishing,
        confidence=0.96,
        class_probabilities={"safe": 0.04, "phishing": 0.88, "spam": 0.08},
        risk_score=0.88,
        model_name="test",
        signals=["credential request"],
    )

    class FakeGraph:
        async def ainvoke(self, _initial):
            return {
                "email": _initial["email"],
                "classifier": classifier.model_dump(mode="json"),
                "url_reports": [],
                "sender_report": SenderReport(
                    sender_domain="unknown.invalid",
                    trusted=False,
                    unknown=True,
                    signals=["unknown sender domain age"],
                ).model_dump(mode="json"),
                "risk_score": 0.7,
                "final_verdict": "suspicious",
            }

    agent.graph = FakeGraph()

    async def fake_explain(_email, _classifier, _urls, _sender):
        return SpamExplanation(
            verdict=Verdict.spam,
            risk_score=0.82,
            summary="Email co dau hieu phishing ro rang.",
            spam_signals=["credential request", "unknown sender domain age"],
            recommended_action="block_or_quarantine",
            raw={"source": "test"},
        )

    monkeypatch.setattr(agent.explainer, "explain", fake_explain)
    result = await agent.run(email)
    assert result.route == "agent"
    assert result.final_verdict == Verdict.spam
    assert result.metadata["classifier_label"] == "phishing"
    assert result.metadata["agent_backend"] in {"langgraph", "fallback"}


@pytest.mark.asyncio
async def test_agent_uses_langgraph_backend() -> None:
    """Verify the agent is using LangGraph when available, not the old FallbackGraph."""
    agent = SpamAgent()
    # If LangGraph compiled successfully, graph is not a _FallbackGraph instance
    assert not isinstance(agent.graph, _FallbackGraph), (
        "LangGraph should be available; agent should not fall back to sequential graph"
    )
    assert agent.metadata_backend_name() == "langgraph"


@pytest.mark.asyncio
async def test_fallback_graph_produces_valid_state() -> None:
    graph = _FallbackGraph()
    email = EmailMessage(message_id="fb1", sender="a@example.com", subject="Hello", body="normal message")
    initial = {
        "email": email.model_dump(mode="json"),
        "classifier": None,
        "url_reports": [],
        "sender_report": None,
        "risk_score": 0.0,
        "final_verdict": "safe",
    }
    state = await graph.ainvoke(initial)
    assert state["classifier"] is not None
    assert state["sender_report"] is not None
    assert state["final_verdict"] in {"safe", "suspicious", "spam", "phishing"}
    assert 0.0 <= state["risk_score"] <= 1.0
