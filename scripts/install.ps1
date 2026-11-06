# ============================================================
# Ni-Oh Distributed Server — 1-Click Installer (Windows)
# ============================================================
# Chạy: powershell -ExecutionPolicy Bypass -File install.ps1
# ============================================================

$ErrorActionPreference = "Stop"
$REPO_URL = "https://github.com/Neito112/nioh-server"
$INSTALL_DIR = if ($env:NIOH_DIR) { $env:NIOH_DIR } else { "$env:USERPROFILE\nioh-server" }
$SERVICE_NAME = "NiOhServer"

function Write-Info  { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Ok    { param($msg) Write-Host "[OK]   $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err   { param($msg) Write-Host "[ERR]  $msg" -ForegroundColor Red; exit 1 }

Write-Host @"
╔══════════════════════════════════════════╗
║          Ni-Oh Distributed Server        ║
║          1-Click Installer v1.0          ║
╚══════════════════════════════════════════╝
"@ -ForegroundColor Cyan

# ── 1. Kiểm tra Python ──────────────────────────────────────
Write-Info "Kiểm tra Python 3.10+..."
$PYTHON = $null
foreach ($py in @("python", "python3", "py")) {
    try {
        $ver = & $py -c "import sys; print(sys.version_info >= (3,10))" 2>$null
        if ($ver -eq "True") {
            $PYTHON = $py
            $verStr = & $py -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
            Write-Ok "Python $verStr tìm thấy ($py)"
            break
        }
    } catch { }
}

if (-not $PYTHON) {
    Write-Warn "Python 3.10+ không tìm thấy. Đang cài qua winget..."
    try {
        winget install Python.Python.3.12 --accept-source-agreements --accept-package-agreements
        $PYTHON = "python"
        Write-Ok "Python 3.12 đã cài"
    } catch {
        Write-Err "Không cài được Python. Tải tại: https://python.org/downloads"
    }
}

# ── 2. Kiểm tra Git ─────────────────────────────────────────
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Warn "Git không tìm thấy. Đang cài..."
    winget install Git.Git --accept-source-agreements --accept-package-agreements
}

# ── 3. Clone / Update repo ──────────────────────────────────
if (Test-Path "$INSTALL_DIR\.git") {
    Write-Info "Repo đã tồn tại → update..."
    Push-Location $INSTALL_DIR
    git pull origin main
    Pop-Location
} else {
    Write-Info "Clone repo về $INSTALL_DIR..."
    git clone $REPO_URL $INSTALL_DIR
}

# ── 4. Clone xiaozhi-server upstream ────────────────────────
$XIAOZHI_DIR = "$INSTALL_DIR\xiaozhi-server"
if (-not (Test-Path $XIAOZHI_DIR)) {
    Write-Info "Clone xiaozhi-esp32-server..."
    git clone --depth=1 https://github.com/xinnan-tech/xiaozhi-esp32-server "$INSTALL_DIR\_upstream"
    Copy-Item "$INSTALL_DIR\_upstream\main\xiaozhi-server\*" $XIAOZHI_DIR -Recurse -Force
    Remove-Item "$INSTALL_DIR\_upstream" -Recurse -Force
    Write-Ok "xiaozhi-server sẵn sàng"
}

# ── 5. Tạo virtualenv ───────────────────────────────────────
Write-Info "Tạo virtual environment..."
& $PYTHON -m venv "$INSTALL_DIR\.venv"
$VENV_PY = "$INSTALL_DIR\.venv\Scripts\python.exe"
$VENV_PIP = "$INSTALL_DIR\.venv\Scripts\pip.exe"

Write-Info "Cài dependencies..."
& $VENV_PIP install --quiet --upgrade pip
& $VENV_PIP install --quiet -r "$XIAOZHI_DIR\requirements.txt"
& $VENV_PIP install --quiet -r "$INSTALL_DIR\requirements.txt"
Write-Ok "Dependencies đã cài xong"

# ── 6. Thu thập config ──────────────────────────────────────
$ENV_FILE = "$INSTALL_DIR\.env"

function Collect-Config {
    Write-Host ""
    Write-Host "════════ Cấu hình Ni-Oh Server ════════" -ForegroundColor Yellow

    $apiKey = Read-Host "  LLM API Key (OpenRouter/OpenAI) → https://openrouter.ai/keys`n  NIOH_API_KEY"
    
    $baseUrl = Read-Host "  LLM Base URL [https://openrouter.ai/api/v1]"
    if (-not $baseUrl) { $baseUrl = "https://openrouter.ai/api/v1" }
    
    $model = Read-Host "  Model [deepseek/deepseek-chat]"
    if (-not $model) { $model = "deepseek/deepseek-chat" }

    Write-Host ""
    Write-Host "Node Registry (đồng bộ nhiều máy):" -ForegroundColor Yellow
    Write-Host "  Tạo token tại: https://github.com/settings/tokens (scope: gist)" -ForegroundColor Cyan
    $ghToken = Read-Host "  GitHub Token (để trống = single node)"

    Write-Host ""
    Write-Host "Cloudflare Domain (optional):" -ForegroundColor Yellow
    Write-Host "  Để trống = tự động dùng trycloudflare.com (free)" -ForegroundColor Cyan
    $cfDomain = Read-Host "  Domain"

    $nodeId = "$env:COMPUTERNAME-$(Get-Random -Maximum 999999)"

    @"
# Ni-Oh Server Config — tự động tạo bởi install.ps1

# ── LLM Config ──
NIOH_API_KEY=$apiKey
NIOH_LLM_BASE_URL=$baseUrl
NIOH_MODEL=$model

# ── ASR / TTS (optional) ──
NIOH_ASR_TYPE=
NIOH_ASR_KEY=
NIOH_TTS_TYPE=
NIOH_TTS_KEY=

# ── Node Registry ──
NIOH_GITHUB_TOKEN=$ghToken
NIOH_GIST_ID=
NIOH_NODE_ID=$nodeId

# ── Cloudflare Tunnel ──
NIOH_CF_DOMAIN=$cfDomain
NIOH_CF_TUNNEL_UUID=

# ── Server Ports ──
NIOH_WS_PORT=8000
NIOH_HTTP_PORT=8003

# ── Firmware ──
NIOH_FIRMWARE_VERSION=2.5.3
NIOH_FIRMWARE_URL=
"@ | Out-File -FilePath $ENV_FILE -Encoding UTF8

    Write-Ok ".env đã lưu tại $ENV_FILE"
}

if (-not (Test-Path $ENV_FILE)) {
    Collect-Config
} else {
    Write-Warn ".env đã tồn tại."
    $reconfig = Read-Host "Muốn cấu hình lại? (y/N)"
    if ($reconfig -eq "y") { Collect-Config }
}

# ── 7. Cài Windows Service / Task Scheduler ─────────────────
Write-Info "Cài Windows Task Scheduler để tự khởi động..."

$startScript = "$INSTALL_DIR\start.ps1"
@"
Set-Location '$INSTALL_DIR'
`$env:PYTHONPATH = '$INSTALL_DIR'
Get-Content '$ENV_FILE' | ForEach-Object {
    if (`$_ -match '^([^#=]+)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable(`$Matches[1].Trim(), `$Matches[2].Trim(), 'Process')
    }
}
& '$VENV_PY' -m server.main
"@ | Out-File -FilePath $startScript -Encoding UTF8

try {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$startScript`""
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit (New-TimeSpan -Hours 0)
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest
    
    Register-ScheduledTask -TaskName $SERVICE_NAME -Action $action `
        -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    
    Write-Ok "Task Scheduler '$SERVICE_NAME' đã cài (tự chạy khi đăng nhập)"
} catch {
    Write-Warn "Không cài được Task Scheduler: $_"
    Write-Warn "Chạy thủ công bằng: $startScript"
}

# ── 8. Done ─────────────────────────────────────────────────
Write-Host ""
Write-Host "════════════════════════════════════════" -ForegroundColor Green
Write-Host "✓ Ni-Oh Server cài xong!" -ForegroundColor Green
Write-Host "════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host "  Thư mục:    $INSTALL_DIR" -ForegroundColor Cyan
Write-Host "  Config:     $ENV_FILE" -ForegroundColor Cyan
Write-Host "  Chạy tay:   $startScript" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Khởi động ngay?" -ForegroundColor Yellow
$start = Read-Host "  (y/N)"
if ($start -eq "y") {
    Write-Info "Đang khởi động..."
    Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File `"$startScript`"" -WindowStyle Normal
}

