#!/usr/bin/env bash
set -e

echo "=== Deploying Outreach Command Center ==="

APP_DIR="/opt/outreach"

# 1. Install system prerequisites
echo "[1/5] Installing system packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git curl build-essential

# 2. Setup Python virtual environment
echo "[2/5] Setting up virtual environment..."
cd "$APP_DIR"
if [ ! -d "$APP_DIR/venv" ]; then
    python3 -m venv "$APP_DIR/venv"
fi

"$APP_DIR/venv/bin/pip" install --upgrade pip -q
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q

# 3. Ensure permissions and directories exist
echo "[3/5] Setting up data directories..."
mkdir -p "$APP_DIR/app_data" "$APP_DIR/cookies_files"
chmod -R 755 "$APP_DIR"

# 4. Install systemd service
echo "[4/5] Configuring systemd service..."
cp "$APP_DIR/scripts/outreach.service" /etc/systemd/system/outreach.service
systemctl daemon-reload
systemctl enable outreach

# 5. Start / Restart service
echo "[5/5] Starting outreach service..."
systemctl restart outreach

echo "=== Deployment Complete ==="
systemctl status outreach --no-pager
