# Workspace Architecture & AI Agent Developer Guide

This document describes the architectural layout, component interactions, data pipeline flow, and operational protocols for the **Programme Review (Datalake)** Power BI repository. 

> [!IMPORTANT]
> **AI AGENT MANDATORY UPDATE PROTOCOL**
> Any time an AI agent adds, modifies, refactors, or deletes any table, column, measure, report page, visual, script, or theme asset within this repository, **the AI agent MUST update this `ARCHITECTURE.md` file** so it remains 100% accurate and up to date.

---

## 1. High-Level Architecture Overview

This repository hosts a developer-mode Power BI Project (**PBIP**) that delivers Primavera P6 schedule and programme analytics built over an AWS Athena Data Lake backend.

```mermaid
flowchart TD
    subgraph Data Source Layer
        Athena[Amazon Athena Data Lake\n`primary_p6_bi_reporting`]
        P6[Primavera P6 XER Exports\n`prod_projectcontrols_p6`]
        SharePoint[SharePoint Online\nProgramme Review XER CSV bundles]
    end

    subgraph Semantic Model Layer TMDL
        MExpr[M Query Expressions\nAthena routing + validated CSV loader]
        Params[Nine required parameters\nportable source + project scope settings]
        Tables[Star Schema Tables & Dimensions\n61 TMDL tables, 40 relationships]
        Measures[DAX Measure Tables\n`XER Measures`, `XER  Counts`, `XER Metrics`, etc.]
        RLS[Role-Based Security\n`Project Access` RLS]
    end

    subgraph Report Layer PBIR
        ReportRoot[`Project Review - Programme (datalake).Report`]
        Pages[17 PBIR Report Pages\n14 visible + 3 drill-through]
        Bookmarks[44 Bookmarks JSON]
        Themes[JSON Theme Schemas\n`Contract_Theme.json`, `Target_Theme.json`]
        Backgrounds[Background Canvas Images\n`Contract.png`, `Target.png`]
    end

    subgraph Automation & Validation Scripts
        ThemeScript[`scripts/switch_theme.js`]
        PrefilterTest[`scripts/test_prefilter.py`]
        SchedMetrics[`scripts/schedule_metrics/`]
        ResPlayground[`scripts/resource_playground/`]
    end

    P6 --> Athena
    Athena -->|Native Query| MExpr
    Params --> MExpr
    SharePoint --> Tables
    MExpr --> Tables
    Tables --> Measures
    Tables --> RLS
    Measures --> Pages
    Themes --> ReportRoot
    Backgrounds --> ThemeScript
    ThemeScript -->|Inject Canvas BG| Pages
```

---

## 2. How This Works

### A. Data Source & Ingestion Layer
- **AWS Athena & Power Query M Integration**: Raw Primavera P6 schedule data (`.xer` file parses) resides in AWS Athena under database `primary_p6_bi_reporting` and schema `prod_projectcontrols_p6`.
- **Query Expressions (`expressions.tmdl`)**:
  - `AthenaDB`: Establishes native Amazon Athena database connection.
  - `AthenaScopeSql`: Filters narrow project metadata first, requires a named `dbo_project` match, prefers the complete J history over C separately for Contract/Target (except `CJ:6012`, which prefers `C6012` over `J6012`), then selects the latest baseline and subsequent updates. Numeric C/J aliases are considered together for registry eligibility/inclusion and excluded together for project exclusions/CSV ownership; other codes require an exact registry match. All eleven XER queries join this shared filename scope; TASK reuses its parsed fields. The load-disabled `AthenaProgrammeSelectionAudit` query exposes `NO_NAMED_PROJECT_MATCH` for rejected files. See [ATHENA_PROGRAMME_SELECTION.md](ATHENA_PROGRAMME_SELECTION.md) for lookup and date rules.
  - `fnAthenaSource`: Parameterised M function executing SQL against kept filenames in Athena.
  - `scripts/test_prefilter.py`: Extracts the current native SQL and checks common named-project eligibility and baseline-window selection across all eleven XER consumers: nine `fnAthenaSource` queries plus the TASK and `11_xer_calendar_detailed` native SQL. `CalendarAlignmentTests` executes table 11's dated-exception alignment vote (a day early, aligned, a day late, independent snapshots, scope fallback, weak or missing evidence, duplicate rules, invalid rows). Synthetic fixtures execute translated Trino SQL in DuckDB; they do not establish live Athena, Power Query, DAX or RLS acceptance.
  - `XerCsvRouting` & `XerCsvTableContracts`: `XerCsvRouting` computes case-insensitive SharePoint CSV project ownership and Athena C/J family exclusions; `XerCsvTableContracts` defines ordered columns, types, nullability and key rules for the eleven fallback tables. The current loader requires schema `5.0` only, including table 11's weekday rules and dated exceptions. Older bundles must be regenerated.
  - `XerCsvSelectedBundles`: Navigates SharePoint with `SharePoint.Contents` only through project folders explicitly named in `XerCsvProjectCodes`, ignores manifest-free staging folders, selects the newest project/programme folder, and validates that selected bundle with `fnXerCsvReadBundle`. An invalid newest bundle fails rather than falling back to an older folder.
  - `fnXerCsvReadBundle` and `XerCsvSelectedManifest`: Validate the selected small manifest and expose its matching files. The selected metadata is loaded into the hidden `XER CSV Manifest` audit table.
  - `fnXerCsvReadBundleTable` and `fnXerCsvLoadTable`: For each selected project, sums manifest `row_count` across all source snapshots for the requested table, streams the corresponding CSV, validates its data-row count after its header, then applies types and validates current compact keys without rewriting them. A mismatch raises contextual `XerCsvRowCount`; large CSV binaries and tables are not buffered. Table 11 bundles are also checked by `fnXerCsvValidateCalendarDetails`, then realigned with `fnXerCalendarDetectExceptionShift` and `fnXerCalendarApplyExceptionShift` (see `11 XER_CALENDAR_DETAILED`).
  - `XER CSV Refresh Audit`: Hidden calculated table that returns `PASS` or `DIAGNOSTIC_MISMATCH` for each of the eleven row-count records. It still fails refresh through `ERROR()` for Athena/CSV ownership overlap or a routed project missing from `dbo_project` or `dbo_userpermission`. Manifest content never grants RLS access.
  - **Parameters**:
    - `AthenaDsn`: Amazon Athena connection DSN; default `primary_p6_bi_reporting`.
    - `SharePointSite`: Required SharePoint site-root URL used by both external assets and CSV loading.
    - `SelectedProjects`: Overall report scope as a comma-separated list of project codes or `"ALL"`. **In Power BI Desktop, this parameter is kept to a reduced development subset (currently `"J5064, J5068"`) for fast local authoring; after publishing to the Power BI Service, it is changed to `"ALL"` so scheduled/service refreshes load the entire governed project portfolio.** Selecting either numeric C/J alias considers both and prefers J when available for the selected programme type (except `CJ:6012`, which prefers `C6012` over `J6012`). Athena-owned projects must have a named registry match even when explicitly selected; `ALL` does not bypass that check.
    - `ExcludedProjects`: Optional comma-separated list of project codes to exclude from the report scope (e.g. `"C6036, C5064"`), or blank / `"NONE"`. Automatically excludes both C and J aliases from Athena queries.
    - `SelectedProgrammeType`: Programme type code (`"C"` for Contract, `"T"` for Target, or `"ALL"`).
    - `XerCsvEnabled`: Logical opt-in; current default `false`.
    - `XerCsvProjectCodes`: Current CSV-source override as comma-separated routed project codes; current default `CNZ01`. Do not enter both C and J aliases for the same project.
    - `XerCsvLibrary`: Document library name; default `Documents`. Set it to the exact name exposed by `SharePoint.Contents` for `SharePointSite`.
    - `XerCsvRootFolder`: Path below the library; default `P6/XER CSV/Active`.

