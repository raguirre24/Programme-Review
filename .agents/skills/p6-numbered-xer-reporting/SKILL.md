---
name: p6-numbered-xer-reporting
description: Interpret and use the numbered XER-to-CSV Power BI tables in reports, including legacy Enhanced, Programme Review, and Tender Review exports. Use for table grain, joins, snapshot identity, calendar-aware float, resource spreads, and report reconciliation; not as a general P6 scheduling engine.
---

# Numbered XER tables for reporting

Help an agent build, review, or explain reports using this parser's numbered CSVs without confusing raw P6 fields, calculated columns, or export profiles. This portable reference describes the corrected working-tree implementation on 2026-09-07; it is not an Oracle schema specification, a release identifier, or proof of native P6 scheduling parity.

## Establish the actual contract

Inspect the supplied headers, manifest, parser/schema version, and source scope before choosing joins or calculations. Do not assume that identical table numbers imply identical schemas. If files are unavailable, state the profile/version assumption and request only information needed for the task.

- Read [profile-contracts.md](references/profile-contracts.md) for profile detection, exact review headers, namespaces, snapshot dates, and manifest checks.
- Read [table-dictionary.md](references/table-dictionary.md) for the relevant numbered tables, their grain, derived values, and join/aggregation constraints.
- For calendar, relationship float, longest-path/trace, resource spread, or reconciliation work, also read [calculation-rules.md](references/calculation-rules.md).
- For ingestion/export guarantees, Web handoff, older-build differences and genuine unsupported cases, consult [known-limitations.md](references/known-limitations.md).
- For a relationship audit, nullable `06.free_float`, or progressed scheduling settings, read [relationship-audit.md](references/relationship-audit.md). Its optional audit output explains the shared calculation; it is separate from normal report exports.

## Essential decisions

1. Keep snapshot/stage identity in every relationship. Native IDs, activity codes, filenames, paths and hashes are not globally unique. Standard and Tender accept repeated ordered inputs; internal occurrence tokens are distinct from public reporting keys and filename provenance. Programme preserves its stricter snapshot uniqueness contract.
2. Do not join a history/stage fact to a dimension on native ID alone or deduplicate repeated assignments to manufacture uniqueness. Establish the dimension grain first.
3. Distinguish `01` activity free float from `06.free_float`, a relationship-specific predecessor delay allowance. Read its inline `free_float_status`, `free_float_basis` and `free_float_reason`: only `Finite`/`Estimated` carry numbers; fixed-event, historical, ignored/no-finite-bound, context-dependent, missing and invalid outcomes remain blank. Resource-dependent endpoint calculations are explicitly TASK-calendar estimates. Preserve signed values and the user's intentional least-float path policy. Use the optional assessment for complete input evidence.
4. Working shifts and dated exceptions determine available hours. Hours-per-day is a conversion factor, not a workweek. `11` contains rules and overrides, not one row for every calendar date.
5. `15.monthly_quantity` is distributed assignment units, not cost, resource availability, or necessarily actual timesheets. Aggregate only compatible units and selected snapshots. Actual and remaining portions are separate. Active named remaining curves can be forecast estimates or labeled uniform fallbacks; their successful method warnings do not represent unallocated units. Table 15's assignment-calendar selection is separate from table 06's TASK-calendar resource estimate.
6. Treat all CSV keys as text, even when native IDs look numeric. Preserve null/blank separately from numeric zero. Check the profile's boolean, date, decimal, and case conventions before transformations.
7. Expect every selected Enhanced numbered output with available source data, not an aborted table because one row or dependent calculation is bad. Preserve available rows; unverifiable derived fields stay blank and source issues appear in `XER_DATA_QUALITY.csv`. The companion accompanies any Enhanced selection, header-only when clean; raw-only exports remain unchanged. Review profiles enforce their declared numbered schemas and governed request metadata; current table 06 metadata requires Programme 4.0/Tender 2.0 consumers. Inspect `source_table`, `source_row_number`, `column_name`, `raw_value` and `raw_row_json` for evidence. Reconcile distributed plus known unallocated table 15 quantities separately for actual and remaining; an unknown amount is not zero. An omitted or stale file is never evidence of zero data.

Explain which conclusions come from the parser contract, observed source data, and report-specific business policy. Do not silently repair upstream defects in DAX/Power Query or change the parser, visual, report, or deployment unless the user's task authorizes that change.

## Refreshing this reference

When parser source is available, start with `XerToCsvConverter.Core/CoreLogic.cs`, `XerSourceIdentity.cs`, `XerSourceSchema.cs`, `StandardExportSchema.cs`, `StandardExportPublication.cs`, `XerTextEncoding.cs`, and the `ProgrammeReview` and `TenderReview` contract/transformer/metadata files. Relationship behavior is in `XerTransformer.RelationshipAssessment.cs`, `RelationshipFloatAssessment.cs` and `Calendars/`; remaining resource profiles and forecasts are in `Resources/RemainingResourceProfile.cs`, `Resources/ResourceCurveForecast.cs` and `XerTransformer.ResourceDistribution.cs`. `CALENDAR_CALCULATIONS.md` explains calculation intent. The repository's `review/relationship-free-float-evaluation-2026-09-07/IMPLEMENTATION.md` and `review/RESOURCE_CURVE_FORECAST_VALIDATION.md` record scoped validation and reproduction commands; tests do not establish universal P6 parity. Runtime CSV headers and manifests remain necessary when the installed parser differs from this reference.
