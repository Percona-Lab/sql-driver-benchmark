#!/usr/bin/env python3
"""Write reports/phase1.md and reports/phase2.md from the aggregated results.
Numbers in the prose are looked up from the data, so text and tables cannot drift apart.

usage: build_reports.py summary.json summary-mem.json   (report.py output of the timed runs and of the memory pass)
"""
import json, subprocess, sys

SUM, MEM = sys.argv[1], sys.argv[2]
rows = {(r["server"], r["stack"], r["test"], r["variant"], r["config"]): r for r in json.load(open(SUM)) if "cpu_ns_op" in r}
mem = {(r["server"], r["stack"], r["test"], r["variant"], r["config"]): r for r in json.load(open(MEM)) if "mem_work_kb" in r}
DIV = {"T0": 1e6, "T1": 1e3, "T2": 1e3, "T3": 1, "T4": 1, "T5": 1, "T6": 1e3}


def fmt(v):
    return f"{v:,.0f}" if v >= 100 else f"{v:.3g}"


def cpu(stack, test, variant, server="ps", config="default"):
    return fmt(rows[(server, stack, test, variant, config)]["cpu_ns_op"] / DIV[test])


def mb(stack, test, variant, field="mem_work_kb", server="ps", config="default"):
    return fmt(max(0, mem[(server, stack, test, variant, config)][field]) / 1024)


DISCLOSURE = ("> **AI-generated results.** This benchmark was designed, run and analyzed with an AI assistant (Claude). "
              "Results and findings have been spot-checked by a person, but not every number and explanation has been verified "
              "in detail, and some may be wrong. The code and raw data are published so you can verify anything here; please "
              "report problems as [issues](https://github.com/Percona-Lab/sql-driver-benchmark/issues).\n")

COMMON = """All numbers are **client CPU per operation** (user + kernel, whole process, GC and JIT threads included), median of 5
fresh processes, in steady state, shown as **Percona / MariaDB**; memory tables come from a separate memory pass.
Interactive version: https://percona-lab.github.io/sql-driver-benchmark/ · Method: [SPEC.md](../SPEC.md) ·
host pitfalls we found and fixed: [measurement-pitfalls](../docs/measurement-pitfalls.md).

**Memory measures.** *Memory for the work* is the peak resident memory during a measured iteration minus the memory at its
start. It reads near zero when a runtime keeps freed memory between iterations (Python's allocator, garbage-collected heaps),
so for those *memory growth* is the better measure: the highest peak minus the memory right after connecting, before warm-up.
Growth of JIT/GC runtimes includes heap the runtime chose to keep (the JVM sizes its heap up to a quarter of RAM by default).
"""


TUNED = json.load(open("reports/tuned.json"))


def tuned_section(prefixes):
    lines = [f"- **{k}**: {v}" for k, v in TUNED.items() if not k.startswith("_") and any(k.startswith(p) for p in prefixes.split(","))]
    return ("## What \"tuned\" changes\n\nEvery \"tuned\" result uses exactly these changes from the library defaults "
            "(server settings are never tuned). Stacks not listed have no tuned configuration.\n\n" + "\n".join(lines) + "\n\n")


def tables(stacks, tests="T1,T2,T3,T4,T5,T6"):
    out = subprocess.run(["python3", "orchestrator/tables.py", SUM, "--stacks", stacks, "--tests", tests],
                         capture_output=True, text=True, check=True).stdout
    for metric in ("mem_work_kb", "mem_growth_kb"):
        out += subprocess.run(["python3", "orchestrator/tables.py", MEM, "--stacks", stacks, "--tests", "T3,T4,T5,T6",
                               "--metric", metric], capture_output=True, text=True, check=True).stdout
    return out


