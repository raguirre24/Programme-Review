# Numbered table dictionary

The 14 legacy Enhanced tables are listed below. There is deliberately no table 05. Review profiles are projections of selected numbers, not interchangeable copies of the legacy files. Their exact headers are in [profile-contracts.md](profile-contracts.md).

Legacy CSV serialization adds the original `FileName` provenance column, not an internal token or collision-qualified public namespace. Dynamic tables preserve the deterministic union of source headers and append keys plus `MonthUpdate`; incoming-only fields are not discarded. Legacy `MonthUpdate` is inferred from the original source filename, not the P6 Data Date. Inspect the actual value instead of treating the filename convention as universal.

If an imported column collides with a reserved derived/provenance column, the Enhanced output retains the raw value under a collision-safe `raw_<original-name>` alias and warns with its original field/evidence. Inspect the actual header and warning instead of assuming the colliding source value is the derived result; raw-only export semantics are unchanged.

## Grain and joins

| Table | Source / grain | Keys and reporting use |
| --- | --- | --- |
| 01_XER_TASK | TASK; one activity per source/snapshot | `task_id_key`; project, WBS and calendar foreign keys. Activity dimension/fact at snapshot grain. |
| 02_XER_PROJECT | PROJECT; one project per source/snapshot | `proj_id_key`; P6 Data Date and project metadata. Review bundle ProjectCode is governed metadata, not the native ID. |
| 03_XER_PROJWBS | PROJWBS; one WBS node per source/snapshot | `wbs_id_key`, self-referencing `parent_wbs_id_key`; `01.wbs_id_key` joins here. Duplicate/cyclic/cross-project parent identities are warned; unresolved hierarchy values stay blank while source rows remain. |
| 04_XER_BASELINE | Filtered legacy 01 | All rows at the global earliest valid filename-derived MonthUpdate. Not an Oracle designated baseline, not independently selected per project. Absent from both review profiles. |
| 06_XER_PREDECESSOR | TASKPRED; one relationship | `task_id_key` is successor, `pred_task_id_key` is predecessor. Review profiles also supply `task_pred_id_key`. Multiple relationships between an activity pair can be valid. |
| 07_XER_ACTVTYPE | ACTVTYPE; one code category | `actv_code_type_id_key`; category name, not activity assignment. |
| 08_XER_ACTVCODE | ACTVCODE; one code value | `actv_code_id_key`, `actv_code_type_id_key`; join to 07 for category. |
| 09_XER_TASKACTV | TASKACTV; one activity/code assignment | Bridge `task_id_key` to `actv_code_id_key`; not an activity dimension. One activity can have multiple code assignments. |
| 10_XER_CALENDAR | CALENDAR; one calendar per source | `clndr_id_key`. Legacy preserves shifts blob, base ID and period factors; review profiles contain only key/name. |
| 11_XER_CALENDAR_DETAILED | Parsed CALENDAR; weekday rules plus dated replacements | Calendar key plus rule/day/exception identity; not unique on calendar key or a dense Date dimension. Absent from review profiles. |
| 12_XER_RSRC | RSRC; one resource per source | `rsrc_id_key`; legacy also `clndr_id_key`, `unit_id_key`. Review projection is resource key/default rate only. |
| 13_XER_TASKRSRC | TASKRSRC; one resource assignment | Raw `taskrsrc_id` remains important. Added `task_id_key`, `rsrc_id_key`; task/resource alone is not a guaranteed assignment key. Legacy only. |
| 14_XER_UMEASURE | UMEASURE; one unit definition per source | `unit_id_key`; join legacy 12. Preserve unit semantics. Legacy only. |
| 15_XER_RESOURCE_DISTRIBUTION | Derived TASKRSRC monthly units | Legacy/Programme retain assignment contributions; Tender normally aggregates to stage-qualified task/resource/actual/month; an unrepresentable or conflicting group retains separate contributions with a warning. See calculation rules before aggregation. |

For 06, use role-playing predecessor/successor activity dimensions or deliberate measure-specific relationships so filters have an unambiguous direction. Do not make both endpoint relationships bidirectional by default. For 09, retain the bridge and avoid multiplying activity measures through code assignments. Same-name calendars/resources in separate snapshots remain separate identities unless a deliberate cross-snapshot mapping is established.

## 01: activity fields and calculations

Legacy fixed columns before the writer's FileName:

```text
task_id,proj_id,wbs_id,clndr_id,task_type,status_code,task_code,task_name,rsrc_id,act_start_date,act_end_date,early_start_date,early_end_date,late_start_date,late_end_date,target_start_date,target_end_date,cstr_type,cstr_date,priority_type,float_path,float_path_order,driving_path_flag,remain_drtn_hr_cnt,phys_complete_pct,Start,Finish,ID_Name,Remaining Duration,Original Duration,total_float,Free Float,%,Data Date,wbs_id_key,task_id_key,calendar_id_key,proj_id_key,MonthUpdate
```

