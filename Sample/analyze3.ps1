$rsrc = Import-Csv 'c:\Users\raguirre\Documents\Code\Programme Review\Sample\12_XER_RSRC.csv'
$taskrsrc = Import-Csv 'c:\Users\raguirre\Documents\Code\Programme Review\Sample\13_XER_TASKRSRC.csv'
$dist = Import-Csv 'c:\Users\raguirre\Documents\Code\Programme Review\Sample\15_XER_RESOURCE_DISTRIBUTION.csv'

$rsrcLookup = @{}
foreach ($r in $rsrc) { $rsrcLookup[$r.rsrc_id_key] = $r }

$taskrsrcLookup = @{}
foreach ($t in $taskrsrc) {
    $key = "$($t.task_id_key)|$($t.rsrc_id_key)"
    $taskrsrcLookup[$key] = $t
}

Write-Output "============================================================"
Write-Output "FORMULA DISCOVERY: What formula produces monthly_quantity?"
Write-Output "============================================================"
Write-Output ""
Write-Output "Testing: monthly_quantity = month_working_hours * target_qty_per_hr (from TASKRSRC)"
Write-Output ""

$tests = $dist | Select-Object -First 1000
$match1 = 0; $miss1 = 0; $noTask = 0
$samples = @()

foreach ($d in $tests) {
    $key = "$($d.task_id_key)|$($d.rsrc_id_key)"
    $t = $taskrsrcLookup[$key]
    if (-not $t) { $noTask++; continue }
    
    $qty = [double]$d.monthly_quantity
    $hrs = [double]$d.month_working_hours
    $tqph = [double]$t.target_qty_per_hr
    $expected = [math]::Round($hrs * $tqph, 4)
    
    if ([math]::Abs($qty - $expected) -lt 0.01) {
        $match1++
    } else {
        $miss1++
        if ($samples.Count -lt 5) {
            $r = $rsrcLookup[$d.rsrc_id_key]
            $samples += [PSCustomObject]@{
                rsrc = $r.rsrc_short_name
                monthly_qty = $qty
                month_wk_hrs = $hrs
                target_qty_per_hr = $tqph
                expected_hrs_x_tqph = $expected
                diff = [math]::Round($qty - $expected, 4)
                is_actual = $d.is_actual
                status_code = $d.status_code
            }
        }
    }
}
Write-Output "  Result: $match1 match / $miss1 mismatch / $noTask no taskrsrc found"
if ($samples) {
    Write-Output "  Mismatches:"
    $samples | Format-Table -AutoSize | Out-String -Width 300
}

Write-Output ""
Write-Output "============================================================"
Write-Output "Testing: monthly_quantity = target_qty * (month_working_hours / total_working_hours)"
Write-Output "(i.e. pro-rata distribution of target_qty by working hours)"
Write-Output "============================================================"

$match2 = 0; $miss2 = 0; $noTask2 = 0
$samples2 = @()

foreach ($d in $tests) {
    $key = "$($d.task_id_key)|$($d.rsrc_id_key)"
    $t = $taskrsrcLookup[$key]
    if (-not $t) { $noTask2++; continue }
    
    $qty = [double]$d.monthly_quantity
    $mhrs = [double]$d.month_working_hours
    $thrs = [double]$d.total_working_hours
    $tqty = [double]$t.target_qty
    
    if ($thrs -eq 0) { continue }
    
    $expected = [math]::Round($tqty * ($mhrs / $thrs), 4)
    
    if ([math]::Abs($qty - $expected) -lt 0.02) {
        $match2++
    } else {
        $miss2++
        if ($samples2.Count -lt 8) {
            $r = $rsrcLookup[$d.rsrc_id_key]
            $samples2 += [PSCustomObject]@{
                rsrc = $r.rsrc_short_name
                monthly_qty = $qty
                target_qty = $tqty
                month_hrs = $mhrs
                total_hrs = $thrs
                expected = $expected
                diff = [math]::Round($qty - $expected, 4)
                is_actual = $d.is_actual
                status = $d.status_code
            }
        }
    }
}
Write-Output "  Result: $match2 match / $miss2 mismatch"
if ($samples2) {
    Write-Output "  Mismatches:"
    $samples2 | Format-Table -AutoSize | Out-String -Width 300
}

Write-Output ""
Write-Output "============================================================"
Write-Output "KEY QUESTION: Is monthly_quantity already in the resource's native unit?"
Write-Output "(i.e. already adjusted by def_qty_per_hr / target_qty_per_hr)"
Write-Output "============================================================"
Write-Output ""

# For crew resources (def_qty_per_hr=0.125), check if qty represents days
$crewKey = "2602-EBA_PAA_8.0_BL.xer.9019"
$crewDist = $dist | Where-Object { $_.rsrc_id_key -eq $crewKey } | Select-Object -First 5
Write-Output "Crew resource (def_qty_per_hr=0.125, 8hr day -> 0.125 = 1/8 = 1 unit per day):"
foreach ($d in $crewDist) {
    $qty = [double]$d.monthly_quantity
    $hrs = [double]$d.month_working_hours
    $days = $hrs / 8
    Write-Output ("  month={0}, monthly_qty={1}, month_hrs={2}, implied_days={3}, qty_matches_days={4}" -f $d.distribution_month, $qty, $hrs, $days, ($qty -eq $days))
}

Write-Output ""
Write-Output "============================================================"
Write-Output "CONCLUSION VERIFICATION: SUM(monthly_quantity) == target_qty for each task/resource?"
Write-Output "============================================================"

$taskGrouped = $dist | Group-Object { "$($_.task_id_key)|$($_.rsrc_id_key)" }
$sumMatch = 0; $sumMiss = 0
$sumSamples = @()

foreach ($g in ($taskGrouped | Select-Object -First 200)) {
    $parts = $g.Name -split '\|'
    $tid = $parts[0]; $rid = $parts[1]
    $key = "$tid|$rid"
    $t = $taskrsrcLookup[$key]
    if (-not $t) { continue }
    
    $distSum = ($g.Group | Measure-Object -Property monthly_quantity -Sum).Sum
    $targetQty = [double]$t.target_qty
    
    if ([math]::Abs($distSum - $targetQty) -lt 0.02) {
        $sumMatch++
    } else {
        $sumMiss++
        if ($sumSamples.Count -lt 5) {
            $r = $rsrcLookup[$rid]
            $sumSamples += [PSCustomObject]@{
                rsrc = $r.rsrc_short_name
                def_qty_per_hr = $r.def_qty_per_hr
                target_qty = $targetQty
                dist_sum = [math]::Round($distSum, 4)
                diff = [math]::Round($distSum - $targetQty, 4)
                status = ($g.Group | Select-Object -First 1).status_code
                is_actual = ($g.Group | Select-Object -First 1).is_actual
            }
        }
    }
}
Write-Output "  SUM(monthly_quantity) == target_qty: $sumMatch match / $sumMiss mismatch"
if ($sumSamples) {
    Write-Output "  Mismatches (likely in-progress or completed tasks with actuals):"
    $sumSamples | Format-Table -AutoSize | Out-String -Width 300
}
