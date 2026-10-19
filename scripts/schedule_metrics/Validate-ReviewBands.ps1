[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path,
    [string]$ServerAddress,
    [string]$Catalog,
    [string]$AssemblyDirectory,
    [switch]$FixturesOnly,
    [switch]$SnapshotsOnly,
    [switch]$UseLoadedModel
)

. (Join-Path $PSScriptRoot 'Common.ps1')
Import-ScheduleMetricsTom -AssemblyDirectory $AssemblyDirectory
$proposed = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeModelFromFolder(
    (Join-Path $RepositoryRoot 'Project Review - Programme (datalake).SemanticModel/definition'))
$target = Connect-ScheduleMetricsModel -ServerAddress $ServerAddress -Catalog $Catalog
$assertions = 0
$fixtureCount = 0
$snapshotCount = 0

# Independent acceptance policy, deliberately not extracted from implementation.
# Ten scored checks; high float is no longer presented or scored.
# Points: 1 at or better than Target, 0 at or past Limit, linear between.
# Baseline coverage is a ratio from the detail table, supplied directly (Direct).
$coverageInput = 'Schedule Metric Detail[SM Detail Value]'
$policy = @(
    @{ Label='Missing Logic'; Rate='SM Missing Logic %'; Numerator='SM Missing Logic Count'; Denominator='Task_Count'; Excluded=$null; Target=.05; Limit=.10; Direction='low' },
    @{ Label='Leads'; Rate='<0Lead%'; Numerator='Leads<0d'; Denominator='SM Eligible Relationship Count'; Excluded='SM Missing Lag Count'; Target=0; Limit=.01; Direction='low' },
    @{ Label='Lags'; Rate='Lags%'; Numerator='Lags>5d'; Denominator='SM Eligible Relationship Count'; Excluded='SM Missing Lag Count'; Target=.05; Limit=.10; Direction='low' },
    @{ Label='FS'; Rate='SM FS %'; Numerator='SM FS Count'; Denominator='SM Eligible Relationship Count'; Excluded='SM Unknown Relationship Type Count'; Target=.90; Limit=.80; Direction='high' },
    @{ Label='Constraints'; Rate='Constraint%'; Numerator='SM Restrictive Primary Count'; Denominator='Task_Count'; Excluded='SM Unknown Constraint Count'; Target=.05; Limit=.10; Direction='low' },
    @{ Label='Negative Float'; Rate='<0Float%'; Numerator='Task_Count_Negative_Float'; Denominator='Task_Count'; Excluded='SM Missing Float Count'; Target=0; Limit=.05; Direction='low' },
    @{ Label='High Duration'; Rate='HighDur%'; Numerator='Dur >44'; Denominator='Task_Count'; Excluded='SM Missing Duration Count'; Target=.05; Limit=.10; Direction='low' },
    @{ Label='Invalid Dates'; Rate='SM Invalid Dates %'; Numerator='SM Invalid Dates Count'; Denominator='SM Date Eligible Count'; Excluded=$null; Target=0; Limit=.01; Direction='low' },
    @{ Label='Out Of Sequence'; Rate='SM Out Of Sequence %'; Numerator='Out Of Sequence Count'; Denominator='SM In Progress Count'; Excluded=$null; Target=0; Limit=.10; Direction='low' },
    @{ Label='Baseline Coverage'; Rate='SM Detail Value'; Direct=$coverageInput; Target=.90; Limit=.60; Direction='high' }
)
$inputNames = @('Task_Count','SM Eligible Relationship Count','SM Date Eligible Count','SM Missing Logic Count','Leads<0d',
    'Lags>5d','SM FS Count','SM Restrictive Primary Count','Float >44','Task_Count_Negative_Float','Dur >44',
    'SM Invalid Dates Count','SM Missing Float Count','SM Missing Duration Count','SM Missing Lag Count',
    'SM Unknown Relationship Type Count','SM Unknown Constraint Count','Out Of Sequence Count','SM In Progress Count',$coverageInput,
    'SM Snapshot Valid')

# Measure reference for an input name; detail-table inputs are table-qualified.
function Get-InputReference([string]$Name) {
    if ($Name -match '^(.+)\[(.+)\]$') { return "'" + $Matches[1] + "'[" + $Matches[2] + ']' }
    return '[' + $Name + ']'
}

