param(
    [string]$ModelRoot,
    [string]$ReportRoot,
    [string]$BaselineReportRoot,
    [string]$OutputPath,
    [string]$TomDirectory,
    [string]$PowerQueryParserDirectory,
    [string]$ReportAuthoringCli
)

# Offline checks only. TOM deserialises metadata but does not compile or execute
# DAX. No Analysis Services connection, data refresh or model mutation occurs.
$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if (-not $ModelRoot) { $ModelRoot = Join-Path $repoRoot 'Project Review - Programme (datalake).SemanticModel\definition' }
if (-not $ReportRoot) { $ReportRoot = Join-Path $repoRoot 'Project Review - Programme (datalake).Report' }
$ModelRoot = (Resolve-Path -LiteralPath $ModelRoot).Path
$ReportRoot = (Resolve-Path -LiteralPath $ReportRoot).Path

if (-not $TomDirectory) {
    $cache = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.nuget\packages\microsoft.analysisservices'
    $package = Get-ChildItem -LiteralPath $cache -Directory |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'lib\net8.0\Microsoft.AnalysisServices.Tabular.dll') } |
        Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
    if (-not $package) { throw 'Pass -TomDirectory pointing to Microsoft.AnalysisServices net8.0 assemblies.' }
    $TomDirectory = Join-Path $package.FullName 'lib\net8.0'
}
$npmCache = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'npm-cache\_npx'
if (-not $PowerQueryParserDirectory) {
    $PowerQueryParserDirectory = Get-ChildItem -LiteralPath $npmCache -Directory |
        ForEach-Object { Join-Path $_.FullName 'node_modules\@microsoft\powerquery-parser' } |
        Where-Object { Test-Path -LiteralPath (Join-Path $_ 'package.json') } | Select-Object -First 1
}
if (-not $ReportAuthoringCli) {
    $ReportAuthoringCli = Get-ChildItem -LiteralPath $npmCache -Directory |
        ForEach-Object { Join-Path $_.FullName 'node_modules\@microsoft\powerbi-report-authoring-cli\dist\cli.js' } |
        Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $PowerQueryParserDirectory) { throw 'Pass -PowerQueryParserDirectory for Microsoft Power Query syntax validation.' }
if (-not $ReportAuthoringCli) { throw 'Pass -ReportAuthoringCli for Microsoft report capability validation.' }
foreach ($name in @('Microsoft.AnalysisServices.Core.dll','Microsoft.AnalysisServices.Tabular.dll','Microsoft.AnalysisServices.Tabular.Json.dll')) {
    [Reflection.Assembly]::LoadFrom((Join-Path $TomDirectory $name)) | Out-Null
}
$model = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeModelFromFolder($ModelRoot)
$scenarioTables = @($model.Tables | Where-Object { $_.Name -like 'Scenario *' -or $_.Name -eq 'Resource Scenario Measures' })
$scenarioMeasures = $model.Tables.Find('Resource Scenario Measures')
$expectedScenarioMeasures = 48
if ($null -eq $scenarioMeasures -or $scenarioMeasures.Measures.Count -ne $expectedScenarioMeasures) { throw "Expected all $expectedScenarioMeasures Resource Scenario Measures, including the two chart and five daily display measures." }
if ($scenarioTables.Count -ne 14) { throw "Expected 14 bounded scenario tables; found $($scenarioTables.Count)." }

