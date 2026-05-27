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

echo "==> [5] Installing requirements-server.txt (headless Linux subset)"
# requirements.txt has macOS-only deps (pyobjc, sounddevice) that fail on Linux.
# requirements-server.txt is the pure-python subset needed by govori.server.
pip install -r requirements-server.txt --quiet

echo "==> [7.5] Normalizing ~/.config/govori/env for systemd"
# systemd's EnvironmentFile= does NOT accept `export KEY=value` (bash-style).
# Strip the `export ` prefix in place if present.
if [[ -f "$HOME/.config/govori/env" ]] && grep -q '^export ' "$HOME/.config/govori/env"; then
    sed -i 's/^export //' "$HOME/.config/govori/env"
    echo "    stripped 'export' prefix from env file"
else
    echo "    env file already systemd-compatible (or missing)"
fi

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