function Get-ExpectedReviewPoints($Value, $Rule) {
    if ($null -eq $Value) { return $null }
    if ($Rule.Direction -eq 'high') {
        if ($Value -ge $Rule.Target) { return 1.0 }
        if ($Value -le $Rule.Limit) { return 0.0 }
        return ([double]$Value - $Rule.Limit) / ($Rule.Target - $Rule.Limit)
    }
    if ($Value -le $Rule.Target) { return 1.0 }
    if ($Value -ge $Rule.Limit) { return 0.0 }
    return ($Rule.Limit - [double]$Value) / ($Rule.Limit - $Rule.Target)
}

function Get-ExpectedBandColour($Points) {
    if ($null -eq $Points) { return '#687078' }
    if ($Points -ge 1) { return '#4b6110' }
    if ($Points -gt 0) { return '#9C6500' }
    return '#6f0516'
}

function Get-ReviewExpectation([hashtable]$Inputs) {
    $expected = [ordered]@{ Rates=@{}; Points=@{}; Colours=@{}; Assessed=0; Passed=0; Review=0; Priority=0; Partial=0; PointsTotal=0.0 }
    foreach ($rule in $policy) {
        if ($rule.Direct) {
            $rate = if ($null -ne $Inputs[$rule.Direct]) { [double]$Inputs[$rule.Direct] } else { $null }
        } else {
            $known = [double]$Inputs[$rule.Denominator]
            if ($rule.Excluded) { $known -= [double]$Inputs[$rule.Excluded] }
            # A valid snapshot always shows a number: nothing to count is 0%.
            $rate = if (-not $Inputs['SM Snapshot Valid']) { $null }
                elseif ($known -gt 0 -and $null -ne $Inputs[$rule.Numerator]) { [double]$Inputs[$rule.Numerator] / $known }
                else { 0.0 }
        }
        $points = Get-ExpectedReviewPoints $rate $rule
        $expected.Rates[$rule.Rate] = $rate
        $expected.Points[$rule.Label] = $points
        $expected.Colours[$rule.Label] = Get-ExpectedBandColour $points
        if ($null -ne $points) {
            $expected.Assessed++
            $expected.PointsTotal += $points
            if ($points -ge 1) { $expected.Passed++ } elseif ($points -gt 0) { $expected.Review++ } else { $expected.Priority++ }
            if ($rule.Excluded -and $Inputs[$rule.Excluded] -gt 0 -and $Inputs[$rule.Excluded] -lt $Inputs[$rule.Denominator]) { $expected.Partial++ }
        }
    }
    $expected['Applicable'] = 10
    $expected['Score'] = if ($Inputs['Task_Count'] -gt 0 -and $expected.Assessed -gt 0) { $expected.PointsTotal / $expected.Assessed } else { $null }
    $expected['ScoreColour'] = if ($null -eq $expected.Score) { '#687078' } elseif ($expected.Score -ge .95) { '#4b6110' } elseif ($expected.Score -ge .75) { '#9C6500' } else { '#6f0516' }
    if (-not ($Inputs['Task_Count'] -gt 0)) {
        foreach ($key in @('Applicable','Assessed','Passed','Review','Priority','Partial')) { $expected[$key] = $null }
    }
    $floatKnown = [double]$Inputs['Task_Count'] - [double]$Inputs['SM Missing Float Count']
    $expected['HighFloat'] = if ($floatKnown -gt 0 -and $null -ne $Inputs['Float >44']) { [double]$Inputs['Float >44'] / $floatKnown } else { $null }
    $expected['HighFloatColour'] = if ($null -eq $expected.HighFloat) { '#687078' } else { '#252525' }
    return $expected
}

