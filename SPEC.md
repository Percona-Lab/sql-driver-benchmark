# MySQL / MariaDB driver overhead benchmark — specification

Goal: measure the **client-side cost** (CPU time, memory) of MySQL and MariaDB
drivers and of the frameworks built on them, across programming languages.
This is not a database benchmark: the server configuration is fixed and the
same for every stack; only driver/framework options vary.

## 1. Fixed environment

| Item | Value |
|---|---|
| Host | Vultr bare metal vbm-6c-32gb-amd (EPYC 4245P Zen 5, 6C, 30 GB, 2× Samsung PM9A3 NVMe), ewr, Ubuntu 26.04.1 (upgraded in place from 24.04; Vultr has no 26.04 image for this plan), kernel 7.0 |
| CPU | `nosmt`, boost off, `performance` governor with min = max = 3.9 GHz (verified under load); applied at boot by `dbbench-cpu.service` |
| Pinning | client on CPU 5 (`isolcpus=5 nohz_full=5 rcu_nocbs=5`); mysqld `CPUAffinity=1 2 3`; CPUs 0 and 4 for OS, orchestrator, profilers |
| Servers | Percona Server for MySQL 9.7.2-3 LTS (`ps`, apt, port 3306), MariaDB 12.3.4 LTS (`maria`, official bintar in /opt/mariadb, port 3307); only one running at a time (`dbctl.sh start ps\|maria`). Users: `bench` (caching_sha2 on ps, native on maria), `bench_ed` (ed25519, maria) |
| Transport | TCP 127.0.0.1 (default); Unix socket as a T1/T2 variant |
| TLS | TLS 1.3, one ECDSA P-256 server cert used by both servers; client verifies CA in `tls-verify` variant |
| Server config | buffer pool 16 GB (all data in memory), binlog off, `innodb_flush_log_at_trx_commit=2`, `max_allowed_packet=256M`, everything else default. Identical for every stack, never tuned per stack. |
| Runtimes | Java 25 LTS, Python 3.14, Go 1.27.4, Node 26 LTS, PHP 8.5, Ruby 4.0.9 (built with YJIT + frame pointers), .NET 10 LTS, Rust stable, GCC; Oracle libmysqlclient 9.7 LTS, MariaDB Connector/C (distro). Exact versions in `versions.txt` |

## 2. Data set (created once per server by `orchestrator/load.py`)

| Table | Shape | Notes |
|---|---|---|
| `t_int` | `id INT PK, v INT NOT NULL`, 1,000,000 rows | `v = (id * 7919) % 1000003` |
| `t_wide_int` | `id INT PK, c001..c100 INT NOT NULL`, 10,000 rows | |
| `t_wide_mix` | `id INT PK` + 100 columns, 10,000 rows | 10-type pattern repeated 10×: `INT`, `BIGINT`, `DECIMAL(15,2)`, `DOUBLE`, `VARCHAR(32)`, `DATETIME(6)`, `DATE`, `TINYINT`, `VARCHAR(255) NULL` (~10% NULL), `INT NULL` (~10% NULL) |
| `t_blob` | `id INT PK, size_class VARCHAR(8), doc JSON, doc_bin LONGBLOB` | 1,000 rows each of `1k`, `10k`, `100k`, `mix` (70% 1K / 25% 10K / 5% 100K). ASCII-only JSON, so char length = byte length. `doc_bin` holds the same bytes. |
| `t_bulk` | `id INT PK, a INT, b VARCHAR(32), c DOUBLE` | Emptied (`TRUNCATE`) before each measured iteration, outside the timing. |

Expected checksums are computed by the loader and stored in `data/expected.json`.
Point-select ids: `data/ids_200k.txt` (seeded, same for all stacks), read by the
runner before timing.

## 3. Tests

All single-threaded. Every test verifies a checksum; a mismatch invalidates the run.

TLS: T2–T6 run with TLS explicitly **off** for every stack (several drivers default to TLS-preferred, which
would otherwise mix crypto cost into the driver comparison); `+tls` variants (T3, T5) turn it on. Every runner
reports the negotiated cipher of the connection under test. caching_sha2_password: the orchestrator fills the
server's auth cache after every restart, so T1 measures the fast-auth path.

