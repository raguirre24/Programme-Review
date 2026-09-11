param([Parameter(Mandatory=$true)][int]$Port)
# Pinned read-only endpoint check: clock, existing date-axis extent and readiness.
$ErrorActionPreference='Stop'
if($Port -ne 65096){throw 'Endpoint is pinned to the authorised local Desktop engine.'}
$catalog='3848c689-7848-44b6-8dfe-8b8c1f7f8fa8'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$artifacts=Join-Path (Split-Path $repo -Parent) 'resource_playground_review\open_horizon_20260911'
[IO.Directory]::CreateDirectory($artifacts)|Out-Null
$tom=Join-Path $env:USERPROFILE '.nuget\packages\microsoft.analysisservices\19.114.8\lib\net8.0'
foreach($dll in @('Microsoft.AnalysisServices.Core.dll','Microsoft.AnalysisServices.Tabular.dll')){[Reflection.Assembly]::LoadFrom((Join-Path $tom $dll))|Out-Null}
$server=[Microsoft.AnalysisServices.Tabular.Server]::new()
try{
    $server.Connect("localhost:$Port")
    $database=$server.Databases.Find($catalog)
    if($null -eq $database){throw 'Protected database is absent.'}
    $states=@($database.Model.Tables|ForEach-Object {$table=$_;$_.Partitions|ForEach-Object {[PSCustomObject]@{table=$table.Name;partition=$_.Name;state=$_.State.ToString();error=$_.ErrorMessage}}})
    $notReady=@($states|Where-Object state -ne 'Ready')
    $reader=$null;$messages=$null
    $dax='EVALUATE ROW("Today",TODAY(),"AxisStart",CALCULATE(MIN(''Scenario Date''[Date]),REMOVEFILTERS(''Scenario Date'')),"AxisEnd",CALCULATE(MAX(''Scenario Date''[Date]),REMOVEFILTERS(''Scenario Date'')),"AxisRows",COUNTROWS(ALL(''Scenario Date'')))'
    $reader=$server.ExecuteReader('<Statement>'+[Security.SecurityElement]::Escape($dax)+'</Statement>',[ref]$messages,@{Catalog=$catalog;Format='Tabular';Timeout='10';DbpropMsmdRequestMemoryLimit='1048576'},$true)
    try{
        if(-not $reader.Read()){throw 'Endpoint extent query returned no row.'}
        $dates=@();for($i=0;$i -lt 3;$i++){$value=$reader.GetValue($i);$date=if($value -is [DateTime]){$value}else{[DateTime]::FromOADate([double]$value)};$dates+=$date.ToString('yyyy-MM-dd')}
        $result=[ordered]@{result=if($notReady.Count){'ERROR'}else{'PASS'};today=$dates[0];axisStart=$dates[1];windowEnd=$dates[2];axisRows=$reader.GetValue(3);port=$Port;catalog=$catalog;tables=$database.Model.Tables.Count;scenarioMeasures=$database.Model.Tables.Find('Resource Scenario Measures').Measures.Count;partitions=$states;scope='Read-only production readiness and existing date-axis extent; no business rows copied.'}
        $result|ConvertTo-Json -Depth 8|Set-Content -LiteralPath (Join-Path $artifacts 'engine_clock.json') -Encoding utf8
        [PSCustomObject]@{result=$result.result;today=$result.today;axisStart=$result.axisStart;axisEnd=$result.windowEnd;axisRows=$result.axisRows;partitions=$states.Count;notReady=$notReady.Count;measures=$result.scenarioMeasures}|ConvertTo-Json
        if($notReady.Count){exit 1}
    }finally{if($reader){$reader.Close()}}
}finally{$server.Disconnect()}