function Get-ReviewProjection {
    $parts = [Collections.Generic.List[string]]::new()
    foreach ($rule in $policy) {
        $parts.Add('"' + $rule.Rate + '",[' + $rule.Rate + ']')
        $parts.Add('"Points:' + $rule.Label + '",[SM ' + $rule.Label + ' Points]')
        $parts.Add('"Colour:' + $rule.Label + '",[SM ' + $rule.Label + ' Colour]')
    }
    $parts.Add('"Score",[Score],"Passed",[SM Passed Checks],"Review",[SM Review Checks],"Priority",[SM Priority Checks],"Assessed",[SM Assessed Checks],"Applicable",[SM Applicable Checks],"Partial",[SM Partial Checks],"ScoreColour",[SM Score Colour],"ScoreStatus",[SM Score Status],"Coverage",[SM Score Coverage],"HighFloat",[HighFloat%],"HighFloatColour",[SM High Float Colour]')
    return $parts -join ','
}

function Assert-ReviewResult($Row, $Expected, [string]$Context) {
    foreach ($rule in $policy) {
        Assert-ScheduleMetric (Test-ScheduleMetricNumber $Row.("["+$rule.Rate+"]") $Expected.Rates[$rule.Rate]) "${Context}: $($rule.Rate) available-record denominator mismatch."
        Assert-ScheduleMetric (Test-ScheduleMetricNumber $Row.("[Points:"+$rule.Label+"]") $Expected.Points[$rule.Label]) "${Context}: $($rule.Label) points mismatch."
        Assert-ScheduleMetric ($Row.("[Colour:"+$rule.Label+"]") -eq $Expected.Colours[$rule.Label]) "${Context}: $($rule.Label) severity colour mismatch."
        $script:assertions += 3
    }
    foreach ($field in @('Score','Passed','Review','Priority','Assessed','Applicable','Partial','HighFloat')) {
        Assert-ScheduleMetric (Test-ScheduleMetricNumber $Row.("["+$field+"]") $Expected[$field]) "${Context}: $field mismatch."
        $script:assertions++
    }
    Assert-ScheduleMetric ($Row.'[ScoreColour]' -eq $Expected.ScoreColour) "${Context}: score colour must follow the 90%/65% score thresholds."
    Assert-ScheduleMetric ($Row.'[HighFloatColour]' -eq $Expected.HighFloatColour) "${Context}: high float must be neutral contextual information."
    $script:assertions += 2
    if ($Expected.Partial -gt 0) {
        Assert-ScheduleMetric ($Row.'[Coverage]' -match 'partial') "${Context}: partial evidence must remain separately disclosed."
        $script:assertions++
    }
    if ($null -ne $Expected.Applicable) {
        Assert-ScheduleMetric ($Row.'[Coverage]'.Contains("$($Expected.Assessed)/$($Expected.Applicable)")) "${Context}: assessed/applicable coverage is missing."
        $script:assertions++
    }
    if ($null -ne $Expected.Score) {
        $label = "$($Expected.Passed) within | $($Expected.Review) review | $($Expected.Priority) priority"
        Assert-ScheduleMetric ($Row.'[ScoreStatus]'.StartsWith($label)) "${Context}: score band count labels disagree with the independent calculation."
        Assert-ScheduleMetric ($Row.'[ScoreStatus]'.Contains($Row.'[Coverage]')) "${Context}: score status must retain separate input coverage."
        $script:assertions += 2
    }
}

