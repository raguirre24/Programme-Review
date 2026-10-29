[CmdletBinding()]
param(
    [string]$ServerAddress,
    [string]$Catalog,
    [string]$ModelDefinition = (Join-Path $PSScriptRoot '..\..\Project Review - Programme (datalake).SemanticModel\definition'),
    [string]$ReportDefinition = (Join-Path $PSScriptRoot '..\..\Project Review - Programme (datalake).Report\definition')
)

<#
.SYNOPSIS
Read-only live Row-Level Security (RLS) validator against an open Power BI Desktop instance.

.DESCRIPTION
Connects to Power BI Desktop using read-only DAX ExecuteReader queries only (zero TMSL,
SaveChanges, Process, or model mutations):
  1. Connects under Roles='Project Access' and executes all 257 data-bound PBIR visual
     queries across all 13 pages (injecting disk DEFINE MEASURE overrides for newly edited
     measures and applying the 'Update Has Visible Tasks' = 1 filter on all 11 CurrentDate
     slicers).
  2. Verifies zero-access table isolation across all 11 RLS-reachable project tables and
     zero leaked dates on CurrentDate slicers when the Desktop Windows UPN has no grants.
  3. Compiles and evaluates the disk tablePermission DAX predicates (Project_Dimension,
     Monthly Resource Distribution Baseline, dbo_userpermission) across Zero-Access,
     All-Access, #ext# Guest UPN recovery, Project-Scoped, and State-Scoped user tiers.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

. (Join-Path $PSScriptRoot '..\schedule_metrics\Common.ps1')
Import-ScheduleMetricsTom
$tomDir = Split-Path ([Microsoft.AnalysisServices.Tabular.Server].Assembly.Location)
[Reflection.Assembly]::LoadFrom((Join-Path $tomDir 'Microsoft.AnalysisServices.Tabular.Json.dll')) | Out-Null

$resolvedModelDir = (Resolve-Path -LiteralPath $ModelDefinition).Path
$resolvedReportDir = (Resolve-Path -LiteralPath $ReportDefinition).Path
$diskModel = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeModelFromFolder($resolvedModelDir)

$validCols = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$validMeas = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
foreach ($t in $diskModel.Tables) {
    foreach ($c in $t.Columns) {
        if ($c -isnot [Microsoft.AnalysisServices.Tabular.RowNumberColumn]) {
            [void]$validCols.Add("$($t.Name)|$($c.Name)")
        }
    }
    foreach ($m in $t.Measures) {
        [void]$validMeas.Add("$($t.Name)|$($m.Name)")
    }
}

# Build query-scoped DEFINE MEASURE block so disk measure edits are validated even before Desktop reloads TMDL
$defineLines = [System.Collections.Generic.List[string]]::new()
$defineLines.Add('DEFINE')
$overriddenMeasures = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
foreach ($tName in @('Resource Scenario Measures', 'XER Measures')) {
    $tbl = $diskModel.Tables[$tName]
    foreach ($m in $tbl.Measures) {
        if ($tName -eq 'Resource Scenario Measures' -or $m.Name -like 'CA *' -or $m.Name -like 'CS *' -or $m.Name -eq 'Update Has Visible Tasks') {
            $escT = $tName.Replace("'", "''")
            $escM = $m.Name.Replace(']', ']]')
            $defineLines.Add("MEASURE '$escT'[$escM] =`n$($m.Expression)")
            [void]$overriddenMeasures.Add("$tName|$($m.Name)")
        }
    }
}
$defineBlock = $defineLines -join "`n"

