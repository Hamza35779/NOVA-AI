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
