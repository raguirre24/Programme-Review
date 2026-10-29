"""Read-only PBIR/reference checks for the Schedule Metrics page and its 10 drill-through routes.

TMDL is parsed formally by Validate-Live.ps1 using TOM. Here the declaration
index checks PBIR references, and a separate metadata check rejects mutually
exclusive static and dynamic measure formats that TOM deserialisation accepts.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

EXPECTED_DRILL_ROUTES = [
    (
        "4da217e10ae952b9b4a4",
        "Missing Logic",
        "SM Missing Logic Count",
        "SM Drill Missing Logic Header",
        "SM Drill Missing Logic Detail",
        ("status_code", "task_type", "SM Fail Missing Logic"),
    ),
    (
        "566c6f848f9c58ccae18",
        "Leads",
        "SM Leads Activity Count",
        "SM Drill Leads Header",
        "SM Drill Leads Detail",
        ("status_code", "task_type", "SM Fail Leads"),
    ),
    (
        "2dc1210d106d519e8c33",
        "Lags >5d",
        "SM Lags Activity Count",
        "SM Drill Lags Header",
        "SM Drill Lags Detail",
        ("status_code", "task_type", "SM Fail Lags"),
    ),
    (
        "a4aae77cfb0f528bb352",
        "Non-FS Relationships",
        "SM Non-FS Activity Count",
        "SM Drill Non-FS Header",
        "SM Drill Non-FS Detail",
        ("status_code", "task_type", "SM Fail Non FS"),
    ),
    (
        "4e84ddebb9405ac18f9d",
        "Hard Constraints",
        "SM Restrictive Primary Count",
        "SM Drill Restrictive Constraints Header",
        "SM Drill Restrictive Constraints Detail",
        ("status_code", "task_type", "cstr_type"),
    ),
    (
        "0ce34782f4f350ad83b5",
        "Out-of-Sequence",
        "Out Of Sequence Count",
        "SM Drill Out-of-Sequence Header",
        "SM Drill Out-of-Sequence Detail",
        ("status_code", "task_type", "SM Fail Out Of Sequence"),
    ),
    (
        "1650221e71f2522ca403",
        "Negative Float",
        "Task_Count_Negative_Float",
        "SM Drill Negative Float Header",
        "SM Drill Negative Float Detail",
        ("status_code", "task_type", "total_float"),
    ),
    (
        "381cf6286aea5f0a94f6",
        "Remaining Duration >44d",
        "Dur >44",
        "SM Drill Remaining Duration Header",
        "SM Drill Remaining Duration Detail",
        ("status_code", "task_type", "remaining_duration"),
    ),
    (
        "7a03ed9cacd75d91903e",
        "Date Integrity",
        "SM Invalid Dates Count",
        "SM Drill Date Integrity Header",
        "SM Drill Date Integrity Detail",
        ("status_code", "task_type", "SM Fail Invalid Dates"),
    ),
    (
        "68cba7045a475d22afb7",
        "Baseline Coverage",
        "SM Baseline Unmatched Activity Count",
        "SM Drill Baseline Coverage Header",
        "SM Drill Baseline Coverage Detail",
        ("status_code", "task_type", "SM Fail Baseline Coverage"),
    ),
]

EXPECTED_GUIDE_GRID_MEASURES = {
    "missing_logic": "XER Metrics[SM Missing Logic Count]",
    "leads": "XER Metrics[SM Leads Activity Count]",
    "positive_lags": "XER Metrics[SM Lags Activity Count]",
    "fs_relationships": "XER Metrics[SM Non-FS Activity Count]",
    "restrictive_constraints": "XER Metrics[SM Restrictive Primary Count]",
    "out_of_sequence": "XER Metrics[Out Of Sequence Count]",
    "negative_float": "XER Metrics[Task_Count_Negative_Float]",
    "long_remaining_duration": "XER Metrics[Dur >44]",
    "invalid_dates": "XER Metrics[SM Invalid Dates Count]",
    "baseline_coverage": "XER Metrics[SM Baseline Unmatched Activity Count]",
}


def unquote(name: str) -> str:
    return name[1:-1].replace("''", "'") if name.startswith("'") else name


def declarations(path: Path) -> tuple[str, set[str], set[str]]:
    text = path.read_text(encoding="utf-8-sig")
    table = re.search(r"^table (.+)$", text, re.MULTILINE)
    if not table:
        raise AssertionError(f"No table declaration in {path}")
    measures, columns = set(), set()
    pattern = r"^\t(measure|column) ('(?:[^']|'')+'|[^\s=]+)(?:\s*=|\s*$)"
    for kind, name in re.findall(pattern, text, re.MULTILINE):
        (measures if kind == "measure" else columns).add(unquote(name))
    return unquote(table.group(1).strip()), measures, columns


def conflicting_measure_formats(text: str) -> list[str]:
    """Return measures with both static and dynamic format properties.

    This checks measure metadata, not DAX evaluation. Property indentation must
    be one level below the measure; deeper DAX expression text is ignored.
    """
    conflicts = []
    measure = None
    measure_indent = 0
    properties: set[str] = set()

    def finish():
        if measure is not None and properties == {"formatString", "formatStringDefinition"}:
            conflicts.append(measure)

    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("///"):
            continue
        indent = len(line) - len(line.lstrip("\t "))
        indent_width = len(line[:indent].expandtabs(4))
        declaration = re.match(r"\s*measure ('(?:[^']|'')+'|[^\s=]+)\s*=", line)
        if measure is not None and indent_width <= measure_indent:
            finish()
            measure = None
        if declaration:
            measure = unquote(declaration.group(1))
            measure_indent = indent_width
            properties = set()
        elif measure is not None and indent_width == measure_indent + 4:
            prop = re.match(r"\s*(formatString\s*:|formatStringDefinition\s*=)", line)
            if prop:
                properties.add(re.split(r"\s*[:=]", prop.group(1))[0])
    finish()
    return conflicts


def validate_measure_formats(paths: list[Path]) -> int:
    conflicts = [f"{path.name}[{measure}]" for path in paths
                 for measure in conflicting_measure_formats(path.read_text(encoding="utf-8-sig"))]
    assert not conflicts, ("Desktop does not support both formatString and "
                           "formatStringDefinition on a measure: " + ", ".join(conflicts))
    return len(paths)


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def field_references(data):
    sources = {}
    for node in walk(data):
        if isinstance(node.get("From"), list):
            sources.update({x["Name"]: x["Entity"] for x in node["From"]
                            if "Name" in x and "Entity" in x})
    for node in walk(data):
        for kind, slot in (("Measure", 0), ("Column", 1)):
            field = node.get(kind)
            if not isinstance(field, dict) or "Property" not in field:
                continue
            ref = field.get("Expression", {}).get("SourceRef", {})
            entity = ref.get("Entity") or sources.get(ref.get("Source"))
            yield kind, slot, entity, field["Property"]


def validate_guide_policy(guide: dict) -> int:
    """Acceptance policy is fixed independently of the authored guide/model."""
    lower_five = {"direction": "lower", "target": .05, "limit": .10}
    expected = {
        "missing_logic": lower_five,
        "leads": {"direction": "lower", "target": 0, "limit": .01},
        "positive_lags": lower_five,
        "fs_relationships": {"direction": "higher", "target": .90, "limit": .80},
        "restrictive_constraints": lower_five,
        "negative_float": {"direction": "lower", "target": 0, "limit": .05},
        "long_remaining_duration": lower_five,
        "invalid_dates": {"direction": "lower", "target": 0, "limit": .01},
        "out_of_sequence": {"direction": "lower", "target": 0, "limit": .10},
        "baseline_coverage": {"direction": "higher", "target": .90, "limit": .60},
    }
    rows = {row["id"]: row for row in guide["rows"]}
    assert len(rows) == len(guide["rows"]) == 10, "Guide must retain exactly 10 rows: the ten scored checks"
    assert "date_alignment_count" not in rows, "Removed Date alignment guide entry remains"
    assert not {"high_float", "zero_float_count"} & set(rows), "Unscored float rows must not be presented"
    assert {key for key, row in rows.items() if row.get("scored")} == set(expected), "Guide must identify exactly ten scored checks"
    for key, bands in expected.items():
        assert rows[key].get("review_bands") == bands, f"Guide band contract differs: {key}"
        for band_field in ("green", "amber", "red"):
            assert str(rows[key].get(band_field, "")).strip(), f"Guide band text missing: {key}.{band_field}"
        grid_counts = rows[key].get("related_grid_counts", [])
        assert len(grid_counts) == 1 and grid_counts[0].get("measure") == EXPECTED_GUIDE_GRID_MEASURES[key], (
            f"Guide grid count binding differs: {key}"
        )
    policy = guide.get("score_policy", {})
    assert len(policy.get("scored_metric_ids", [])) == 10 and set(policy["scored_metric_ids"]) == set(expected), "Score policy membership differs"
    expected_policy = {
        "points": {"at_target": 1, "at_limit": 0, "between": "linear"},
        "aggregation": "mean_points/assessed_count",
        "overall_colour": {"green_min": .95, "amber_min": .75},
        "coverage": "separate_warning",
    }
    assert all(policy.get(key) == value for key, value in expected_policy.items()), "Guide score aggregation/severity/coverage policy differs"
    return len(expected)


def validate_failing_activities_table(table_visual: dict) -> None:
    projections = table_visual["visual"]["query"]["queryState"]["Values"]["projections"]
    expected_measures = [route[2] for route in EXPECTED_DRILL_ROUTES]
    assert len(projections) == 11, f"Failing-activities table must project UpdateDate + 10 scored checks, found {len(projections)}"
    first = projections[0]["field"].get("Column", {})
    assert first.get("Property") == "UpdateDate" and first.get("Expression", {}).get("SourceRef", {}).get("Entity") == "01 XER_TASK", (
        "First column of failing-activities table must be 01 XER_TASK[UpdateDate]"
    )
    actual_measures = [
        p["field"].get("Measure", {}).get("Property")
        for p in projections[1:]
    ]
    assert actual_measures == expected_measures, f"Failing-activities table columns differ: {actual_measures}"
    assert all(
        p["field"].get("Measure", {}).get("Expression", {}).get("SourceRef", {}).get("Entity") == "XER Metrics"
        for p in projections[1:]
    ), "All 10 failing-activities table measures must bind to XER Metrics"


def validate_review_visuals(visuals: dict[str, dict]) -> None:
    validate_failing_activities_table(visuals["58fbc09d197fe53515d8"])
    # The former high-float panel now shows the scored out-of-sequence check.
    out_of_sequence = visuals["b472a4a2b0c50d6843ad"]["visual"]
    values = out_of_sequence["query"]["queryState"]["Y"]["projections"]
    assert [p["field"]["Measure"]["Property"] for p in values] == ["SM Out Of Sequence %"], "Out-of-sequence gauge binding changed"
    axes = out_of_sequence["objects"].get("axis", [])
    if isinstance(axes, dict):
        axes = [axes]
    assert any(axis.get("properties", {}).get("target", {}).get("expr", {}).get("Literal", {}).get("Value") == "0D"
               for axis in axes), "Out-of-sequence gauge must mark its 0% target"
    targets = out_of_sequence["objects"].get("target", [])
    if isinstance(targets, dict):
        targets = [targets]
    assert targets and all(t.get("properties", {}).get("show", {}).get("expr", {}).get("Literal", {}).get("Value") == "true"
                           for t in targets), "Out-of-sequence target marker must be visible"
    for identifier in ("81ad6771956ff5d1741f", "c7f71fd2e347b3f85c92"):
        for node in walk(visuals[identifier]):
            for key, value in node.items():
                if key in {"displayName", "Value"} and isinstance(value, str):
                    assert not re.search(r"checks?\s+passed", value, re.I), "Score caption still implies binary passed checks"
    expected_history = {
        "SM Out Of Sequence % (History)", "HighDur% (History)", "Lags% (History)",
        "<0Lead% (History)", "<0Float% (History)", "Constraint% (History)",
        "SM Missing Logic % (History)", "SM FS % (History)",
        "SM Invalid Dates % (History)", "Score (History)", "SM Detail History",
    }
    bound_history = []
    for data in visuals.values():
        visual = data.get("visual", {})
        if visual.get("visualType") == "lineChart":
            for projection in visual["query"]["queryState"]["Y"]["projections"]:
                bound_history.append(projection["field"]["Measure"]["Property"])
    assert len(bound_history) == 11 and set(bound_history) == expected_history, "History metric bindings changed"


def validate_drillthrough_and_retirements(report: Path, objects: dict) -> int:
    removed_pages = {"db92ae49184b6932662e", "061f748900951ae92ba9", "4f15f55676d2add4e922"}
    removed_bookmarks = {
        "35c2baadfa05e673110e", "d85911f94d2be6576068",
        "aae4df89fc5cb53b08d6", "b78ddd824cdcaae69b89",
    }
    page_dirs = {path.name for path in (report / "pages").iterdir() if path.is_dir()}
    page_index = json.loads((report / "pages/pages.json").read_text(encoding="utf-8-sig"))
    # 11 visible pages + 10 hidden Schedule Metrics drill-through pages = 21 pages.
    assert len(page_dirs) == 21 and not (removed_pages & page_dirs), "Removed page remains or retained page count differs"
    assert set(page_index["pageOrder"]) == page_dirs and len(page_index["pageOrder"]) == 21, "Page order is not the 21 retained pages"
    assert page_index.get("activePageName") in page_dirs, "Active page points to a removed page"
    for bmid in removed_bookmarks:
        assert not (report / "bookmarks" / f"{bmid}.bookmark.json").exists(), f"Retired bookmark file remains: {bmid}"
    removed = {
        ("XER Metrics", name) for name in (
            "DD Driving", "DataDate%", "DataDate% (History)",
            "SM Drill Date Alignment Header", "SM Drill Date Alignment Reason",
            "SM Drill Missing Predecessor Header", "SM Drill Missing Predecessor Flag",
            "SM Drill Missing Successor Header", "SM Drill Missing Successor Flag",
        )
    } | {("XER Measures", "ShowDriven")}
    for table, measure in removed:
        assert measure not in objects[table][0], f"Removed measure still declared: {table}[{measure}]"
    assert "Driven_DataDate" in objects["01 XER_TASK"][1], "Removing a report metric must not delete the source classification column"
    for col in (
        "SM Fail Missing Logic", "SM Fail Leads", "SM Fail Lags", "SM Fail Non FS",
        "SM Fail Out Of Sequence", "SM Fail Invalid Dates", "SM Fail Baseline Coverage",
    ):
        assert col in objects["01 XER_TASK"][1], f"Missing storage-engine failure column: 01 XER_TASK[{col}]"

    for path in report.rglob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        for kind, _, entity, prop in field_references(data):
            assert kind != "Measure" or (entity, prop) not in removed, f"Removed measure reference remains: {path}"
        for node in walk(data):
            for retired in removed_pages | removed_bookmarks:
                assert retired not in node, f"Retired ID {retired} retained as a key: {path}"
                assert retired not in node.values(), f"Retired ID {retired} reference remains: {path}"

    for pid, display_name, count_measure, header_measure, detail_measure, required_cols in EXPECTED_DRILL_ROUTES:
        pdir = report / "pages" / pid
        page = json.loads((pdir / "page.json").read_text(encoding="utf-8-sig"))
        assert page.get("displayName") == display_name, f"Drill-through page displayName differs: {pid}"
        assert page.get("visibility") == "HiddenInViewMode", f"Drill-through page must be hidden: {display_name}"
        assert page.get("type") == "Drillthrough", f"Drill-through page type missing: {display_name}"
        binding = page.get("pageBinding", {})
        params = binding.get("parameters", [])
        assert binding.get("type") == "Drillthrough" and len(params) == 1, f"Invalid drill-through pageBinding: {display_name}"
        bound_measure = params[0].get("fieldExpr", {}).get("Measure", {})
        assert (
            bound_measure.get("Expression", {}).get("SourceRef", {}).get("Entity") == "XER Metrics"
            and bound_measure.get("Property") == count_measure
        ), f"Drill-through binding measure differs on {display_name}"

        page_filters = page.get("filterConfig", {}).get("filters", [])
        filter_cols = set()
        for flt in page_filters:
            if not flt.get("filter"):
                continue
            assert "Column" in flt.get("field", {}), f"Non-column page filter predicate on {display_name}"
            col_entity = flt["field"]["Column"]["Expression"]["SourceRef"]["Entity"]
            col_prop = flt["field"]["Column"]["Property"]
            assert col_entity == "01 XER_TASK" and col_prop != "Is Unscheduled", (
                f"Disallowed page filter {col_entity}[{col_prop}] on {display_name}"
            )
            filter_cols.add(col_prop)
        for req_col in required_cols:
            assert req_col in filter_cols, f"Missing storage-engine filter {req_col} on {display_name}"

        matrices = []
        page_refs = set()
        for vpath in [pdir / "page.json", *(pdir / "visuals").glob("*/visual.json")]:
            vdoc = json.loads(vpath.read_text(encoding="utf-8-sig"))
            for kind, slot, entity, prop in field_references(vdoc):
                assert entity in objects and prop in objects[entity][slot], (
                    f"Missing {kind} {entity}[{prop}] in {vpath}"
                )
                if kind == "Measure":
                    page_refs.add((entity, prop))
            if vpath.name == "visual.json" and str(vdoc.get("visual", {}).get("visualType", "")).startswith("P6WBSMatrix"):
                matrices.append(vdoc)
        assert len(matrices) == 1, f"Expected one P6WBSMatrix on {display_name}"
        assert not matrices[0].get("filterConfig", {}).get("filters"), (
            f"P6WBSMatrix on {display_name} must not carry visual-level filters"
        )
        for required_helper in (count_measure, header_measure, detail_measure, "SM Drill Status", "SM Drill Context", "SM Drill Data Date", "SM Drill Source File"):
            assert ("XER Metrics", required_helper) in page_refs, (
                f"Drill-through page {display_name} missing helper XER Metrics[{required_helper}]"
            )
    return len(EXPECTED_DRILL_ROUTES)


def original_references(root: Path, path: Path):
    previous = subprocess.run(["git", "show", f"HEAD:{path.relative_to(root).as_posix()}"],
                              cwd=root, capture_output=True, text=True, encoding="utf-8")
    if previous.returncode:
        return set()
    return set(field_references(json.loads(previous.stdout)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    model = root / "Project Review - Programme (datalake).SemanticModel" / "definition"
    report = root / "Project Review - Programme (datalake).Report" / "definition"
    format_files_checked = validate_measure_formats(list(model.rglob("*.tmdl")))
    objects = {name: (measures, columns) for name, measures, columns in
               (declarations(path) for path in (model / "tables").glob("*.tmdl"))}
    drillthrough_routes = validate_drillthrough_and_retirements(report, objects)
    pages = [(path, json.loads(path.read_text(encoding="utf-8-sig")))
             for path in (report / "pages").glob("*/page.json")]
    matches = [(path, page) for path, page in pages
               if page.get("displayName", "").strip().casefold() in
               {"schedule metrics", "sched. metrics"}]
    assert len(matches) == 1, f"Expected one Schedule Metrics page, found {len(matches)}"
    page_path, page = matches[0]
    assert page.get("name") == "327b48a7fbd37ce0a51c", "Existing page identity changed"
    visual_paths = list((page_path.parent / "visuals").glob("*/visual.json"))
    assert visual_paths, "No page visuals found"
    scored_policy_checks = validate_guide_policy(json.loads(
        (root / "scripts/schedule_metrics/metric_guide.json").read_text(encoding="utf-8-sig")))
    validate_review_visuals({path.parent.name: json.loads(path.read_text(encoding="utf-8-sig"))
                             for path in visual_paths})
    metrics: dict[str, set[str]] = {}
    warnings = []
    gap_safe_trends = 0
    for path in [page_path, *visual_paths]:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        original = None
        for kind, slot, entity, prop in field_references(data):
            valid = entity in objects and prop in objects[entity][slot]
            if not valid:
                if original is None:
                    original = original_references(root, path)
                assert (kind, slot, entity, prop) in original, f"New missing {kind} {entity}[{prop}] in {path}"
                warning = f"Pre-existing reference: {entity}[{prop}] in {path.parent.name}"
                if warning not in warnings:
                    warnings.append(warning)
            if kind == "Measure" and entity == "XER Metrics":
                metrics.setdefault(prop, set()).add(path.parent.name)
        if path.name == "visual.json":
            pos = data.get("position", {})
            assert pos.get("width", 1) > 0 and pos.get("height", 1) > 0, f"Invalid size {path}"
            assert pos.get("x", 0) >= 0 and pos.get("y", 0) >= 0, f"Negative position {path}"
            assert pos.get("x", 0) + pos.get("width", 0) <= page["width"] + 1, f"Horizontal overflow {path}"
            assert pos.get("y", 0) + pos.get("height", 0) <= page["height"] + 1, f"Vertical overflow {path}"
            visual = data.get("visual", {})
            if visual.get("visualType") == "lineChart":
                category = visual["query"]["queryState"]["Category"]
                assert category.get("showAll") is True, f"Unknown periods would lose their category in {path}"
                axes = visual["objects"]["categoryAxis"]
                if isinstance(axes, dict):
                    axes = [axes]
                assert any(axis.get("properties", {}).get("axisType", {}).get("expr", {}).get("Literal", {}).get("Value")
                           == "'Categorical'" for axis in axes), f"Trend gap axis is not categorical in {path}"
                scope_filters = [flt for flt in data.get("filterConfig", {}).get("filters", [])
                                 if flt.get("field", {}).get("Measure", {}).get("Property") in
                                 {"SM History In Scope", "SM Detail History In Scope"}]
                assert len(scope_filters) == 1, f"Trend scope filter missing or duplicated in {path}"
                comparisons = [node["Comparison"] for node in walk(scope_filters[0]) if "Comparison" in node]
                assert any(c.get("ComparisonKind") == 0 and c.get("Right", {}).get("Literal", {}).get("Value") == "1L"
                           for c in comparisons), f"Trend scope must equal one in {path}"
                gap_safe_trends += 1
    histories = [name for name in metrics if name.endswith(" (History)")]
    for history in histories:
        base = history.removesuffix(" (History)")
        assert base in metrics, f"Trend {history} has no corresponding page metric"
    assert "Score" in metrics and "Score (History)" in metrics, "Score gauge/trend pair missing"
    assert gap_safe_trends == 11, f"Expected 11 trend configurations, found {gap_safe_trends}"
    print(json.dumps({"page": page["name"], "visuals": len(visual_paths),
                      "measure_references": len(metrics), "history_pairs": len(histories),
                      "gap_safe_trends": gap_safe_trends,
                      "scored_policy_checks": scored_policy_checks,
                      "drillthrough_routes": drillthrough_routes,
                      "report_pages": 21, "date_alignment_removed": True,
                      "measure_format_files_checked": format_files_checked,
                      "pre_existing_warnings": warnings, "status": "passed"}, indent=2))


if __name__ == "__main__":
    main()