#### SharePoint XER CSV fallback

- **Ownership rule**: CSV routing is project-level. When active, Athena excludes both recognised C/J aliases of each currently routed project inside the native SQL scope; all eleven imported XER tables then append the selected CSV bundle data. A project cannot be owned by both sources. With `SelectedProjects = ALL`, `XerCsvProjectCodes` changes only current source ownership: `C6036` routes C6036 to CSV and every other project to Athena; switching it to `CNZ01` routes CNZ01 to CSV and returns C6036 to Athena when records exist; selecting `C6036,CNZ01` routes both to CSV and every other project to Athena. A former CSV project with no Athena records contributes zero rows without a routing error. With a finite selection, every CSV-routed project must remain inside `SelectedProjects`. When that finite list is entirely CSV-owned, all eleven XER Athena branches return typed empty tables without opening `AthenaDB`; governed RLS tables remain Athena-authoritative. Tables `04 XER_BASELINE` and `06a XER_SUCCESSOR` remain calculated model tables.
- **Inactive rule**: If `XerCsvEnabled = false` or `XerCsvProjectCodes` is blank, the loader returns typed empty tables and does not evaluate `SharePoint.Contents`. Stale CSV settings cannot block Athena-only refresh.
- **Folder contract**: `<XerCsvLibrary>/P6/XER CSV/Active/<PROJECT_CODE>/<PROJECT>_<C|T>_<yyyyMMddTHHmmssZ>_<hash8>/`. `SharePointSite` uses `Documents`, which is therefore the default `XerCsvLibrary`; if the selected site exposes a different connector name, set the library parameter to that exact name. Each project has its own exact uppercase parent folder, whose name must match `XerCsvProjectCodes` and manifest `project_code`; bundle CSVs must never be placed loose in that parent. Superseded bundles belong under `Archive/<PROJECT_CODE>/`. If `SelectedProgrammeType = ALL`, every routed project requires separate active C and T bundles beneath the same project folder. Project folders not listed in `XerCsvProjectCodes` and manifest-free staging folders are ignored. The contract-valid `bundle_id` timestamp selects the newest folder first, and that selected folder is then fully validated.
- **Required files**: `01_XER_TASK.csv`, `02_XER_PROJECT.csv`, `03_XER_PROJWBS.csv`, `06_XER_PREDECESSOR.csv`, `07_XER_ACTVTYPE.csv`, `08_XER_ACTVCODE.csv`, `09_XER_TASKACTV.csv`, `10_XER_CALENDAR.csv`, `11_XER_CALENDAR_DETAILED.csv`, `12_XER_RSRC.csv`, `15_XER_RESOURCE_DISTRIBUTION.csv`, and `XER_CSV_MANIFEST.csv`. A completed bundle may contain no other files or child folders.
- **CSV format**: UTF-8, comma-delimited, RFC-style CSV quoting, one exact ordered header row, ISO `yyyy-MM-dd` dates, invariant numbers, and lowercase `true`/`false`. Header-only optional tables are valid. Each data file uses one streaming conversion that validates its raw tokens while assigning model types.
- **Manifest contract**: Publication and loading require schema `5.0` only. Older and mixed-schema bundles are rejected. The manifest has one row for every canonical source XER × eleven table names. Per-source metadata must be identical across its eleven rows. The bundle contains exactly one baseline (`BLnn` with optional `-A` revision), unique snapshot tags, and updates tagged `YYMM`. Canonical names are `<PROJECT>-<C|T>-<TAG>_<YYYYMMDD>.xer`, with the suffix date equal to manifest `data_date`. For each imported table, Power Query sums its manifest counts across every source snapshot and blocks the table load when the CSV data-row count differs. Selected rows are also imported into hidden `XER CSV Manifest` for diagnostics.
- **Compact key contract**: Schema `5.0` relationship keys use `CSV::<project_code>::<programme_type>::<snapshot_tag>::<native_id>`. The loader validates this grammar and the manifest snapshot; it never rewrites legacy keys. The `::` delimiter is intentional: DAX `PATH` reserves vertical pipe and fails when an identifier contains `|`. Snapshot tags must be unique within a project/programme history. Cross-snapshot historical matching remains project + `task_code`; never use `task_id` across snapshots.
- **Source marker**: Each of the eleven imported XER tables has a hidden Boolean `IsCsvSource`; it is `true` for SharePoint rows and `false` for Athena rows. It supports refresh auditing and diagnostics and does not replace governed RLS.
- **Validation boundary**: The parser is authoritative for SHA-256 computation, duplicate-key detection and complete project/WBS/task/code/calendar/resource referential integrity before it writes `bundle_status=complete`. Power Query independently validates each selected folder/manifest identity, supported schema, exact files and headers, required values, strict tokens, types, project ownership, compact key syntax and per-table row count. The calculated audit keeps row-count reconciliation diagnostic while continuing to block ownership and governance failures. Power BI no longer rereads all eleven CSVs through `01 XER_TASK` to repeat parser validation.
- **Evaluation boundary**: Every imported table streams only its corresponding CSV. The small selected manifest can be evaluated independently by each loaded query because Power Query does not provide a shared cross-query cache. Do not add `Table.Buffer` or large-table `Binary.Buffer`; those buffers increase concurrent memory. `Binary.Buffer` is retained only inside validation of the small manifest.
- **Model-memory changes**: `Resource Calendar` derives its bounds from scalar minima/maxima instead of materialising a union of all resource rows. `06a XER_SUCCESSOR[Free Float]` is projected directly from `06 XER_PREDECESSOR`, and the near-unique `task_pred_id_key` is omitted from both stored model tables while remaining in the CSV file contract for parser validation.
- **Conditional future work**: Separate physical Athena/CSV partitions, aggregation or upstream `monthly_hours` changes for `15_XER_RESOURCE_DISTRIBUTION`, and upstream predecessor enrichment are not implemented. They require live VertiPaq/processing evidence, Desktop reopen/save proof and a matched Service result before adoption. The broader unused-column candidates remain stored until external thin-report/lineage dependencies are confirmed; only the specifically refactored `task_pred_id_key` has been removed and its local linguistic metadata cleaned.

