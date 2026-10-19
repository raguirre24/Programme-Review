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
    $files = Invoke-ScheduleMetricsDax $target @"
EVALUATE SUMMARIZECOLUMNS('01 XER_TASK'[ProjectCode],'01 XER_TASK'[ProgrammeType],'01 XER_TASK'[UpdateDate],'01 XER_TASK'[filename],"Rows",COUNTROWS('01 XER_TASK'))
"@
    $endpointSnapshots = if ($FixturesOnly) { @() } else { $snapshots }
    foreach ($snapshot in $endpointSnapshots) {
        $filter = Get-DetailFilter $snapshot
        $clock = [Diagnostics.Stopwatch]::StartNew()
        $rows = Invoke-ScheduleMetricsDax $target ($definitions + @"

EVALUATE CALCULATETABLE(ROW("Gauge",[SM Detail Value],"Public",[SM Baseline Coverage %],"History",[SM Detail History],"Maximum",[SM Detail Maximum],"BaselineDate",[SM Detail Baseline Date]),$filter)
"@) -TimeoutSeconds 30
        $clock.Stop()
        Assert-ScheduleMetric (Test-ScheduleMetricNumber $rows[0].'[Gauge]' $rows[0].'[Public]') 'Consolidated coverage differs from SM Baseline Coverage %.'
        $assertions++
        # Coverage compares with the latest BL-tagged snapshot on or before the selected update.
        $latestBaseline = @($files | Where-Object {
            $_.'01 XER_TASK[ProjectCode]' -eq $snapshot.'01 XER_TASK[ProjectCode]' -and
            $_.'01 XER_TASK[ProgrammeType]' -eq $snapshot.'01 XER_TASK[ProgrammeType]' -and
            [datetime]$_.'01 XER_TASK[UpdateDate]' -le [datetime]$snapshot.'01 XER_TASK[UpdateDate]' -and
            $_.'01 XER_TASK[filename]' -match '-BL' } | ForEach-Object { [datetime]$_.'01 XER_TASK[UpdateDate]' } | Sort-Object | Select-Object -Last 1)
        $chosen = if ($null -ne $rows[0].'[BaselineDate]') { [datetime]$rows[0].'[BaselineDate]' } else { $null }
        Assert-ScheduleMetric ($(if ($latestBaseline.Count) { $chosen -eq $latestBaseline[0] } else { $null -eq $chosen })) 'Baseline is not the latest BL-tagged snapshot up to the selected update.'
        $assertions++
        if (-not $ComparePublicOnly) {
            Assert-ScheduleMetric (Test-ScheduleMetricNumber $rows[0].'[Gauge]' $rows[0].'[History]') 'Gauge/history endpoint mismatch.'
            if ($null -ne $rows[0].'[Gauge]') {
                Assert-ScheduleMetric ([double]$rows[0].'[Gauge]' -ge 0 -and [double]$rows[0].'[Gauge]' -le [double]$rows[0].'[Maximum]') 'Coverage exceeds its gauge domain.'
                $assertions++
            }
            $assertions++
        }
        $timings.Add([pscustomobject]@{
            Project = $snapshot.'01 XER_TASK[ProjectCode]'
            Update = $snapshot.'01 XER_TASK[UpdateDate]'
            Seconds = [Math]::Round($clock.Elapsed.TotalSeconds, 3)
        })
        Write-Output ("PASS detail endpoint {0} {1:yyyy-MM-dd}: {2:n3}s" -f $snapshot.'01 XER_TASK[ProjectCode]', [datetime]$snapshot.'01 XER_TASK[UpdateDate]', $clock.Elapsed.TotalSeconds)
    }

    if ($ComparePublicOnly) {
        [pscustomobject]@{ Status = 'PASS'; Scope = 'Consolidated coverage compared with SM Baseline Coverage % through read-only DEFINE.'; Snapshots = $snapshots.Count; Comparisons = $timings.Count; Assertions = $assertions } | ConvertTo-Json
        return
    }

    $latest = $snapshots[-1]
    $filter = Get-DetailFilter $latest
    $historyFilter = Get-DetailFilter $latest -WithoutAxis
    $rows = Invoke-ScheduleMetricsDax $target ($definitions + @"

EVALUATE CALCULATETABLE(SUMMARIZECOLUMNS(UpdateHistory[UpdateDate],"InScope",[SM Detail History In Scope],"Value",[SM Detail History],"Tooltip",[SM Detail Tooltip (History)]),$historyFilter)
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
    Assert-ScheduleMetric (Test-ScheduleMetricNumber $rows[0].'[Ordinary]' $rows[0].'[CompletedOnly]') 'Baseline coverage deliberately uses all statuses and must not change under the page completion filter.'
    $assertions++

    $scopeDate = [datetime]$latest.'01 XER_TASK[UpdateDate]'
    $rows = Invoke-ScheduleMetricsDax $target ($definitions + @"

EVALUATE CALCULATETABLE(ROW("Value",[SM Detail Value],"Scope",[SM Detail Scope Message]),TREATAS({DATE($($scopeDate.Year),$($scopeDate.Month),$($scopeDate.Day))},CurrentDate[UpdateDate]))
"@)
    if (@($snapshots.'01 XER_TASK[ProjectCode]' | Sort-Object -Unique).Count -gt 1) {
        Assert-ScheduleMetric ($null -eq $rows[0].'[Value]' -and $rows[0].'[Scope]' -eq 'Select one project.') 'Multi-project detail context must be unavailable with an explicit diagnostic.'
        $assertions++
    }

    # Unusable baseline evidence must show 0% in both the public and consolidated
    # measures (never blank) and leave an explicit tooltip reason. Repeated or
    # blank activity codes are not unusable evidence: see the cohort cases below.
    $fixtures = @(
        @{ Name = 'No BL provenance'; Variable = 'HasBaselineProvenance'; Value = 'FALSE()'; Overrides = @{ 'Schedule Metric Detail[SM Detail Baseline File]' = '"PROJECT-C-2609_20260930.xer"' } }
    )
    foreach ($fixture in $fixtures) {
        foreach ($name in @('SM Detail Value', 'SM Detail Tooltip')) {
            $fixture.Overrides["Schedule Metric Detail[$name]"] = Set-DetailFixtureVariable $detail.Measures.Find($name).Expression $fixture.Variable $fixture.Value
        }
        $fixtureDefinitions = Get-ScheduleMetricsDefinitions -Model $model -LiveModel $target.Database.Model -Overrides $fixture.Overrides
        $rows = Invoke-ScheduleMetricsDax $target ($fixtureDefinitions + @"

EVALUATE CALCULATETABLE(ROW("Coverage",[SM Baseline Coverage %],"Selected",[SM Detail Value],"Status",[SM Detail Status],"Tooltip",[SM Detail Tooltip]),$filter)
"@) -TimeoutSeconds 30
        Assert-ScheduleMetric ((Test-ScheduleMetricNumber $rows[0].'[Coverage]' 0) -and (Test-ScheduleMetricNumber $rows[0].'[Selected]' 0)) "$($fixture.Name): baseline coverage must show 0%."
        Assert-ScheduleMetric ($rows[0].'[Status]' -eq 'Partial dated coverage') "$($fixture.Name): status must reflect 0% coverage."
        Assert-ScheduleMetric ($rows[0].'[Tooltip]' -match '0%: ') "$($fixture.Name): an explicit tooltip reason is required."
        $assertions += 3
    }

    # A known matched cohort exercises the actual consolidated ratio, status,
    # colour and tooltip rather than a second implementation of their rules.
    $cohortRows = @(1..9 | ForEach-Object { "ROW(""ActivityCode"",""A$_"",""BaselineFinish"",DATE(2025,8,$_))" }) + 'ROW("ActivityCode","A10","BaselineFinish",BLANK())'
    $cohortTable = 'UNION(' + ($cohortRows -join ',') + ')'
    foreach ($case in @(
        @{ Name = 'Partial coverage'; Current = 12; Cohort = $cohortTable; Invalid = 0; Value = 0.75; Status = 'Partial dated coverage'; Colour = '#9C6500'; Tooltip = '9 of 12 activities matched to a dated baseline' },
        @{ Name = 'Full coverage'; Current = 9; Cohort = 'UNION(' + ($cohortRows[0..8] -join ',') + ')'; Invalid = 0; Value = 1; Status = 'Full dated coverage'; Colour = '#4b6110'; Tooltip = '9 of 9 activities matched to a dated baseline' },
        @{ Name = 'Repeated codes disclosed, not penalised'; Current = 12; Cohort = $cohortTable; Invalid = 1; Value = 0.75; Status = 'Partial dated coverage'; Colour = '#9C6500'; Tooltip = 'Duplicate or blank codes: 1.' }
    )) {
        $overrides = @{}
        foreach ($name in @('SM Detail Value', 'SM Detail Tooltip')) {
            $expression = Set-DetailFixtureVariable $detail.Measures.Find($name).Expression 'MatchedActivities' $case.Cohort
            $inputs = @{ 'ScopeMessage' = '""'; 'HasBaselineProvenance' = 'TRUE()'; 'CurrentCount' = "$($case.Current)" }
            # Only the tooltip reads the repeated/blank code count; it no longer gates coverage.
            if ($name -eq 'SM Detail Tooltip') { $inputs['InvalidCodeCount'] = "$($case.Invalid)" }
            foreach ($fixtureInput in $inputs.GetEnumerator()) {
                $expression = Set-DetailFixtureVariable $expression $fixtureInput.Key $fixtureInput.Value
            }
            $overrides["Schedule Metric Detail[$name]"] = $expression
        }
        $caseDefinitions = Get-ScheduleMetricsDefinitions -Model $model -LiveModel $target.Database.Model -Overrides $overrides
        $rows = Invoke-ScheduleMetricsDax $target ($caseDefinitions + @"

EVALUATE CALCULATETABLE(ROW("Value",[SM Detail Value],"Status",[SM Detail Status],"Colour",[SM Detail Colour],"Tooltip",[SM Detail Tooltip]),$filter)
"@)
        Assert-ScheduleMetric (Test-ScheduleMetricNumber $rows[0].'[Value]' $case.Value) "$($case.Name): dated matches / current activities is wrong."
        Assert-ScheduleMetric ($rows[0].'[Status]' -eq $case.Status) "$($case.Name): status mismatch."
        Assert-ScheduleMetric ($rows[0].'[Colour]' -eq $case.Colour) "$($case.Name): colour mismatch."
        Assert-ScheduleMetric ($rows[0].'[Tooltip]' -match [regex]::Escape($case.Tooltip)) "$($case.Name): tooltip must disclose its numerator and denominator."
        $assertions += 4
    }

    $projectGroups = @($snapshots | Group-Object { $_.'01 XER_TASK[ProjectCode]' + '|' + $_.'01 XER_TASK[ProgrammeType]' })
    $historyGroup = @($projectGroups | Where-Object Count -gt 1 | Select-Object -First 1)
    if ($historyGroup.Count) {
        $selected = $historyGroup[0].Group[0]
        $future = [datetime]$historyGroup[0].Group[-1].'01 XER_TASK[UpdateDate]'
        $cutoffFilter = Get-DetailFilter $selected $future
        $rows = Invoke-ScheduleMetricsDax $target ($definitions + @"

EVALUATE CALCULATETABLE(ROW("History",[SM Detail History],"Tooltip",[SM Detail Tooltip (History)]),$cutoffFilter)
"@)
        Assert-ScheduleMetric ($null -eq $rows[0].'[History]' -and $null -eq $rows[0].'[Tooltip]') 'History value and tooltip must be BLANK beyond the selected update.'
        $assertions++
        $project = $selected.'01 XER_TASK[ProjectCode]'.Replace('"', '""')
        $first = [datetime]$selected.'01 XER_TASK[UpdateDate]'
        $earlierFilter = Get-DetailFilter $historyGroup[0].Group[-1] $first
        $rows = Invoke-ScheduleMetricsDax $target ($definitions + @"

EVALUATE CALCULATETABLE(ROW("History",[SM Detail History],"EarlierGauge",CALCULATE([SM Detail Value],REMOVEFILTERS(CurrentDate),TREATAS({DATE($($first.Year),$($first.Month),$($first.Day))},CurrentDate[UpdateDate]))),$earlierFilter)
"@)
        Assert-ScheduleMetric (Test-ScheduleMetricNumber $rows[0].'[History]' $rows[0].'[EarlierGauge]') 'An earlier history point must use its own snapshot while the slicer remains on the latest update.'
        $assertions++
        $rows = Invoke-ScheduleMetricsDax $target ($definitions + @"

EVALUATE CALCULATETABLE(ROW("Value",[SM Detail Value],"Scope",[SM Detail Scope Message]),TREATAS({"$project"},'01 XER_TASK'[ProjectCode]),TREATAS({DATE($($first.Year),$($first.Month),$($first.Day)),DATE($($future.Year),$($future.Month),$($future.Day))},CurrentDate[UpdateDate]))
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

EVALUATE CALCULATETABLE(ROW("Value",[SM Detail Value],"History",[SM Detail History],"Tooltip",[SM Detail Tooltip (History)],"Scope",[SM Detail Scope Message]),$missingFilter)
"@)
        Assert-ScheduleMetric ($null -eq $rows[0].'[Value]' -and $null -eq $rows[0].'[History]' -and $null -eq $rows[0].'[Tooltip]') 'A missing project snapshot must not render a numeric zero or a history tooltip.'
        Assert-ScheduleMetric (-not [string]::IsNullOrWhiteSpace($rows[0].'[Scope]')) 'A missing snapshot requires a diagnostic.'
        $assertions += 2
    }

    [pscustomobject]@{
        Status = 'PASS'
        Scope = 'Read-only DAX DEFINE against existing loaded data; no model or report writes and no refresh.'
        Snapshots = $snapshots.Count
        Endpoints = $timings.Count
        Assertions = $assertions
        MaximumSnapshotQuerySeconds = if ($timings.Count) { ($timings | Measure-Object Seconds -Maximum).Maximum } else { $null }
        Timings = $timings
    } | ConvertTo-Json -Depth 4
} finally {
    $target.Connection.Disconnect()
}
