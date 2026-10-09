[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path,
    [string]$ServerAddress,
    [string]$Catalog,
    [string]$AssemblyDirectory,
    [switch]$UseLoadedModel,
    [switch]$HelpersOnly,
    [switch]$SkipWbs
)

# Read-only: PBIR/TMDL inspection and DAX Statements against the loaded cache.
# Fixtures use isolated query-local tables and scoped measure definitions.
# This does not open, refresh, save, deploy or change a report/model.
. (Join-Path $PSScriptRoot 'Common.ps1')
Import-ScheduleMetricsTom -AssemblyDirectory $AssemblyDirectory
$reportRoot = Join-Path $RepositoryRoot 'Project Review - Programme (datalake).Report/definition'
$modelRoot = Join-Path $RepositoryRoot 'Project Review - Programme (datalake).SemanticModel/definition'
$disk = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeModelFromFolder($modelRoot)
$script:assertions = 0
$script:staticAssertions = 0
$routes = @(
    @{ Page = '061f748900951ae92ba9'; Measure = 'Missing Predecessor'; Column = 'No Predecessor'; Header = 'SM Drill Missing Predecessor Header'; Detail = 'SM Drill Missing Predecessor Flag' },
    @{ Page = '4f15f55676d2add4e922'; Measure = 'Missing Successor'; Column = 'No Successor'; Header = 'SM Drill Missing Successor Header'; Detail = 'SM Drill Missing Successor Flag' }
)
$sourcePageID = '327b48a7fbd37ce0a51c'
$removedMeasures = @('DD Driving','DataDate%','DataDate% (History)','SM Drill Date Alignment Header','SM Drill Date Alignment Reason')

function Assert-Drill([bool]$Condition, [string]$Message, [switch]$Static) {
    Assert-ScheduleMetric $Condition $Message
    $script:assertions++
    if ($Static) { $script:staticAssertions++ }
}

function Read-Pbir([string]$Path) {
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json -AsHashtable
}

function Convert-PbirExpression($Expression, [hashtable]$Aliases, [hashtable]$TableMap) {
    if ($Expression.ContainsKey('Column')) {
        $column = $Expression['Column']
        $source = $column['Expression']['SourceRef']
        $entity = if ($source['Entity']) { $source['Entity'] } else { $Aliases[$source['Source']] }
        if (-not $entity) { throw 'PBIR column source could not be resolved.' }
        if ($TableMap.ContainsKey($entity)) { $entity = $TableMap[$entity] }
        return "'" + $entity.Replace("'", "''") + "'[" + $column['Property'].Replace(']', ']]') + ']'
    }
    if ($Expression.ContainsKey('Literal')) {
        $value = [string]$Expression['Literal']['Value']
        if ($value -eq 'null') { return 'BLANK()' }
        if ($value -eq 'true') { return 'TRUE()' }
        if ($value -eq 'false') { return 'FALSE()' }
        if ($value -match "^'(.*)'$") { return '"' + $Matches[1].Replace("''", "'").Replace('"', '""') + '"' }
        if ($value -match '^-?[0-9]+(?:\.[0-9]+)?[LD]?$') { return $value -replace '[LD]$', '' }
        throw "Unsupported PBIR literal: $value"
    }
    foreach ($operator in @('And', 'Or')) {
        if ($Expression.ContainsKey($operator)) {
            $node = $Expression[$operator]
            $symbol = if ($operator -eq 'And') { '&&' } else { '||' }
            return '(' + (Convert-PbirExpression $node['Left'] $Aliases $TableMap) + " $symbol " +
                (Convert-PbirExpression $node['Right'] $Aliases $TableMap) + ')'
        }
    }
    if ($Expression.ContainsKey('Not')) {
        return 'NOT (' + (Convert-PbirExpression $Expression['Not']['Expression'] $Aliases $TableMap) + ')'
    }
    if ($Expression.ContainsKey('Comparison')) {
        $node = $Expression['Comparison']
        $operators = @{ 0 = '='; 1 = '>'; 2 = '>='; 3 = '<'; 4 = '<='; 5 = '<>' }
        $kind = [int]$node['ComparisonKind']
        if (-not $operators.ContainsKey($kind)) { throw "Unsupported comparison kind: $kind" }
        return '(' + (Convert-PbirExpression $node['Left'] $Aliases $TableMap) + ' ' + $operators[$kind] + ' ' +
            (Convert-PbirExpression $node['Right'] $Aliases $TableMap) + ')'
    }
    if ($Expression.ContainsKey('In')) {
        $node = $Expression['In']
        if (@($node['Expressions']).Count -ne 1) { throw 'Only single-column PBIR In predicates are supported.' }
        $column = Convert-PbirExpression $node['Expressions'][0] $Aliases $TableMap
        $values = @($node['Values'] | ForEach-Object { Convert-PbirExpression $_[0] $Aliases $TableMap })
        return '(' + $column + ' IN {' + ($values -join ',') + '})'
    }
    throw ('Unsupported PBIR predicate: ' + ($Expression.Keys -join ', '))
}

