#!/bin/bash
# mysqli and pdo_mysql ship with the distro PHP (php-mysql). Phase 3 frameworks come from Composer (pinned versions).
set -euo pipefail
cd "$(dirname "$0")"
php -v | head -1
php -m | grep -iE "^(mysqli|mysqlnd|pdo_mysql)$"
php -r 'echo "opcache.jit=", ini_get("opcache.jit"), " opcache.enable_cli=", ini_get("opcache.enable_cli"), "\n";'
[ -f composer.json ] || echo '{"require": {}}' > composer.json
COMPOSER_ALLOW_SUPERUSER=1 composer require -q --no-interaction doctrine/dbal:4.6.0 doctrine/orm:3.8.0 illuminate/database:v13.43.0 symfony/cache
python3 gen_entities.py
COMPOSER_ALLOW_SUPERUSER=1 composer show 2>/dev/null | grep -E "^(doctrine/(dbal|orm)|illuminate/database) "
