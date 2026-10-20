# Calendar comparison validation

> [!NOTE]
> **Current contract (20 October 2026 — `df14c05`)**: `Resource Scenario Measures` now contains **66 measures** (`57` `Scenario *` + `9` `Comparison *`, including `Scenario Anchor Date` and the 9 `* Display` card wrappers) and `Resource Calendars` (`4c53a34bba9dcc7f3e8c`) contains **50 visuals** (including the 11 shared report header/navigation/guide visuals). Both `verify_integration.py` and `verify_comparison_integration.py` validate this 66-measure / 50-visual contract. The notes below describe the 17 October 2026 comparison fixture (`resource-playground-comparison-20261017`).

The comparison fixture is separate from the historical September fixtures. It
copies the final production scenario TMDL and supplies only synthetic calendar,
project, update and task rows. It has 21 tables, 56 scenario measures and no
external data source. Its marker is `resource-playground-comparison-20261017`.
The final fixture includes 24 calendar identities, 21 in its principal
project/update, and 56 cases including 24 grouped Week/Month chart queries and
one grouped results-table query mixing valid and unknown calendars. Label
regressions include case-only names and original names matching both generated
native-ID labels and qualified fallback labels. The accepted final run has
8,076 passing assertions; expected-BLANK columns must exist in the returned row.
All grouped chart queries project the real guarded identity tooltip and verify the
complete row set, including suppression for invalid and unsupported modes.
Four focused scalar cases also check future unknown data after the target:
partial forward allocation, proven completion, conservative warnings when finish
is later than target, and an inverse scenario completed before the unknown date.

Run the static and independent checks from the repository root:

```powershell
python -B scripts/resource_playground/test_comparison_validation.py
python -B scripts/resource_playground/verify_rule_calculations.py
python -B scripts/resource_playground/verify_integration.py
python -B scripts/resource_playground/verify_comparison_integration.py
```

The final check compares all 48 original measure expressions with Git HEAD,
requires exactly eight named comparison measures and verifies the report's
selector, legend, guarded identity tooltip, summary fields, view bookmarks, Reset and interactions. It
does not execute DAX. `validation-runtime.ps1` adds Microsoft TOM round-trip,
M syntax and report-authoring checks; provide a complete pre-change report
folder using `-BaselineReportRoot` to distinguish existing report diagnostics.

Obtain the current date from the target engine's `TODAY()` and use it explicitly:

```powershell
python -B scripts/resource_playground/test_build_comparison_fixture.py --today 2026-10-17 --output-dir ../resource_playground_review/comparison_20261017/fixture
python -B scripts/resource_playground/test_comparison_cases.py --output-dir ../resource_playground_review/comparison_20261017/fixture
```

Replace the example date with the actual engine date. Rebuild after a source
change or date rollover. The builder refuses the production repository and
unmarked existing outputs. It does not connect to an engine. Its manifest
retains source-file hashes, the date anchor, full table inventory and definition
path. Creating or processing a database is a separate guarded operation.

`comparison_cases.json` contains scalar `expect`/`contains` assertions and
grouped `expectedRows` keyed by calendar identity plus period. Expected quantities
come from an independent daily `Fraction` oracle, not a translation of the DAX
prefix algorithm. The query groups the real Calendar legend, then returns the
stable key and full source identity for comparison. Different calendars are independent alternatives;
the runner must compare each series separately and must never reconcile their
combined total to one input quantity. Preserve returned row counts, key sets,
values, query text, duration and errors. Use a 30-second timeout and 1 GB memory
limit for the initial native-shaped regression run.

The engine runner must require the marker, exact inventory, no external data
sources, Ready partitions and `Fixture Identity[AnchorDate] = TODAY()`. It may
query the marked synthetic model only. Execute the restricted `Fixture Project
P1` case as that role; the fixture policy does not prove production email/RLS
matching or Service identity behaviour. Verify final source-expression parity
after processing and retain both failed diagnostic runs and accepted results.

Native acceptance is separate: switch Single/Compare; set and clear calendar
subsets; switch Week/Month; inspect and clear a summary row; change project/update;
confirm independent errors; exercise Reset; inspect Focus Mode, saved/reopened
state, keyboard and display scaling; and check representative real source
calendars. A source-free fixture cannot establish upstream raw-XER decoding,
production permissions or P6 scheduling/levelling parity.
