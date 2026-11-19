#!/bin/bash
# Memory pass (2026-11-19): waits for Phase 2 to finish, builds the memory-instrumented runners from
# /root/bench/src-mem, then runs every stack once per combination (no counter processes).
set -u
until grep -q PHASE2-DONE /root/bench/phase2.out; do sleep 60; done
echo "MEMPASS-BUILD $(date -u +%H:%M)"
cd /root/bench/src-mem/stacks
for s in c cpp go java rust dotnet node; do bash $s/build.sh > /root/bench/build-mem-$s.log 2>&1 || echo "BUILD-FAILED $s"; done
# python and ruby reuse the venv / gems of the main checkout (same driver versions)
ln -sfn /root/bench/src/stacks/python/venv python/venv
ln -sfn /root/bench/src/stacks/ruby/vendor ruby/vendor
cp /root/bench/src/stacks/ruby/run ruby/run 2>/dev/null
export BENCH_SRC=/root/bench/src-mem
R="python3 /root/bench/src-mem/orchestrator/run.py --results /root/bench/results-mem --repeats 1 --no-counters"
echo "MEMPASS-START $(date -u +%H:%M)"
$R --stacks c-libmysqlclient,c-mariadb-connc,cpp-mysql-connector,cpp-mariadb,rust-mysql,rust-sqlx,go-sql-driver,go-mysql --configs default,tuned
$R --stacks java-connector-j,java-mariadb-j,dotnet-mysqlconnector,dotnet-mysql-data --configs default,tuned
$R --stacks node-mysql2,node-mariadb,node-mysql,php-mysqli,php-pdo-mysql,rb-mysql2,rb-trilogy --configs default,tuned
$R --stacks py-mysqlclient,py-mysql-connector-c,py-mariadb,py-pymysql,py-mysql-connector-pure --configs default
echo "MEMPASS-DONE $(date -u +%H:%M)"
