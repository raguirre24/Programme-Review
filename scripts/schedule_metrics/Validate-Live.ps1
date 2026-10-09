[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path,
    [string]$ServerAddress,
    [string]$Catalog,
    [string]$AssemblyDirectory,
    [string]$OutputPath,
    [switch]$UseLoadedModel,
    [switch]$CompileOnly
)

. (Join-Path $PSScriptRoot 'Common.ps1')
Import-ScheduleMetricsTom -AssemblyDirectory $AssemblyDirectory
$definitionPath = Join-Path $RepositoryRoot 'Project Review - Programme (datalake).SemanticModel/definition'
$proposed = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeModelFromFolder($definitionPath)
$target = Connect-ScheduleMetricsModel -ServerAddress $ServerAddress -Catalog $Catalog
$checks = [Collections.Generic.List[string]]::new()
$result = [ordered]@{
    status = 'running'; server = $target.Address; catalog = $target.Database.Name
    modelWrites = $false; refreshedSourceData = $false; definitions = $definitionPath
    executionMode = if ($UseLoadedModel) { 'loaded model; no DEFINE overrides' } else { 'query-scoped proposed expressions' }
}

function Quote-DaxString([string]$Value) { return '"' + $Value.Replace('"', '""') + '"' }
function Date-DaxLiteral([datetime]$Value) { return "DATE($($Value.Year),$($Value.Month),$($Value.Day))" }
function Get-MetricProjections([string[]]$Names, [string]$Suffix = '') {
    return (($Names | ForEach-Object {
        (Quote-DaxString $_) + ',[' + ($_ + $Suffix).Replace(']', ']]') + ']'
    }) -join ",`n")
}

