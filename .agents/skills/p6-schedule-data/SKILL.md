---
name: p6-schedule-data
description: Understand and correctly analyse Oracle Primavera P6 schedule data — XER file structure, TASK/TASKPRED/PROJWBS/CALENDAR tables, data date semantics, hours-to-days conversion, float, driving logic, relationship free float (aref/arls), percent complete types, unscheduled-task detection, and cross-export key stability. Use this skill whenever the user mentions P6, Primavera, XER files, schedules, activities, CPM, float, data date, baselines, TASK/TASKPRED tables, or is building reports/pipelines (Power BI, SQL, Athena, Python) over scheduling data. Use it before writing ANY query or measure against P6 data — naive treatment of P6 fields produces plausible-looking wrong numbers.
---

# P6 Schedule Data

Primavera P6 data looks like ordinary relational data but is governed by CPM scheduling semantics. The three cardinal rules, before anything else:

1. **`task_id` is a database surrogate key, not a business key.** It identifies a row *within one database/export*. Across projects, databases, and re-imports it changes. The durable activity identity is **`task_code` (Activity ID) within a project** — and even that can be renumbered by planners. Any pipeline joining multiple exports/snapshots must join on `task_code` (+ a project/snapshot identifier), never raw `task_id`, and must handle renames explicitly.
2. **All durations and floats are stored in hours** (`*_hr_cnt` fields), and conversion to days depends on **the activity's own calendar** (`TASK.clndr_id` → `CALENDAR.day_hr_cnt`). Dividing everything by 8 is wrong the moment a project mixes 8h/10h/24h calendars — which real projects do. There is no single "hours per day" for a project.
3. **Every number is relative to the Data Date** (`PROJECT.last_recalc_date`). Remaining durations, floats, and early/late dates are forecasts from that date. Comparing measures across snapshots without carrying the data date alongside them is meaningless.

## XER file anatomy

- Tab-delimited text. Line prefixes: `ERMHDR` (file header: version, export date, user), `%T` table name, `%F` field list, `%R` data row, `%E` end of file.
- Encoding varies (often Windows-1252, sometimes UTF-8); memo/notebook fields can contain embedded newlines and tabs that break naive line parsers — use a parser that respects the `%R` record structure, and detect encoding rather than assuming.
- One file can contain multiple projects; global objects (calendars, resources, activity code types) come along with them. On import, global data can collide with/overwrite existing global data — a reason analytics pipelines should read the XER directly rather than round-tripping through another P6 database.
- Baselines are **not** included in an XER of the current project; a "baseline" arrives as a separate exported project. Snapshot-based pipelines therefore model each XER as (project × data date) and reconstruct baseline comparisons by joining snapshots on `task_code`.
- Calculated/display values you see in the P6 UI but not in the file (e.g. day-denominated durations, some percent completes, Longest Path per se) must be **recomputed** from stored fields — this skill tells you how.

## Core tables and how they join

```
PROJECT (proj_id) ─┬─< PROJWBS (wbs_id, parent_wbs_id, proj_id)   WBS hierarchy
                   ├─< TASK (task_id, proj_id, wbs_id, clndr_id)  activities
                   │      └── CALENDAR (clndr_id)                 hours/day + workweek
                   ├─< TASKPRED (task_pred_id, task_id=successor,
                   │             pred_task_id, pred_type, lag_hr_cnt)  relationships
                   ├─< TASKRSRC (taskrsrc_id, task_id, rsrc_id)   resource assignments
                   ├─< TASKACTV (task_id, actv_code_type_id, actv_code_id)  code assignments
                   └─< UDFVALUE (udf_type_id, fk_id)              user-defined fields
ACTVTYPE (actv_code_type_id) ─< ACTVCODE (actv_code_id)           activity code dictionaries
UDFTYPE (udf_type_id)                                             UDF dictionary
RSRC (rsrc_id)                                                    resources
```

