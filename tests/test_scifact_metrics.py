import importlib.util
from pathlib import Path


def test_scifact_metrics_use_rank_and_multiple_gold_documents():
    spec = importlib.util.spec_from_file_location("scifact_eval", Path(__file__).resolve().parents[1] / "scripts" / "evaluate_scifact.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    recall, ndcg = module.score(["wrong", "a", "b"], {"a", "b"}, 2)
    assert recall == 0.5
    assert 0 < ndcg < 1
    assert module.score(["a", "b"], {"a", "b"}, 2) == (1.0, 1.0)
