# SQL driver benchmark

> **AI-generated results.** This benchmark was designed, run and analyzed with an AI assistant (Claude). Results and findings have been spot-checked by a person, but not every number and explanation has been verified in detail, and some may be wrong. The code and raw data are published so you can verify anything here; please report problems as [issues](https://github.com/Percona-Lab/sql-driver-benchmark/issues).

Measures the **client-side cost of database drivers** — CPU time, memory, hardware counters — across
programming languages, and the extra cost of frameworks built on them (SQLAlchemy, Hibernate, GORM, …).
It is not a database benchmark: the server configuration is fixed and identical for every driver, and
only driver/framework options vary. The first round covers **MySQL (Percona Server 9.7 LTS) and
MariaDB 12.3 LTS**; other databases will follow.

**Interactive results: https://percona-lab.github.io/sql-driver-benchmark/**

Full method: [SPEC.md](SPEC.md). Host-setup distortions we found and fixed: [docs/measurement-pitfalls.md](docs/measurement-pitfalls.md). Stack inventory and tuned options: [stacks.yaml](stacks.yaml).

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

Per measured iteration: process CPU (includes GC/JIT threads), wall time, server CPU and peak RSS. Each
cell runs as 5 fresh processes; the median is reported. Hardware counters (cycles, instructions, IPC,
user/kernel split, branch/L1/LLC/TLB misses) come from two extra processes per cell under `perf stat`,
because counting adds measurable cost to syscall-heavy work and must not touch the timed runs.
A separate profiling pass (perf/eBPF + language profilers) shows where the time goes.

## Environment

One bare-metal host (Vultr, AMD EPYC 4245P, 6 cores, 32 GB, NVMe), Ubuntu 26.04.1, kernel 7.0.
SMT off, boost off, frequency fixed at 3.9 GHz. The client runs alone on an isolated core (`isolcpus`); the database
server is pinned to three other cores. Client and server talk over loopback TCP (Unix socket as a
variant), so only client-side cost differs between drivers. Exact versions: [results/versions.txt](results/versions.txt).

## Drivers

| Language | Drivers |
|---|---|
| C | Oracle libmysqlclient 9.7.4, MariaDB Connector/C 3.4.11 |
| C++ | MySQL Connector/C++ 26.10, MariaDB Connector/C++ 1.1.9 |
| Go 1.27 | go-sql-driver/mysql 1.10.2 (database/sql), go-mysql 1.16.0 |
| Rust | mysql 28.0.4, sqlx 0.9.1 |
| Java 25 | MySQL Connector/J 26.10.0, MariaDB Connector/J 4.0.0 |
| .NET 10 | MySqlConnector 3.0.0, MySql.Data 26.10.0 |
| Python 3.14 | mysqlclient 2.3.1, mysql-connector-python 26.10 (C extension and pure), PyMySQL 1.2.4, MariaDB Connector/Python 1.1.15 |
| Node.js 26 | mysql2 3.24.6, mariadb 3.5.5, mysql 2.18.1 |
| PHP 8.5 | mysqli, PDO_MySQL (mysqlnd) |
| Ruby 4.0 (YJIT) | mysql2 0.5.7, trilogy 2.13.3 |

Frameworks (Phase 3), each on the driver named in the [Phase 3 report](reports/phase3.md): SQLAlchemy 2.1 Core/ORM,
Django 6.1, Spring JdbcTemplate 7.1, jOOQ 3.21, Hibernate 7.4, sqlx 1.4 and GORM 1.31 (Go), Knex 3.3, Drizzle 0.45,
TypeORM 1.1, Sequelize 6.37, Prisma 7.10, Dapper 2.1, EF Core 9.0 (Pomelo), Doctrine DBAL 4.6 and ORM 3.8, Eloquent 13.43,
Sequel 5.110, ActiveRecord 8.1, Diesel 2.4, SeaORM 2.0. Later: async drivers, ODBC and Perl.

## Status

- **All 24 drivers and 22 frameworks measured** (C, C++, Go, Rust, Java, .NET, Python, Node.js, PHP, Ruby) on both
  servers, CPU and memory. Reports: [Phase 1 — C, Go, Java, Python](reports/phase1.md) ·
  [Phase 2 — C++, Rust, .NET, Node.js, PHP, Ruby](reports/phase2.md) · [Phase 3 — frameworks](reports/phase3.md).
- 2026-11-26: steady-state correction for JIT runtimes (warm-up could stop on a plateau of unoptimized code; 90 cells
  rerun) and for the Node.js drivers' streamed rows; see the correction section in each report.
- `results/summary.json` (timed runs) and `results/summary-mem.json` (memory pass) aggregate `results/raw/` and `results/raw-mem/`.
- **Profiles** (where the client CPU goes, 381 perf profiles with flame graphs): [reports/profiles.md](reports/profiles.md).
  Breakdowns in `results/profile-summary.json`, flame graphs in `results/profiles/svg/`; the raw folded stacks (1.8 GB) are in
  `results/profiles-folded-2026-11-26.tar.zst` (`orchestrator/profile_stats.py` recomputes the stack-level figures).

## Updating the results page

`docs/` is the GitHub Pages site. After a run: `python3 orchestrator/report.py results/raw > s.json`,
`python3 orchestrator/artifact_data.py s.json docs/data/cells.json --mem summary-mem.json`, copy `reports/notes.json` and
`reports/tuned.json` to `docs/data/`, then `python3 orchestrator/build_site.py`. Reports: `python3 orchestrator/build_reports.py
results/summary.json results/summary-mem.json` (framework tax: `orchestrator/fwtax.py`).
Notes are rules in `reports/notes.json` matched against server, driver, test, variant and config.

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

## License

Apache License 2.0 — see [LICENSE](LICENSE).
