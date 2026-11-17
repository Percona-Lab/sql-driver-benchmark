#!/bin/bash
# dbctl.sh start ps|maria  -> stops the other, starts the requested one, prints PID
case "$1" in
  start)
    if [ "$2" = ps ]; then systemctl stop mariadb-bench; systemctl start mysql; cat /var/run/mysqld/mysqld.pid
    else systemctl stop mysql; systemctl start mariadb-bench; cat /run/mariadb/mariadb.pid; fi ;;
  stop) systemctl stop mysql mariadb-bench ;;
  *) echo "usage: dbctl.sh start ps|maria | stop"; exit 1 ;;
esac
