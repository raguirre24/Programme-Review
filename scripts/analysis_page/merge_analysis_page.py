"""Merge the Float, Duration and Constraint Analysis pages into one 'Analysis' page with Float | Duration | Constraint view
buttons.

The Float Analysis page (ea24ab599f13f4ea4572) survives as 'Analysis'. The content of the Remaining Duration Analysis
(97f7d216ba38e55033da) and Constraint Analysis (1eb7703c500eb2ba5a6c) pages moves onto it unchanged (same IDs and
coordinates), hidden until its view button is pressed; their header, project menu, update and WBS slicers and page
navigators duplicated the surviving page's own and are dropped with the pages. Each view keeps its own title, charts,
matrices and category slicer; the header, project menu, update slicer and synced WBS slicer are shared, and no view
filters another.

Page filters: Constraint counts milestones, so the page filter becomes TaskType_Classified in (Milestone, Activity) and
every Float and Duration data visual gets a visual-level TaskType_Classified = 'Activity' filter, as their pages had.
Moved visuals whose filter names already exist on the page get new, stable names.

Written files: the moved visuals, the Float view visuals that gain the Activity filter, the saved visibility of the
Duration and Constraint views, the view navigator, page.json (name, filters, interactions), the three view bookmarks
and their group, the scope and names of the surviving project-menu bookmarks, bookmarks.json and pages.json; the two
former pages and their four project-menu bookmarks are removed. Once the former pages are gone the moved visuals are
read from the merged page, so a re-run is idempotent.

Modes: --check compares with the report (exit 1 on difference), --output-dir writes a review copy outside the report,
--apply writes into the report (close Power BI Desktop without saving first). --definition points every mode at another
report definition folder, for example a scratch copy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
DEFINITION = ROOT / "Project Review - Programme (datalake).Report" / "definition"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"
PAGE = "ea24ab599f13f4ea4572"
PAGE_NAME = "Analysis"
DURATION_PAGE, CONSTRAINT_PAGE = "97f7d216ba38e55033da", "1eb7703c500eb2ba5a6c"
FORMER_PAGES = (DURATION_PAGE, CONSTRAINT_PAGE)
MENU_BOOKMARKS = {"9218d93701ca451431aa": "Open Project Menu - Analysis", "70b568f01f42cfebb6b7": "Close Project Menu - Analysis"}
FORMER_BOOKMARKS = ("dbbe1f1552457b289208", "f756559112979fc8347b", "4310153686a4d92c6613", "75858eb0aea26f8888e2")


def identifier(label: str) -> str:
    return hashlib.sha256(("analysis-page-merge-v1:" + label).encode()).hexdigest()[:20]


# Each view: page title, (milestone note), charts, matrices and category slicer.
FLOAT_VIEW = ["49e872ccee5ff973eea3", "84866ab77b4a247fc84b", "a443a42b6ed02244a6dc", "92a3e137070d4b221c37",
              "b2626bd96758358bf97e", "fd85806e21428c03cbe2"]
DURATION_VIEW = ["90274c44b981ead054c2", "88d7b628ca5bdd710039", "f0c9695069063ce1e7a5", "8d4942bbdcedd4a00594",
                 "c96df61f3fa0f6ec086c", "3d6eaba8af0d76028d95"]
CONSTRAINT_VIEW = ["2c9a96d5ea55dd693008", "5da707f9b0d8db0d2b6e", "ee988fbebaa08d8521b4", "7e92ee6a3b8c6b1c0b4d",
                   "51f3c27d80d54a9852a8", "85d9a29b54cb54003334", "fc64d8be0e0201a8612b", "0f6740cb8070910e7441",
                   "58211dc0ca774e65a107"]
TOGGLED = FLOAT_VIEW + DURATION_VIEW + CONSTRAINT_VIEW
MOVED = {DURATION_PAGE: DURATION_VIEW, CONSTRAINT_PAGE: CONSTRAINT_VIEW}
# Data visuals of the activity-only views (charts, matrices, category slicers; not the title and note shapes).
ACTIVITY_ONLY = FLOAT_VIEW[2:] + DURATION_VIEW[2:]
NAVIGATOR = "aa01viewnav000000001"
VIEWS = {
    identifier("float-bookmark"): ("Float", FLOAT_VIEW),
    identifier("duration-bookmark"): ("Duration", DURATION_VIEW),
    identifier("constraint-bookmark"): ("Constraint", CONSTRAINT_VIEW),
}
FLOAT_BOOKMARK = next(iter(VIEWS))
VIEW_GROUP = identifier("view-group")
# The former pages' header, project-menu and WBS visuals, mapped to the surviving page's own (for their interactions).
FURNITURE = {
    "1e421e9373372d0e598b": "55ded4e0371db3140703", "43278dd5dec86b7b1c93": "c22b2438bbd9d00fd0e1",
    "e7d3b3d0780c4c963302": "fba8bc780d88aab07dd2", "7aca20987b0fd3683fe1": "519501f73536aa481135",
    "b900eee48c68bb7c6eec": "55ded4e0371db3140703", "a53f78b03d9e2c2d8926": "c22b2438bbd9d00fd0e1",
    "66ad99319683c3868a64": "fba8bc780d88aab07dd2", "a08cadf59fb91cea1e57": "519501f73536aa481135",
}
TASK = "01 XER_TASK"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def rendered(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def expr(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def string(value: str) -> dict:
    return expr("'" + value.replace("'", "''") + "'")


def task_type_filter(name: str, values: list[str]) -> dict:
    return {
        "name": name,
        "field": {"Column": {"Expression": {"SourceRef": {"Entity": TASK}}, "Property": "TaskType_Classified"}},
        "type": "Categorical",
        "filter": {"Version": 2, "From": [{"Name": "0", "Entity": TASK, "Type": 0}], "Where": [{"Condition": {"In": {
            "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "0"}}, "Property": "TaskType_Classified"}}],
            "Values": [[{"Literal": {"Value": f"'{value}'"}}] for value in values]}}}]},
        "howCreated": "User",
    }


def view_navigator() -> dict:
    """Header buttons Float | Duration | Constraint, right of the logo; styled like the other pages' view buttons."""
    theme_colour = lambda index: {"solid": {"color": {"expr": {"ThemeDataColor": {"ColorId": index, "Percent": 0}}}}}  # noqa: E731
    return {
        "$schema": SCHEMA + "visualContainer/2.13.0/schema.json",
        "name": NAVIGATOR,
        "position": {"x": 200, "y": 20, "z": 22000, "height": 44, "width": 450, "tabOrder": 22000},
        "visual": {
            "visualType": "bookmarkNavigator",
            "objects": {
                "bookmarks": [{"properties": {"bookmarkGroup": string(VIEW_GROUP), "allowDeselectionBookmark": expr("false"),
                                              "selectedBookmark": string(FLOAT_BOOKMARK)}}],
                "fill": [{"properties": {"fillColor": theme_colour(9)}, "selector": {"id": "selected"}}],
                "layout": [{"properties": {"cellPadding": expr("2L")}}],
                "text": [{"properties": {"bold": expr("true")}, "selector": {"id": "default"}}],
            },
            "visualContainerObjects": {
                "title": [{"properties": {"show": expr("false"), "text": string("Analysis view")}}],
                "background": [{"properties": {"show": expr("false")}}],
                "visualHeader": [{"properties": {"show": expr("false")}}],
                "general": [{"properties": {"altText": string("Analysis view: Float, Duration or Constraint")}}],
            },
            "drillFilterOtherVisuals": True,
        },
    }


