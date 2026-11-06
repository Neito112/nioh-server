#!/usr/bin/env bash
# ============================================================
# Ni-Oh Distributed Server — 1-Click Installer (Linux/macOS)
# ============================================================
set -euo pipefail

REPO_URL="https://github.com/Neito112/nioh-server"
INSTALL_DIR="${NIOH_DIR:-$HOME/nioh-server}"
PYTHON_MIN="3.10"
SERVICE_NAME="nioh-server"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERR]${NC}  $*"; exit 1; }

echo -e "${CYAN}"
cat << 'EOF'
╔══════════════════════════════════════════╗
║          Ni-Oh Distributed Server        ║
║          1-Click Installer v1.0          ║
╚══════════════════════════════════════════╝
EOF
echo -e "${NC}"

# ── 1. Kiểm tra Python ──────────────────────────────────────
info "Kiểm tra Python $PYTHON_MIN+..."
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PY_OK=$(python3 -c "import sys; print(1 if sys.version_info >= (3,10) else 0)")
    if [ "$PY_OK" = "1" ]; then
        success "Python $PY_VER đã có"
        PYTHON=python3
    else
        warn "Python $PY_VER quá cũ. Cần 3.10+"
        # Thử python3.10 / python3.11 / python3.12
        for v in python3.12 python3.11 python3.10; do
            if command -v $v &>/dev/null; then
                PYTHON=$v
                success "Dùng $v"
                break
            fi
        done
        [ -z "${PYTHON:-}" ] && error "Hãy cài Python 3.10+ trước khi chạy script này"
    fi
else
    error "Python3 không tìm thấy. Hãy cài Python 3.10+"
fi

# ── 2. Clone / Update repo ──────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Repo đã tồn tại tại $INSTALL_DIR → update..."
    cd "$INSTALL_DIR"
    git pull origin main
else
    info "Đang clone repo về $INSTALL_DIR..."
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# ── 3. Clone xiaozhi-server (upstream) nếu chưa có ─────────
XIAOZHI_DIR="$INSTALL_DIR/xiaozhi-server"
if [ ! -d "$XIAOZHI_DIR" ]; then
    info "Đang clone xiaozhi-esp32-server..."
    git clone --depth=1 https://github.com/xinnan-tech/xiaozhi-esp32-server "$XIAOZHI_DIR/upstream"
    # Copy chỉ phần server
    cp -r "$XIAOZHI_DIR/upstream/main/xiaozhi-server/." "$XIAOZHI_DIR/"
    rm -rf "$XIAOZHI_DIR/upstream"
    success "xiaozhi-server đã sẵn sàng"
fi

# ── 4. Tạo virtualenv + cài dependencies ────────────────────
info "Tạo virtual environment..."
$PYTHON -m venv "$INSTALL_DIR/.venv"
source "$INSTALL_DIR/.venv/bin/activate"

info "Cài Python dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r "$XIAOZHI_DIR/requirements.txt"
pip install --quiet -r "$INSTALL_DIR/requirements.txt"
success "Dependencies đã cài xong"

# ── 5. Thu thập config từ người dùng ────────────────────────
ENV_FILE="$INSTALL_DIR/.env"

