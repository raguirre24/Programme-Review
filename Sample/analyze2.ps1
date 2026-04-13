$rsrc = Import-Csv 'c:\Users\raguirre\Documents\Code\Programme Review\Sample\12_XER_RSRC.csv'
$taskrsrc = Import-Csv 'c:\Users\raguirre\Documents\Code\Programme Review\Sample\13_XER_TASKRSRC.csv'
$dist = Import-Csv 'c:\Users\raguirre\Documents\Code\Programme Review\Sample\15_XER_RESOURCE_DISTRIBUTION.csv'

# Build rsrc lookup
$rsrcLookup = @{}
foreach ($r in $rsrc) { $rsrcLookup[$r.rsrc_id_key] = $r }

Write-Output "============================================================"
Write-Output "DEEP ANALYSIS: monthly_quantity vs month_working_hours vs def_qty_per_hr"
Write-Output "============================================================"
Write-Output ""

# Crew resource (def_qty_per_hr = 0.125)
$crewKey = "2602-EBA_PAA_8.0_BL.xer.9019"
$crewRsrc = $rsrcLookup[$crewKey]
Write-Output "=== CREW: $($crewRsrc.rsrc_short_name) ($($crewRsrc.rsrc_name)) ==="
Write-Output "  def_qty_per_hr: $($crewRsrc.def_qty_per_hr)"
Write-Output "  cost_qty_type: $($crewRsrc.cost_qty_type)"
Write-Output "  rsrc_type: $($crewRsrc.rsrc_type)"
Write-Output ""

$crewDist = $dist | Where-Object { $_.rsrc_id_key -eq $crewKey } | Select-Object -First 8
Write-Output "  dist_month | monthly_qty | month_wk_hrs | total_wk_hrs | qty/hr_ratio     | distribution_type | Unit"
Write-Output "  -----------|-------------|--------------|--------------|------------------|-------------------|-----"
foreach ($d in $crewDist) {
    $qty = [double]$d.monthly_quantity
    $hrs = [double]$d.month_working_hours
    $ratio = if ($hrs -gt 0) { [math]::Round($qty / $hrs, 6) } else { "N/A" }
    Write-Output ("  {0,-11}| {1,-12}| {2,-13}| {3,-13}| {4,-17}| {5,-18}| {6}" -f $d.distribution_month, $d.monthly_quantity, $d.month_working_hours, $d.total_working_hours, $ratio, $d.distribution_type, $d.Unit)
}

Write-Output ""
Write-Output "=== REGULAR: R-16 (CST-6 Wheeler EBA) ==="
$regKey = "2602-EBA_PAA_8.0_BL.xer.5622"
$regRsrc = $rsrcLookup[$regKey]
Write-Output "  def_qty_per_hr: $($regRsrc.def_qty_per_hr)"
Write-Output "  cost_qty_type: $($regRsrc.cost_qty_type)"
Write-Output "  rsrc_type: $($regRsrc.rsrc_type)"
Write-Output ""

$regDist = $dist | Where-Object { $_.rsrc_id_key -eq $regKey } | Select-Object -First 8
Write-Output "  dist_month | monthly_qty | month_wk_hrs | total_wk_hrs | qty/hr_ratio     | distribution_type | Unit"
Write-Output "  -----------|-------------|--------------|--------------|------------------|-------------------|-----"
foreach ($d in $regDist) {
    $qty = [double]$d.monthly_quantity
    $hrs = [double]$d.month_working_hours
    $ratio = if ($hrs -gt 0) { [math]::Round($qty / $hrs, 6) } else { "N/A" }
    Write-Output ("  {0,-11}| {1,-12}| {2,-13}| {3,-13}| {4,-17}| {5,-18}| {6}" -f $d.distribution_month, $d.monthly_quantity, $d.month_working_hours, $d.total_working_hours, $ratio, $d.distribution_type, $d.Unit)
}

Write-Output ""
Write-Output "=== MATERIAL: Check if any RT_Mat resources have distribution ==="
$matKeys = ($rsrc | Where-Object { $_.rsrc_type -eq "RT_Mat" }).rsrc_id_key
$matDist = $dist | Where-Object { $_.rsrc_id_key -in $matKeys } | Select-Object -First 8
if ($matDist) {
    $matRsrc = $rsrcLookup[$matDist[0].rsrc_id_key]
    Write-Output "  Resource: $($matRsrc.rsrc_short_name) ($($matRsrc.rsrc_name))"
    Write-Output "  def_qty_per_hr: $($matRsrc.def_qty_per_hr)"
    Write-Output "  cost_qty_type: $($matRsrc.cost_qty_type)"
    Write-Output ""
    Write-Output "  dist_month | monthly_qty | month_wk_hrs | total_wk_hrs | qty/hr_ratio     | distribution_type | Unit"
    Write-Output "  -----------|-------------|--------------|--------------|------------------|-------------------|-----"
    foreach ($d in $matDist) {
        $qty = [double]$d.monthly_quantity
        $hrs = [double]$d.month_working_hours
        $ratio = if ($hrs -gt 0) { [math]::Round($qty / $hrs, 6) } else { "N/A" }
        Write-Output ("  {0,-11}| {1,-12}| {2,-13}| {3,-13}| {4,-17}| {5,-18}| {6}" -f $d.distribution_month, $d.monthly_quantity, $d.month_working_hours, $d.total_working_hours, $ratio, $d.distribution_type, $d.Unit)
    }
} else {
    Write-Output "  No distribution rows found for RT_Mat resources"
}

