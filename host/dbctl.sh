#!/bin/bash
# dbctl.sh start ps|maria  -> stops the other, starts the requested one, verifies settings, prints mysqld PID
set -e
verify() {  # $1 = client command; refuses to continue if the benchmark config is not in effect
  local got; got=$($1 -N -e "SELECT CONCAT_WS(',', @@innodb_buffer_pool_size DIV 1073741824, @@log_bin, @@innodb_flush_log_at_trx_commit, @@max_allowed_packet DIV 1048576, @@ssl_cert)")
  [ "${got/,OFF,/,0,}" = "16,0,2,256,/etc/dbbench/tls/server-cert.pem" ] || { echo "CONFIG CHECK FAILED: $got" >&2; exit 2; }
}
case "$1" in
  start)
    if [ "$2" = ps ]; then
      update-alternatives --quiet --set my.cnf /etc/mysql/mysql.cnf   # mariadb-common may re-point it
      systemctl stop mariadb-bench; systemctl restart mysql; verify "mysql -uroot"
      # fill the caching_sha2_password cache (cleared by restart) so non-TLS TCP logins use the fast path
      mysql -ubench -pbench -S /var/run/mysqld/mysqld.sock -e "DO 1" 2>/dev/null
      systemctl show -p MainPID --value mysql
    else
      systemctl stop mysql; systemctl restart mariadb-bench; verify "/opt/mariadb/bin/mariadb -uroot -S /run/mariadb/mariadb.sock"
      systemctl show -p MainPID --value mariadb-bench
    fi ;;
  stop) systemctl stop mysql mariadb-bench ;;
  *) echo "usage: dbctl.sh start ps|maria | stop"; exit 1 ;;
esac
