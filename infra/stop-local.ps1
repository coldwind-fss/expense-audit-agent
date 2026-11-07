$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$stateFile = Join-Path $projectRoot 'data/v2/local-processes.json'
if (!(Test-Path -LiteralPath $stateFile)) { Write-Output 'No recorded local processes.'; exit 0 }
$state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
if ($state.workspace -ne $projectRoot) { throw 'Process record belongs to another workspace.' }
$inventory = @(Get-CimInstance Win32_Process)
$ownedIds = @($state.process_ids)
foreach ($candidate in $inventory) { if ($candidate.ParentProcessId -in $ownedIds) { $ownedIds += $candidate.ProcessId } }
foreach ($processId in $ownedIds | Select-Object -Unique) {
    $processInfo = $inventory | Where-Object ProcessId -eq $processId
    if ($processInfo -and ($processInfo.CommandLine -match 'reimbursement.main:app|reimbursement.worker' -or $processInfo.CommandLine.Contains((Join-Path $projectRoot 'frontend/node_modules/vite/bin/vite.js')))) {
        Stop-Process -Id $processId -ErrorAction SilentlyContinue
    }
}
$runtimeRoot = Join-Path $env:LOCALAPPDATA 'reimbursement-v2-runtime'
if ((Test-Path -LiteralPath "$runtimeRoot/state/nginx.pid") -and (Test-Path -LiteralPath "$runtimeRoot/nginx/nginx.exe")) {
    $nginxPid = [int](Get-Content -LiteralPath "$runtimeRoot/state/nginx.pid")
    $nginxInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $nginxPid"
    $nginxBinary = "$runtimeRoot/nginx/nginx.exe"
    $expectedBinary = [IO.Path]::GetFullPath((Join-Path $projectRoot '.tools/nginx/nginx-1.31.8/nginx.exe'))
    if ($nginxInfo -and $nginxInfo.ExecutablePath -in @([IO.Path]::GetFullPath($nginxBinary),$expectedBinary)) {
        & $nginxBinary -p ($runtimeRoot.Replace('\','/')+'/') -c 'state/nginx.conf' -s quit
    }
}
Write-Output 'Stopped the recorded new-version API, Worker and web processes. PostgreSQL and data are retained.'