Raw IDs/dates and schedule fields are imported, not a new CPM schedule. `Remaining Duration`, `Original Duration`, activity `total_float` and activity `Free Float` convert their source hour counts using the activity calendar's positive `day_hr_cnt`, with two-decimal legacy formatting. Completed activity floats are blank. The raw `remain_drtn_hr_cnt` remains hours. Do not multiply a day value by eight unless its actual calendar conversion factor is eight. Do not sum activity duration/float/percentage to represent a project duration/float/percentage.

The `%` output is 0..100, not a 0..1 fraction. Complete=100 and unstarted=0. Active physical uses source physical percent; active duration uses `(target hours - remaining hours)/target hours`; active units uses `(actual labor + actual nonlabor)/(actual labor + actual nonlabor + remaining labor + remaining nonlabor)`. The units inputs are `act_work_qty`, `act_equip_qty`, `remain_work_qty`, `remain_equip_qty`; they do not include unlike material units. Optional blank unit quantities count as zero and a zero units denominator gives zero. Physical/duration required inputs must be present, finite and nonnegative, and duration target must be positive. Malformed/negative/nonfinite/overflowing values, unknown active completion types or unknown statuses yield blank, not NaN or an invented zero. Supported results are clamped to 0..100. In Power BI, do not format an unscaled 60 as a fraction-based percent and display 6000%.

01 and the shared 06 display endpoints use status-aware dates: unstarted Start prefers `restart_date`, falling back to `early_start_date` only when the preferred value is empty or whitespace; active/completed Start uses actual start. Unstarted/active Finish prefers `reend_date`, falling back to early finish only when the preferred value is empty or whitespace; completed Finish uses actual finish. Absent headers and omitted cells normally read as empty for this display fallback; this is not restricted to the audit's technical `AbsentHeader` state. A malformed nonblank preferred value remains blank, and late dates are not forecast substitutes. Tender follows this remaining/actual policy too. Raw early/late columns remain imported raw values and can legitimately differ. `ID_Name`/`id_name` is a display label, not an identity. `driving_path_flag` is imported, not a guarantee that every relationship chosen by a custom visual is P6-driving.

## 02/03/04 and code/resource dimensions

02,03,07,08,09,10,12,13,14 retain native rows in legacy; they are not global deduplicated master dimensions. Key additions are exactly those in the grain table; most also retain other raw IDs without adding keys for every possible relationship.

03 retains source WBS occurrences even when identities are blank/duplicated or parent links are cyclic, ambiguous or cross-project. Unverifiable derived hierarchy links remain blank with warnings; genuinely absent parents remain blank as before. Do not deduplicate exported rows to manufacture a valid hierarchy. Reports must preserve activities missing a usable WBS mapping and choose an explicit fallback display group.

04 is a legacy convenience snapshot. Do not silently replace the Programme profile's resolved baseline/adjusted-baseline history with it. If two unrelated projects have different earliest available months, global selection can omit one project's baseline entirely. No valid filename month produces a header-only 04, not an old file retained from another export.

07 -> 08 -> 09 provides code category -> code value -> activity mapping. Labels can repeat; use qualified keys. 12's rate is not a monthly quantity. 13 preserves raw assignment quantities and profiles (`remain_crv`, `curv_id`) supplied by any input schema. Missing values for an occurrence are not borrowed from another occurrence. 14 identifies units, not a universal conversion between unlike resources.

## 06: relationship fields

Legacy preserves TASKPRED fields and adds:

```text
task_id_key,pred_task_id_key,calendar_id_key,predecessor_clndr_id_key,status_code,predecessor_status_code,task_type,predecessor_task_type,lag,time_period_hours_per_day,Start,Finish,predecessor_start,predecessor_finish,free_float,free_float_status,free_float_basis,free_float_reason,total_float,MonthUpdate
```

`free_float` is derived per relationship in predecessor-calendar day units. Read it with `free_float_status`, `free_float_basis` and `free_float_reason`: only `Finite` and `Estimated` contain a number, including signed and zero values. Resource-dependent endpoint results are labeled `Estimated`; fixed, historical, ignored, context-dependent and missing/invalid outcomes remain blank. `total_float` repeats successor activity float converted with the successor's valid HPD; it remains blank when that conversion is unresolved, never defaulting to eight. `lag` is a display conversion of raw lag hours using predecessor HPD; that does not define which calendar schedules the lag. `calendar_id_key` denotes successor calendar; `predecessor_clndr_id_key` denotes predecessor calendar. Display dates follow the 01 status-aware policy above; 15 dates remain assignment-period dates. Review date-only fields still lose intraday precision and cannot reconstruct relationship arithmetic.