- `TASKPRED.task_id` is the **successor**; `pred_task_id` the predecessor. `pred_type` ∈ `PR_FS`, `PR_SS`, `PR_FF`, `PR_SF`. `lag_hr_cnt` is in hours **on a calendar** (which calendar depends on the P6 scheduling option "Calendar for scheduling relationship lag" — commonly predecessor's; confirm the project's setting, don't assume).
- Cross-project links appear as rows where `pred_proj_id` ≠ `proj_id`; the external predecessor's TASK row may not be in your file. Handle the orphan case.
- WBS: `PROJWBS` is an adjacency list (`parent_wbs_id`); the project root node has the project itself as parent context. Flatten to a path/level structure for reporting (recursive CTE in SQL, List.Generate or self-merge in Power Query) and beware `seq_num` for sibling ordering.
- UDFs pivot: `UDFVALUE` rows attach to tasks (or other objects) via `fk_id` + `udf_type_id`, with the value in the type-appropriate column (`udf_text`, `udf_date`, `udf_number`, `udf_code_id`). Join to `UDFTYPE` for names; pivot only the UDFs you need.

## Activity semantics (TASK)

**Types** (`task_type`): `TT_Task` (task-dependent), `TT_Rsrc` (resource-dependent — uses resource calendars, not activity calendar, for work), `TT_Mile`/`TT_FinMile` (start/finish milestones — zero duration, only one date is meaningful), `TT_LOE` (level of effort — dates *derived from* linked activities; exclude from progress/float analysis or it distorts everything), `TT_WBS` (WBS summary — likewise derived, exclude).

**Status** (`status_code`): `TK_NotStart`, `TK_Active`, `TK_Complete`. This drives which date fields are real:

| Field pair | Not started | In progress | Complete |
|---|---|---|---|
| `act_start_date` / `act_end_date` | null / null | actual / null | actual / actual |
| `early_start_date` / `early_end_date` | forecast | ⚠ see below | typically null/frozen |
| `late_start_date` / `late_end_date` | backward pass | ⚠ | typically null/frozen |
| `restart_date` / `reend_date` | = early dates | **remaining** early start/finish (from data date) | null |
| `rem_late_start_date` / `rem_late_end_date` | = late dates | remaining late dates | null |
| `target_start_date` / `target_end_date` | current-plan ("planned") dates — NOT the project baseline | same | same |

The reporting-grade **Start** and **Finish** columns must be derived:
`Start = act_start_date if started else restart_date (fallback early_start_date)`;
`Finish = act_end_date if complete else reend_date (fallback early_end_date)`.
Never chart raw `early_*` alone: for in-progress activities the remaining-date fields carry the forecast. And `target_*` ("planned dates") are notorious: P6 can silently overwrite them on progressed activities depending on settings — treat real baselines as separate snapshot projects, not `target_*`.

**Constraints**: `cstr_type`/`cstr_date` (+ secondary `cstr_type2`/`cstr_date2`). Values like `CS_MSO` (start on), `CS_MSOB` (start on or before), `CS_MSOA` (on or after), `CS_MEO*` (finish equivalents), `CS_ALAP`, `CS_MANDSTART`/`CS_MANDFIN` (mandatory — these *override* logic and can make float misleading). Constraint prevalence is itself a schedule-quality metric (DCMA).

**Durations**: `target_drtn_hr_cnt` (original/planned), `remain_drtn_hr_cnt` (remaining), `total_drtn_hr_cnt` where present; at-completion = actual-to-date + remaining. Convert per-activity: `days = hr_cnt / CALENDAR.day_hr_cnt` of the **activity's** calendar.

**Percent complete is not one number.** `complete_pct_type` picks which one the UI shows: `CP_Drtn` (duration %: 1 − remaining/original... careful when original changes), `CP_Phys` (`phys_complete_pct`, manually entered), `CP_Units` (from resource actual vs at-completion units). Roll-ups must be weighted (typically by duration, budgeted units, or cost) — averaging activity percents is always wrong. Earned-value style progress: pick an explicit weight basis and state it.

## Float and driving logic

- `total_float_hr_cnt`, `free_float_hr_cnt`: hours, activity-calendar-denominated, only meaningful for unfinished activities, and undefined/na for completed ones. Negative total float = constrained/late against a constraint or project must-finish date.
- **"Critical" is a definition, not a fact**: TF ≤ 0 (or ≤ threshold), or Longest Path. The XER stores `driving_path_flag` on TASK (longest-path membership as of last schedule) — but only as-of the scheduling run in P6; recompute if you need certainty.
- Multiple calendars make float non-additive along a path; never sum floats.
- **Relationship-level float** (for driving-logic analytics without rerunning CPM): TASKPRED carries two undocumented datetime fields, `aref` and `arls` — best understood as **relationship early finish** and **relationship late start**. From these, with the successor's early dates:
  - Relationship Free Float ≈ (successor ES for FS/SS, successor EF for FF/SF) − `aref`, measured in working time on the **predecessor's** calendar; the same interval measured on the **successor's** calendar gives Relationship Successor Free Float (RSFF).
  - A relationship is **driving** when RSFF = 0 (no successor working time between lag-adjusted predecessor date and successor early date). Per successor, the minimum relationship float identifies the driving predecessor.
  - These fields are undocumented and absent from Oracle's official XER data map: validate against P6's displayed Relationship Free Float on a sample before trusting a build, and code defensively for their absence (older exports/tools may drop them).

## Detecting unscheduled / invalid tasks

Activities added after the last F9 (schedule calculation), or in never-scheduled projects, have **null CPM outputs while inputs exist**. Robust rule set (flag if any):
- `status_code = 'TK_NotStart'` and (`early_start_date` is null or `late_start_date` is null or `total_float_hr_cnt` is null)
- `status_code = 'TK_Active'` and (`reend_date` is null or `rem_late_end_date` is null)
- date pathologies: early > late with no negative-float explanation; finish < start; actuals after the data date (a progress-update quality error worth flagging separately).
Exclude flagged tasks from float/critical-path visuals and surface them on a QA page — silently including them skews mins/maxes and cumulative curves.

## Snapshot / time-series modelling (for Athena / warehouse / Power BI)

- Grain: one row per (`project`, `data_date`/snapshot, `task_code`). Carry `proj_id`+`task_id` as lineage columns only.
- Partition warehouse tables by snapshot date; every fact query filters to snapshot(s) first.
- Trend analysis (slippage, float erosion): self-join consecutive snapshots on `task_code`; classify added/deleted/renamed activities explicitly (deleted ≠ complete!).
- Store hours **and** the resolved per-activity `hours_per_day` at ingest so day conversions are stable even if calendars later change.
- Keep the raw XER (or raw parsed tables) immutable; derive analytics tables from them — scheduling semantics disputes (delay claims!) require going back to source.

## Quality checks worth automating (DCMA-14 aligned)

Missing predecessors/successors (dangling logic), leads (negative lag), lags, FS-relationship ratio, hard constraints, high float (> threshold), negative float, high duration, invalid dates (forecast before data date / actual after), resources on effort activities, missed activities vs baseline, critical-path integrity test. Each is a simple aggregate over TASK/TASKPRED once the semantics above are respected.

## Detailed field reference

For per-table, per-field detail (TASK, TASKPRED, PROJECT, PROJWBS, CALENDAR incl. `clndr_data` parsing, TASKRSRC, codes/UDFs), read `references/xer-table-reference.md` in this skill before writing ingestion code or wide queries.
