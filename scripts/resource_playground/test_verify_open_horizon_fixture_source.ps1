param([Parameter(Mandatory=$true)][int]$Port,[Parameter(Mandatory=$true)][string]$FixtureDatabaseId,[string]$OutputPath)
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$sourcePath=Join-Path $repo 'Project Review - Programme (datalake).SemanticModel\definition'
if(-not $OutputPath){$OutputPath=Join-Path (Split-Path $repo -Parent) 'resource_playground_review\open_horizon_20260911\fixture_source_equivalence.json'}
$tom=Join-Path $env:USERPROFILE '.nuget\packages\microsoft.analysisservices\19.114.8\lib\net8.0'
foreach($dll in @('Microsoft.AnalysisServices.Core.dll','Microsoft.AnalysisServices.Tabular.dll','Microsoft.AnalysisServices.Tabular.Json.dll')){[Reflection.Assembly]::LoadFrom((Join-Path $tom $dll))|Out-Null}
$source=[Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeModelFromFolder($sourcePath)
$server=[Microsoft.AnalysisServices.Tabular.Server]::new()
function Normalise([string]$Expression){return $Expression.Replace("`r`n","`n").Trim()}
try{
    $server.Connect("localhost:$Port")
    $fixture=$server.Databases.Find($FixtureDatabaseId)
    if($null -eq $fixture -or $fixture.ID -notmatch '^ResourcePlaygroundOpenHorizonFixture_20260911_[a-f0-9]{32}$' -or $fixture.Model.Annotations.Find('ResourcePlaygroundFixture').Value -ne 'resource-playground-open-horizon-20260911'){throw 'Fixture marker guard failed.'}
    $checks=@()
    foreach($table in $source.Tables){
        if($table.Name -notlike 'Scenario *' -and $table.Name -ne 'Resource Scenario Measures'){continue}
        $target=$fixture.Model.Tables.Find($table.Name)
        if($null -eq $target){throw 'Fixture table missing.'}
        if($table.Name -like 'Scenario *'){
            $checks += [PSCustomObject]@{object=$table.Name;kind='calculated table expression';pass=(Normalise $table.Partitions[0].Source.Expression) -ceq (Normalise $target.Partitions[0].Source.Expression)}
        }
        foreach($measure in $table.Measures){
            $actual=$target.Measures.Find($measure.Name)
            $checks += [PSCustomObject]@{object=$measure.Name;kind='measure expression';pass=$null -ne $actual -and (Normalise $measure.Expression) -ceq (Normalise $actual.Expression)}
        }
    }
    $checks += [PSCustomObject]@{object='CurrentDate';kind='production calculated table';pass=(Normalise $source.Tables.Find('CurrentDate').Partitions[0].Source.Expression) -ceq (Normalise $fixture.Model.Tables.Find('CurrentDate').Partitions[0].Source.Expression)}
    $failures=@($checks|Where-Object {-not $_.pass})
    $result=[PSCustomObject]@{result=if($failures.Count){'FAIL'}else{'PASS'};fixtureDatabase=$FixtureDatabaseId;port=$Port;checks=$checks;checked=$checks.Count;sourceMeasureSha256=(Get-FileHash -LiteralPath (Join-Path $sourcePath 'tables\Resource Scenario Measures.tmdl') -Algorithm SHA256).Hash;scope='Read-only comparison of current source DAX with the exact fixture expressions executed by tests.'}
    $result|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $OutputPath -Encoding utf8
    [PSCustomObject]@{result=$result.result;checks=$checks.Count;failures=$failures;output=$OutputPath}|ConvertTo-Json -Depth 6
    if($failures.Count){exit 1}
}finally{$server.Disconnect()}
