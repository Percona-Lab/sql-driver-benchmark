#!/bin/bash
# MySQL Connector/C++ 26.10 (Oracle debs unpacked in /opt/oracle) and MariaDB Connector/C++ (built from source
# against MariaDB Connector/C 3.4 in /opt/mariadb-connc).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
MACPP=1.1.9
if [ ! -f /opt/mariadb-connector-cpp/lib/libmariadbcpp.so ] && [ ! -f /opt/mariadb-connector-cpp/lib64/libmariadbcpp.so ]; then
  cd /usr/local/src && rm -rf mariadb-connector-cpp
  git clone -q --depth 1 -b $MACPP --recurse-submodules https://github.com/mariadb-corporation/mariadb-connector-cpp
  cd mariadb-connector-cpp
  cmake -S . -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_INSTALL_PREFIX=/opt/mariadb-connector-cpp \
    -DCMAKE_CXX_FLAGS="-fno-omit-frame-pointer" -DCMAKE_C_FLAGS="-fno-omit-frame-pointer" -DWITH_UNIT_TESTS=OFF -DCONC_WITH_UNIT_TESTS=OFF >/dev/null
  cmake --build build -j5 >/dev/null && cmake --install build >/dev/null
fi
cd "$HERE"
MLIB=$(dirname "$(find /opt/mariadb-connector-cpp -name 'libmariadbcpp.so' | head -1)")
OLIB=/opt/oracle/usr/lib/x86_64-linux-gnu
MYCPP=$(ls $OLIB/libmysqlcppconn.so.10.* | sed 's/.*\.so\.10\.//')
CXX="g++ -std=c++17 -O2 -g -fno-omit-frame-pointer -Wall -Wno-unused-function -Wno-deprecated-declarations"
$CXX -DMYCPP_VERSION="\"$MYCPP\"" -I/opt/oracle/usr/include -I/opt/oracle/usr/include/mysql-cppconn runner.cpp -o run-mysql-connector \
  -L$OLIB -Wl,-rpath,$OLIB -lmysqlcppconn
$CXX -DMARIADB_CPP -DMACPP_VERSION="\"$MACPP\"" -I/opt/mariadb-connector-cpp/include/mariadb runner.cpp -o run-mariadb \
  -L$MLIB -Wl,-rpath,$MLIB -lmariadbcpp
ls -la run-*