$allMeasures = @{}
foreach ($table in $model.Tables) {
    foreach ($measure in $table.Measures) {
        if ($allMeasures.ContainsKey($measure.Name)) { throw "Ambiguous measure name: $($measure.Name)" }
        $allMeasures[$measure.Name] = $measure
    }
}
$references = 0
$edges = @{}
$variableChecks = 0
$tableNames = @{}
foreach ($table in $model.Tables) { $tableNames[$table.Name] = $true }
$daxExpressions = @()
$calculatedTableCount = 0
$calculatedPartitionCount = 0
foreach ($table in $scenarioTables) {
    foreach ($measure in $table.Measures) { $daxExpressions += @{name=($table.Name + '/' + $measure.Name);expression=$measure.Expression} }
    $hasCalculatedPartition = $false
    foreach ($partition in $table.Partitions) {
        if ($partition.Source -is [Microsoft.AnalysisServices.Tabular.CalculatedPartitionSource]) {
            $daxExpressions += @{name=($table.Name + '/' + $partition.Name);expression=$partition.Source.Expression}
            $calculatedPartitionCount++
            $hasCalculatedPartition = $true
        }
    }
    if ($hasCalculatedPartition) { $calculatedTableCount++ }
}
if ($calculatedTableCount -ne 13 -or $calculatedPartitionCount -ne 13 -or $daxExpressions.Count -ne (13 + $expectedScenarioMeasures)) {
    throw "Incomplete expression coverage: expected 13 calculated tables/partitions and $expectedScenarioMeasures measures; found $calculatedTableCount tables, $calculatedPartitionCount partitions and $($daxExpressions.Count) expressions."
}
# These identifiers were rejected by the installed DAX engine during the repair
# investigation. This is a regression list, not a complete DAX parser/denylist.
$knownRejectedVariables = @('FirstDate', 'LastDate', 'Updates', 'Key')
foreach ($item in $daxExpressions) {
    $code = [regex]::Replace($item.expression, '(?s)/\*.*?\*/|(?m)//[^\r\n]*|--[^\r\n]*|"(?:[^"]|"")*"', ' ')
    if ($code -match '(?i)\bCROSSJOIN\s*\(') { throw "Calendar-by-date CROSSJOIN found in $($item.name)." }
    foreach ($match in [regex]::Matches($code, '(?i)\bVAR\s+([A-Z_][A-Z0-9_]*)\s*=')) {
        $name = $match.Groups[1].Value
        if ($tableNames.ContainsKey($name)) { throw "DAX variable '$name' collides with an existing model table in $($item.name)." }
        if ($knownRejectedVariables -contains $name) { throw "Known engine-rejected DAX variable '$name' in $($item.name). This static regression check is not DAX compilation." }
        $variableChecks++
    }
}
foreach ($measure in $scenarioMeasures.Measures) {
    # Remove comments and DAX string values before checking field identifiers.
    $expression = [regex]::Replace($measure.Expression, '(?s)/\*.*?\*/|(?m)//[^\r\n]*|--[^\r\n]*|"(?:[^"]|"")*"', ' ')
    if ($expression -match '(?i)\bCROSSJOIN\s*\(') { throw "Calendar-by-date CROSSJOIN found in $($measure.Name)." }
    foreach ($match in [regex]::Matches($expression, "'(?<table>(?:[^']|'')+)'\s*\[(?<field>(?:[^\]]|\]\])+?)\]")) {
        $tableName = $match.Groups['table'].Value.Replace("''", "'")
        $fieldName = $match.Groups['field'].Value.Replace(']]', ']')
        $table = $model.Tables.Find($tableName)
        if ($null -eq $table) { throw "Unknown table '$tableName' in $($measure.Name)." }
        if ($null -eq $table.Columns.Find($fieldName) -and $null -eq $table.Measures.Find($fieldName)) {
            throw "Unknown field '$tableName'[$fieldName] in $($measure.Name)."
        }
        $references++
    }
    $withoutQualifiedFields = [regex]::Replace($expression, "'(?:[^']|'')+'\s*\[(?:[^\]]|\]\])+?\]", ' ')
    $edges[$measure.Name] = @([regex]::Matches($withoutQualifiedFields, '\[(?<name>[^\]]+)\]') |
        ForEach-Object { $_.Groups['name'].Value } | Where-Object { $allMeasures.ContainsKey($_) } | Sort-Object -Unique)
}
function Test-DependencyPath([string]$Name, [string[]]$Path) {
    if ($Path -contains $Name) { throw ('DAX measure dependency cycle: ' + (($Path + $Name) -join ' -> ')) }
    if (-not $edges.ContainsKey($Name)) { return }
    foreach ($next in $edges[$Name]) { Test-DependencyPath $next ($Path + $Name) }
}
foreach ($name in $edges.Keys) { Test-DependencyPath $name @() }

$scenarioRelations = @($model.Relationships | Where-Object {
    $_.FromTable.Name -like 'Scenario *' -or $_.ToTable.Name -like 'Scenario *'
})
if ($scenarioRelations.Count -ne 2) { throw 'Scenario tables must have exactly the project and report-update selector relationships.' }
foreach ($expected in @(
    @{FromColumn='ProjectKey';ToTable='Project_Dimension';ToColumn='ProjectKey'},
    @{FromColumn='Report Update Date';ToTable='CurrentDate';ToColumn='UpdateDate'}
)) {
    $matches = @($scenarioRelations | Where-Object {
        $_.FromTable.Name -eq 'Scenario Calendar' -and $_.FromColumn.Name -eq $expected.FromColumn -and
        $_.ToTable.Name -eq $expected.ToTable -and $_.ToColumn.Name -eq $expected.ToColumn
    })
    if ($matches.Count -ne 1 -or -not $matches[0].IsActive -or
        $matches[0].CrossFilteringBehavior.ToString() -ne 'OneDirection' -or
        $matches[0].SecurityFilteringBehavior.ToString() -ne 'OneDirection') {
        throw "Scenario Calendar direct $($expected.ToTable) filtering metadata is incorrect."
    }
}
if (($model.Tables.Find('Scenario Date').Columns.Name -join '|') -ne 'Date|Week|Month') {
    throw 'Scenario Date must remain one shared axis, without project, update or calendar identity.'
}