def view_bookmark(name: str, visual_types: dict[str, str]) -> dict:
    """Display-only: shows one view's visuals and hides the others, without touching data, filters or other visuals."""
    caption, shown = VIEWS[name]
    targets = sorted(TOGGLED)
    states = {}
    for visual_id in targets:
        single = {"visualType": visual_types[visual_id], "objects": {}}
        if visual_id not in shown:
            single["display"] = {"mode": "hidden"}
        states[visual_id] = {"singleVisual": single}
    return {
        "$schema": SCHEMA + "bookmark/2.1.0/schema.json", "displayName": caption, "name": name,
        "options": {"targetVisualNames": targets, "suppressData": True, "suppressActiveSection": True,
                    "applyOnlyToTargetVisuals": True},
        "explorationState": {"version": "1.0", "activeSection": PAGE, "sections": {PAGE: {"visualContainers": states}}},
    }


def interactions(page: dict, former: dict[str, dict]) -> list[dict]:
    """The surviving page's pairs, the former pages' pairs (header visuals mapped), and no filtering between views."""
    pairs: dict[tuple[str, str], str] = {}
    for document in [page, *former.values()]:
        for entry in document.get("visualInteractions", []):
            source, target = FURNITURE.get(entry["source"], entry["source"]), FURNITURE.get(entry["target"], entry["target"])
            if source != target:
                pairs.setdefault((source, target), entry["type"])
    views = [FLOAT_VIEW, DURATION_VIEW, CONSTRAINT_VIEW]
    for view in views:
        for other in views:
            if other is not view:
                for source in view:
                    for target in other:
                        pairs[(source, target)] = "NoFilter"
    return [{"source": source, "target": target, "type": kind} for (source, target), kind in pairs.items()]


