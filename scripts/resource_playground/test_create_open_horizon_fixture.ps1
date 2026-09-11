param([Parameter(Mandatory=$true)][int]$Port)
# Only a new, marked 20-table literal-data fixture can be created by this script.
$ErrorActionPreference='Stop'
if($Port -ne 65096){throw 'Fixture creation is pinned to the authorised endpoint.'}
$protectedId='3848c689-7848-44b6-8dfe-8b8c1f7f8fa8'
$marker='resource-playground-open-horizon-20260911'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$artifacts=Join-Path (Split-Path $repo -Parent) 'resource_playground_review\open_horizon_20260911'
$fixtureRoot=Join-Path $artifacts 'ResourcePlaygroundOpenHorizonFixture'
$definition=Join-Path $fixtureRoot 'ResourcePlaygroundOpenHorizonFixture.SemanticModel\definition'
$manifest=Get-Content -LiteralPath (Join-Path $fixtureRoot 'fixture-marker.json') -Raw|ConvertFrom-Json
if($manifest.marker -ne $marker -or $manifest.tables.Count -ne 20 -or $manifest.literalTables.Count -ne 5){throw 'Invalid fixture manifest.'}
$tom=Join-Path $env:USERPROFILE '.nuget\packages\microsoft.analysisservices\19.114.8\lib\net8.0'
foreach($dll in @('Microsoft.AnalysisServices.Core.dll','Microsoft.AnalysisServices.Tabular.dll','Microsoft.AnalysisServices.Tabular.Json.dll')){[Reflection.Assembly]::LoadFrom((Join-Path $tom $dll))|Out-Null}
$model=[Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeModelFromFolder($definition)
if($model.Annotations.Find('ResourcePlaygroundFixture').Value -ne $marker -or $model.Tables.Count -ne 20 -or $model.DataSources.Count -ne 0 -or @(Compare-Object @($manifest.tables|Sort-Object) @($model.Tables|ForEach-Object Name|Sort-Object)).Count){throw 'Model inventory guard failed.'}
foreach($name in $manifest.literalTables){$table=$model.Tables.Find($name);if($table.Partitions.Count -ne 1 -or $table.Partitions[0].Source -isnot [Microsoft.AnalysisServices.Tabular.CalculatedPartitionSource] -or $table.Partitions[0].Source.Expression.Trim() -notmatch '^(ROW|UNION)\('){throw ('Literal table guard failed: '+$name)}}
if($model.Tables.Find('CurrentDate').Partitions[0].Source.Expression.Trim() -cne "DISTINCT('01 XER_TASK'[UpdateDate])"){throw 'CurrentDate exact production-expression guard failed.'}
$measures=$model.Tables.Find('Resource Scenario Measures');$measures.Partitions.Clear()
$carrier=[Microsoft.AnalysisServices.Tabular.CalculatedTableColumn]::new();$carrier.Name='__FixtureCarrier';$carrier.DataType=[Microsoft.AnalysisServices.Tabular.DataType]::Int64;$carrier.SourceColumn='[__FixtureCarrier]';$carrier.IsHidden=$true;$measures.Columns.Add($carrier)
$partition=[Microsoft.AnalysisServices.Tabular.Partition]::new();$partition.Name='Fixture carrier';$partition.Mode=[Microsoft.AnalysisServices.Tabular.ModeType]::Import;$partition.Source=[Microsoft.AnalysisServices.Tabular.CalculatedPartitionSource]::new();$partition.Source.Expression='ROW("__FixtureCarrier",1)';$measures.Partitions.Add($partition)
foreach($table in $model.Tables){if($table.Partitions.Count -ne 1 -or $table.Partitions[0].Source -isnot [Microsoft.AnalysisServices.Tabular.CalculatedPartitionSource]){throw 'No external or mashup partition is allowed in this fixture.'}}
$fixtureId='ResourcePlaygroundOpenHorizonFixture_20260911_'+[Guid]::NewGuid().ToString('N')
$server=[Microsoft.AnalysisServices.Tabular.Server]::new();$created=$false;$phase='connect'
try{
    $server.Connect("localhost:$Port")
    if($null -eq $server.Databases.Find($protectedId) -or $server.Databases.Find($fixtureId) -or @($server.Databases|Where-Object {$_.Model.Annotations.Find('ResourcePlaygroundFixture').Value -eq $marker}).Count){throw 'Endpoint fixture/protected-database guard failed.'}
    $fixture=[Microsoft.AnalysisServices.Tabular.Database]::new();$fixture.ID=$fixtureId;$fixture.Name=$fixtureId;$fixture.CompatibilityLevel=1606;$fixture.Model=$model;$server.Databases.Add($fixture)
    $phase='create';$fixture.Update([Microsoft.AnalysisServices.UpdateOptions]::ExpandFull);$created=$true
    $phase='process';$fixture.Model.RequestRefresh([Microsoft.AnalysisServices.Tabular.RefreshType]::Full);$fixture.Model.SaveChanges()|Out-Null
    $phase='readiness';$fixture.Refresh()
    $badPartitions=@($fixture.Model.Tables|ForEach-Object {$table=$_; $_.Partitions|Where-Object State -ne 'Ready'|ForEach-Object {$table.Name+': '+$_.State+' '+$_.ErrorMessage}})
    if($badPartitions.Count){throw ($badPartitions -join '; ')}
    $result=[ordered]@{result='PASS';marker=$marker;port=$Port;fixtureDatabase=$fixtureId;protectedDatabase=$protectedId;tables=$model.Tables.Count;measures=$measures.Measures.Count;created=$created;scope='Only the new 20-table source-free fixture was created and processed.'}
}catch{$result=[ordered]@{result='ERROR';marker=$marker;port=$Port;fixtureDatabase=$fixtureId;protectedDatabase=$protectedId;created=$created;phase=$phase;error=$_.Exception.Message}}
finally{$result|ConvertTo-Json -Depth 8|Set-Content -LiteralPath (Join-Path $artifacts 'fixture_database.json') -Encoding utf8;$result|ConvertTo-Json -Depth 8;$server.Disconnect()}
if($result.result -ne 'PASS'){exit 1}
