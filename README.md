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

- **Phase 1 (C, Go, Python, Java) complete** — report: [reports/phase1.md](reports/phase1.md), including the Java rerun.
- **Phase 2 (Node.js, PHP, Ruby, .NET, Rust, C++)**: full run in progress.

Early observations (to be confirmed by the profiling pass):

- With TLS but no CA configured, both C client libraries load and parse the whole system CA bundle on
  every connection (~3.6 ms CPU vs ~0.7 ms with a CA file).
- libmysqlclient issues two `SSL_read` calls per row (2M for 1M rows; Connector/C: ~700), so TLS doubles
  its per-row cost for large result sets.
- MariaDB Connector/C sleeps (`usleep(1)`, ~50 µs on Linux) after every `connect()`, adding wall time
  (not CPU) to each connection.
- MySQL/Percona Server converts `JSON` from its binary storage format to text on every read: ~13× the
  server CPU of the same bytes as `LONGBLOB` (100 KB documents), output ~10% larger (reformatted), and the
  slower send costs the client 10–30% more CPU per KB than reading the same documents from MariaDB, which
  stores `JSON` as text. A storage-format trade-off; analysing it further is out of scope here.

## Updating the results page

`docs/` is the GitHub Pages site. After a run: `python3 orchestrator/report.py results/raw > s.json`,
`python3 orchestrator/artifact_data.py s.json docs/data/cells.json`, and copy `reports/notes.json` to `docs/data/`.
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
