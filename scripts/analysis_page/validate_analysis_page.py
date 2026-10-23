"""Static checks for the merged Analysis page (Float | Duration | Constraint views, merge_analysis_page.py).

    python scripts/analysis_page/validate_analysis_page.py [--definition <report definition folder>]

Checks: the former Duration and Constraint pages and their project-menu bookmarks are gone; the page name, visual count
and page filters (TaskType_Classified in Milestone, Activity; Is Unscheduled = false); every Float and Duration data
visual keeps its TaskType_Classified = 'Activity' filter and no Constraint visual has one; the three view bookmarks
(same 21 targets, display only, each showing its own view), their group and the navigator default (Float); the saved
view (Float visible, Duration and Constraint hidden); no filtering between views; unique filter names on the page; the
scoped project-menu bookmarks; and parity with merge_analysis_page.py --check. Read-only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import merge_analysis_page as merge  # noqa: E402


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def task_type_values(entry: dict) -> list[str]:
    condition = entry["filter"]["Where"][0]["Condition"]["In"]
    return sorted(value[0]["Literal"]["Value"].strip("'") for value in condition["Values"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--definition", type=Path, default=merge.DEFINITION)
    definition = parser.parse_args().definition.resolve()

    pages = read(definition / "pages" / "pages.json")
    for pid in merge.FORMER_PAGES:
        assert pid not in pages["pageOrder"] and not (definition / "pages" / pid).exists(), f"Former page {pid} must be removed"
    for name in merge.FORMER_BOOKMARKS:
        assert not (definition / "bookmarks" / f"{name}.bookmark.json").exists(), f"Bookmark {name} of a removed page remains"
    page_dir = definition / "pages" / merge.PAGE
    page = read(page_dir / "page.json")
    assert merge.PAGE in pages["pageOrder"] and page["displayName"] == merge.PAGE_NAME

    page_filters = {f["field"]["Column"]["Property"]: f for f in page["filterConfig"]["filters"]}
    assert set(page_filters) == {"TaskType_Classified", "Is Unscheduled"}, f"Page filters changed: {sorted(page_filters)}"
    assert task_type_values(page_filters["TaskType_Classified"]) == ["Activity", "Milestone"], "Page must admit activities and milestones"
    unscheduled = page_filters["Is Unscheduled"]["filter"]["Where"][0]["Condition"]["In"]["Values"]
    assert unscheduled == [[{"Literal": {"Value": "false"}}]], "Is Unscheduled must stay false"

    visuals = {path.parent.name: read(path) for path in page_dir.glob("visuals/*/visual.json")}
    assert len(visuals) == 35, f"Expected 35 visuals (19 shared and Float, 6 Duration, 9 Constraint, 1 navigator), found {len(visuals)}"
    assert set(merge.TOGGLED) | {merge.NAVIGATOR} <= set(visuals)
    for name in merge.TOGGLED:
        filters = [f for f in visuals[name].get("filterConfig", {}).get("filters", [])
                   if f["field"].get("Column", {}).get("Property") == "TaskType_Classified"]
        if name in merge.ACTIVITY_ONLY:
            assert len(filters) == 1 and task_type_values(filters[0]) == ["Activity"], f"{name} must keep TaskType_Classified = 'Activity'"
        else:
            assert not filters, f"{name} must not filter TaskType_Classified"
    names = [f["name"] for v in visuals.values() for f in v.get("filterConfig", {}).get("filters", [])]
    assert len(names) == len(set(names)), "Filter names must be unique on the page"

    # Saved view: Float visible, Duration and Constraint hidden.
    assert all(not visuals[name].get("isHidden") for name in merge.FLOAT_VIEW + [merge.NAVIGATOR])
    assert all(visuals[name].get("isHidden") is True for name in merge.DURATION_VIEW + merge.CONSTRAINT_VIEW)

    states = []
    for name, (caption, shown) in merge.VIEWS.items():
        bookmark = read(definition / "bookmarks" / f"{name}.bookmark.json")
        options = bookmark["options"]
        assert bookmark["displayName"] == caption and sorted(options["targetVisualNames"]) == sorted(merge.TOGGLED)
        assert options.get("applyOnlyToTargetVisuals") is True and options.get("suppressData") is True and options.get("suppressActiveSection") is True
        state = bookmark["explorationState"]["sections"][merge.PAGE]["visualContainers"]
        assert "filter" not in json.dumps(state).lower(), f"View bookmark {caption} must not capture filters"
        visible = {visual for visual, value in state.items() if value["singleVisual"].get("display", {}).get("mode") != "hidden"}
        assert visible == set(shown), f"View bookmark {caption} shows the wrong visuals"
        states.append(json.dumps(state, sort_keys=True))
    assert len(set(states)) == 3
    groups = [item for item in read(definition / "bookmarks" / "bookmarks.json")["items"] if item.get("name") == merge.VIEW_GROUP]
    assert groups and groups[0].get("children") == list(merge.VIEWS), "The Analysis view group must hold Float, Duration, Constraint"
    navigator = visuals[merge.NAVIGATOR]["visual"]["objects"]["bookmarks"][0]["properties"]
    assert navigator["bookmarkGroup"]["expr"]["Literal"]["Value"] == f"'{merge.VIEW_GROUP}'"
    assert navigator["selectedBookmark"]["expr"]["Literal"]["Value"] == f"'{merge.FLOAT_BOOKMARK}'", "Analysis must open on Float"

    interactions = {(i["source"], i["target"]): i["type"] for i in page["visualInteractions"]}
    views = [merge.FLOAT_VIEW, merge.DURATION_VIEW, merge.CONSTRAINT_VIEW]
    for view in views:
        for other in views:
            if other is not view:
                for source in view:
                    for target in other:
                        assert interactions.get((source, target)) == "NoFilter", f"Views must not filter each other ({source} -> {target})"
    for name in merge.MENU_BOOKMARKS:
        options = read(definition / "bookmarks" / f"{name}.bookmark.json")["options"]
        assert options.get("applyOnlyToTargetVisuals") is True, f"{name} must apply only to the project menu visuals"
        assert not set(options["targetVisualNames"]) & set(merge.TOGGLED)

    check = subprocess.run([sys.executable, str(HERE / "merge_analysis_page.py"), "--check", "--definition", str(definition)],
                           capture_output=True, text=True, encoding="utf-8")
    assert check.returncode == 0, f"merge_analysis_page.py --check differs from the report:\n{check.stdout[-1500:]}"
    print(json.dumps({"status": "PASS", "page": merge.PAGE, "visuals": len(visuals), "views": [c for c, _ in merge.VIEWS.values()],
                      "activity_only_visuals": len(merge.ACTIVITY_ONLY), "merge_parity": "PASS"}, indent=2))


if __name__ == "__main__":
    main()