Write-Output ""
Write-Output "=== VERIFICATION: Does monthly_quantity = month_working_hours * def_qty_per_hr ? ==="
$sampleDist = $dist | Select-Object -First 500
$matchCount = 0
$mismatchCount = 0
$mismatches = @()
foreach ($d in $sampleDist) {
    $r = $rsrcLookup[$d.rsrc_id_key]
    if ($r) {
        $qty = [double]$d.monthly_quantity
        $hrs = [double]$d.month_working_hours
        $dqph = [double]$r.def_qty_per_hr
        $expected = [math]::Round($hrs * $dqph, 4)
        if ([math]::Abs($qty - $expected) -lt 0.01) {
            $matchCount++
        } else {
            $mismatchCount++
            if ($mismatches.Count -lt 5) {
                $mismatches += [PSCustomObject]@{
                    rsrc = $r.rsrc_short_name
                    def_qty_per_hr = $dqph
                    monthly_qty = $qty
                    month_wk_hrs = $hrs
                    expected = $expected
                    diff = [math]::Round($qty - $expected, 4)
                    dist_type = $d.distribution_type
                    unit = $d.Unit
                }
            }
        }
    }
}
Write-Output "  Formula: monthly_quantity = month_working_hours * def_qty_per_hr"
Write-Output "  Matches: $matchCount / $($matchCount + $mismatchCount)"
Write-Output "  Mismatches: $mismatchCount"
if ($mismatches) {
    Write-Output ""
    Write-Output "  Sample mismatches:"
    $mismatches | Format-Table -AutoSize | Out-String -Width 250
}

Write-Output ""
Write-Output "=== TASKRSRC: Does target_qty_per_hr match def_qty_per_hr? ==="
$taskSample = $taskrsrc | Select-Object -First 200
$tMatch = 0
$tMismatch = 0
$tMismatches = @()
foreach ($t in $taskSample) {
    $r = $rsrcLookup[$t.rsrc_id_key]
    if ($r) {
        $tqph = [double]$t.target_qty_per_hr
        $dqph = [double]$r.def_qty_per_hr
        if ([math]::Abs($tqph - $dqph) -lt 0.001) {
            $tMatch++
        } else {
            $tMismatch++
            if ($tMismatches.Count -lt 5) {
                $tMismatches += [PSCustomObject]@{
                    rsrc = $r.rsrc_short_name
                    def_qty_per_hr = $dqph
                    target_qty_per_hr = $tqph
                    target_qty = $t.target_qty
                    remain_qty = $t.remain_qty
                }
            }
        }
    }
}
Write-Output "  Matches (target_qty_per_hr == def_qty_per_hr): $tMatch / $($tMatch + $tMismatch)"
Write-Output "  Mismatches: $tMismatch"
if ($tMismatches) {
    Write-Output ""
    Write-Output "  Sample mismatches (target_qty_per_hr overridden at task level):"
    $tMismatches | Format-Table -AutoSize | Out-String -Width 250
}

Write-Output ""
Write-Output "=== QT_Day resources: How are they distributed? ==="
$dayKeys = ($rsrc | Where-Object { $_.cost_qty_type -eq "QT_Day" }).rsrc_id_key
$dayDist = $dist | Where-Object { $_.rsrc_id_key -in $dayKeys } | Select-Object -First 8
if ($dayDist) {
    $dayRsrc = $rsrcLookup[$dayDist[0].rsrc_id_key]
    Write-Output "  Resource: $($dayRsrc.rsrc_short_name) ($($dayRsrc.rsrc_name))"
    Write-Output "  def_qty_per_hr: $($dayRsrc.def_qty_per_hr)"
    Write-Output "  cost_qty_type: $($dayRsrc.cost_qty_type)"
    Write-Output "  rsrc_type: $($dayRsrc.rsrc_type)"
    Write-Output ""
    Write-Output "  dist_month | monthly_qty | month_wk_hrs | total_wk_hrs | distribution_type | Unit"
    Write-Output "  -----------|-------------|--------------|--------------|-------------------|-----"
    foreach ($d in $dayDist) {
        Write-Output ("  {0,-11}| {1,-12}| {2,-13}| {3,-13}| {4,-18}| {5}" -f $d.distribution_month, $d.monthly_quantity, $d.month_working_hours, $d.total_working_hours, $d.distribution_type, $d.Unit)
    }
} else {
    Write-Output "  No distribution rows found for QT_Day resources"
}
