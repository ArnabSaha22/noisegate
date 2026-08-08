"""
Tests for the relevance floor and the routing that feeds it.

WHY THIS FILE EXISTS
Vector search cannot say "no" -- it always returns its nearest neighbours,
however distant. Asked for a cookie recipe this corpus returned passages about
restaurant ownership, and the LLM wrote a fluent answer from them.

The floor rejects context whose cross-encoder score is below a threshold derived
from measurement (see config.RELEVANCE_FLOOR). Two behaviours matter enough to
pin down in tests:

  1. It rejects irrelevant context and accepts relevant context.
  2. It FAILS OPEN. When reranking breaks, scores are None, and the floor must be
     skipped -- otherwise a FlashRank outage turns into "the agent refuses every
     question", which is far worse than a slightly weaker answer.

No network: search and reranking are both stubbed.
"""

import pytest

from app.agents.nodes import retriever as retriever_mod
from app.agents.nodes.retriever import retrieve_node
from app.config import settings

FLOOR = settings.RELEVANCE_FLOOR


def _state(query="how do I scale pods on cpu?"):
    return {
        "messages": [{"role": "user", "content": query}],
        "current_query": query,
        "documents": [],
        "plan": ["Start"],
        "status": "",
    }


@pytest.fixture
def stub(monkeypatch):
    """Replace vector search and reranking with controllable fakes."""
    def _apply(candidates, scored):
        monkeypatch.setattr(
            retriever_mod, "search_enterprise_key",
            lambda q, limit=15: [{"content": c, "source": "doc.md", "score": 0.5} for c in candidates],
        )
        monkeypatch.setattr(
            retriever_mod, "rerank_with_scores",
            lambda q, docs, top_n=5: scored,
        )
    return _apply


def test_relevant_context_is_kept(stub):
    stub(["hpa scales pods"], [("hpa scales pods", 0.98)])
    out = retrieve_node(_state())

    assert len(out["documents"]) == 1
    assert "hpa scales pods" in out["documents"][0]
    assert out["status"] == "Found Technical Context."


def test_irrelevant_context_is_rejected(stub):
    """A score below the floor must yield no documents at all."""
    stub(["restaurants are owner operated"], [("restaurants are owner operated", 0.00001)])
    out = retrieve_node(_state("best chocolate chip cookie recipe"))

    assert out["documents"] == [], "context below the floor must not reach the LLM"
    assert "relevant" in out["status"].lower()


def test_floor_boundary(stub):
    """Just above the floor passes; just below it does not."""
    stub(["borderline"], [("borderline", FLOOR * 1.1)])
    assert retrieve_node(_state())["documents"] != []

    stub(["borderline"], [("borderline", FLOOR * 0.9)])
    assert retrieve_node(_state())["documents"] == []


def test_fails_open_when_reranking_is_unavailable(stub):
    """
    Scores of None mean "we could not measure", not "irrelevant".

    If this ever inverts, a FlashRank failure silently becomes a total outage:
    every question refused, with retrieval that was actually working fine.
    """
    stub(["still useful text"], [("still useful text", None)])
    out = retrieve_node(_state())

    assert out["documents"] != [], "unscored context must be passed through, not rejected"


def test_empty_search_results_are_handled(stub):
    stub([], [])
    out = retrieve_node(_state())
    assert out["documents"] == []


def test_rejection_is_explained_in_the_plan(stub):
    """The trace should say why it declined -- the UI renders this live."""
    stub(["unrelated"], [("unrelated", 0.00001)])
    plan = retrieve_node(_state())["plan"]

    assert any("floor" in step.lower() for step in plan), (
        f"plan should record the floor decision, got {plan}"
    )


def test_responder_declines_instead_of_inventing_an_answer():
    """
    With no documents, the technical path must return a fixed refusal WITHOUT
    calling the LLM. Handing a model an empty context invites it to answer from
    training data -- ungrounded and unsourced, which is the whole failure the
    floor exists to prevent.
    """
    from app.agents.nodes.responder import generate_node

    out = generate_node({
        "messages": [{"role": "user", "content": "how do I bake cookies?"}],
        "current_query": "bake cookies recipe",   # not CONVERSATIONAL
        "documents": [],
        "plan": [],
        "status": "",
    })

    assert "don't have information" in out["final_answer"].lower()
    assert out["status"].lower().startswith("declined")