def build() -> dict[Path, dict | None]:
    """Every file the merge writes; None removes a file or folder of a former page."""
    page_dir = DEFINITION / "pages" / PAGE
    page = read(page_dir / "page.json")
    former = {pid: read(DEFINITION / "pages" / pid / "page.json") for pid in FORMER_PAGES if (DEFINITION / "pages" / pid).exists()}
    outputs: dict[Path, dict | None] = {}

    visuals = {name: read(page_dir / "visuals" / name / "visual.json") for name in FLOAT_VIEW}
    for pid, names in MOVED.items():
        source = DEFINITION / "pages" / (pid if pid in former else PAGE) / "visuals"
        visuals.update({name: read(source / name / "visual.json") for name in names})
    # Filter names must stay unique on the page: rename a moved visual's filter whose name the page already uses.
    staying = [path.parent.name for path in page_dir.glob("visuals/*/visual.json") if path.parent.name not in DURATION_VIEW + CONSTRAINT_VIEW]
    taken = {f["name"] for name in staying for f in read(page_dir / "visuals" / name / "visual.json").get("filterConfig", {}).get("filters", [])}
    for name in DURATION_VIEW + CONSTRAINT_VIEW:
        for entry in visuals[name].get("filterConfig", {}).get("filters", []):
            if entry["name"] in taken:
                entry["name"] = identifier(f"{name}:{entry['name']}")
            taken.add(entry["name"])

    for name in TOGGLED:
        item = visuals[name]
        if name in FLOAT_VIEW:
            item.pop("isHidden", None)  # Float is the saved view.
        else:
            item["isHidden"] = True
        if name in ACTIVITY_ONLY:
            # Their pages filtered TaskType_Classified = 'Activity'; the merged page also admits Constraint's milestones.
            filters = item.setdefault("filterConfig", {}).setdefault("filters", [])
            if not any(f["field"].get("Column", {}).get("Property") == "TaskType_Classified" for f in filters):
                filters.append(task_type_filter(identifier(f"{name}:activity-only"), ["Activity"]))
        outputs[Path("pages") / PAGE / "visuals" / name / "visual.json"] = item

    outputs[Path("pages") / PAGE / "visuals" / NAVIGATOR / "visual.json"] = view_navigator()

    page["displayName"] = PAGE_NAME
    for entry in page["filterConfig"]["filters"]:
        if entry["field"]["Column"]["Property"] == "TaskType_Classified":
            entry["filter"] = task_type_filter(entry["name"], ["Milestone", "Activity"])["filter"]
    page["visualInteractions"] = interactions(page, former)
    outputs[Path("pages") / PAGE / "page.json"] = page

    visual_types = {name: item["visual"]["visualType"] for name, item in visuals.items()}
    for name in VIEWS:
        outputs[Path("bookmarks") / f"{name}.bookmark.json"] = view_bookmark(name, visual_types)
    for name, caption in MENU_BOOKMARKS.items():
        # Opening or closing the project menu must leave the selected view alone.
        path = Path("bookmarks") / f"{name}.bookmark.json"
        bookmark = read(DEFINITION / path)
        bookmark["displayName"] = caption
        bookmark["options"] = {"applyOnlyToTargetVisuals": True,
                               **{key: value for key, value in bookmark["options"].items() if key != "applyOnlyToTargetVisuals"}}
        outputs[path] = bookmark
    metadata = read(DEFINITION / "bookmarks" / "bookmarks.json")
    metadata["items"] = [entry for entry in metadata["items"] if entry.get("name") not in FORMER_BOOKMARKS]
    group = {"name": VIEW_GROUP, "displayName": "Analysis view", "children": list(VIEWS)}
    positions = [index for index, entry in enumerate(metadata["items"]) if entry.get("name") == VIEW_GROUP]
    if positions:
        metadata["items"][positions[0]] = group
    else:
        metadata["items"].append(group)
    outputs[Path("bookmarks") / "bookmarks.json"] = metadata
    for name in FORMER_BOOKMARKS:
        outputs[Path("bookmarks") / f"{name}.bookmark.json"] = None
    for pid in FORMER_PAGES:
        outputs[Path("pages") / pid] = None

    pages = read(DEFINITION / "pages" / "pages.json")
    pages["pageOrder"] = [name for name in pages["pageOrder"] if name not in FORMER_PAGES]
    if pages.get("activePageName") in FORMER_PAGES:
        pages["activePageName"] = PAGE
    outputs[Path("pages") / "pages.json"] = pages
    return outputs


def main() -> None:
    global DEFINITION
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--output-dir", type=Path)
    parser.add_argument("--definition", type=Path, help="Report definition folder to read and --apply to (default: the report)")
    args = parser.parse_args()
    production = DEFINITION
    if args.definition:
        DEFINITION = args.definition.resolve()
    outputs = build()
    destination = args.output_dir.resolve() if args.output_dir else DEFINITION
    if args.output_dir and (destination == production.parent or production.parent in destination.parents):
        raise ValueError("Review drafts must be outside the production report folder; use --apply for the merge.")
    changed = []
    for relative, value in outputs.items():
        path = destination / relative
        if value is None:
            if path.exists():
                changed.append(relative.as_posix() + " (removed)")
                if not args.check:
                    shutil.rmtree(path) if path.is_dir() else path.unlink()
            continue
        text = rendered(value)
        if not path.exists() or path.read_text(encoding="utf-8-sig") != text:
            changed.append(relative.as_posix())
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
    print(json.dumps({"result": "FAIL" if args.check and changed else "PASS", "page": PAGE, "changed": changed}, indent=2))
    if args.check and changed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
