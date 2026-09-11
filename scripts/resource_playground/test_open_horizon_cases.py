"""Focused open-horizon assertions, independent of the superseded one-year limits."""
import datetime as dt
from fractions import Fraction
import json
import re
import sys

sys.dont_write_bytecode = True
from test_build_open_horizon_fixture import ARTIFACTS, OUTPUT, SOURCE, MARKER, edate
from test_build_fixture import dax, js
import test_window_cases as base


def build():
    manifest = json.loads((OUTPUT / 'fixture-marker.json').read_text(encoding='utf-8-sig'))
    visual_path=SOURCE.parent.parent/'Project Review - Programme (datalake).Report/definition/pages/4c53a34bba9dcc7f3e8c/visuals/c4762ffe207ce780fc4d/visual.json'
    visual=json.loads(visual_path.read_text(encoding='utf-8-sig'))
    bound=[p['field']['Measure']['Property'] for p in visual['visual']['query']['queryState']['Values']['projections'][1:]]
    if bound != ['Scenario Daily Display '+name for name in ['Hours','Capacity','Quantity','Cumulative','Remaining']]:
        raise ValueError('Native test fields must match the current six-field daily PBIR')
    if any(f.get('field',{}).get('Measure',{}).get('Property')=='Scenario Show Daily Row' for f in visual.get('filterConfig',{}).get('filters',[])):
        raise ValueError('Unexpected native daily visual measure filter')
    base.manifest = manifest
    today, end, start = (dt.date.fromisoformat(manifest[k]) for k in ['today', 'windowEnd', 'start'])
    scenario, filters, query = base.scenario, base.filters, base.query
    tests = []
    def add(name, columns, f, expect, split=False, contains=None):
        test = dict(name=name, dax=query(columns, f), expect=expect, contains=contains or {}, role=None, maxRows=1)
        if split:
            test['fragments'] = [dict(name=label, dax=query({label: expression}, f)) for label, expression in columns.items()]
        tests.append(test)
    measures = re.findall(r"^\s*measure '([^']+)'", (SOURCE / 'tables/Resource Scenario Measures.tmdl').read_text(encoding='utf-8-sig'), re.M)
    add('all_current_measures_execute', {name:'['+name+']' for name in measures}, filters(scenario()), {}, split=True)
    long_start = today + dt.timedelta(days=500)
    examples = {
        'within_year_forward': scenario(),
        'within_year_inverse_daily': scenario(mode='Meet target date', cap=None),
        'within_year_inverse_hourly': scenario(mode='Meet target date', calendar='unequal', basis='Per working hour', cap=None),
        'start_beyond_one_year': scenario(start=long_start, target=long_start+dt.timedelta(days=30), axis=long_start, calendar='always'),
        'target_beyond_one_year_inverse': scenario(calendar='always', start=today, target=edate(today,24), axis=edate(today,24), mode='Meet target date', cap=None),
        'finish_beyond_one_year': scenario(calendar='always', start=today, target=today+dt.timedelta(days=30), axis=today, quantity=1000, rate=1, cap=None),
        'all_available_dates_insufficient': scenario(calendar='always', start=today, target=end, axis=end, quantity=100000, rate=1, cap=None),
        'first_permitted_date': scenario(calendar='always', start=today, target=today, axis=today, quantity=1, rate=1, cap=None),
        'last_available_date': scenario(calendar='always', start=end, target=end, axis=end, quantity=50, rate=50, cap=None),
        'past_last_date_unallocated': scenario(calendar='always', start=end, target=end, axis=end, quantity=51, rate=50, cap=None),
        'known_completion_before_unknown': scenario(calendar='unknown', quantity=100),
        'unknown_limits_forecast': scenario(calendar='unknown', quantity=1000),
        'past_unknown_ignored_after_new_start': scenario(calendar='unknown', start=long_start, target=long_start+dt.timedelta(days=30), axis=long_start),
        'unsupported_hourly_inverse_cap': scenario(mode='Meet target date', basis='Per working hour', calendar='unequal', cap=50),
    }
    for name, s in examples.items():
        add(name, {label:'['+measure+']' for label, measure in base.NUMERIC.items()}, filters(s), base.oracle(s), split=True)
    for mode in ['Find finish date','Meet target date']:
        for suffix, edits in [('start_yesterday',dict(start=today-dt.timedelta(days=1))),
                              ('start_after_axis',dict(start=end+dt.timedelta(days=1),target=end+dt.timedelta(days=1))),
                              ('target_after_axis',dict(target=end+dt.timedelta(days=1)))]:
            add(mode+'_'+suffix, base.BLANK_OUTPUTS, filters(scenario(mode=mode,**edits)), dict.fromkeys(base.BLANK_OUTPUTS))
    for tag in ['invalid_week','duplicate_week','unknown_on_start']:
        s = scenario(calendar=tag, start=today, axis=today) if tag=='unknown_on_start' else scenario(calendar=tag)
        expected=dict.fromkeys(base.BLANK_OUTPUTS)
        if tag=='unknown_on_start':expected['HorizonRemaining']=s['quantity']*s['scale']
        add('calendar_rejected_'+tag, base.BLANK_OUTPUTS, filters(s), expected)
    for date in [long_start, end]:
        f=filters(scenario(calendar='always',start=date,target=end,axis=date));f.pop('target')
        add('default_target_'+date.isoformat(), {'Target':'[Scenario Selected Target]','InputIssue':'[Scenario Input Validation]'}, f,
            {'Target':min(date+dt.timedelta(days=30),end).isoformat(),'InputIssue':''})
    multiyear=scenario(calendar='always',start=today,target=today+dt.timedelta(days=30),quantity=1000,rate=1,cap=None)
    for field, bucket in [('Date',today),('Week',today-dt.timedelta(days=today.weekday())),('Month',today.replace(day=1))]:
        f=filters(multiyear);f.pop('axis');f['bucket']=f"TREATAS({{{dax(bucket)}}},'Scenario Date'[{field}])"
        add('unfiltered_horizon_inside_'+field, {'Safe':'[Scenario Safe Through]','Finish':'[Scenario Finish Date]','Remaining':'[Scenario Horizon Remaining]'},f,
            {'Safe':end.isoformat(),'Finish':(today+dt.timedelta(days=999)).isoformat(),'Remaining':0},split=True)
    for field, selected, count in [('Month',[edate(today.replace(day=1),4),edate(today.replace(day=1),18)],None),
                                    ('Week',[today-dt.timedelta(days=today.weekday())+dt.timedelta(days=28),today-dt.timedelta(days=today.weekday())+dt.timedelta(days=700)],14)]:
        f=filters(scenario(calendar='always',start=today,target=end,quantity=100000,rate=1,cap=None));f.pop('axis')
        f['period']=f"TREATAS({{{1 if field=='Week' else 2}}},'Scenario Period'[Period Order])"
        f['sparse']='TREATAS({'+','.join(dax(d) for d in selected)+"},'Scenario Date'["+field+'])'
        last_day=selected[-1]+dt.timedelta(days=6) if field=='Week' else edate(selected[-1],1)-dt.timedelta(days=1)
        quantity=count if count is not None else sum((edate(d,1)-d).days for d in selected)
        add('sparse_'+field+'_beyond_year',{'Raw':'[Scenario Period Quantity]','Chart':'[Scenario Chart Quantity]','Cumulative':'[Scenario Chart Cumulative Quantity]','Safe':'[Scenario Safe Through]'},f,
            {'Raw':quantity,'Chart':quantity,'Cumulative':(last_day-today).days+1,'Safe':end.isoformat()},split=True)
    add('existing_axis_unchanged',{'Start':"MIN('Scenario Date'[Date])",'End':"MAX('Scenario Date'[Date])",'Rows':"COUNTROWS('Scenario Date')"},{},
        {'Start':'2025-01-01','End':end.isoformat(),'Rows':4383})
    js(ARTIFACTS/'fixture_cases.json',dict(marker=MARKER,tests=tests))
    native=[]
    def daily_rows(s):
        spec=manifest['calendars'][s['calendar']]
        quantity=Fraction(str(s['quantity']))*Fraction(str(s['scale']))
        def hours(date):return spec['exceptions'].get(date.isoformat(),spec['week'][date.weekday()])
        unknown=[dt.date.fromisoformat(d) for d,h in spec['exceptions'].items() if h is None and dt.date.fromisoformat(d)>=s['start']]
        safe=min(end,min(unknown)-dt.timedelta(days=1)) if unknown else end
        if s['mode']=='Meet target date':
            if s['target']>safe or (s['basis']=='Per working hour' and s['cap'] is not None):return []
            dates=[s['start']+dt.timedelta(days=i) for i in range((s['target']-s['start']).days+1)]
            work=sum(Fraction(str(hours(d))) if s['basis']=='Per working hour' else int(hours(d)>0) for d in dates)
            if not work:return []
            rate=quantity/work
        else:rate=Fraction(str(s['rate']))
        allocated=Fraction(0);rows=[]
        for offset in range(max(0,(safe-s['start']).days+1)):
            date=s['start']+dt.timedelta(days=offset)
            if allocated>=quantity:break
            h=Fraction(str(hours(date)))
            capacity=(rate*h if s['basis']=='Per working hour' else rate) if h>0 else Fraction(0)
            if s['cap'] is not None:capacity=min(capacity,Fraction(str(s['cap'])))
            amount=min(capacity,quantity-allocated);allocated+=amount
            rows.append({'Scenario Date[Date]':date.isoformat(),'DailyHours':float(h),'DailyCapacity':float(capacity),'Allocated':float(amount),'Cumulative':float(allocated),'DailyRemaining':float(quantity-allocated)})
        return rows
    def add_native(name,s,field,limit):
        f=filters(s);f.pop('axis');f['period']=f"TREATAS({{{1 if field=='Week' else 2}}},'Scenario Period'[Period Order])"
        rows=daily_rows(s)
        if field=='Date':
            measures=['Scenario Daily Display '+x for x in ['Hours','Capacity','Quantity','Cumulative','Remaining']]
            values=','.join(dax(label)+',['+measure+']' for label,measure in zip(['DailyHours','DailyCapacity','Allocated','Cumulative','DailyRemaining'],measures))
        else:
            values='"Allocated",[Scenario Chart Quantity],"Cumulative",[Scenario Chart Cumulative Quantity]'
            grouped={}
            for row in rows:
                date=dt.date.fromisoformat(row['Scenario Date[Date]'])
                bucket=date-dt.timedelta(days=date.weekday()) if field=='Week' else date.replace(day=1)
                target=grouped.setdefault(bucket,{'Scenario Date['+field+']':bucket.isoformat(),'Allocated':0,'Cumulative':0})
                target['Allocated']+=row['Allocated'];target['Cumulative']=row['Cumulative']
            rows=list(grouped.values())
        rows=rows[:limit]
        statement=f"DEFINE VAR __DS0Core=SUMMARIZECOLUMNS('Scenario Date'[{field}],"+','.join(f.values())+','+values+f") VAR __DS0PrimaryWindowed=TOPN({limit},__DS0Core,'Scenario Date'[{field}],1) EVALUATE __DS0PrimaryWindowed ORDER BY 'Scenario Date'[{field}]"
        native.append(dict(name=name,dax=statement,expect={'Buckets':len(rows),'Quantity':sum(r['Allocated'] for r in rows),'FinalCumulative':rows[-1]['Cumulative'] if rows else None},contains={},role=None,maxRows=5000,aggregateRows=True,axisColumn='Scenario Date['+field+']',expectedNativeRows=rows))
    for name,s in [('multi_year_finish',multiyear),('full_available_horizon',examples['all_available_dates_insufficient']),('inverse_beyond_year',examples['target_beyond_one_year_inverse'])]:
        for field in ['Week','Month']:add_native('native_'+name+'_'+field,s,field,1001)
    add_native('native_daily_501_row_page',examples['all_available_dates_insufficient'],'Date',501)
    add_native('native_daily_complete_available_horizon',examples['all_available_dates_insufficient'],'Date',5001)
    add_native('native_daily_start_beyond_year',examples['start_beyond_one_year'],'Date',501)
    add_native('native_daily_last_available_date',examples['last_available_date'],'Date',501)
    js(ARTIFACTS/'fixture_native_cases.json',dict(marker=MARKER,tests=native))
    print(json.dumps(dict(scalarCases=len(tests),nativeCases=len(native),measures=len(measures),today=today.isoformat(),end=end.isoformat(),availableDays=(end-today).days+1),indent=2))


if __name__=='__main__':build()