function Get-PbirFilters($Document, [hashtable]$TableMap = @{}) {
    $result = [Collections.Generic.List[string]]::new()
    $config = $Document['filterConfig']
    if (-not $config) { return $result.ToArray() }
    foreach ($entry in $config['filters']) {
        $filter = $entry['filter']
        if (-not $filter) { continue } # Empty field-well/drill-through placeholders are not predicates.
        $aliases = @{}
        foreach ($source in $filter['From']) { $aliases[$source['Name']] = $source['Entity'] }
        foreach ($where in $filter['Where']) {
            $result.Add((Convert-PbirExpression $where['Condition'] $aliases $TableMap))
        }
    }
    return $result.ToArray()
}

function Get-ColumnFilterEntries($Document, [string]$Column) {
    if (-not $Document['filterConfig']) { return ,@() }
    return ,@($Document['filterConfig']['filters'] | Where-Object {
        $_['field']['Column'] -and $_['field']['Column']['Expression']['SourceRef']['Entity'] -eq '01 XER_TASK' -and
        $_['field']['Column']['Property'] -eq $Column -and $_['filter']
    })
}

function Join-DaxFilters([string[]]$Filters) {
    return (@($Filters | ForEach-Object { "KEEPFILTERS($_)" }) -join ",`n")
}

function Get-SnapshotFilters($Snapshot, [string]$Table = '01 XER_TASK') {
    $project = $Snapshot.'01 XER_TASK[ProjectCode]'.Replace('"', '""')
    $programme = $Snapshot.'01 XER_TASK[ProgrammeType]'.Replace('"', '""')
    $date = [datetime]$Snapshot.'01 XER_TASK[UpdateDate]'
    return @"
TREATAS({"$project"},'$Table'[ProjectCode]),TREATAS({"$programme"},'$Table'[ProgrammeType]),
TREATAS({DATE($($date.Year),$($date.Month),$($date.Day))},'$Table'[UpdateDate])
"@
}

function Get-Cell($Row, [string]$Name) { return $Row.PSObject.Properties["[$Name]"].Value }

function Get-PbirMeasureReferences($Node) {
    if ($Node -is [System.Collections.IDictionary]) {
        if ($Node.Contains('Measure')) {
            $measure = $Node['Measure']
            if ($measure['Expression']['SourceRef']['Entity'] -and $measure['Property']) {
                $measure['Expression']['SourceRef']['Entity'] + '[' + $measure['Property'] + ']'
            }
        }
        foreach ($key in $Node.Keys) { Get-PbirMeasureReferences $Node[$key] }
    } elseif ($Node -is [System.Collections.IEnumerable] -and $Node -isnot [string]) {
        foreach ($item in $Node) { Get-PbirMeasureReferences $item }
    }
}

Assert-Drill ($routes.Count -eq 2) 'Exactly two drill-through routes must remain.' -Static
Assert-Drill (-not (Test-Path -LiteralPath (Join-Path $reportRoot 'pages/db92ae49184b6932662e'))) 'Removed Date alignment page still exists.' -Static
Assert-Drill (@(Get-ChildItem -LiteralPath (Join-Path $reportRoot 'pages') -Directory).Count -eq 15) 'Expected 15 retained report pages.' -Static
foreach ($name in $removedMeasures) {
    Assert-Drill ($null -eq $disk.Tables['XER Metrics'].Measures.Find($name)) "Removed measure remains in source: $name" -Static
}
$report = Read-Pbir (Join-Path $reportRoot 'report.json')
$source = Read-Pbir (Join-Path $reportRoot "pages/$sourcePageID/page.json")
$reportFilters = @(Get-PbirFilters $report)
$sourceFilters = @($reportFilters) + @(Get-PbirFilters $source)
Assert-Drill ((Get-ColumnFilterEntries $report 'Is Unscheduled').Count -eq 0) 'Report-level unscheduled exclusion still suppresses detail candidates.' -Static
Assert-Drill ((Get-ColumnFilterEntries $source 'Is Unscheduled').Count -eq 0) 'Source page still transfers an unscheduled exclusion.' -Static
$governance = Get-ColumnFilterEntries $report 'IsExcludedFromDataLake'
Assert-Drill ($governance.Count -eq 1) 'The global datalake exclusion must be retained exactly once.' -Static
Assert-Drill (($reportFilters -join ' ') -match "\[IsExcludedFromDataLake\].*FALSE\(\)") 'Global datalake exclusion is not false.' -Static

