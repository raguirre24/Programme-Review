param([Parameter(Mandatory=$true)][int]$Port,[switch]$RawPeriodOnly)
# Only expression updates in the exact marked source-free test model are allowed.
$ErrorActionPreference='Stop'
if($Port -ne 65096){throw 'Endpoint is pinned.'}
$marker='resource-playground-open-horizon-20260911'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$artifacts=Join-Path (Split-Path $repo -Parent) 'resource_playground_review\open_horizon_20260911'
$info=Get-Content -LiteralPath (Join-Path $artifacts 'fixture_database.json') -Raw|ConvertFrom-Json
$manifest=Get-Content -LiteralPath (Join-Path $artifacts 'ResourcePlaygroundOpenHorizonFixture\fixture-marker.json') -Raw|ConvertFrom-Json
if($info.marker -ne $marker -or $info.fixtureDatabase -notmatch '^ResourcePlaygroundOpenHorizonFixture_20260911_[a-f0-9]{32}$' -or $manifest.marker -ne $marker -or $manifest.tables.Count -ne 20 -or $manifest.literalTables.Count -ne 5){throw 'Manifest guard failed.'}
$tom=Join-Path $env:USERPROFILE '.nuget\packages\microsoft.analysisservices\19.114.8\lib\net8.0'
foreach($dll in @('Microsoft.AnalysisServices.Core.dll','Microsoft.AnalysisServices.Tabular.dll','Microsoft.AnalysisServices.Tabular.Json.dll')){[Reflection.Assembly]::LoadFrom((Join-Path $tom $dll))|Out-Null}
$source=[Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeModelFromFolder((Join-Path $repo 'Project Review - Programme (datalake).SemanticModel\definition'))
$server=[Microsoft.AnalysisServices.Tabular.Server]::new()
try{
    $server.Connect("localhost:$Port")
    $fixture=$server.Databases.Find($info.fixtureDatabase)
    if($null -eq $fixture -or $fixture.Model.Annotations.Find('ResourcePlaygroundFixture').Value -ne $marker -or $fixture.Model.Tables.Count -ne 20 -or $fixture.Model.DataSources.Count -ne 0 -or $null -eq $server.Databases.Find('3848c689-7848-44b6-8dfe-8b8c1f7f8fa8')){throw 'Database guard failed.'}
    if(@(Compare-Object @($manifest.tables|Sort-Object) @($fixture.Model.Tables|ForEach-Object Name|Sort-Object)).Count){throw 'Inventory guard failed.'}
    foreach($name in $manifest.literalTables){$t=$fixture.Model.Tables.Find($name);if($t.Partitions.Count -ne 1 -or $t.Partitions[0].Source -isnot [Microsoft.AnalysisServices.Tabular.CalculatedPartitionSource] -or $t.Partitions[0].Source.Expression.Trim() -notmatch '^(ROW|UNION)\('){throw 'Literal partition guard failed.'}}
    if($fixture.Model.Tables.Find('CurrentDate').Partitions[0].Source.Expression.Trim() -cne "DISTINCT('01 XER_TASK'[UpdateDate])"){throw 'CurrentDate production expression guard failed.'}
    $copied=0
    foreach($table in $source.Tables){
        if($table.Name -notlike 'Scenario *' -and $table.Name -ne 'Resource Scenario Measures'){continue}
        if($RawPeriodOnly -and $table.Name -ne 'Resource Scenario Measures'){continue}
        $target=$fixture.Model.Tables.Find($table.Name)
        if($null -eq $target){throw 'Missing scenario table.'}
        foreach($measure in $table.Measures){if($RawPeriodOnly -and $measure.Name -ne 'Scenario Period Quantity'){continue};$destination=$target.Measures.Find($measure.Name);if($null -eq $destination){throw 'Measure inventory change requires explicit fixture rebuild.'};$destination.Expression=$measure.Expression;$destination.FormatString=$measure.FormatString}
        if($table.Name -like 'Scenario *'){$target.Partitions[0].Source.Expression=$table.Partitions[0].Source.Expression}
        $copied++
    }
    if($copied -ne $(if($RawPeriodOnly){1}else{14})){throw 'Scenario inventory guard failed.'}
    $fixture.Model.RequestRefresh($(if($RawPeriodOnly){[Microsoft.AnalysisServices.Tabular.RefreshType]::Calculate}else{[Microsoft.AnalysisServices.Tabular.RefreshType]::Full}));$fixture.Model.SaveChanges()|Out-Null;$fixture.Refresh()
    $states=@($fixture.Model.Tables|ForEach-Object {$t=$_;$_.Partitions|ForEach-Object {[PSCustomObject]@{table=$t.Name;state=$_.State.ToString();error=$_.ErrorMessage}}})
    $errors=@($states|Where-Object state -ne 'Ready')
    $result=[ordered]@{result=if($errors.Count){'ERROR'}else{'PASS'};fixtureDatabase=$fixture.ID;marker=$marker;tables=20;measures=$fixture.Model.Tables.Find('Resource Scenario Measures').Measures.Count;partitionStates=$states}
    $result|ConvertTo-Json -Depth 8|Set-Content -LiteralPath (Join-Path $artifacts 'fixture_sync.json') -Encoding utf8
    $result|ConvertTo-Json -Depth 8
    if($errors.Count){exit 1}
}finally{$server.Disconnect()}