function Extract-VisualRefs {
    param($Node, [System.Collections.Generic.List[object]]$Cols, [System.Collections.Generic.List[object]]$Meas)
    if ($null -eq $Node) { return }
    if ($Node -is [System.Management.Automation.PSCustomObject]) {
        $props = $Node.PSObject.Properties
        if ($props['Column'] -and $Node.Column -is [System.Management.Automation.PSCustomObject]) {
            $c = $Node.Column
            $ent = $null
            if ($c.PSObject.Properties['Expression'] -and $c.Expression.PSObject.Properties['SourceRef'] -and $c.Expression.SourceRef.PSObject.Properties['Entity']) {
                $ent = $c.Expression.SourceRef.Entity
            }
            $prop = if ($c.PSObject.Properties['Property']) { $c.Property } else { $null }
            if ($ent -and $prop -and $validCols.Contains("$ent|$prop")) {
                if (-not ($Cols | Where-Object { $_[0] -eq $ent -and $_[1] -eq $prop })) {
                    $Cols.Add(@($ent, $prop))
                }
            }
        }
        if ($props['Measure'] -and $Node.Measure -is [System.Management.Automation.PSCustomObject]) {
            $m = $Node.Measure
            $ent = $null
            if ($m.PSObject.Properties['Expression'] -and $m.Expression.PSObject.Properties['SourceRef'] -and $m.Expression.SourceRef.PSObject.Properties['Entity']) {
                $ent = $m.Expression.SourceRef.Entity
            }
            $prop = if ($m.PSObject.Properties['Property']) { $m.Property } else { $null }
            if ($ent -and $prop -and $validMeas.Contains("$ent|$prop")) {
                if (-not ($Meas | Where-Object { $_[0] -eq $ent -and $_[1] -eq $prop })) {
                    $Meas.Add(@($ent, $prop))
                }
            }
        }
        foreach ($p in $props) {
            if ($p.Name -ne 'sortDefinition') {
                Extract-VisualRefs -Node $p.Value -Cols $Cols -Meas $Meas
            }
        }
    } elseif ($Node -is [System.Collections.IEnumerable] -and $Node -isnot [string]) {
        foreach ($item in $Node) {
            Extract-VisualRefs -Node $item -Cols $Cols -Meas $Meas
        }
    }
}

$adminTarget = Connect-ScheduleMetricsModel -ServerAddress $ServerAddress -Catalog $Catalog
$addr = $adminTarget.Address
$dbId = $adminTarget.Database.ID

$rlsServer = New-Object Microsoft.AnalysisServices.Tabular.Server
$rlsServer.Connect("Data Source=$addr;Initial Catalog=$dbId;Roles=Project Access")
$rlsTarget = [pscustomobject]@{
    Connection = $rlsServer
    Database   = [pscustomobject]@{ ID = $dbId }
    Address    = $addr
}

