# SQL driver benchmark

Measures the **client-side cost of database drivers** — CPU time, memory, hardware counters — across
programming languages, and the extra cost of frameworks built on them (SQLAlchemy, Hibernate, GORM, …).
It is not a database benchmark: the server configuration is fixed and identical for every driver, and
only driver/framework options vary. The first round covers **MySQL (Percona Server 9.7 LTS) and
MariaDB 12.3 LTS**; other databases will follow.

Full method: [SPEC.md](SPEC.md). Stack inventory and tuned options: [stacks.yaml](stacks.yaml).

## What is measured

All tests are single-threaded and verify a checksum on every iteration, so no driver can skip work.

| Test | Work | Unit |
|---|---|---|
| T0 footprint | load driver, connect, `SELECT 1` | RSS, startup CPU |
| T1 connect | connect + auth + close; TCP, Unix socket, TLS (no verify / verify / resumption), ed25519 | µs per connection |
| T2 point select | 200,000 × `SELECT v FROM t_int WHERE id = ?`; literal, client-side param, server-prepared | µs per query |
| T3 1M ints | `SELECT v FROM t_int`, summed on the client; text/binary protocol × buffered/streamed, TLS | ns per row |
| T4 wide rows | 10,000 rows × 100 columns (all-INT and mixed types), every cell touched | ns per cell |
| T5 large values | 1,000 JSON / BLOB values of 1 KB, 10 KB, 100 KB or mixed, 20 queries | ns per KB |
| T6 bulk insert | 1M rows in 1,000-row statements: app-built SQL, 4,000-placeholder statement, driver batch API | µs per statement |

Per measured iteration: process CPU (includes GC/JIT threads), wall time, server CPU, peak RSS, and
`perf stat` hardware counters (cycles, instructions, IPC, user/kernel split, branch/L1/LLC/TLB misses)
counted only during measured iterations. Each cell runs as 5 fresh processes; the median is reported.
A separate profiling pass (perf/eBPF + language profilers) shows where the time goes.

## Environment

One bare-metal host (Vultr, AMD EPYC 4245P, 6 cores, 32 GB, NVMe), Ubuntu 26.04.1, kernel 7.0.
SMT off, boost off, frequency fixed at 3.9 GHz. The client runs alone on an isolated core; the database
server is pinned to three other cores. Client and server talk over loopback TCP (Unix socket as a
variant), so only client-side cost differs between drivers. Exact versions: [results/versions.txt](results/versions.txt).

## Drivers (phase 1)

| Language | Drivers |
|---|---|
| C | Oracle libmysqlclient 9.7.4, MariaDB Connector/C 3.4.11 (baseline floor) |
| Java 25 | MySQL Connector/J 26.10.0, MariaDB Connector/J 4.0.0 (defaults and tuned options) |
| Python 3.14 | mysqlclient 2.3.1, mysql-connector-python 26.10 (C extension and pure), PyMySQL 1.2.4, MariaDB Connector/Python 1.1.15 |
| Go 1.27 | go-sql-driver/mysql 1.10.2 (database/sql), go-mysql 1.16.0 |

Next: Node.js, PHP, Ruby, Rust, .NET, C++, then frameworks (SQLAlchemy, Django, Hibernate, jOOQ, GORM,
Prisma, Sequelize, Doctrine, ActiveRecord, EF Core, Diesel, …), then async drivers, ODBC and Perl.

## Status

- C baseline: complete on both servers.
- Phase 1 (Java, Python, Go): runners validated, full run in progress. `results/` is a **snapshot of a run
  in progress**; `results/summary-snapshot.json` aggregates whatever has finished.

Early observations (to be confirmed by the profiling pass):

- With TLS but no CA configured, both C client libraries load and parse the whole system CA bundle on
  every connection (~3.6 ms CPU vs ~0.7 ms with a CA file).
- libmysqlclient issues two `SSL_read` calls per row (2M for 1M rows; Connector/C: ~700), so TLS doubles
  its per-row cost for large result sets.
- MariaDB Connector/C sleeps (`usleep(1)`, ~50 µs on Linux) after every `connect()`, adding wall time
  (not CPU) to each connection.
- Percona Server returns `JSON` columns ~10% larger than stored (it reformats them).

## Layout

```
SPEC.md                 method
stacks.yaml             drivers, frameworks, tuned options
host/                   host setup: OS upgrade, CPU isolation, servers, toolchains, dbctl.sh
orchestrator/load.py    schema, data, expected checksums
orchestrator/run.py     runs cells as fresh pinned processes under perf stat
orchestrator/report.py  aggregates result files; tables.py renders markdown tables
stacks/<lang>/          one runner per language (shared CLI/env contract, SPEC.md §5)
results/raw/<server>/<stack>/<test>-<variant>-<config>-<rep>.json
```

## Running

On a host prepared with `host/01..05`:

```
python3 orchestrator/load.py ps && python3 orchestrator/load.py maria
stacks/<lang>/build.sh
python3 orchestrator/run.py --stacks c-libmysqlclient,java-connector-j --servers ps,maria --configs default,tuned
python3 orchestrator/report.py > summary.json && python3 orchestrator/tables.py summary.json
```

`run.py --quick` runs every cell once as a smoke test.
