# XER Table & Field Reference

Companion to the p6-schedule-data skill. Field lists cover the analytically important columns, not every column P6 exports. Read the section for each table you're about to query or ingest.

Contents: [File structure](#file-structure) · [PROJECT](#project) · [PROJWBS](#projwbs) · [CALENDAR](#calendar) · [TASK](#task) · [TASKPRED](#taskpred) · [TASKRSRC & RSRC](#taskrsrc--rsrc) · [Activity codes](#activity-codes-actvtype-actvcode-taskactv) · [UDFs](#udfs-udftype-udfvalue) · [Other tables](#other-tables-youll-meet)

## File structure

```
ERMHDR  <version> <export date> <...> <user> <db> <...> <currency>
%T  PROJECT
%F  proj_id  fin_dates_id  ...          ← tab-separated field names
%R  389  ...                            ← tab-separated values, one row
%T  CALENDAR
...
%E
```

Parsing rules that bite:
- Fields are positional per the `%F` line of the current table — never hard-code positions; different P6 versions emit different field sets/orders.
- Memo fields (notebooks, `clndr_data`) may contain CR/LF; a robust parser reads records, not lines, or pre-cleans quoted segments.
- Dates are `YYYY-MM-DD HH:MM` local text; empty string = null. Numerics use `.` decimal separator regardless of locale.
- Detect encoding (BOM check → try UTF-8 → fall back to Windows-1252). Currency/symbols and accented names are where it breaks.

## PROJECT

| Field | Meaning / analytics use |
|---|---|
| `proj_id` | Surrogate PK; joins everything. Snapshot-local. |
| `proj_short_name` | Project code (business key across exports, alongside data date) |
| `last_recalc_date` | **Data Date** — the single most important field in the file |
| `plan_start_date` | Project planned start |
| `plan_end_date` | Must-finish-by constraint if set (drives negative float) |
| `scd_end_date` | Scheduled (calculated) finish — current forecast completion |
| `sum_data_date` | Data date at last summarisation (can differ from last_recalc_date) |
| `export_flag` | Which project(s) in a multi-project file were actually exported |
| `clndr_id` | Project default calendar |
| `critical_drtn_hr_cnt` | The "critical if TF ≤ X" threshold configured in P6 |
| `def_complete_pct_type` | Default percent-complete type for new activities |

Multi-project files: filter `export_flag = 'Y'` for the intended project(s); related "external" projects may be partially present.

## PROJWBS

| Field | Meaning |
|---|---|
| `wbs_id` / `parent_wbs_id` | Adjacency-list hierarchy (snapshot-local IDs) |
| `proj_id` | Owning project; the top node per project represents the project itself |
| `wbs_short_name` | WBS code segment (concatenate up the tree for full code) |
| `wbs_name` | Description |
| `proj_node_flag` | 'Y' on the project root node |
| `seq_num` | Sibling display order |
| `status_code` | WBS-level status |
| `anticip_start_date` / `anticip_end_date` | Anticipated dates (top-down placeholders — not CPM outputs) |

Flatten to `Level1..LevelN` + full-path columns at ingest; the durable WBS identity across snapshots is the full concatenated path/code, not `wbs_id`. Beware planners restructuring WBS between snapshots — trend joins on WBS need fuzzy/mapping handling.

## CALENDAR

| Field | Meaning |
|---|---|
| `clndr_id` | PK (snapshot-local) |
| `clndr_name` | Name (business key-ish; not guaranteed unique) |
| `clndr_type` | `CA_Base` (global), `CA_Project`, `CA_Rsrc` |
| `base_clndr_id` | Parent calendar exceptions derive from |
| `day_hr_cnt`, `week_hr_cnt`, `month_hr_cnt`, `year_hr_cnt` | **The hours-per-period settings used for day/week conversions** |
| `default_flag` | Default calendar marker |
| `clndr_data` | Nested-parentheses blob: workweek + exceptions |

`clndr_data` structure (all on one logical line):
```
(0||CalendarData()(
  (0||DaysOfWeek()(
    (0||1()())                                ← day 1 = Sunday, no shifts = non-working
    (0||2()((0||0(s|08:00|f|16:00)())))       ← Monday: one shift 08:00–16:00
    ... days 3–7 = Tue..Sat
  ))
  (0||VIEW(ShowTotal|Y)())
  (0||Exceptions()(
    (0||0(d|41519)())                         ← exception day; d|N is an Excel-style
    (0||1(d|41155)((0||0(s|08:00|f|12:00)())))  serial date. Empty () = non-working
  ))                                            holiday; nested s|f pairs = worked hours
))
```
Key facts: day numbering is 1=Sunday…7=Saturday; a day/exception with **no shift records is non-working**; `d|` serials convert as `DATE(1899-12-30) + N`; multiple shift pairs per day are allowed (compute daily hours by summing shift lengths). For hours→days conversion in reporting, `day_hr_cnt` is what P6 itself uses — parse `clndr_data` only when you need true working-day date math (e.g. recomputing float or working-day differences between dates).

## TASK

Identity & classification:

| Field | Meaning |
|---|---|
| `task_id` | Surrogate PK — snapshot-local, never a cross-export key |
| `task_code` | Activity ID — the business key (unique per project) |
| `task_name` | Activity name |
| `proj_id`, `wbs_id`, `clndr_id` | Owning project, WBS node, **activity calendar** |
| `task_type` | `TT_Task`, `TT_Rsrc`, `TT_Mile`, `TT_FinMile`, `TT_LOE`, `TT_WBS` |
| `status_code` | `TK_NotStart`, `TK_Active`, `TK_Complete` |
| `duration_type` | `DT_FixedDrtn`, `DT_FixedQty`, `DT_FixedRate`, `DT_FixedDUR2` (fixed duration & units) — matters for resource analytics, not date analytics |
| `complete_pct_type` | `CP_Drtn`, `CP_Phys`, `CP_Units` |
| `rsrc_id` | Primary resource |

Dates (see SKILL.md for the status-dependent validity matrix):
`early_start_date`, `early_end_date`, `late_start_date`, `late_end_date`, `act_start_date`, `act_end_date`, `restart_date`, `reend_date`, `rem_late_start_date`, `rem_late_end_date`, `target_start_date`, `target_end_date`, `expect_end_date`, `suspend_date`, `resume_date`, `create_date`, `update_date`.

Durations, float, progress:

| Field | Meaning |
|---|---|
| `target_drtn_hr_cnt` | Original duration (hours) |
| `remain_drtn_hr_cnt` | Remaining duration (hours; 0 when complete) |
| `total_float_hr_cnt` / `free_float_hr_cnt` | Floats (hours, activity calendar; null when unscheduled, na for completed) |
| `phys_complete_pct` | Physical % (only meaningful when `complete_pct_type='CP_Phys'`) |
| `act_work_qty` / `remain_work_qty` / `target_work_qty` | Labour units actual/remaining/budget |
| `act_equip_qty` / `remain_equip_qty` / `target_equip_qty` | Non-labour equivalents |
| `driving_path_flag` | On longest path as of last schedule run |
| `float_path` / `float_path_order` | Multiple Float Path results if MFP was run |
| `cstr_type`/`cstr_date`, `cstr_type2`/`cstr_date2` | Constraints (see SKILL.md codes) |
| `priority_type` | Levelling priority |
| `lock_plan_flag` | Planned dates locked |
| `auto_compute_act_flag` | Auto-compute actuals |
| `est_wt` | Estimation weight |

Derived columns every model should materialise: display Start/Finish (per SKILL.md rule), at-completion duration, hours-per-day (from calendar), duration/float in days, is-critical (explicit definition), is-LOE-or-summary flag, is-unscheduled flag, is-milestone flag.

## TASKPRED

| Field | Meaning |
|---|---|
| `task_pred_id` | Surrogate PK |
| `task_id` | **Successor** activity |
| `pred_task_id` | Predecessor activity |
| `proj_id` / `pred_proj_id` | Successor / predecessor projects (differ ⇒ external link) |
| `pred_type` | `PR_FS`, `PR_SS`, `PR_FF`, `PR_SF` |
| `lag_hr_cnt` | Lag in hours (negative = lead); denominating calendar per project scheduling option |
| `comments` | Relationship comment |
| `aref` / `arls` | Undocumented datetimes ≈ relationship early finish / relationship late start (see SKILL.md for RFF/RSFF derivation; validate before use; handle absence) |

For a cross-export durable relationship key use (`pred task_code`, `succ task_code`, `pred_type`) — and note P6 permits multiple relationships between the same pair with different types.

## TASKRSRC & RSRC

TASKRSRC (assignments): `taskrsrc_id`, `task_id`, `proj_id`, `rsrc_id`, `role_id`, quantities (`target_qty`, `act_reg_qty`, `act_ot_qty`, `remain_qty`), costs (`target_cost`, `act_reg_cost`, `act_ot_cost`, `remain_cost`), assignment dates (`target_start_date`, `target_end_date`, `act_start_date`, `act_end_date`, `restart_date`, `reend_date`), `cost_per_qty`, curve (`curv_id`). Assignment-level dates can differ from activity dates (lags/curves). Cost at completion = actual (reg+ot) + remaining.
RSRC: `rsrc_id`, `rsrc_short_name`, `rsrc_name`, `rsrc_type` (`RT_Labor`, `RT_Mat`, `RT_Equip`), `clndr_id`, `parent_rsrc_id` (hierarchy), `unit_id`.
Spread/time-phased data is **not** in a standard XER — periodised curves must be recomputed (calendar-aware spreading of quantities between assignment dates) or sourced from P6 directly.

## Activity codes (ACTVTYPE, ACTVCODE, TASKACTV)

- `ACTVTYPE`: code dictionaries — `actv_code_type_id`, `actv_code_type` (name), `actv_code_type_scope` (`AS_Global`, `AS_EPS`, `AS_Project`), `proj_id` when project-scoped.
- `ACTVCODE`: values — `actv_code_id`, `actv_code_type_id`, `short_name`, `actv_code_name`, `parent_actv_code_id` (values can be hierarchical), `seq_num`.
- `TASKACTV`: assignment bridge — `task_id`, `actv_code_type_id`, `actv_code_id`, `proj_id`.
Pivot one column per code type used in reporting (e.g. Area, Discipline, Responsibility). Same-named project-scoped types can exist in multiple projects with different IDs — resolve by (scope, name).

## UDFs (UDFTYPE, UDFVALUE)

- `UDFTYPE`: `udf_type_id`, `table_name` (which object the UDF attaches to — e.g. TASK, PROJWBS), `udf_type_name`/`udf_type_label`, `logical_data_type` (`FT_TEXT`, `FT_START_DATE`, `FT_END_DATE`, `FT_FLOAT`, `FT_INT`, `FT_MONEY`, `FT_STATICTYPE`...).
- `UDFVALUE`: `udf_type_id`, `fk_id` (the object's PK, e.g. `task_id`), `proj_id`, and one populated value column among `udf_text`, `udf_date`, `udf_number`, `udf_code_id`.
Filter by `table_name`, pivot by label, take the column matching the logical type. UDFs are the usual home of contract-specific attributes (e.g. compensation event references, location strings) — they're often the highest-value fields in the whole file for bespoke reporting.

## Other tables you'll meet

`SCHEDOPTIONS` (per-project scheduling options — retained logic, lag calendar setting, critical definition; read it before interpreting float), `CALENDAR`-linked `RSRCRATE` (resource prices), `PROJCOST`/`TASKFIN`/`TRSRCFIN` (financial periods, only if period actuals stored), `MEMOTYPE`/`TASKMEMO` (notebooks — memo minefield for parsers), `TASKPROC` (steps), `PHASE`/`ROLES`/`POBS` (org data). Ingest raw, model only what reporting needs.
