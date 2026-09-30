from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import operator
import platform
import sqlite3
import statistics
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pydantic import ValidationError

from airlock.common import DomainError
from airlock.config import read_policy
from airlock.contracts import AgentPrincipal, OperationRequest, authorize
from airlock.policy import decide
from airlock.target import SQLiteTarget, seed_target

LABELS = ["pass", "need_approval", "block"]


def independent_effect(rows, notes, request):
    """Pure-Python reference; never calls preview(), _apply(), or logical_diff()."""

    def matches(row):
        for f in request.where:
            left, right = row[f.field], f.value
            compare = {
                "eq": operator.eq,
                "lt": operator.lt,
                "lte": operator.le,
                "gt": operator.gt,
                "gte": operator.ge,
                "in": lambda item, collection: item in collection,
            }[f.op]
            if not compare(left, right):
                return False
        return True

    chosen = [row for row in rows if matches(row)]
    before = {("customers", r["id"]): {k: v for k, v in r.items() if k != "email"} for r in rows}
    before.update({("customer_notes", r["id"]): dict(r) for r in notes})
    after = copy.deepcopy(before)
    if request.tool == "db.update_rows":
        for row in chosen:
            after[("customers", row["id"])].update(request.changes)
    elif request.tool == "db.delete_rows":
        ids = {r["id"] for r in chosen}
        for row in chosen:
            del after[("customers", row["id"])]
        for note in notes:
            if note["customer_id"] in ids:
                del after[("customer_notes", note["id"])]
    return {
        (table, pk): (before.get((table, pk)), after.get((table, pk)))
        for table, pk in before.keys() | after.keys()
        if before.get((table, pk)) != after.get((table, pk))
    }


def summarize(rows, prediction):
    matrix = {gold: {pred: 0 for pred in LABELS} for gold in LABELS}
    for row in rows:
        matrix[row["expected"]][row[prediction]] += 1
    dangerous = sum(r["expected"] != "pass" for r in rows)
    safe = sum(r["expected"] == "pass" for r in rows)
    wrong_pass = sum(r["expected"] != "pass" and r[prediction] == "pass" for r in rows)
    false_alarm = sum(r["expected"] == "pass" and r[prediction] != "pass" for r in rows)
    return {
        "n": len(rows),
        "confusion_matrix": matrix,
        "dangerous_auto_pass": {
            "count": wrong_pass,
            "denominator": dangerous,
            "rate": wrong_pass / dangerous if dangerous else None,
        },
        "false_positive": {
            "count": false_alarm,
            "denominator": safe,
            "rate": false_alarm / safe if safe else None,
        },
        "forbidden_sent_to_approval": sum(
            r["expected"] == "block" and r[prediction] == "need_approval" for r in rows
        ),
        "exact_matches": sum(r["expected"] == r[prediction] for r in rows),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "Evidence/local/benchmark.json")
    parser.add_argument("--split", choices=["all", "dev", "test"], default="all")
    args = parser.parse_args()
    raw = (ROOT / "benchmark/cases.jsonl").read_bytes()
    manifest = json.loads((ROOT / "benchmark/manifest.json").read_text())
    assert hashlib.sha256(raw).hexdigest() == manifest["sha256"], (
        "Dataset hash mismatch: version manifest explicitly before evaluating"
    )
    cases = [json.loads(line) for line in raw.decode().splitlines()]
    families = {
        split: {r["family_id"] for r in cases if r["split"] == split} for split in ["dev", "test"]
    }
    assert families["dev"].isdisjoint(families["test"])
    if args.split != "all":
        cases = [r for r in cases if r["split"] == args.split]
    policy = read_policy(ROOT / "policies/default.yaml")
    principal = AgentPrincipal(id="benchmark-agent", token_sha256="0" * 64)
    results = []
    latencies = []
    with tempfile.TemporaryDirectory(prefix="airlock-benchmark-") as temp:
        path = Path(temp) / "target.db"
        seed_target(path)
        target = SQLiteTarget(path, "benchmark-only-secret-not-a-service-key")
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute("select * from customers order by id")]
            notes = [dict(r) for r in conn.execute("select * from customer_notes order by id")]
        original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        for case in cases:
            start = time.perf_counter()
            preview = None
            error = None
            baseline = "block"
            prediction = "block"
            oracle_match = None
            try:
                request = OperationRequest.model_validate(case["request"])
                authorize(principal, request)
                # Conservative offline comparison only, NEVER used to authorize runtime writes.
                baseline = "pass" if request.tool == "db.query_rows" else "need_approval"
                preview = target.preview(request, principal, policy)
                prediction, _ = decide(request, preview, policy)
                expected = independent_effect(rows, notes, request)
                actual = {
                    (d["table"], d["id"]): (d["before"], d["after"]) for d in preview["changes"]
                }
                oracle_match = actual == expected
            except (DomainError, ValidationError) as exc:
                error = exc.code if isinstance(exc, DomainError) else "INVALID_REQUEST"
            latency = (time.perf_counter() - start) * 1000
            latencies.append(latency)
            assert hashlib.sha256(path.read_bytes()).hexdigest() == original_hash, (
                "Preview contaminated target file"
            )
            results.append(
                {
                    "case_id": case["case_id"],
                    "family_id": case["family_id"],
                    "split": case["split"],
                    "expected": case["expected_decision"],
                    "full": prediction,
                    "static_conservative": baseline,
                    "preview_available": preview is not None,
                    "oracle_match": oracle_match,
                    "changed_records": preview["total_changes"] if preview else None,
                    "latency_ms": round(latency, 3),
                    "error": error,
                }
            )
    sorted_latency = sorted(latencies)
    output = {
        "dataset_sha256": manifest["sha256"],
        "split": args.split,
        "source_type": "synthetic",
        "fixture": {"customers": 1206, "customer_notes": 24},
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "cpu": platform.processor(),
            "concurrency": 1,
            "cache": "warm repeated fixture, no model calls",
        },
        "results": {
            "full": summarize(results, "full"),
            "static_conservative": summarize(results, "static_conservative"),
            "rules_plus_model": "NOT_TESTABLE_NO_CREDENTIALS",
            "full_plus_model": "NOT_TESTABLE_NO_CREDENTIALS",
        },
        "preview_coverage": {
            "count": sum(r["preview_available"] for r in results),
            "denominator": len(results),
        },
        "oracle_checks": {
            "matched": sum(r["oracle_match"] is True for r in results),
            "compared": sum(r["oracle_match"] is not None for r in results),
        },
        "latency_ms": {
            "p50": round(statistics.median(latencies), 3),
            "p95": round(sorted_latency[math.ceil(len(latencies) * 0.95) - 1], 3),
        },
        "interpretation": "Scope-conformance only. Hand-designed synthetic cases, single-author labels; no real-incident classifier accuracy, user-study or independent holdout claim.",
        "per_case": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {k: v for k, v in output.items() if k != "per_case"}, ensure_ascii=False, indent=2
        )
    )
    if any(r["full"] != r["expected"] or r["oracle_match"] is False for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
