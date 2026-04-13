$rsrc = Import-Csv 'c:\Users\raguirre\Documents\Code\Programme Review\Sample\12_XER_RSRC.csv'
$taskrsrc = Import-Csv 'c:\Users\raguirre\Documents\Code\Programme Review\Sample\13_XER_TASKRSRC.csv'
$dist = Import-Csv 'c:\Users\raguirre\Documents\Code\Programme Review\Sample\15_XER_RESOURCE_DISTRIBUTION.csv'

Write-Output "=== 12_XER_RSRC: DISTINCT def_qty_per_hr values ==="
$rsrc | Group-Object def_qty_per_hr | ForEach-Object { Write-Output ("  {0}: {1} resources" -f $_.Name, $_.Count) }

Write-Output ""
Write-Output "=== 12_XER_RSRC: DISTINCT cost_qty_type values ==="
$rsrc | Group-Object cost_qty_type | ForEach-Object { Write-Output ("  {0}: {1} resources" -f $_.Name, $_.Count) }

Write-Output ""
Write-Output "=== 12_XER_RSRC: def_qty_per_hr by rsrc_type ==="
$rsrc | Group-Object rsrc_type, def_qty_per_hr | ForEach-Object { Write-Output ("  {0}: {1} resources" -f $_.Name, $_.Count) }

Write-Output ""
Write-Output "=== 12_XER_RSRC: cost_qty_type by rsrc_type ==="
$rsrc | Group-Object rsrc_type, cost_qty_type | ForEach-Object { Write-Output ("  {0}: {1} resources" -f $_.Name, $_.Count) }

Write-Output ""
Write-Output "=== SAMPLE: Crew resource (def_qty_per_hr=0.125) ==="
$crew = $rsrc | Where-Object { [double]$_.def_qty_per_hr -ne 1 } | Select-Object rsrc_short_name, rsrc_name, rsrc_type, def_qty_per_hr, cost_qty_type, unit_id, rsrc_id_key
$crew | Format-Table -AutoSize | Out-String -Width 250

Write-Output ""
Write-Output "=== 13_XER_TASKRSRC: Sample rows for a crew resource ==="
if ($crew) {
    $crewKey = $crew[0].rsrc_id_key
    Write-Output "Looking for rsrc_id_key: $crewKey"
    $taskrsrc | Where-Object { $_.rsrc_id_key -eq $crewKey } | Select-Object -First 5 task_id_key, rsrc_id_key, target_qty, remain_qty, target_qty_per_hr, remain_qty_per_hr, act_reg_qty, act_ot_qty, rsrc_type | Format-Table -AutoSize | Out-String -Width 250
}

Write-Output ""
Write-Output "=== 15_XER_RESOURCE_DISTRIBUTION: Sample rows for same crew resource ==="
if ($crew) {
    $crewKey = $crew[0].rsrc_id_key
    $dist | Where-Object { $_.rsrc_id_key -eq $crewKey } | Select-Object -First 10 task_id_key, rsrc_id_key, rsrc_short_name, distribution_month, monthly_quantity, distribution_type, month_working_hours, total_working_hours, Unit | Format-Table -AutoSize | Out-String -Width 250
}

Write-Output ""
Write-Output "=== 15_XER_RESOURCE_DISTRIBUTION: DISTINCT distribution_type values ==="
$dist | Group-Object distribution_type | ForEach-Object { Write-Output ("  {0}: {1} rows" -f $_.Name, $_.Count) }

Write-Output ""
Write-Output "=== 15_XER_RESOURCE_DISTRIBUTION: DISTINCT Unit values ==="
$dist | Group-Object Unit | ForEach-Object { Write-Output ("  {0}: {1} rows" -f $_.Name, $_.Count) }

Write-Output ""
Write-Output "=== Compare: TASKRSRC target_qty vs DISTRIBUTION total for same task/resource ==="
if ($crew) {
    $crewKey = $crew[0].rsrc_id_key
    $crewTasks = $taskrsrc | Where-Object { $_.rsrc_id_key -eq $crewKey } | Select-Object -First 3
    foreach ($t in $crewTasks) {
        $tid = $t.task_id_key
        $tqty = $t.target_qty
        $rqty = $t.remain_qty
        $tqtyhr = $t.target_qty_per_hr
        $distRows = $dist | Where-Object { $_.task_id_key -eq $tid -and $_.rsrc_id_key -eq $crewKey }
        $distTotal = ($distRows | Measure-Object -Property monthly_quantity -Sum).Sum
        Write-Output "  task_id_key: $tid"
        Write-Output "    TASKRSRC: target_qty=$tqty, remain_qty=$rqty, target_qty_per_hr=$tqtyhr"
        Write-Output "    DISTRIBUTION SUM(monthly_quantity): $distTotal"
        Write-Output "    DISTRIBUTION distribution_type: $(($distRows | Select-Object -First 1).distribution_type)"
        Write-Output "    DISTRIBUTION rows: $($distRows.Count)"
        Write-Output ""
    }
}

Write-Output ""
Write-Output "=== Compare: Regular resource (def_qty_per_hr=1) vs Crew (def_qty_per_hr=0.125) ==="
$regular = $rsrc | Where-Object { [double]$_.def_qty_per_hr -eq 1 } | Select-Object -First 1
if ($regular) {
    $regKey = $regular.rsrc_id_key
    Write-Output "Regular resource: $($regular.rsrc_short_name) ($($regular.rsrc_name)), def_qty_per_hr=$($regular.def_qty_per_hr)"
    $regTasks = $taskrsrc | Where-Object { $_.rsrc_id_key -eq $regKey } | Select-Object -First 3
    foreach ($t in $regTasks) {
        $tid = $t.task_id_key
        $distRows = $dist | Where-Object { $_.task_id_key -eq $tid -and $_.rsrc_id_key -eq $regKey }
        $distTotal = ($distRows | Measure-Object -Property monthly_quantity -Sum).Sum
        Write-Output "  task_id_key: $tid"
        Write-Output "    TASKRSRC: target_qty=$($t.target_qty), remain_qty=$($t.remain_qty), target_qty_per_hr=$($t.target_qty_per_hr)"
        Write-Output "    DISTRIBUTION SUM(monthly_quantity): $distTotal"
        Write-Output "    DISTRIBUTION distribution_type: $(($distRows | Select-Object -First 1).distribution_type)"
        Write-Output ""
    }
}