P1 = "c-,go-,java-,py-"
p1 = f"""# Phase 1 report — C, Go, Java, Python

{DISCLOSURE}
Run: 2026-11-17 → 2026-11-21 on one bare-metal host (EPYC 4245P, client alone on an isolated core, 3.9 GHz fixed), Percona
Server 9.7.2-3 and MariaDB 12.3.4 with identical configuration. Java was rerun with adaptive warm-up and PyMySQL with TLS
actually disabled; see "Corrections".

{COMMON}
## Corrections to the first version of this report

- **PyMySQL was not slow to connect.** PyMySQL negotiates TLS by default whenever the server offers it, and the first runner
  did not turn that off, so every non-TLS PyMySQL result ran over TLS. With `ssl_disabled=True` a plain connect costs
  **{cpu('py-pymysql','T1','tcp')} µs**; with its TLS default it costs {cpu('py-pymysql','T1','tls')} µs. The orchestrator
  now fails any result whose negotiated TLS state differs from the intended one.
- **Java numbers were not steady state.** A fixed 5-iteration warm-up left the JIT compiler working during measured
  iterations (26–45% spread within a process). Runners now warm up until three iterations agree within 5%; Java numbers
  moved by up to 60% (Connector/J app-built bulk insert {cpu('java-connector-j','T6','sqltext')} µs per 1,000 rows, previously
  292). The "unexplained Java JSON" result was an artifact of this and is gone.

## Key findings

**Connections**
- Plain TCP connect: libmysqlclient {cpu('c-libmysqlclient','T1','tcp')} µs, go-sql-driver {cpu('go-sql-driver','T1','tcp')},
  MariaDB Connector/Python {cpu('py-mariadb','T1','tcp')}, MariaDB Connector/J {cpu('java-mariadb-j','T1','tcp')},
  Connector/J {cpu('java-connector-j','T1','tcp')}.
- **TLS without a CA file costs {cpu('c-libmysqlclient','T1','tls')} µs per connect in libmysqlclient** (vs
  {cpu('c-libmysqlclient','T1','tls-verify')} µs with a CA file): it loads and parses the full system CA bundle on every
  connection. The same holds for every driver built on libmysqlclient or MariaDB Connector/C.
- **MariaDB 12.3 forces TLS key exchange to ECDH P-521; Percona Server uses P-256.** go-sql-driver needs
  {cpu('go-sql-driver','T1','tls')} µs per TLS connect to Percona and {cpu('go-sql-driver','T1','tls','maria')} µs to MariaDB.
- Go has the cheapest TLS here: go-sql-driver verified TLS {cpu('go-sql-driver','T1','tls-verify')} µs; Connector/J
  {cpu('java-connector-j','T1','tls-verify')} µs.

**Point selects**
- libmysqlclient {cpu('c-libmysqlclient','T2','literal')} µs, MariaDB Connector/J {cpu('java-mariadb-j','T2','literal')},
  go-sql-driver {cpu('go-sql-driver','T2','literal')}, mysqlclient {cpu('py-mysqlclient','T2','literal')}, PyMySQL
  {cpu('py-pymysql','T2','literal')}, pure-Python mysql-connector {cpu('py-mysql-connector-pure','T2','literal')}.
- **go-sql-driver's parameterized query: {cpu('go-sql-driver','T2','param')} µs by default** (prepare + execute + close per
  call), {cpu('go-sql-driver','T2','param',config='tuned')} µs with `interpolateParams`.

**Large result sets (1M ints, buffered text protocol)**
- **MariaDB Connector/J {cpu('java-mariadb-j','T3','text-buffered')} ns/row, cheaper than libmysqlclient
  ({cpu('c-libmysqlclient','T3','text-buffered')} ns):** it keeps the raw bytes and converts only on `getInt()`, while
  libmysqlclient copies every row into its own structures (310 vs 736 instructions per row). Connector/J
  {cpu('java-connector-j','T3','text-buffered')} ns.
- **libmysqlclient over TLS: {cpu('c-libmysqlclient','T3','text-buffered+tls')} ns/row** (two `SSL_read` calls per row);
  MariaDB Connector/C {cpu('c-mariadb-connc','T3','text-buffered+tls')} ns.
- Python: MariaDB Connector/Python {cpu('py-mariadb','T3','text-buffered')} ns/row, mysqlclient
  {cpu('py-mysqlclient','T3','text-buffered')}, PyMySQL {cpu('py-pymysql','T3','text-buffered')}, pure-Python mysql-connector
  {cpu('py-mysql-connector-pure','T3','text-buffered')}.
- Memory for the buffered result: libmysqlclient {mb('c-libmysqlclient','T3','text-buffered')} MB, mysqlclient
  {mb('py-mysqlclient','T3','text-buffered')} MB, pure-Python mysql-connector {mb('py-mysql-connector-pure','T3','text-buffered')} MB;
  streaming needs almost none. Process growth: libmysqlclient {mb('c-libmysqlclient','T3','text-buffered','mem_growth_kb')} MB,
  Connector/J {mb('java-connector-j','T3','text-buffered','mem_growth_kb')} MB (mostly default JVM heap sizing).

**Large values**
- **MySQL/Percona Server converts JSON from binary to text on every read** (~13× the server CPU of the same bytes as
  LONGBLOB, ~10% larger output); most clients spend more CPU per KB reading it than from MariaDB. A storage trade-off,
  not analyzed further. MariaDB Connector/Python returns Percona's JSON as raw bytes (no decoding), so its JSON figures
  are not comparable.

**Bulk insert (1,000-row statements)**
- Connector/J `executeBatch()`: {cpu('java-connector-j','T6','batch')} µs per 1,000 rows on defaults,
  {cpu('java-connector-j','T6','batch',config='tuned')} µs with `rewriteBatchedStatements`.
- MariaDB's bulk protocol: MariaDB Connector/Python `executemany` {cpu('py-mariadb','T6','batch','maria')} µs on MariaDB,
  {cpu('py-mariadb','T6','batch')} µs on Percona (one execute per row).

""" + tuned_section(P1) + """## Tables

Superscript numbers mark results with a note; the notes follow each table.
""" + tables(P1)

