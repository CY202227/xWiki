"""Structural lint smoke tests."""

from __future__ import annotations


def test_structural_lint_runs(service):
    report = service.run_structural_lint()
    assert "orphans" in report
    assert "stale_entities" in report
    assert "missing_pages" in report
