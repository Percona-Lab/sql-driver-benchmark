#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
export PATH=/opt/node/bin:$PATH
[ -f package.json ] || npm init -y >/dev/null
npm install --no-audit --no-fund mysql2@3.24.6 mariadb@3.5.5 mysql@2.18.1   # versions measured in Phase 2
# Phase 3 frameworks (Prisma pinned to the latest stable 7.x; npm "latest" points at an 8.0 release candidate)
npm install --no-audit --no-fund knex@3.3.0 sequelize@6.37.8 typeorm@1.1.3 reflect-metadata drizzle-orm@0.45.4 \
  @prisma/client@7.10.1 prisma@7.10.1 @prisma/adapter-mariadb@7.10.1
python3 gen_prisma.py
npx prisma generate --schema prisma/schema.prisma
node -v; npm ls --depth=0
