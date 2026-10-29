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
    @{ Page = '4da217e10ae952b9b4a4'; Label = 'Missing Logic'; Measure = 'SM Missing Logic Count'; LinkExpr = $null; RequiredCols = @('status_code','task_type','SM Fail Missing Logic'); FailCol = 'SM Fail Missing Logic'; FailType = 'string'; Header = 'SM Drill Missing Logic Header'; Detail = 'SM Drill Missing Logic Detail' },
    @{ Page = '566c6f848f9c58ccae18'; Label = 'Leads'; Measure = 'SM Leads Activity Count'; LinkExpr = '[Leads<0d]'; RequiredCols = @('status_code','task_type','SM Fail Leads'); FailCol = 'SM Fail Leads'; FailType = 'int'; Header = 'SM Drill Leads Header'; Detail = 'SM Drill Leads Detail' },
    @{ Page = '2dc1210d106d519e8c33'; Label = 'Lags >5d'; Measure = 'SM Lags Activity Count'; LinkExpr = '[Lags>5d]'; RequiredCols = @('status_code','task_type','SM Fail Lags'); FailCol = 'SM Fail Lags'; FailType = 'int'; Header = 'SM Drill Lags Header'; Detail = 'SM Drill Lags Detail' },
    @{ Page = 'a4aae77cfb0f528bb352'; Label = 'Non-FS Relationships'; Measure = 'SM Non-FS Activity Count'; LinkExpr = '([SM Eligible Relationship Count] - [SM Unknown Relationship Type Count] - [SM FS Count])'; RequiredCols = @('status_code','task_type','SM Fail Non FS'); FailCol = 'SM Fail Non FS'; FailType = 'int'; Header = 'SM Drill Non-FS Header'; Detail = 'SM Drill Non-FS Detail' },
    @{ Page = '4e84ddebb9405ac18f9d'; Label = 'Hard Constraints'; Measure = 'SM Restrictive Primary Count'; LinkExpr = $null; RequiredCols = @('status_code','task_type','cstr_type'); FailCol = $null; FailType = $null; Header = 'SM Drill Restrictive Constraints Header'; Detail = 'SM Drill Restrictive Constraints Detail' },
    @{ Page = '0ce34782f4f350ad83b5'; Label = 'Out-of-Sequence'; Measure = 'Out Of Sequence Count'; LinkExpr = $null; RequiredCols = @('status_code','task_type','SM Fail Out Of Sequence'); FailCol = 'SM Fail Out Of Sequence'; FailType = 'int'; Header = 'SM Drill Out-of-Sequence Header'; Detail = 'SM Drill Out-of-Sequence Detail' },
    @{ Page = '1650221e71f2522ca403'; Label = 'Negative Float'; Measure = 'Task_Count_Negative_Float'; LinkExpr = $null; RequiredCols = @('status_code','task_type','total_float'); FailCol = $null; FailType = $null; Header = 'SM Drill Negative Float Header'; Detail = 'SM Drill Negative Float Detail' },
    @{ Page = '381cf6286aea5f0a94f6'; Label = 'Remaining Duration >44d'; Measure = 'Dur >44'; LinkExpr = $null; RequiredCols = @('status_code','task_type','remaining_duration'); FailCol = $null; FailType = $null; Header = 'SM Drill Remaining Duration Header'; Detail = 'SM Drill Remaining Duration Detail' },
    @{ Page = '7a03ed9cacd75d91903e'; Label = 'Date Integrity'; Measure = 'SM Invalid Dates Count'; LinkExpr = $null; RequiredCols = @('status_code','task_type','SM Fail Invalid Dates'); FailCol = 'SM Fail Invalid Dates'; FailType = 'string'; Header = 'SM Drill Date Integrity Header'; Detail = 'SM Drill Date Integrity Detail' },
    @{ Page = '68cba7045a475d22afb7'; Label = 'Baseline Coverage'; Measure = 'SM Baseline Unmatched Activity Count'; LinkExpr = $null; RequiredCols = @('status_code','task_type','SM Fail Baseline Coverage'); FailCol = 'SM Fail Baseline Coverage'; FailType = 'string'; Header = 'SM Drill Baseline Coverage Header'; Detail = 'SM Drill Baseline Coverage Detail' }
)

$failColumnNames = @(
    'SM Fail Missing Logic',
    'SM Fail Leads',
    'SM Fail Lags',
    'SM Fail Non FS',
    'SM Fail Out Of Sequence',
    'SM Fail Invalid Dates',
    'SM Fail Baseline Coverage'
)

$sourcePageID = '327b48a7fbd37ce0a51c'
$sourceTableID = '58fbc09d197fe53515d8'
$removedPages = @('db92ae49184b6932662e', '061f748900951ae92ba9', '4f15f55676d2add4e922')
$removedMeasures = @(
    'DD Driving','DataDate%','DataDate% (History)',
    'SM Drill Date Alignment Header','SM Drill Date Alignment Reason',
    'SM Drill Missing Predecessor Header','SM Drill Missing Predecessor Flag',
    'SM Drill Missing Successor Header','SM Drill Missing Successor Flag'
)

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
        $rightDax = Convert-PbirExpression $node['Right'] $Aliases $TableMap
        $op = if ($kind -eq 0 -and $rightDax -eq 'BLANK()') { '==' } else { $operators[$kind] }
        return '(' + (Convert-PbirExpression $node['Left'] $Aliases $TableMap) + ' ' + $op + ' ' + $rightDax + ')'
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
        if (-not $filter) { continue }
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