$queries = @()
foreach ($expression in $model.Expressions) {
    if ($expression.Kind.ToString() -eq 'M') { $queries += @{name=$expression.Name;expression=$expression.Expression} }
}
foreach ($table in $model.Tables) {
    foreach ($partition in $table.Partitions) {
        if ($partition.Source -is [Microsoft.AnalysisServices.Tabular.MPartitionSource]) {
            $queries += @{name=($table.Name + '/' + $partition.Name);expression=$partition.Source.Expression}
        }
    }
}
$mText = (@{queries=$queries} | ConvertTo-Json -Depth 6 -Compress) |
    & node (Join-Path $PSScriptRoot 'validation-runtime-m.cjs') $PowerQueryParserDirectory
if ($LASTEXITCODE -ne 0) { throw ('Microsoft M parser failed: ' + ($mText -join [Environment]::NewLine)) }
$mResult = ($mText -join [Environment]::NewLine) | ConvertFrom-Json

function Read-ReportValidation([string]$Path) {
    $text = (& node $ReportAuthoringCli validate $Path --pretty) -join [Environment]::NewLine
    $parsed = $text | ConvertFrom-Json
    if ($null -eq $parsed.data.diagnostics) { throw "Report validator returned unexpected output for $Path." }
    return $parsed.data
}
function Get-Diagnostics($Report) {
    $result = @{}
    foreach ($property in $Report.diagnostics.PSObject.Properties) {
        foreach ($item in $property.Value.items) {
            $relativeFile = ($item.file -split [regex]::Escape('Project Review - Programme (datalake).Report'))[-1]
            $key = @($property.Name,$property.Value.severity,$relativeFile,$item.path) -join '|'
            $result[$key] = @{code=$property.Name;severity=$property.Value.severity;file=$relativeFile;path=$item.path;message=$item.message}
        }
    }
    return $result
}
$reportResult = Read-ReportValidation $ReportRoot
$current = Get-Diagnostics $reportResult
$newDiagnostics = @($current.Values)
$baselineCounts = $null
if ($BaselineReportRoot) {
    $baselineResult = Read-ReportValidation (Resolve-Path -LiteralPath $BaselineReportRoot).Path
    $baseline = Get-Diagnostics $baselineResult
    $newDiagnostics = @($current.Keys | Where-Object { -not $baseline.ContainsKey($_) } | ForEach-Object { $current[$_] })
    $baselineCounts = @{errors=$baselineResult.errorCount;warnings=$baselineResult.warningCount}
}
$newErrors = @($newDiagnostics | Where-Object { $_.severity -eq 'error' })
$result = [ordered]@{
    result=if($newErrors.Count -eq 0){'PASS'}else{'FAIL'}
    tom=@{result='PASS';tables=$model.Tables.Count;relationships=$model.Relationships.Count;scenarioTables=$scenarioTables.Count;scenarioMeasures=$scenarioMeasures.Measures.Count;calculatedTables=$calculatedTableCount;calculatedPartitions=$calculatedPartitionCount}
    daxMetadata=@{result='PASS';expressionsChecked=$daxExpressions.Count;qualifiedReferences=$references;variableTableNameChecks=$variableChecks;knownRejectedVariableRegressionChecks=$true;acyclicScenarioMeasureGraph=$true;scope='Complete expression extraction plus field-name, known variable-name and dependency checks only. No DAX compilation or execution.'}
    mSyntax=$mResult
    report=@{errors=$reportResult.errorCount;warnings=$reportResult.warningCount;baseline=$baselineCounts;newDiagnostics=$newDiagnostics}
    engine=@{status='NOT_RUN';scope='No DAX compilation, execution, table processing or source refresh.'}
    host=@{status='NOT_RUN';scope='No Desktop/Service interaction, rendering, performance or runtime RLS.'}
}
$json = $result | ConvertTo-Json -Depth 12
if ($OutputPath) { $json | Set-Content -LiteralPath $OutputPath -Encoding utf8 }
$json
if ($newErrors.Count -gt 0) { exit 1 }
