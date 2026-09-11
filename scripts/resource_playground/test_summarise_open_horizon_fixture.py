"""Consolidate only completed tests for the open-horizon revision."""
import datetime as dt
import json
import sys

sys.dont_write_bytecode=True
from test_build_open_horizon_fixture import ARTIFACTS,OUTPUT,MARKER
from test_build_fixture import js


def build():
    manifest=json.loads((OUTPUT/'fixture-marker.json').read_text(encoding='utf-8-sig'))
    evidence=[];expected=[]
    for suffix in ['', '_native']:
        cases=json.loads((ARTIFACTS/f'fixture{suffix}_cases.json').read_text(encoding='utf-8-sig'))
        results=json.loads((ARTIFACTS/f'fixture{suffix}_results.json').read_text(encoding='utf-8-sig'))
        if cases['marker']!=MARKER or results['marker']!=MARKER:raise ValueError('Evidence marker mismatch')
        expected.extend(cases['tests']);evidence.extend(results['tests'])
    failures=[test['name'] for test in evidence if test['status']!='PASS']
    missing=sorted({test['name'] for test in expected}-{test['name'] for test in evidence})
    parity=json.loads((ARTIFACTS/'fixture_source_equivalence.json').read_text(encoding='utf-8-sig'))
    native=[test for test in evidence if 'nativeRows' in test]
    full=next(test for test in native if test['name']=='native_daily_complete_available_horizon')
    all_measures=next(test for test in evidence if test['name']=='all_current_measures_execute')
    measure_count=len(all_measures.get('fragments',[])) if all_measures['status']=='PASS' else 0
    result=dict(result='PASS' if not failures and not missing and parity['result']=='PASS' and measure_count==48 else 'FAIL',marker=MARKER,
                fixtureDatabase=parity['fixtureDatabase'],logicalCases=len(expected),passed=len(evidence)-len(failures),failed=failures,missing=missing,
                assertions=sum(len(test.get('assertions',[])) for test in evidence),measuresExecuted=measure_count,sourceExpressionChecks=parity['checked'],
                sourceMeasureSha256=parity['sourceMeasureSha256'],nativeQueries=len(native),nativeMaxMilliseconds=max(t['milliseconds'] for t in native),
                start=manifest['today'],end=manifest['windowEnd'],availableDates=(dt.date.fromisoformat(manifest['windowEnd'])-dt.date.fromisoformat(manifest['today'])).days+1,
                completeDailyRows=len(full['nativeRows']),completeDailyMilliseconds=full['milliseconds'],dateAxisRows=4383,
                earlierEvidence='The prior fixed-window114suite is preserved separately; its one-year boundary expectations are not reused for this revision.',
                cases=[dict(name=t['name'],status=t['status'],milliseconds=t['milliseconds']) for t in evidence])
    js(ARTIFACTS/'fixture_acceptance_summary.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='cases'},indent=2))
    if result['result']!='PASS':raise SystemExit(1)


if __name__=='__main__':build()
