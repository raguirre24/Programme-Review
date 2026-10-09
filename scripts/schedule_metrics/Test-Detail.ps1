param(
    [string]$ModelRoot,
    [string]$ServerAddress,
    [string]$Catalog,
    [string]$AssemblyDirectory,
    [switch]$FixturesOnly,
    [switch]$ComparePublicOnly
)

. (Join-Path $PSScriptRoot 'Common.ps1')
Import-ScheduleMetricsTom -AssemblyDirectory $AssemblyDirectory
if (-not $ModelRoot) {
    $ModelRoot = Join-Path $PSScriptRoot '../../Project Review - Programme (datalake).SemanticModel/definition'
}
$model = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeModelFromFolder((Resolve-Path -LiteralPath $ModelRoot).Path)
$detail = $model.Tables.Find('Schedule Metric Detail')
$target = Connect-ScheduleMetricsModel -ServerAddress $ServerAddress -Catalog $Catalog
$assertions = 0
$timings = [Collections.Generic.List[object]]::new()

function Get-DetailFilter {
    param($Snapshot, [datetime]$AxisDate = $Snapshot.'01 XER_TASK[UpdateDate]', [switch]$WithoutAxis)
    $project = $Snapshot.'01 XER_TASK[ProjectCode]'.Replace('"', '""')
    $programme = $Snapshot.'01 XER_TASK[ProgrammeType]'.Replace('"', '""')
    $date = [datetime]$Snapshot.'01 XER_TASK[UpdateDate]'
    $filterText = @"
TREATAS({"$project"},'01 XER_TASK'[ProjectCode]),
TREATAS({"$programme"},'01 XER_TASK'[ProgrammeType]),
TREATAS({DATE($($date.Year),$($date.Month),$($date.Day))},CurrentDate[UpdateDate])
"@
    if (-not $WithoutAxis) {
        $filterText += ",TREATAS({DATE($($AxisDate.Year),$($AxisDate.Month),$($AxisDate.Day))},UpdateHistory[UpdateDate])"
    }
    return $filterText
}

function Set-DetailFixtureVariable {
    param([string]$Expression, [string]$Name, [string]$Value)
    # Replace a local input in the actual consolidated expression, retaining its
    # source guard and ratio logic; this never updates a loaded model measure.
    $pattern = '(?ms)^VAR ' + [regex]::Escape($Name) + '\s*=.*?(?=^VAR\s|^RETURN\s)'
    $matches = [regex]::Matches($Expression, $pattern)
    if ($matches.Count -ne 1) { throw "Expected one consolidated variable '$Name'." }
    return [regex]::Replace($Expression, $pattern, "VAR $Name = $Value`n")
}

