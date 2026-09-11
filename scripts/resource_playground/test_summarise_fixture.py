"""Consolidate explicitly supplied fixture runs without hiding earlier evidence."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path


def summarise(paths, equivalence_path, output):
    merged = {}
    history = []
    for path in paths:
        run = json.loads(path.read_text(encoding="utf-8-sig"))
        if run.get("marker") != "resource-playground-repair-20260911":
            raise ValueError(f"Unrecognised fixture run: {path}")
        for test in run["tests"]:
            merged[test["name"]] = dict(test, evidence=str(path))
        history.append({"path": str(path), "tests": len(run["tests"]), "pass": sum(t["status"] == "PASS" for t in run["tests"])})
    equivalence = json.loads(equivalence_path.read_text(encoding="utf-8-sig"))
    failed = [test for test in merged.values() if test["status"] != "PASS"]
    result = {
        "result": "PASS" if not failed and equivalence["result"] == "PASS" else "FAIL",
        "generatedUtc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "logicalTests": len(merged),
        "passed": sum(t["status"] == "PASS" for t in merged.values()),
        "assertions": sum(len(t.get("assertions", [])) for t in merged.values()),
        "executedQueryFragments": sum(len(t.get("fragments", [])) for t in merged.values()),
        "executedIndividualScalarQueries": sum(sum(f["name"] != "bundle" for f in t.get("fragments", [])) for t in merged.values()),
        "executedNativeGroupedQueries": sum("nativeRows" in t for t in merged.values()),
        "fixtureDatabase": equivalence["fixtureDatabase"],
        "sourceExpressionChecks": equivalence["checked"],
        "sourceMeasureSha256": equivalence["sourceMeasureSha256"],
        "runsInPrecedenceOrder": history,
        "failed": failed,
        "caseEvidence": [{"name": t["name"], "status": t["status"], "evidence": t["evidence"]} for t in merged.values()],
        "scope": "Actual DAX on synthetic sparse calendars; unaffected cases may use preserved prior-run evidence, with changed branches rerun on the final source.",
        "limits": [
            "The P1 fixture role proves filtering paths, not production email/permission matching or a Service identity.",
            "Some runs overlapped separate bounded chart diagnostics; timings are not isolated native page benchmarks.",
            "Native input editing, bookmark persistence and page rendering require separate Desktop checks.",
            "Initial failures and query-wrapper timeout evidence remain in their original diagnostic artifacts.",
        ],
    }
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ["result", "logicalTests", "passed", "assertions", "executedQueryFragments", "sourceExpressionChecks"]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, nargs="+", required=True)
    parser.add_argument("--equivalence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summarise(args.results, args.equivalence, args.output)
