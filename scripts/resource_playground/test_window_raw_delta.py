"""Focused final-expression rerun manifests after the raw allocation kernel change."""
import json
import sys

sys.dont_write_bytecode = True
from test_build_window_fixture import ARTIFACTS, MARKER
from test_build_fixture import js


def build():
    cases = json.loads((ARTIFACTS / 'fixture_cases.json').read_text(encoding='utf-8-sig'))['tests']
    delta = []
    for test in cases:
        if 'DailyQuantity' not in test['expect']:
            continue
        fragment = next(f for f in test['fragments'] if f['name'] == 'DailyQuantity')
        delta.append(dict(name='raw_delta_' + test['name'], dax=fragment['dax'], expect={'DailyQuantity': test['expect']['DailyQuantity']}, contains={}, role=None, maxRows=1))
    for name, tests in [('fixture_raw_delta_cases.json', delta),
                        ('fixture_extra_cases.json', [t for t in cases if t['name'] in ['sparse_dates_clip_window', 'disjoint_months_only_selected_allocation']]),
                        ('fixture_scalar_fixed_cases.json', [t for t in cases if t['name'] in ['all_current_measures_execute', 'inverse_daily_precision', 'inverse_daily_cap', 'inverse_hourly']])]:
        js(ARTIFACTS / name, dict(marker=MARKER, tests=tests))
        print(name, len(tests))


if __name__ == '__main__':
    build()
