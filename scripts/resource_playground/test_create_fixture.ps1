param(
    [Parameter(Mandatory=$true)][int]$Port,
    [Parameter(Mandatory=$true)][string]$ProtectedDatabaseId,
    [string]$FixtureDefinition,
    [string]$OutputPath
)

# Explicit isolated-test operation. Adds a uniquely named fixture database only;
# never removes a database, changes a pre-existing model, or saves production.
$ErrorActionPreference = 'Stop'
if ($Port -ne 65096 -or $ProtectedDatabaseId -ne '3848c689-7848-44b6-8dfe-8b8c1f7f8fa8') {
    throw 'This bootstrap is authorised only for the explicitly identified test endpoint.'
}
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$artifacts = Join-Path (Split-Path $repoRoot -Parent) 'resource_playground_review\repair_20260911'
if (-not $FixtureDefinition) { $FixtureDefinition = Join-Path $artifacts 'ResourcePlaygroundFixture\ResourcePlaygroundFixture.SemanticModel\definition' }
if (-not $OutputPath) { $OutputPath = Join-Path $artifacts 'fixture_database.json' }
$fixtureMarker = 'resource-playground-repair-20260911'
$tomRoot = Join-Path $env:USERPROFILE '.nuget\packages\microsoft.analysisservices\19.114.8\lib\net8.0'
foreach ($dll in @('Microsoft.AnalysisServices.Core.dll','Microsoft.AnalysisServices.Tabular.dll','Microsoft.AnalysisServices.Tabular.Json.dll')) {
    [Reflection.Assembly]::LoadFrom((Join-Path $tomRoot $dll)) | Out-Null
}
$model = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeModelFromFolder((Resolve-Path -LiteralPath $FixtureDefinition).Path)
if ($model.Annotations.Find('ResourcePlaygroundFixture').Value -ne $fixtureMarker -or $model.Tables.Count -ne 17) { throw 'Invalid fixture definition.' }
if ($model.Tables.Find('01 XER_TASK')) { throw 'Production table detected in fixture.' }
# The empty measure-table carrier has no semantic role. Replacing its empty M
# partition avoids any external or Desktop-only mashup processing dependencies.
$measures = $model.Tables.Find('Resource Scenario Measures')
$measures.Partitions.Clear()
$carrier = [Microsoft.AnalysisServices.Tabular.CalculatedTableColumn]::new()
$carrier.Name = '__FixtureCarrier'
$carrier.DataType = [Microsoft.AnalysisServices.Tabular.DataType]::Int64
$carrier.SourceColumn = '[__FixtureCarrier]'
$carrier.IsHidden = $true
$measures.Columns.Add($carrier)
$partition = [Microsoft.AnalysisServices.Tabular.Partition]::new()
$partition.Name = 'Fixture carrier'
$partition.Mode = [Microsoft.AnalysisServices.Tabular.ModeType]::Import
$partition.Source = [Microsoft.AnalysisServices.Tabular.CalculatedPartitionSource]::new()
$partition.Source.Expression = 'ROW("__FixtureCarrier", 1)'
$measures.Partitions.Add($partition)
$server = [Microsoft.AnalysisServices.Tabular.Server]::new()
$created = $false
$fixtureId = 'ResourcePlaygroundFixture_20260911_' + [Guid]::NewGuid().ToString('N')
$phase = 'connect'
try {
    $server.Connect("localhost:$Port")
    $protected = $server.Databases.Find($ProtectedDatabaseId)
    if ($null -eq $protected) { throw 'Expected protected database is absent; refusing endpoint mutation.' }
    if ($server.Databases.Find($fixtureId)) { throw 'Unique fixture ID unexpectedly already exists.' }
    $fixture = [Microsoft.AnalysisServices.Tabular.Database]::new()
    $fixture.ID = $fixtureId
    $fixture.Name = $fixtureId
    $fixture.CompatibilityLevel = 1606
    $fixture.Model = $model
    $server.Databases.Add($fixture)
    $phase = 'create-fixture-only'
    $fixture.Update([Microsoft.AnalysisServices.UpdateOptions]::ExpandFull)
    $created = $true
    if ($fixture.ID -eq $ProtectedDatabaseId -or $fixture.Model.Annotations.Find('ResourcePlaygroundFixture').Value -ne $fixtureMarker) { throw 'Fixture identity safety guard failed.' }
    $phase = 'process-fixture-only'
    $fixture.Model.RequestRefresh([Microsoft.AnalysisServices.Tabular.RefreshType]::Full)
    $fixture.Model.SaveChanges()
    $phase = 'complete'
    $result = [ordered]@{result='PASS';marker=$fixtureMarker;port=$Port;fixtureDatabase=$fixtureId;protectedDatabase=$ProtectedDatabaseId;created=$created;phase=$phase;tables=$fixture.Model.Tables.Count;measureCarrier='One hidden literal calculated column; production measure expressions unchanged.'}
} catch {
    $result = [ordered]@{result='ERROR';marker=$fixtureMarker;port=$Port;fixtureDatabase=$fixtureId;protectedDatabase=$ProtectedDatabaseId;created=$created;phase=$phase;error=$_.Exception.Message}
} finally {
    $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputPath -Encoding utf8
    $result | ConvertTo-Json -Depth 8
    $server.Disconnect()
}
if ($result.result -ne 'PASS') { exit 1 }
