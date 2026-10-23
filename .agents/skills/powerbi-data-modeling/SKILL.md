---
name: powerbi-data-modeling
description: Design Power BI semantic models — star schemas, relationships, date tables, storage modes (Import/DirectQuery/composite), incremental refresh, aggregations, and role-playing dimensions. Use this skill whenever the user is deciding how to structure tables, mentions relationships, cardinality, "many-to-many", slow models, large datasets, incremental refresh, DirectQuery, or asks why filtering one table doesn't affect another. Use it before writing DAX for any new model — modelling mistakes cannot be fixed with clever DAX.
---

# Power BI Data Modelling

The model determines 80% of both correctness and performance. DAX and visuals sit on top; if the model is wrong, everything downstream fights it. Design the model first, deliberately.

## Star schema — the default, always

- **Facts**: transactions/events/snapshots, narrow and long, numeric measures + dimension keys only. **Dimensions**: descriptive attributes, one row per entity.
- Flat wide tables ("one big table") compress worse, kill filter reuse, and make many-to-one semantics impossible. Snowflaking (dimension→dimension chains) works but costs extra relationship hops — flatten dimensions unless there's a strong reason.
- Every fact→dimension relationship: **many-to-one, single direction** (dimension filters fact). Treat anything else as an exception requiring justification.
- Degenerate dimensions (e.g. document numbers) can stay on the fact table; don't build a dimension with the same cardinality as the fact.
- Multiple facts at different grains (e.g. baseline vs current schedule snapshots, budget vs actuals) share **conformed dimensions**. Never relate fact to fact; go through shared dimensions and let DAX combine.

## Relationships

- One-to-many, single-direction is the workhorse. **Bidirectional filters** are a last resort: they create ambiguity, hurt performance, and can silently change numbers as the model grows. For the classic "slicer on dimension B should reduce dimension A" need, prefer a measure-based approach or `CROSSFILTER` inside specific measures.
- **Many-to-many** relationships (composite keys, mismatched grain) are legitimate but expensive; where possible, resolve through a bridge table with single-direction relationships and a well-understood filter path.
- **Role-playing dimensions** (Date as Start Date vs Finish Date): one active relationship, others inactive, activated per-measure with `USERELATIONSHIP`. If two roles are both used heavily across the report, a second physical date table is often *clearer* than a forest of USERELATIONSHIP measures — clarity beats purity.
- Integer surrogate keys beat text keys for relationship columns (memory + join speed). If natural keys are unstable across source exports (IDs regenerated per export), a durable business key must be engineered upstream — relationships on unstable keys corrupt history silently.

## Date table

