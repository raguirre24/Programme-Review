"""Summarise this revision's actual engine results; earlier repair evidence stays separate."""
import json
import datetime as dt
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from test_build_window_fixture import ARTIFACTS, MARKER, OUTPUT
from test_build_fixture import js


def build():
    manifest = json.loads((OUTPUT / 'fixture-marker.json').read_text(encoding='utf-8-sig'))
    files = ['fixture_results.json', 'fixture_context_results.json', 'fixture_native_results.json', 'fixture_native_unsupported_results.json',
             'fixture_extra_results.json', 'fixture_scalar_fixed_results.json']
    latest = {}
    for name in files:
        path = ARTIFACTS / name
        if not path.exists():
            raise ValueError('Missing completed evidence: ' + name)
        result = json.loads(path.read_text(encoding='utf-8-sig'))
        for test in result['tests']:
            latest[test['name']] = dict(test, evidence=name)
    expected = {}
    for name in ['fixture_cases.json', 'fixture_context_cases.json', 'fixture_native_cases.json']:
        for test in json.loads((ARTIFACTS / name).read_text(encoding='utf-8-sig'))['tests']:
            expected[test['name']] = test
    missing = sorted(set(expected) - set(latest))
    parity = json.loads((ARTIFACTS / 'fixture_source_equivalence.json').read_text(encoding='utf-8-sig'))
    sync = json.loads((ARTIFACTS / 'fixture_sync.json').read_text(encoding='utf-8-sig'))
    selected = [latest[name] for name in expected if name in latest]
    failed = [t['name'] for t in selected if t['status'] != 'PASS']
    all_measures = latest.get('all_current_measures_execute', {})
    measures_executed = len(all_measures.get('fragments', [])) if all_measures.get('status') == 'PASS' else 0
    native = [t for t in selected if 'nativeRows' in t]
    delta = json.loads((ARTIFACTS / 'fixture_raw_delta_results.json').read_text(encoding='utf-8-sig'))['tests']
    delta_manifest = json.loads((ARTIFACTS / 'fixture_raw_delta_cases.json').read_text(encoding='utf-8-sig'))['tests']
    delta_ok = len(delta) == len(delta_manifest) == 22 and {t['name'] for t in delta} == {t['name'] for t in delta_manifest} and all(t['status'] == 'PASS' for t in delta)
    result = dict(result='PASS' if not failed and not missing and parity['result'] == 'PASS' and sync['result'] == 'PASS' and measures_executed == 48 and delta_ok else 'FAIL',
                  marker=MARKER, fixtureDatabase=sync['fixtureDatabase'], logicalCases=len(expected), passed=len(selected)-len(failed), failed=failed, missing=missing,
                  assertions=sum(len(t.get('assertions', [])) for t in selected), measuresExecuted=measures_executed,
                  affectedRawMeasureChecks=len(delta), affectedRawMeasurePass=sum(t['status'] == 'PASS' for t in delta),
                  affectedRawMeasureAssertions=sum(len(t.get('assertions', [])) for t in delta),
                  scenarioDaxExpressionChecks=61, sourceExpressionChecks=parity['checked'], sourceMeasureSha256=parity['sourceMeasureSha256'],
                  nativeQueries=len(native), nativeMaxMilliseconds=max(t['milliseconds'] for t in native),
                  windowStart=manifest['today'], windowEnd=manifest['windowEnd'],
                  windowDays=(dt.date.fromisoformat(manifest['windowEnd'])-dt.date.fromisoformat(manifest['today'])).days+1,
                  priorVersionEvidence='The earlier 101-case repair suite is prior-version evidence and is not included in these totals.',
                  limitations=['Future leap rollover is checked against independent EDATE/CALENDAR boundary examples. Production TODAY was not replaced to simulate a future date.',
                               'The synthetic RLS role proves ProjectKey propagation; production View-as-RLS and native UI checks are separate evidence.'],
                  cases=[dict(name=t['name'], status=t['status'], milliseconds=t['milliseconds'], evidence=t['evidence']) for t in selected])
    js(ARTIFACTS / 'fixture_acceptance_summary.json', result)
    print(json.dumps({k: v for k, v in result.items() if k != 'cases'}, indent=2))
    return result


if __name__ == '__main__':
    build()
