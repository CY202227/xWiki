"""Query API fallback tests."""

from __future__ import annotations

import asyncio


def test_query_fallback(service):
  response = asyncio.run(service.ask("什么是测试文档？"))
  assert response["question"] == "什么是测试文档？"
  assert "未配置 LLM key" in response["answer"]
  assert "evidence" in response