Assert-Drill ($routes.Count -eq 10) 'Exactly ten scored drill-through routes must exist.' -Static
foreach ($retiredPage in $removedPages) {
    Assert-Drill (-not (Test-Path -LiteralPath (Join-Path $reportRoot "pages/$retiredPage"))) "Removed page still exists: $retiredPage" -Static
}
Assert-Drill (@(Get-ChildItem -LiteralPath (Join-Path $reportRoot 'pages') -Directory).Count -eq 21) 'Expected 21 retained report pages (11 visible + 10 hidden drill-through).' -Static
foreach ($name in $removedMeasures) {
    Assert-Drill ($null -eq $disk.Tables['XER Metrics'].Measures.Find($name)) "Removed measure remains in source: $name" -Static
}
foreach ($col in $failColumnNames) {
    Assert-Drill ($null -ne $disk.Tables['01 XER_TASK'].Columns.Find($col)) "Missing storage-engine failure column in source: $col" -Static
}

$sourceTable = Read-Pbir (Join-Path $reportRoot "pages/$sourcePageID/visuals/$sourceTableID/visual.json")
$tableProjections = @($sourceTable['visual']['query']['queryState']['Values']['projections'])
Assert-Drill ($tableProjections.Count -eq 11) 'Sched. Metrics table must project UpdateDate + 10 scored failing-activity counts.' -Static
$expectedTableMeasures = @($routes | ForEach-Object { $_.Measure })
$actualTableMeasures = @($tableProjections[1..10] | ForEach-Object { $_['field']['Measure']['Property'] })
Assert-Drill (($actualTableMeasures -join '|') -eq ($expectedTableMeasures -join '|')) 'Sched. Metrics table columns do not match the 10 drill-through routes.' -Static

$report = Read-Pbir (Join-Path $reportRoot 'report.json')
$source = Read-Pbir (Join-Path $reportRoot "pages/$sourcePageID/page.json")
$reportFilters = @(Get-PbirFilters $report)
$sourceFilters = @($reportFilters) + @(Get-PbirFilters $source)
Assert-Drill ((Get-ColumnFilterEntries $report 'Is Unscheduled').Count -eq 0) 'Report-level unscheduled exclusion still suppresses detail candidates.' -Static
Assert-Drill ((Get-ColumnFilterEntries $source 'Is Unscheduled').Count -eq 0) 'Source page still transfers an unscheduled exclusion.' -Static
$governance = Get-ColumnFilterEntries $report 'IsExcludedFromDataLake'
Assert-Drill ($governance.Count -eq 1) 'The global datalake exclusion must be retained exactly once.' -Static
Assert-Drill (($reportFilters -join ' ') -match "\[IsExcludedFromDataLake\].*FALSE\(\)") 'Global datalake exclusion is not false.' -Static

