# Rolling-window revision fixture

These helpers validate the later project/update calendar and rolling-window
revision. They do not replace or relabel the earlier repair's 101-case evidence.

The fixture copies the 14 current Scenario tables and production CurrentDate
calculated table. Five literal tables provide synthetic calendar rules,
Project_Dimension, minimal Task/WBS and an immutable marker. No production task
or calendar data is copied; no external data source is configured. The complete
active project/WBS/task/update/calendar relationship graph is processed.

The local endpoint is explicitly authorised for this task. Creation and sync
guard the marker, exact inventory and source-free partition types. Execution is
read-only and verifies the fixture's anchor still equals engine TODAY. Cleanup
requires final acceptance, pins the exact temporary database ID, checks the
marker and partition inventory again, and compares production metadata before
and after deleting only the fixture.

Run with Python 3 (`-B`) and PowerShell 7. The TOM helpers use the installed
Microsoft.AnalysisServices 19.114.8 net8.0 assemblies.

1. Read the engine date with `test_window_engine_clock.ps1 -Port 65096`.
2. Build source-free TMDL with `python -B test_build_window_fixture.py`.
3. Create/process with `test_create_window_fixture.ps1 -Port 65096`. Every
   partition must report Ready; a successful SaveChanges call alone is insufficient.
4. Generate cases with `test_window_cases.py`, `test_window_context_cases.py`,
   and `test_window_native_cases.py`. The independent oracle enumerates only the
   fixture window and uses exact Fraction arithmetic.
5. Execute each JSON suite with `test_execute_window_fixture.ps1 -Port 65096
   -MemoryLimitKB 1048576 -CasesPath <suite> -OutputPath <evidence>`. Scalar
   diagnostics use separate queries to avoid artificial bundled expansion.
6. After a bounded source correction, sync only the marked fixture with
   `test_sync_window_fixture.ps1`, then rerun affected cases. Preserve earlier
   failures as evidence. Verify current source parity with
   `test_verify_window_fixture_source.ps1` and summarise with
   `test_summarise_window_fixture.py`.
7. Once the final acceptance is PASS and Desktop is not saving/applying changes,
   run `test_cleanup_window_fixture.ps1 -Port 65096`.

Artifacts are stored outside the repository under
`resource_playground_review/refinement_20260911/window_revision`.
Native Desktop interaction, save/reopen and production RLS verification remain
distinct from synthetic-engine evidence. Leap rollover examples test the date
arithmetic contract; they do not simulate a future production TODAY value.