#### Activation and refresh procedure

1. Generate and locally validate a complete schema `5.0` bundle. Under `Active`, create the matching `<PROJECT_CODE>` parent and exact parser-generated `<bundle_id>` child. Upload the eleven table CSVs first and `XER_CSV_MANIFEST.csv` last; folders without a manifest are ignored. Older bundles must be regenerated with the current parser before use or rollback.
2. Confirm the routed project (or its C/J alias) exists in `dbo_project` and has a project-specific entry in `dbo_userpermission`.
3. Confirm `AthenaDsn`, the single required `SharePointSite`, `XerCsvLibrary` and `XerCsvRootFolder`; then set `XerCsvProjectCodes` and enable `XerCsvEnabled`. Configure Athena and SharePoint Online credentials with `Organizational` privacy. A durable organisational/service account remains preferable for shared production refresh.
4. Reopen Power BI Desktop and run a full refresh. Verify `IsCsvSource`, compact keys, all eleven audit records, Athena-only, CSV-only and mixed ownership, baseline/previous-period logic, network links, codes, calendars, resources and RLS **View as**.
5. Publish to a test workspace, verify scheduled refresh and a real low-privilege RLS account, then run the matched performance experiment below. Switching `XerCsvProjectCodes` in the Service requires a standard whole-model **Refresh now** or enhanced refresh with `type=full`, `commitMode=transactional`, a low `maxParallelism` such as `2`, and no `objects`; object-only and `partialBatch` processing are unsupported for source switching. SharePoint Online normally needs no on-premises gateway; retain the established Athena connection/gateway path.
6. To replace a bundle, upload a newer completed v5 bundle beneath the same project folder, validate refresh, then move the older folder to `Archive/<PROJECT_CODE>`. To roll back, move the newest bundle to Archive, restore the required preceding completed v5 bundle from `Archive/<PROJECT_CODE>` to `Active/<PROJECT_CODE>`, and refresh. See the [SharePoint CSV setup guide](SHAREPOINT_CSV_SETUP.md) for the full operating procedure.

#### Refresh-performance acceptance

- Use the same Service capacity, parameters, bundles, credentials and comparable time window for every control. Use the median of two completed runs for CSV disabled, schema v5 CSV-only loading, and mixed Athena/CSV ownership.
- Where enhanced refresh is available, test transactional refresh with `maxParallelism` 6, 3 and 2. Capture wall duration, cumulative external-query time, total and M-engine CPU, total and M-engine peak memory, effective parallelism, VertiPaq rows, capacity throttling, data-source connection throttling and Athena query history. External-query time is cumulative across concurrent requests and can exceed wall time.
- Functional acceptance requires identical business row counts and values, no increase in VertiPaq rows, no audit error, `PASS` on all eleven diagnostic records and one table-data read per CSV table/bundle. Zero heavy XER Athena queries applies only when every project in a finite `SelectedProjects` list is CSV-owned; `SelectedProjects = ALL` deliberately retains the broad Athena workload for every non-routed project.
- Performance minimum: median wall duration no more than **40 minutes**. Target: **25 minutes or less**. M-engine peak no more than **0.938 GiB**. Total peak no more than **7.5 GiB**, with at least **20%** capacity headroom.
- Use `maxParallelism = 3` when it lowers peak memory by at least 15% with no more than a 10% wall-time penalty; otherwise retain the fastest setting that satisfies the memory and duration limits.