$healthPages = @($sourcePageID) + @($routes | ForEach-Object { $_.Page })
$unfilteredPages = @('2cc544dc10a1e237ae90')
foreach ($pageID in $unfilteredPages) {
    $page = Read-Pbir (Join-Path $reportRoot "pages/$pageID/page.json")
    Assert-Drill (@(Get-PbirFilters $page | Where-Object { $_ -match '\[Is Unscheduled\]' }).Count -eq 0 -and
        -not ($page['filterConfig'] -and @($page['filterConfig']['filters'] | Where-Object { $_['field']['Column'] -and $_['field']['Column']['Property'] -eq 'Is Unscheduled' }).Count)) `
        "Page $($page['displayName']) must not filter Is Unscheduled." -Static
}
$normalPages = 0
foreach ($directory in Get-ChildItem -LiteralPath (Join-Path $reportRoot 'pages') -Directory) {
    if ($directory.Name -in $healthPages -or $directory.Name -in $unfilteredPages) { continue }
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
    Assert-Drill ($page['visibility'] -eq 'HiddenInViewMode') "$($route.Measure) target page must be HiddenInViewMode." -Static
    Assert-Drill ((Get-ColumnFilterEntries $page 'Is Unscheduled').Count -eq 0) "$($route.Measure) target excludes unscheduled tasks." -Static
    $binding = $page['pageBinding']
    Assert-Drill ($binding['type'] -eq 'Drillthrough') "$($route.Measure) target is not a drill-through page." -Static
    Assert-Drill ($binding['acceptsFilterContext'] -ne 'None') "$($route.Measure) does not inherit context." -Static
    $parameters = @($binding['parameters'])
    Assert-Drill ($parameters.Count -eq 1 -and $parameters[0]['fieldExpr']['Measure']['Property'] -eq $route.Measure -and
        $parameters[0]['fieldExpr']['Measure']['Expression']['SourceRef']['Entity'] -eq 'XER Metrics') "$($route.Measure) drill binding changed." -Static
    $predicates = $route.Filters -join ' '
    foreach ($required in $route.RequiredCols) {
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
    Assert-Drill (@(Get-PbirFilters $matrix).Count -eq 0) "$($route.Measure) matrix must not carry visual-level filters." -Static
    $activity = @($matrix['visual']['query']['queryState']['Activity']['projections'])
    Assert-Drill ($activity.Count -eq 1 -and $activity[0]['field']['Column']['Property'] -eq 'task_code' -and
        $activity[0]['field']['Column']['Expression']['SourceRef']['Entity'] -eq '01 XER_TASK') "$($route.Measure) matrix activity grain is not task_code." -Static
    $matrixRefs = @(Get-PbirMeasureReferences $matrix)
    foreach ($helper in @('SM Drill Status', $route.Detail)) {
        Assert-Drill ($matrixRefs -contains "XER Metrics[$helper]") "$($route.Measure) matrix does not bind $helper." -Static
    }
    foreach ($helper in @($route.Header, 'SM Drill Context', 'SM Drill Data Date', 'SM Drill Source File')) {
        Assert-Drill ($visualRefs -contains "XER Metrics[$helper]") "$($route.Measure) page does not bind $helper." -Static
    }
}

function Convert-PreReloadMeasureDax([string]$Expr, [hashtable]$FailKeyTableNames) {
    $out = $Expr
    # Replace the 7 unmaterialised SM Fail * columns inside REMOVEFILTERS(...) with task_id_key
    # so simulated TREATAS(FailKeys, '01 XER_TASK'[task_id_key]) filters are cleared identically.
    $removeBlockPattern = "(?s)REMOVEFILTERS\s*\(\s*'01 XER_TASK'\[No Predecessor\].*?'01 XER_TASK'\[Is Unscheduled\]\s*\)"
    $out = [regex]::Replace($out, $removeBlockPattern, @"
REMOVEFILTERS (
        '01 XER_TASK'[task_id_key],
        '01 XER_TASK'[No Predecessor],
        '01 XER_TASK'[No Successor],
        '01 XER_TASK'[Driven_DataDate],
        '01 XER_TASK'[cstr_type],
        '01 XER_TASK'[total_float],
        '01 XER_TASK'[remaining_duration],
        '01 XER_TASK'[status_code],
        '01 XER_TASK'[StatusCategory],
        '01 XER_TASK'[task_type],
        '01 XER_TASK'[TaskType_Classified],
        '01 XER_TASK'[Is Unscheduled]
    )
"@)
    foreach ($col in $FailKeyTableNames.Keys) {
        $tbl = $FailKeyTableNames[$col]
        $escaped = [regex]::Escape("'01 XER_TASK'[$col]")
        $out = [regex]::Replace($out, "KEEPFILTERS\s*\(\s*$escaped\s*>\s*0\s*\)", "KEEPFILTERS ( TREATAS ( SELECTCOLUMNS ( '$tbl', `"k`", '$tbl'[task_id_key] ), '01 XER_TASK'[task_id_key] ) )")
        $out = [regex]::Replace($out, "KEEPFILTERS\s*\(\s*NOT\s+ISBLANK\s*\(\s*$escaped\s*\)\s*\)", "KEEPFILTERS ( TREATAS ( SELECTCOLUMNS ( '$tbl', `"k`", '$tbl'[task_id_key] ), '01 XER_TASK'[task_id_key] ) )")
        $out = [regex]::Replace($out, "SELECTEDVALUE\s*\(\s*$escaped\s*\)", "LOOKUPVALUE ( '$tbl'[val], '$tbl'[task_id_key], SELECTEDVALUE ( '01 XER_TASK'[task_id_key] ) )")
    }
    return $out
}

function Convert-PreReloadFilters([string[]]$Filters, [hashtable]$FailKeyTableNames) {
    $converted = [Collections.Generic.List[string]]::new()
    foreach ($flt in $Filters) {
        $replaced = $false
        foreach ($col in $FailKeyTableNames.Keys) {
            if ($flt.Contains("'01 XER_TASK'[$col]")) {
                $tbl = $FailKeyTableNames[$col]
                $converted.Add("KEEPFILTERS(TREATAS(SELECTCOLUMNS('$tbl',`"k`",'$tbl'[task_id_key]),'01 XER_TASK'[task_id_key]))")
                $replaced = $true
                break
            }
        }
        if (-not $replaced) {
            $converted.Add("KEEPFILTERS($flt)")
        }
    }
    return ($converted -join ",`n")
}

