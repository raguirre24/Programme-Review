"""Read-only PBIR/reference checks for the existing Schedule Metrics page.

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
    lower_five = {"direction": "lower", "green_max": .05, "amber_max": .10}
    zero_one = {"direction": "lower", "green_max": 0, "amber_max": .01}
    expected = {
        "missing_logic": lower_five, "leads": zero_one,
        "positive_lags": lower_five,
        "fs_relationships": {"direction": "higher", "green_min": .90, "amber_min": .80},
        "restrictive_constraints": lower_five, "negative_float": zero_one,
        "long_remaining_duration": lower_five,
        "invalid_dates": {"direction": "lower", "green_max": 0, "amber_max": .001},
    }
    rows = {row["id"]: row for row in guide["rows"]}
    assert len(rows) == len(guide["rows"]) == 18, "Guide must retain exactly 18 rows after Date alignment removal"
    assert "date_alignment_count" not in rows, "Removed Date alignment guide entry remains"
    assert {key for key, row in rows.items() if row.get("scored")} == set(expected), "Guide must identify exactly eight scored checks"
    for key, bands in expected.items():
        assert rows[key].get("review_bands") == bands, f"Guide band contract differs: {key}"
    assert rows["high_float"].get("scored") is False, "High float must be explicitly excluded"
    assert not rows["high_float"].get("review_bands"), "High float must not imply a scored band"
    policy = guide.get("score_policy", {})
    assert len(policy.get("scored_metric_ids", [])) == 8 and set(policy["scored_metric_ids"]) == set(expected), "Score policy membership differs"
    expected_policy = {
        "points": {"green": 1, "amber": .5, "red": 0},
        "aggregation": "sum_points/assessed_count",
        "overall_colour": "worst_assessed_band",
        "coverage": "separate_warning",
    }
    assert all(policy.get(key) == value for key, value in expected_policy.items()), "Guide score aggregation/severity/coverage policy differs"
    return len(expected)


def validate_review_visuals(visuals: dict[str, dict]) -> None:
    high_float = visuals["b472a4a2b0c50d6843ad"]["visual"]
    query = high_float["query"]["queryState"]
    assert not query.get("TargetValue", {}).get("projections"), "High float still binds a target"
    axes = high_float["objects"].get("axis", [])
    if isinstance(axes, dict):
        axes = [axes]
    assert not any("target" in axis.get("properties", {}) for axis in axes), "High float still has a numerical target"
    targets = high_float["objects"].get("target", [])
    if isinstance(targets, dict):
        targets = [targets]
    assert targets and all(t.get("properties", {}).get("show", {}).get("expr", {}).get("Literal", {}).get("Value") == "false"
                           for t in targets), "High float target marker remains visible"
    for identifier in ("81ad6771956ff5d1741f", "c7f71fd2e347b3f85c92"):
        for node in walk(visuals[identifier]):
            for key, value in node.items():
                if key in {"displayName", "Value"} and isinstance(value, str):
                    assert not re.search(r"checks?\s+passed", value, re.I), "Score caption still implies binary passed checks"
    expected_history = {
        "HighFloat% (History)", "HighDur% (History)", "Lags% (History)",
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


def validate_removed_date_alignment(report: Path, objects: dict) -> None:
    removed_page = "db92ae49184b6932662e"
    page_dirs = {path.name for path in (report / "pages").iterdir() if path.is_dir()}
    page_index = json.loads((report / "pages/pages.json").read_text(encoding="utf-8-sig"))
    assert len(page_dirs) == 15 and removed_page not in page_dirs, "Removed page remains or retained page count differs"
    assert set(page_index["pageOrder"]) == page_dirs and len(page_index["pageOrder"]) == 15, "Page order is not the 15 retained pages"
    assert page_index.get("activePageName") in page_dirs, "Active page points to a removed page"
    removed = {
        ("XER Metrics", name) for name in (
            "DD Driving", "DataDate%", "DataDate% (History)",
            "SM Drill Date Alignment Header", "SM Drill Date Alignment Reason")
    } | {("XER Measures", "ShowDriven")}
    for table, measure in removed:
        assert measure not in objects[table][0], f"Removed measure still declared: {table}[{measure}]"
    assert "Driven_DataDate" in objects["01 XER_TASK"][1], "Removing a report metric must not delete the source classification column"
    for path in report.rglob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        for kind, _, entity, prop in field_references(data):
            assert kind != "Measure" or (entity, prop) not in removed, f"Removed measure reference remains: {path}"
        for node in walk(data):
            assert removed_page not in node, f"Removed page retained as a bookmark/state key: {path}"
            assert removed_page not in node.values(), f"Removed page reference remains: {path}"


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
    validate_removed_date_alignment(report, objects)
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
                      "report_pages": 15, "date_alignment_removed": True,
                      "measure_format_files_checked": format_files_checked,
                      "pre_existing_warnings": warnings, "status": "passed"}, indent=2))


if __name__ == "__main__":
    main()