| Test | Work in one measured iteration | Variants | Reported unit |
|---|---|---|---|
| **T0 footprint** | Start, load driver, open 1 connection, run `SELECT 1` | — | RSS after load, RSS delta per connection, startup CPU |
| **T1 connect** | 2,000 × (connect, authenticate, `COM_QUIT`/close). No pooling: pooling is disabled even where it is the default (.NET, ORMs use null pools) | `tcp`, `tls`, `tls-verify`, `tls-resume` (where supported), `socket`; auth: `caching_sha2` (ps), `native` + `ed25519` (maria) | client CPU µs/connect, wall µs |
| **T2 point select** | 200,000 × `SELECT v FROM t_int WHERE id = ?` | `literal` (id in SQL text), `param` (driver's parameter API, client-side if that is the default), `prepared` (server prepare once, execute N) | client CPU µs/query |
| **T3 1M ints** | `SELECT v FROM t_int`, sum `v` on the client | `text`/`binary` protocol × `buffered`/`streamed` result | client ns/row, peak RSS |
| **T4 wide** | `SELECT * FROM t_wide_int` / `t_wide_mix`, touch every cell | `int`, `mix` × `text`/`binary` | client ns/cell, peak RSS |
| **T5 blob** | `SELECT doc FROM t_blob WHERE size_class = ?` (1,000 rows), 20 repetitions in one process, touch each value | `1k`, `10k`, `100k`, `mix` × `json`/`blob` column; extra `parse` variant (parse JSON with the language's standard library) | client ns/KB, peak RSS, RSS after, GC/alloc counts |
| **T6 bulk insert** | 1,000,000 rows into `t_bulk`, 1,000 rows per statement, `COMMIT` per statement; row values generated in the runner (part of the measured cost) | `sqltext` (app builds multi-row INSERT text, using the driver's escaping function), `multiparam` (one statement with 1,000 × 4 placeholders), `batch` (driver's native batch API: `rewriteBatchedStatements`, `executemany`, MariaDB bulk execute, …) | client µs/statement, ns/row |

Touch rules (same everywhere):
- **T3**: add `v` to a 64-bit sum.
- **T4**: read every cell with the driver's natural typed accessor (the default type mapping; e.g. `getBigDecimal` for DECIMAL in JDBC, whatever object the Python driver returns). Checksum = number of non-NULL cells + sum of all integer-family values + sum of string lengths. DECIMAL, DOUBLE, DATE and DATETIME are touched (accessed, NULL-checked) but not summed, so no app-side conversion is added.
- **T5**: checksum = sum over values of (length + sum of the code units at positions 0, 64, 128, …). The stride of 64 reads every cache line without making a language loop over every byte.
- **T6 rows**: `id = i`, `a = i * 3`, `b = "name-" + i`, with an apostrophe (`"o'k-" + i`) on every 10th row so escaping is exercised, `c = i * 0.5`.

Language floor: each runner also runs the same touch loop over equivalent
in-memory data (`--floor`), so the driver cost can be reported net of the
language's own iteration cost.

## 4. Configurations (driver/framework tuning only)

- `default`: the library's defaults, plus only what is needed to run the test (credentials, TLS settings, pooling off for T1).
- `tuned`: the best-known **driver or framework options** for that test (listed per stack in `stacks.yaml`). No server-side changes. A tuned option may change the returned types (e.g. raw bytes), but the app must still compute the same checksum, and the conversion counts as measured cost.

## 5. Runner contract

One runner per stack, in its own directory `stacks/<lang>/<stack>/`, built by `build.sh`.

```
run --test T3 --variant text-buffered --config default \
    --server ps --host 127.0.0.1 --port 3306 [--socket PATH] \
    --warmup N --iters K [--floor] --out result.json
```

- Unsupported test/variant: exit 3 with a one-line reason (it is recorded as `n/a` with that reason).
- Each measured iteration lasts ≥ 1 s (iteration counts above are scaled up by the orchestrator if needed).
- Per iteration, the runner records:
  - `cpu_ns`: process CPU (user + sys) from the best ns/µs source (`CLOCK_PROCESS_CPUTIME_ID`, `getProcessCpuTime`, `process.cpuUsage`, …). Process CPU, not thread CPU, so GC and JIT threads are counted. They share the client's one pinned core.
  - `wall_ns`: monotonic clock.
  - `srv_ticks`: mysqld utime + stime from `/proc/<pid>/stat` (pid in `$MYSQLD_PID`).
  - `rss_peak_kb`: write `5` to `/proc/self/clear_refs` before the iteration, read `VmHWM` after.
  - `rss_end_kb`.
  - `checksum`.
  - Runtime counters where available: `alloc_bytes`, `gc_count`, `gc_ns`.
- Output JSON: stack, driver and runtime versions, options used, warmup and iterations, per-iteration records.
- Hardware counters: the runner writes `enable` / `disable` to the FIFO in `$PERF_CTL` (if set) around each
  measured iteration and waits for `ack` on `$PERF_ACK`. The orchestrator wraps the runner in
  `perf stat -D -1 --control fifo:$PERF_CTL,$PERF_ACK`, so only measured iterations are counted, for any language
  (it is just two file writes).

## 5a. Hardware counters (all timed runs)

Counting mode (`perf stat`, no sampling), so overhead is negligible. The client process only, user and kernel
counted separately (`:u` / `:k`). Two event sets, each ≤ 6 events so the AMD PMU never multiplexes:

| Set | Events | Derived metrics |
|---|---|---|
| A (runs 1–3) | cycles, instructions, branch-misses, context-switches, page-faults, task-clock | cycles/op, instructions/op, **IPC**, branch-miss %, minor faults/op (allocation churn) |
| B (runs 4–5) | cycles, instructions, L1-dcache-load-misses, LLC misses (`cache-misses`), dTLB-load-misses, iTLB-load-misses | L1/LLC misses per op and per 1k instructions, TLB misses (large heaps, big code footprint of JIT/interpreters) |

With boost off, cycles track CPU time closely; **instructions per op** is the most stable metric and is used to confirm
small differences that CPU time alone cannot resolve. Kernel cycles show the syscall/network share. Exact AMD Zen 5
event names are fixed after `perf list` on the box and recorded in the results.

Per-function counter attribution (e.g. which functions take the cache misses) comes from the profiling pass:
`perf record -e cycles,cache-misses` (AMD IBS `ibs_op//` for precise data-cache attribution) on C/C++/Rust/Go stacks and
on the native parts of the others.

## 6. Run protocol

- Orchestrator (`orchestrator/run.py`) runs each (stack, server, test, variant, config) as **5 fresh processes**; median of the per-process medians is reported.
- Warm-up: 2 iterations for AOT/native/interpreted stacks; for JIT stacks (JVM, .NET, Node) warm-up runs until the per-iteration CPU changes by < 2% for 3 iterations (cap 30). The warm-up length is reported.
- A cell is accepted when the coefficient of variation across the 5 processes is ≤ 3%; otherwise it is re-run once and flagged if still noisy.
- CPU frequency, temperature and steal-free state are checked before each batch.

## 7. Profiling pass (separate from timed runs)

For every stack, server `ps`, `tuned` config, one variant per test:

| Language | CPU profile | Allocation profile |
|---|---|---|
| C / C++ / Rust | `perf record -g` (frame pointers, DWARF fallback) | heaptrack; malloc uprobe counts (eBPF) |
| Go | perf + pprof | pprof alloc |
| Java | async-profiler (cpu) | async-profiler (alloc) |
| Python | perf with `-X perf`; `py-spy --native` | memray |
| Node.js | perf + `--perf-basic-prof`; `--cpu-prof` | V8 heap sampling |
| .NET | perf + `DOTNET_PerfMapEnabled=1` | dotnet-trace GC events |
| PHP | perf (mysqlnd is C) + phpspy | — |
| Ruby | perf + YJIT perf map; rbspy | — |
| Perl | perf + NYTProf | — |

Outputs:
- Flame graph (SVG) per stack × test.
- **Category breakdown**: collapsed stacks are mapped by per-language regex rules (`profiling/categories/<lang>.yaml`) to: `net-syscall`, `tls-crypto`, `protocol-parse`, `type-conversion`, `alloc-gc`, `runtime-interp`, `framework`, `app-touch`, `other`. Each rule file is checked by hand against one profile before use.
- eBPF extras: syscall counts per operation (all tests), off-CPU time (T1, T2).

## 8. Results layout

```
results/<server>/<stack>/<test>-<variant>-<config>-<n>.json
profiles/<server>/<stack>/<test>-<variant>.{svg,folded,categories.json}
```

A report generator builds per-test tables and charts: absolute values, multiple of
the C floor, and for wrappers the **wrapper tax** over the same underlying driver.
