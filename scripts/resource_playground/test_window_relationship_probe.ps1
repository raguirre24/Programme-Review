param([Parameter(Mandatory=$true)][int]$Port)
$ErrorActionPreference='Stop'
if($Port -ne 65096){throw 'Probe endpoint is pinned.'}
$protectedId='3848c689-7848-44b6-8dfe-8b8c1f7f8fa8'
$marker='resource-playground-window-relationship-probe'
$probeId='ResourcePlaygroundWindowRelationshipProbe_'+[Guid]::NewGuid().ToString('N')
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$artifacts=Join-Path (Split-Path $repo -Parent) 'resource_playground_review\refinement_20260911\window_revision'
$tom=Join-Path $env:USERPROFILE '.nuget\packages\microsoft.analysisservices\19.114.8\lib\net8.0'
foreach($dll in @('Microsoft.AnalysisServices.Core.dll','Microsoft.AnalysisServices.Tabular.dll')){[Reflection.Assembly]::LoadFrom((Join-Path $tom $dll))|Out-Null}
$model=[Microsoft.AnalysisServices.Tabular.Model]::new()
$model.Culture='en-NZ'
$annotation=[Microsoft.AnalysisServices.Tabular.Annotation]::new();$annotation.Name='ResourcePlaygroundRelationshipProbe';$annotation.Value=$marker;$model.Annotations.Add($annotation)
function Add-LiteralTable($Name,$Columns,$Expression){
    $table=[Microsoft.AnalysisServices.Tabular.Table]::new();$table.Name=$Name
    foreach($name in $Columns.Keys){$column=[Microsoft.AnalysisServices.Tabular.CalculatedTableColumn]::new();$column.Name=$name;$column.SourceColumn='['+$name+']';$column.DataType=[Microsoft.AnalysisServices.Tabular.DataType]::$($Columns[$name]);$table.Columns.Add($column)}
    $partition=[Microsoft.AnalysisServices.Tabular.Partition]::new();$partition.Name='Literal fixture';$partition.Mode=[Microsoft.AnalysisServices.Tabular.ModeType]::Import;$partition.Source=[Microsoft.AnalysisServices.Tabular.CalculatedPartitionSource]::new();$partition.Source.Expression=$Expression;$table.Partitions.Add($partition);$model.Tables.Add($table)
}
Add-LiteralTable 'Project_Dimension' ([ordered]@{ProjectKey='String'}) 'UNION(ROW("ProjectKey","P1"),ROW("ProjectKey","P2"))'
Add-LiteralTable '03 XER_WBS' ([ordered]@{WBSKey='String';ProjectKey='String'}) 'UNION(ROW("WBSKey","W1","ProjectKey","P1"),ROW("WBSKey","W2","ProjectKey","P2"))'
Add-LiteralTable '01 XER_TASK' ([ordered]@{TaskKey='String';WBSKey='String';UpdateDate='DateTime'}) 'UNION(ROW("TaskKey","T1","WBSKey","W1","UpdateDate",DATE(2026,9,1)),ROW("TaskKey","T2","WBSKey","W2","UpdateDate",DATE(2026,10,1)))'
Add-LiteralTable 'CurrentDate' ([ordered]@{UpdateDate='DateTime'}) 'UNION(ROW("UpdateDate",DATE(2026,9,1)),ROW("UpdateDate",DATE(2026,10,1)))'
Add-LiteralTable 'Scenario Calendar' ([ordered]@{ProjectKey='String';ReportUpdateDate='DateTime'}) 'UNION(ROW("ProjectKey","P1","ReportUpdateDate",DATE(2026,9,1)),ROW("ProjectKey","P2","ReportUpdateDate",DATE(2026,10,1)))'
Add-LiteralTable 'Fixture Identity' ([ordered]@{Marker='String'}) ('ROW("Marker","'+$marker+'")')
function Add-Relationship($FromTable,$FromColumn,$ToTable,$ToColumn,$Both){
    $relationship=[Microsoft.AnalysisServices.Tabular.SingleColumnRelationship]::new();$relationship.Name=[Guid]::NewGuid().ToString();$relationship.FromColumn=$model.Tables.Find($FromTable).Columns.Find($FromColumn);$relationship.ToColumn=$model.Tables.Find($ToTable).Columns.Find($ToColumn);$relationship.CrossFilteringBehavior=if($Both){[Microsoft.AnalysisServices.Tabular.CrossFilteringBehavior]::BothDirections}else{[Microsoft.AnalysisServices.Tabular.CrossFilteringBehavior]::OneDirection};$model.Relationships.Add($relationship)
}
Add-Relationship '03 XER_WBS' 'ProjectKey' 'Project_Dimension' 'ProjectKey' $false
Add-Relationship '01 XER_TASK' 'WBSKey' '03 XER_WBS' 'WBSKey' $true
Add-Relationship '01 XER_TASK' 'UpdateDate' 'CurrentDate' 'UpdateDate' $true
Add-Relationship 'Scenario Calendar' 'ProjectKey' 'Project_Dimension' 'ProjectKey' $false
Add-Relationship 'Scenario Calendar' 'ReportUpdateDate' 'CurrentDate' 'UpdateDate' $false
$server=[Microsoft.AnalysisServices.Tabular.Server]::new();$phase='connect';$created=$false;$result=[ordered]@{probeDatabase=$probeId;protectedDatabase=$protectedId}
try{
    $server.Connect("localhost:$Port")
    if($null -eq $server.Databases.Find($protectedId) -or $server.Databases.Find($probeId)){throw 'Endpoint inventory guard failed.'}
    $probe=[Microsoft.AnalysisServices.Tabular.Database]::new();$probe.ID=$probeId;$probe.Name=$probeId;$probe.CompatibilityLevel=1606;$probe.Model=$model;$server.Databases.Add($probe)
    $phase='create';$probe.Update([Microsoft.AnalysisServices.UpdateOptions]::ExpandFull);$created=$true
    $phase='process';$probe.Model.RequestRefresh([Microsoft.AnalysisServices.Tabular.RefreshType]::Full);$probe.Model.SaveChanges()|Out-Null
    $phase='query';$dax='EVALUATE ROW("Matching",CALCULATE(COUNTROWS(''Scenario Calendar''),TREATAS({"P1"},Project_Dimension[ProjectKey]),TREATAS({DATE(2026,9,1)},CurrentDate[UpdateDate])),"Conflicting",CALCULATE(COUNTROWS(''Scenario Calendar''),TREATAS({"P1"},Project_Dimension[ProjectKey]),TREATAS({DATE(2026,10,1)},CurrentDate[UpdateDate])))'
    $messages=$null;$reader=$server.ExecuteReader('<Statement>'+[Security.SecurityElement]::Escape($dax)+'</Statement>',[ref]$messages,@{Catalog=$probeId;Format='Tabular';Timeout='15';DbpropMsmdRequestMemoryLimit='1048576'},$true)
    try{if(-not $reader.Read()){throw 'No result.'};$values=[ordered]@{};for($i=0;$i -lt $reader.FieldCount;$i++){$value=$reader.GetValue($i);$values[$reader.GetName($i)]=if($value -is [DBNull]){$null}else{$value}};$result.result='ACCEPTED';$result.values=$values;$result.dax=$dax}finally{$reader.Close()}
}catch{$result.result='REJECTED';$result.phase=$phase;$result.error=$_.Exception.Message}
finally{
    $existing=$server.Databases.Find($probeId)
    if($created -and $existing -and $existing.ID -ne $protectedId -and $existing.Model.Tables.Count -eq 6 -and $existing.Model.Annotations.Find('ResourcePlaygroundRelationshipProbe').Value -eq $marker){$existing.Drop();$result.cleanedUp=$true}
    $result.protectedStillPresent=$null -ne $server.Databases.Find($protectedId)
    $result|ConvertTo-Json -Depth 7|Set-Content -LiteralPath (Join-Path $artifacts 'relationship_probe.json') -Encoding utf8
    $result|ConvertTo-Json -Depth 7
    $server.Disconnect()
}
