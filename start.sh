#!/bin/bash
# start.sh — Railway startup script

set -e

echo "============================================"
echo " NQ Bot startup — $(date)"
echo "============================================"

# ── Create config.py from example (reads Railway env vars) ───────────────────
if [ ! -f config.py ]; then
    cp config.example.py config.py
    echo "[setup] Created config.py from config.example.py"
fi

# ── Validate required env vars ────────────────────────────────────────────────
python - <<'EOF'
import os, sys
required = ["TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"]
missing = [k for k in required if not os.environ.get(k) or os.environ.get(k, "").startswith("YOUR_")]
if missing:
    print(f"[setup] WARNING: Missing env vars: {', '.join(missing)}")
    print("[setup] Telegram notifications will be disabled until set in Railway Variables tab")
else:
    print("[setup] All env vars present.")
EOF

# ── Start bot ─────────────────────────────────────────────────────────────────
echo "[setup] Starting NQ bot..."
python bot.py
