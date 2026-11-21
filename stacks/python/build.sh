#!/bin/bash
# One venv with all Python drivers (latest releases), built against Oracle libmysqlclient 9.7 and
# MariaDB Connector/C 3.4 from /opt.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv venv
. venv/bin/activate
pip -q install --upgrade pip
export MYSQLCLIENT_CFLAGS="$(/opt/oracle/usr/bin/mysql_config --cflags)"
export MYSQLCLIENT_LDFLAGS="-L/opt/oracle/usr/lib/x86_64-linux-gnu -Wl,-rpath,/opt/oracle/usr/lib/x86_64-linux-gnu -lmysqlclient"
export MARIADB_CONFIG=/opt/mariadb-connc/bin/mariadb_config
pip -q install --no-binary mysqlclient mysqlclient==2.3.1
pip -q install --no-binary mariadb mariadb==1.1.15
pip -q install pymysql==1.2.4 cryptography pynacl mysql-connector-python==26.10.0   # pynacl: PyMySQL's optional ed25519 support
pip -q install sqlalchemy==2.1.9 django==6.1.3   # Phase 3 frameworks
pip list 2>/dev/null | grep -iE "mysql|maria|crypto|sqlalchemy|django"
python -c "import mysql.connector; print('connector C ext:', mysql.connector.HAVE_CEXT)"