# Preserve the original scheduled-only behaviour of every other existing page.
$healthPages = @($sourcePageID) + @($routes | ForEach-Object { $_.Page })
$normalPages = 0
foreach ($directory in Get-ChildItem -LiteralPath (Join-Path $reportRoot 'pages') -Directory) {
    if ($directory.Name -in $healthPages) { continue }
    $page = Read-Pbir (Join-Path $directory.FullName 'page.json')
    $filters = Get-ColumnFilterEntries $page 'Is Unscheduled'
    Assert-Drill ($filters.Count -eq 1) "Normal page $($page['displayName']) lost or duplicated its scheduled-only exclusion." -Static
    Assert-Drill (((Get-PbirFilters $page) -join ' ') -match "\[Is Unscheduled\].*FALSE\(\)") "Normal page $($page['displayName']) has the wrong unscheduled predicate." -Static
    $normalPages++
}

foreach ($route in $routes) {
    $page = Read-Pbir (Join-Path $reportRoot "pages/$($route.Page)/page.json")
    $route.Document = $page
    $route.Filters = @($reportFilters) + @(Get-PbirFilters $page)
    Assert-Drill ((Get-ColumnFilterEntries $page 'Is Unscheduled').Count -eq 0) "$($route.Measure) target excludes unscheduled tasks." -Static
    $binding = $page['pageBinding']
    Assert-Drill ($binding['type'] -eq 'Drillthrough') "$($route.Measure) target is not a drill-through page." -Static
    Assert-Drill ($binding['acceptsFilterContext'] -ne 'None') "$($route.Measure) does not inherit context." -Static
    $parameters = @($binding['parameters'])
    Assert-Drill ($parameters.Count -eq 1 -and $parameters[0]['fieldExpr']['Measure']['Property'] -eq $route.Measure -and
        $parameters[0]['fieldExpr']['Measure']['Expression']['SourceRef']['Entity'] -eq 'XER Metrics') "$($route.Measure) drill binding changed." -Static
    $predicates = $route.Filters -join ' '
    foreach ($required in @('status_code', 'task_type', $route.Column)) {
        Assert-Drill ($predicates.Contains("[$required]")) "$($route.Measure) lacks its $required population predicate." -Static
    }
    $matrices = @()
    $visualRefs = @()
    foreach ($directory in Get-ChildItem -LiteralPath (Join-Path $reportRoot "pages/$($route.Page)/visuals") -Directory) {
        $visual = Read-Pbir (Join-Path $directory.FullName 'visual.json')
        $visualRefs += @(Get-PbirMeasureReferences $visual)
        if ($visual['visual']['visualType'] -notlike 'P6WBSMatrix*') { continue }
        $matrices += $visual
    }
    Assert-Drill ($matrices.Count -eq 1) "$($route.Measure) needs one activity detail matrix." -Static
    $matrix = $matrices[0]
    $route.Matrix = $matrix
    $activity = @($matrix['visual']['query']['queryState']['Activity']['projections'])
    Assert-Drill ($activity.Count -eq 1 -and $activity[0]['field']['Column']['Property'] -eq 'task_code' -and
        $activity[0]['field']['Column']['Expression']['SourceRef']['Entity'] -eq '01 XER_TASK') "$($route.Measure) matrix activity grain is not task_code." -Static
    $route.Filters += @(Get-PbirFilters $matrix)
    $matrixRefs = @(Get-PbirMeasureReferences $matrix)
    foreach ($helper in @('SM Drill Status', $route.Detail)) {
        Assert-Drill ($matrixRefs -contains "XER Metrics[$helper]") "$($route.Measure) matrix does not bind $helper." -Static
    }
    foreach ($helper in @($route.Header, 'SM Drill Data Date', 'SM Drill Source File')) {
        Assert-Drill ($visualRefs -contains "XER Metrics[$helper]") "$($route.Measure) page does not bind $helper." -Static
    }
}

