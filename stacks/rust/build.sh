#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
export PATH=/root/.cargo/bin:$PATH
cargo build --release
cargo build --release   # second pass so build.rs sees the generated Cargo.lock
grep -A1 -E '^name = "(mysql|sqlx)"$' Cargo.lock
# Phase 3 frameworks: Diesel on Oracle libmysqlclient 9.7 (/opt/oracle), SeaORM on sqlx
cd fw
python3 gen_wide.py
export MYSQLCLIENT_LIB_DIR=/opt/oracle/usr/lib/x86_64-linux-gnu MYSQLCLIENT_INCLUDE_DIR=/opt/oracle/usr/include/mysql MYSQLCLIENT_VERSION=9.5.0   # 0.5.3 rejects versions it has no feature flags for even with buildtime_bindgen; bindings still come from the 9.7 headers
dpkg -s libclang-dev >/dev/null 2>&1 || apt-get install -y -q libclang-dev >/dev/null   # bindgen
export RUSTFLAGS="-C link-arg=-Wl,-rpath,/opt/oracle/usr/lib/x86_64-linux-gnu"
cargo build --release
cargo build --release
grep -A1 -E '^name = "(diesel|sea-orm|sqlx)"$' Cargo.lock
ldd target/release/fwrunner | grep -i mysql
