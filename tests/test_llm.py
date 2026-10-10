"""Retry only transient failures and never sleep after the final attempt."""

import pytest
from types import SimpleNamespace

from xwiki.llm import XWikiLLM
from xwiki.config import XWikiConfig


def test_validation_errors_are_not_retried(monkeypatch):
    sleeps = []
    monkeypatch.setattr("time.sleep", sleeps.append)
    llm = XWikiLLM(XWikiConfig(llm_max_retries=3))
    calls = []

    def fail():
        calls.append(True)
        raise ValueError("invalid output")

    with pytest.raises(ValueError):
        llm._call_with_retries(fail)
    assert len(calls) == 1
    assert sleeps == []


def test_transport_retries_have_no_final_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr("time.sleep", sleeps.append)
    llm = XWikiLLM(XWikiConfig(llm_max_retries=3))
    calls = []

    def fail():
        calls.append(True)
        raise ConnectionError("offline")

    with pytest.raises(ConnectionError):
        llm._call_with_retries(fail)
    assert len(calls) == 3
    assert sleeps == [0.5, 1.0]


def test_json_provider_mode_keeps_system_first_and_validates_locally():
    from xwiki.maintenance import ReadPlan
    sent = []

    def create(**kwargs):
        sent.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='```json\n{"page_ids": []}\n```'))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    llm = XWikiLLM(XWikiConfig(llm_api_key="test", llm_structured_mode="json"))
    llm._client = client
    messages = [{"role": "system", "content": "Wiki维护"}, {"role": "user", "content": "资料"}]
    response = llm.structured(messages, ReadPlan)
    assert response.choices[0].message.parsed.page_ids == []
    assert [message["role"] for message in sent[0]["messages"]] == ["system", "user"]
    assert messages[0]["content"] == "Wiki维护"


def test_json_provider_mode_rejects_unknown_model_fields():
    from xwiki.maintenance import ReadPlan
    def create(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"page_ids": [], "delete_all": true}'))])
    llm = XWikiLLM(XWikiConfig(llm_api_key="test", llm_structured_mode="json"))
    llm._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with pytest.raises(ValueError):
        llm.structured([{"role": "user", "content": "资料"}], ReadPlan)