$target = Connect-ScheduleMetricsModel -ServerAddress $ServerAddress -Catalog $Catalog
try {
    # Verify the intended model before any data query. Loaded route counts are
    # always tested directly; only new display helpers may use proposed DAX.
    Assert-Drill ($target.Database.Model.Tables.Contains('Project_Dimension')) 'Unexpected model: Project_Dimension absent.'
    Assert-Drill ($target.Database.Model.Tables.Contains('03 XER_PROJWBS')) 'Unexpected model: WBS absent.'
    $coreNames = @('Task_Count', 'SM Snapshot Valid') + @($routes | ForEach-Object { $_.Measure })
    foreach ($name in $coreNames) {
        $loaded = $target.Database.Model.Tables['XER Metrics'].Measures.Find($name)
        Assert-Drill ($null -ne $loaded) "Loaded core measure missing: $name"
        Assert-Drill ($loaded.Expression.Trim() -eq $disk.Tables['XER Metrics'].Measures[$name].Expression.Trim()) "Loaded core expression differs from disk: $name"
    }
    if ($UseLoadedModel) {
        foreach ($name in $removedMeasures) {
            Assert-Drill ($null -eq $target.Database.Model.Tables['XER Metrics'].Measures.Find($name)) "Removed measure remains loaded: $name"
        }
    }
    Write-Output "Verified read-only target $($target.Address), catalog $($target.Database.ID)."
    $snapshots = Invoke-ScheduleMetricsDax $target @'
EVALUATE SUMMARIZECOLUMNS('01 XER_TASK'[ProjectCode],'01 XER_TASK'[ProgrammeType],'01 XER_TASK'[UpdateDate],
TREATAS({FALSE()},'01 XER_TASK'[IsExcludedFromDataLake]),"Rows",COUNTROWS('01 XER_TASK'))
ORDER BY '01 XER_TASK'[ProjectCode],'01 XER_TASK'[ProgrammeType],'01 XER_TASK'[UpdateDate]
'@
    Assert-Drill ($snapshots.Count -gt 0) 'No loaded snapshots to validate.'
    $snapshotComparisons = 0
    $zeroCases = 0
    $wbsComparisons = 0
    $populationSnapshots = if ($HelpersOnly) { @() } else { $snapshots }
    foreach ($snapshot in $populationSnapshots) {
        $scope = Get-SnapshotFilters $snapshot
        foreach ($route in $routes) {
            $sourceDax = Join-DaxFilters $sourceFilters
            $detailDax = Join-DaxFilters $route.Filters
            $query = @"
EVALUATE CALCULATETABLE(ROW(
"Source",CALCULATE([$($route.Measure)],$sourceDax),
"Detail",COALESCE(CALCULATE(COUNTROWS('01 XER_TASK'),$detailDax),0),
"DistinctCodes",COALESCE(CALCULATE(DISTINCTCOUNT('01 XER_TASK'[task_code]),$detailDax),0)),
$scope)
"@
            $result = (Invoke-ScheduleMetricsDax $target $query)[0]
            $sourceCount = Get-Cell $result 'Source'
            $detailCount = Get-Cell $result 'Detail'
            Assert-Drill (Test-ScheduleMetricNumber $sourceCount $detailCount) "$($route.Measure) count mismatch at $scope"
            Assert-Drill (Test-ScheduleMetricNumber $detailCount (Get-Cell $result 'DistinctCodes')) "$($route.Measure) detail records collapse at activity-code grain."
            $snapshotComparisons++
            if ($sourceCount -eq 0) { $zeroCases++ }
            if (-not $SkipWbs) {
            # Exercise actual WBS dimension filtering, rather than copying an
            # activity-table WBS predicate; the report uses this relationship.
            $query = @"
EVALUATE CALCULATETABLE(
FILTER(SUMMARIZECOLUMNS('03 XER_PROJWBS'[wbs_id_key],
"ScopedRows",COUNTROWS('01 XER_TASK'),
"Source",CALCULATE([$($route.Measure)],$sourceDax),
"Detail",COALESCE(CALCULATE(COUNTROWS('01 XER_TASK'),$detailDax),0)),[ScopedRows]>0),$scope)
"@
            $wbsRows = Invoke-ScheduleMetricsDax $target $query
            foreach ($wbs in $wbsRows) {
                $sourceWbs = Get-Cell $wbs 'Source'
                $detailWbs = Get-Cell $wbs 'Detail'
                # A WBS containing only completed/non-discrete work has no
                # eligible metric population, and correctly returns BLANK.
                Assert-Drill (($null -eq $sourceWbs -and $detailWbs -eq 0) -or
                    (Test-ScheduleMetricNumber $sourceWbs $detailWbs)) "$($route.Measure) differs under WBS context."
                $wbsComparisons++
            }
            }
        }
        Write-Output ('PASS routes {0} {1:yyyy-MM-dd}: two retained counts' -f $snapshot.'01 XER_TASK[ProjectCode]',[datetime]$snapshot.'01 XER_TASK[UpdateDate]')
    }
    if (-not $HelpersOnly) {
        Assert-Drill ($zeroCases -gt 0) 'The loaded sample did not exercise an empty destination; fixture coverage still runs below.'
    }

    # Isolated records deliberately include qualifying unscheduled activities,
    # blank classifications, excluded types/statuses, governance exclusions,
    # and records outside the requested project/programme/update/WBS.
    $fixtureTable = @'
TABLE '__SM Drill Tasks' = DATATABLE(
"task_code",STRING,"ProjectCode",STRING,"ProgrammeType",STRING,"UpdateDate",STRING,"wbs_id_key",STRING,
"status_code",STRING,"StatusCategory",STRING,"task_type",STRING,"TaskType_Classified",STRING,
"Is Unscheduled",BOOLEAN,"IsExcludedFromDataLake",BOOLEAN,
"No Predecessor",INTEGER,"No Successor",INTEGER,"Driven_DataDate",STRING,
{
{"A","P1","C","D1","W1","Not Started","Not Complete","TT_Task","Activity",FALSE,FALSE,1,0,"Driven"},
{"B","P1","C","D1","W1","Not Started","Not Complete","TT_Task","Activity",TRUE,FALSE,1,0,"Driven"},
{"C","P1","C","D1","W1","In Progress","Not Complete","TT_Rsrc","Activity",TRUE,FALSE,0,1,"Not Driven"},
{"D","P1","C","D1","W1","In Progress","Not Complete","TT_Task","Activity",TRUE,FALSE,0,0,BLANK()},
{"E","P1","C","D1","W2","Not Started","Not Complete","TT_Task","Activity",FALSE,FALSE,0,1,BLANK()},
{"F","P1","C","D1","W1","Complete","Complete","TT_Task","Activity",FALSE,FALSE,1,1,"Driven"},
{"G","P1","C","D1","W1","Not Started","Not Complete","TT_Mile","Milestone",FALSE,FALSE,1,1,"Driven"},
{"H","P1","C","D1","W1","Not Started","Not Complete","TT_LOE","Level Of Effort",FALSE,FALSE,1,1,"Driven"},
{"I","P1","C","D1","W1","Not Started","Not Complete","TT_WBS","WBS Summary",FALSE,FALSE,1,1,"Driven"},
{"J","P1","C","D1","W1","Not Started","Not Complete","TT_Task","Activity",FALSE,TRUE,1,1,"Driven"},
{"K","P2","C","D1","W1","Not Started","Not Complete","TT_Task","Activity",FALSE,FALSE,1,1,"Driven"},
{"L","P1","P","D1","W1","Not Started","Not Complete","TT_Task","Activity",FALSE,FALSE,1,1,"Driven"},
{"M","P1","C","D2","W1","Not Started","Not Complete","TT_Task","Activity",FALSE,FALSE,1,1,"Driven"},
{"N","P1","C","D1","W2","In Progress","Not Complete","TT_Task","Activity",FALSE,FALSE,1,1,"Driven"}
})
'@
    $fixtureDefinitions = "DEFINE`n$fixtureTable`nMEASURE 'XER Metrics'[SM Snapshot Valid] = TRUE()`n"
    foreach ($name in @('Task_Count') + @($routes | ForEach-Object { $_.Measure })) {
        $expression = $disk.Tables['XER Metrics'].Measures[$name].Expression.Replace("'01 XER_TASK'", "'__SM Drill Tasks'")
        $fixtureDefinitions += "MEASURE 'XER Metrics'[$name] = $expression`n"
    }
    $map = @{ '01 XER_TASK' = '__SM Drill Tasks' }
    $fixtureSource = Join-DaxFilters (@(Get-PbirFilters $report $map) + @(Get-PbirFilters $source $map))
    $fixtureScope = @'
TREATAS({"P1"},'__SM Drill Tasks'[ProjectCode]),TREATAS({"C"},'__SM Drill Tasks'[ProgrammeType]),
TREATAS({"D1"},'__SM Drill Tasks'[UpdateDate])
'@
    $fixtures = @(
        @{ Name='whole selected snapshot'; Extra=''; Expected=@(3,3) },
        @{ Name='WBS W1 retains qualifying unscheduled activities'; Extra=",TREATAS({`"W1`"},'__SM Drill Tasks'[wbs_id_key])"; Expected=@(2,1) },
        @{ Name='WBS W2 scope'; Extra=",TREATAS({`"W2`"},'__SM Drill Tasks'[wbs_id_key])"; Expected=@(1,2) },
        @{ Name='qualifying unscheduled task B'; Extra=",TREATAS({`"B`"},'__SM Drill Tasks'[task_code])"; Expected=@(1,0) },
        @{ Name='qualifying unscheduled resource task C'; Extra=",TREATAS({`"C`"},'__SM Drill Tasks'[task_code])"; Expected=@(0,1) },
        @{ Name='activity without either missing-logic flag'; Extra=",TREATAS({`"D`"},'__SM Drill Tasks'[task_code])"; Expected=@(0,0) }
    )
    $fixtureComparisons = 0
    $activeFixtures = if ($HelpersOnly) { @() } else { $fixtures }
    foreach ($case in $activeFixtures) {
        Assert-Drill ($case.Expected.Count -eq $routes.Count) 'Fixture expectations must match the two retained routes.'
        for ($index=0; $index -lt $routes.Count; $index++) {
            $route = $routes[$index]
            $detailFilters = Join-DaxFilters (@(Get-PbirFilters $report $map) + @(Get-PbirFilters $route.Document $map) + @(Get-PbirFilters $route.Matrix $map))
            $query = @"
$fixtureDefinitions
EVALUATE CALCULATETABLE(ROW(
"Source",CALCULATE([$($route.Measure)],$fixtureSource),
"Detail",COALESCE(CALCULATE(COUNTROWS('__SM Drill Tasks'),$detailFilters),0)),
$fixtureScope$($case.Extra))
"@
            $row = (Invoke-ScheduleMetricsDax $target $query)[0]
            Assert-Drill (Test-ScheduleMetricNumber (Get-Cell $row 'Source') $case.Expected[$index]) "Fixture source: $($case.Name), $($route.Measure)"
            Assert-Drill (Test-ScheduleMetricNumber (Get-Cell $row 'Detail') $case.Expected[$index]) "Fixture PBIR destination: $($case.Name), $($route.Measure)"
            $fixtureComparisons++
        }
    }

    # Display-helper validation is added only when all named helpers exist;
    # absence is reported explicitly rather than silently claiming coverage.
    $helperNames = @('SM Drill Snapshot Available', 'SM Drill Context', 'SM Drill Data Date', 'SM Drill Source File', 'SM Drill Status') + @($routes | ForEach-Object { $_.Header; $_.Detail })
    $helpersPresent = @($helperNames | Where-Object { $null -ne $disk.Tables['XER Metrics'].Measures.Find($_) })
    Assert-Drill ($helpersPresent.Count -eq $helperNames.Count) 'Drill display helpers are not all present in the source model.'
    $helperDefinitions = ''
    if ($UseLoadedModel) {
        foreach ($name in $helperNames) {
            $loaded = $target.Database.Model.Tables['XER Metrics'].Measures.Find($name)
            Assert-Drill ($null -ne $loaded -and $loaded.Expression.Trim() -eq $disk.Tables['XER Metrics'].Measures[$name].Expression.Trim()) "Loaded drill helper differs: $name"
        }
    } else {
        $helperDefinitions = "DEFINE`n" + (($helperNames | ForEach-Object {
            "MEASURE 'XER Metrics'[$_] = " + $disk.Tables['XER Metrics'].Measures[$_].Expression
        }) -join "`n")
    }
    $helperChecks = 0
    foreach ($snapshot in $snapshots) {
        $scope = Get-SnapshotFilters $snapshot
        $sourceDax = Join-DaxFilters $sourceFilters
        foreach ($route in $routes) {
            $detailDax = Join-DaxFilters $route.Filters
            $prefix = $route.Measure
            $query = @"
$helperDefinitions
EVALUATE CALCULATETABLE(
VAR SourceCount = CALCULATE([$($route.Measure)],$sourceDax)
VAR ExpectedContext = SELECTEDVALUE('01 XER_TASK'[ProjectName]) & " | " & FORMAT(SELECTEDVALUE('01 XER_TASK'[UpdateDate]),"MMMM yyyy")
VAR ExpectedHeader = "$prefix`: " & FORMAT(COALESCE(SourceCount,0),"#,0") & IF(SourceCount=1," matching activity"," matching activities") & " | " & ExpectedContext
VAR ExpectedDataDate = "Data date: " & IF(ISBLANK(SELECTEDVALUE('01 XER_TASK'[data_date])),"Unavailable or multiple",FORMAT(SELECTEDVALUE('01 XER_TASK'[data_date]),"dd MMM yyyy"))
VAR ExpectedFile = SELECTEDVALUE('01 XER_TASK'[FileName],"Multiple or unavailable source files")
VAR ActivityEvidenceRows = CALCULATETABLE(SUMMARIZECOLUMNS('01 XER_TASK'[task_code],
    "ActualStatus",[SM Drill Status],"ExpectedStatus",SELECTEDVALUE('01 XER_TASK'[status_code]),
    "ActualEvidence",[$($route.Detail)],"ExpectedEvidence",SELECTEDVALUE('01 XER_TASK'[$($route.Column)]),
    "Rows",COUNTROWS('01 XER_TASK')),$detailDax)
VAR WbsSummary = CALCULATETABLE(SUMMARIZECOLUMNS('03 XER_PROJWBS'[Level_2],
    "ActualStatus",[SM Drill Status],"ActualEvidence",[$($route.Detail)],
    "Rows",COUNTROWS('01 XER_TASK')),$detailDax)
RETURN ROW(
    "SnapshotAvailable",CALCULATE([SM Drill Snapshot Available],$detailDax),
    "ContextMatches",CALCULATE([SM Drill Context],$detailDax)==ExpectedContext,
    "HeaderMatches",CALCULATE([$($route.Header)],$detailDax)==ExpectedHeader,
    "DataDateMatches",CALCULATE([SM Drill Data Date],$detailDax)==ExpectedDataDate,
    "SourceFileMatches",CALCULATE([SM Drill Source File],$detailDax)==ExpectedFile,
    "LeafCount",COALESCE(COUNTROWS(FILTER(ActivityEvidenceRows,[Rows]>0)),0),"ExpectedLeafCount",COALESCE(SourceCount,0),
    "WrongLeafStatus",COALESCE(COUNTROWS(FILTER(ActivityEvidenceRows,[Rows]>0 && NOT([ActualStatus]==[ExpectedStatus]))),0),
    "WrongLeafEvidence",COALESCE(COUNTROWS(FILTER(ActivityEvidenceRows,[Rows]>0 && NOT([ActualEvidence]==[ExpectedEvidence]))),0),
    "NonblankWbsStatus",COALESCE(COUNTROWS(FILTER(WbsSummary,[Rows]>0 && NOT ISBLANK([ActualStatus]))),0),
    "NonblankWbsEvidence",COALESCE(COUNTROWS(FILTER(WbsSummary,[Rows]>0 && NOT ISBLANK([ActualEvidence]))),0)),
$scope,$(Join-DaxFilters $reportFilters))
"@
            $row = (Invoke-ScheduleMetricsDax $target $query)[0]
            foreach ($field in @('SnapshotAvailable','ContextMatches','HeaderMatches','DataDateMatches','SourceFileMatches')) {
                Assert-Drill ((Get-Cell $row $field) -eq $true) "$($route.Measure) $field failed under destination filters at $scope"
                $helperChecks++
            }
            Assert-Drill (Test-ScheduleMetricNumber (Get-Cell $row 'LeafCount') (Get-Cell $row 'ExpectedLeafCount')) "$($route.Measure) activity evidence rows do not match source count."
            $helperChecks++
            foreach ($field in @('WrongLeafStatus','WrongLeafEvidence','NonblankWbsStatus','NonblankWbsEvidence')) {
                Assert-Drill ((Get-Cell $row $field) -eq 0) "$($route.Measure) $field is nonzero."
                $helperChecks++
            }
        }
    }

    # Direct page access must not present an unavailable/ambiguous snapshot as
    # a valid zero. Generate cases from the loaded sample, including an update
    # after one project's last available snapshot and multiple real updates.
    $guardCases = [Collections.Generic.List[object]]::new()
    $firstProject = $snapshots[0].'01 XER_TASK[ProjectCode]'
    $firstProgramme = $snapshots[0].'01 XER_TASK[ProgrammeType]'
    $projectSnapshots = @($snapshots | Where-Object {
        $_.'01 XER_TASK[ProjectCode]' -eq $firstProject -and $_.'01 XER_TASK[ProgrammeType]' -eq $firstProgramme
    } | Sort-Object { [datetime]$_.'01 XER_TASK[UpdateDate]' })
    $missingDate = ([datetime]$projectSnapshots[-1].'01 XER_TASK[UpdateDate]').AddMonths(1)
    $projectLiteral = $firstProject.Replace('"','""')
    $programmeLiteral = $firstProgramme.Replace('"','""')
    $projectScope = "TREATAS({`"$projectLiteral`"},'01 XER_TASK'[ProjectCode]),TREATAS({`"$programmeLiteral`"},'01 XER_TASK'[ProgrammeType])"
    $missingDateDax = "DATE($($missingDate.Year),$($missingDate.Month),$($missingDate.Day))"
    $guardCases.Add(@{Name='unavailable task update'; Scope="$projectScope,TREATAS({$missingDateDax},'01 XER_TASK'[UpdateDate])"})
    $guardCases.Add(@{Name='unavailable CurrentDate selection'; Scope="$projectScope,TREATAS({$missingDateDax},CurrentDate[UpdateDate])"})
    if ($projectSnapshots.Count -gt 1) {
        $selectedDates = @($projectSnapshots | Select-Object -First 2 | ForEach-Object {
            $date=[datetime]$_.'01 XER_TASK[UpdateDate]'; "DATE($($date.Year),$($date.Month),$($date.Day))"
        }) -join ','
        $guardCases.Add(@{Name='multiple task updates'; Scope="$projectScope,TREATAS({$selectedDates},'01 XER_TASK'[UpdateDate])"})
        $guardCases.Add(@{Name='multiple CurrentDate selections'; Scope="$projectScope,TREATAS({$selectedDates},CurrentDate[UpdateDate])"})
    }
    $sharedUpdate = @($snapshots | Group-Object -Property { $_.'01 XER_TASK[UpdateDate]' } |
        Where-Object { @($_.Group.'01 XER_TASK[ProjectCode]' | Select-Object -Unique).Count -gt 1 } | Select-Object -First 1)
    if ($sharedUpdate.Count) {
        $date=[datetime]$sharedUpdate[0].Group[0].'01 XER_TASK[UpdateDate]'
        $projectValues = @($sharedUpdate[0].Group.'01 XER_TASK[ProjectCode]' | Select-Object -Unique | ForEach-Object {
            '"' + $_.Replace('"','""') + '"'
        }) -join ','
        $guardCases.Add(@{Name='multiple projects at one update'; Scope="TREATAS({$projectValues},'01 XER_TASK'[ProjectCode]),TREATAS({DATE($($date.Year),$($date.Month),$($date.Day))},'01 XER_TASK'[UpdateDate])"})
    }
    $guardCases.Add(@{Name='direct access without a snapshot selection'; Scope='REMOVEFILTERS(CurrentDate)'})
    $guardChecks = 0
    foreach ($case in $guardCases) {
        foreach ($route in $routes) {
            $detailDax = Join-DaxFilters $route.Filters
            $query = @"
$helperDefinitions
EVALUATE CALCULATETABLE(ROW("Available",[SM Drill Snapshot Available],"Header",[$($route.Header)]),
$($case.Scope),$detailDax)
"@
            $row = (Invoke-ScheduleMetricsDax $target $query)[0]
            Assert-Drill ((Get-Cell $row 'Available') -eq $false) "$($case.Name): $($route.Measure) incorrectly claims one available snapshot."
            Assert-Drill ((Get-Cell $row 'Header') -eq 'Select one project and available update') "$($case.Name): $($route.Measure) must request a valid snapshot instead of claiming zero matches."
            $guardChecks += 2
        }
    }
    # Exercise the existing identity-validity contract independently from the
    # current cache's clean keys. A structural rejection must not become a
    # zero-match header, even when the selected project/update exists.
    # A query-local input override does not rebind dependencies inside already
    # compiled model measures. Re-declare their exact loaded/proposed expressions
    # for this synthetic fixture only; ordinary loaded checks above have no DEFINE.
    $fixtureHelperTable = if ($UseLoadedModel) { $target.Database.Model.Tables['XER Metrics'] } else { $disk.Tables['XER Metrics'] }
    $invalidIdentityDefinitions = "DEFINE`nMEASURE 'XER Metrics'[SM Snapshot Valid] = FALSE()`n" +
        (($helperNames | ForEach-Object { "MEASURE 'XER Metrics'[$_] = " + $fixtureHelperTable.Measures[$_].Expression }) -join "`n")
    $validScope = Get-SnapshotFilters $snapshots[0]
    foreach ($route in $routes) {
        $detailDax = Join-DaxFilters $route.Filters
        $query = @"
$invalidIdentityDefinitions
EVALUATE CALCULATETABLE(ROW("Available",[SM Drill Snapshot Available],"Header",[$($route.Header)]),
$validScope,$detailDax)
"@
        $row = (Invoke-ScheduleMetricsDax $target $query)[0]
        Assert-Drill ((Get-Cell $row 'Available') -eq $false) "$($route.Measure) ignores a structural snapshot rejection."
        Assert-Drill ((Get-Cell $row 'Header') -eq 'Select one project and available update') "$($route.Measure) represents invalid identities as zero matches."
        $guardChecks += 2
    }
    [pscustomobject]@{
        Status='passed'; Server=$target.Address; Catalog=$target.Database.ID; Assertions=$script:assertions;
        StaticAssertions=$script:staticAssertions; NormalPagesPreserved=$normalPages;
        Snapshots=$snapshots.Count; SnapshotComparisons=$snapshotComparisons; ZeroCountCases=$zeroCases;
        WbsComparisons=$wbsComparisons; WbsSweepSkipped=[bool]$SkipWbs; FixtureComparisons=$fixtureComparisons; HelperChecks=$helperChecks;
        GuardCases=$guardCases.Count; StructuralGuardFixtureCases=1; GuardChecks=$guardChecks;
        StructuralFixtureUsesScopedHelpers=$true;
        HelpersUseLoadedModel=[bool]$UseLoadedModel; HelpersOnly=[bool]$HelpersOnly;
        RouteCountsUseLoadedModel=$true; ModelWrites=$false;
        Limitation='DAX and PBIR contracts only; native navigation, expansion, formatting and exported row sets require Desktop acceptance.'
    } | ConvertTo-Json -Depth 4
} finally { $target.Connection.Disconnect() }
