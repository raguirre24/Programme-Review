param(
    [Parameter(Mandatory=$true)][int]$Port,
    [Parameter(Mandatory=$true)][string]$ProtectedDatabase,
    [Parameter(Mandatory=$true)][string]$DefinitionPath,
    [Parameter(Mandatory=$true)][string]$ManifestPath,
    [Parameter(Mandatory=$true)][string]$OutputPath
)

# Creates only a new marked, source-free test database on an explicit local
# Desktop endpoint. The production catalog is checked and never modified.
$ErrorActionPreference = 'Stop'
$marker = 'resource-playground-comparison-20261017'
if ($Port -lt 1 -or $Port -gt 65535) { throw 'An explicit localhost port is required.' }
$manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
if ($manifest.marker -ne $marker -or $manifest.tables.Count -ne 21 -or $manifest.literalTables.Count -ne 5) { throw 'Unexpected fixture manifest.' }
$package = Get-ChildItem -LiteralPath (Join-Path $env:USERPROFILE '.nuget/packages/microsoft.analysisservices') -Directory |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'lib/net8.0/Microsoft.AnalysisServices.Tabular.dll') } |
    Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
foreach ($dll in @('Microsoft.AnalysisServices.Core.dll','Microsoft.AnalysisServices.Tabular.dll','Microsoft.AnalysisServices.Tabular.Json.dll')) {
    [Reflection.Assembly]::LoadFrom((Join-Path $package.FullName ('lib/net8.0/' + $dll))) | Out-Null
}
$model = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeModelFromFolder((Resolve-Path -LiteralPath $DefinitionPath).Path)
if ($model.Annotations.Find('ResourcePlaygroundFixture').Value -ne $marker -or $model.Tables.Count -ne 21 -or $model.DataSources.Count -ne 0) { throw 'Source-free model inventory guard failed.' }
if (@(Compare-Object @($manifest.tables | Sort-Object) @($model.Tables | ForEach-Object Name | Sort-Object)).Count) { throw 'Exact table inventory mismatch.' }
foreach ($name in $manifest.literalTables) {
    $table = $model.Tables.Find($name)
    if ($table.Partitions.Count -ne 1 -or $table.Partitions[0].Source -isnot [Microsoft.AnalysisServices.Tabular.CalculatedPartitionSource] -or $table.Partitions[0].Source.Expression.Trim() -notmatch '^(ROW|UNION)\(') { throw ('Literal-only table guard failed: ' + $name) }
}
$measures = $model.Tables.Find('Resource Scenario Measures')
if ($measures.Measures.Count -ne 56) { throw 'Expected the 48 base measures and eight comparison measures.' }
# The production empty M carrier has no data; a literal carrier makes the
# isolated fixture entirely source-free without changing any DAX expression.
$measures.Partitions.Clear()
$carrier = [Microsoft.AnalysisServices.Tabular.CalculatedTableColumn]::new()
$carrier.Name='__FixtureCarrier'; $carrier.DataType=[Microsoft.AnalysisServices.Tabular.DataType]::Int64
$carrier.SourceColumn='[__FixtureCarrier]'; $carrier.IsHidden=$true; $measures.Columns.Add($carrier)
$partition = [Microsoft.AnalysisServices.Tabular.Partition]::new()
$partition.Name='Fixture carrier'; $partition.Mode=[Microsoft.AnalysisServices.Tabular.ModeType]::Import
$partition.Source=[Microsoft.AnalysisServices.Tabular.CalculatedPartitionSource]::new()
$partition.Source.Expression='ROW("__FixtureCarrier",1)'; $measures.Partitions.Add($partition)
foreach ($table in $model.Tables) {
    if ($table.Partitions.Count -ne 1 -or $table.Partitions[0].Source -isnot [Microsoft.AnalysisServices.Tabular.CalculatedPartitionSource]) { throw 'External/mashup fixture partitions are forbidden.' }
}
$fixtureId = 'ResourcePlaygroundComparisonFixture_20261017_' + [Guid]::NewGuid().ToString('N')
$server = [Microsoft.AnalysisServices.Tabular.Server]::new()
$created=$false; $phase='connect'; $result=$null
try {
    $server.Connect("localhost:$Port")
    if (-not $server.Databases.Find($ProtectedDatabase) -or $ProtectedDatabase -eq $fixtureId -or $server.Databases.Find($fixtureId)) { throw 'Protected catalog/new identity guard failed.' }
    if (@($server.Databases | Where-Object { $_.Model.Annotations.Find('ResourcePlaygroundFixture').Value -eq $marker }).Count) { throw 'A marked fixture already exists; inspect it before creating another.' }
    $fixture=[Microsoft.AnalysisServices.Tabular.Database]::new()
    $fixture.ID=$fixtureId; $fixture.Name=$fixtureId; $fixture.CompatibilityLevel=1606; $fixture.Model=$model
    $server.Databases.Add($fixture)
    $phase='create'; $fixture.Update([Microsoft.AnalysisServices.UpdateOptions]::ExpandFull); $created=$true
    $phase='process'; $fixture.Model.RequestRefresh([Microsoft.AnalysisServices.Tabular.RefreshType]::Full); $fixture.Model.SaveChanges() | Out-Null
    $phase='readiness'; $fixture.Refresh()
    $errors=@($fixture.Model.Tables | ForEach-Object { $table=$_; $_.Partitions | Where-Object State -ne 'Ready' | ForEach-Object { $table.Name + ': ' + $_.State + ' ' + $_.ErrorMessage } })
    if ($errors.Count) { throw ($errors -join '; ') }
    $result=[ordered]@{result='PASS';marker=$marker;port=$Port;fixtureDatabase=$fixtureId;protectedDatabase=$ProtectedDatabase;created=$created;tables=$model.Tables.Count;measures=$measures.Measures.Count}
} catch {
    $result=[ordered]@{result='ERROR';marker=$marker;port=$Port;fixtureDatabase=$fixtureId;protectedDatabase=$ProtectedDatabase;created=$created;phase=$phase;error=$_.Exception.Message}
} finally {
    $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $OutputPath -Encoding utf8
    $result | ConvertTo-Json -Depth 6
    $server.Disconnect()
}
if ($result.result -ne 'PASS') { exit 1 }
