# Phase 1 report — C, Go, Java, Python

> **AI-generated results.** This benchmark was designed, run and analyzed with an AI assistant (Claude). Results and findings have been spot-checked by a person, but not every number and explanation has been verified in detail, and some may be wrong. The code and raw data are published so you can verify anything here; please report problems as [issues](https://github.com/Percona-Lab/sql-driver-benchmark/issues).

Run: 2026-11-17 23:09 → 2026-11-18 19:20 UTC on one bare-metal host (EPYC 4245P, client alone on an
isolated core, 3.9 GHz fixed). Servers: Percona Server 9.7.2-3 and MariaDB 12.3.4, identical
configuration. Method: [SPEC.md](../SPEC.md); host pitfalls fixed before this run: [measurement-pitfalls](../docs/measurement-pitfalls.md).

- 829 test cells (stack × server × test × variant × config), each 5 fresh timed processes (no `perf`
  attached) + 2 hardware-counter processes; every iteration checksum-verified. **0 failures.**
- Repeatability: median coefficient of variation across the 5 processes **0.47%**; 95% of cells under 2.6%
  (outliers are T0, a single cold start).
- **Java was rerun** (2026-11-18 20:21 → 2026-11-19 03:15 UTC) after a runner fix: the first run read process CPU
  from `OperatingSystemMXBean`, which only advances in 10 ms ticks on Linux. Java now uses `clock_gettime` via FFM.
  Java cells show more run-to-run spread than the others (up to ~13%, JIT and GC); read small Java differences
  with that in mind.
- Raw results: [`results/raw/`](../results/raw), aggregate: [`results/summary-phase1.json`](../results/summary-phase1.json).

All numbers are **client CPU per operation** (user + kernel, whole process), shown as **Percona / MariaDB**.

## Key findings

**Connections**
- Plain TCP connect costs 21–26 µs of client CPU with the C libraries, 27–39 µs in Go, 29–128 µs in Python —
  except **PyMySQL: ~3.7 ms per connect**, on TCP and Unix socket alike and on both servers. Something in its
  connect path costs 80× the C library; the profiling pass will show what.
- **TLS without a CA configured costs ~3.6 ms per connect in every libmysqlclient/Connector/C-based driver**
  (C, mysqlclient, mysql-connector C ext, MariaDB Connector/Python): the library loads and parses the full
  system CA bundle (120 certificates) on every connection. With a CA file: ~0.7 ms.
- **MariaDB 12.3 forces TLS key exchange to ECDH P-521 (secp521r1); Percona Server uses P-256.** Every client
  pays: Go 2.6 ms vs 0.28 ms per TLS connect, C +0.3 ms; the server itself burns ~5 ms CPU per TLS connect.
- Go's TLS stack is the cheapest here (0.28 ms on Percona with no CA, 0.24 ms with session resumption).
  libmysqlclient session resumption saves ~15% (0.73 → 0.61 ms).
- Pure-Python mysql-connector spends **7.3 ms** per TLS connect (verified or not).
- MariaDB Connector/C sleeps `usleep(1)` after every `connect()` (~50 µs on Linux): wall time only, not CPU.

**Point selects**
- C: 4.1–4.5 µs per query, ~78% of it kernel time (one send + one receive). Prepared vs literal: no difference in C.
- **go-sql-driver's parameterized query costs 13.4 µs by default**: without `interpolateParams` each call does
  prepare + execute + close (3 round trips). With the option: 6.0 µs. go-mysql's `Execute(sql, args...)` does
  the same (13.2 µs).
- Python: MariaDB Connector/Python and mysqlclient ~6–7 µs (close to Go); PyMySQL 15–16 µs;
  pure-Python mysql-connector 25–38 µs. Server-side prepared statements are *slower* than literal SQL in
  both Python drivers that offer them (mariadb 13 vs 6 µs, connector-C 14.5 vs 10.7 µs).

**Large result sets (1M ints)**
- C: 25–38 ns/row; binary protocol and streaming are cheapest.
- **libmysqlclient over TLS: 2× the per-row cost** (78 vs 37 ns) — it makes two `SSL_read` calls per row
  (2M for 1M rows). MariaDB Connector/C buffers reads (~700 calls): TLS adds nothing measurable.
- Go: 66–101 ns/row; go-sql-driver has no buffered mode (`database/sql` always streams).
- Python: MariaDB Connector/Python 196 ns/row and mysqlclient 218 ns/row (buffered); PyMySQL ~1.1 µs/row;
  pure-Python mysql-connector 2.4–3.8 µs/row. **mysql-connector's prepared (binary) cursor is 2.6× slower than
  its text cursor** (1,300 vs 500 ns/row); streaming is slower than buffering in every Python driver.

**Wide rows (100 columns)**
- C binary protocol: 7–8 ns per INT cell, 11–14 ns per mixed-type cell; text protocol about 2× for INTs.
- Go: go-mysql is near C on INTs (9 ns binary) but 53 ns on mixed types in binary; go-sql-driver 35–62 ns.
- Python: 62–650 ns per cell; type conversion (Decimal, datetime) dominates the mixed table.

**Large values (JSON / BLOB, ns per KB)**
- Most of this cost is the kernel copying data out of the socket (~74% kernel time in C).
- **MySQL/Percona Server converts `JSON` from binary to text on every read**: ~13× the server CPU of the same
  bytes as `LONGBLOB`, output ~10% larger, and 10–30% more client CPU per KB than reading the same documents
  from MariaDB (text storage). A storage-format trade-off; not analysed further here.
- Parsing JSON in the client costs 10–60× the driver's read cost (Go `encoding/json` 15–18 µs/KB, Python `json` ~4 µs/KB).

**Bulk insert (1,000-row statements)**
- Building the SQL text costs C ~250–270 µs per 1,000 rows (double formatting + escaping); a 4,000-placeholder
  prepared statement 54–66 µs; MariaDB's bulk API 59 µs (MariaDB server only — Percona rejects it).
- Go: 225–310 µs; `interpolateParams` saves 28% on the multi-placeholder insert.
- Python: building the SQL text yourself (608–965 µs) beats the drivers' parameter interpolation
  (1.2–3.1 ms) and `executemany` (2.1–4.7 ms). **MariaDB Connector/Python `executemany`: 0.6 ms on MariaDB (bulk
  protocol) but 13.7 ms on Percona** (falls back to one execute per row).

**Java**
- MariaDB Connector/J reads 1M integers at 17–21 ns/row, cheaper than the C libraries; Connector/J needs
  148–265 ns/row. On wide rows MariaDB Connector/J is 9–32 ns/cell vs Connector/J 54–97.
- Point select: MariaDB Connector/J 4.3 µs per query (C level); Connector/J 6.2–6.9 µs.
- Connector/J's verified TLS costs 4.6 ms per connect vs 1.8 ms unverified; MariaDB Connector/J ~1.85 ms either way.
- Connector/J `executeBatch()` on defaults: 5.7 ms per 1,000 rows (one statement per row); with
  `rewriteBatchedStatements`: 1.6 ms.
- JVM start + connect: 180–340 ms of CPU and 67–77 MB resident before any work.

**Footprint (T0)**
- Startup + connect: Go 0.1 ms / ~10 MB RSS, C 0.4–0.7 ms / 8–11 MB, Python 0.9–5.6 ms / 23–36 MB
  (PyMySQL the largest).

**Not supported (recorded as n/a, with the driver's own reason)**
- ed25519 authentication works only in MariaDB Connector/C and Python, go-mysql, and PyMySQL (with `pynacl`).
  **go-sql-driver fails it against MariaDB 12.3 with "malformed packet"** — a failure, not a missing feature.
- No Python driver exposes TLS session resumption; mysqlclient and PyMySQL have no server-side prepared statements.

## Tables

Superscript numbers mark results with a note; the notes follow each table.

### T1 — client CPU, µs/connect (Percona / MariaDB)

| stack | config | socket | tcp | tls | tls-resume | tls-verify | tls-verify-resume | tcp@ed25519 |
|---|---|---|---|---|---|---|---|---|
| c-libmysqlclient | default | 11.3⁴ / 10.5⁴ | 23.9⁴ / 21.3⁴ | 3,598³ / 3,876²˒³ | 3,513³ / 3,879²˒³ | 727 / 1,020² | 611 / 1,021² | n/a / n/a |
| c-mariadb-connc | default | 12⁴˒⁵ / 10.8⁴˒⁵ | 25.6⁴˒⁵ / 22.8⁴˒⁵ | 3,586³˒⁵ / 3,797²˒³˒⁵ | n/a³˒⁵ / n/a²˒³˒⁵ | 669⁵ / 958²˒⁵ | n/a⁵ / n/a²˒⁵ | n/a⁵ / 69.2⁵ |
| go-sql-driver | default | 17.3⁴ / 14.5⁴ | 31.6⁴ / 26.7⁴ | 284 / 2,557² | 233 / 2,560² | 395 / 2,617² | 236 / 2,624² | n/a / n/a¹² |
| go-sql-driver | tuned | 17.2⁴ / 14.5⁴ | 31.7⁴ / 26.6⁴ | 285 / 2,557² | 233 / 2,562² | 395 / 2,618² | 236 / 2,622² | n/a / n/a¹² |
| go-mysql | default | 25⁴ / 22.4⁴ | 39.4⁴ / 34.7⁴ | 314 / 2,606² | 265 / 2,608² | 452 / 2,690² | 292 / 2,701² | n/a / 69.5 |
| go-mysql | tuned | n/a⁴ / n/a⁴ | n/a⁴ / n/a⁴ | n/a / n/a² | n/a / n/a² | n/a / n/a² | n/a / n/a² | n/a / n/a |
| java-connector-j | default | n/a¹˒⁴ / n/a¹˒⁴ | 72.9¹˒⁴ / 70.9¹˒⁴ | 1,848¹ / 7,763¹˒²˒¹⁶ | n/a¹ / n/a¹˒² | 4,578¹ / 10,634¹˒² | n/a¹ / n/a¹˒² | n/a¹ / n/a¹ |
| java-connector-j | tuned | n/a¹˒⁴ / n/a¹˒⁴ | 57.4¹˒⁴ / 54¹˒⁴ | 1,868¹˒¹⁶ / 7,645¹˒² | n/a¹ / n/a¹˒² | 4,638¹ / 9,916¹˒² | n/a¹ / n/a¹˒² | n/a¹ / n/a¹ |
| java-mariadb-j | default | 43.9¹˒⁴ / 40¹˒⁴ | 66.5¹˒⁴˒¹⁶ / 58.9¹˒⁴ | 1,839¹ / 7,352¹˒² | n/a¹ / n/a¹˒² | 1,854¹ / 7,055¹˒²˒¹⁶ | n/a¹ / n/a¹˒² | n/a¹ / 155¹ |
| java-mariadb-j | tuned | 59.2¹˒⁴ / 53.2¹˒⁴ | 79.8¹˒⁴ / 70¹˒⁴ | 1,973¹˒¹⁶ / 7,435¹˒² | n/a¹ / n/a¹˒² | 2,031¹ / 7,235¹˒² | n/a¹ / n/a¹˒² | n/a¹ / 166¹ |
| py-mysqlclient | default | 29.6⁴ / 28.9⁴ | 46.6⁴ / 44.4⁴ | 3,684³ / 3,954²˒³ | n/a³ / n/a²˒³ | 816 / 1,103² | n/a / n/a² | n/a / n/a |
| py-mysql-connector-c | default | 42.4⁴ / 41.7⁴ | 65⁴ / 62.1⁴ | 3,730³ / 4,004²˒³ | n/a³ / n/a²˒³ | 856 / 1,148² | n/a / n/a² | n/a / n/a |
| py-mariadb | default | 16.2⁴˒⁵ / 15⁴˒⁵ | 31.8⁴˒⁵ / 29.1⁴˒⁵ | 3,637³˒⁵ / 3,867²˒³˒⁵ | n/a³˒⁵ / n/a²˒³˒⁵ | 718⁵ / 1,011²˒⁵ | n/a⁵ / n/a²˒⁵ | n/a⁵ / 76⁵ |
| py-pymysql | default | 3,644⁴˒¹⁵ / 3,915⁴˒¹⁵ | 3,750⁴˒¹⁵ / 4,023⁴˒¹⁵ | 3,753 / 4,023² | n/a / n/a² | 873 / 1,162² | n/a / n/a² | n/a¹⁵ / 4,092¹⁵ |
| py-mysql-connector-pure | default | 96.4⁴ / 89.3⁴ | 128⁴ / 117⁴ | 7,289 / 7,555² | n/a / n/a² | 7,363 / 7,638² | n/a / n/a² | n/a / n/a |

¹ **Provisional (Java warm-up).** Measured with a fixed 5-iteration warm-up that did not reach steady state: the JIT compiler was still working during measured iterations (spread within a process 26-45%). A rerun with adaptive warm-up (until 3 iterations agree within 5%) is queued; treat these Java figures as provisional.  
² **MariaDB TLS key exchange.** MariaDB 12.3 negotiates ECDH on P-521 (secp521r1); Percona Server uses P-256. Much of the extra client CPU per TLS connect on MariaDB is that server-side choice, not the driver.  
³ **TLS without a CA loads the system trust store.** With no CA configured, libmysqlclient and MariaDB Connector/C load and parse the full system CA bundle (120 certificates) on every connection although they verify nothing.  
⁴ **Different default authentication.** Each server uses its own default authentication: Percona Server caching_sha2_password (SHA-256 plus an extra round trip on the fast path), MariaDB mysql_native_password. Part of the Percona-vs-MariaDB difference in plain connect cost comes from this, not the driver.  
⁵ **Connector/C sleeps after connect().** MariaDB Connector/C calls usleep(1) after every connect() (about 50 µs on Linux). This adds wall time per connection, not CPU.  
¹² **Fails, not unsupported.** go-sql-driver advertises ed25519 support but fails against MariaDB 12.3 with "malformed packet" (go-mysql works with the same account). A driver bug, not a missing feature.  
¹⁵ **Slow connect, cause not yet profiled.** PyMySQL spends about 3.7 ms of CPU per plain connection, on TCP and Unix socket alike and on both servers, roughly 80× libmysqlclient. Where the time goes will be shown by the profiling pass.  
¹⁶ **Higher run-to-run spread.** The 5 processes for this result differ by more than 5% (coefficient of variation). Small differences against it are not meaningful.  

### T2 — client CPU, µs/query (Percona / MariaDB)

| stack | config | literal | prepared | param |
|---|---|---|---|---|
| c-libmysqlclient | default | 4.32 / 4.09 | 4.23 / 4.19 | n/a / n/a |
| c-mariadb-connc | default | 4.48 / 4.3 | 4.27 / 4.2 | n/a / n/a |
| go-sql-driver | default | 5.89 / 6.09 | 6.34 / 6.2 | 13.4¹³ / 13.4¹³ |
| go-sql-driver | tuned | 5.94 / 6.08 | 6.3 / 6.21 | 6.04 / 6.26 |
| go-mysql | default | 5.76 / 5.89 | 5.84 / 5.7 | 13.2¹⁴ / 13.1¹⁴ |
| go-mysql | tuned | n/a / n/a | n/a / n/a | n/a / n/a |
| java-connector-j | default | 6.9¹ / 6.8¹ | 6.21¹ / 6.05¹ | 6.19¹ / 6.12¹ |
| java-connector-j | tuned | 6.7¹ / 6.65¹ | 6.05¹ / 5.83¹ | 6.07¹ / 5.87¹ |
| java-mariadb-j | default | 4.29¹ / 4.21¹ | 4.28¹ / 4.2¹ | 4.33¹ / 4.2¹ |
| java-mariadb-j | tuned | 4.29¹ / 4.21¹ | 4.32¹ / 4.17¹ | 4.36¹ / 4.2¹ |
| py-mysqlclient | default | 6.4 / 6.36 | n/a / n/a | 6.99 / 6.95 |
| py-mysql-connector-c | default | 10.7 / 10.7 | 14.5 / 14.5 | 11.6 / 11.6 |
| py-mariadb | default | 5.92 / 5.98 | 13.1 / 12 | 6.66 / 6.69 |
| py-pymysql | default | 14.8 / 15.1 | n/a / n/a | 15.9 / 16.1 |
| py-mysql-connector-pure | default | 26.2 / 25 | 37.9 / 38.2 | 30.6 / 29.8 |

¹ **Provisional (Java warm-up).** Measured with a fixed 5-iteration warm-up that did not reach steady state: the JIT compiler was still working during measured iterations (spread within a process 26-45%). A rerun with adaptive warm-up (until 3 iterations agree within 5%) is queued; treat these Java figures as provisional.  
¹³ **Three round trips per parameterized query.** Without client-side interpolation (go-sql-driver: interpolateParams=true, tuned) each parameterized call prepares, executes and closes a server-side statement.  
¹⁴ **Three round trips per parameterized query.** go-mysql's Conn.Execute(sql, args...) prepares, executes and closes a server-side statement on every call.  

### T3 — client CPU, ns/row (Percona / MariaDB)

| stack | config | binary-buffered | binary-streamed | text-buffered | text-buffered+tls | text-streamed | text-streamed+tls |
|---|---|---|---|---|---|---|---|
| c-libmysqlclient | default | 26.8 / 26.8 | 24.6 / 25 | 37.1 / 37 | 78.3⁹ / 78.5⁹ | 28.1 / 28.1 | 69.4⁹ / 69.5⁹ |
| c-mariadb-connc | default | 33.5 / 34.9 | 25.4 / 25.4 | 38.1 / 38 | 38 / 37.8 | 28.8 / 29.3 | 29.4 / 29.5 |
| go-sql-driver | default | n/a / n/a | 85.7 / 85.5 | n/a / n/a | n/a / n/a | 101 / 100 | 103 / 105 |
| go-sql-driver | tuned | n/a / n/a | 85.8 / 85.6 | n/a / n/a | n/a / n/a | 101 / 101 | 102 / 107 |
| go-mysql | default | 69.3 / 69.8 | 65.7 / 65.9 | 83.4 / 83.1 | 84.3 / 85.7 | 78.7 / 81.4 | 80.6 / 83.9 |
| go-mysql | tuned | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a |
| java-connector-j | default | 265¹˒¹⁶ / 262¹˒¹⁶ | 148¹ / 147¹ | 221¹ / 220¹˒¹⁶ | 329¹ / 326¹˒¹⁶ | 149¹ / 150¹ | 167¹ / 169¹ |
| java-connector-j | tuned | 188¹ / 187¹ | 124¹ / 123¹ | 218¹ / 211¹ | 311¹˒¹⁶ / 235¹˒¹⁶ | 123¹ / 123¹ | 142¹ / 150¹ |
| java-mariadb-j | default | 21.5¹˒¹⁶ / 21¹ | 21.3¹˒¹⁶ / 20.7¹˒¹⁶ | 20.5¹ / 20.4¹ | 51.3¹˒¹⁶ / 41.3¹˒¹⁶ | 17¹˒¹⁶ / 23.7¹˒¹⁶ | 63.5¹˒¹⁶ / 40.4¹˒¹⁶ |
| java-mariadb-j | tuned | 20¹ / 20.1¹ | 22.6¹˒¹⁶ / 21.3¹ | 20¹ / 20.4¹ | 61.5¹˒¹⁶ / 41.6¹˒¹⁶ | 17.1¹ / 18.6¹˒¹⁶ | 62.6¹˒¹⁶ / 44.3¹˒¹⁶ |
| py-mysqlclient | default | n/a / n/a | n/a / n/a | 218 / 219 | 260 / 260 | 320 / 319 | 425 / 427 |
| py-mysql-connector-c | default | 1,300 / 1,313 | 1,291 / 1,321 | 500 / 506 | 575 / 585 | 989 / 999 | 1,102 / 1,118 |
| py-mariadb | default | 306 / 305 | 400 / 409 | 196 / 197 | 196 / 197 | 396 / 401 | 402 / 405 |
| py-pymysql | default | n/a / n/a | n/a / n/a | 1,085 / 1,092 | 1,097 / 1,090 | 1,180 / 1,183 | 1,176 / 1,174 |
| py-mysql-connector-pure | default | 3,805 / 3,793 | 3,827 / 3,804 | 2,446 / 2,426 | 2,384 / 2,364 | 3,743 / 3,719 | 3,725 / 3,725 |

¹ **Provisional (Java warm-up).** Measured with a fixed 5-iteration warm-up that did not reach steady state: the JIT compiler was still working during measured iterations (spread within a process 26-45%). A rerun with adaptive warm-up (until 3 iterations agree within 5%) is queued; treat these Java figures as provisional.  
⁹ **Two TLS reads per row.** libmysqlclient issues two SSL_read calls per row (2M for 1M rows; MariaDB Connector/C about 700), so TLS doubles its per-row cost.  
¹⁶ **Higher run-to-run spread.** The 5 processes for this result differ by more than 5% (coefficient of variation). Small differences against it are not meaningful.  

### T4 — client CPU, ns/cell (Percona / MariaDB)

| stack | config | int-binary | int-text | mix-binary | mix-text |
|---|---|---|---|---|---|
| c-libmysqlclient | default | 7.07 / 7.08 | 15.3 / 15.2 | 11.1 / 11.1 | 14.5 / 14.5 |
| c-mariadb-connc | default | 8.05 / 8.01 | 16.7 / 16.5 | 13.8 / 13.6 | 16.2 / 16.7 |
| go-sql-driver | default | 35.4 / 35.2 | 50.3 / 50.7 | 48.6 / 48.6 | 61.9 / 61.9 |
| go-sql-driver | tuned | 35.4 / 35.3 | 50.4 / 51 | 48.3 / 48.5 | 61.4 / 61.6 |
| go-mysql | default | 8.96 / 8.79 | 21.8 / 21.9 | 53.5 / 53 | 25.6 / 25.9 |
| go-mysql | tuned | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a |
| java-connector-j | default | 53.7¹ / 53¹ | 67.7¹ / 69.2¹ | 76.2¹˒¹⁶ / 72.7¹˒¹⁶ | 96.6¹˒¹⁶ / 94.5¹˒¹⁶ |
| java-connector-j | tuned | 51.9¹ / 50.3¹˒¹⁶ | 69.1¹ / 69.7¹˒¹⁶ | 75.2¹˒¹⁶ / 70.9¹ | 92¹˒¹⁶ / 92.1¹ |
| java-mariadb-j | default | 8.77¹˒¹⁶ / 10.2¹˒¹⁶ | 14¹˒¹⁶ / 13.4¹˒¹⁶ | 21.3¹ / 21.3¹ | 32.2¹ / 30.9¹˒¹⁶ |
| java-mariadb-j | tuned | 10.4¹˒¹⁶ / 11.7¹˒¹⁶ | 11.5¹˒¹⁶ / 13¹˒¹⁶ | 21.6¹˒¹⁶ / 21.1¹˒¹⁶ | 30.7¹ / 31.5¹ |
| py-mysqlclient | default | n/a / n/a | 66.8 / 66.9 | n/a / n/a | 197 / 196 |
| py-mysql-connector-c | default | 107 / 108 | 95.4 / 95.5 | 262 / 261 | 242 / 241 |
| py-mariadb | default | 61.6 / 61.5 | 110 / 109 | 83.2 / 81.3 | 148 / 148 |
| py-pymysql | default | n/a / n/a | 272 / 273 | n/a / n/a | 503 / 501 |
| py-mysql-connector-pure | default | 393 / 391 | 252 / 251 | 651 / 649 | 469 / 469 |

¹ **Provisional (Java warm-up).** Measured with a fixed 5-iteration warm-up that did not reach steady state: the JIT compiler was still working during measured iterations (spread within a process 26-45%). A rerun with adaptive warm-up (until 3 iterations agree within 5%) is queued; treat these Java figures as provisional.  
¹⁶ **Higher run-to-run spread.** The 5 processes for this result differ by more than 5% (coefficient of variation). Small differences against it are not meaningful.  

### T5 — client CPU, ns/KB (Percona / MariaDB)

| stack | config | 100k-doc | 100k-doc+tls | 100k-doc_bin | 10k-doc | 10k-doc_bin | 1k-doc | 1k-doc_bin | mix-doc | mix-doc_bin | 10k-doc-parse |
|---|---|---|---|---|---|---|---|---|---|---|---|
| c-libmysqlclient | default | 241⁶ / 232 | 371⁶ / 353 | 231 / 237 | 218⁶ / 226 | 230 / 226 | 289⁶ / 284 | 284 / 283¹⁶ | 215⁶ / 193 | 193 / 191 | n/a⁶ / n/a |
| c-mariadb-connc | default | 295⁶ / 274 | 429⁶ / 392 | 278 / 281 | 335⁶ / 303 | 305 / 312 | 367⁶ / 370 | 367 / 366¹⁶ | 276⁶ / 244 | 244 / 241 | n/a⁶ / n/a |
| go-sql-driver | default | 184⁶ / 147 | 375⁶ / 388 | 148 / 147 | 332⁶ / 255 | 257 / 256 | 526⁶ / 480 | 485 / 485 | 264⁶ / 199 | 199 / 199 | 16,364⁶ / 17,641 |
| go-sql-driver | tuned | 185⁶ / 147 | 373⁶ / 387 | 149 / 148 | 332⁶ / 254 | 257 / 257 | 522⁶ / 477 | 479 / 484 | 264⁶ / 199 | 199 / 199 | 16,378⁶ / 17,576 |
| go-mysql | default | 237⁶ / 225 | 439⁶ / 403 | 223 / 226 | 349⁶˒¹⁶ / 265 | 266 / 268 | 424⁶ / 380 | 377 / 382 | 251⁶ / 204 | 196 / 201 | 14,796⁶ / 16,069 |
| go-mysql | tuned | n/a⁶ / n/a | n/a⁶ / n/a | n/a / n/a | n/a⁶ / n/a | n/a / n/a | n/a⁶ / n/a | n/a / n/a | n/a⁶ / n/a | n/a / n/a | n/a⁶ / n/a |
| java-connector-j | default | 186¹˒⁶˒⁸ / 197¹ | 417¹˒⁶˒⁸ / 443¹ | 185¹ / 187¹ | 428¹˒⁶˒⁸ / 518¹ | 538¹ / 531¹ | 2,409¹˒⁶˒⁸˒¹⁶ / 1,594¹ | 1,594¹ / 1,542¹˒¹⁶ | 403¹˒⁶˒⁸ / 528¹ | 506¹ / 481¹˒¹⁶ | n/a¹˒⁶ / n/a¹ |
| java-connector-j | tuned | 183¹˒⁶˒⁸ / 192¹ | 421¹˒⁶˒⁸ / 449¹ | 184¹ / 185¹ | 413¹˒⁶˒⁸ / 493¹˒¹⁶ | 539¹ / 541¹ | 1,736¹˒⁶˒⁸˒¹⁶ / 1,809¹˒¹⁶ | 1,660¹˒¹⁶ / 1,615¹˒¹⁶ | 391¹˒⁶˒⁸˒¹⁶ / 524¹ | 492¹ / 495¹ | n/a¹˒⁶ / n/a¹ |
| java-mariadb-j | default | 191¹˒⁶˒⁸ / 191¹ | 419¹˒⁶˒⁸ / 451¹ | 182¹ / 185¹ | 329¹˒⁶˒⁸ / 397¹˒¹⁶ | 408¹ / 398¹ | 1,630¹˒⁶˒⁸˒¹⁶ / 1,372¹˒¹⁶ | 1,317¹˒¹⁶ / 1,259¹˒¹⁶ | 259¹˒⁶˒⁸ / 447¹ | 431¹ / 431¹ | n/a¹˒⁶ / n/a¹ |
| java-mariadb-j | tuned | 189¹˒⁶˒⁸ / 191¹ | 421¹˒⁶˒⁸ / 446¹ | 181¹ / 183¹ | 329¹˒⁶˒⁸ / 398¹ | 434¹ / 403¹ | 1,643¹˒⁶˒⁸ / 1,298¹˒¹⁶ | 1,310¹ / 1,344¹˒¹⁶ | 261¹˒⁶˒⁸ / 439¹ | 439¹ / 428¹ | n/a¹˒⁶ / n/a¹ |
| py-mysqlclient | default | 351⁶ / 354 | 477⁶ / 486 | 253 / 254 | 463⁶ / 462 | 349 / 350 | 736⁶ / 708 | 516 / 521 | 457⁶ / 349 | 232 / 232 | 3,962⁶ / 4,372 |
| py-mysql-connector-c | default | 376⁶ / 386 | 501⁶ / 499 | 274 / 269 | 515⁶ / 509 | 399 / 393 | 1,604⁶ / 1,599 | 1,346 / 1,350 | 519⁶ / 403 | 281 / 281 | 3,999⁶ / 4,296 |
| py-mariadb | default | 324⁶˒⁷ / 440 | 455⁶˒⁷ / 567 | 331 / 330 | 410⁶˒⁷ / 522 | 406 / 404 | 548⁶˒⁷ / 757 | 571 / 573 | 274⁶˒⁷ / 378 | 261 / 253 | 3,990⁶˒⁷ / 4,406 |
| py-pymysql | default | 497⁶ / 505 | 498⁶ / 508 | 461 / 463 | 627⁶ / 612 | 472 / 474 | 1,853⁶ / 1,927 | 1,641 / 1,650 | 656⁶ / 647 | 489 / 502 | 4,101⁶ / 4,436 |
| py-mysql-connector-pure | default | 418⁶ / 409 | 559⁶ / 563 | 263 / 252 | 785⁶ / 809 | 677 / 674 | 4,751⁶ / 5,100 | 4,786 / 4,838 | 854⁶ / 893 | 750 / 762 | 4,258⁶ / 4,583 |

¹ **Provisional (Java warm-up).** Measured with a fixed 5-iteration warm-up that did not reach steady state: the JIT compiler was still working during measured iterations (spread within a process 26-45%). A rerun with adaptive warm-up (until 3 iterations agree within 5%) is queued; treat these Java figures as provisional.  
⁶ **Percona converts JSON on every read.** Percona Server (like MySQL) stores JSON in a binary format and converts it to text on every read: about 13× the server CPU of the same bytes as LONGBLOB, and ~10% larger output. The slower send makes most clients spend more CPU per KB than reading the same documents from MariaDB, which stores JSON as text.  
⁷ **Returns JSON as bytes on Percona.** MariaDB Connector/Python returns Percona's JSON column as raw bytes (no UTF-8 decoding) but MariaDB's JSON column as a decoded string. Not comparable with other drivers or across servers.  
⁸ **Unexplained (Java JSON reads).** Both Java drivers read Percona's JSON column with less CPU per KB than the same bytes as BLOB, the opposite of every other language. Not yet explained; to be rechecked after the Java warm-up rerun and profiled if it persists.  
¹⁶ **Higher run-to-run spread.** The 5 processes for this result differ by more than 5% (coefficient of variation). Small differences against it are not meaningful.  

### T6 — client CPU, µs/1000-row stmt (Percona / MariaDB)

| stack | config | multiparam | sqltext | batch |
|---|---|---|---|---|
| c-libmysqlclient | default | 65.9 / 59 | 268 / 268 | n/a / n/a |
| c-mariadb-connc | default | 54 / 53.2 | 249 / 250 | n/a¹⁰ / 59.1¹⁰ |
| go-sql-driver | default | 312¹³ / 310¹³ | 259 / 257 | n/a / n/a |
| go-sql-driver | tuned | 225 / 226 | 258 / 257 | n/a / n/a |
| go-mysql | default | 277 / 269 | 282 / 280 | n/a / n/a |
| go-mysql | tuned | n/a / n/a | n/a / n/a | n/a / n/a |
| java-connector-j | default | 484¹ / 459¹ | 292¹ / 230¹˒¹⁶ | 5,654¹˒¹¹ / 5,605¹˒¹¹ |
| java-connector-j | tuned | 345¹ / 296¹ | 322¹ / 237¹˒¹⁶ | 1,572¹˒¹¹ / 1,548¹˒¹¹ |
| java-mariadb-j | default | 158¹ / 159¹ | 104¹ / 111¹˒¹⁶ | 4,024¹˒¹⁰ / 189¹˒¹⁰ |
| java-mariadb-j | tuned | 116¹˒¹⁶ / 114¹ | 102¹ / 115¹˒¹⁶ | 3,959¹˒¹⁰ / 195¹˒¹⁰ |
| py-mysqlclient | default | 1,811 / 1,837 | 813 / 821 | 2,326 / 2,351 |
| py-mysql-connector-c | default | 1,208 / 1,219 | 806 / 814 | 2,079 / 2,098 |
| py-mariadb | default | 1,351 / 1,396 | 608 / 612 | 13,733¹⁰ / 608¹⁰˒¹⁶ |
| py-pymysql | default | 1,598 / 1,610 | 781 / 778 | 2,151 / 2,171 |
| py-mysql-connector-pure | default | 3,143 / 3,177 | 959 / 965 | 4,628 / 4,729 |

¹ **Provisional (Java warm-up).** Measured with a fixed 5-iteration warm-up that did not reach steady state: the JIT compiler was still working during measured iterations (spread within a process 26-45%). A rerun with adaptive warm-up (until 3 iterations agree within 5%) is queued; treat these Java figures as provisional.  
¹⁰ **MariaDB-only bulk protocol.** On MariaDB this uses the bulk-execute protocol (COM_STMT_BULK_EXECUTE). Percona Server does not have it, so the driver falls back to one execute per row there, or the test is n/a.  
¹¹ **Connector/J batch defaults.** With default settings Connector/J's executeBatch() sends one INSERT per row; rewriteBatchedStatements=true (tuned) rewrites the batch into multi-row INSERTs.  
¹³ **Three round trips per parameterized query.** Without client-side interpolation (go-sql-driver: interpolateParams=true, tuned) each parameterized call prepares, executes and closes a server-side statement.  
¹⁶ **Higher run-to-run spread.** The 5 processes for this result differ by more than 5% (coefficient of variation). Small differences against it are not meaningful.  
