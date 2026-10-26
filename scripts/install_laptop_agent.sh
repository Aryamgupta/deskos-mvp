#!/usr/bin/env bash
set -e

TARGET_URL="${1:-https://deskos.local}"
AGENT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SERVICE_DIR/deskos-agent.service"

mkdir -p "$SERVICE_DIR"

echo "[DeskOS Agent Installer] Configuring systemd user service..."
echo "  Target Master URL: $TARGET_URL"
echo "  Agent script:      $AGENT_DIR/agent/desk_agent.py"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=DeskOS Workstation Telemetry Agent
After=network.target

[Service]
Type=simple
WorkingDirectory=$AGENT_DIR
ExecStart=/usr/bin/python3 $AGENT_DIR/agent/desk_agent.py "$TARGET_URL"
Restart=always
RestartSec=5s
Environment="DESKOS_MASTER_URL=$TARGET_URL"
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable deskos-agent.service
systemctl --user restart deskos-agent.service

echo "[DeskOS Agent Installer] Service enabled and started successfully!"
echo "Check status with: systemctl --user status deskos-agent.service"