Non-negotiable in every model: contiguous date range covering all facts, marked as date table, with Year/Month/Period columns, fiscal or project-period columns as needed, and sort-by columns for month names. Generate in Power Query or source SQL (preferred over DAX CALENDARAUTO, which picks ranges you don't control).

## Storage modes

| Mode | Use when | Watch out |
|---|---|---|
| **Import** | Default. Best performance, full feature set | Model size limits, refresh windows |
| **DirectQuery** | Data too big / real-time need / sovereignty | Every visual = source queries; slow sources = slow reports; DAX/PQ feature limits |
| **Composite** | Big fact in DQ + small dims imported, or aggregations | Relationship types across sources become "limited"; complexity |
| **Dual** | Dimensions in composite models | Set dims to Dual so they serve both sides |

Import until proven otherwise. If Import is too big: reduce (below), then incremental refresh, then aggregations over DirectQuery, in that order.

## Making models small (VertiPaq rules)

Column store compression means **cardinality is everything**:
1. Remove columns you don't use. Audit with VertiPaq Analyzer — usually 2-3 columns are half the model.
2. Split datetime into date + time (or drop time). A datetime with seconds precision is near-unique = incompressible.
3. Reduce decimal precision where business-acceptable; use fixed decimal (currency) type.
4. Avoid high-cardinality text on facts (GUIDs, long descriptions, free text). Push to dimension or drop.
5. Disable Auto date/time in options — it builds hidden date tables per date column.
6. IsAvailableInMDX = false on non-attribute columns (via Tabular Editor) trims dictionary overhead.

## Incremental refresh

- Requires `RangeStart`/`RangeEnd` datetime parameters filtering the fact **foldably**. If the filter doesn't fold, each partition still scans the full source — verify folding before publishing.
- Define policy: archive period (e.g. 5 years), incremental period (e.g. 10 days). Optionally detect data changes via a max-updated-datetime column.
- Published models with IR can't be downloaded as PBIX — keep source PBIP/PBIX in git; make changes via ALM tooling (XMLA/Tabular Editor/deployment pipelines).
- For sources like Athena, align IR partitions with source partitioning (e.g. by date) so each partition refresh prunes S3 scans.

## Aggregation tables

For very large facts: an imported pre-aggregated table (by the common query dimensions) with the detail fact in DirectQuery. Power BI automatically hits the agg when the query matches its grain. Manage mappings in Model view; verify hits with DAX Studio server timings (look for the agg table being queried).

## Calculated tables/columns vs upstream

Order of preference for any derived data: **source (SQL/view) → Power Query → calculated column/table → measure-time**. Push left for anything static; measures for anything that must respond to filter context. Calculated tables are fine for date tables, parameter tables, and disconnected slicer tables.

## Model hygiene checklist

- Hide all key columns and raw fact columns users shouldn't drag; expose measures instead.
- Organise measures in display folders or a dedicated measure table.
- Descriptions on measures and tables (they surface in tooltips and feed documentation/Copilot).
- Perspectives/certified endorsement for shared semantic models; one model serving many thin reports beats copies of the model per report.
- Row-level security roles defined with simple single-direction filter paths; test with "View as".


## This workspace: 61-Table Semantic Model Architecture

1. **Table Inventory (`61` Tables, `38` Relationships, `1` RLS Role)**:
   - **11 Imported XER Tables**: `01 XER_TASK`, `02 XER_PROJECT`, `03 XER_PROJWBS`, `06 XER_PREDECESSOR`, `07 XER_ACTVTYPE`, `08 XER_ACTVCODE`, `09 XER_TASKACTV`, `10 XER_CALENDARS`, `11 XER_CALENDAR_DETAILED`, `12_XER_RSRC`, `15_XER_RESOURCE_DISTRIBUTION`.
   - **Governance & Audit**: `dbo_project`, `dbo_userpermission`, `Logos`, `XER CSV Manifest`, and calculated `XER CSV Refresh Audit`.
   - **Governed Project Dimension (`Project_Dimension`)**: 1 row per canonical `ProjectKey` (`CJ:<digits>` for numeric `C`/`J` codes, `EXACT:<code>` otherwise). Secured by the `Project Access` RLS role (`roles/Project Access.tmdl`), which normalises Acciona guest UPNs (`#ext#` and `@acciona.com`) and checks `HasAllAccess || HasStateAccess || HasProjectAccess`.
   - **Update & Date Tables**:
     - `CurrentDate`: Active **bidirectional** relationship to `'01 XER_TASK'[UpdateDate]`, plus one-way relationships to `Scenario Calendar` and `Scenario Comparison Calendar`.
     - `UpdateHistory`: Disconnected `DISTINCT('01 XER_TASK'[UpdateDate])` table used as the x-axis for trend-by-update visuals up to the `CurrentDate` cutoff.
     - `00 CALENDAR` & `00 PLANNED DATE TABLE (PV)`: Date tables with multiple inactive relationships to `'01 XER_TASK'` and `'04 XER_BASELINE'`, activated via `USERELATIONSHIP` in S-Curve and progress measures.
     - `Resource Calendar`: Uses scalar `MIN`/`MAX` bounds over `15_XER_RESOURCE_DISTRIBUTION[Period]` instead of materialising a `UNION` of all resource rows.
   - **Calculated Snapshot/Logic Projections**:
     - `04 XER_BASELINE`: Subset of `01 XER_TASK` at the earliest `UpdateDate` per `(ProjectCode, ProgrammeType)`.
     - `06a XER_SUCCESSOR`: Projection of `06 XER_PREDECESSOR` keyed on `pred_task_id_key` for successor analysis (`task_pred_id_key` is intentionally omitted from both `06` and `06a` to save VertiPaq dictionary memory).
   - **11 Disconnected/Lookup Slicer Tables (`Filter_*`)**: `Filter_Activity_Status`, `Filter_Constraint_Types`, `Filter_Critical_Status`, `Filter_Driving`, `Filter_Duration`, `Filter_Finish_Delay`, `Filter_Finish_Within`, `Filter_Float`, `Filter_Start_Delay`, `Filter_Start_Within`, `Filter_TaskType`.
   - **14 Resource Playground Tables (`Scenario *`)**: `Scenario Date`, `Scenario Start`, `Scenario Target`, `Scenario Calendar`, `Scenario Comparison Calendar`, `Scenario Quantity`, `Scenario Quantity Scale`, `Scenario Rate`, `Scenario Rate Basis`, `Scenario Limit`, `Scenario Limit Mode`, `Scenario Mode`, `Scenario Period` (field parameter), `Scenario Unit`.
     - `Scenario Calendar` and `Scenario Date` have no relationship to `'01 XER_TASK'`, so a slicer or cross-filter selection on them never removes activity rows by itself. Re-apply it in the activity measures (Calendar Analysis: every `CA Activity *` guard ANDs in `[CA Inspector Selection Match]`, a `TREATAS` on `calendar_id_key` plus a month-overlap filter). Never add a relationship for it: it would create ambiguous paths through `CurrentDate` and `Project_Dimension`, and it would make the Resources page's scenario calendar slicers filter activities.
   - **Schedule Metric Tables**: `Schedule Metric Detail` (1 row `"Baseline coverage"` + 19 `SM Detail *` measures) and hidden `Schedule Metric Guide` (14-row static `DATATABLE`).
   - **9 Dedicated Measure Carrier Tables**: `XER Measures`, `XER  Counts` (**note the double space!**), `XER Metrics`, `XER S-Curve`, `WBS Measures`, `Activity Completion`, `Resources`, `Dynamic Titles & Formatting`, `Resource Scenario Measures`.
