#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
export PATH=/opt/node/bin:$PATH
[ -f package.json ] || npm init -y >/dev/null
npm install --no-audit --no-fund mysql2@latest mariadb@latest mysql@latest
node -v; npm ls --depth=0
