#!/bin/bash
# Two builds of the same runner: Oracle libmysqlclient 9.7 and MariaDB Connector/C 3.4.
set -euo pipefail
cd "$(dirname "$0")"
CFLAGS="-O2 -g -fno-omit-frame-pointer -Wall -Wno-unused-function"
gcc $CFLAGS $(/opt/oracle/usr/bin/mysql_config --cflags) runner.c -o run-libmysqlclient \
  -L/opt/oracle/usr/lib/x86_64-linux-gnu -Wl,-rpath,/opt/oracle/usr/lib/x86_64-linux-gnu -lmysqlclient
gcc $CFLAGS -I/opt/mariadb-connc/include/mariadb runner.c -o run-mariadb-connc \
  -L/opt/mariadb-connc/lib/mariadb -Wl,-rpath,/opt/mariadb-connc/lib/mariadb -lmariadb
ldd run-libmysqlclient | grep -E "mysqlclient|ssl"; ldd run-mariadb-connc | grep -E "mariadb|ssl"