Use explicit FS/SS/FF/SF type mapping; never infer every row to be FS. Endpoint resolution requires exactly one same-source task identity and matching exported project context; a project filter cannot legitimize duplicate task IDs. An unresolved external predecessor is not linked to a local same-ID activity. Unresolved endpoint keys and dependent calculations remain blank; warnings preserve relationship source evidence in every profile without deleting the relationship or inventing a match. Keep unknown free float nullable and visible in data-quality counts.

An optional relationship assessment explains each raw TASKPRED row separately, including finite, estimated, fixed-event, ignored/no-finite-bound, historical, context-dependent, missing-data and invalid-data outcomes. Its selected remaining endpoints can differ from displayed Start/Finish fields. Audit 1.1 is not an extra numbered table and does not extend the normal file/manifest envelope; the new inline table 06 metadata is part of Programme 4.0/Tender 2.0. Use [relationship-audit.md](relationship-audit.md) when inspecting those reasons or raw field states.

## 10 and 11: calendar data

10's legacy `day_hr_cnt`, `week_hr_cnt`, `month_hr_cnt`, `year_hr_cnt` are conversion factors. `clndr_data` defines work availability; `base_clndr_id` can supply inherited exceptions. The fixed review 10 has neither these factors nor shifts, so a report cannot reconstruct a full working calendar from that projection alone.

11 columns before FileName:

```text
clndr_id,clndr_name,clndr_type,date,day_of_week,working_day,work_hours,exception_type,clndr_id_key,MonthUpdate,day_of_week_num,working_day_int
```

Each source CALENDAR occurrence produces seven standard-weekday rows with blank `date`; additional dated rows replace that date's rule, including inherited/overridden exceptions. An unusable weekday remains as a row with blank hours/working flags, not zero/nonworking. If its unknown overnight spill could affect the following weekday, that derived daily result is also unknown. Valid independent rules and explicit valid dated overrides remain usable. Blank/duplicate calendar identities retain metadata but have blank derived calendar keys; they cannot be safely joined as one calendar.

An invalid dated exception uses `exception_type=Exception - Invalid` and blank hours/working flags. An invalid or unresolvable exception date/inheritance produces an undated invalid marker with blank date/day/hours. Such a marker signals unknown exception coverage: do not silently choose the normal weekday rule for every date and report an apparently complete calendar. Inspect the companion and original calendar evidence.

`day_of_week_num` is Monday=1 through Sunday=7 (different from the raw P6 weekday numbering). `work_hours` is daily resolved availability; the table does not expose exact intraday intervals. For a verified calendar-date bridge, choose the usable dated exception if present, otherwise the usable weekday rule, and retain unknown dates as unknown. Never add exception hours to weekday hours or coalesce an invalid rule to zero.

## 15: distribution fields

Legacy columns before FileName:

```text
task_id_key,rsrc_id_key,clndr_id_key,proj_id_key,distribution_month,month_start_date,month_end_date,monthly_quantity,distribution_type,month_working_hours,total_working_hours,calendar_hours_per_day,month_working_days,total_working_days,month_calendar_days,total_calendar_days,Start,Finish,is_actual,status_code,Unit,task_code,rsrc_short_name,rsrc_name,rsrc_type,MonthUpdate
```

`distribution_month` is the monthly bucket date, independent of the source's update/status date. `Start`/`Finish` are allocation-period timestamps, not necessarily activity endpoints. `is_actual` separates actual from remaining. Legacy `distribution_type` distinguishes `Working Hours`, `Resource Curve`, `Remaining Units Profile`, `Resource Curve Forecast`, `Working Hours Fallback`, `Actual Elapsed Time` and `Actual Recorded Date`; it is not included in the review projection. The last two preserve recorded actual units when the entire valid period has no scheduled work, or the timestamps coincide. Their working-hour/day diagnostics remain zero (day conversions blank if HPD is unknown); a recorded instant also has zero calendar-duration diagnostics. These actual labels do not claim timesheet detail or authorize elapsed-time fallback for remaining units. The two new remaining methods use valid remaining working availability and carry separate method warnings in the companion; they are allocated estimates, not unallocated quantities.

Successful active-curve forecasts use issue_code `REMAINING_CURVE_ESTIMATED`; phase fallbacks use `REMAINING_CURVE_UNIFORM_FALLBACK`. Both retain raw assignment evidence, keys/dates and the calculation reason, with blank allocation_portion and unallocated totals. Calendar-hour diagnostics remain raw even when recorded suspensions reduce effective forecast time; consult A/R/p when a method message is emitted. Linear or one-working-month active named curves retain `Resource Curve` and have no forecast-method warning or A/R/p message, while still using suspension-adjusted availability. Review projections retain their fixed headers and expose forecast/fallback methods through companion diagnostics only.