### B. Semantic Model Layer (TMDL Format)
- Location: `Project Review - Programme (datalake).SemanticModel/definition/`
- **Format**: **TMDL** (Tabular Model Definition Language) - plain-text, source-controlled definitions (`61` table TMDL files, `40` relationships, `1` RLS role).
- **Core Entity & Governance Tables**:
  - `01 XER_TASK`: Task activities, dates (`act_end_date`, `early_end_date`, `late_end_date`, `Finish`), duration, critical status, constraint types, variance categories. Calculated columns `Finish Without Exceptions` and `Calendar Delay Days` (display folder `Calendar Stretch`): the finish the remaining work would have on its calendar's own workweek without dated exceptions such as holidays, shutdowns and rostered days off (the wording avoids "normal week", which differs by calendar; the `CEILING(remaining_duration)`-th working day from `MAX(Start, data_date)` on `RELATED('10 XER_CALENDARS'[Workweek Mask])`, an O(1) closed form; dated exceptions ignored) and `MAX(0, Finish − Finish Without Exceptions)`, the calendar days holidays and shutdowns add. Both are blank for complete or non-Activity rows and unusable workweeks; as columns they give the Calendar Stretch Top-15 filter and KPIs storage-engine predicates instead of measure filters.
  - `02 XER_PROJECT`: Project-level metadata and settings.
  - `03 XER_PROJWBS`: Work Breakdown Structure hierarchy.
  - `04 XER_BASELINE`: Calculated baseline schedule snapshots (earliest `UpdateDate` per project/programme) for variance comparison.
  - `06 XER_PREDECESSOR` & `06a XER_SUCCESSOR`: Network logic links and dependencies.
  - `07 XER_ACTVTYPE`, `08 XER_ACTVCODE`, `09 XER_TASKACTV`: Activity code definitions and assignments.
  - `10 XER_CALENDARS`, `12_XER_RSRC`, `15_XER_RESOURCE_DISTRIBUTION`: Calendars, resource master, and resource distribution data.
  - `11 XER_CALENDAR_DETAILED`: Seven undated `Standard` weekday rules plus sparse dated exceptions for each scoped source calendar. The Athena feed stores dated exceptions one day early (found 2026-10; tables 06/15 were calculated correctly upstream), so the load realigns them. Its own native SQL votes per source file: P6 stores an exception only for a date whose hours differ from its weekday rule, so the alignment (as stored, a day later, a day earlier) that leaves the fewest exceptions repeating their weekday hours wins when it has at most half the runner-up's repeats and at least 10 fewer; otherwise the file takes the whole scope's vote, else 0. The vote reads only the source `day_of_week_num` and `work_hours`, so it does not depend on Athena's date typing. `fnXerCalendarApplyExceptionShift` then moves `date`, `day_of_week_num` and `day_of_week` together after typing, and the hidden `ExceptionDateShiftDays` column records the shift per row (+1, 0 or -1). CSV bundles run the same vote per bundle in M (`fnXerCalendarDetectExceptionShift`, no scope fallback). Already-correct sources stay unshifted, so an upstream fix needs no model change. Every consumer (Calendar Analysis, `Resource Scenario Measures`, `Scenario Calendar`) reads the realigned dates.
  - `10 XER_CALENDARS` hidden calculated column `Workweek Mask`: seven characters Monday to Sunday (`1` working, `0` non-working) from table 11's undated weekday rules, blank unless exactly one usable rule exists per weekday. The Calendar Analysis activity measures read it with `RELATED`.
  - `dbo_project`, `dbo_userpermission`, `Logos`, `XER CSV Manifest`, `XER CSV Refresh Audit`: Governance metadata, SharePoint branding assets, CSV manifest rows, and the calculated CSV refresh audit table.
  - `00 CALENDAR`, `00 PLANNED DATE TABLE (PV)`, `Resource Calendar`, `Monthly Resource Distribution Baseline`, `CurrentDate`, `UpdateHistory`, `Project_Dimension`: Dimension date tables, disconnected trend axis (`UpdateHistory`), and governed project lookup table (`Project_Dimension`).
  - `Schedule Metric Detail` & `Schedule Metric Guide`: Single-row detail-scope selector (`"Baseline coverage"`, hosting 19 `SM Detail *` measures) and hidden 14-row static `DATATABLE` generated from `scripts/schedule_metrics/metric_guide.json`.
  - `Filter_*` (11 disconnected/lookup slicer tables): `Filter_Activity_Status`, `Filter_Constraint_Types`, `Filter_Critical_Status`, `Filter_Driving`, `Filter_Duration`, `Filter_Finish_Delay`, `Filter_Finish_Within`, `Filter_Float`, `Filter_Start_Delay`, `Filter_Start_Within`, `Filter_TaskType`.
  - `Scenario *` (14 Resource Playground tables): `Scenario Date`, `Scenario Start`, `Scenario Target`, `Scenario Calendar`, `Scenario Comparison Calendar`, `Scenario Quantity`, `Scenario Quantity Scale`, `Scenario Rate`, `Scenario Rate Basis`, `Scenario Limit`, `Scenario Limit Mode`, `Scenario Mode`, `Scenario Period`, `Scenario Unit`.