P2 = "cpp-,rust-,dotnet-,node-,php-,rb-"
p2 = f"""# Phase 2 report — C++, Rust, .NET, Node.js, PHP, Ruby

{DISCLOSURE}
Run: 2026-11-18 → 2026-11-21, same host, servers and method as [Phase 1](phase1.md). JIT runtimes (.NET, Node.js, Ruby YJIT)
were measured with adaptive warm-up (until three iterations agree within 5%). Drivers: MySQL Connector/C++ 26.10, MariaDB
Connector/C++ 1.1.9, Rust `mysql` 28.0.4 and `sqlx` 0.9.1, MySqlConnector 3.0.0 and MySql.Data 26.10.0, Node mysql2 3.24.6,
mariadb 3.5.5 and mysql 2.18.1, PHP 8.5 mysqli and PDO_MySQL (mysqlnd), Ruby mysql2 0.5.7 and trilogy 2.13.3.

{COMMON}
For comparison, libmysqlclient (C) on Percona: plain connect {cpu('c-libmysqlclient','T1','tcp')} µs, point select
{cpu('c-libmysqlclient','T2','literal')} µs, 1M buffered rows {cpu('c-libmysqlclient','T3','text-buffered')} ns/row.

## Key findings

- **PHP is as cheap as C for connections and point selects.** mysqli: plain connect {cpu('php-mysqli','T1','tcp')} µs,
  point select {cpu('php-mysqli','T2','literal')} µs (mysqlnd is C inside PHP). Row-heavy work costs more:
  {cpu('php-mysqli','T3','text-buffered')} ns/row on defaults, {cpu('php-mysqli','T3','text-buffered',config='tuned')} with
  numeric arrays and native types.
- **Oracle's MySql.Data costs several times MySqlConnector:** plain connect {cpu('dotnet-mysql-data','T1','tcp')} vs
  {cpu('dotnet-mysqlconnector','T1','tcp')} µs, point select {cpu('dotnet-mysql-data','T2','literal')} vs
  {cpu('dotnet-mysqlconnector','T2','literal')} µs, streamed rows {cpu('dotnet-mysql-data','T3','text-streamed')} vs
  {cpu('dotnet-mysqlconnector','T3','text-streamed')} ns/row. MySql.Data also cannot verify a server against a CA file
  without a client certificate.
- **Rust: cheapest TLS and near-C binary decoding.** The `mysql` crate: verified TLS connect
  {cpu('rust-mysql','T1','tls-verify')} µs (rustls), wide mixed-type binary rows {cpu('rust-mysql','T4','mix-binary')} ns/cell.
  `sqlx` is slower on large results ({cpu('rust-sqlx','T3','text-buffered')} ns/row vs {cpu('rust-mysql','T3','text-buffered')}).
  The `mysql` crate ships without TLS unless a TLS feature is enabled, and by default silently switches 127.0.0.1
  connections to the Unix socket (`prefer_socket`).
- **Row format matters in scripting languages.** Returning rows as arrays instead of objects/hashes: Node mysql2
  {cpu('node-mysql2','T3','text-buffered')} → {cpu('node-mysql2','T3','text-buffered',config='tuned')} ns/row, Ruby trilogy
  {cpu('rb-trilogy','T3','text-buffered')} → {cpu('rb-trilogy','T3','text-buffered',config='tuned')} ns/row.
- **Ruby mysql2's prepared-statement streaming costs {cpu('rb-mysql2','T3','binary-streamed')} ns/row**, about 20× its text
  path ({cpu('rb-mysql2','T3','text-streamed')}).
- **Ruby mysql2 tuned (`as: :array, cache_rows: false`) runs out of memory on 100 KB documents**: past the 8 GB client cap on
  both servers (before the cap existed it pushed the host into the kernel OOM killer twice). Unfreed results hold C buffers
  that Ruby's garbage collector does not account for.
- **Node connects slowly:** mysql2 {cpu('node-mysql2','T1','tcp')} µs, mariadb {cpu('node-mariadb','T1','tcp')} µs per plain
  connect. The legacy `mysql` package cannot authenticate with `caching_sha2_password`, so it only works against MariaDB here.
- **C++:** MySQL Connector/C++ point select {cpu('cpp-mysql-connector','T2','literal')} µs; MariaDB Connector/C++'s
  4,000-placeholder insert {cpu('cpp-mariadb','T6','multiparam')} µs vs {cpu('cpp-mysql-connector','T6','multiparam')} for MySQL
  Connector/C++. Connector/C++ needs `pluginDir` to find `mysql_native_password`; MariaDB Connector/C++ keeps the batch
  after `executeBatch()` (call `clearBatch()`).
- **trilogy verifies certificates by host name only**, not by IP address.
- Memory after connecting: Rust {mb('rust-sqlx','T2','literal','mem_baseline_kb')}–{mb('rust-mysql','T2','literal','mem_baseline_kb')} MB,
  PHP {mb('php-mysqli','T2','literal','mem_baseline_kb')} MB, .NET {mb('dotnet-mysqlconnector','T2','literal','mem_baseline_kb')} MB,
  Node {mb('node-mariadb','T2','literal','mem_baseline_kb')}–{mb('node-mysql2','T2','literal','mem_baseline_kb')} MB.

""" + tuned_section(P2) + """## Tables

Superscript numbers mark results with a note; the notes follow each table.
""" + tables(P2)

open("reports/phase1.md", "w").write(p1)
open("reports/phase2.md", "w").write(p2)
print("wrote reports/phase1.md", len(p1), "and reports/phase2.md", len(p2))