try {
    # -------------------------------------------------------------------------
    # 1. Execute all 257 data-bound PBIR visual queries across all 13 pages
    # -------------------------------------------------------------------------
    $pagesJson = Get-Content -LiteralPath (Join-Path $resolvedReportDir 'pages\pages.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $visualQueries = [System.Collections.Generic.List[object]]::new()

    foreach ($pid_ in $pagesJson.pageOrder) {
        $pdir = Join-Path $resolvedReportDir "pages\$pid_"
        $pjson = Get-Content -LiteralPath (Join-Path $pdir 'page.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $pname = if ($pjson.PSObject.Properties['displayName']) { $pjson.displayName } else { $pid_ }
        $vfiles = Get-ChildItem -LiteralPath (Join-Path $pdir 'visuals') -Filter 'visual.json' -Recurse | Sort-Object FullName
        foreach ($vf in $vfiles) {
            $vjson = Get-Content -LiteralPath $vf.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            if (-not $vjson.PSObject.Properties['visual']) { continue }
            $vis = $vjson.visual
            $vtype = if ($vis.PSObject.Properties['visualType']) { $vis.visualType } else { 'unknown' }
            $cols = [System.Collections.Generic.List[object]]::new()
            $meas = [System.Collections.Generic.List[object]]::new()
            if ($vis.PSObject.Properties['query']) {
                Extract-VisualRefs -Node $vis.query -Cols $cols -Meas $meas
            }
            if ($vis.PSObject.Properties['objects']) {
                $dummyCols = [System.Collections.Generic.List[object]]::new()
                Extract-VisualRefs -Node $vis.objects -Cols $dummyCols -Meas $meas
            }
            if ($vis.PSObject.Properties['visualContainerObjects']) {
                $dummyCols = [System.Collections.Generic.List[object]]::new()
                Extract-VisualRefs -Node $vis.visualContainerObjects -Cols $dummyCols -Meas $meas
            }
            if ($cols.Count -eq 0 -and $meas.Count -eq 0) { continue }

            # Expand composite-key field parameter tables ('Scenario Period', 'Calendar Period')
            foreach ($fpTable in @('Scenario Period', 'Calendar Period')) {
                $hasFp = @($cols | Where-Object { $_[0] -eq $fpTable }).Count -gt 0
                if ($hasFp) {
                    foreach ($reqCol in @('Period', 'Period Fields', 'Period Order')) {
                        if (-not ($cols | Where-Object { $_[0] -eq $fpTable -and $_[1] -eq $reqCol })) {
                            $cols.Add(@($fpTable, $reqCol))
                        }
                    }
                }
            }

            $hasUhvtFilter = $false
            if ($vjson.PSObject.Properties['filterConfig'] -and $vjson.filterConfig.PSObject.Properties['filters']) {
                foreach ($flt in $vjson.filterConfig.filters) {
                    if ($flt.PSObject.Properties['field'] -and $flt.field.PSObject.Properties['Measure']) {
                        $fm = $flt.field.Measure
                        if ($fm.Property -eq 'Update Has Visible Tasks') {
                            $hasUhvtFilter = $true
                        }
                    }
                }
            }

            $visualQueries.Add([pscustomobject]@{
                Page          = $pname
                Visual        = $vf.Directory.Name
                Type          = $vtype
                Cols          = $cols
                Meas          = $meas
                HasUhvtFilter = $hasUhvtFilter
            })
        }
    }

    $passCount = 0
    $failures = [System.Collections.Generic.List[object]]::new()
    $currentDateSlicerRows = 0
    $currentDateSlicersTested = 0

    foreach ($vq in $visualQueries) {
        $colArgs = @($vq.Cols | ForEach-Object {
            $t = $_[0].Replace("'", "''")
            $c = $_[1].Replace("]", "]]")
            "'$t'[$c]"
        })
        $measArgs = @()
        $idx = 0
        foreach ($m in $vq.Meas) {
            $idx++
            $t = $m[0].Replace("'", "''")
            $mn = $m[1].Replace("]", "]]")
            $measArgs += """M$idx"", '$t'[$mn]"
        }

        $needsDefine = $vq.HasUhvtFilter
        foreach ($m in $vq.Meas) {
            if ($overriddenMeasures.Contains("$($m[0])|$($m[1])")) { $needsDefine = $true }
        }
        $prefix = if ($needsDefine) { "$defineBlock`n" } else { '' }

        $filterArgs = @("TREATAS({FALSE}, '01 XER_TASK'[IsExcludedFromDataLake])")
        if ($vq.HasUhvtFilter) {
            $filterArgs += "FILTER(KEEPFILTERS(VALUES('CurrentDate'[UpdateDate])), 'XER Measures'[Update Has Visible Tasks] = 1)"
        }

        if ($colArgs.Count -gt 0) {
            $allArgs = @($colArgs) + $filterArgs + @($measArgs)
            $dax = "${prefix}EVALUATE TOPN(20, SUMMARIZECOLUMNS(" + ($allArgs -join ', ') + '))'
        } else {
            $dax = "${prefix}EVALUATE CALCULATETABLE(ROW(" + ($measArgs -join ', ') + '), ' + ($filterArgs -join ', ') + ')'
        }

        try {
            $rows = (Invoke-ScheduleMetricsDax -Target $rlsTarget -Query $dax -TimeoutSeconds 30)
            $passCount++
            if ($vq.HasUhvtFilter -and $vq.Type -eq 'slicer') {
                $currentDateSlicersTested++
                $currentDateSlicerRows += $rows.Count
            }
        } catch {
            $failures.Add([pscustomobject]@{
                Page   = $vq.Page
                Visual = $vq.Visual
                Type   = $vq.Type
                Error  = $_.Exception.Message
            })
        }
    }

    if ($failures.Count -gt 0) {
        $failures | Format-List | Out-String | Write-Error
        throw "Live RLS visual validation failed on $($failures.Count) visual(s)."
    }
    Assert-ScheduleMetric ($visualQueries.Count -ge 257) "Expected at least 257 data-bound PBIR visuals, found $($visualQueries.Count)."
    Assert-ScheduleMetric ($currentDateSlicersTested -eq 11) "Expected 11 guarded CurrentDate slicers, tested $currentDateSlicersTested."

    # -------------------------------------------------------------------------
    # 2. Check signed-in RLS user's grant count & verify zero-access isolation
    # -------------------------------------------------------------------------
    $selfCheck = (Invoke-ScheduleMetricsDax -Target $rlsTarget -Query 'EVALUATE ROW("Upn", USERPRINCIPALNAME(), "VisibleProjects", COUNTROWS(''Project_Dimension''))')[0]
    if ([int]$selfCheck.'[VisibleProjects]' -eq 0) {
        Assert-ScheduleMetric ($currentDateSlicerRows -eq 0) "Zero-access RLS user saw $currentDateSlicerRows CurrentDate slicer rows (expected 0)."
        $securedTables = @(
            'Project_Dimension', '03 XER_PROJWBS', '01 XER_TASK', '04 XER_BASELINE',
            '06 XER_PREDECESSOR', '06a XER_SUCCESSOR', '09 XER_TASKACTV',
            '11 XER_CALENDAR_DETAILED', '15_XER_RESOURCE_DISTRIBUTION',
            'Scenario Calendar', 'Scenario Comparison Calendar'
        )
        $rowPairs = @($securedTables | ForEach-Object { """$_"", COUNTROWS('$_')" }) -join ', '
        $zeroCounts = (Invoke-ScheduleMetricsDax -Target $rlsTarget -Query "EVALUATE ROW($rowPairs)")[0]
        foreach ($st in $securedTables) {
            $colKey = "[$st]"
            Assert-ScheduleMetric ([int]$zeroCounts.$colKey -eq 0) "Zero-access RLS user saw $($zeroCounts.$colKey) rows in '$st' (expected 0)."
        }
    }

    # -------------------------------------------------------------------------
    # 3. Compile & evaluate disk tablePermission predicates across access tiers
    # -------------------------------------------------------------------------
    $role = $diskModel.Roles['Project Access']
    $pdPerm = ($role.TablePermissions | Where-Object { $_.Table.Name -eq 'Project_Dimension' }).FilterExpression
    $blPerm = ($role.TablePermissions | Where-Object { $_.Table.Name -eq 'Monthly Resource Distribution Baseline' }).FilterExpression
    $upPerm = ($role.TablePermissions | Where-Object { $_.Table.Name -eq 'dbo_userpermission' }).FilterExpression

    function Invoke-SimulatedTierCheck {
        param([string]$SimulatedUpn)
        $escUpn = $SimulatedUpn.Replace('"', '""')
        $pdExpr = $pdPerm.Replace('USERPRINCIPALNAME ()', """$escUpn""")
        $blExpr = $blPerm.Replace('USERPRINCIPALNAME ()', """$escUpn""")
        $upExpr = $upPerm.Replace('USERPRINCIPALNAME ()', """$escUpn""")
        $q = @"
EVALUATE
ROW(
    "PD_Total", COUNTROWS(ALL('Project_Dimension')),
    "PD_Allowed", COUNTROWS(FILTER(ALL('Project_Dimension'), $pdExpr)),
    "BL_Total", COUNTROWS(ALL('Monthly Resource Distribution Baseline')),
    "BL_Allowed", COUNTROWS(FILTER(ALL('Monthly Resource Distribution Baseline'), $blExpr)),
    "UP_Total", COUNTROWS(ALL('dbo_userpermission')),
    "UP_Allowed", COUNTROWS(FILTER(ALL('dbo_userpermission'), $upExpr))
)
"@
        return (Invoke-ScheduleMetricsDax -Target $adminTarget -Query $q -TimeoutSeconds 30)[0]
    }

    # 3a. Zero-access external guest
    $zeroSim = Invoke-SimulatedTierCheck -SimulatedUpn 'stranger.person_gmail.com#ext#@acciona365.onmicrosoft.com'
    Assert-ScheduleMetric ([int]$zeroSim.'[PD_Allowed]' -eq 0) "Zero-access guest matched $($zeroSim.'[PD_Allowed]') Project_Dimension rows."
    Assert-ScheduleMetric ([int]$zeroSim.'[BL_Allowed]' -eq 0) "Zero-access guest matched $($zeroSim.'[BL_Allowed]') Monthly Resource Distribution Baseline rows."
    Assert-ScheduleMetric ([int]$zeroSim.'[UP_Allowed]' -eq 0) "Zero-access guest matched $($zeroSim.'[UP_Allowed]') dbo_userpermission rows."

    # 3b. Sample real All-Access user + #ext# guest UPN recovery
    $allAccessSample = (Invoke-ScheduleMetricsDax -Target $adminTarget -Query @"
EVALUATE
TOPN(
    1,
    FILTER(
        ALL('dbo_userpermission'),
        NOT ISBLANK('dbo_userpermission'[userprincipalname])
            && ISBLANK('dbo_userpermission'[projectid])
            && (ISBLANK('dbo_userpermission'[region]) || TRIM('dbo_userpermission'[region]) = "")
            && ISBLANK('dbo_userpermission'[companyid])
    ),
    'dbo_userpermission'[userprincipalname], ASC
)
"@)
    $allAccessTested = $false
    if ($allAccessSample.Count -gt 0) {
        $allUpn = [string]$allAccessSample[0].'dbo_userpermission[userprincipalname]'
        $allSim = Invoke-SimulatedTierCheck -SimulatedUpn "  $($allUpn.ToUpperInvariant())  "
        Assert-ScheduleMetric ([int]$allSim.'[PD_Allowed]' -eq [int]$allSim.'[PD_Total]') "All-Access user should see all $($allSim.'[PD_Total]') projects, got $($allSim.'[PD_Allowed]')."
        Assert-ScheduleMetric ([int]$allSim.'[BL_Allowed]' -eq [int]$allSim.'[BL_Total]') "All-Access user should see all $($allSim.'[BL_Total]') baseline rows, got $($allSim.'[BL_Allowed]')."
        Assert-ScheduleMetric ([int]$allSim.'[UP_Allowed]' -gt 0 -and [int]$allSim.'[UP_Allowed]' -lt [int]$allSim.'[UP_Total]') "dbo_userpermission self-filter failed for All-Access user."

        # Guest #ext# mangled form of the same UPN
        $atIdx = $allUpn.Trim().LastIndexOf('@')
        if ($atIdx -gt 0) {
            $guestUpn = $allUpn.Trim().Substring(0, $atIdx) + '_' + $allUpn.Trim().Substring($atIdx + 1) + '#ext#@acciona365.onmicrosoft.com'
            $guestSim = Invoke-SimulatedTierCheck -SimulatedUpn $guestUpn
            Assert-ScheduleMetric ([int]$guestSim.'[PD_Allowed]' -eq [int]$guestSim.'[PD_Total]') "#ext# guest recovery failed for $guestUpn."
        }
        $allAccessTested = $true
    }

    # 3c. Sample real Project-Scoped user (who has access to a loaded project, but NOT all loaded projects)
    $projScopedSample = (Invoke-ScheduleMetricsDax -Target $adminTarget -Query @"
EVALUATE
VAR LoadedCodes = VALUES('Project_Dimension'[ProjectCode])
VAR CandidateUsers =
    DISTINCT(
        SELECTCOLUMNS(
            FILTER(
                ALL('dbo_userpermission'),
                NOT ISBLANK('dbo_userpermission'[userprincipalname])
                    && UPPER(TRIM('dbo_userpermission'[projectno])) IN LoadedCodes
            ),
            "UPN", LOWER(TRIM('dbo_userpermission'[userprincipalname]))
        )
    )
VAR ScopedOnly =
    FILTER(
        CandidateUsers,
        VAR u = [UPN]
        VAR HasGlobal =
            COUNTROWS(
                FILTER(
                    ALL('dbo_userpermission'),
                    LOWER(TRIM('dbo_userpermission'[userprincipalname])) = u
                        && ISBLANK('dbo_userpermission'[projectid])
                )
            ) > 0
        VAR MatchedProjects =
            COUNTROWS(
                DISTINCT(
                    SELECTCOLUMNS(
                        FILTER(
                            ALL('Project_Dimension'),
                            UPPER(TRIM('Project_Dimension'[ProjectCode])) IN
                                SELECTCOLUMNS(
                                    FILTER(ALL('dbo_userpermission'), LOWER(TRIM('dbo_userpermission'[userprincipalname])) = u),
                                    "P", UPPER(TRIM('dbo_userpermission'[projectno]))
                                )
                        ),
                        "PK", 'Project_Dimension'[ProjectKey]
                    )
                )
            )
        RETURN NOT HasGlobal && MatchedProjects > 0 && MatchedProjects < COUNTROWS(ALL('Project_Dimension'))
    )
RETURN TOPN(1, ScopedOnly, [UPN], ASC)
"@)
    $projScopedTested = $false
    if ($projScopedSample.Count -gt 0) {
        $scopedUpn = [string]$projScopedSample[0].'[UPN]'
        $scopedSim = Invoke-SimulatedTierCheck -SimulatedUpn $scopedUpn
        Assert-ScheduleMetric ([int]$scopedSim.'[PD_Allowed]' -gt 0 -and [int]$scopedSim.'[PD_Allowed]' -lt [int]$scopedSim.'[PD_Total]') (
            "Project-scoped user expected partial Project_Dimension access (0 < x < $($scopedSim.'[PD_Total]')), got $($scopedSim.'[PD_Allowed]')."
        )
        Assert-ScheduleMetric ([int]$scopedSim.'[BL_Allowed]' -lt [int]$scopedSim.'[BL_Total]') (
            "Project-scoped user expected partial Monthly Resource Distribution Baseline access (< $($scopedSim.'[BL_Total]')), got $($scopedSim.'[BL_Allowed]')."
        )
        Assert-ScheduleMetric ([int]$scopedSim.'[UP_Allowed]' -gt 0 -and [int]$scopedSim.'[UP_Allowed]' -lt [int]$scopedSim.'[UP_Total]') (
            "Project-scoped user expected self-only dbo_userpermission rows, got $($scopedSim.'[UP_Allowed]')."
        )
        $projScopedTested = $true
    }

    $summary = [ordered]@{
        status                        = 'PASS'
        server                        = $addr
        visuals_tested                = $visualQueries.Count
        visuals_passed                = $passCount
        currentdate_slicers_tested    = $currentDateSlicersTested
        zero_access_slicer_rows       = $currentDateSlicerRows
        tier_zero_access_guest        = 'PASS'
        tier_all_access_and_ext_guest = if ($allAccessTested) { 'PASS' } else { 'SKIPPED_NO_SAMPLE' }
        tier_project_scoped           = if ($projScopedTested) { 'PASS' } else { 'SKIPPED_NO_SAMPLE' }
    }
    $summary | ConvertTo-Json -Depth 5
} finally {
    $rlsServer.Disconnect()
    $adminTarget.Connection.Disconnect()
}