- **Measure Tables**:
  - `XER Measures`: Core DAX measures for task calculations, plus 34 `CA *` measures (`displayFolder: Calendar Analysis`) for closed-form monthly calendar working/non-working day availability, workweek signatures, dated exception blackouts, and `O(1)` activity-level calendar stretch decomposition (`Remaining Working Days` vs `Remaining Calendar Days` = `Weekends / Off-Days` + `Holidays / Exceptions`; weekends/off-days count the calendar's own non-working weekdays from `RELATED('10 XER_CALENDARS'[Workweek Mask])` with a closed-form string formula, never the calendar name, and holidays/exceptions are the remaining non-working days, blank when the weekday rules are unusable; guarded by `COUNTROWS('01 XER_TASK') > 0` sparsity short-circuiting with zero bi-directional `CROSSFILTER`). The 12 activity-grain measures (8 stretch measures plus the `CA Activity Name` / `Calendar` / `Start` / `Finish` display measures) also AND in the hidden `CA Inspector Selection Match` gate, their only measure reference. The 6 day-count measures compute on each activity's own row inside `MAXX('01 XER_TASK', …)`; group-level `MIN`/`MAX`/`SUM` variables forced per-activity lookups (19 s against 0.3 s for 10,310 activities). The gate returns FALSE unless `CA Inspector Scope Ready` (exactly one project and one update, because `task_code` is unique only within a project snapshot), and `CA Inspector Title` then asks for a project. The monthly matrix colours each Working Days cell with `CA Monthly Working Days Colour` and `CA Monthly Working Days Font Colour`: grey with white text when `CA Monthly Active Activities` (the gate's month overlap, so a grey cell lists no activities) is 0, light red when any of those activities is critical (`CriticalStatus` "Critical", TF ≤ 0) and light orange when only near-critical ones are ("Near Critical", 0 < TF ≤ 10). The legend text box `ca25matxleg000000025` sits under the matrix. Because `Scenario Calendar` and `Scenario Date` have no relationship to `'01 XER_TASK'`, the gate re-applies a calendar or month selected in the summary table or matrix: a `TREATAS` on `calendar_id_key`, plus a month overlap of the remaining window (`MAX(Start, Data Date)` → `Finish`).
  - `XER Measures` also holds 16 `CS *` measures (`displayFolder: Calendar Stretch`) for the Calendar Stretch page. Five `CS Activity *` measures (calendar delay, effective start, finish without exceptions, ISO `Timeline Dates` and `Shutdown Bands` for Deneb) compute on row values inside `MAXX('01 XER_TASK', …)` behind `TaskRows > 0 && ISINSCOPE(task_code) && [CA Inspector Scope Ready]`; `Shutdown Bands` reads the activity's table-11 exceptions (as loaded) only for delayed rows and returns runs of 7+ consecutive non-working days. Five `CS KPI *` measures use `KEEPFILTERS` predicates on `Calendar Delay Days` (portfolio-safe, no scope gate). `CS Scope Prompt` subtitles the charts. The cliff-edge set (`CS Cliff Task Code` (hidden; the clicked activity, else the largest delay), `CS Cliff Finish Date` (hidden), `CS Cliff Finish Shift Days`, `CS Cliff Title`, `CS Cliff Callout`) evaluates, per `'Scenario Date'[Date]` within 60 days of the remaining start (BLANK outside, no visual filter), the finish if the remaining work started that day: closed-form weekday counts plus sparse exception deltas, the exception-free closed form when no delta precedes it, otherwise 13 unrolled bisection levels. The search stops at the scheduled finish + 400 days when the latest window start (remaining start + 60) still completes by then (a storage-engine reach test, identical for every axis date and so cached), which keeps the exception deltas few without changing any result; otherwise it runs to the axis end (for example cutover calendars with long embargoes). The callout evaluates the whole window in one pass over `'Scenario Date'` (as the chart does, sharing the date-independent work) and picks the latest earlier start that finishes 7+ days sooner and the earliest later start that finishes 7+ days later. The unrolled DAX is rendered by `scripts/calendar_analysis/stretch_dax.py`. The Deneb spec converts parsed dates to UTC timestamps (`time(utcParse(...))`) before adding a day: adding a number to a JavaScript `Date` concatenates text and left the timeline blank.
  - `XER  Counts`: Task, milestone, constraint, and logic count metrics (note double space in table name).
  - `XER Metrics`: Schedule health indicator metrics (`SM Score` and 10 scored checks with graduated points, plus legacy `Schedule Quality Score` and trend-by-update measures evaluated over `UpdateHistory[UpdateDate]` up to `CurrentDate`).
  - `XER S-Curve`: Cumulative baseline vs actual vs forecast curves.
  - `Resources`: Resource distribution and histogram measures.
  - `Dynamic Titles & Formatting`: Dynamic visual title strings and conditional formatting flags.
  - `WBS Measures` & `Activity Completion`: Dedicated WBS rollup and progress completion DAX.
  - `Resource Scenario Measures`: 66 measures (57 `Scenario *` + 9 `Comparison *`) for calendar-aware hypothetical resource allocation, inverse target rates, bounded finish search, validation, display wrappers, card formatting wrappers, and side-by-side calendar comparison.
- **Row-Level Security (RLS)**:
  - Role defined in `roles/Project Access.tmdl`. Filters `Project_Dimension` by evaluating UPN / email against `dbo_userpermission` for explicit project, state, or global permissions.

### C. Report Layer (PBIR Format)
- Location: `Project Review - Programme (datalake).Report/definition/`
- **Format**: **PBIR** (Power BI Report definition) - modern JSON-structured folder layout.
- **Page Management (`pages/pages.json`)**:
  - Lists 17 report pages (14 visible operational/analytical pages + 3 hidden drill-through pages) and sets the active/landing page (`2cc544dc10a1e237ae90` - `Home`):
    1. `2cc544dc10a1e237ae90`: `Home` (Visible, 17 visuals)
    2. `1351c9e89c045d35e160`: `Summary` (Visible, 22 visuals)
    3. `90b784e28b9f50741b0b`: `Programme` (Visible, 57 visuals)
    4. `349fceb1aa22881316d8`: `Gantt Chart` (Visible, 17 visuals)
    5. `60269a73141469b06603`: `Activity Completion Progress` (Visible, 22 visuals)
    6. `584ca37745f48e8b6958`: `Schedule Adherence Scorecard` (Visible, 23 visuals)
    7. `099895b98057d0135349`: `Resources` (Visible, 21 visuals)
    8. `4c53a34bba9dcc7f3e8c`: `Resource Simulator` (Visible, 50 visuals)
    9. `ca1da4a175154c398f01`: `Calendar Analysis` (Visible, 25 visuals, enforcing `Float Category <= 50` and incomplete status across all visuals with a `Max Total Float (<= 50d)` slider slicer; selecting a calendar in the Project Calendars Summary (`ca21calprof000000021`), or a row, month or cell in the Monthly Working Days matrix (`ca22calmatx000000022`), cross-filters the Activities by Calendar table (`ca23actinsp000000023`) through `CA Inspector Selection Match`; that table lists activities only when one project and one update are selected; matrix cells are light red for months with critical activities, light orange for near-critical only and grey for no activities, explained by a legend under the matrix)
    10. `csstretchpage0000001`: `Calendar Stretch` (Visible, 26 visuals, generated by `scripts/calendar_analysis/generate_stretch_page.py`; same page filters as Calendar Analysis but its cloned `Max Total Float` slider starts unrestricted; header, slicers (sync groups Project, State, last_recalc_date, Level_2) and project menu (bookmarks `cs91openbm0000000091`/`cs92closebm000000092`) cloned from Calendar Analysis; four KPI cards; a stacked `barChart` 'work vs wait' (working days / weekends and off-days / holidays and shutdowns) and a Deneb (Vega-Lite) delay timeline (dark bar to the finish without calendar exceptions, red calendar-driven delay, shutdowns drawn over the bars as pale dashed boxes), both limited to the Top 15 activities by `MAX('01 XER_TASK'[Calendar Delay Days])` with a TopN column filter plus `Calendar Delay Days > 0`; a `scatterChart` outlier finder (log working days against delay, coloured by `CriticalStatus`); and a stepped `lineChart` cliff-edge chart over `'Scenario Date'[Date]` with a word-wrapped `card` callout. Clicking an activity in the bars, timeline or scatter selects it for the cliff chart and callout; the cliff chart filters nothing; no visual has a measure filter)
    11. `eb4b0a43085cad901574`: `Cross-WBS Analysis` (HiddenInViewMode, 25 visuals)
    12. `327b48a7fbd37ce0a51c`: `Sched. Metrics` (Visible, 55 visuals)
    13. `ea24ab599f13f4ea4572`: `Float Analysis` (Visible, 19 visuals)
    14. `97f7d216ba38e55033da`: `Duration Analysis` (Visible, 19 visuals)
    15. `1eb7703c500eb2ba5a6c`: `Constraint Analysis` (Visible, 22 visuals)
    16. `4f15f55676d2add4e922`: `Missing Successor` (HiddenInViewMode, 12 visuals)
    17. `061f748900951ae92ba9`: `Missing Predecessor` (HiddenInViewMode, 12 visuals)
  - Each page folder contains `page.json` (page settings and canvas layout) and a `visuals/` subdirectory containing individual visual JSON definitions.
- **Bookmarks**:
  - `bookmarks/*.bookmark.json` defines 44 interactive state bookmarks (navigational toggles, panel switches, and visual state snapshots).

### Resource Playground (`Resource Calendars` Page)

- Page `4c53a34bba9dcc7f3e8c` (`Resource Calendars`) follows `Resources` and contains 50 native visuals (including the Single/Compare view toggle and Calendar Comparison visuals). Project and Monthly update are visible shared context controls; State is synchronised and hidden. Reset bookmark `e899bf3a9c2d243f33bf` affects only its 14 target visuals (`12` scenario inputs plus the comparison calendar slicer and comparison results table, with `applyOnlyToTargetVisuals: true`). Existing `Resources` visuals are unchanged.
- Uses `11 XER_CALENDAR_DETAILED` at its original weekday/exception grain. No calendar-by-date expansion is stored or evaluated across projects or updates. Measures sum weekday occurrences plus dated replacement corrections, with a daily cap applied before aggregation.
- Both `Scenario Calendar` and `Scenario Comparison Calendar` carry one calendar-selector row per project/key/source identity, inheriting `Project Access` through direct one-way `Project_Dimension` relationships and restricting to the selected update via one-way `CurrentDate` relationships. Report Update Date comes from a compact Task source/update mapping, preserving unused calendars in mapped sources and rejecting ambiguous mappings. Visible calendar labels contain only the name. There is no selector-to-calendar-fact relationship; `KEEPFILTERS` and `TREATAS` preserve the selected governed scope in each measure.
- One shared date axis (`Scenario Date`) and two date-input projections (`Scenario Start`, `Scenario Target`) cover the previous year through ten future years. Three bounded numeric-input tables total 300,003 rows across the entire model. Other option tables are small. Calendar count only affects the selector and existing table-11 rows.
- Finds finish from month-end checkpoints plus at most 31 daily probes (`Scenario Finish Date` and `Scenario Effective Start`), pre-computing the 7 weekday capacities and exception corrections once outside the probe loops. Query-time bounds enforce the data date (`Scenario Anchor Date`, falling back to `TODAY()` only when no single project/update is selected) through the full, unfiltered shared `Scenario Date` maximum, inclusive; there is no fixed twelve-month cap. Start/target text uses exact DD-MM-YYYY equality; invalid dates block calculation. Charts offer Week or Month, while daily detail includes every known permitted date. Invalid source data limits verified coverage instead of inventing availability.
- The 66 measures in `Resource Scenario Measures` (57 `Scenario *` + 9 `Comparison *` measures) include the original 48 core/display scenario measures, 8 core comparison measures, `Scenario Anchor Date`, and 9 `* Display` card text-formatting wrappers (`Scenario Target Quantity Display`, `Scenario Target Remaining Display`, `Scenario Finish Date Display`, `Scenario Effective Start Display`, `Scenario Working Days Display`, `Scenario Elapsed Days Display`, `Scenario Required Rate Display`, `Scenario Horizon Remaining Display`, `Comparison Finish Date Display`) that return `"—"` when unavailable; no target date is assumed when `Scenario Target` is unfiltered. Chart and daily-detail display measures suppress inactive rows without visual-level measure filters. A shared generator template computes the selected rate, seven weekday capacities and sparse exception corrections once per bucket and reuses them for its endpoints. This avoids repeated target-rate dependency expansion in native visual queries. The daily table remains independent of the chart period selector and omits unknown dates whose numeric results are blank; the status measure identifies the coverage boundary. Core allocation/endpoint measures retain their total and sparse-selection semantics within the permitted window. Arithmetic switches from exact fixed-decimal input matching to double precision before inverse-rate division.
- `scripts/resource_playground/generate_scaffold.py`, `generate_measures.py` and `generate_page.py` create review drafts through an explicit output directory and refuse deployed-file overwrites. Targeted integration preserves Desktop metadata and IDs. `verify_integration.py` and `verify_comparison_integration.py` use TOM/static checks to verify scenario and comparison expressions, bookmark reset targets, and projection contracts.
- The 11 September repair explicitly aliases the calendar selector's six output columns and replaces engine-rejected DAX variable names (`firstdate`, `lastdate`, `updates`, `key`, `ordinal`). All playground partitions are Ready in the reopened Desktop model. Tests build a separately marked source-free model, execute the production DAX against synthetic calendar rules and compare results with an independent oracle. Static TOM/M/report checks remain separate from this evidence.
- See [RESOURCE_PLAYGROUND.md](RESOURCE_PLAYGROUND.md) and [VALIDATION.md](scripts/resource_playground/VALIDATION.md) for inputs, bounds and current acceptance evidence. Native Performance Analyzer queries are retained for chart memory regression checks; a simpler query does not represent the native visual's query plan. Service publishing and restricted-account validation are separate release work.

### Schedule Metrics & Drill-Through Validation Suite (`scripts/schedule_metrics/`)

- Page `327b48a7fbd37ce0a51c` (`Sched. Metrics`, 55 visuals) and its two hidden drill-through pages (`Missing Predecessor` `061f748900951ae92ba9`, `Missing Successor` `4f15f55676d2add4e922`) evaluate 10 scored schedule-health checks (`1` point at target, `0` at limit, proportional between, averaged in `SM Score`) plus coverage diagnostics.
- `Is Unscheduled = false` is applied as a page-level filter on the other 14 operational pages and intentionally omitted from `Sched. Metrics`, `Missing Predecessor`, and `Missing Successor` so schedule quality checks evaluate the full eligible activity population.
- `Schedule Metric Guide` is a hidden 14-row static `DATATABLE` generated from `scripts/schedule_metrics/metric_guide.json` via `python scripts/schedule_metrics/build_metric_guide.py --content-only`.
- `scripts/schedule_metrics/validate_static.py` verifies TMDL/PBIR invariants offline; PowerShell scripts (`Validate-Live.ps1`, `Validate-ReviewBands.ps1`, `Validate-Detail-Loaded.ps1`, `Validate-Drillthrough.ps1`, `Validate-Guide.ps1`) verify live DAX evaluation and drill-through reconciliation against an open Power BI Desktop instance. See [scripts/schedule_metrics/README.md](scripts/schedule_metrics/README.md) and [scripts/schedule_metrics/IMPLEMENTATION.md](scripts/schedule_metrics/IMPLEMENTATION.md).

### D. Visual Theme & Canvas Background Subsystem
- **Themes (`Themes/`)**: Contains custom theme JSON definitions (`Contract_Theme.json` and `Target_Theme.json`).
- **Backgrounds (`Backgrounds/`)**: Canvas background graphics (`Contract.png`, `Target.png`).
- **Theme Switcher Script (`scripts/switch_theme.js`)**:
  - Node.js script that parses all `page.json` files and injects the corresponding canvas background image (`Contract.png` or `Target.png`) with 0% transparency and `'Fill'` scaling.
  - Usage: `node scripts/switch_theme.js contract` or `node scripts/switch_theme.js target`.

### E. Direct PBIP Publication

- `Project Review - Programme (datalake).pbip` is the single working project for editing, refreshing and publishing. No deployment copy or preparation script is required.
- The root project has been cleared of prior `.pbi/localSettings.json` Service bindings. Its first publication is therefore workspace-independent: a destination without matching items creates new items, while a destination with exactly one matching report and semantic model can offer an explicit **Replace** operation.
- After a successful publication, Desktop may recreate ignored `localSettings.json` files in the same root project. This is expected and lets subsequent publications from that PBIP update the same target directly. These machine-local bindings are never committed.
- Continue only when Desktop explicitly offers **Replace** for the expected same-name pair. Never delete, recreate or manually rename the existing Service items during replacement.
- In the Power BI Service dataset parameters, switch `SelectedProjects` from the local Desktop development subset to `"ALL"` (and configure `XerCsvEnabled` / `XerCsvProjectCodes` as required for production CSV routing) before running the full Service refresh.
- Record and then verify the report/model IDs, links, direct and Build access, RLS membership, app inclusion, audiences, refresh settings, gateway mapping, endorsement and labels.
- A PBIX saved from the root PBIP is an optional fallback. PBIX files, caches, credentials and local Service bindings are never committed.

---

## 3. Directory Map

```
Programme-Review/
├── AGENTS.md                                           # Repository-specific rules for AI agents
├── ARCHITECTURE.md                                     # System architecture & AI maintenance guide (this file)
├── ATHENA_PROGRAMME_SELECTION.md                       # Athena C/J family selection and baseline window rules
├── RESOURCE_PLAYGROUND.md                              # Resource Calendars (Playground) functional specification
├── SHAREPOINT_CSV_SETUP.md                             # SharePoint folders, credentials, refresh and rollback guide
├── Backgrounds/                                        # Canvas background images (Contract.png, Target.png)
├── Themes/                                             # JSON theme definitions (Contract_Theme.json, Target_Theme.json)
├── scripts/                                            # Automation & verification scripts
│   ├── calendar_analysis/                              # Calendar Analysis static/TOM/conservation-law validator, plus read-only live table-11 alignment and P6 reconciliation check (validate_calendar_live.py, Export-CalendarLiveData.ps1); Calendar Stretch generator (generate_stretch_page.py, stretch_dax.py, calendar_stretch_timeline.vl.json), static/oracle validator (validate_calendar_stretch.py) and live check (validate_calendar_stretch_live.py, Invoke-ReadOnlyDax.ps1)
│   ├── resource_playground/                            # Scenario generators, static/TOM checks, and live harnesses
│   ├── schedule_metrics/                               # Schedule metrics guide generator, static validator, and XMLA tests
│   ├── switch_theme.js                                 # Script to switch page canvas background images
│   └── test_prefilter.py                               # DuckDB test harness for AthenaScopeSql, 01 XER_TASK and 11 XER_CALENDAR_DETAILED SQL
├── Project Review - Programme (datalake).pbip          # Root Power BI Project declaration file
├── Project Review - Programme (datalake).SemanticModel/# TMDL Semantic Model root
│   ├── definition.pbism                                # Semantic Model metadata
│   ├── diagramLayout.json                              # Model diagram visual layout configuration
│   └── definition/                                     # TMDL model definition folder
│       ├── model.tmdl                                  # Model declaration & table/role references
│       ├── database.tmdl                               # Database declaration
│       ├── expressions.tmdl                            # Power Query M parameters & queries (Athena + SharePoint CSV)
│       ├── relationships.tmdl                          # Model table relationships (40 relationships)
│       ├── cultures/                                   # Locale definition (en-NZ)
│       ├── roles/                                      # Row-Level Security definitions (Project Access.tmdl)
│       └── tables/                                     # TMDL table & measure files (61 TMDL files)
└── Project Review - Programme (datalake).Report/       # PBIR Report root
    ├── definition.pbir                                 # Report metadata pointing to SemanticModel
    ├── CustomVisuals/                                  # Custom visual packages (3 custom visuals; AppSource Deneb is registered in report.json publicCustomVisuals instead)
    ├── StaticResources/                                # Embedded image resources
    └── definition/                                     # PBIR report definition folder
        ├── report.json                                 # Global report settings, theme bindings & publicCustomVisuals (Deneb)
        ├── version.json                                # PBIR format version
        ├── bookmarks/                                  # Report bookmark JSON files (44 bookmarks)
        └── pages/                                      # 17 Report pages (page.json & visual folders)
```

---

## 4. AI Coding Agent Rules & Maintenance Protocol

When modifying this repository, any AI coding agent **MUST** adhere to the following rules:

### 1. Always Keep `ARCHITECTURE.md` Updated
- **Requirement**: If you add, remove, rename, or re-architect any dataset, table, measure, column, query parameter, report page, script, or theme asset, you **must update this document (`ARCHITECTURE.md`)** in the same task before declaring completion.

### 2. Git Status Discipline
- Run `git status --short` **before** making changes to inspect dirty states.
- Run `git status --short` **after** making changes to confirm exact modified/untracked files.

### 3. Safety for PBIP, TMDL, and PBIR Files
- Treat `.pbip`, `.SemanticModel`, `.Report`, TMDL, and PBIR files as source-controlled code files.
- **Do not edit or commit** `.pbi/cache.abf`, `.pbi/localSettings.json`, `.pbi/unappliedChanges.json`, or `.pbix` binaries. Desktop may recreate local Service bindings after publication; keep them ignored and use the normal root PBIP for subsequent updates to that target.
- Preserve table/column lineage tags, relationship IDs, page GUIDs, visual names, and TMDL structure.
- Perform impact checks (check DAX measures, relationships, and PBIR report visuals) before deleting or renaming any column or measure.

### 4. Language & Prose Standard
- Use **New Zealand English** (`en-NZ`) for user-facing text, documentation, and comments (e.g. *programme*, *organisation*, *colour*).

### 5. Post-Edit User Notification
- Whenever TMDL semantic model or PBIR report files are modified, inform the user to **reopen or restart Power BI Desktop** to reload updated files.

## Athena project preference and prefiltering

See [ATHENA_PROGRAMME_SELECTION.md](ATHENA_PROGRAMME_SELECTION.md) for the J-history rule, query-only optimisation, load-disabled selection diagnostic and validation checklist. C-only projects remain included; unmatched C history is deliberately excluded once J exists for the same programme type. No database objects or permissions are changed. Hidden canonical project keys keep one project-dimension row across C/J, while programme type separates activity/baseline/resource comparisons.
