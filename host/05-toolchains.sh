#!/bin/bash
# Language runtimes, client libraries and profilers. Versions are recorded in /root/bench/versions.txt.
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
GO=1.27.4; NODE=v26.13.1; RUBY=4.0.9; ASPROF=4.6; RBSPY=v0.55.0; MYSQLAPT=0.8.40-1

apt-get update
apt-get -y install build-essential cmake pkg-config git unzip zip jq libssl-dev zlib1g-dev libyaml-dev \
  libffi-dev libreadline-dev libgdbm-dev libjemalloc-dev \
  openjdk-25-jdk maven python3 python3-dev python3-venv \
  php-cli php-mysql php-dev php-xml php-mbstring composer \
  dotnet-sdk-10.0 \
  unixodbc unixodbc-dev odbc-mariadb libdbi-perl libdbd-mysql-perl libdbd-mariadb-perl cpanminus \
  libmariadb-dev \
  linux-tools-generic linux-tools-$(uname -r) bpftrace bpfcc-tools heaptrack

# Oracle MySQL 9.7 LTS client library + Connector/C++ + Connector/ODBC (only client packages from this repo)
if ! apt-cache policy | grep -q repo.mysql.com; then
  curl -sLO https://repo.mysql.com/apt/ubuntu/pool/mysql-apt-config/m/mysql-apt-config/mysql-apt-config_${MYSQLAPT}_all.deb
  echo "mysql-apt-config mysql-apt-config/select-server select mysql-9.7-lts" | debconf-set-selections
  echo "mysql-apt-config mysql-apt-config/select-tools select Enabled" | debconf-set-selections
  dpkg -i mysql-apt-config_${MYSQLAPT}_all.deb
  # never take server packages from Oracle's repo (Percona Server is installed from Percona's)
  printf "Package: mysql-server* mysql-community-server* mysql-client* mysql-community-client*\nPin: origin repo.mysql.com\nPin-Priority: -1\n" > /etc/apt/preferences.d/no-oracle-server
  apt-get update
fi
apt-get -y install libmysqlclient-dev libmysqlcppconnx2 libmysqlcppconn-dev mysql-connector-odbc || \
  apt-get -y install libmysqlclient-dev

# Go, Node (official tarballs: newer than the distro)
[ -x /opt/go/bin/go ] || { curl -sL https://go.dev/dl/go$GO.linux-amd64.tar.gz | tar xz -C /opt; }
[ -x /opt/node/bin/node ] || { curl -sL https://nodejs.org/dist/$NODE/node-$NODE-linux-x64.tar.xz | tar xJ -C /opt && ln -sfn /opt/node-$NODE-linux-x64 /opt/node; }
# Ruby from source (distro has 3.3), with frame pointers + YJIT for profiling
if [ ! -x /opt/ruby/bin/ruby ]; then
  apt-get -y install rustc   # YJIT build dependency
  cd /usr/local/src && curl -sL https://cache.ruby-lang.org/pub/ruby/${RUBY%.*}/ruby-$RUBY.tar.gz | tar xz
  cd ruby-$RUBY && ./configure --prefix=/opt/ruby --enable-yjit --disable-install-doc cflags="-fno-omit-frame-pointer" >/dev/null
  make -j5 >/dev/null && make install >/dev/null
fi
# Rust (rustup stable)
[ -x /root/.cargo/bin/cargo ] || { curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal; }

cat > /etc/profile.d/dbbench.sh <<'EOF'
export PATH=/opt/go/bin:/root/go/bin:/opt/node/bin:/opt/ruby/bin:/root/.cargo/bin:/opt/tools/bin:$PATH
export DOTNET_CLI_TELEMETRY_OPTOUT=1
EOF
. /etc/profile.d/dbbench.sh

# Profilers
mkdir -p /opt/tools/bin
[ -d /opt/tools/async-profiler ] || { curl -sL https://github.com/async-profiler/async-profiler/releases/download/v$ASPROF/async-profiler-$ASPROF-linux-x64.tar.gz | tar xz -C /opt/tools && ln -sfn /opt/tools/async-profiler-$ASPROF-linux-x64 /opt/tools/async-profiler; }
[ -x /opt/tools/bin/rbspy ] || { curl -sL https://github.com/rbspy/rbspy/releases/download/$RBSPY/rbspy-x86_64-unknown-linux-musl.tar.gz | tar xz -C /opt/tools/bin && mv /opt/tools/bin/rbspy* /opt/tools/bin/rbspy 2>/dev/null || true; }
[ -d /opt/tools/FlameGraph ] || git clone -q --depth 1 https://github.com/brendangregg/FlameGraph /opt/tools/FlameGraph
[ -x /opt/tools/bin/phpspy ] || { cd /usr/local/src && rm -rf phpspy && git clone -q --depth 1 https://github.com/adsr/phpspy && cd phpspy && make >/dev/null && cp phpspy /opt/tools/bin/; }
python3 -m venv /opt/tools/pyprof && /opt/tools/pyprof/bin/pip -q install py-spy memray && ln -sfn /opt/tools/pyprof/bin/py-spy /opt/tools/bin/py-spy && ln -sfn /opt/tools/pyprof/bin/memray /opt/tools/bin/memray
dotnet tool install --tool-path /opt/tools/bin dotnet-trace >/dev/null 2>&1 || true
dotnet tool install --tool-path /opt/tools/bin dotnet-counters >/dev/null 2>&1 || true

# Record versions
mkdir -p /root/bench
{
  echo "kernel $(uname -r)"; lsb_release -ds
  gcc --version | head -1; java -version 2>&1 | head -1; mvn -v | head -1; python3 --version
  go version; echo "node $(node -v)"; php -v | head -1; ruby -v; dotnet --version | sed 's/^/dotnet /'
  rustc --version; perl -v | sed -n 2p
  echo "libmysqlclient $(mysql_config --version 2>/dev/null)"; echo "libmariadb $(mariadb_config --version 2>/dev/null)"
  dpkg-query -W -f '${Package} ${Version}\n' libmysqlcppconnx2 libmysqlcppconn-dev mysql-connector-odbc odbc-mariadb libdbd-mysql-perl libdbd-mariadb-perl 2>/dev/null
  perf --version; bpftrace --version; echo "async-profiler $ASPROF"; /opt/tools/bin/py-spy --version
} > /root/bench/versions.txt 2>&1
cat /root/bench/versions.txt