try {
    $definitions = Get-ScheduleMetricsDefinitions -Model $model -LiveModel $target.Database.Model
    $snapshots = Invoke-ScheduleMetricsDax $target @"
EVALUATE SUMMARIZECOLUMNS('01 XER_TASK'[ProjectCode],'01 XER_TASK'[ProgrammeType],'01 XER_TASK'[UpdateDate],"Rows",COUNTROWS('01 XER_TASK'))
ORDER BY '01 XER_TASK'[ProjectCode],'01 XER_TASK'[ProgrammeType],'01 XER_TASK'[UpdateDate]
"@
    Assert-ScheduleMetric ($snapshots.Count -gt 0) 'Loaded snapshots must exist.'
    $endpointSnapshots = if ($FixturesOnly) { @() } else { $snapshots }
    foreach ($snapshot in $endpointSnapshots) {
        $filter = Get-DetailFilter $snapshot
        $clock = [Diagnostics.Stopwatch]::StartNew()
        if ($ComparePublicOnly) {
            $rows = Invoke-ScheduleMetricsDax $target ($definitions + @"

EVALUATE CALCULATETABLE(SUMMARIZECOLUMNS('Schedule Metric Detail'[Metric ID],"Value",[SM Detail Value],"Public",SWITCH(SELECTEDVALUE('Schedule Metric Detail'[Metric ID]),1,[SM Matched Baseline Missed %],2,[SM Matched Baseline Execution Index],3,[SM Baseline Coverage %],4,[SM Longest Path %]),"Keep",1),$filter)
"@) -TimeoutSeconds 30
            $clock.Stop()
            Assert-ScheduleMetric ($rows.Count -eq 4) 'All four canonical comparisons must be evaluated, including unavailable metrics.'
            $assertions++
            foreach ($row in $rows) {
                Assert-ScheduleMetric (Test-ScheduleMetricNumber $row.'[Value]' $row.'[Public]') 'Consolidated detail value differs from its canonical public measure.'
                $assertions++
            }
            $timings.Add([pscustomobject]@{ Project = $snapshot.'01 XER_TASK[ProjectCode]'; Update = $snapshot.'01 XER_TASK[UpdateDate]'; Seconds = [Math]::Round($clock.Elapsed.TotalSeconds, 3) })
            Write-Output ("PASS canonical detail comparison {0} {1:yyyy-MM-dd}: four options, {2:n3}s" -f $snapshot.'01 XER_TASK[ProjectCode]', [datetime]$snapshot.'01 XER_TASK[UpdateDate]', $clock.Elapsed.TotalSeconds)
            continue
        }
        $rows = Invoke-ScheduleMetricsDax $target ($definitions + @"

EVALUATE CALCULATETABLE(
    SUMMARIZECOLUMNS('Schedule Metric Detail'[Metric ID],
        "Gauge",[SM Detail Value],"History",[SM Detail History],
        "Maximum",[SM Detail Maximum],"Format",[SM Detail Format],"Status",[SM Detail Status]),
    $filter)
"@) -TimeoutSeconds 30
        $clock.Stop()
        Assert-ScheduleMetric ($rows.Count -eq 4) 'Each snapshot must expose four selector options.'
        $assertions++
        foreach ($row in $rows) {
            $id = [int]$row.'Schedule Metric Detail[Metric ID]'
            Assert-ScheduleMetric (Test-ScheduleMetricNumber $row.'[Gauge]' $row.'[History]') "Gauge/history endpoint mismatch for selector $id."
            Assert-ScheduleMetric ($row.'[Format]' -eq $(if ($id -eq 2) { '0.00' } else { '0.0%' })) "Wrong dynamic format for selector $id."
            if ($null -ne $row.'[Gauge]') {
                Assert-ScheduleMetric ([double]$row.'[Gauge]' -ge 0 -and [double]$row.'[Gauge]' -le [double]$row.'[Maximum]') "Selector $id value exceeds its gauge domain."
                $assertions++
            }
            $assertions += 2
        }
        $timings.Add([pscustomobject]@{
            Project = $snapshot.'01 XER_TASK[ProjectCode]'
            Update = $snapshot.'01 XER_TASK[UpdateDate]'
            Seconds = [Math]::Round($clock.Elapsed.TotalSeconds, 3)
        })
        Write-Output ("PASS detail endpoints {0} {1:yyyy-MM-dd}: four options, {2:n3}s" -f $snapshot.'01 XER_TASK[ProjectCode]', [datetime]$snapshot.'01 XER_TASK[UpdateDate]', $clock.Elapsed.TotalSeconds)
    }

    if ($ComparePublicOnly) {
        [pscustomobject]@{ Status = 'PASS'; Scope = 'Consolidated value compared with canonical public component measures through read-only DEFINE.'; Snapshots = $snapshots.Count; SelectorComparisons = $timings.Count * 4; Assertions = $assertions } | ConvertTo-Json
        return
    }

    $latest = $snapshots[-1]
    $filter = Get-DetailFilter $latest
    $historyFilter = Get-DetailFilter $latest -WithoutAxis
    $rows = Invoke-ScheduleMetricsDax $target ($definitions + @"

EVALUATE CALCULATETABLE(SUMMARIZECOLUMNS(UpdateHistory[UpdateDate],"InScope",[SM Detail History In Scope],"Value",[SM Detail History],"Tooltip",[SM Detail Tooltip (History)]),$historyFilter,TREATAS({1},'Schedule Metric Detail'[Metric ID]))
"@)
    $expectedPeriods = @($snapshots | Where-Object {
        $_.'01 XER_TASK[ProjectCode]' -eq $latest.'01 XER_TASK[ProjectCode]' -and
        $_.'01 XER_TASK[ProgrammeType]' -eq $latest.'01 XER_TASK[ProgrammeType]'
    })
    Assert-ScheduleMetric ($rows.Count -eq $expectedPeriods.Count) 'Every existing whole-project snapshot must remain in the categorical history scope.'
    $assertions++
    foreach ($row in $rows) {
        Assert-ScheduleMetric (Test-ScheduleMetricNumber $row.'[InScope]' 1) 'Existing history periods must remain visible independently of assessment availability.'
        Assert-ScheduleMetric (-not [string]::IsNullOrWhiteSpace($row.'[Tooltip]')) 'Every visible history period must explain the diagnostic or its unavailable inputs.'
        if ($null -eq $row.'[Value]') {
            Assert-ScheduleMetric ($row.'[Tooltip]' -match 'N/A|Select one|No snapshot') 'An unassessed history period must retain an explicit reason.'
            $assertions++
        }
        $assertions += 2
    }
    $rows = Invoke-ScheduleMetricsDax $target ($definitions + @"

EVALUATE CALCULATETABLE(ROW("Ordinary",[SM Detail Value],"CompletedOnly",CALCULATE([SM Detail Value],TREATAS({"Complete"},Filter_Activity_Status[status_code]))),$filter)
"@)
    Assert-ScheduleMetric (Test-ScheduleMetricNumber $rows[0].'[Ordinary]' $rows[0].'[CompletedOnly]') 'Matched baseline metrics deliberately use all statuses and must not change under the page completion filter.'
    $assertions++

    $scopeDate = [datetime]$latest.'01 XER_TASK[UpdateDate]'
    $rows = Invoke-ScheduleMetricsDax $target ($definitions + @"

EVALUATE CALCULATETABLE(ROW("Value",[SM Detail Value],"Scope",[SM Detail Scope Message]),TREATAS({DATE($($scopeDate.Year),$($scopeDate.Month),$($scopeDate.Day))},CurrentDate[UpdateDate]),TREATAS({4},'Schedule Metric Detail'[Metric ID]))
"@)
    if (@($snapshots.'01 XER_TASK[ProjectCode]' | Sort-Object -Unique).Count -gt 1) {
        Assert-ScheduleMetric ($null -eq $rows[0].'[Value]' -and $rows[0].'[Scope]' -eq 'Select one project.') 'Multi-project detail context must be unavailable with an explicit diagnostic.'
        $assertions++
    }
    $fixtures = @(
        @{ Name = 'No BL provenance'; Variable = 'HasBaselineProvenance'; Value = 'FALSE()'; Overrides = @{ 'Schedule Metric Detail[SM Detail Baseline File]' = '"PROJECT-C-2609_20260930.xer"' }; AllBaselineBlank = $true },
        @{ Name = 'Blank or duplicate identities'; Variable = 'InvalidCodeCount'; Value = '1'; Overrides = @{ 'Schedule Metric Detail[SM Detail Invalid Activity Codes]' = '1' }; AllBaselineBlank = $true },
        @{ Name = 'No matched due activities'; Variable = 'DueCount'; Value = '0'; Overrides = @{ 'Schedule Metric Detail[SM Detail Baseline Due]' = '0' }; AllBaselineBlank = $false }
    )
    foreach ($fixture in $fixtures) {
        $fixture.Overrides['Schedule Metric Detail[SM Detail Value]'] = Set-DetailFixtureVariable $detail.Measures.Find('SM Detail Value').Expression $fixture.Variable $fixture.Value
        $fixtureDefinitions = Get-ScheduleMetricsDefinitions -Model $model -LiveModel $target.Database.Model -Overrides $fixture.Overrides
        $rows = Invoke-ScheduleMetricsDax $target ($fixtureDefinitions + @"

EVALUATE CALCULATETABLE(ROW("Missed",[SM Matched Baseline Missed %],"Execution",[SM Matched Baseline Execution Index],"Coverage",[SM Baseline Coverage %],"Reason",[SM Detail Baseline Message],"SelectedMissed",CALCULATE([SM Detail Value],REMOVEFILTERS('Schedule Metric Detail'),TREATAS({1},'Schedule Metric Detail'[Metric ID])),"SelectedExecution",CALCULATE([SM Detail Value],REMOVEFILTERS('Schedule Metric Detail'),TREATAS({2},'Schedule Metric Detail'[Metric ID])),"SelectedCoverage",CALCULATE([SM Detail Value],REMOVEFILTERS('Schedule Metric Detail'),TREATAS({3},'Schedule Metric Detail'[Metric ID]))),$filter)
"@) -TimeoutSeconds 30
        Assert-ScheduleMetric ($null -eq $rows[0].'[Missed]' -and $null -eq $rows[0].'[Execution]') "$($fixture.Name): matched metrics must be BLANK."
        Assert-ScheduleMetric (-not [string]::IsNullOrWhiteSpace($rows[0].'[Reason]')) "$($fixture.Name): an explicit diagnostic is required."
        Assert-ScheduleMetric (Test-ScheduleMetricNumber $rows[0].'[Missed]' $rows[0].'[SelectedMissed]') "$($fixture.Name): consolidated missed guard differs."
        Assert-ScheduleMetric (Test-ScheduleMetricNumber $rows[0].'[Execution]' $rows[0].'[SelectedExecution]') "$($fixture.Name): consolidated execution guard differs."
        Assert-ScheduleMetric (Test-ScheduleMetricNumber $rows[0].'[Coverage]' $rows[0].'[SelectedCoverage]') "$($fixture.Name): consolidated coverage guard differs."
        $assertions += 3
        if ($fixture.AllBaselineBlank) {
            Assert-ScheduleMetric ($null -eq $rows[0].'[Coverage]') "$($fixture.Name): baseline coverage must be BLANK."
            $assertions++
        }
        $assertions += 2
    }

    $aboveOneValue = Set-DetailFixtureVariable $detail.Measures.Find('SM Detail Value').Expression 'BaselineMessage' '""'
    $aboveOneValue = Set-DetailFixtureVariable $aboveOneValue 'CompletedCount' '15'
    $aboveOneValue = Set-DetailFixtureVariable $aboveOneValue 'ExecutionDueCount' '10'
    $aboveOne = Get-ScheduleMetricsDefinitions -Model $model -LiveModel $target.Database.Model -Overrides @{
        'Schedule Metric Detail[SM Detail Value]' = $aboveOneValue
        'Schedule Metric Detail[SM Detail Baseline Message]' = '""'
        'Schedule Metric Detail[SM Detail Matched Completed]' = '15'
        'Schedule Metric Detail[SM Detail Execution Due]' = '10'
    }
    $rows = Invoke-ScheduleMetricsDax $target ($aboveOne + @"

EVALUATE CALCULATETABLE(ROW("Value",[SM Detail Value],"Maximum",[SM Detail Maximum],"Format",[SM Detail Format]),$filter,TREATAS({2},'Schedule Metric Detail'[Metric ID]))
"@)
    Assert-ScheduleMetric (Test-ScheduleMetricNumber $rows[0].'[Value]' 1.5) 'Execution index must preserve a value above one.'
    Assert-ScheduleMetric (Test-ScheduleMetricNumber $rows[0].'[Maximum]' 1.5) 'Gauge maximum must contain an execution index above one.'
    Assert-ScheduleMetric ($rows[0].'[Format]' -eq '0.00') 'Execution index must use ratio format.'
    $assertions += 3

    # Mixed usable/unusable rows exercise the actual canonical expressions and
    # consolidated visual expression, not a second implementation of their rules.
    # The fixture distinguishes unrelated Start/status warnings from missing
    # finish dates, unknown completion state, and genuine early completion.
    $cohortRows = @(
        'ROW("BaselineFinish",DATE(2026,8,1),"CurrentFinish",DATE(2026,8,2),"CurrentStart",DATE(2026,7,1),"ActualFinish",DATE(2026,8,2),"ActivityStatus","Complete")',
        'ROW("BaselineFinish",DATE(2026,8,1),"CurrentFinish",DATE(2026,9,2),"CurrentStart",DATE(2026,7,1),"ActualFinish",DATE(2026,9,2),"ActivityStatus","Complete")',
        'ROW("BaselineFinish",DATE(2026,8,1),"CurrentFinish",DATE(2026,8,2),"CurrentStart",DATE(2026,7,1),"ActualFinish",DATE(2026,8,2),"ActivityStatus","In Progress")',
        'ROW("BaselineFinish",DATE(2026,8,1),"CurrentFinish",DATE(2026,8,3),"CurrentStart",DATE(2026,7,1),"ActualFinish",DATE(2026,8,2),"ActivityStatus","Complete")',
        'ROW("BaselineFinish",DATE(2026,8,1),"CurrentFinish",DATE(2026,8,2),"CurrentStart",BLANK(),"ActualFinish",DATE(2026,8,2),"ActivityStatus","Complete")',
        'ROW("BaselineFinish",BLANK(),"CurrentFinish",DATE(2026,8,2),"CurrentStart",DATE(2026,7,1),"ActualFinish",DATE(2026,8,2),"ActivityStatus","Complete")',
        'ROW("BaselineFinish",DATE(2026,8,1),"CurrentFinish",BLANK(),"CurrentStart",DATE(2026,7,1),"ActualFinish",BLANK(),"ActivityStatus","Not Started")',
        'ROW("BaselineFinish",DATE(2026,8,1),"CurrentFinish",DATE(2026,8,2),"CurrentStart",DATE(2026,7,1),"ActualFinish",BLANK(),"ActivityStatus","Unsupported")',
        'ROW("BaselineFinish",DATE(2026,8,1),"CurrentFinish",DATE(2026,8,2),"CurrentStart",DATE(2026,9,2),"ActualFinish",BLANK(),"ActivityStatus","In Progress")',
        'ROW("BaselineFinish",DATE(2026,9,10),"CurrentFinish",DATE(2026,8,2),"CurrentStart",DATE(2026,7,1),"ActualFinish",DATE(2026,8,2),"ActivityStatus","Complete")'
    )
    $cohortTable = 'UNION(' + ($cohortRows -join ',') + ')'
    $partialOverrides = @{
        'Schedule Metric Detail[SM Detail Baseline Message]' = '""'
        'Schedule Metric Detail[SM Detail Matched Activities]' = '10'
        'Schedule Metric Detail[SM Detail Dated Matches]' = '9'
    }
    foreach ($name in @('SM Detail Baseline Due','SM Detail Missed Due','SM Detail Missed Assessable Due','SM Detail Matched Completed','SM Detail Execution Activities','SM Detail Execution Due')) {
        $expression = Set-DetailFixtureVariable $detail.Measures.Find($name).Expression 'MatchedActivities' $cohortTable
        $expression = Set-DetailFixtureVariable $expression 'StatusDate' 'DATE(2026,8,31)'
        $partialOverrides["Schedule Metric Detail[$name]"] = $expression
    }
    foreach ($name in @('SM Detail Value','SM Detail Tooltip')) {
        $expression = Set-DetailFixtureVariable $detail.Measures.Find($name).Expression 'MatchedActivities' $cohortTable
        foreach ($input in @{
            'StatusDate' = 'DATE(2026,8,31)'; 'BaselineMessage' = '""'; 'ScopeMessage' = '""'
            'HasBaselineProvenance' = 'TRUE()'; 'InvalidCodeCount' = '0'
            'BaselineCount' = '10'; 'CurrentCount' = '10'; 'MissingBaselineCount' = '1'
        }.GetEnumerator()) {
            $expression = Set-DetailFixtureVariable $expression $input.Key $input.Value
        }
        $partialOverrides["Schedule Metric Detail[$name]"] = $expression
    }
    $partialDefinitions = Get-ScheduleMetricsDefinitions -Model $model -LiveModel $target.Database.Model -Overrides $partialOverrides
    $rows = Invoke-ScheduleMetricsDax $target ($partialDefinitions + @"

EVALUATE CALCULATETABLE(ROW("Due",[SM Detail Baseline Due],"MissedDue",[SM Detail Missed Due],"AssessedDue",[SM Detail Missed Assessable Due],"ExecutionCohort",[SM Detail Execution Activities],"ExecutionDue",[SM Detail Execution Due],"Completed",[SM Detail Matched Completed],"Missed",[SM Matched Baseline Missed %],"Execution",[SM Matched Baseline Execution Index],"SelectedMissed",CALCULATE([SM Detail Value],TREATAS({1},'Schedule Metric Detail'[Metric ID])),"SelectedExecution",CALCULATE([SM Detail Value],TREATAS({2},'Schedule Metric Detail'[Metric ID])),"MissedTooltip",CALCULATE([SM Detail Tooltip],TREATAS({1},'Schedule Metric Detail'[Metric ID])),"ExecutionTooltip",CALCULATE([SM Detail Tooltip],TREATAS({2},'Schedule Metric Detail'[Metric ID]))),$filter)
"@)
    foreach ($expected in @{ Due=8; MissedDue=7; AssessedDue=7; ExecutionCohort=6; ExecutionDue=5; Completed=4; Missed=1; Execution=0.8; SelectedMissed=1; SelectedExecution=0.8 }.GetEnumerator()) {
        Assert-ScheduleMetric (Test-ScheduleMetricNumber $rows[0].("["+$expected.Key+"]") $expected.Value) "Partial cohort fixture: $($expected.Key) must use only its required inputs."
        $assertions++
    }
    Assert-ScheduleMetric ($rows[0].'[MissedTooltip]' -match 'Assessed 7 / 8' -and $rows[0].'[MissedTooltip]' -match 'excluded 1 due matches' -and $rows[0].'[MissedTooltip]' -match 'Partial input coverage') 'Missed tooltip must disclose its usable due cohort and missing finish exclusion.'
    Assert-ScheduleMetric ($rows[0].'[ExecutionTooltip]' -match '6 / 10 matches; excluded 4' -and $rows[0].'[ExecutionTooltip]' -match 'including 3 of 8 known due' -and $rows[0].'[ExecutionTooltip]' -match 'Partial input coverage') 'Execution tooltip must disclose a consistent known-completion cohort.'
    $assertions += 2

    foreach ($id in @(1,2)) {
        $rows = Invoke-ScheduleMetricsDax $target ($partialDefinitions + @"

EVALUATE CALCULATETABLE(ROW("Value",[SM Detail Value],"Status",[SM Detail Status],"Colour",[SM Detail Colour]),$filter,TREATAS({$id},'Schedule Metric Detail'[Metric ID]))
"@)
        Assert-ScheduleMetric ($null -ne $rows[0].'[Value]' -and $rows[0].'[Status]' -like 'Partial inputs; *') 'A partial metric must retain its numeric result and explicitly label partial inputs.'
        Assert-ScheduleMetric ($rows[0].'[Colour]' -eq '#6f0516') 'Partial input coverage must not mask the out-of-target severity of these matched metrics.'
        $assertions += 2
    }

    # If every required input is unavailable, keep BLANK; a broad warning alone
    # must not hide the usable source-derived cohort.
    foreach ($zero in @(@{ Variable='AssessedDueCount'; Measure='SM Detail Missed Assessable Due'; ID=1 },@{ Variable='ExecutionDueCount'; Measure='SM Detail Execution Due'; ID=2 })) {
        $zeroOverrides = $partialOverrides.Clone()
        $zeroOverrides["Schedule Metric Detail[$($zero.Measure)]"] = '0'
        foreach ($name in @('SM Detail Value','SM Detail Tooltip')) {
            $zeroOverrides["Schedule Metric Detail[$name]"] = Set-DetailFixtureVariable $partialOverrides["Schedule Metric Detail[$name]"] $zero.Variable '0'
        }
        $zeroDefinitions = Get-ScheduleMetricsDefinitions -Model $model -LiveModel $target.Database.Model -Overrides $zeroOverrides
        $rows = Invoke-ScheduleMetricsDax $target ($zeroDefinitions + @"

EVALUATE CALCULATETABLE(ROW("Value",[SM Detail Value],"Tooltip",[SM Detail Tooltip],"Public",IF(SELECTEDVALUE('Schedule Metric Detail'[Metric ID])=1,[SM Matched Baseline Missed %],[SM Matched Baseline Execution Index])),$filter,TREATAS({$($zero.ID)},'Schedule Metric Detail'[Metric ID]))
"@)
        Assert-ScheduleMetric ($null -eq $rows[0].'[Value]' -and $null -eq $rows[0].'[Public]') 'No usable denominator must remain BLANK in canonical and selected measures.'
        Assert-ScheduleMetric ($rows[0].'[Tooltip]' -match 'N/A: no due matches') 'No usable denominator must retain an explicit tooltip reason.'
        $assertions += 2
    }

    $warningOverrides = @{
        'Schedule Metric Detail[SM Detail Invalid Matched Records]' = '999'
        'Schedule Metric Detail[SM Detail Value]' = (Set-DetailFixtureVariable $detail.Measures.Find('SM Detail Value').Expression 'InvalidMatchedCount' '999')
    }
    $warningDefinitions = Get-ScheduleMetricsDefinitions -Model $model -LiveModel $target.Database.Model -Overrides $warningOverrides
    $rows = Invoke-ScheduleMetricsDax $target ($warningDefinitions + @"

EVALUATE CALCULATETABLE(ROW("Value",[SM Detail Value],"Public",[SM Matched Baseline Missed %],"Reason",[SM Detail Baseline Message]),$filter,TREATAS({1},'Schedule Metric Detail'[Metric ID]))
"@)
    Assert-ScheduleMetric (Test-ScheduleMetricNumber $rows[0].'[Value]' $rows[0].'[Public]') 'A broad source warning must not gate an otherwise usable finish comparison.'
    Assert-ScheduleMetric ($rows[0].'[Reason]' -notmatch 'invalid actual|inconsistent status') 'Broad source warnings must not create an all-or-nothing baseline error.'
    $assertions += 2

    $projectGroups = @($snapshots | Group-Object { $_.'01 XER_TASK[ProjectCode]' + '|' + $_.'01 XER_TASK[ProgrammeType]' })
    $historyGroup = @($projectGroups | Where-Object Count -gt 1 | Select-Object -First 1)
    if ($historyGroup.Count) {
        $selected = $historyGroup[0].Group[0]
        $future = [datetime]$historyGroup[0].Group[-1].'01 XER_TASK[UpdateDate]'
        $cutoffFilter = Get-DetailFilter $selected $future
        $rows = Invoke-ScheduleMetricsDax $target ($definitions + @"

EVALUATE CALCULATETABLE(ROW("History",[SM Detail History],"Tooltip",[SM Detail Tooltip (History)]),$cutoffFilter,TREATAS({4},'Schedule Metric Detail'[Metric ID]))
"@)
        Assert-ScheduleMetric ($null -eq $rows[0].'[History]' -and $null -eq $rows[0].'[Tooltip]') 'History value and tooltip must be BLANK beyond the selected update.'
        $assertions++
        $project = $selected.'01 XER_TASK[ProjectCode]'.Replace('"', '""')
        $first = [datetime]$selected.'01 XER_TASK[UpdateDate]'
        $earlierFilter = Get-DetailFilter $historyGroup[0].Group[-1] $first
        $rows = Invoke-ScheduleMetricsDax $target ($definitions + @"

EVALUATE CALCULATETABLE(ROW("History",[SM Detail History],"EarlierGauge",CALCULATE([SM Detail Value],REMOVEFILTERS(CurrentDate),TREATAS({DATE($($first.Year),$($first.Month),$($first.Day))},CurrentDate[UpdateDate]))),$earlierFilter,TREATAS({4},'Schedule Metric Detail'[Metric ID]))
"@)
        Assert-ScheduleMetric (Test-ScheduleMetricNumber $rows[0].'[History]' $rows[0].'[EarlierGauge]') 'An earlier history point must use its own snapshot while the slicer remains on the latest update.'
        $assertions++
        $rows = Invoke-ScheduleMetricsDax $target ($definitions + @"

EVALUATE CALCULATETABLE(ROW("Value",[SM Detail Value],"Scope",[SM Detail Scope Message]),TREATAS({"$project"},'01 XER_TASK'[ProjectCode]),TREATAS({DATE($($first.Year),$($first.Month),$($first.Day)),DATE($($future.Year),$($future.Month),$($future.Day))},CurrentDate[UpdateDate]),TREATAS({4},'Schedule Metric Detail'[Metric ID]))
"@)
        Assert-ScheduleMetric ($null -eq $rows[0].'[Value]' -and $rows[0].'[Scope]' -eq 'Select one update.') 'Multiple selected updates must be unavailable with an explicit diagnostic.'
        $assertions++
    }

    $globalLatest = [datetime]($snapshots | Sort-Object { [datetime]$_.'01 XER_TASK[UpdateDate]' } | Select-Object -Last 1).'01 XER_TASK[UpdateDate]'
    $missingGroup = @($projectGroups | Where-Object { [datetime]$_.Group[-1].'01 XER_TASK[UpdateDate]' -lt $globalLatest } | Select-Object -First 1)
    if ($missingGroup.Count) {
        $missing = $missingGroup[0].Group[-1].PSObject.Copy()
        $missing.'01 XER_TASK[UpdateDate]' = $globalLatest
        $missingFilter = Get-DetailFilter $missing
        $rows = Invoke-ScheduleMetricsDax $target ($definitions + @"

EVALUATE CALCULATETABLE(ROW("Value",[SM Detail Value],"History",[SM Detail History],"Tooltip",[SM Detail Tooltip (History)],"Scope",[SM Detail Scope Message]),$missingFilter,TREATAS({4},'Schedule Metric Detail'[Metric ID]))
"@)
        Assert-ScheduleMetric ($null -eq $rows[0].'[Value]' -and $null -eq $rows[0].'[History]' -and $null -eq $rows[0].'[Tooltip]') 'A missing project snapshot must not render a numeric zero or a history tooltip.'
        Assert-ScheduleMetric (-not [string]::IsNullOrWhiteSpace($rows[0].'[Scope]')) 'A missing snapshot requires a diagnostic.'
        $assertions += 2
    }

    [pscustomobject]@{
        Status = 'PASS'
        Scope = 'Read-only DAX DEFINE against existing loaded data; no model or report writes and no refresh.'
        Snapshots = $snapshots.Count
        SelectorEndpoints = $timings.Count * 4
        Assertions = $assertions
        MaximumSnapshotQuerySeconds = if ($timings.Count) { ($timings | Measure-Object Seconds -Maximum).Maximum } else { $null }
        Timings = $timings
    } | ConvertTo-Json -Depth 4
} finally {
    $target.Connection.Disconnect()
}
