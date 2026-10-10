"""Evidence review must fail closed and never trust citations alone."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from xwiki.evidence import EvidenceReview, ClaimDecision, UnsupportedClaimError, verify_operation
from xwiki.maintenance import PageOperation, PlanCitation


def operation(body="普通图书可借用31天。", quote="普通图书借阅期限为21天。"):
    return PageOperation(action="create", title="借阅", summary=body, body=body, reason="测试",
                         sources=["doc"], citations=[PlanCitation(document_id="doc", page_no=1, quote=quote)])


class Reviewer:
    def __init__(self, mode="reject"):
        self.mode, self.calls = mode, 0

    def structured(self, messages, response_model):
        self.calls += 1
        claims = json.loads(messages[-1]["content"])["claims"]
        decisions = [ClaimDecision(claim_id=c["id"], supported=self.mode != "reject",
                     evidence_ids=[99] if self.mode == "unknown" else c["evidence_ids"], reason="测试审查") for c in claims]
        if self.mode == "omit":
            decisions = []
        if self.mode == "duplicate":
            decisions += decisions[:1]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=EvidenceReview(decisions=decisions)))])


def test_verbatim_only_uses_no_model_call():
    reviewer = Reviewer()
    result = asyncio.run(verify_operation(reviewer, operation("普通图书借阅期限为21天。")))
    assert result["verbatim_only"]
    assert reviewer.calls == 0


@pytest.mark.parametrize("mode", ["reject", "omit", "duplicate", "unknown"])
def test_unsupported_or_malformed_decisions_never_pass(mode):
    reviewer = Reviewer(mode)
    with pytest.raises(ValueError):
        asyncio.run(verify_operation(reviewer, operation()))


@pytest.mark.parametrize("body,quote", [
    ("可以饮用。", "不可以饮用。"),
    ("28摄氏度时开启通风。", "超过28摄氏度时开启通风。"),
])
def test_substrings_cannot_remove_prohibition_or_condition(body, quote):
    reviewer = Reviewer()
    with pytest.raises(UnsupportedClaimError):
        asyncio.run(verify_operation(reviewer, operation(body, quote)))
    assert reviewer.calls == 1


def test_body_locator_must_match_declared_evidence():
    reviewer = Reviewer("support")
    with pytest.raises(ValueError, match="undeclared"):
        asyncio.run(verify_operation(reviewer, operation("结论 [other p.1]")))
    assert reviewer.calls == 0


def test_context_prevents_truncated_quote_from_reversing_negation():
    reviewer = Reviewer()
    with pytest.raises(UnsupportedClaimError):
        asyncio.run(verify_operation(reviewer, operation("可以饮用。", "可以饮用。"), ["雨水不可以饮用。"] ))
    assert reviewer.calls == 1


def test_model_cannot_use_evidence_from_a_different_inline_source():
    page = operation("普通图书可借用21天 [doc p.1]")
    page.citations.append(PlanCitation(document_id="second", page_no=1, quote="温室24度。"))
    class WrongSourceReviewer:
        def structured(self, messages, response_model):
            claims = json.loads(messages[-1]["content"])["claims"]
            review = EvidenceReview(decisions=[ClaimDecision(claim_id=claim["id"], supported=True,
                                    evidence_ids=[1], reason="误用另一个文档") for claim in claims])
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=review))])

    reviewer = WrongSourceReviewer()
    with pytest.raises(ValueError, match="evidence IDs"):
        asyncio.run(verify_operation(reviewer, page))


def test_unsupported_review_is_persisted_before_archive(service):
    from test_maintenance import prepare, Planner

    path = prepare(service)

    class RejectedPlanner(Planner):
        def structured(self, messages, response_model):
            if response_model is EvidenceReview:
                return Reviewer().structured(messages, response_model)
            return super().structured(messages, response_model)

    service.llm = RejectedPlanner()
    result = asyncio.run(service.maintain(limit=1))
    assert result["failed"] == 1
    task = service.maintenance_tasks()[0]
    assert task["status"] == "review"
    assert json.loads(task["review_json"])["decisions"]
    assert path.exists()
    assert list(service.workspace.paths.raw_dir.iterdir()) == []
    assert service.page_cards() == []
