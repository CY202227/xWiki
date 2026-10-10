"""Check evaluator document identity mapping and score denominators."""
import asyncio
import json
from pathlib import Path

from scripts.evaluate_wiki import evaluate


def test_gold_dataset_offline_scores_use_source_identity():
    dataset = json.loads((Path(__file__).parent / "fixtures/wiki_eval.json").read_text(encoding="utf-8"))
    report = asyncio.run(evaluate(dataset, live=False))
    assert report["metrics"]["hit_at_3"] == {"score": 1.0, "n": 6}
    assert report["metrics"]["reciprocal_rank"] == {"score": 1.0, "n": 6}
    assert report["metrics"]["answer_correct"] is None
    assert report["cases"][-1]["retrieved_titles"] == []


def test_gold_maintenance_plans_preserve_facts_and_reject_duplicates():
    from scripts.evaluate_maintenance import evaluate as evaluate_plans
    dataset = json.loads((Path(__file__).parent / "fixtures/maintenance_eval.json").read_text(encoding="utf-8"))
    report = asyncio.run(evaluate_plans(dataset))
    assert report["passed"] == report["total"], report["cases"]
