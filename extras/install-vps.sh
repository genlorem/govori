#!/usr/bin/env bash
set -euo pipefail

echo "==> [1] Checking environment"
HOSTNAME_NOW=$(hostname 2>/dev/null || echo "unknown")
echo "    hostname: $HOSTNAME_NOW"

echo "==> [2] Checking govori repo"
if [ ! -d /home/gen/Projects/govori/.git ]; then
    echo "ERROR: /home/gen/Projects/govori/.git not found."
    echo "Clone the repo first (private — use your SSH key):"
    echo "  git clone git@github.com:<org>/govori.git /home/gen/Projects/govori"
    exit 1
fi

cd /home/gen/Projects/govori

echo "==> [3] Creating venv"
if [ ! -d .venv ]; then
    python3 -m venv .venv
    echo "    venv created"
else
    echo "    venv already exists"
fi

echo "==> [4] Activating venv and upgrading pip"
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -U pip --quiet

echo "==> [5] Installing requirements.txt"
pip install -r requirements.txt --quiet

echo "==> [6] Installing server deps"
pip install fastapi 'uvicorn[standard]' python-multipart av --quiet

echo "==> [7] Updating requirements.txt with server deps"
for pkg in fastapi "uvicorn[standard]" python-multipart av; do
    if ! grep -qF "$pkg" requirements.txt 2>/dev/null; then
        echo "$pkg" >> requirements.txt
        echo "    added: $pkg"
    fi
done

echo "==> [8] Installing systemd user unit"
mkdir -p ~/.config/systemd/user
cp extras/govori-relay.service ~/.config/systemd/user/govori-relay.service
echo "    unit copied to ~/.config/systemd/user/govori-relay.service"

echo "==> [9] Reloading systemd"
systemctl --user daemon-reload

echo "==> [10] Enabling and starting service"
systemctl --user enable --now govori-relay.service

echo "==> [11] Enabling linger for gen"
loginctl enable-linger gen

echo "==> [12] Waiting for service to start..."
sleep 3
systemctl --user status govori-relay --no-pager

echo "==> [13] Health check"
if curl -sf http://localhost:8765/health; then
    echo ""
    echo "Health check PASSED"
else
    echo "WARNING: health check failed — check logs:"
    echo "  tail -f ~/.config/govori/relay.log"
fi
