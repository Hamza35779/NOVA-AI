#!/usr/bin/env bash
# CI gate for docs version drift (PR-2/PR-3).
set -euo pipefail
PKG=$(node -p "require('./frontend/package.json').version")
echo "frontend version: $PKG"
rg -n "NOVA-AI-Setup-[0-9.]+" README.md SETUP_AND_USAGE_GUIDE.md docs || true
# fail if old version string still present
if rg -q "1\\.2\\.4" README.md SETUP_AND_USAGE_GUIDE.md; then echo "stale 1.2.4 ref found"; exit 1; fi
# agent count guard — remove number instead of bumping forever:
if rg -qi "eight built-in agents" README.md; then echo "stale agent count"; exit 1; fi
