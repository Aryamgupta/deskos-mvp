
#!/usr/bin/env bash
set -euo pipefail

# Run this script from the DeskOS project directory. Replacing a service from
# another checkout requires the explicit --replace-existing option.
REPLACE_EXISTING=false
if [[ "${1:-}" == "--replace-existing" ]]; then
    REPLACE_EXISTING=true
elif [[ $# -gt 0 ]]; then
    echo "Usage: $0 [--replace-existing]"
    exit 2
fi

PROJECT_DIR="$(pwd)"
SERVICE_NAME="deskos"
PORT="${DESKOS_PORT:-8765}"
HOST="${DESKOS_HOST:-0.0.0.0}"
RUN_USER="$(id -un)"
RUN_GROUP="$(id -gn)"
DATA_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}"
DATA_DIR="${DESKOS_DATA_DIR:-${DATA_ROOT}/deskos}"
GEMINI_ENV_FILE="${DESKOS_GEMINI_ENV_FILE:-$HOME/.config/deskos/gemini.env}"

if [[ ! "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1 || PORT > 65535 )); then
    echo "Error: DESKOS_PORT must be an integer from 1 to 65535."
    exit 2
fi

if [[ ! -f "$PROJECT_DIR/server.py" ]]; then
    echo "Error: server.py not found."
    echo "Run this script from the DeskOS project directory."
    exit 1
fi

if systemctl is-active --quiet "${SERVICE_NAME}"; then
    EXISTING_DIR="$(systemctl show --property=WorkingDirectory --value "${SERVICE_NAME}" 2>/dev/null || true)"
    if [[ -n "$EXISTING_DIR" && "$EXISTING_DIR" != "$PROJECT_DIR" && "$REPLACE_EXISTING" != true ]]; then
        echo "Error: ${SERVICE_NAME} is active from a different checkout: ${EXISTING_DIR}"
        echo "Stop and migrate that installation deliberately, or rerun with --replace-existing."
        echo "This script does not migrate existing application data."
        exit 1
    fi
fi

if [[ -x "$PROJECT_DIR/.venv/bin/python" ]]; then
    PYTHON="$PROJECT_DIR/.venv/bin/python"
else
    PYTHON="$(command -v python3)"
fi

echo "Installing DeskOS systemd service..."
echo "Project: $PROJECT_DIR"
echo "Python:  $PYTHON"
echo "Port:    $PORT"
echo "Host:    $HOST"
echo "Data:    $DATA_DIR"
echo "Gemini environment file: $GEMINI_ENV_FILE (optional; key value is not printed)"

mkdir -p "$DATA_DIR"
chmod 700 "$DATA_DIR"

sudo tee "/etc/systemd/system/${SERVICE_NAME}.service" >/dev/null <<EOF
[Unit]
Description=DeskOS Workstation Dashboard
After=network.target

[Service]
Type=simple
User=${RUN_USER}
Group=${RUN_GROUP}
WorkingDirectory=${PROJECT_DIR}
Environment=DESKOS_HOST=${HOST}
Environment=DESKOS_PORT=${PORT}
Environment=DESKOS_DATA_DIR=${DATA_DIR}
EnvironmentFile=-${GEMINI_ENV_FILE}
ExecStart=${PYTHON} ${PROJECT_DIR}/server.py
Restart=on-failure
RestartSec=3
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now "${SERVICE_NAME}"

echo
echo "DeskOS service installed and started."
echo "Check status: sudo systemctl status deskos"
echo "View logs:    journalctl -u deskos -f"
echo "Dashboard:    http://<laptop-lan-ip>:${PORT}"
