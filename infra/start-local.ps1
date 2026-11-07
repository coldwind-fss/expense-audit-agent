param([switch]$InstallPostgres)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$backendRoot = Join-Path $projectRoot 'backend'
$frontendRoot = Join-Path $projectRoot 'frontend'
$stateRoot = Join-Path $projectRoot 'data/v2'
New-Item -ItemType Directory -Force $stateRoot | Out-Null
$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
$uvPath = if ($uvCommand) { $uvCommand.Source } else { Join-Path $env:USERPROFILE '.local/bin/uv.exe' }
if (!(Test-Path -LiteralPath $uvPath)) { throw 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/' }
Push-Location $backendRoot
try { & $uvPath sync --locked; if ($LASTEXITCODE) { throw 'uv sync failed' } } finally { Pop-Location }
$pythonPath = Join-Path $backendRoot '.venv/Scripts/python.exe'
$pgRoot = Join-Path $projectRoot '.tools/pg18/pgsql'
if (!(Test-Path -LiteralPath "$pgRoot/bin/pg_ctl.exe")) {
    if (!$InstallPostgres) { throw 'Portable PG18 is missing. Run this script with -InstallPostgres, or use infra/compose.yaml.' }
    $archivePath = Join-Path $projectRoot '.cache/postgresql-18.6.zip'
    New-Item -ItemType Directory -Force (Split-Path $archivePath) | Out-Null
    & curl.exe -sS -L --fail --continue-at - --output $archivePath 'https://get.enterprisedb.com/postgresql/postgresql-18.6-1-windows-x64-binaries.zip'
    if ($LASTEXITCODE) { throw 'PostgreSQL download failed; rerun to resume.' }
    $env:REIMBURSEMENT_ARCHIVE = $archivePath
    $env:REIMBURSEMENT_PG_DEST = Join-Path $projectRoot '.tools/pg18'
    & $pythonPath -c 'import os,zipfile; z=zipfile.ZipFile(os.environ["REIMBURSEMENT_ARCHIVE"]); [z.extract(n,os.environ["REIMBURSEMENT_PG_DEST"]) for n in z.namelist() if n.startswith(("pgsql/bin/","pgsql/lib/","pgsql/share/"))]'
    if ($LASTEXITCODE) { throw 'PostgreSQL archive extraction failed' }
}
# ASCII junctions avoid a Windows initdb UTF-8/path issue; all actual data stays in this workspace.
$runtimeRoot = Join-Path $env:LOCALAPPDATA 'reimbursement-v2-runtime'
New-Item -ItemType Directory -Force $runtimeRoot | Out-Null
foreach ($link in @(@{Name='pgsql';Target=$pgRoot}, @{Name='state';Target=$stateRoot})) {
    $linkPath = Join-Path $runtimeRoot $link.Name
    if (!(Test-Path -LiteralPath $linkPath)) { New-Item -ItemType Junction -Path $linkPath -Target $link.Target | Out-Null }
    elseif ((Get-Item -LiteralPath $linkPath).Target -ne [IO.Path]::GetFullPath($link.Target)) { throw "Existing junction $linkPath belongs to a different workspace. No changes made to it." }
}
$pgBin = Join-Path $runtimeRoot 'pgsql/bin'
$cluster = Join-Path $runtimeRoot 'state/pg18'
if (!(Test-Path -LiteralPath "$cluster/PG_VERSION")) {
    & "$pgBin/initdb.exe" -D $cluster --username=reimbursement --auth=trust --encoding=UTF8 --locale=C
    if ($LASTEXITCODE) { throw 'initdb failed' }
}
& "$pgBin/pg_ctl.exe" -D $cluster status | Out-Null
if ($LASTEXITCODE) {
    if (Get-NetTCPConnection -State Listen -LocalPort 15432 -ErrorAction SilentlyContinue) { throw 'Port 15432 belongs to another process; it will not be stopped.' }
    & "$pgBin/pg_ctl.exe" -D $cluster -l "$runtimeRoot/state/pg18.log" -o '-h 127.0.0.1 -p 15432' start
    if ($LASTEXITCODE) { throw 'PostgreSQL startup failed' }
}
foreach ($databaseName in @('reimbursement_v2', 'reimbursement_v2_test')) {
    $exists = & "$pgBin/psql.exe" -h 127.0.0.1 -p 15432 -U reimbursement -d postgres -t -A -c "SELECT 1 FROM pg_database WHERE datname='$databaseName'"
    if ($LASTEXITCODE) { throw 'Isolated PostgreSQL connection failed' }
    if ($exists -ne '1') { & "$pgBin/createdb.exe" -h 127.0.0.1 -p 15432 -U reimbursement $databaseName; if ($LASTEXITCODE) { throw 'Database creation failed' } }
}
Push-Location $backendRoot
try {
    & $pythonPath -m alembic upgrade head
    if ($LASTEXITCODE) { throw 'Application migration failed' }
    & $pythonPath -m reimbursement.bootstrap
    if ($LASTEXITCODE) { throw 'Checkpoint setup failed' }
} finally { Pop-Location }
Push-Location $frontendRoot
try { & npm.cmd ci --silent; if ($LASTEXITCODE) { throw 'npm ci failed' } } finally { Pop-Location }
foreach ($port in @(18881, 5173)) { if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { throw "Port $port is already in use; stop the existing new-version app first. No process was stopped." } }
$processes = @()
$processes += Start-Process -FilePath $pythonPath -ArgumentList '-m','uvicorn','reimbursement.main:app','--host','127.0.0.1','--port','18881','--no-access-log' -WorkingDirectory $backendRoot -RedirectStandardOutput "$stateRoot/api.out.log" -RedirectStandardError "$stateRoot/api.err.log" -WindowStyle Hidden -PassThru
$processes += Start-Process -FilePath $pythonPath -ArgumentList '-m','reimbursement.worker' -WorkingDirectory $backendRoot -RedirectStandardOutput "$stateRoot/worker.out.log" -RedirectStandardError "$stateRoot/worker.err.log" -WindowStyle Hidden -PassThru
$viteScript = Join-Path $frontendRoot 'node_modules/vite/bin/vite.js'
$processes += Start-Process -FilePath (Get-Command node.exe).Source -ArgumentList ('"'+$viteScript+'"'),'--host','127.0.0.1','--port','5173','--strictPort' -WorkingDirectory $frontendRoot -RedirectStandardOutput "$stateRoot/web.out.log" -RedirectStandardError "$stateRoot/web.err.log" -WindowStyle Hidden -PassThru
@{workspace=$projectRoot;process_ids=@($processes.Id)} | ConvertTo-Json | Set-Content -Encoding utf8 "$stateRoot/local-processes.json"
$ready = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    try { $health = Invoke-RestMethod 'http://127.0.0.1:18881/api/v1/health/ready'; if ($health.status -eq 'ready') { $ready=$true; break } } catch { Start-Sleep -Milliseconds 500 }
}
if (!$ready) { throw "API did not become ready. Inspect $stateRoot/api.err.log" }
Write-Output 'Application: http://127.0.0.1:5173/ | API docs: http://127.0.0.1:18881/docs'
Write-Output ('Model mode: '+$health.model_mode+'. Enterprise: local Stub only. Data remains in data/v2; restarting does not reset it.')
