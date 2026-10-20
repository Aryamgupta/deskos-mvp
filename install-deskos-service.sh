
#!/usr/bin/env bash
set -euo pipefail

# Run this script from the DeskOS project directory.
PROJECT_DIR="$(pwd)"
SERVICE_NAME="deskos"
PORT="8769"
RUN_USER="$(id -un)"
RUN_GROUP="$(id -gn)"

if [[ ! -f "$PROJECT_DIR/server.py" ]]; then
    echo "Error: server.py not found."
    echo "Run this script from the DeskOS project directory."
    exit 1
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

sudo tee "/etc/systemd/system/${SERVICE_NAME}.service" >/dev/null <<EOF
[Unit]
Description=DeskOS Workstation Dashboard
After=network.target

[Service]
Type=simple
User=${RUN_USER}
Group=${RUN_GROUP}
WorkingDirectory=${PROJECT_DIR}
Environment=DESKOS_HOST=0.0.0.0
Environment=DESKOS_PORT=${PORT}
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
echo "Dashboard:    http://192.168.29.66:${PORT}"
