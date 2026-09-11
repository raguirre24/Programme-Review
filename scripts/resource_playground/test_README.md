# Executing Resource Playground fixture tests

These tests execute the production scenario DAX on a small, separate semantic
model. `test_build_fixture.py` copies the current 14 scenario table definitions
and adds 93 literal table-11 rows covering 12 scoped calendar identities across
two projects. The calendar fixtures retain weekday/exception grain. Daily
enumeration exists only in the independent Python assertion oracle.

The fixture includes holidays, a working weekend, unequal shifts, a zero-hour
calendar, invalid or duplicate rules, unresolved dates, duplicate calendar names,
CSV/source identity and a role restricted to project P1. It has no external data
source. A one-row hidden calculated carrier can replace the empty measure-table
M partition when processing through TOM; measure expressions are unchanged.

## Generate

From the repository root:

```powershell
python scripts/resource_playground/test_build_fixture.py
python scripts/resource_playground/test_fixture_cases.py
python scripts/resource_playground/test_fixture_native_queries.py
python scripts/resource_playground/test_fixture_display_edge_queries.py
python scripts/resource_playground/test_fixture_daily_audit_queries.py
python scripts/resource_playground/test_fixture_daily_audit_queries.py --report-bindings
```

The default artifact directory is the sibling
`resource_playground_review/repair_20260911/ResourcePlaygroundFixture`. It is not
the production PBIP directory. The regression dates are anchored in September
2026 and must remain inside the copied date-axis horizon when rerunning later.

## Execute against an isolated fixture

Open the generated fixture PBIP in Desktop and process it, or use an explicitly
authorised separate fixture database on a Desktop test engine. The
`test_create_fixture.ps1` bootstrap is deliberately pinned to the endpoint and
protected database ID authorised during this repair; it refuses other values.
It never deletes databases. Do not broaden those safeguards merely to make a
command succeed.

`test_sync_fixture.ps1` can copy updated scenario expressions into a previously
created, uniquely named and marked fixture. It verifies its marker and expected
17-table shape before saving or recalculating that fixture. It never copies real
calendar data or changes production permissions.

Run read-only assertions with the verified fixture engine's port:

```powershell
pwsh -NoProfile -File scripts/resource_playground/test_execute_fixture.ps1 -Port <fixture-port>
```

The harness refuses endpoints without exactly one marked fixture. It verifies
the marker table and processed partitions and rejects production task tables.
Its test statements are limited to `EVALUATE`/`DEFINE`. Large diagnostic result
sets run as individual scalar queries, then merge into one logical assertion
case; this matches native card expressions and exposes scalar timings. XMLA date
serials are normalised after reading rather than duplicating a finish measure
inside a DAX formatting expression.

`-NamePattern` runs a bounded subset. `-CasesPath` and `-OutputPath` allow separate
diagnostic artifacts. Every result retains query text, values, assertions,
execution time and failing fragment details. Final coverage includes all model
measures, independent numerical scenarios, invalid inputs, forward/inverse
modes, daily caps, unknown-calendar boundaries, disjoint date/period selections,
totals, chart-period guards and explicit role queries.

Use `-TimeoutSeconds 60 -MemoryLimitKB 1048576` for the grouped visual regressions.
The timeout and 1 GB query memory limit are recorded in each run. Native chart
tests return the grouped rows directly; totals and per-bucket cumulative
reconciliation are checked outside DAX. This avoids turning a visual query into
an unnecessarily repeated diagnostic aggregate.

The daily audit cases reproduce the visual's six projected fields and its
`__ValueFilterDM0` measure-filter query pattern, across the complete date axis.
Their expected rows come from the independent calendar oracle. Passing scalar
measures or a query with a pre-filtered date range cannot substitute for this
native-shaped test.

The `--report-bindings` variant reads the final daily table projections directly
from PBIR and verifies that its old measure filter is absent. It tests the native
query shape used by the final report, including the 365-day boundary and cleared,
multiple or unmatched chart Period selections.

`test_fixture_affected_queries.py` prepares focused core regressions after a
source change. `test_verify_fixture_source.ps1` checks the processed fixture's
scenario expressions against the final production source. Preserve earlier
diagnostics and consolidate explicit accepted runs with
`test_summarise_fixture.py`; a later run takes precedence only for matching
logical test names. An experimental candidate run is not final source
equivalence evidence.

The fixture role proves project filtering through the selector and calendar
measures. It does not prove the production email/permission matching policy or a
Service user's identity. Native input persistence, Reset, visual rendering and
production-role acceptance remain separate host checks.

The completed 11 September repair run has 101 passing logical cases and 2,512
assertions, covering all 47 final measures. Its 60 final expression comparisons
match the source (13 calculated tables and 47 measures). The final chart and
daily table queries passed with a 1 GB per-query memory limit. The acceptance
summary preserves the earlier scalar evidence for unchanged core branches and
the final runs for changed chart/daily expressions.

The temporary live fixture database was removed after acceptance. The cleanup
artifact records an unchanged protected-production metadata hash. The portable
fixture PBIP and every query/result artifact remain available for inspection;
endpoint-specific bootstrap and cleanup scripts deliberately retain their
original identity guards.