Legacy nonmaterial unit labels may look like units/time. The allocated value is nevertheless assignment units, not a rate multiplied by time; inspect source resource/unit definitions before choosing display labels or summing unlike resources.

`monthly_quantity` is additive across compatible assignment/month contributions within the intended snapshot. `total_working_hours`, `total_working_days`, `total_calendar_days`, conversion factors and period endpoints repeat across monthly rows; do not sum them. Even monthly working hours are assignment exposure, not distinct resource capacity: overlapping assignments can cover the same hours. `month_working_days` is working hours divided by HPD, not a count of distinct dates. Curve shapes change units, not these raw calendar diagnostics. No profile exports an assignment ID in table 15, and review projections also omit diagnostics. Visible duplicate task/resource/month rows in Standard or Programme can be legitimate separate assignments. Reconstruct from raw assignments for aggregate or multiset reconciliation; these CSV rows alone do not provide unique assignment traceability.

## Supplemental XER_DATA_QUALITY.csv

This is not another numbered monthly table. It accompanies every Standard Enhanced selection and every review bundle, including a header-only file when no issues are detected. Raw-only exports remain unchanged. All profiles use the same 35-column header, including writer provenance. Schema 1.2 preserves all 30 data columns from 1.1 and appends `source_table`, `column_name`, `raw_value`, `raw_row_json` before the writer's final `FileName`:

```text
diagnostic_schema_version,severity,issue_code,table_name,source_namespace,source_row_number,proj_id_key,task_id_key,rsrc_id_key,taskrsrc_id_key,taskrsrc_id,task_code,rsrc_name,rsrc_type,unit,status_code,act_start_date,act_end_date,project_data_date,act_reg_qty,act_ot_qty,unallocated_actual_quantity,message,allocation_portion,restart_date,reend_date,remain_qty,curv_id,remain_crv,unallocated_remaining_quantity,source_table,column_name,raw_value,raw_row_json,FileName
```

Grain is one reported source-quality or unavailable-calculation issue, identified by affected `table_name` and source occurrence/row; `diagnostic_schema_version=1.2` and `severity=Warning`. General issues use `source_table`, `column_name`, `raw_value` and `raw_row_json` for evidence; allocation-specific fields can be blank. Resource issues retain one unsuccessful actual or remaining portion per assignment occurrence, with `table_name=15_XER_RESOURCE_DISTRIBUTION` and `allocation_portion=Actual` or `Remaining`; an assignment can generate both portion warnings. Original assignment dates, quantities, `curv_id`, `remain_crv` and raw project Data Date remain text, including missing or malformed values. `status_code` is the raw TASK status when unambiguously resolvable. The corresponding `unallocated_actual_quantity` or `unallocated_remaining_quantity` is the known signed source total rounded to four decimals; the other portion's column is blank. An unrepresentable component/sum leaves that total blank, never zero. `message` explains the issue; `issue_code` gives a stable classification. Dates in this companion are intentionally not the date-normalized review columns.

The four keys use the same public namespace as that profile's numbered tables; `taskrsrc_id_key` qualifies the native assignment ID when present. `source_namespace` is the Standard collision-qualified filename namespace or governed review namespace without its trailing `::`. It is not the internal token. Internal occurrence tokens still protect all correlation before serialization. `FileName` preserves the original name, including repeats. `source_row_number` is the one-based row ordinal within the named `source_table` and input occurrence, not always TASKRSRC. A table-level issue can have no row ordinal. `raw_row_json` preserves source header/value evidence without exposing internal occurrence tokens. Neither ordinal nor warning count is a durable cross-export business key. Keep bundle/source provenance when comparing warnings across exports.

Use this file to show affected tables/fields, source-quality issues and unavailable calculations, and separately reconcile unallocated actual/remaining quantities. Completed activities retaining remaining units remain visible as warnings with their source amount. Do not add companion units to a monthly trend as though a month were known. Reconcile distributed plus unallocated separately by portion at compatible source/task/resource grain, retaining every independently valid portion; count unknown numeric quantities separately. Source row ordinal disambiguates missing/duplicated native assignment IDs. The review manifest includes per-source companion row counts and its CSV hash; completion literals indicate completed publication, while a nonzero companion count means completed with warnings. Warning count is an issue count, not a count of source rows, relationships or distinct assignments. Filter `allocation_portion` before using resource reconciliation rules; do not add unrelated diagnostic rows to unallocated-unit totals.

Normal Standard exports include warnings only for selected numbered outputs. Table 04 copies applicable task-calculation warnings only for its retained baseline rows and attributes them to 04; it does not include discarded-update warnings or unselected 01 dependency warnings. If both 01 and 04 are selected, one underlying source defect can have a warning for each affected output. Count distinct source problems separately from table/field warning occurrences.
