param(
    [Parameter(Mandatory=$true)][int]$Port,
    [Parameter(Mandatory=$true)][string]$FixtureDatabaseId,
    [string]$SourceDefinition,
    [string]$OutputPath
)

# Synchronises only a previously created marked fixture. Production tables,
# calendars, permissions and the protected Desktop database are never changed.
$ErrorActionPreference = 'Stop'
$marker = 'resource-playground-repair-20260911'
if ($FixtureDatabaseId -notmatch '^ResourcePlaygroundFixture_20260911_[a-f0-9]{32}$') { throw 'A fixture ID is required.' }
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if (-not $SourceDefinition) { $SourceDefinition = Join-Path $repo 'Project Review - Programme (datalake).SemanticModel\definition' }
if (-not $OutputPath) { $OutputPath = Join-Path (Split-Path $repo -Parent) 'resource_playground_review\repair_20260911\fixture_sync.json' }
$tom = Join-Path $env:USERPROFILE '.nuget\packages\microsoft.analysisservices\19.114.8\lib\net8.0'
foreach ($dll in @('Microsoft.AnalysisServices.Core.dll','Microsoft.AnalysisServices.Tabular.dll','Microsoft.AnalysisServices.Tabular.Json.dll')) { [Reflection.Assembly]::LoadFrom((Join-Path $tom $dll)) | Out-Null }
$source = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeModelFromFolder((Resolve-Path -LiteralPath $SourceDefinition).Path)
$server = [Microsoft.AnalysisServices.Tabular.Server]::new()
try {
    $server.Connect("localhost:$Port")
    $fixture = $server.Databases.Find($FixtureDatabaseId)
    if ($null -eq $fixture -or $fixture.Model.Annotations.Find('ResourcePlaygroundFixture').Value -ne $marker -or $fixture.Model.Tables.Count -ne 17 -or $fixture.Model.Tables.Find('01 XER_TASK')) { throw 'Fixture identity guard failed.' }
    $copied = @()
    foreach ($table in $source.Tables) {
        if ($table.Name -notlike 'Scenario *' -and $table.Name -ne 'Resource Scenario Measures') { continue }
        $target = $fixture.Model.Tables.Find($table.Name)
        if ($null -eq $target) { throw ('Missing fixture scenario table: ' + $table.Name) }
        foreach ($measure in $table.Measures) {
            $destination = $target.Measures.Find($measure.Name)
            if ($null -eq $destination) { $destination = [Microsoft.AnalysisServices.Tabular.Measure]::new(); $destination.Name=$measure.Name; $target.Measures.Add($destination) }
            $destination.Expression = $measure.Expression
            $destination.FormatString = $measure.FormatString
            $destination.IsHidden = $measure.IsHidden
        }
        if ($table.Name -like 'Scenario *') {
            if ($table.Partitions.Count -ne 1 -or $table.Partitions[0].Source -isnot [Microsoft.AnalysisServices.Tabular.CalculatedPartitionSource]) { throw 'Unexpected scenario partition type.' }
            $target.Partitions[0].Source.Expression = $table.Partitions[0].Source.Expression
        }
        $copied += [PSCustomObject]@{table=$table.Name;measures=$table.Measures.Count}
    }
    if ($copied.Count -ne 14) { throw 'Unexpected number of scenario source tables.' }
    $fixture.Model.RequestRefresh([Microsoft.AnalysisServices.Tabular.RefreshType]::Calculate)
    $fixture.Model.SaveChanges() | Out-Null
    $measureHash = (Get-FileHash -LiteralPath (Join-Path $SourceDefinition 'tables\Resource Scenario Measures.tmdl') -Algorithm SHA256).Hash
    $result = [PSCustomObject]@{result='PASS';marker=$marker;fixtureDatabase=$FixtureDatabaseId;port=$Port;scenarioTables=$copied;measureCount=$fixture.Model.Tables.Find('Resource Scenario Measures').Measures.Count;sourceMeasureSha256=$measureHash;scope='Only scenario expressions in the marked synthetic fixture were updated.'}
    $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputPath -Encoding utf8
    $result | ConvertTo-Json -Depth 8
} finally { $server.Disconnect() }
