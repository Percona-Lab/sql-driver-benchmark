#!/bin/bash
# Percona Server 9.7 LTS (apt, port 3306) + MariaDB 12.3 LTS (bintar, port 3307).
# Only one runs at a time during measurements (dbctl.sh start ps|maria).
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
MDB=12.3.4
apt-get update
apt-get -y install curl gnupg lsb-release openssl libaio1t64 libncurses6 numactl

# --- TLS: one CA + ECDSA P-256 server cert for both servers
mkdir -p /etc/dbbench/tls && cd /etc/dbbench/tls
if [ ! -f server-cert.pem ] || ! openssl x509 -in ca.pem -noout -ext keyUsage 2>/dev/null | grep -q "Certificate Sign"; then
  # strict-X.509-clean chain (Python 3.13+ and Java check keyUsage / basicConstraints)
  openssl ecparam -genkey -name prime256v1 -out ca-key.pem
  openssl req -x509 -new -key ca-key.pem -days 3650 -subj "/CN=dbbench-ca" -out ca.pem \
    -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "subjectKeyIdentifier=hash"
  openssl ecparam -genkey -name prime256v1 -out server-key.pem
  openssl req -new -key server-key.pem -subj "/CN=localhost" -out server.csr
  printf "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:localhost,IP:127.0.0.1\nauthorityKeyIdentifier=keyid\nsubjectKeyIdentifier=hash\n" > san.ext
  openssl x509 -req -in server.csr -CA ca.pem -CAkey ca-key.pem -CAcreateserial -days 3650 -extfile san.ext -out server-cert.pem
  chmod 644 *.pem
  # Java truststore with the same CA
  rm -f ca.p12; keytool -importcert -noprompt -alias dbbench-ca -file ca.pem -keystore ca.p12 -storetype PKCS12 -storepass changeit >/dev/null 2>&1 || true
fi

# --- Percona Server 9.7
if ! dpkg -l percona-server-server 2>/dev/null | grep -q ^ii; then
  curl -sO https://repo.percona.com/apt/percona-release_latest.generic_all.deb
  apt-get -y install ./percona-release_latest.generic_all.deb
  percona-release enable-only ps-97-lts release
  apt-get update
  debconf-set-selections <<< "percona-server-server percona-server-server/root-pass password"
  debconf-set-selections <<< "percona-server-server percona-server-server/re-root-pass password"
  apt-get -y install percona-server-server percona-server-client
fi
cat > /etc/mysql/mysql.conf.d/zz-bench.cnf <<CNF
[mysqld]
port=3306
bind-address=127.0.0.1
skip-name-resolve
innodb_buffer_pool_size=16G
innodb_flush_log_at_trx_commit=2
disable_log_bin
max_allowed_packet=256M
ssl_ca=/etc/dbbench/tls/ca.pem
ssl_cert=/etc/dbbench/tls/server-cert.pem
ssl_key=/etc/dbbench/tls/server-key.pem
tls_version=TLSv1.2,TLSv1.3
CNF
mkdir -p /etc/systemd/system/mysql.service.d
printf "[Service]\nCPUAffinity=1 2 3\n" > /etc/systemd/system/mysql.service.d/affinity.conf

# --- MariaDB 12.3 bintar
if [ ! -x /opt/mariadb/bin/mariadbd ]; then
  cd /opt && curl -sL -o mdb.tgz https://downloads.mariadb.org/rest-api/mariadb/$MDB/mariadb-$MDB-linux-systemd-x86_64.tar.gz
  tar xzf mdb.tgz && ln -sfn /opt/mariadb-$MDB-linux-systemd-x86_64 /opt/mariadb && rm mdb.tgz
  id mariadb >/dev/null 2>&1 || useradd -r -s /usr/sbin/nologin mariadb
  mkdir -p /var/lib/mariadb && chown mariadb: /var/lib/mariadb
  /opt/mariadb/scripts/mariadb-install-db --no-defaults --basedir=/opt/mariadb --datadir=/var/lib/mariadb --user=mariadb --auth-root-authentication-method=socket
fi
mkdir -p /etc/mariadb-bench
cat > /etc/mariadb-bench/my.cnf <<CNF
[mariadbd]
basedir=/opt/mariadb
datadir=/var/lib/mariadb
user=mariadb
port=3307
bind-address=127.0.0.1
socket=/run/mariadb/mariadb.sock
pid-file=/run/mariadb/mariadb.pid
plugin-load-add=auth_ed25519
skip-name-resolve
innodb_buffer_pool_size=16G
innodb_flush_log_at_trx_commit=2
skip-log-bin
max_allowed_packet=256M
ssl_ca=/etc/dbbench/tls/ca.pem
ssl_cert=/etc/dbbench/tls/server-cert.pem
ssl_key=/etc/dbbench/tls/server-key.pem
tls_version=TLSv1.2,TLSv1.3
[client]
socket=/run/mariadb/mariadb.sock
CNF
cat > /etc/systemd/system/mariadb-bench.service <<UNIT
[Unit]
Description=MariaDB $MDB (benchmark)
After=network.target
[Service]
Type=notify
User=mariadb
RuntimeDirectory=mariadb
ExecStart=/opt/mariadb/bin/mariadbd --defaults-file=/etc/mariadb-bench/my.cnf
LimitNOFILE=65535
CPUAffinity=1 2 3
TimeoutStartSec=300
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl disable --now mysql || true
systemctl disable mariadb-bench || true
