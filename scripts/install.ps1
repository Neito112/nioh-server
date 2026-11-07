# ============================================================
# XiaoZhiVN Distributed Server — 1-Click Installer (Windows)
# ============================================================
# Tự động cài đặt & tạo Shortcut icon "XiaoZhiVN Server" trên Desktop
# Toàn bộ cấu hình được thực hiện 100% trên giao diện trực quan!
# ============================================================

$ErrorActionPreference = "Stop"
$REPO_URL = "https://github.com/Neito112/nioh-server"
$INSTALL_DIR = if ($env:NIOH_DIR) { $env:NIOH_DIR } else { "$env:USERPROFILE\nioh-server" }

function Write-Info  { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Ok    { param($msg) Write-Host "[OK]   $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err   { param($msg) Write-Host "[ERR]  $msg" -ForegroundColor Red; exit 1 }

Write-Host @"
╔══════════════════════════════════════════╗
║         XiaoZhiVN Distributed Server     ║
║          1-Click Installer v2.0          ║
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
    Write-Warn "Python 3.10+ không tìm thấy. Đang tự động cài qua winget..."
    try {
        winget install Python.Python.3.12 --accept-source-agreements --accept-package-agreements
        $PYTHON = "python"
        Write-Ok "Python 3.12 đã cài đặt thành công"
    } catch {
        Write-Err "Không thể tự động cài Python. Vui lòng tải tại: https://python.org/downloads"
    }
}

# ── 2. Kiểm tra Git ─────────────────────────────────────────
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Warn "Git không tìm thấy. Đang cài đặt..."
    winget install Git.Git --accept-source-agreements --accept-package-agreements
}

# ── 3. Clone / Update repo ──────────────────────────────────
if (Test-Path "$INSTALL_DIR\.git") {
    Write-Info "Repo đã tồn tại → Đồng bộ bản mới nhất..."
    Push-Location $INSTALL_DIR
    git pull origin master
    Pop-Location
} else {
    Write-Info "Tải mã nguồn XiaoZhiVN Server về $INSTALL_DIR..."
    git clone $REPO_URL $INSTALL_DIR
}

# ── 4. Tạo virtualenv & cài dependencies ────────────────────
Write-Info "Chuẩn bị môi trường Python..."
if (-not (Test-Path "$INSTALL_DIR\.venv")) {
    & $PYTHON -m venv "$INSTALL_DIR\.venv"
}
$VENV_PIP = "$INSTALL_DIR\.venv\Scripts\pip.exe"
$VENV_PY = "$INSTALL_DIR\.venv\Scripts\python.exe"

Write-Info "Cài đặt thư viện cần thiết (duckduckgo, yt-dlp, aiohttp...)..."
& $VENV_PIP install --quiet --upgrade pip
& $VENV_PIP install --quiet -r "$INSTALL_DIR\requirements.txt"
Write-Ok "Đã cài đặt toàn bộ thư viện cần thiết"

# ── 5. Tạo file .env mặc định nếu chưa có ───────────────────
$ENV_FILE = "$INSTALL_DIR\.env"
if (-not (Test-Path $ENV_FILE)) {
    @"
NIOH_HOST_ACCOUNT=admin@nioh.local
NIOH_LLM_PROVIDER=openrouter
NIOH_LLM_BASE_URL=https://openrouter.ai/api/v1
NIOH_API_KEY=
NIOH_MODEL=deepseek/deepseek-chat
NIOH_GITHUB_TOKEN=
NIOH_CF_DOMAIN=
NIOH_WS_PORT=8000
NIOH_HTTP_PORT=8003
"@ | Out-File -FilePath $ENV_FILE -Encoding UTF8
    Write-Ok "Khởi tạo file cấu hình mặc định (Quản lý trực tiếp từ UI)"
}

# ── 6. Tạo Desktop Shortcut với Icon chuyên nghiệp ──────────
Write-Info "Tạo Shortcut 'XiaoZhiVN Server' trên màn hình Desktop..."
try {
    $desktopPath = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = "$desktopPath\XiaoZhiVN Server.lnk"
    $wscriptPath = "$env:SystemRoot\System32\wscript.exe"
    $vbsPath = "$INSTALL_DIR\run_silent.vbs"
    $iconPath = "$INSTALL_DIR\assets\icon.ico"

    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut($shortcutPath)
    $Shortcut.TargetPath = $wscriptPath
    $Shortcut.Arguments = "`"$vbsPath`""
    $Shortcut.WorkingDirectory = $INSTALL_DIR
    if (Test-Path $iconPath) {
        $Shortcut.IconLocation = "$iconPath,0"
    } else {
        $Shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,14"
    }
    $Shortcut.Description = "XiaoZhiVN Server Engine & Control Center"
    $Shortcut.Save()
    Write-Ok "Đã tạo Icon 'XiaoZhiVN Server' ngay trên Desktop của bạn!"
} catch {
    Write-Warn "Không thể tạo Shortcut Desktop: $_"
}

# ── 7. Hoàn tất & Khởi chạy ngay ─────────────────────────────
Write-Host ""
Write-Host "═════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "   ✓ CÀI ĐẶT THÀNH CÔNG XIAOZHIVN SERVER ENGINE!" -ForegroundColor Green
Write-Host "═════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host "  * Bạn KHÔNG CẦN sửa file code hay cấu hình thủ công." -ForegroundColor Cyan
Write-Host "  * Chỉ cần nhấp đúp vào Icon 'XiaoZhiVN Server' trên Desktop." -ForegroundColor Cyan
Write-Host "  * Toàn bộ cài đặt (API Key, Model, Mạng...) nằm ngay trên giao diện!" -ForegroundColor Cyan
Write-Host ""

# Tự động kích hoạt Dashboard ngay sau khi cài
Write-Info "Đang mở giao diện XiaoZhiVN Server Control Center..."
Start-Process "wscript.exe" -ArgumentList "`"$INSTALL_DIR\run_silent.vbs`""
