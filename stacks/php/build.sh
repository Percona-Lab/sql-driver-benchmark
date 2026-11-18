#!/bin/bash
# mysqli and pdo_mysql ship with the distro PHP (php-mysql); nothing to build. JIT stays at the distro default.
set -euo pipefail
php -v | head -1
php -m | grep -iE "^(mysqli|mysqlnd|pdo_mysql)$"
php -r 'echo "opcache.jit=", ini_get("opcache.jit"), " opcache.enable_cli=", ini_get("opcache.enable_cli"), "\n";'