try {
    if ($FixturesOnly -and $SnapshotsOnly) { throw 'Choose only one scope switch.' }
    if ($FixturesOnly -and $UseLoadedModel) { throw 'Synthetic fixtures require query-scoped inputs; loaded validation is direct snapshots only.' }
    $metrics = $proposed.Tables['XER Metrics']
    foreach ($rule in $policy) { Assert-ScheduleMetric ($metrics.Measures.Contains('SM '+$rule.Label+' Points')) "Candidate policy helper missing: $($rule.Label)." }
    if ($UseLoadedModel) {
        $live = $target.Database.Model.Tables['XER Metrics']
        Assert-ScheduleMetric ($live.Measures.Count -eq $metrics.Measures.Count) 'Loaded/source core measure counts differ.'
        foreach ($measure in $metrics.Measures) {
            Assert-ScheduleMetric ($live.Measures.Contains($measure.Name)) "Loaded measure missing: $($measure.Name)."
            $loaded = $live.Measures[$measure.Name]
            Assert-ScheduleMetric ($loaded.Expression.Replace("`r`n","`n").Trim() -ceq $measure.Expression.Replace("`r`n","`n").Trim()) "Loaded/source expression differs: $($measure.Name)."
            Assert-ScheduleMetric ($loaded.FormatString -ceq $measure.FormatString) "Loaded/source format differs: $($measure.Name)."
            $assertions += 3
        }
        $definitions = ''
    } else { $definitions = Get-ScheduleMetricsDefinitions -Model $proposed -LiveModel $target.Database.Model }
    $projection = Get-ReviewProjection

    if (-not $SnapshotsOnly -and -not $UseLoadedModel) {
        $base = @{
            'SM Snapshot Valid'=$true; 'Task_Count'=100000; 'SM Eligible Relationship Count'=100000; 'SM Date Eligible Count'=100000
            'SM Missing Logic Count'=5000; 'Leads<0d'=0; 'Lags>5d'=5000; 'SM FS Count'=90000
            'SM Restrictive Primary Count'=5000; 'Float >44'=5000; 'Task_Count_Negative_Float'=0; 'Dur >44'=5000; 'SM Invalid Dates Count'=0
            'SM Missing Float Count'=0; 'SM Missing Duration Count'=0; 'SM Missing Lag Count'=0; 'SM Unknown Relationship Type Count'=0; 'SM Unknown Constraint Count'=0
            'Out Of Sequence Count'=0; 'SM In Progress Count'=100000; $coverageInput=1
        }
        $cases = [Collections.Generic.List[object]]::new()
        $cases.Add(@{Name='all ten at green boundary';Changes=@{}})
        foreach ($rule in $policy) {
            $midpoint = ($rule.Target + $rule.Limit) / 2
            $values = @(0,1,($rule.Target-.00001),$rule.Target,($rule.Target+.00001),$midpoint,($rule.Limit-.00001),$rule.Limit,($rule.Limit+.00001)) | Where-Object {$_ -ge 0 -and $_ -le 1} | Sort-Object -Unique
            foreach ($value in $values) {
                $change = if ($rule.Direct) { @{$rule.Direct=[double]$value} } else { @{$rule.Numerator=[int][Math]::Round($value*100000)} }
                $cases.Add(@{Name="$($rule.Label) exact/adjacent boundary $value";Changes=$change})
            }
        }
        $cases.Add(@{Name='high float zero has no score weight';Changes=@{'Float >44'=0}})
        $cases.Add(@{Name='high float hundred percent has no score weight';Changes=@{'Float >44'=100000}})
        $cases.Add(@{Name='partial float contributes only one scored coverage check';Changes=@{'SM Missing Float Count'=20000}})
        $cases.Add(@{Name='partial negative float does not mask red severity';Changes=@{'SM Missing Float Count'=20000;'Task_Count_Negative_Float'=5000}})
        $cases.Add(@{Name='partial duration uses known denominator';Changes=@{'SM Missing Duration Count'=20000}})
        $cases.Add(@{Name='partial lag affects both sign checks';Changes=@{'SM Missing Lag Count'=20000}})
        $cases.Add(@{Name='partial FS uses recognised denominator';Changes=@{'SM Unknown Relationship Type Count'=20000;'SM FS Count'=64000}})
        $cases.Add(@{Name='partial constraints use recognised denominator';Changes=@{'SM Unknown Constraint Count'=20000}})
        $cases.Add(@{Name='complete green bands with six partial input cohorts';Changes=@{'SM Missing Float Count'=20000;'SM Missing Duration Count'=20000;'SM Missing Lag Count'=20000;'SM Unknown Relationship Type Count'=20000;'SM Unknown Constraint Count'=20000;'Dur >44'=4000;'Lags>5d'=4000;'SM FS Count'=72000;'SM Restrictive Primary Count'=4000}})
        # Headline colour follows the score: one check at its limit stays amber (90%),
        # two stay amber at 80%, three fall to red at 70%.
        $cases.Add(@{Name='one check at its limit keeps an amber headline';Changes=@{'SM Missing Logic Count'=10000}})
        $cases.Add(@{Name='two checks at their limits keep an amber headline';Changes=@{'SM Missing Logic Count'=10000;'SM FS Count'=80000}})
        $cases.Add(@{Name='three checks at their limits turn the headline red';Changes=@{'SM Missing Logic Count'=10000;'SM FS Count'=80000;'SM Invalid Dates Count'=1000}})
        $cases.Add(@{Name='every check halfway to its limit is red';Changes=@{'SM Missing Logic Count'=7500;'Leads<0d'=500;'Lags>5d'=7500;'SM FS Count'=85000;'SM Restrictive Primary Count'=7500;'Task_Count_Negative_Float'=2500;'Dur >44'=7500;'SM Invalid Dates Count'=500;'Out Of Sequence Count'=5000;$coverageInput=.75}})
        $cases.Add(@{Name='out-of-sequence shows 0% without in-progress work';Changes=@{'SM In Progress Count'=0;'Out Of Sequence Count'=$null}})
        $cases.Add(@{Name='a blank baseline coverage value is not scored';Changes=@{$coverageInput=$null}})
        foreach ($missing in @('SM Missing Float Count','SM Missing Duration Count','SM Missing Lag Count','SM Unknown Relationship Type Count','SM Unknown Constraint Count')) {
            $changes=@{$missing=100000}
            foreach ($rule in $policy | Where-Object Excluded -eq $missing) { $changes[$rule.Numerator]=0 }
            if ($missing -eq 'SM Missing Float Count') { $changes['Float >44']=0 }
            $cases.Add(@{Name="all input unavailable: $missing";Changes=$changes})
        }
        $cases.Add(@{Name='no date population shows 0% invalid dates';Changes=@{'SM Date Eligible Count'=0;'SM Invalid Dates Count'=0}})
        $cases.Add(@{Name='no relationships: leads and lags 0%, FS 0% scores nothing';Changes=@{'SM Eligible Relationship Count'=0;'Leads<0d'=0;'Lags>5d'=0;'SM FS Count'=0;'SM Missing Logic Count'=100000}})
        $cases.Add(@{Name='no incomplete work yields no score';Changes=@{'Task_Count'=0}})
        $cases.Add(@{Name='unknown incomplete work yields no score';Changes=@{'Task_Count'=$null}})
        $cases.Add(@{Name='empty populations show 0%; FS and blank coverage do not pass';Changes=@{'SM Missing Logic Count'=$null;'SM Invalid Dates Count'=$null;'SM Missing Float Count'=100000;'Float >44'=0;'Task_Count_Negative_Float'=0;'SM Missing Duration Count'=100000;'Dur >44'=0;'SM Missing Lag Count'=100000;'Leads<0d'=0;'Lags>5d'=0;'SM Unknown Relationship Type Count'=100000;'SM FS Count'=0;'SM Unknown Constraint Count'=100000;'SM Restrictive Primary Count'=0;'SM In Progress Count'=0;'Out Of Sequence Count'=$null;$coverageInput=$null}})
        foreach ($case in $cases) {
            $inputs=$base.Clone()
            foreach ($key in $case.Changes.Keys) { $inputs[$key]=$case.Changes[$key] }
            $overrides=@{}
            foreach ($key in $inputs.Keys) {
                $value=$inputs[$key]
                $literal=if ($null -eq $value) {'BLANK()'} elseif ($value -is [bool]) {if($value){'TRUE()'}else{'FALSE()'}} else {$value.ToString([Globalization.CultureInfo]::InvariantCulture)}
                $overrides[$(if ($key -match '\[') { $key } else { "XER Metrics[$key]" })]=$literal
            }
            $fixtureDefinitions=Get-ScheduleMetricsDefinitions -Model $proposed -LiveModel $target.Database.Model -Overrides $overrides
            $row=(Invoke-ScheduleMetricsDax $target ($fixtureDefinitions+"`nEVALUATE ROW($projection)"))[0]
            Assert-ReviewResult $row (Get-ReviewExpectation $inputs) $case.Name
            $fixtureCount++
        }
        Write-Output "PASS $fixtureCount focused policy fixtures."

        # Test genuine baseline-coverage presentation expressions with only the
        # value supplied. Coverage is scored: the gauge colour follows its points.
        $detailCases = @(
            @{Value='1';Colour='#4b6110';Status='Full dated coverage'},
            @{Value='.9';Colour='#4b6110';Status='Partial dated coverage'},
            @{Value='.75';Colour='#9C6500';Status='Partial dated coverage'},
            @{Value='.6';Colour='#6f0516';Status='Partial dated coverage'},
            @{Value='BLANK()';Colour='#687078';Status='N/A'}
        )
        foreach ($case in $detailCases) {
            $overrides=@{ 'Schedule Metric Detail[SM Detail Value]'=$case.Value }
            $fixtureDefinitions=Get-ScheduleMetricsDefinitions -Model $proposed -LiveModel $target.Database.Model -Overrides $overrides
            $row=(Invoke-ScheduleMetricsDax $target ($fixtureDefinitions+"`nEVALUATE ROW(""Colour"",[SM Detail Colour],""Status"",[SM Detail Status])"))[0]
            Assert-ScheduleMetric ($row.'[Colour]' -eq $case.Colour) "Baseline coverage $($case.Value) colour mismatch."
            Assert-ScheduleMetric ($row.'[Status]' -eq $case.Status) "Baseline coverage $($case.Value) status mismatch."
            $assertions+=2
            $fixtureCount++
        }
        Write-Output "PASS $($detailCases.Count) detail severity/coverage fixtures."

    }

    if (-not $FixturesOnly) {
        $snapshots=Invoke-ScheduleMetricsDax $target @'
EVALUATE SUMMARIZECOLUMNS('01 XER_TASK'[ProjectCode],'01 XER_TASK'[ProgrammeType],'01 XER_TASK'[UpdateDate],"Rows",COUNTROWS('01 XER_TASK'))
ORDER BY '01 XER_TASK'[ProjectCode],'01 XER_TASK'[UpdateDate]
'@
        $inputProjection=($inputNames | ForEach-Object {'"Input:'+($_ -replace '\[|\]','_')+'",'+(Get-InputReference $_)}) -join ','
        foreach ($snapshot in $snapshots) {
            $project=$snapshot.'01 XER_TASK[ProjectCode]'.Replace('"','""')
            $programme=$snapshot.'01 XER_TASK[ProgrammeType]'.Replace('"','""')
            $date=[datetime]$snapshot.'01 XER_TASK[UpdateDate]'
            $query=@"
$definitions
EVALUATE CALCULATETABLE(ROW($projection,$inputProjection,"HistoryScore",[Score (History)]),
TREATAS({"$project"},'01 XER_TASK'[ProjectCode]),TREATAS({"$programme"},'01 XER_TASK'[ProgrammeType]),
TREATAS({DATE($($date.Year),$($date.Month),$($date.Day))},CurrentDate[UpdateDate]),
TREATAS({DATE($($date.Year),$($date.Month),$($date.Day))},UpdateHistory[UpdateDate]),
TREATAS({"Activity","Milestone"},'01 XER_TASK'[TaskType_Classified]),TREATAS({"Not Started","In Progress"},'01 XER_TASK'[status_code]),
TREATAS({FALSE()},'01 XER_TASK'[Is Unscheduled]),TREATAS({FALSE()},'01 XER_TASK'[IsExcludedFromDataLake]))
"@
            $row=(Invoke-ScheduleMetricsDax $target $query)[0]
            $inputs=@{}
            foreach ($name in $inputNames) { $inputs[$name]=$row.("[Input:"+($name -replace '\[|\]','_')+"]") }
            Assert-ReviewResult $row (Get-ReviewExpectation $inputs) "$project $($date.ToString('yyyy-MM-dd'))"
            Assert-ScheduleMetric (Test-ScheduleMetricNumber $row.'[Score]' $row.'[HistoryScore]') 'Weighted score gauge/history endpoint differs.'
            $assertions++
            $snapshotCount++
            Write-Output ("PASS review bands {0} {1:yyyy-MM-dd}: score={2:P2}, G/A/R={3}/{4}/{5}" -f $project,$date,$row.'[Score]',$row.'[Passed]',$row.'[Review]',$row.'[Priority]')
        }
    }
    [pscustomobject]@{Status='PASS';Mode=if($UseLoadedModel){'Direct loaded model; no DEFINE'}else{'Query-scoped candidate expressions'};ScoredChecks=10;HighFloat='No longer presented or scored';Fixtures=$fixtureCount;Snapshots=$snapshotCount;Assertions=$assertions;ModelWrites=$false}|ConvertTo-Json
} finally { $target.Connection.Disconnect() }
