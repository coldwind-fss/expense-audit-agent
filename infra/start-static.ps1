param([switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$frontendRoot = Join-Path $projectRoot 'frontend'
if (!$SkipBuild) {
    Push-Location $frontendRoot
    try { & npm.cmd run build; if ($LASTEXITCODE) { throw 'Frontend build failed' } } finally { Pop-Location }
}
$nginxRoot = Join-Path $projectRoot '.tools/nginx/nginx-1.31.8'
if (!(Test-Path -LiteralPath "$nginxRoot/nginx.exe")) {
    $archive = Join-Path $projectRoot '.cache/nginx-1.31.8.zip'
    New-Item -ItemType Directory -Force (Split-Path $archive) | Out-Null
    & curl.exe -sS -L --fail --output $archive 'https://nginx.org/download/nginx-1.31.8.zip'
    if ($LASTEXITCODE) { throw 'NGINX download failed' }
    Expand-Archive -LiteralPath $archive -DestinationPath (Split-Path $nginxRoot) -Force
}
$runtimeRoot = Join-Path $env:LOCALAPPDATA 'reimbursement-v2-runtime'
New-Item -ItemType Directory -Force "$runtimeRoot/logs" | Out-Null
New-Item -ItemType Directory -Force "$runtimeRoot/temp" | Out-Null
foreach ($link in @(@{Name='nginx';Target=$nginxRoot},@{Name='web';Target=(Join-Path $frontendRoot 'dist')})) {
    $linkPath = Join-Path $runtimeRoot $link.Name
    if (!(Test-Path -LiteralPath $linkPath)) { New-Item -ItemType Junction -Path $linkPath -Target $link.Target | Out-Null }
    elseif ((Get-Item -LiteralPath $linkPath).Target -ne [IO.Path]::GetFullPath($link.Target)) { throw 'Static runtime junction belongs to another workspace.' }
}
$prefix = $runtimeRoot.Replace('\','/')+'/'
$server = Get-Content -LiteralPath "$frontendRoot/nginx.conf" -Raw
$server = $server.Replace('listen 80;', 'listen 127.0.0.1:18880;').Replace('/usr/share/nginx/html', $prefix+'web').Replace('http://api:8000','http://127.0.0.1:18881')
$config = "pid ${prefix}state/nginx.pid;`nerror_log ${prefix}state/nginx-error.log;`nevents { worker_connections 256; }`nhttp { include ${prefix}nginx/conf/mime.types; access_log off; $server }"
$config | Set-Content -Encoding utf8NoBOM -LiteralPath "$runtimeRoot/state/nginx.conf"
$binary = "$runtimeRoot/nginx/nginx.exe"
& $binary -p $prefix -c 'state/nginx.conf' -t
if ($LASTEXITCODE) { throw 'NGINX configuration check failed' }
$listener = Get-NetTCPConnection -State Listen -LocalPort 18880 -ErrorAction SilentlyContinue
if ($listener) {
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
    $allowedBinaries = @([IO.Path]::GetFullPath($binary), [IO.Path]::GetFullPath("$nginxRoot/nginx.exe"))
    if ($processInfo.ExecutablePath -notin $allowedBinaries) { throw 'Port 18880 is owned by another process; it will not be stopped.' }
    & $binary -p $prefix -c 'state/nginx.conf' -s reload
} else {
    Start-Process -FilePath $binary -ArgumentList '-p',$prefix,'-c','state/nginx.conf' -WorkingDirectory $runtimeRoot -WindowStyle Hidden | Out-Null
}
Write-Output 'Built application: http://127.0.0.1:18880/ (NGINX, API proxy, no dev source server)'