collect_config() {
    echo ""
    echo -e "${YELLOW}════════ Cấu hình Ni-Oh Server ════════${NC}"
    
    # API Key (OpenRouter hoặc bất kỳ OpenAI-compatible)
    if [ -z "${NIOH_API_KEY:-}" ]; then
        echo -e "LLM API Key (OpenRouter/OpenAI/etc.):"
        echo -e "  → Lấy tại: ${CYAN}https://openrouter.ai/keys${NC}"
        read -rp "  NIOH_API_KEY: " NIOH_API_KEY
    fi

    # Base URL
    if [ -z "${NIOH_LLM_BASE_URL:-}" ]; then
        read -rp "  LLM Base URL [https://openrouter.ai/api/v1]: " NIOH_LLM_BASE_URL
        NIOH_LLM_BASE_URL="${NIOH_LLM_BASE_URL:-https://openrouter.ai/api/v1}"
    fi

    # Model
    if [ -z "${NIOH_MODEL:-}" ]; then
        read -rp "  Model [deepseek/deepseek-chat]: " NIOH_MODEL
        NIOH_MODEL="${NIOH_MODEL:-deepseek/deepseek-chat}"
    fi

    # GitHub Token cho node sync
    echo ""
    echo -e "${YELLOW}Node Registry (đồng bộ nhiều máy):${NC}"
    echo -e "  Tạo token tại: ${CYAN}https://github.com/settings/tokens${NC}"
    echo -e "  Quyền cần: ${CYAN}gist${NC} (chỉ cần gist scope thôi)"
    read -rp "  GitHub Token (để trống nếu chạy single node): " NIOH_GITHUB_TOKEN

    # Cloudflare domain tùy chỉnh (optional)
    echo ""
    echo -e "${YELLOW}Cloudflare Domain (optional):${NC}"
    echo -e "  Nếu có domain → dùng wss://your.domain.com"
    echo -e "  Nếu không → tự động dùng trycloudflare.com (free, không cần login)"
    read -rp "  Domain (để trống = auto): " NIOH_CF_DOMAIN

    # Node ID tự động
    NIOH_NODE_ID=$(hostname)-$(cat /dev/urandom | tr -dc 'a-z0-9' | head -c 6 2>/dev/null || echo "$(date +%s | tail -c 6)")

    # Ghi vào .env
    cat > "$ENV_FILE" << ENVEOF
# Ni-Oh Server Config — tự động tạo bởi install.sh
# Chỉnh sửa file này để thay đổi cấu hình

# ── LLM Config ──
NIOH_API_KEY=${NIOH_API_KEY}
NIOH_LLM_BASE_URL=${NIOH_LLM_BASE_URL}
NIOH_MODEL=${NIOH_MODEL}

# ── ASR / TTS (optional — để trống = dùng default của xiaozhi) ──
NIOH_ASR_TYPE=
NIOH_ASR_KEY=
NIOH_TTS_TYPE=
NIOH_TTS_KEY=

# ── Node Registry ──
NIOH_GITHUB_TOKEN=${NIOH_GITHUB_TOKEN}
NIOH_GIST_ID=
NIOH_NODE_ID=${NIOH_NODE_ID}

# ── Cloudflare Tunnel ──
NIOH_CF_DOMAIN=${NIOH_CF_DOMAIN}
NIOH_CF_TUNNEL_UUID=

# ── Server Ports ──
NIOH_WS_PORT=8000
NIOH_HTTP_PORT=8003

# ── Firmware OTA ──
NIOH_FIRMWARE_VERSION=2.5.3
NIOH_FIRMWARE_URL=
ENVEOF

    success ".env đã lưu tại $ENV_FILE"
}

if [ ! -f "$ENV_FILE" ]; then
    collect_config
else
    warn ".env đã tồn tại. Muốn cấu hình lại? (y/N)"
    read -rp "  → " RECONFIGURE
    if [[ "${RECONFIGURE,,}" == "y" ]]; then
        collect_config
    fi
fi

# ── 6. Cài systemd service (Linux) ──────────────────────────
install_systemd_service() {
    VENV_PYTHON="$INSTALL_DIR/.venv/bin/python"
    SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
    
    sudo tee "$SERVICE_FILE" > /dev/null << SVCEOF
[Unit]
Description=Ni-Oh Distributed Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$VENV_PYTHON -m server.main
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCEOF

    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE_NAME"
    sudo systemctl start "$SERVICE_NAME"
    success "systemd service '$SERVICE_NAME' đã cài và khởi động"
}

# macOS launchd service
install_launchd_service() {
    PLIST_FILE="$HOME/Library/LaunchAgents/com.nioh.server.plist"
    VENV_PYTHON="$INSTALL_DIR/.venv/bin/python"
    
    cat > "$PLIST_FILE" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.nioh.server</string>
    <key>ProgramArguments</key>
    <array>
        <string>$VENV_PYTHON</string>
        <string>-m</string>
        <string>server.main</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>NIOH_DIR</key>
        <string>$INSTALL_DIR</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$HOME/Library/Logs/nioh-server.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/Library/Logs/nioh-server-err.log</string>
</dict>
</plist>
PLISTEOF

    launchctl load "$PLIST_FILE"
    success "launchd service đã cài tại $PLIST_FILE"
}

if [ "$(uname)" = "Darwin" ]; then
    info "macOS detected → cài launchd service..."
    install_launchd_service
elif [ -d "/etc/systemd" ]; then
    info "Linux systemd detected → cài service..."
    install_systemd_service
else
    warn "Không phát hiện systemd/launchd → chạy thủ công:"
    echo "  cd $INSTALL_DIR && source .venv/bin/activate && python -m server.main"
fi

# ── 7. Tạo shortcut chạy thủ công ───────────────────────────
cat > "$INSTALL_DIR/start.sh" << 'STARTEOF'
#!/usr/bin/env bash
cd "$(dirname "$0")"
source .venv/bin/activate
exec python -m server.main
STARTEOF
chmod +x "$INSTALL_DIR/start.sh"

# ── 8. Done ─────────────────────────────────────────────────
echo ""
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ Ni-Oh Server cài xong!${NC}"
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo ""
echo -e "  Thư mục:    ${CYAN}$INSTALL_DIR${NC}"
echo -e "  Config:     ${CYAN}$ENV_FILE${NC}"
echo -e "  Chạy tay:   ${CYAN}$INSTALL_DIR/start.sh${NC}"
echo ""
echo -e "  Firmware OTA URL của bạn sẽ hiển thị sau khi server khởi động."
echo -e "  Nhập URL đó vào firmware Ni-Oh để kết nối."
echo ""
