param([Parameter(Mandatory=$true)][int]$Port)
# Read only: no model data is selected; query the engine's clock for test dates.
$ErrorActionPreference='Stop'
if($Port -ne 65096){throw 'This clock probe is pinned to the authorised local endpoint.'}
$catalog='3848c689-7848-44b6-8dfe-8b8c1f7f8fa8'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$artifacts=Join-Path (Split-Path $repo -Parent) 'resource_playground_review\refinement_20260911\window_revision'
$tom=Join-Path $env:USERPROFILE '.nuget\packages\microsoft.analysisservices\19.114.8\lib\net8.0'
foreach($dll in @('Microsoft.AnalysisServices.Core.dll','Microsoft.AnalysisServices.Tabular.dll')){[Reflection.Assembly]::LoadFrom((Join-Path $tom $dll))|Out-Null}
$server=[Microsoft.AnalysisServices.Tabular.Server]::new()
try{
    $server.Connect("localhost:$Port")
    if($null -eq $server.Databases.Find($catalog)){throw 'Expected protected database is absent.'}
    $statement='<Statement>EVALUATE ROW("Today",TODAY(),"WindowEnd",EDATE(TODAY(),12))</Statement>'
    $messages=$null
    $reader=$server.ExecuteReader($statement,[ref]$messages,@{Catalog=$catalog;Format='Tabular';Timeout='10';DbpropMsmdRequestMemoryLimit='1048576'},$true)
    try{
        if(-not $reader.Read()){throw 'Clock query returned no row.'}
        $values=@()
        for($i=0;$i -lt 2;$i++){
            $value=$reader.GetValue($i)
            $date=if($value -is [DateTime]){$value}else{[DateTime]::FromOADate([double]$value)}
            $values += $date.ToString('yyyy-MM-dd')
        }
        $result=[PSCustomObject]@{today=$values[0];windowEnd=$values[1];port=$Port;catalog=$catalog;scope='Read-only engine clock; no model rows copied.'}
        $result|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $artifacts 'engine_clock.json') -Encoding utf8
        $result|ConvertTo-Json
    }finally{$reader.Close()}
}finally{$server.Disconnect()}