$target = Connect-ScheduleMetricsModel -ServerAddress $ServerAddress -Catalog $Catalog
try {
    Assert-Drill ($target.Database.Model.Tables.Contains('Project_Dimension')) 'Unexpected model: Project_Dimension absent.'
    Assert-Drill ($target.Database.Model.Tables.Contains('03 XER_PROJWBS')) 'Unexpected model: WBS absent.'

    $hasPhysicalFailCols = $true
    foreach ($col in $failColumnNames) {
        if ($null -eq $target.Database.Model.Tables['01 XER_TASK'].Columns.Find($col)) {
            $hasPhysicalFailCols = $false
            break
        }
    }
    if ($UseLoadedModel) {
        Assert-Drill $hasPhysicalFailCols 'UseLoadedModel requires the 7 SM Fail * columns to be materialised in Power BI Desktop.'
        foreach ($col in $failColumnNames) {
            $loadedCol = $target.Database.Model.Tables['01 XER_TASK'].Columns.Find($col)
            Assert-Drill ($loadedCol.Expression.Trim() -eq $disk.Tables['01 XER_TASK'].Columns[$col].Expression.Trim()) "Loaded column differs from disk: $col"
        }
        foreach ($name in $removedMeasures) {
            Assert-Drill ($null -eq $target.Database.Model.Tables['XER Metrics'].Measures.Find($name)) "Removed measure remains loaded: $name"
        }
    }

    $preexistingCore = @(
        'Task_Count', 'SM Snapshot Valid', 'SM Missing Logic Count',
        'SM Restrictive Primary Count', 'Out Of Sequence Count',
        'Task_Count_Negative_Float', 'Dur >44', 'SM Invalid Dates Count',
        'Leads<0d', 'Lags>5d', 'SM Eligible Relationship Count',
        'SM Unknown Relationship Type Count', 'SM FS Count'
    )
    foreach ($name in $preexistingCore) {
        $loaded = $target.Database.Model.Tables['XER Metrics'].Measures.Find($name)
        Assert-Drill ($null -ne $loaded) "Loaded core measure missing: $name"
        Assert-Drill ($loaded.Expression.Trim() -eq $disk.Tables['XER Metrics'].Measures[$name].Expression.Trim()) "Loaded core expression differs from disk: $name"
    }

    $newCountMeasures = @('SM Leads Activity Count', 'SM Lags Activity Count', 'SM Non-FS Activity Count', 'SM Baseline Unmatched Activity Count')
    $helperNames = @('SM Drill Snapshot Available', 'SM Drill Context', 'SM Drill Data Date', 'SM Drill Source File', 'SM Drill Status') +
        @($routes | ForEach-Object { $_.Header; $_.Detail })
    foreach ($name in ($newCountMeasures + $helperNames)) {
        Assert-Drill ($null -ne $disk.Tables['XER Metrics'].Measures.Find($name)) "Disk measure missing: $name"
        if ($UseLoadedModel) {
            $loaded = $target.Database.Model.Tables['XER Metrics'].Measures.Find($name)
            Assert-Drill ($null -ne $loaded -and $loaded.Expression.Trim() -eq $disk.Tables['XER Metrics'].Measures[$name].Expression.Trim()) "Loaded measure differs: $name"
        }
    }

    $failKeyTableNames = @{}
    for ($i = 0; $i -lt $failColumnNames.Count; $i++) {
        $failKeyTableNames[$failColumnNames[$i]] = "__SM_Fail_$i"
    }

    function Get-DefineBlock([string]$ScopeFilterDax = '') {
        if ($UseLoadedModel) { return '' }
        $lines = [Collections.Generic.List[string]]::new()
        $lines.Add('DEFINE')
        if (-not $hasPhysicalFailCols) {
            $baseTaskTable = if ($ScopeFilterDax) {
                "CALCULATETABLE('01 XER_TASK', REMOVEFILTERS('03 XER_PROJWBS'), REMOVEFILTERS('01 XER_TASK'[status_code],'01 XER_TASK'[StatusCategory],'01 XER_TASK'[task_type],'01 XER_TASK'[TaskType_Classified],'01 XER_TASK'[Is Unscheduled],'01 XER_TASK'[cstr_type],'01 XER_TASK'[total_float],'01 XER_TASK'[remaining_duration]), REMOVEFILTERS(Filter_Activity_Status), REMOVEFILTERS(Filter_TaskType), REMOVEFILTERS('00 CALENDAR'), REMOVEFILTERS('00 PLANNED DATE TABLE (PV)'), $ScopeFilterDax)"
            } else {
                "ALLNOBLANKROW('01 XER_TASK')"
            }
            foreach ($col in $failColumnNames) {
                $tbl = $failKeyTableNames[$col]
                $colExpr = $disk.Tables['01 XER_TASK'].Columns[$col].Expression
                $isInt = $col -in @('SM Fail Leads', 'SM Fail Lags', 'SM Fail Non FS', 'SM Fail Out Of Sequence')
                $pred = if ($isInt) { "[val] > 0" } else { "NOT ISBLANK([val]) && [val] <> `"`"" }
                $lines.Add("TABLE '$tbl' = FILTER(SELECTCOLUMNS($baseTaskTable, `"task_id_key`", '01 XER_TASK'[task_id_key], `"val`", $colExpr), $pred)")
            }
            foreach ($mName in ($newCountMeasures + $helperNames)) {
                $mExpr = Convert-PreReloadMeasureDax $disk.Tables['XER Metrics'].Measures[$mName].Expression $failKeyTableNames
                $lines.Add("MEASURE 'XER Metrics'[$mName] = $mExpr")
            }
        } else {
            foreach ($mName in ($newCountMeasures + $helperNames)) {
                $mExpr = $disk.Tables['XER Metrics'].Measures[$mName].Expression
                $lines.Add("MEASURE 'XER Metrics'[$mName] = $mExpr")
            }
        }
        return ($lines -join "`n")
    }

    function Get-EffectiveDetailDax($Route) {
        if ($UseLoadedModel -or $hasPhysicalFailCols) {
            return Join-DaxFilters $Route.Filters
        }
        return Convert-PreReloadFilters $Route.Filters $failKeyTableNames
    }

    Write-Output "Verified read-only target $($target.Address), catalog $($target.Database.ID) (PhysicalFailCols=$hasPhysicalFailCols, UseLoadedModel=$UseLoadedModel)."
    $snapshots = Invoke-ScheduleMetricsDax $target @'
EVALUATE SUMMARIZECOLUMNS('01 XER_TASK'[ProjectCode],'01 XER_TASK'[ProgrammeType],'01 XER_TASK'[UpdateDate],
TREATAS({FALSE()},'01 XER_TASK'[IsExcludedFromDataLake]),"Rows",COUNTROWS('01 XER_TASK'))
ORDER BY '01 XER_TASK'[ProjectCode],'01 XER_TASK'[ProgrammeType],'01 XER_TASK'[UpdateDate]
'@
    Assert-Drill ($snapshots.Count -gt 0) 'No loaded snapshots to validate.'

    $snapshotComparisons = 0
    $zeroCases = 0
    $wbsComparisons = 0
    $helperChecks = 0
    $maxQueryMs = 0
    $sourceDax = Join-DaxFilters $sourceFilters

    foreach ($snapshot in $snapshots) {
        $scope = Get-SnapshotFilters $snapshot
        $defineBlock = Get-DefineBlock $scope

        foreach ($route in $routes) {
            $detailDax = Get-EffectiveDetailDax $route
            if (-not $HelpersOnly) {
                $query = @"
$defineBlock
EVALUATE CALCULATETABLE(ROW(
"Source",CALCULATE([$($route.Measure)],$sourceDax),
"Detail",COALESCE(CALCULATE(COUNTROWS('01 XER_TASK'),$detailDax),0),
"DistinctCodes",COALESCE(CALCULATE(DISTINCTCOUNT('01 XER_TASK'[task_code]),$detailDax),0)),
$scope)
"@
                $sw = [System.Diagnostics.Stopwatch]::StartNew()
                $result = (Invoke-ScheduleMetricsDax $target $query)[0]
                $sw.Stop()
                if ($sw.ElapsedMilliseconds -gt $maxQueryMs) { $maxQueryMs = $sw.ElapsedMilliseconds }
                $sourceCount = Get-Cell $result 'Source'
                $detailCount = Get-Cell $result 'Detail'
                Assert-Drill (Test-ScheduleMetricNumber $sourceCount $detailCount) "$($route.Measure) count mismatch ($sourceCount vs $detailCount) at $scope"
                Assert-Drill (Test-ScheduleMetricNumber $detailCount (Get-Cell $result 'DistinctCodes')) "$($route.Measure) detail records collapse at activity-code grain."
                $snapshotComparisons++
                if ($sourceCount -eq 0) { $zeroCases++ }

                if (-not $SkipWbs) {
                    $wbsQuery = @"
$defineBlock
EVALUATE CALCULATETABLE(
FILTER(SUMMARIZECOLUMNS('03 XER_PROJWBS'[wbs_id_key],
"ScopedRows",COUNTROWS('01 XER_TASK'),
"Source",CALCULATE([$($route.Measure)],$sourceDax),
"Detail",COALESCE(CALCULATE(COUNTROWS('01 XER_TASK'),$detailDax),0)),[ScopedRows]>0),$scope)
"@
                    $wbsRows = Invoke-ScheduleMetricsDax $target $wbsQuery
                    foreach ($wbs in $wbsRows) {
                        $sourceWbs = Get-Cell $wbs 'Source'
                        $detailWbs = Get-Cell $wbs 'Detail'
                        Assert-Drill (($null -eq $sourceWbs -and $detailWbs -eq 0) -or
                            (Test-ScheduleMetricNumber $sourceWbs $detailWbs)) "$($route.Measure) differs under WBS context ($sourceWbs vs $detailWbs)."
                        $wbsComparisons++
                    }
                }
            }

            $label = $route.Label
            $expectedHeaderExpr = if ($route.LinkExpr) {
                "VAR LinkCount = COALESCE(CALCULATE($($route.LinkExpr),$sourceDax),0) RETURN `"$label`: `" & FORMAT(COALESCE(SourceCount,0),`"#,0`") & IF(COALESCE(SourceCount,0)=1,`" matching activity (`",`" matching activities (`") & FORMAT(LinkCount,`"#,0`") & IF(LinkCount=1,`" relationship) | `",`" relationships) | `") & ExpectedContext"
            } else {
                "`"$label`: `" & FORMAT(COALESCE(SourceCount,0),`"#,0`") & IF(COALESCE(SourceCount,0)=1,`" matching activity | `",`" matching activities | `") & ExpectedContext"
            }

            $helperQuery = @"
$defineBlock
EVALUATE CALCULATETABLE(
VAR SourceCount = CALCULATE([$($route.Measure)],$sourceDax)
VAR ExpectedContext = SELECTEDVALUE('01 XER_TASK'[ProjectName]) & " | " & FORMAT(SELECTEDVALUE('01 XER_TASK'[UpdateDate]),"MMMM yyyy")
VAR ExpectedHeader = $expectedHeaderExpr
VAR ExpectedDataDate = "Data date: " & IF(ISBLANK(SELECTEDVALUE('01 XER_TASK'[data_date])),"Unavailable or multiple",FORMAT(SELECTEDVALUE('01 XER_TASK'[data_date]),"dd MMM yyyy"))
VAR ExpectedFile = SELECTEDVALUE('01 XER_TASK'[FileName],"Multiple or unavailable source files")
VAR ActivityEvidenceRows = CALCULATETABLE(SUMMARIZECOLUMNS('01 XER_TASK'[task_code],
    "ActualStatus",[SM Drill Status],"ExpectedStatus",SELECTEDVALUE('01 XER_TASK'[status_code]),
    "ActualEvidence",[$($route.Detail)],
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
    "BlankLeafEvidence",COALESCE(COUNTROWS(FILTER(ActivityEvidenceRows,[Rows]>0 && (ISBLANK([ActualEvidence]) || [ActualEvidence]=="") )),0),
    "NonblankWbsStatus",COALESCE(COUNTROWS(FILTER(WbsSummary,[Rows]>0 && NOT ISBLANK([ActualStatus]))),0),
    "NonblankWbsEvidence",COALESCE(COUNTROWS(FILTER(WbsSummary,[Rows]>0 && NOT ISBLANK([ActualEvidence]))),0)),
$scope,$(Join-DaxFilters $reportFilters))
"@
            $row = (Invoke-ScheduleMetricsDax $target $helperQuery)[0]
            foreach ($field in @('SnapshotAvailable','ContextMatches','HeaderMatches','DataDateMatches','SourceFileMatches')) {
                Assert-Drill ((Get-Cell $row $field) -eq $true) "$($route.Measure) $field failed under destination filters at $scope"
                $helperChecks++
            }
            Assert-Drill (Test-ScheduleMetricNumber (Get-Cell $row 'LeafCount') (Get-Cell $row 'ExpectedLeafCount')) "$($route.Measure) activity evidence rows do not match source count."
            $helperChecks++
            foreach ($field in @('WrongLeafStatus','BlankLeafEvidence','NonblankWbsStatus','NonblankWbsEvidence')) {
                Assert-Drill ((Get-Cell $row $field) -eq 0) "$($route.Measure) $field is nonzero."
                $helperChecks++
            }
        }
        Write-Output ('PASS routes {0} {1:yyyy-MM-dd}: all 10 scored drill-through routes reconciled' -f $snapshot.'01 XER_TASK[ProjectCode]',[datetime]$snapshot.'01 XER_TASK[UpdateDate]')
    }
    if (-not $HelpersOnly) {
        Assert-Drill ($zeroCases -gt 0) 'The loaded sample did not exercise an empty destination; fixture coverage still runs below.'
    }

    # Isolated synthetic fixture covering all 10 routes, including unscheduled tasks,
    # completed tasks/milestones on Date Integrity & Baseline Coverage, restrictive vs
    # non-restrictive constraints, boundary float (0) and duration (44), LOE/WBS, and exclusions.
    $fixtureTable = @'
TABLE '__SM Drill Tasks' = DATATABLE(
"task_id_key",STRING,"task_code",STRING,"ProjectCode",STRING,"ProgrammeType",STRING,"UpdateDate",STRING,"wbs_id_key",STRING,
"status_code",STRING,"StatusCategory",STRING,"task_type",STRING,"TaskType_Classified",STRING,
"Is Unscheduled",BOOLEAN,"IsExcludedFromDataLake",BOOLEAN,
"No Predecessor",INTEGER,"No Successor",INTEGER,"cstr_type",STRING,"total_float",DOUBLE,"remaining_duration",DOUBLE,
"data_date",DATETIME,"Start",DATETIME,"Finish",DATETIME,"act_end_date",DATETIME,
"SM Fail Missing Logic",STRING,"SM Fail Leads",INTEGER,"SM Fail Lags",INTEGER,"SM Fail Non FS",INTEGER,
"SM Fail Out Of Sequence",INTEGER,"SM Fail Invalid Dates",STRING,"SM Fail Baseline Coverage",STRING,
{
{"K_A","A","P1","C","D1","W1","Not Started","Not Complete","TT_Task","Activity",FALSE,FALSE,1,0,"CS_MSO",-5.0,50.0,"2026-06-01","2026-06-10","2026-08-20",BLANK(),"No predecessor",1,0,0,0,BLANK(),"Added after baseline"},
{"K_B","B","P1","C","D1","W1","Not Started","Not Complete","TT_Task","Activity",TRUE,FALSE,1,0,"CS_ALAP",0.0,44.0,"2026-06-01","2026-05-15","2026-07-15",BLANK(),"No predecessor",0,2,1,0,"Not Started before data date",BLANK()},
{"K_C","C","P1","C","D1","W1","In Progress","Not Complete","TT_Rsrc","Activity",TRUE,FALSE,0,1,BLANK(),-1.5,10.0,"2026-06-01","2026-05-20","2026-06-20",BLANK(),"No successor",0,0,1,1,BLANK(),BLANK()},
{"K_D","D","P1","C","D1","W1","In Progress","Not Complete","TT_Task","Activity",FALSE,FALSE,0,0,"CS_MANDFIN",10.0,12.0,"2026-06-01","2026-05-25","2026-06-15",BLANK(),BLANK(),0,0,0,0,BLANK(),BLANK()},
{"K_E","E","P1","C","D1","W2","Not Started","Not Complete","TT_Task","Activity",FALSE,FALSE,1,1,BLANK(),BLANK(),60.0,"2026-06-01","2026-06-05","2026-09-01",BLANK(),"No pred. & no succ.",0,1,0,0,BLANK(),"Baseline finish missing"},
{"K_F","F","P1","C","D1","W1","Complete","Complete","TT_Task","Activity",FALSE,FALSE,1,1,"CS_MSO",-10.0,50.0,"2026-06-01","2026-04-01","2026-05-01",BLANK(),BLANK(),0,0,0,0,"Completed without actual finish","Added after baseline"},
{"K_G","G","P1","C","D1","W1","Not Started","Not Complete","TT_Mile","Milestone",FALSE,FALSE,1,1,"CS_MSO",-5.0,0.0,"2026-06-01",BLANK(),BLANK(),BLANK(),"No pred. & no succ.",0,0,0,0,"Missing start date",BLANK()},
{"K_H","H","P1","C","D1","W1","Not Started","Not Complete","TT_LOE","Level Of Effort",FALSE,FALSE,1,1,"CS_MSO",-5.0,80.0,"2026-06-01","2026-06-05","2026-09-30",BLANK(),BLANK(),0,0,0,0,BLANK(),BLANK()},
{"K_I","I","P1","C","D1","W1","Not Started","Not Complete","TT_WBS","WBS Summary",FALSE,FALSE,1,1,"CS_MSO",-5.0,80.0,"2026-06-01","2026-06-05","2026-09-30",BLANK(),BLANK(),0,0,0,0,BLANK(),BLANK()},
{"K_J","J","P1","C","D1","W1","Not Started","Not Complete","TT_Task","Activity",FALSE,TRUE,1,1,"CS_MSO",-5.0,80.0,"2026-06-01",BLANK(),BLANK(),BLANK(),"No pred. & no succ.",1,1,1,0,"Missing start date","Added after baseline"},
{"K_K","K","P2","C","D1","W1","Not Started","Not Complete","TT_Task","Activity",FALSE,FALSE,1,1,"CS_MSO",-5.0,80.0,"2026-06-01",BLANK(),BLANK(),BLANK(),"No pred. & no succ.",1,1,1,0,"Missing start date","Added after baseline"}
})
TABLE '__SM Drill Preds' = DATATABLE(
"task_id_key",STRING,"pred_task_id_key",STRING,"pred_type",STRING,"lag",DOUBLE,"predecessor_task_type",STRING,"predecessor_status_code",STRING,
{
{"K_C","K_A","PR_FS",0.0,"TT_Task","TK_NotStart"},
{"K_D","K_F","PR_FS",0.0,"TT_Task","TK_Complete"}
})
'@
    $fixtureDefinitions = "DEFINE`n$fixtureTable`nMEASURE 'XER Metrics'[SM Snapshot Valid] = TRUE()`n"
    foreach ($name in (@('Task_Count', 'SM In Progress Count') + @($routes | ForEach-Object { $_.Measure }) | Select-Object -Unique)) {
        $expression = $disk.Tables['XER Metrics'].Measures[$name].Expression.Replace("'01 XER_TASK'", "'__SM Drill Tasks'").Replace("'06 XER_PREDECESSOR'", "'__SM Drill Preds'")
        $fixtureDefinitions += "MEASURE 'XER Metrics'[$name] = $expression`n"
    }
    $map = @{ '01 XER_TASK' = '__SM Drill Tasks' }
    $fixtureSource = Join-DaxFilters (@(Get-PbirFilters $report $map) + @(Get-PbirFilters $source $map))
    $fixtureScope = @'
TREATAS({"P1"},'__SM Drill Tasks'[ProjectCode]),TREATAS({"C"},'__SM Drill Tasks'[ProgrammeType]),
TREATAS({"D1"},'__SM Drill Tasks'[UpdateDate])
'@
    # Route order: MissingLogic, Leads, Lags, NonFS, Restrictive, OutOfSeq, NegFloat, RemDur>44, InvalidDates, BaselineUnmatched
    $fixtures = @(
        @{ Name='whole selected snapshot'; Extra=''; Expected=@(5, 1, 2, 2, 3, 1, 3, 2, 2, 2) },
        @{ Name='WBS W1 retains unscheduled, completed and milestone rules'; Extra=",TREATAS({`"W1`"},'__SM Drill Tasks'[wbs_id_key])"; Expected=@(4, 1, 1, 2, 3, 1, 3, 1, 2, 1) },
        @{ Name='WBS W2 scope'; Extra=",TREATAS({`"W2`"},'__SM Drill Tasks'[wbs_id_key])"; Expected=@(1, 0, 1, 0, 0, 0, 0, 1, 0, 1) },
        @{ Name='unscheduled task B with boundary float=0 and dur=44'; Extra=",TREATAS({`"B`"},'__SM Drill Tasks'[task_code])"; Expected=@(1, 0, 1, 1, 0, 0, 0, 0, 1, 0) },
        @{ Name='unscheduled in-progress resource task C'; Extra=",TREATAS({`"C`"},'__SM Drill Tasks'[task_code])"; Expected=@(1, 0, 0, 1, 0, 1, 1, 0, 0, 0) },
        @{ Name='clean activity D with only mandatory finish constraint'; Extra=",TREATAS({`"D`"},'__SM Drill Tasks'[task_code])"; Expected=@(0, 0, 0, 0, 1, 0, 0, 0, 0, 0) }
    )
    $fixtureComparisons = 0
    $activeFixtures = if ($HelpersOnly) { @() } else { $fixtures }
    foreach ($case in $activeFixtures) {
        Assert-Drill ($case.Expected.Count -eq $routes.Count) 'Fixture expectations must match all 10 routes.'
        for ($index = 0; $index -lt $routes.Count; $index++) {
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
            Assert-Drill (Test-ScheduleMetricNumber (Get-Cell $row 'Source') $case.Expected[$index]) "Fixture source: $($case.Name), $($route.Measure) (got $(Get-Cell $row 'Source'), expected $($case.Expected[$index]))"
            Assert-Drill (Test-ScheduleMetricNumber (Get-Cell $row 'Detail') $case.Expected[$index]) "Fixture PBIR destination: $($case.Name), $($route.Measure) (got $(Get-Cell $row 'Detail'), expected $($case.Expected[$index]))"
            $fixtureComparisons++
        }
    }

    # Guard checks: unavailable, multi-update, multi-project, and unselected snapshots
    # must never claim zero matches.
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

    $guardDefineLines = [Collections.Generic.List[string]]::new()
    if (-not $UseLoadedModel) {
        $guardDefineLines.Add('DEFINE')
        if (-not $hasPhysicalFailCols) {
            foreach ($col in $failColumnNames) {
                $tbl = $failKeyTableNames[$col]
                $isInt = $col -in @('SM Fail Leads', 'SM Fail Lags', 'SM Fail Non FS', 'SM Fail Out Of Sequence')
                $emptyVal = if ($isInt) { '0' } else { '""' }
                $valType = if ($isInt) { 'INTEGER' } else { 'STRING' }
                $guardDefineLines.Add("TABLE '$tbl' = FILTER(DATATABLE(`"task_id_key`", STRING, `"val`", $valType, {{`"`", $emptyVal}}), FALSE())")
            }
            foreach ($mName in ($newCountMeasures + $helperNames)) {
                $mExpr = Convert-PreReloadMeasureDax $disk.Tables['XER Metrics'].Measures[$mName].Expression $failKeyTableNames
                $guardDefineLines.Add("MEASURE 'XER Metrics'[$mName] = $mExpr")
            }
        } else {
            foreach ($mName in ($newCountMeasures + $helperNames)) {
                $guardDefineLines.Add("MEASURE 'XER Metrics'[$mName] = " + $disk.Tables['XER Metrics'].Measures[$mName].Expression)
            }
        }
    }
    $guardDefine = ($guardDefineLines -join "`n")

    $guardChecks = 0
    foreach ($case in $guardCases) {
        foreach ($route in $routes) {
            $detailDax = Get-EffectiveDetailDax $route
            $query = @"
$guardDefine
EVALUATE CALCULATETABLE(ROW("Available",[SM Drill Snapshot Available],"Header",[$($route.Header)]),
$($case.Scope),$detailDax)
"@
            $row = (Invoke-ScheduleMetricsDax $target $query)[0]
            Assert-Drill ((Get-Cell $row 'Available') -eq $false) "$($case.Name): $($route.Measure) incorrectly claims one available snapshot."
            Assert-Drill ((Get-Cell $row 'Header') -eq 'Select one project and available update') "$($case.Name): $($route.Measure) must request a valid snapshot instead of claiming zero matches."
            $guardChecks += 2
        }
    }

    # Structural identity rejection fixture
    $structLines = [Collections.Generic.List[string]]::new()
    $structLines.Add('DEFINE')
    $structLines.Add("MEASURE 'XER Metrics'[SM Snapshot Valid] = FALSE()")
    $fixtureHelperTable = if ($UseLoadedModel) { $target.Database.Model.Tables['XER Metrics'] } else { $disk.Tables['XER Metrics'] }
    if (-not $UseLoadedModel -and -not $hasPhysicalFailCols) {
        foreach ($col in $failColumnNames) {
            $tbl = $failKeyTableNames[$col]
            $isInt = $col -in @('SM Fail Leads', 'SM Fail Lags', 'SM Fail Non FS', 'SM Fail Out Of Sequence')
            $emptyVal = if ($isInt) { '0' } else { '""' }
            $valType = if ($isInt) { 'INTEGER' } else { 'STRING' }
            $structLines.Add("TABLE '$tbl' = FILTER(DATATABLE(`"task_id_key`", STRING, `"val`", $valType, {{`"`", $emptyVal}}), FALSE())")
        }
        foreach ($mName in ($newCountMeasures + $helperNames)) {
            $structLines.Add("MEASURE 'XER Metrics'[$mName] = " + (Convert-PreReloadMeasureDax $fixtureHelperTable.Measures[$mName].Expression $failKeyTableNames))
        }
    } else {
        foreach ($mName in ($newCountMeasures + $helperNames)) {
            $structLines.Add("MEASURE 'XER Metrics'[$mName] = " + $fixtureHelperTable.Measures[$mName].Expression)
        }
    }
    $invalidIdentityDefinitions = ($structLines -join "`n")
    $validScope = Get-SnapshotFilters $snapshots[0]
    foreach ($route in $routes) {
        $detailDax = Get-EffectiveDetailDax $route
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
        Routes=$routes.Count; Snapshots=$snapshots.Count; SnapshotComparisons=$snapshotComparisons; ZeroCountCases=$zeroCases;
        WbsComparisons=$wbsComparisons; WbsSweepSkipped=[bool]$SkipWbs; FixtureComparisons=$fixtureComparisons; HelperChecks=$helperChecks;
        GuardCases=$guardCases.Count; StructuralGuardFixtureCases=1; GuardChecks=$guardChecks;
        MaxSnapshotQueryMs=$maxQueryMs;
        PhysicalFailColumnsLoaded=$hasPhysicalFailCols;
        HelpersUseLoadedModel=[bool]$UseLoadedModel; HelpersOnly=[bool]$HelpersOnly;
        ModelWrites=$false;
        Limitation='DAX and PBIR contracts only; native navigation, expansion, formatting and exported row sets require Desktop acceptance.'
    } | ConvertTo-Json -Depth 4
} finally { $target.Connection.Disconnect() }
