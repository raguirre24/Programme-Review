"""Native grouped Week/Month and six-field daily rows against independent daily arithmetic."""
import datetime as dt
import json
import sys

sys.dont_write_bytecode = True
from test_window_cases import manifest, scenario, filters, oracle
from test_build_fixture import js
from test_build_window_fixture import ARTIFACTS, MARKER, SOURCE


def build():
    today, end = (dt.date.fromisoformat(manifest[k]) for k in ["today", "windowEnd"])
    start = dt.date.fromisoformat(manifest["start"])
    visual_path = SOURCE.parent.parent / 'Project Review - Programme (datalake).Report/definition/pages/4c53a34bba9dcc7f3e8c/visuals/c4762ffe207ce780fc4d/visual.json'
    visual = json.loads(visual_path.read_text(encoding='utf-8-sig'))
    projections = visual['visual']['query']['queryState']['Values']['projections']
    measures = [p['field']['Measure']['Property'] for p in projections[1:]]
    expected_measures = ['Scenario Daily Display ' + x for x in ['Hours', 'Capacity', 'Quantity', 'Cumulative', 'Remaining']]
    if measures != expected_measures or any(f.get('field', {}).get('Measure', {}).get('Property') == 'Scenario Show Daily Row' for f in visual.get('filterConfig', {}).get('filters', [])):
        raise ValueError('Unexpected native daily PBIR bindings or filter')
    tests = []
    def rows(s, period, rejected=False):
        daily = []
        if not rejected:
            for offset in range(max(0, (end - s['start']).days + 1)):
                date = s['start'] + dt.timedelta(days=offset)
                values = oracle(dict(s, axis=date))
                if values['DailyQuantity'] is not None:
                    daily.append({'Scenario Date[Date]': date.isoformat(), 'DailyHours': values['DailyHours'], 'DailyCapacity': values['DailyCapacity'],
                                  'Allocated': values['DailyQuantity'], 'Cumulative': values['Cumulative'], 'DailyRemaining': values['DailyRemaining']})
        if period is None:
            return daily
        grouped = {}
        field = 'Week' if period == 1 else 'Month'
        for day in daily:
            date = dt.date.fromisoformat(day['Scenario Date[Date]'])
            bucket = date - dt.timedelta(days=date.weekday()) if period == 1 else date.replace(day=1)
            row = grouped.setdefault(bucket, {'Scenario Date[' + field + ']': bucket.isoformat(), 'Allocated': 0, 'Cumulative': 0})
            row['Allocated'] += day['Allocated']; row['Cumulative'] = day['Cumulative']
        return list(grouped.values())
    def add(name, s, period, rejected=False, role=None, period_selection='2'):
        f = filters(s); f.pop('axis')
        if period is None:
            if period_selection is None:
                f.pop('period')
            else:
                f['period'] = f"TREATAS({{{period_selection}}},'Scenario Period'[Period Order])"
            field = 'Date'
            fields = ','.join('"' + label + '",[' + measure + ']' for label, measure in zip(['DailyHours','DailyCapacity','Allocated','Cumulative','DailyRemaining'], measures))
        else:
            field = 'Week' if period == 1 else 'Month'
            f['period'] = f"TREATAS({{{period}}},'Scenario Period'[Period Order])"
            fields = '"Allocated",[Scenario Chart Quantity],"Cumulative",[Scenario Chart Cumulative Quantity]'
        variables = '\n'.join(f'VAR __Filter{i} = {expression}' for i, expression in enumerate(f.values()))
        arguments = ','.join(f'__Filter{i}' for i in range(len(f)))
        query = f"DEFINE\n{variables}\nVAR __DS0Core = SUMMARIZECOLUMNS('Scenario Date'[{field}],{arguments},{fields})\nVAR __DS0PrimaryWindowed = TOPN(501,__DS0Core,'Scenario Date'[{field}],1)\nEVALUATE __DS0PrimaryWindowed\nORDER BY 'Scenario Date'[{field}]"
        expected_rows = rows(s, period, rejected)
        tests.append(dict(name=name, dax=query, expect={'Buckets': len(expected_rows), 'Quantity': sum(row['Allocated'] for row in expected_rows),
                                                      'FinalCumulative': expected_rows[-1]['Cumulative'] if expected_rows else None},
                          contains={}, role=role, maxRows=367, aggregateRows=True, axisColumn='Scenario Date[' + field + ']', expectedNativeRows=expected_rows))
    cases = [
        ('forward', scenario()), ('inverse_daily', scenario(mode='Meet target date', cap=None)),
        ('inverse_capped', scenario(mode='Meet target date', cap=50)),
        ('inverse_hourly', scenario(mode='Meet target date', basis='Per working hour', calendar='unequal', cap=None)),
        ('unequal_capped', scenario(calendar='unequal', basis='Per working hour', rate=10, cap=50)),
        ('holiday', scenario(calendar='holiday')),
        ('fractional_final', scenario(quantity=12345, scale=0.01, rate=12.3, cap=None)),
        ('unknown', scenario(calendar='unknown')),
        ('completed_before_unknown', scenario(calendar='unknown', quantity=100)),
        ('full_window', scenario(calendar='always', start=today, target=end, axis=end, quantity=100000, rate=1, cap=None)),
        ('end_only', scenario(calendar='always', start=end, target=end, axis=end, quantity=51, rate=50, cap=None)),
    ]
    for name, values in cases:
        for period in [1, 2]:
            add('chart_' + name + ('_week' if period == 1 else '_month'), values, period)
    for name, values in [cases[0], cases[1], cases[3], cases[4], cases[7], cases[9], cases[10]]:
        add('daily_' + name, values, None)
    for selection in [None, '1,2', '99']:
        add('daily_period_' + str(selection), scenario(), None, period_selection=selection)
    for name, values, role in [('zero', scenario(quantity=0), None), ('invalid_calendar', scenario(calendar='duplicate_week'), None),
                                ('unknown_on_start', scenario(calendar='unknown_on_start', start=today, axis=today), None),
                                ('rls_denied', scenario(calendar='base_p2'), 'Fixture Project P1'),
                                ('inverse_hourly_capped', scenario(mode='Meet target date', basis='Per working hour', calendar='unequal', cap=50), None),
                                ('invalid_target', scenario(target=end + dt.timedelta(days=1)), None)]:
        add('chart_rejected_' + name, values, 2, rejected=True, role=role)
        add('daily_rejected_' + name, values, None, rejected=True, role=role)
    output = ARTIFACTS / 'fixture_native_cases.json'
    js(output, dict(marker=MARKER, tests=tests))
    print(json.dumps(dict(tests=len(tests), output=str(output)), indent=2))


if __name__ == '__main__':
    build()
