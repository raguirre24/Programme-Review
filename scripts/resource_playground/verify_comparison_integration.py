"""Strict static checks for additive calendar comparison. Does not execute DAX."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
import verify_integration as base

PAGE = "4c53a34bba9dcc7f3e8c"
TABLE = "Scenario Comparison Calendar"
IDS = {name: hashlib.sha256(("resource-playground-comparison-v1:" + name).encode()).hexdigest()[:20]
       for name in ["selector", "selection-summary", "results", "finish", "status", "chart", "help", "view-navigation"]}
BOOKMARKS = ["3fc3d41f00865b324fc4", "e1c605698b0ada439b54"]


def canonical(expression):
    return "".join(re.findall(r'"(?:[^"]|"")*"|\'(?:[^\']|\'\')*\'|\S', expression))


def extract_measures(text):
    measures = {}
    for match in re.finditer(r"^\tmeasure '([^']+)'\s*=\s*(.*?)(?=^\t\tformatString:)", text, re.M | re.S):
        expression = match[2].strip()
        if expression.startswith("```") and expression.endswith("```"):
            expression = expression[3:-3].strip()
        measures[match[1]] = expression
    return measures


def validate_model(tables):
    measures = {m["name"]: m["expression"] for m in tables["Resource Scenario Measures"]["measures"]}
    assert len(measures) == 56 and {n for n in measures if n.startswith("Comparison ")} == base.COMPARISON_MEASURES
    original = subprocess.run(["git", "show", "HEAD:Project Review - Programme (datalake).SemanticModel/definition/tables/Resource Scenario Measures.tmdl"], cwd=base.ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    original_measures = {n: e for n, e in extract_measures(original).items() if n.startswith("Scenario ")}
    assert len(original_measures) == 48, "Original single-calendar measure inventory changed."
    assert all(canonical(measures[n]) == canonical(e) for n, e in original_measures.items()), "Existing single-calendar expressions changed."
    expected_columns = {"ProjectKey", "clndr_id_key", "IsCsvSource", "Calendar Name", "MonthUpdate", "Report Update Date", "Calendar", "Inspection Calendar"}
    assert {c["name"] for c in tables[TABLE]["columns"]} == expected_columns
    assert len(tables[TABLE]["calculatedPartitions"]) == 1
    source = tables[TABLE]["calculatedPartitions"][0]["expression"]
    assert "'Scenario Calendar'" in source and "'Scenario Date'" not in source and not re.search(r"\bCROSSJOIN\s*\(", source, re.I)
    for name in base.COMPARISON_MEASURES - {"Comparison Selection Summary"}:
        expression = measures[name]
        compact = canonical(expression)
        assert "COUNTROWS('Scenario Comparison Calendar')=1" in compact, (name, "one independent identity required")
        assert "HASONEVALUE('Project_Dimension'[ProjectKey])" in compact and "HASONEVALUE('CurrentDate'[UpdateDate])" in compact
        if name != "Comparison Calendar Identity":
            for column in ["ProjectKey", "clndr_id_key", "IsCsvSource"]:
                assert "'Scenario Calendar'[" + column + "]" in expression, (name, column)
        assert not re.search(r"REMOVEFILTERS\s*\(\s*'(Project_Dimension|CurrentDate)'", expression, re.I), (name, "must preserve secured scope")
        assert not re.search(r"\bSUMX?\s*\(", base.dax_code(expression), re.I), (name, "alternatives must not be added")
    for name in ["Comparison Finish Date", "Comparison Status"]:
        assert canonical("ISFILTERED('Scenario Comparison Calendar'[Inspection Calendar])") in canonical(measures[name])
    bounded = measures["Comparison Validation"]
    assert "[Scenario Finish Date]" not in bounded and "[Scenario Status]" not in bounded
    summary = measures["Comparison Selection Summary"]
    assert "COUNTROWS('Scenario Comparison Calendar')" in canonical(summary)
    assert "[Inspection Calendar]" in summary and "[Calendar]" in summary
    identity = canonical(measures["Comparison Calendar Identity"])
    assert canonical("NOT ISBLANK([Comparison Chart Quantity])") in identity, "Text tooltips must not add invalid series or empty chart periods."
    assert canonical("IF(Eligible && NOT UnsupportedMode, IF(NOT ISBLANK([Comparison Chart Quantity])") in identity, "Unsupported inverse-hourly-cap mode must exit before the tooltip evaluates chart quantity."
    for expression in ['[Scenario Selected Mode] = "Meet target date"', '[Scenario Selected Basis] = "Per working hour"', '[Scenario Selected Limit Mode] = "Daily limit"']:
        assert canonical(expression) in identity
    for column in ["ProjectKey", "clndr_id_key", "IsCsvSource"]:
        assert "SELECTEDVALUE('Scenario Comparison Calendar'[" + column + "])" in identity
    return {"measures": 56, "preserved_base_measures": 48, "comparison_measures": 8}


def projections(visual, role):
    return [p["field"] for p in visual["visual"]["query"]["queryState"][role]["projections"]]


def field_name(field):
    kind, data = next(iter(field.items()))
    return kind, data["Expression"]["SourceRef"]["Entity"], data["Property"]


def validate_report(report_root):
    page_root = report_root / "pages" / PAGE
    visuals = {p.parent.name: json.loads(p.read_text(encoding="utf-8-sig")) for p in (page_root / "visuals").glob("*/visual.json")}
    assert len(visuals) == 43 and set(IDS.values()) <= visuals.keys(), "Exact 35 existing plus eight comparison visuals required."
    selector, chart, results = (visuals[IDS[n]] for n in ["selector", "chart", "results"])
    assert [field_name(f) for f in projections(selector, "Values")] == [("Column", TABLE, "Calendar")]
    selection = selector["visual"]["objects"]["selection"][0]["properties"]
    for prop in ["singleSelect", "strictSingleSelect"]:
        assert selection[prop]["expr"]["Literal"]["Value"] == "false", "Comparison selector must allow multiple or cleared selections."
    assert chart["visual"]["visualType"] == "clusteredColumnChart"
    assert [field_name(f) for f in projections(chart, "Series")] == [("Column", TABLE, "Calendar")]
    assert [field_name(f) for f in projections(chart, "Y")] == [("Measure", "Resource Scenario Measures", "Comparison Chart Quantity")]
    assert [field_name(f) for f in projections(chart, "Tooltips")] == [("Measure", "Resource Scenario Measures", "Comparison Calendar Identity")], "The measure-only tooltip role must expose the guarded full calendar identity."
    assert chart["visual"]["query"]["queryState"]["Category"]["fieldParameters"] == visuals[base.CHART_VISUAL_ID]["visual"]["query"]["queryState"]["Category"]["fieldParameters"]
    assert [field_name(f) for f in projections(results, "Values")] == [
        ("Column", TABLE, "Inspection Calendar"),
        *(('Measure', 'Resource Scenario Measures', 'Comparison ' + suffix) for suffix in ['Required Rate', 'Target Remaining', 'Validation'])]
    assert results["visual"]["objects"]["total"][0]["properties"]["totals"]["expr"]["Literal"]["Value"] == "false"
    page = json.loads((page_root / "page.json").read_text(encoding="utf-8-sig"))
    interactions = {(r["source"], r["target"]): r["type"] for r in page["visualInteractions"]}
    for target in visuals.keys() - {IDS["results"]}:
        expected = "DataFilter" if target in {IDS["finish"], IDS["status"]} else "NoFilter"
        assert interactions.get((IDS["results"], target)) == expected, ("inspection row interaction", target)
    for target in visuals.keys() - {IDS["chart"]}:
        assert interactions.get((IDS["chart"], target)) == "NoFilter", ("comparison chart interaction", target)
    states = []
    for bookmark_id in BOOKMARKS:
        bookmark = json.loads((report_root / "bookmarks" / (bookmark_id + ".bookmark.json")).read_text(encoding="utf-8-sig"))
        options = bookmark["options"]
        assert options.get("suppressData") is True and options.get("suppressActiveSection") is True and options.get("applyOnlyToTargetVisuals") is True
        state = bookmark["explorationState"]["sections"][PAGE]
        assert set(state) == {"visualContainers"}
        assert all(set(v) <= {"singleVisual", "isHidden"} for v in state["visualContainers"].values()), "Display bookmarks must not capture filters or highlight selections."
        assert "filter" not in json.dumps(state).lower()
        states.append(state)
    assert states[0] != states[1], "Single and Compare must have different display states."
    reset = json.loads((report_root / "bookmarks" / (base.RESET_BOOKMARK_ID + ".bookmark.json")).read_text(encoding="utf-8-sig"))
    expected_targets = base.RESET_TARGET_IDS | {IDS["selector"], IDS["results"]}
    assert set(reset["options"]["targetVisualNames"]) == expected_targets and len(reset["options"]["targetVisualNames"]) == 14
    reset_states = reset["explorationState"]["sections"][PAGE]["visualContainers"]
    assert reset_states[IDS["results"]]["highlight"] == {"selection": []}
    filters = reset_states[IDS["selector"]]["filters"]["byExpr"]
    assert len(filters) == 1 and "filter" not in filters[0]
    assert filters[0]["expression"]["Column"]["Property"] == "Calendar"
    return {"visuals": len(visuals), "selector": IDS["selector"], "results": IDS["results"], "display_bookmarks": 2, "reset_targets": 14}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", type=Path, default=base.MODEL)
    parser.add_argument("--report-root", type=Path, default=base.REPORT)
    parser.add_argument("--tom-directory")
    args = parser.parse_args()
    metadata = base.read_metadata(args.model_root, args.tom_directory)
    result = validate_model({table["name"]: table for table in metadata["tables"]})
    result.update(validate_report(args.report_root))
    print(json.dumps({"result": "PASS", **result, "scope": "Static source/report checks; no DAX execution, rendering or runtime RLS."}, indent=2))


if __name__ == "__main__":
    main()
