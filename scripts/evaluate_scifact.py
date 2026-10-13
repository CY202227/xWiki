"""Evaluate document retrieval on the official BEIR SciFact corpus.

Directly index public title/abstract text into xWiki's SQLite retrieval schema.
No gold claims/qrels enter the index; no LLM is called. This does not evaluate
Wiki compilation, answer correctness, or citation entailment.
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import math
import platform
import sys
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from xwiki import XWikiConfig, XWikiService

OFFICIAL_MD5 = "5f7d1de60b170fc8027bb7898e2efca1"


def score(ranked, gold, k):
    relevant = [doc for doc in ranked[:k] if doc in gold]
    recall = len(relevant) / len(gold)
    dcg = sum(1 / math.log2(i + 2) for i, doc in enumerate(ranked[:k]) if doc in gold)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(gold))))
    return recall, dcg / ideal if ideal else 0.0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--live", action="store_true", help="also ask first 3 test queries using XWiki environment model settings")
    args = parser.parse_args()
    raw = args.archive.read_bytes()
    if hashlib.md5(raw).hexdigest() != OFFICIAL_MD5:
        raise ValueError("Archive does not match the official BEIR SciFact checksum")
    with zipfile.ZipFile(args.archive) as archive:
        corpus = [json.loads(line) for line in archive.read("scifact/corpus.jsonl").decode().splitlines()]
        queries = {str(item["_id"]): item["text"] for item in (json.loads(line) for line in archive.read("scifact/queries.jsonl").decode().splitlines())}
        qrels = {}
        for line in archive.read("scifact/qrels/test.tsv").decode().splitlines()[1:]:
            query_id, document_id, relevance = line.split("\t")
            if int(relevance) > 0:
                qrels.setdefault(query_id, set()).add(document_id)
    started = time.perf_counter()
    rows = []
    with tempfile.TemporaryDirectory(prefix="xwiki-scifact-") as root:
        config = XWikiConfig(workspace=root) if args.live else XWikiConfig(workspace=root, llm_api_key="", llm_base_url="", llm_model="offline")
        service = XWikiService(config)
        live_results = []
        with service.db.connection() as conn:
            for document in corpus:
                did = str(document["_id"])
                title, body = document.get("title", ""), document["text"]
                conn.execute("INSERT INTO xwiki_documents(document_id,source_path,raw_path,title,summary,status,created_at,updated_at) VALUES(?,?,?,?,?,'indexed',?,?)",
                             (did, "beir:" + did, "beir:" + did, title, body[:500], "dataset", "dataset"))
                conn.execute("INSERT INTO xwiki_pages(document_id,page_no,content) VALUES(?,1,?)", (did, body))
                conn.execute("INSERT INTO xwiki_fts(document_id,title,summary,raw_content) VALUES(?,?,?,?)", (did, title, body[:500], body))
            conn.commit()
        for query_id in sorted(qrels, key=int):
            ranked = [str(hit["document_id"]) for hit in service.query_documents(queries[query_id], limit=20)]
            gold = qrels[query_id]
            metrics = {f"recall@{k}": score(ranked, gold, k)[0] for k in (1, 5, 10, 20)}
            metrics["ndcg@10"] = score(ranked, gold, 10)[1]
            metrics["mrr@10"] = next((1 / (i + 1) for i, doc in enumerate(ranked[:10]) if doc in gold), 0.0)
            rows.append({"query_id": query_id, "gold_ids": sorted(gold), "ranked_ids": ranked, **metrics})
            if args.live and len(live_results) < 3:
                try:
                    answer = asyncio.run(service.ask(queries[query_id], backflow=False))
                    live_results.append({"query_id": query_id, "answer": answer["answer"], "citation_status": answer.get("citation_status", "not_generated"), "source_count": answer["source_count"]})
                except Exception as exc:
                    live_results.append({"query_id": query_id, "error_type": type(exc).__name__})
    keys = ("recall@1", "recall@5", "recall@10", "recall@20", "ndcg@10", "mrr@10")
    result = {"dataset": "BEIR/SciFact", "split": "test", "corpus_size": len(corpus), "query_count": len(rows),
              "source_url": "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scifact.zip",
              "archive_sha256": hashlib.sha256(raw).hexdigest(), "python": platform.python_version(),
              "mode": "raw-document retrieval; direct index; no wiki compilation; " + ("plus bounded live answer pilot" if args.live else "no LLM"),
              "retriever": "xWiki FTS5 AND then OR then LIKE; limit=20; summary=first 500 chars",
              "seconds": round(time.perf_counter() - started, 2),
              "metrics": {key: sum(row[key] for row in rows) / len(rows) for key in keys}, "queries": rows,
              "live_model_alias": config.llm_model if args.live else None, "live_answers": live_results,
              "live_limitations": "3 fixed queries, validates citation syntax only; not entailment or claim correctness; no Wiki compilation" if args.live else None}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key not in ("queries", "live_answers")}, indent=2))


if __name__ == "__main__":
    main()
