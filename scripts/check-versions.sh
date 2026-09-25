#!/usr/bin/env bash
# CI gate for docs version drift (PR-2/PR-3).
set -euo pipefail
# Ripgrep is expected in CI images but not every dev machine; the usages
# below map onto grep -E (-r so directory args like `docs` recurse like rg).
if ! command -v rg >/dev/null 2>&1; then
  rg() { grep -r -E "$@"; }
fi
PKG=$(node -p "require('./frontend/package.json').version")
echo "frontend version: $PKG"
rg -n "NOVA-AI-Setup-[0-9.]+" README.md SETUP_AND_USAGE_GUIDE.md docs || true
# fail if old version string still present
if rg -q "1\\.2\\.6" README.md SETUP_AND_USAGE_GUIDE.md; then echo "stale 1.2.6 ref found"; exit 1; fi
# agent count guard — remove number instead of bumping forever:
if rg -qi "eight built-in agents" README.md; then echo "stale agent count"; exit 1; fi

# Installer one-liner URLs must resolve. The GitHub Pages copies have gone
# stale (404) before; the raw.githubusercontent URLs are the canonical,
# always-current source. Also fail if the dead Pages URLs creep back in.
SH_URL="https://raw.githubusercontent.com/Hamza35779/NOVA-AI/main/scripts/install/install.sh"
PS1_URL="https://raw.githubusercontent.com/Hamza35779/NOVA-AI/main/deploy/windows/install.ps1"
for url in "$SH_URL" "$PS1_URL"; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -L "$url")
  if [ "$code" != "200" ]; then echo "installer URL unreachable (HTTP $code): $url"; exit 1; fi
done
if grep -rq --exclude=check-versions.sh "hamza35779.github.io/NOVA-AI/install" README.md SETUP_AND_USAGE_GUIDE.md docs scripts deploy 2>/dev/null; then
  echo "dead GitHub Pages installer URL referenced — use raw.githubusercontent.com URLs"
  exit 1
fi
echo "installer URLs: OK"

# Release-version consistency (#launch-audit): the Windows setup installer
# pins its version in the Inno Setup script and the Tauri bundle carries its
# own — a forgotten bump ships artifacts reporting the wrong version (this
# happened: 1.2.4 installers shipped during the 1.2.5 release). Fail on
# drift instead of trusting memory.
ISS_FILE="deploy/windows/nova-ai-setup.iss"
ISS_VERSION=$(sed -n 's/^#define MyAppVersion "\(.*\)"/\1/p' "$ISS_FILE")
if [ "$ISS_VERSION" != "$PKG" ]; then
  echo "version drift: frontend/package.json=$PKG but $ISS_FILE defines $ISS_VERSION"
  exit 1
fi
TAURI_VERSION=$(node -p "require('./frontend/src-tauri/tauri.conf.json').version")
if [ "$TAURI_VERSION" != "$PKG" ]; then
  echo "version drift: frontend/package.json=$PKG but frontend/src-tauri/tauri.conf.json defines $TAURI_VERSION"
  exit 1
fi
# Installer-filename drift needs more than a string grep: docs must only
# reference assets a workflow actually publishes (version match, existence on
# the v$PKG release, no phantom NOVA-AI-Setup-<version>.exe in current-claim
# docs). This subsumes any plain doc-name grep.
PY="python3"
command -v "$PY" >/dev/null 2>&1 || PY="python"
"$PY" scripts/check-doc-assets.py
echo "release versions: OK ($PKG across package.json, tauri.conf.json, setup.iss, docs)"