try {
    $definitions = ''
    $metricsTable = $proposed.Tables['XER Metrics']
    if ($UseLoadedModel) {
        $loadedTable = $target.Database.Model.Tables['XER Metrics']
        Assert-ScheduleMetric ($loadedTable.Measures.Count -eq $metricsTable.Measures.Count) 'Loaded/source core measure counts differ.'
        foreach ($measure in $metricsTable.Measures) {
            Assert-ScheduleMetric ($loadedTable.Measures.Contains($measure.Name)) "Loaded measure missing: $($measure.Name)."
            $loaded = $loadedTable.Measures[$measure.Name]
            $expectedExpression = ([string]$measure.Expression).Replace("`r`n", "`n").Trim()
            $actualExpression = ([string]$loaded.Expression).Replace("`r`n", "`n").Trim()
            Assert-ScheduleMetric ($actualExpression -ceq $expectedExpression) "Loaded/source expression differs: $($measure.Name)."
            Assert-ScheduleMetric ([string]$loaded.FormatString -ceq [string]$measure.FormatString) "Loaded/source format differs: $($measure.Name)."
            Assert-ScheduleMetric ([string]$loaded.LineageTag -ceq [string]$measure.LineageTag) "Loaded/source lineage differs: $($measure.Name)."
        }
        $checks.Add("All $($metricsTable.Measures.Count) loaded core measures match source expressions, formats and lineage.")
        $metricsTable = $loadedTable
    } else {
        $definitions = Get-ScheduleMetricsDefinitions -Model $proposed -LiveModel $target.Database.Model
    }
    $rates = @('MissingPredecessor%', 'MissingSuccessor%', 'HighFloat%', 'HighDur%', 'Lags%',
        '<0Lead%', '<0Float%', '0Float%', 'Constraint%', 'Score',
        'SM Missing Logic %', 'SM FS %', 'SM Invalid Dates %')
    $availableRates = @($rates | Where-Object { $metricsTable.Measures.Contains($_) })
    $helpers = @('Task_Count', 'SM Eligible Relationship Count', 'SM Date Eligible Count',
        'SM Positive Lag Count', 'SM Missing Logic Count', 'SM FS Count', 'SM Restrictive Primary Count',
        'SM Invalid Dates Count', 'SM Applicable Checks', 'SM Assessed Checks', 'SM Passed Checks',
        'SM Partial Checks', 'SM Review Checks', 'SM Priority Checks', 'Float >44', 'Dur >44', 'Task_Count_Negative_Float', 'Task_Count_Float_0', 'Leads<0d',
        'SM Missing Float Count', 'SM Missing Duration Count', 'SM Missing Lag Count',
        'SM Unknown Relationship Type Count', 'SM Unknown Constraint Count') |
        Where-Object { $metricsTable.Measures.Contains($_) }
    $colourMeasures = [ordered]@{
        'HighFloat%' = 'SM High Float Colour'; 'HighDur%' = 'SM High Duration Colour';
        '<0Lead%' = 'SM Leads Colour'; 'Lags%' = 'SM Lags Colour';
        'SM Missing Logic %' = 'SM Missing Logic Colour'; 'SM FS %' = 'SM FS Colour';
        '<0Float%' = 'SM Negative Float Colour'; 'Constraint%' = 'SM Constraints Colour';
        'SM Invalid Dates %' = 'SM Invalid Dates Colour'; 'Score' = 'SM Score Colour'
    }
    $presentationMeasures = @()
    if ($UseLoadedModel) { $presentationMeasures = @($colourMeasures.Values) + @('SM Coverage Tooltip', 'SM Score Status', 'SM Score Coverage') }
    $pageFilters = @'
TREATAS({"Activity","Milestone"},'01 XER_TASK'[TaskType_Classified]),
TREATAS({"Not Started","In Progress"},'01 XER_TASK'[status_code]),
TREATAS({FALSE},'01 XER_TASK'[Is Unscheduled]),
TREATAS({FALSE},'01 XER_TASK'[IsExcludedFromDataLake])
'@
    $projection = Get-MetricProjections -Names @($availableRates + $helpers + $presentationMeasures)
    $inventoryQuery = @"
EVALUATE SUMMARIZECOLUMNS(
'01 XER_TASK'[ProjectCode], '01 XER_TASK'[ProgrammeType], '01 XER_TASK'[UpdateDate],
$pageFilters,
"Rows",COUNTROWS('01 XER_TASK'))
ORDER BY '01 XER_TASK'[ProjectCode], '01 XER_TASK'[ProgrammeType], '01 XER_TASK'[UpdateDate]
"@
    $inventory = Invoke-ScheduleMetricsDax -Target $target -Query $inventoryQuery
    $snapshotList = [Collections.Generic.List[object]]::new()
    foreach ($item in $inventory) {
        $project = Quote-DaxString $item.'01 XER_TASK[ProjectCode]'
        $programme = Quote-DaxString $item.'01 XER_TASK[ProgrammeType]'
        $pointDate = Date-DaxLiteral ([datetime]$item.'01 XER_TASK[UpdateDate]')
        $snapshotQuery = @"
$definitions
EVALUATE CALCULATETABLE(ROW($projection),
TREATAS({$project},'01 XER_TASK'[ProjectCode]),
TREATAS({$programme},'01 XER_TASK'[ProgrammeType]),
TREATAS({$pointDate},CurrentDate[UpdateDate]),$pageFilters)
"@
        $values = Invoke-ScheduleMetricsDax -Target $target -Query $snapshotQuery
        $combined = [ordered]@{
            '01 XER_TASK[ProjectCode]' = $item.'01 XER_TASK[ProjectCode]'
            '01 XER_TASK[ProgrammeType]' = $item.'01 XER_TASK[ProgrammeType]'
            '01 XER_TASK[UpdateDate]' = $item.'01 XER_TASK[UpdateDate]'
        }
        foreach ($property in $values[0].PSObject.Properties) { $combined[$property.Name] = $property.Value }
        $snapshotList.Add([pscustomobject]$combined)
    }
    $snapshots = $snapshotList.ToArray()
    Assert-ScheduleMetric ($snapshots.Count -gt 0) 'No project snapshots were evaluated.'
    $observedRates = [ordered]@{
        'HighFloat%' = @('Float >44', 'Task_Count', 'SM Missing Float Count')
        '<0Float%' = @('Task_Count_Negative_Float', 'Task_Count', 'SM Missing Float Count')
        '0Float%' = @('Task_Count_Float_0', 'Task_Count', 'SM Missing Float Count')
        'HighDur%' = @('Dur >44', 'Task_Count', 'SM Missing Duration Count')
        'Lags%' = @('SM Positive Lag Count', 'SM Eligible Relationship Count', 'SM Missing Lag Count')
        '<0Lead%' = @('Leads<0d', 'SM Eligible Relationship Count', 'SM Missing Lag Count')
        'SM FS %' = @('SM FS Count', 'SM Eligible Relationship Count', 'SM Unknown Relationship Type Count')
        'Constraint%' = @('SM Restrictive Primary Count', 'Task_Count', 'SM Unknown Constraint Count')
    }
    $scoreLimits = [ordered]@{
        'SM Missing Logic %' = 0.05; '<0Lead%' = 0; 'Lags%' = 0.05; 'SM FS %' = 0.9;
        'Constraint%' = 0.05; '<0Float%' = 0; 'HighDur%' = 0.05; 'SM Invalid Dates %' = 0
    }
    $reviewLimits = @{ 'SM Missing Logic %'=.10; '<0Lead%'=.01; 'Lags%'=.10; 'SM FS %'=.80;
        'Constraint%'=.10; '<0Float%'=.01; 'HighDur%'=.10; 'SM Invalid Dates %'=.001 }
    $availableRecordChecks = 0
    $scoreCoverageChecks = 0
    $colourChecks = 0
    $tooltipCountChecks = 0
    foreach ($row in $snapshots) {
        foreach ($name in $availableRates) {
            $value = $row.PSObject.Properties["[$name]"].Value
            if ($null -ne $value) {
                Assert-ScheduleMetric ([double]::IsFinite([double]$value)) "$name returned NaN/Infinity."
                Assert-ScheduleMetric ([double]$value -ge 0 -and [double]$value -le 1.0000000001) "$name is outside [0,1]."
            }
        }
        foreach ($name in $observedRates.Keys) {
            $spec = $observedRates[$name]
            $count = $row.PSObject.Properties["[$($spec[0])]"].Value
            $eligible = $row.PSObject.Properties["[$($spec[1])]"].Value
            $excluded = $row.PSObject.Properties["[$($spec[2])]"].Value
            $known = [double]$eligible - [double]$excluded
            Assert-ScheduleMetric ($known -ge 0) "$name has more excluded than eligible records."
            $expected = if ($known -gt 0 -and $null -ne $count) { [double]$count / $known } else { $null }
            $actual = $row.PSObject.Properties["[$name]"].Value
            Assert-ScheduleMetric (Test-ScheduleMetricNumber $actual $expected) "$name does not use its available-record denominator."
            $availableRecordChecks++
        }
        $assessed = 0
        $passed = 0
        $review = 0
        $priority = 0
        $pointsTotal = 0.0
        $bandPoints = @{}
        $partial = 0
        foreach ($name in $scoreLimits.Keys) {
            $value = $row.PSObject.Properties["[$name]"].Value
            if ($null -eq $value) { $bandPoints[$name]=$null; continue }
            $assessed++
            if (($name -eq 'SM FS %' -and $value -ge $scoreLimits[$name]) -or
                ($name -ne 'SM FS %' -and $value -le $scoreLimits[$name])) { $passed++; $points=1.0 }
            elseif (($name -eq 'SM FS %' -and $value -ge $reviewLimits[$name]) -or
                ($name -ne 'SM FS %' -and $value -le $reviewLimits[$name])) { $review++; $points=.5 }
            else { $priority++; $points=0.0 }
            $pointsTotal += $points
            $bandPoints[$name] = $points
            if ($observedRates.Contains($name)) {
                $excluded = $row.PSObject.Properties["[$($observedRates[$name][2])]"].Value
                if ($excluded -gt 0) { $partial++ }
            }
        }
        $expectedScore = if ($assessed -gt 0 -and $row.'[Task_Count]' -gt 0) { $pointsTotal / $assessed } else { $null }
        Assert-ScheduleMetric (Test-ScheduleMetricNumber $row.'[Score]' $expectedScore) 'Score is not review-band points/assessed.'
        if ($row.'[Task_Count]' -gt 0) {
            Assert-ScheduleMetric (Test-ScheduleMetricNumber $row.'[SM Assessed Checks]' $assessed) 'Assessed count does not match available checks.'
            Assert-ScheduleMetric (Test-ScheduleMetricNumber $row.'[SM Passed Checks]' $passed) 'Passed count does not match metric thresholds.'
            Assert-ScheduleMetric (Test-ScheduleMetricNumber $row.'[SM Review Checks]' $review) 'Review count does not match amber bands.'
            Assert-ScheduleMetric (Test-ScheduleMetricNumber $row.'[SM Priority Checks]' $priority) 'Priority count does not match red bands.'
            Assert-ScheduleMetric (Test-ScheduleMetricNumber $row.'[SM Partial Checks]' $partial) 'Partial count does not match assessed checks with excluded records.'
        }
        $scoreCoverageChecks++
        if ($UseLoadedModel) {
            foreach ($name in $colourMeasures.Keys) {
                $value = $row.PSObject.Properties["[$name]"].Value
                $points = if ($name -eq 'Score') {
                    if ($priority -gt 0) {0} elseif ($review -gt 0) {.5} else {1}
                } else { $bandPoints[$name] }
                $expectedColour = if ($null -eq $value) { '#687078' } elseif ($name -eq 'HighFloat%') { '#3979A6' }
                    elseif ($points -eq 1) { '#4b6110' } elseif ($points -eq .5) { '#9C6500' } else { '#6f0516' }
                $actualColour = $row.PSObject.Properties["[$($colourMeasures[$name])]"].Value
                Assert-ScheduleMetric ($actualColour -eq $expectedColour) "$name colour disagrees with its severity band."
                $colourChecks++
            }
            $status = $row.'[SM Score Status]'
            Assert-ScheduleMetric ($status.StartsWith("$passed within | $review review | $priority priority")) 'Score status does not show band counts.'
            Assert-ScheduleMetric ($row.'[SM Score Coverage]'.Contains("$assessed/$($row.'[SM Applicable Checks]') assessed")) 'Score coverage does not show assessed/applicable.'
            Assert-ScheduleMetric (($status -match 'partial inputs') -eq ($partial -gt 0)) 'Score partial-input label disagrees with coverage.'
            $tooltip = $row.'[SM Coverage Tooltip]'
            $tooltipSpecs = [ordered]@{
                'High float' = 'HighFloat%'; 'Long remaining duration' = 'HighDur%';
                'Positive lags' = 'Lags%'; 'Leads' = '<0Lead%'; 'FS (including PR_FS1)' = 'SM FS %';
                'Negative float' = '<0Float%'; 'Restrictive primary constraints' = 'Constraint%'
            }
            foreach ($label in $tooltipSpecs.Keys) {
                $spec = $observedRates[$tooltipSpecs[$label]]
                $num = [double]$row.PSObject.Properties["[$($spec[0])]"].Value
                $den = [double]$row.PSObject.Properties["[$($spec[1])]"].Value - [double]$row.PSObject.Properties["[$($spec[2])]"].Value
                $fragment = $label + ': ' + $num.ToString('#,0', [Globalization.CultureInfo]::InvariantCulture) + '/' + $den.ToString('#,0', [Globalization.CultureInfo]::InvariantCulture)
                Assert-ScheduleMetric ($tooltip.Contains($fragment)) "Tooltip disagrees with $label numerator/denominator: $fragment."
                $tooltipCountChecks++
            }
        }
    }
    $checks.Add("All $($snapshots.Count) loaded project/snapshot contexts compile and return finite rates.")
    $checks.Add("$availableRecordChecks available-record denominator checks and $scoreCoverageChecks score/coverage reconciliations passed.")
    if ($UseLoadedModel) { $checks.Add("$colourChecks gauge colours, $tooltipCountChecks tooltip ratios and $scoreCoverageChecks score-status labels passed.") }
    $result.snapshots = $snapshots

    if (-not $CompileOnly) {
        foreach ($required in $rates) {
            Assert-ScheduleMetric ($metricsTable.Measures.Contains($required)) "Required metric '$required' is missing."
        }
        $historyRates = @($availableRates | Where-Object { $metricsTable.Measures.Contains("$_ (History)") })
        $groups = $snapshots | Group-Object { "$($_.'01 XER_TASK[ProjectCode]')|$($_.'01 XER_TASK[ProgrammeType]')" }
        $historyComparisons = 0
        $cutoffTests = 0
        $historyPresentationChecks = 0
        foreach ($group in $groups) {
            $ordered = @($group.Group | Sort-Object { [datetime]$_.'01 XER_TASK[UpdateDate]' })
            $project = Quote-DaxString $ordered[0].'01 XER_TASK[ProjectCode]'
            $programme = Quote-DaxString $ordered[0].'01 XER_TASK[ProgrammeType]'
            $latest = Date-DaxLiteral ([datetime]$ordered[-1].'01 XER_TASK[UpdateDate]')
            $selection = "TREATAS({$project},'01 XER_TASK'[ProjectCode]),TREATAS({$programme},'01 XER_TASK'[ProgrammeType])"
            for ($offset = 0; $offset -lt $historyRates.Count; $offset += 4) {
                $batch = @($historyRates | Select-Object -Skip $offset -First 4)
                $historyProjection = Get-MetricProjections -Names $batch -Suffix ' (History)'
                if ($UseLoadedModel) { $historyProjection += ',"Scope",[SM History In Scope],"Coverage",[SM Coverage Tooltip (History)]' }
                $historyQuery = @"
$definitions
EVALUATE SUMMARIZECOLUMNS(UpdateHistory[UpdateDate],
$selection,TREATAS({$latest},CurrentDate[UpdateDate]),$pageFilters,
$historyProjection)
ORDER BY UpdateHistory[UpdateDate]
"@
                $expectedPoints = @($ordered | Where-Object {
                    $hasValue = $false
                    foreach ($name in $batch) { if ($null -ne $_.PSObject.Properties["[$name]"].Value) { $hasValue = $true } }
                    $hasValue
                })
                $history = Invoke-ScheduleMetricsDax -Target $target -Query $historyQuery
                Assert-ScheduleMetric ($history.Count -eq $expectedPoints.Count) "History snapshot count differs for $($group.Name)."
                foreach ($row in $history) {
                    $pointDate = [datetime]$row.'UpdateHistory[UpdateDate]'
                    $base = @($ordered | Where-Object { [datetime]$_.'01 XER_TASK[UpdateDate]' -eq $pointDate })
                    Assert-ScheduleMetric ($base.Count -eq 1) "Unmatched history date $pointDate for $($group.Name)."
                    foreach ($name in $batch) {
                        $expected = $base[0].PSObject.Properties["[$name]"].Value
                        $actual = $row.PSObject.Properties["[$name]"].Value
                        Assert-ScheduleMetric (Test-ScheduleMetricNumber $actual $expected) "Gauge/history mismatch: $($group.Name), $pointDate, $name."
                        $historyComparisons++
                    }
                    if ($UseLoadedModel) {
                        Assert-ScheduleMetric ($row.'[Scope]' -eq 1) 'A displayed history point is outside the defined snapshot scope.'
                        Assert-ScheduleMetric ($row.'[Coverage]' -ceq $base[0].'[SM Coverage Tooltip]') 'History tooltip differs from its corresponding snapshot tooltip.'
                        $historyPresentationChecks++
                    }
                }
                if ($ordered.Count -gt 1) {
                    $middleDate = [datetime]$ordered[[Math]::Floor(($ordered.Count - 1) / 2)].'01 XER_TASK[UpdateDate]'
                    $middle = Date-DaxLiteral $middleDate
                    $middleQuery = $historyQuery.Replace("TREATAS({$latest},CurrentDate[UpdateDate])", "TREATAS({$middle},CurrentDate[UpdateDate])")
                    $middleRows = Invoke-ScheduleMetricsDax -Target $target -Query $middleQuery
                    $expectedCount = @($expectedPoints | Where-Object { [datetime]$_.'01 XER_TASK[UpdateDate]' -le $middleDate }).Count
                    Assert-ScheduleMetric ($middleRows.Count -eq $expectedCount) "Earlier cutoff drops or adds history for $($group.Name)."
                    Assert-ScheduleMetric (@($middleRows | Where-Object { [datetime]$_.'UpdateHistory[UpdateDate]' -gt $middleDate }).Count -eq 0) "Future points leaked after cutoff for $($group.Name)."
                    $cutoffTests++
                }
            }
        }
        $checks.Add("$historyComparisons gauge/history comparisons passed; $cutoffTests earlier-cutoff checks passed.")
        if ($UseLoadedModel) { $checks.Add("$historyPresentationChecks combined history scope/tooltip checks passed.") }
        $missingDate = Date-DaxLiteral (([datetime]($snapshots | Sort-Object { [datetime]$_.'01 XER_TASK[UpdateDate]' })[-1].'01 XER_TASK[UpdateDate]').AddMonths(1))
        $missingQuery = "$definitions`nEVALUATE CALCULATETABLE(ROW($(Get-MetricProjections $availableRates)),TREATAS({$missingDate},CurrentDate[UpdateDate]),$pageFilters)"
        $missingRows = Invoke-ScheduleMetricsDax -Target $target -Query $missingQuery
        foreach ($name in $availableRates) {
            Assert-ScheduleMetric ($null -eq $missingRows[0].PSObject.Properties["[$name]"].Value) "$name must be BLANK for an unavailable snapshot."
        }
        $checks.Add('Every rate and Score returns BLANK for a missing snapshot.')
    }
    $result.checks = $checks.ToArray()
    $result.status = 'passed'
    if ($OutputPath) {
        $result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputPath -Encoding utf8
    }
    [pscustomobject]@{ Status = $result.status; Server = $target.Address; ExecutionMode = $result.executionMode; Snapshots = $snapshots.Count; Checks = $checks.ToArray() } |
        ConvertTo-Json -Depth 5
} finally { $target.Connection.Disconnect() }
