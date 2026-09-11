# Open-horizon fixture checks

This is a separate revision of the fixture workflow. Earlier window helper
files and evidence remain unchanged. These helpers use marker
`resource-playground-open-horizon-20260911` and write only to the new
`resource_playground_review/open_horizon_20260911` artifact folder.

1. `test_open_horizon_engine_state.ps1 -Port 65096` verifies the protected
   production endpoint read-only and records the existing date-axis bounds.
2. `python -B test_build_open_horizon_fixture.py` copies current Scenario
   expressions and creates only synthetic literal data. CurrentDate retains
   its exact production calculated expression over the synthetic Task table.
3. `test_create_open_horizon_fixture.ps1 -Port 65096` creates a new uniquely
   marked database and requires all 20 partitions to be Ready.
4. `python -B test_open_horizon_cases.py` builds 32 scalar/context cases and ten
   native-shaped multi-year chart/table cases. Expected values come from
   independent exact-arithmetic calendar calculations.
5. `test_execute_open_horizon_fixture.ps1 -Port 65096 -MemoryLimitKB 1048576`
   runs scalar checks; supply the native cases/output JSON paths to run the
   native suite. It connects only to the verified fixture catalog.
6. `test_verify_open_horizon_fixture_source.ps1` compares the actual tested
   expressions with current source. `test_summarise_open_horizon_fixture.py`
   requires complete passing evidence.
7. After acceptance and while Desktop is not saving/applying changes,
   `test_cleanup_open_horizon_fixture.ps1 -Port 65096` deletes only the exact
   accepted fixture ID and verifies production metadata preservation.

PowerShell helpers require PowerShell 7 and the installed TOM 19.114.8 net8.0
assemblies. Python runs use `-B` to avoid creating cache files. There are no
external fixture data sources or production model mutations.
