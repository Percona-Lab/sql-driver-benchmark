# Phase 1 report — C, Go, Java, Python

> **AI-generated results.** This benchmark was designed, run and analyzed with an AI assistant (Claude). Results and findings have been spot-checked by a person, but not every number and explanation has been verified in detail, and some may be wrong. The code and raw data are published so you can verify anything here; please report problems as [issues](https://github.com/Percona-Lab/sql-driver-benchmark/issues).

Run: 2026-11-17 → 2026-11-21 on one bare-metal host (EPYC 4245P, client alone on an isolated core, 3.9 GHz fixed), Percona
Server 9.7.2-3 and MariaDB 12.3.4 with identical configuration. Java was rerun with adaptive warm-up and PyMySQL with TLS
actually disabled; see "Corrections".

All numbers are **client CPU per operation** (user + kernel, whole process, GC and JIT threads included), median of 5
fresh processes, in steady state, shown as **Percona / MariaDB**; memory tables come from a separate memory pass.
Interactive version: https://percona-lab.github.io/sql-driver-benchmark/ · Method: [SPEC.md](../SPEC.md) ·
host pitfalls we found and fixed: [measurement-pitfalls](../docs/measurement-pitfalls.md).

**Memory measures.** *Memory for the work* is the peak resident memory during a measured iteration minus the memory at its
start. It reads near zero when a runtime keeps freed memory between iterations (Python's allocator, garbage-collected heaps),
so for those *memory growth* is the better measure: the highest peak minus the memory right after connecting, before warm-up.
Growth of JIT/GC runtimes includes heap the runtime chose to keep (the JVM sizes its heap up to a quarter of RAM by default).

## Corrections to the first version of this report

- **PyMySQL was not slow to connect.** PyMySQL negotiates TLS by default whenever the server offers it, and the first runner
  did not turn that off, so every non-TLS PyMySQL result ran over TLS. With `ssl_disabled=True` a plain connect costs
  **64.4 µs**; with its TLS default it costs 3,738 µs. The orchestrator
  now fails any result whose negotiated TLS state differs from the intended one.
- **Java numbers were not steady state.** A fixed 5-iteration warm-up left the JIT compiler working during measured
  iterations (26–45% spread within a process). Runners now warm up until three iterations agree within 5%; Java numbers
  moved by up to 60% (Connector/J app-built bulk insert 108 µs per 1,000 rows, previously
  292). The "unexplained Java JSON" result was an artifact of this and is gone.

## Key findings

**Connections**
- Plain TCP connect: libmysqlclient 23.9 µs, go-sql-driver 31.6,
  MariaDB Connector/Python 31.8, MariaDB Connector/J 57.1,
  Connector/J 71.6.
- **TLS without a CA file costs 3,598 µs per connect in libmysqlclient** (vs
  727 µs with a CA file): it loads and parses the full system CA bundle on every
  connection. The same holds for every driver built on libmysqlclient or MariaDB Connector/C.
- **MariaDB 12.3 forces TLS key exchange to ECDH P-521; Percona Server uses P-256.** go-sql-driver needs
  284 µs per TLS connect to Percona and 2,557 µs to MariaDB.
- Go has the cheapest TLS here: go-sql-driver verified TLS 395 µs; Connector/J
  4,233 µs.

**Point selects**
- libmysqlclient 4.32 µs, MariaDB Connector/J 4.22,
  go-sql-driver 5.89, mysqlclient 6.4, PyMySQL
  12.4, pure-Python mysql-connector 26.2.
- **go-sql-driver's parameterized query: 13.4 µs by default** (prepare + execute + close per
  call), 6.04 µs with `interpolateParams`.

**Large result sets (1M ints, buffered text protocol)**
- **MariaDB Connector/J 26.1 ns/row, cheaper than libmysqlclient
  (37.1 ns):** it keeps the raw bytes and converts only on `getInt()`, while
  libmysqlclient copies every row into its own structures (310 vs 736 instructions per row). Connector/J
  268 ns.
- **libmysqlclient over TLS: 78.3 ns/row** (two `SSL_read` calls per row);
  MariaDB Connector/C 38 ns.
- Python: MariaDB Connector/Python 196 ns/row, mysqlclient
  218, PyMySQL 1,125, pure-Python mysql-connector
  2,446.
- Memory for the buffered result: libmysqlclient 30.3 MB, mysqlclient
  149 MB, pure-Python mysql-connector 205 MB;
  streaming needs almost none. Process growth: libmysqlclient 45.8 MB,
  Connector/J 1,393 MB (mostly default JVM heap sizing).

**Large values**
- **MySQL/Percona Server converts JSON from binary to text on every read** (~13× the server CPU of the same bytes as
  LONGBLOB, ~10% larger output); most clients spend more CPU per KB reading it than from MariaDB. A storage trade-off,
  not analyzed further. MariaDB Connector/Python returns Percona's JSON as raw bytes (no decoding), so its JSON figures
  are not comparable.

**Bulk insert (1,000-row statements)**
- Connector/J `executeBatch()`: 5,665 µs per 1,000 rows on defaults,
  1,504 µs with `rewriteBatchedStatements`.
- MariaDB's bulk protocol: MariaDB Connector/Python `executemany` 608 µs on MariaDB,
  13,733 µs on Percona (one execute per row).

## Tables

Superscript numbers mark results with a note; the notes follow each table.

### T1 — client CPU, µs/connect (Percona / MariaDB)

| stack | config | socket | tcp | tls | tls-resume | tls-verify | tls-verify-resume | tcp@ed25519 |
|---|---|---|---|---|---|---|---|---|
| c-libmysqlclient | default | 11.3³ / 10.5³ | 23.9³ / 21.3³ | 3,598² / 3,876¹˒² | 3,513² / 3,879¹˒² | 727 / 1,020¹ | 611 / 1,021¹ | n/a / n/a |
| c-mariadb-connc | default | 12³˒⁴ / 10.8³˒⁴ | 25.6³˒⁴ / 22.8³˒⁴ | 3,586²˒⁴ / 3,797¹˒²˒⁴ | n/a²˒⁴ / n/a¹˒²˒⁴ | 669⁴ / 958¹˒⁴ | n/a⁴ / n/a¹˒⁴ | n/a⁴ / 69.2⁴ |
| go-sql-driver | default | 17.3³ / 14.5³ | 31.6³ / 26.7³ | 284 / 2,557¹ | 233 / 2,560¹ | 395 / 2,617¹ | 236 / 2,624¹ | n/a / n/a¹⁰ |
| go-sql-driver | tuned | 17.2³ / 14.5³ | 31.7³ / 26.6³ | 285 / 2,557¹ | 233 / 2,562¹ | 395 / 2,618¹ | 236 / 2,622¹ | n/a / n/a¹⁰ |
| go-mysql | default | 25³ / 22.4³ | 39.4³ / 34.7³ | 314 / 2,606¹ | 265 / 2,608¹ | 452 / 2,690¹ | 292 / 2,701¹ | n/a / 69.5 |
| java-connector-j | default | n/a³ / n/a³ | 71.6³ / 67.2³ | 1,527¹⁵ / 7,421¹ | n/a / n/a¹ | 4,233 / 9,653¹˒¹⁶ | n/a / n/a¹ | n/a / n/a |
| java-connector-j | tuned | n/a³ / n/a³ | 55.4³ / 51.4³ | 1,699¹⁵ / 7,562¹ | n/a / n/a¹ | 4,213 / 10,152¹ | n/a / n/a¹ | n/a / n/a |
| java-mariadb-j | default | 40.1³ / 34.6³ | 57.1³ / 49.7³ | 1,466¹⁵ / 7,143¹ | n/a / n/a¹ | 1,630¹⁵ / 7,186¹ | n/a / n/a¹ | n/a / 146 |
| java-mariadb-j | tuned | 53.6³ / 48.1³ | 71.5³ / 63.2³ | 1,512¹⁵ / 6,972¹˒¹⁵ | n/a / n/a¹ | 1,561¹⁵ / 7,047¹˒¹⁵ | n/a / n/a¹ | n/a / 161 |
| py-mysqlclient | default | 29.6³ / 28.9³ | 46.6³ / 44.4³ | 3,684² / 3,954¹˒² | n/a² / n/a¹˒² | 816 / 1,103¹ | n/a / n/a¹ | n/a / n/a |
| py-mysql-connector-c | default | 42.4³ / 41.7³ | 65³ / 62.1³ | 3,730² / 4,004¹˒² | n/a² / n/a¹˒² | 856 / 1,148¹ | n/a / n/a¹ | n/a / n/a |
| py-mariadb | default | 16.2³˒⁴ / 15³˒⁴ | 31.8³˒⁴ / 29.1³˒⁴ | 3,637²˒⁴ / 3,867¹˒²˒⁴ | n/a²˒⁴ / n/a¹˒²˒⁴ | 718⁴ / 1,011¹˒⁴ | n/a⁴ / n/a¹˒⁴ | n/a⁴ / 76⁴ |
| py-pymysql | default | 38³˒¹³ / 35.6³˒¹³ | 64.4³˒¹³ / 57.4³˒¹³ | 3,738¹³ / 4,012¹˒¹³ | n/a / n/a¹ | 873 / 1,163¹ | n/a / n/a¹ | n/a¹³ / 109¹³ |
| py-mysql-connector-pure | default | 96.4³ / 89.3³ | 128³ / 117³ | 7,289 / 7,555¹ | n/a / n/a¹ | 7,363 / 7,638¹ | n/a / n/a¹ | n/a / n/a |

¹ **MariaDB TLS key exchange.** MariaDB 12.3 negotiates ECDH on P-521 (secp521r1); Percona Server uses P-256. Much of the extra client CPU per TLS connect on MariaDB is that server-side choice, not the driver.  
² **TLS without a CA loads the system trust store.** With no CA configured, libmysqlclient, MariaDB Connector/C and the drivers built on them (Connector/C++, mysqlclient, MariaDB Connector/Python, Ruby mysql2) and trilogy load and parse the full system CA bundle (120 certificates) on every connection although they verify nothing.  
³ **Different default authentication.** Each server uses its own default authentication: Percona Server caching_sha2_password (SHA-256 plus an extra round trip on the fast path), MariaDB mysql_native_password. Part of the Percona-vs-MariaDB difference in plain connect cost comes from this, not the driver.  
⁴ **Connector/C sleeps after connect().** MariaDB Connector/C calls usleep(1) after every connect() (about 50 µs on Linux). This adds wall time per connection, not CPU.  
¹⁰ **Fails, not unsupported.** go-sql-driver advertises ed25519 support but fails against MariaDB 12.3 with "malformed packet" (go-mysql works with the same account). A driver bug, not a missing feature.  
¹³ **PyMySQL enables TLS by default.** Without TLS options PyMySQL negotiates TLS whenever the server offers it, creating a TLS context and loading the system CA bundle on every connection (about 3.7 ms of CPU). The non-TLS results here pass ssl_disabled=True. An earlier version of this report showed PyMySQL's TLS-by-default cost as its plain connect cost; that was a mistake in the benchmark, corrected on 2026-11-21.  
¹⁵ **Higher run-to-run spread.** The 5 processes for this result differ by more than 5% (coefficient of variation). Small differences against it are not meaningful.  
¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  

### T2 — client CPU, µs/query (Percona / MariaDB)

| stack | config | literal | prepared | param |
|---|---|---|---|---|
| c-libmysqlclient | default | 4.32 / 4.09 | 4.23 / 4.19 | n/a / n/a |
| c-mariadb-connc | default | 4.48 / 4.3 | 4.27 / 4.2 | n/a / n/a |
| go-sql-driver | default | 5.89 / 6.09 | 6.34 / 6.2 | 13.4¹¹ / 13.4¹¹ |
| go-sql-driver | tuned | 5.94 / 6.08 | 6.3 / 6.21 | 6.04 / 6.26 |
| go-mysql | default | 5.76 / 5.89 | 5.84 / 5.7 | 13.2¹² / 13.1¹² |
| java-connector-j | default | 6.83 / 6.69 | 6.14 / 5.97 | 6.11 / 6.02 |
| java-connector-j | tuned | 6.61 / 6.46 | 5.98 / 5.81 | 5.99 / 5.82 |
| java-mariadb-j | default | 4.22 / 4.15 | 4.27 / 4.15 | 4.24 / 4.19 |
| java-mariadb-j | tuned | 4.22 / 4.1 | 4.29 / 4.15 | 4.28 / 4.14 |
| py-mysqlclient | default | 6.4 / 6.36 | n/a / n/a | 6.99 / 6.95 |
| py-mysql-connector-c | default | 10.7 / 10.7 | 14.5 / 14.5 | 11.6 / 11.6 |
| py-mariadb | default | 5.92 / 5.98 | 13.1 / 12 | 6.66 / 6.69 |
| py-pymysql | default | 12.4 / 12.2 | n/a / n/a | 13.3 / 13 |
| py-mysql-connector-pure | default | 26.2 / 25 | 37.9 / 38.2 | 30.6 / 29.8 |

¹¹ **Three round trips per parameterized query.** Without client-side interpolation (go-sql-driver: interpolateParams=true, tuned) each parameterized call prepares, executes and closes a server-side statement.  
¹² **Three round trips per parameterized query.** go-mysql's Conn.Execute(sql, args...) prepares, executes and closes a server-side statement on every call.  

### T3 — client CPU, ns/row (Percona / MariaDB)

| stack | config | binary-buffered | binary-streamed | text-buffered | text-buffered+tls | text-streamed | text-streamed+tls |
|---|---|---|---|---|---|---|---|
| c-libmysqlclient | default | 26.8 / 26.8 | 24.6 / 25 | 37.1 / 37 | 78.3⁷ / 78.5⁷ | 28.1 / 28.1 | 69.4⁷ / 69.5⁷ |
| c-mariadb-connc | default | 33.5 / 34.9 | 25.4 / 25.4 | 38.1 / 38 | 38 / 37.8 | 28.8 / 29.3 | 29.4 / 29.5 |
| go-sql-driver | default | n/a / n/a | 85.7 / 85.5 | n/a / n/a | n/a / n/a | 101 / 100 | 103 / 105 |
| go-sql-driver | tuned | n/a / n/a | 85.8 / 85.6 | n/a / n/a | n/a / n/a | 101 / 101 | 102 / 107 |
| go-mysql | default | 69.3 / 69.8 | 65.7 / 65.9 | 83.4 / 83.1 | 84.3 / 85.7 | 78.7 / 81.4 | 80.6 / 83.9 |
| java-connector-j | default | 253 / 254 | 143 / 143 | 268 / 272 | 259¹⁵˒¹⁶ / 236¹⁵ | 149 / 149 | 150 / 148 |
| java-connector-j | tuned | 223 / 220 | 121 / 121 | 233 / 242¹⁵ | 172¹⁵˒¹⁶ / 149¹⁵ | 120 / 120 | 125 / 120 |
| java-mariadb-j | default | 33.3 / 31.9¹⁵ | 19.2 / 19.8 | 26.1 / 26.3 | 27.7¹⁵ / 27.5 | 16.7 / 16.6 | 19.2 / 19.4 |
| java-mariadb-j | tuned | 33.3 / 33.5 | 19.5 / 19.2 | 26 / 26.4 | 28.4 / 28 | 16.5 / 16.7 | 19 / 19.4¹⁵ |
| py-mysqlclient | default | n/a / n/a | n/a / n/a | 218 / 219 | 260 / 260 | 320 / 319 | 425 / 427 |
| py-mysql-connector-c | default | 1,300 / 1,313 | 1,291 / 1,321 | 500 / 506 | 575 / 585 | 989 / 999 | 1,102 / 1,118 |
| py-mariadb | default | 306 / 305 | 400 / 409 | 196 / 197 | 196 / 197 | 396 / 401 | 402 / 405 |
| py-pymysql | default | n/a / n/a | n/a / n/a | 1,125 / 1,121 | 1,090 / 1,110 | 1,191 / 1,194 | 1,169 / 1,188 |
| py-mysql-connector-pure | default | 3,805 / 3,793 | 3,827 / 3,804 | 2,446 / 2,426 | 2,384 / 2,364 | 3,743 / 3,719 | 3,725 / 3,725 |

⁷ **Two TLS reads per row.** libmysqlclient issues two SSL_read calls per row (2M for 1M rows; MariaDB Connector/C about 700), so TLS doubles its per-row cost.  
¹⁵ **Higher run-to-run spread.** The 5 processes for this result differ by more than 5% (coefficient of variation). Small differences against it are not meaningful.  
¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  

### T4 — client CPU, ns/cell (Percona / MariaDB)

| stack | config | int-binary | int-text | mix-binary | mix-text |
|---|---|---|---|---|---|
| c-libmysqlclient | default | 7.07 / 7.08 | 15.3 / 15.2 | 11.1 / 11.1 | 14.5 / 14.5 |
| c-mariadb-connc | default | 8.05 / 8.01 | 16.7 / 16.5 | 13.8 / 13.6 | 16.2 / 16.7 |
| go-sql-driver | default | 35.4 / 35.2 | 50.3 / 50.7 | 48.6 / 48.6 | 61.9 / 61.9 |
| go-sql-driver | tuned | 35.4 / 35.3 | 50.4 / 51 | 48.3 / 48.5 | 61.4 / 61.6 |
| go-mysql | default | 8.96 / 8.79 | 21.8 / 21.9 | 53.5 / 53 | 25.6 / 25.9 |
| java-connector-j | default | 67.1 / 67.7 | 72.4 / 71.4 | 76.1¹⁵˒¹⁶ / 87.6¹⁵ | 87.3 / 87.4¹⁵ |
| java-connector-j | tuned | 66.1 / 66.9 | 75.2 / 76.5¹⁵ | 75.2¹⁵˒¹⁶ / 66.5¹⁵˒¹⁶ | 84.9¹⁶ / 88.3 |
| java-mariadb-j | default | 7.74¹⁵ / 7.39 | 8.74 / 8.47 | 24.6 / 25 | 33.3¹⁵ / 33.2¹⁵ |
| java-mariadb-j | tuned | 8.05¹⁵ / 11¹⁵ | 8.54 / 8.65 | 23.7 / 24.6¹⁵ | 32.5 / 30.7 |
| py-mysqlclient | default | n/a / n/a | 66.8 / 66.9 | n/a / n/a | 197 / 196 |
| py-mysql-connector-c | default | 107 / 108 | 95.4 / 95.5 | 262 / 261 | 242 / 241 |
| py-mariadb | default | 61.6 / 61.5 | 110 / 109 | 83.2 / 81.3 | 148 / 148 |
| py-pymysql | default | n/a / n/a | 276 / 276 | n/a / n/a | 504 / 504 |
| py-mysql-connector-pure | default | 393 / 391 | 252 / 251 | 651 / 649 | 469 / 469 |

¹⁵ **Higher run-to-run spread.** The 5 processes for this result differ by more than 5% (coefficient of variation). Small differences against it are not meaningful.  
¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  

### T5 — client CPU, ns/KB (Percona / MariaDB)

| stack | config | 100k-doc | 100k-doc+tls | 100k-doc_bin | 10k-doc | 10k-doc_bin | 1k-doc | 1k-doc_bin | mix-doc | mix-doc_bin | 10k-doc-parse |
|---|---|---|---|---|---|---|---|---|---|---|---|
| c-libmysqlclient | default | 241⁵ / 232 | 371⁵ / 353 | 231 / 237 | 218⁵ / 226 | 230 / 226 | 289⁵ / 284 | 284 / 283¹⁵ | 215⁵ / 193 | 193 / 191 | n/a⁵ / n/a |
| c-mariadb-connc | default | 295⁵ / 274 | 429⁵ / 392 | 278 / 281 | 335⁵ / 303 | 305 / 312 | 367⁵ / 370 | 367 / 366¹⁵ | 276⁵ / 244 | 244 / 241 | n/a⁵ / n/a |
| go-sql-driver | default | 184⁵ / 147 | 375⁵ / 388 | 148 / 147 | 332⁵ / 255 | 257 / 256 | 526⁵ / 480 | 485 / 485 | 264⁵ / 199 | 199 / 199 | 16,364⁵ / 17,641 |
| go-sql-driver | tuned | 185⁵ / 147 | 373⁵ / 387 | 149 / 148 | 332⁵ / 254 | 257 / 257 | 522⁵ / 477 | 479 / 484 | 264⁵ / 199 | 199 / 199 | 16,378⁵ / 17,576 |
| go-mysql | default | 237⁵ / 225 | 439⁵ / 403 | 223 / 226 | 349⁵˒¹⁵ / 265 | 266 / 268 | 424⁵ / 380 | 377 / 382 | 251⁵ / 204 | 196 / 201 | 14,796⁵ / 16,069 |
| java-connector-j | default | 205⁵ / 208 | 435⁵ / 466 | 200 / 198 | 397⁵˒¹⁵ / 392 | 385¹⁵ / 376 | 555⁵˒¹⁵ / 1,601¹⁵ | 578¹⁵˒¹⁶ / 1,226¹⁵˒¹⁶ | 344⁵ / 336¹⁵ | 325¹⁵ / 308¹⁵ | n/a⁵ / n/a |
| java-connector-j | tuned | 204⁵ / 209 | 436⁵ / 467 | 198 / 193 | 393⁵ / 384¹⁵˒¹⁶ | 371¹⁵ / 377¹⁵ | 612⁵˒¹⁵˒¹⁶ / 1,528¹⁵˒¹⁶ | 724¹⁵˒¹⁶ / 627¹⁵˒¹⁶ | 345⁵ / 347 | 313¹⁵ / 327¹⁵˒¹⁶ | n/a⁵ / n/a |
| java-mariadb-j | default | 331⁵ / 363 | 588⁵ / 608 | 326 / 300 | 416⁵ / 402¹⁵ | 394 / 394¹⁵ | 454⁵˒¹⁵ / 768¹⁵ | 543¹⁵˒¹⁶ / 1,107¹⁵ | 327⁵ / 312 | 299 / 301 | n/a⁵ / n/a |
| java-mariadb-j | tuned | 350⁵ / 352 | 587⁵ / 604 | 330 / 330 | 414⁵ / 401¹⁵ | 372 / 368¹⁵ | 392⁵˒¹⁵ / 369¹⁵ | 509¹⁵ / 371¹⁵ | 328⁵ / 310 | 303¹⁵ / 298¹⁵ | n/a⁵ / n/a |
| py-mysqlclient | default | 351⁵ / 354 | 477⁵ / 486 | 253 / 254 | 463⁵ / 462 | 349 / 350 | 736⁵ / 708 | 516 / 521 | 457⁵ / 349 | 232 / 232 | 3,962⁵ / 4,372 |
| py-mysql-connector-c | default | 376⁵ / 386 | 501⁵ / 499 | 274 / 269 | 515⁵ / 509 | 399 / 393 | 1,604⁵ / 1,599 | 1,346 / 1,350 | 519⁵ / 403 | 281 / 281 | 3,999⁵ / 4,296 |
| py-mariadb | default | 324⁵˒⁶ / 440 | 455⁵˒⁶ / 567 | 331 / 330 | 410⁵˒⁶ / 522 | 406 / 404 | 548⁵˒⁶ / 757 | 571 / 573 | 274⁵˒⁶ / 378 | 261 / 253 | 3,990⁵˒⁶ / 4,406 |
| py-pymysql | default | 347⁵ / 333 | 498⁵ / 505 | 280 / 286 | 531⁵ / 464 | 410 / 406 | 1,800⁵ / 1,708 | 1,450 / 1,458 | 511⁵ / 458 | 314 / 313 | 3,981⁵ / 4,235 |
| py-mysql-connector-pure | default | 418⁵ / 409 | 559⁵ / 563 | 263 / 252 | 785⁵ / 809 | 677 / 674 | 4,751⁵ / 5,100 | 4,786 / 4,838 | 854⁵ / 893 | 750 / 762 | 4,258⁵ / 4,583 |

⁵ **Percona converts JSON on every read.** Percona Server (like MySQL) stores JSON in a binary format and converts it to text on every read: about 13× the server CPU of the same bytes as LONGBLOB, and ~10% larger output. The slower send makes most clients spend more CPU per KB than reading the same documents from MariaDB, which stores JSON as text.  
⁶ **Returns JSON as bytes on Percona.** MariaDB Connector/Python returns Percona's JSON column as raw bytes (no UTF-8 decoding) but MariaDB's JSON column as a decoded string. Not comparable with other drivers or across servers.  
¹⁵ **Higher run-to-run spread.** The 5 processes for this result differ by more than 5% (coefficient of variation). Small differences against it are not meaningful.  
¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  

### T6 — client CPU, µs/1000-row stmt (Percona / MariaDB)

| stack | config | multiparam | sqltext | batch |
|---|---|---|---|---|
| c-libmysqlclient | default | 65.9 / 59 | 268 / 268 | n/a / n/a |
| c-mariadb-connc | default | 54 / 53.2 | 249 / 250 | n/a⁸ / 59.1⁸ |
| go-sql-driver | default | 312¹¹ / 310¹¹ | 259 / 257 | n/a / n/a |
| go-sql-driver | tuned | 225 / 226 | 258 / 257 | n/a / n/a |
| go-mysql | default | 277 / 269 | 282 / 280 | n/a / n/a |
| java-connector-j | default | 397 / 389 | 108 / 105¹⁵ | 5,665⁹ / 5,505⁹ |
| java-connector-j | tuned | 293 / 268 | 106 / 98¹⁵ | 1,504⁹ / 1,422⁹ |
| java-mariadb-j | default | 132 / 131 | 81.6 / 80.1 | 3,957⁸ / 114⁸ |
| java-mariadb-j | tuned | 99.7 / 104 | 80.9 / 80 | 3,890⁸ / 116⁸ |
| py-mysqlclient | default | 1,811 / 1,837 | 813 / 821 | 2,326 / 2,351 |
| py-mysql-connector-c | default | 1,208 / 1,219 | 806 / 814 | 2,079 / 2,098 |
| py-mariadb | default | 1,351 / 1,396 | 608 / 612 | 13,733⁸ / 608⁸˒¹⁵ |
| py-pymysql | default | 1,613 / 1,618 | 807 / 803 | 2,159 / 2,177 |
| py-mysql-connector-pure | default | 3,143 / 3,177 | 959 / 965 | 4,628 / 4,729 |

⁸ **MariaDB-only bulk protocol.** On MariaDB this uses the bulk-execute protocol (COM_STMT_BULK_EXECUTE). Percona Server does not have it, so the driver falls back to one execute per row there, or the test is n/a.  
⁹ **Connector/J batch defaults.** With default settings Connector/J's executeBatch() sends one INSERT per row; rewriteBatchedStatements=true (tuned) rewrites the batch into multi-row INSERTs.  
¹¹ **Three round trips per parameterized query.** Without client-side interpolation (go-sql-driver: interpolateParams=true, tuned) each parameterized call prepares, executes and closes a server-side statement.  
¹⁵ **Higher run-to-run spread.** The 5 processes for this result differ by more than 5% (coefficient of variation). Small differences against it are not meaningful.  

### T3 — memory for the work, MB (Percona / MariaDB)

| stack | config | binary-buffered | binary-streamed | text-buffered | text-buffered+tls | text-streamed | text-streamed+tls |
|---|---|---|---|---|---|---|---|
| c-libmysqlclient | default | 18.8 / 18.8 | 0 / 0 | 30.3 / 30.3 | 30.3⁷ / 30.2⁷ | 0 / 0 | 0⁷ / 0⁷ |
| c-mariadb-connc | default | 30.3 / 30.3 | 0 / 0 | 45.6 / 45.6 | 45.6 / 45.6 | 0 / 0 | 0 / 0 |
| go-sql-driver | default | n/a / n/a | 0 / 0 | n/a / n/a | n/a / n/a | 0.0508 / 0.0625 | 0 / 0 |
| go-sql-driver | tuned | n/a / n/a | 0 / 0 | n/a / n/a | n/a / n/a | 0.0664 / 0 | 0.0742 / 0 |
| go-mysql | default | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0.0703 / 0 | 0.0703 / 0 |
| java-connector-j | default | 99.7 / 99.7 | 0 / 0 | 98 / 99.7 | 101 / 97.4 | 0.125 / 0.105 | 0 / 0 |
| java-connector-j | tuned | 97.2 / 99.7 | 0 / 0 | 97.8 / 99.8 | 0¹⁶ / 99.6 | 0.113 / 0.121 | 0 / 0 |
| java-mariadb-j | default | 13.3 / 13.3 | 0 / 0 | 13.3 / 13.4 | 11.3 / 11.4 | 0 / 0 | 0 / 0 |
| java-mariadb-j | tuned | 13.3 / 13.3 | 0 / 0 | 13.3 / 13.3 | 11.3 / 11.1 | 0 / 0 | 0 / 0 |
| py-mysqlclient | default | n/a / n/a | n/a / n/a | 149 / 149 | 149 / 149 | 0 / 0 | 0 / 0 |
| py-mysql-connector-c | default | 0 / 0 | 0 / 0 | 87.9 / 87.9 | 87.9 / 87.9 | 0 / 0 | 0 / 0 |
| py-mariadb | default | 30.3 / 30.2 | 0 / 0 | 45.4 / 45.5 | 45.6 / 45.6 | 0 / 0 | 0 / 0 |
| py-pymysql | default | n/a / n/a | n/a / n/a | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| py-mysql-connector-pure | default | 0 / 0 | 0 / 0 | 205 / 205 | 205 / 205 | 0 / 0 | 0 / 0 |

⁷ **Two TLS reads per row.** libmysqlclient issues two SSL_read calls per row (2M for 1M rows; MariaDB Connector/C about 700), so TLS doubles its per-row cost.  
¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  

### T4 — memory for the work, MB (Percona / MariaDB)

| stack | config | int-binary | int-text | mix-binary | mix-text |
|---|---|---|---|---|---|
| c-libmysqlclient | default | 2.62 / 2.62 | 9.88 / 9.88 | 10.1 / 10.1 | 15.3 / 15.3 |
| c-mariadb-connc | default | 4.1 / 4.11 | 15.3 / 15.3 | 15.2 / 15.2 | 26.4 / 26.4 |
| go-sql-driver | default | 0 / 0 | 0 / 0.0547 | 0 / 0 | 0 / 0 |
| go-sql-driver | tuned | 0 / 0 | 0 / 0.375 | 0 / 0.0938 | 0 / 0 |
| go-mysql | default | 0 / 0 | 0 / 0 | 5.55 / 0.0625 | 0 / 0 |
| java-connector-j | default | 23.6 / 23.6 | 23.7 / 23.7 | 0¹⁶ / 37.8 | 24.8 / 24.8 |
| java-connector-j | tuned | 23.6 / 23.6 | 25.3 / 25.2 | 0.113¹⁶ / 0¹⁶ | 35.6 / 24.8¹⁶ |
| java-mariadb-j | default | 0 / 0 | 0.0625 / 0 | 12 / 12.1 | 11.5 / 3.04 |
| java-mariadb-j | tuned | 0 / 0 | 0 / 0 | 12.2 / 11.8 | 7.93 / 8.82 |
| py-mysqlclient | default | n/a / n/a | 26.9 / 27 | n/a / n/a | 46.9 / 47 |
| py-mysql-connector-c | default | 0 / 0 | 26.9 / 26.9 | 0 / 0 | 37.9 / 38 |
| py-mariadb | default | 4.02 / 0 | 5.39 / 5.5 | 15.2 / 0 | 16.5 / 16.4 |
| py-pymysql | default | n/a / n/a | 0 / 0 | n/a / n/a | 0 / 0 |
| py-mysql-connector-pure | default | 0 / 0 | 77.7 / 77.9 | 0 / 0 | 107 / 107 |

¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  

### T5 — memory for the work, MB (Percona / MariaDB)

| stack | config | 100k-doc | 100k-doc+tls | 100k-doc_bin | 10k-doc | 10k-doc_bin | 1k-doc | 1k-doc_bin | mix-doc | mix-doc_bin | 10k-doc-parse |
|---|---|---|---|---|---|---|---|---|---|---|---|
| c-libmysqlclient | default | 84.4⁵ / 74.5 | 84.4⁵ / 74.4 | 74.5 / 74.5 | 6.13⁵ / 6.63 | 6.63 / 6.63 | 0.5⁵ / 0.375 | 0.375 / 0.375 | 5.88⁵ / 4.88 | 4.88 / 4.88 | n/a⁵ / n/a |
| c-mariadb-connc | default | 108⁵ / 96.9 | 108⁵ / 96.9 | 96.9 / 96.9 | 10.8⁵ / 9.81 | 9.81 / 9.81 | 0.828⁵ / 0.703 | 0.703 / 0.703 | 8.56⁵ / 7.69 | 7.69 / 7.69 | n/a⁵ / n/a |
| go-sql-driver | default | 0.0547⁵ / 0.105 | 0⁵ / 0.516 | 0 / 0 | 0⁵ / 0.414 | 0.258 / 0.469 | 0.102⁵ / 0 | 0.266 / 0 | 0.137⁵ / 0.145 | 0 / 0.105 | 5.37⁵ / 0 |
| go-sql-driver | tuned | 0⁵ / 0 | 0⁵ / 0.566 | 0 / 0 | 0⁵ / 0.262 | 0.348 / 0.328 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0.0625 | 0.109 / 0 | 1.65⁵ / 1 |
| go-mysql | default | 0⁵ / 0 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0 | 0 / 0 | 5.06⁵ / 0.5 |
| java-connector-j | default | 0⁵ / 0.0742 | 0⁵ / 0.0703 | 0 / 0 | 55⁵ / 41.1 | 40.6 / 39.8 | 0.0547⁵ / 0.391 | 0.156 / 0.715 | 31.9⁵ / 23.7 | 23.7 / 23.5 | n/a⁵ / n/a |
| java-connector-j | tuned | 0⁵ / 0.0781 | 0⁵ / 0.0703 | 0 / 0 | 55.3⁵ / 43.9 | 44.3 / 43.9 | 0.102⁵ / 0.234 | 0.512 / 0 | 31.1⁵ / 22.9 | 23.3 / 23.8 | n/a⁵ / n/a |
| java-mariadb-j | default | 421⁵ / 497 | 265⁵ / 85.7 | 249 / 279 | 124⁵ / 98.3 | 108 / 99.7 | 0⁵ / 0 | 0.148 / 0 | 81.5⁵ / 62.4 | 60.5 / 107 | n/a⁵ / n/a |
| java-mariadb-j | tuned | 271⁵ / 528 | 181⁵ / 527 | 278 / 301 | 128⁵ / 104 | 103 / 95.7 | 0⁵ / 0.0625 | 0 / 0 | 76.2⁵ / 59.8 | 59.7 / 59.7 | n/a⁵ / n/a |
| py-mysqlclient | default | 332⁵ / 275 | 299⁵ / 312 | 293 / 275 | 32.2⁵ / 29.2 | 29.2 / 29.2 | 2.94⁵ / 0 | 0 / 0 | 26.2⁵ / 0 | 0.0664 / 0 | 32.3⁵ / 29.2 |
| py-mysql-connector-c | default | 214⁵ / 194 | 215⁵ / 194 | 194 / 194 | 21.3⁵ / 19.3 | 19.3 / 19.3 | 1.81⁵ / 0.938 | 0.688 / 0.688 | 17.3⁵ / 0.562 | 0.465 / 0.465 | 21.2⁵ / 19.3 |
| py-mariadb | default | 323⁵˒⁶ / 293 | 323⁵˒⁶ / 292 | 292 / 293 | 32.4⁵˒⁶ / 29.6 | 29.4 / 29.6 | 0.523⁵˒⁶ / 0 | 0 / 0 | 6.02⁵˒⁶ / 0.625 | 1.52 / 0.375 | 32.5⁵˒⁶ / 29.6 |
| py-pymysql | default | 0.0625⁵ / 0 | 0.0625⁵ / 0 | 0.129 / 0.129 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0 |
| py-mysql-connector-pure | default | 217⁵ / 200 | 217⁵ / 200 | 198 / 198 | 21.3⁵ / 19.3 | 19.4 / 19.4 | 1.19⁵ / 0 | 0 / 0 | 17.8⁵ / 0.188 | 0.438 / 0.188 | 21.3⁵ / 19.3 |

⁵ **Percona converts JSON on every read.** Percona Server (like MySQL) stores JSON in a binary format and converts it to text on every read: about 13× the server CPU of the same bytes as LONGBLOB, and ~10% larger output. The slower send makes most clients spend more CPU per KB than reading the same documents from MariaDB, which stores JSON as text.  
⁶ **Returns JSON as bytes on Percona.** MariaDB Connector/Python returns Percona's JSON column as raw bytes (no UTF-8 decoding) but MariaDB's JSON column as a decoded string. Not comparable with other drivers or across servers.  

### T6 — memory for the work, MB (Percona / MariaDB)

| stack | config | multiparam | sqltext | batch |
|---|---|---|---|---|
| c-libmysqlclient | default | 0 / 0 | 0 / 0 | n/a / n/a |
| c-mariadb-connc | default | 0.688 / 0.688 | 0 / 0 | n/a⁸ / 0⁸ |
| go-sql-driver | default | 0¹¹ / 0¹¹ | 0.117 / 0 | n/a / n/a |
| go-sql-driver | tuned | 0 / 0 | 0.453 / 0.344 | n/a / n/a |
| go-mysql | default | 0.441 / 0.379 | 0.305 / 0 | n/a / n/a |
| java-connector-j | default | 0.852 / 0.742 | 0 / 0.109 | 0.0664⁹ / 0.191⁹ |
| java-connector-j | tuned | 0.172 / 0.387 | 0 / 0 | 0⁹ / 0⁹ |
| java-mariadb-j | default | 0.0586 / 0.0898 | 0 / 0.082 | 0.0508⁸ / 0.25⁸ |
| java-mariadb-j | tuned | 0 / 0 | 0.0781 / 0.082 | 0.16⁸ / 0.25⁸ |
| py-mysqlclient | default | 0 / 0 | 0 / 0 | 0 / 0 |
| py-mysql-connector-c | default | 0 / 0 | 0 / 0 | 0 / 0 |
| py-mariadb | default | 1.5 / 1.44 | 0 / 0 | 0⁸ / 0⁸ |
| py-pymysql | default | 0 / 0 | 0 / 0 | 0 / 0 |
| py-mysql-connector-pure | default | 0 / 0 | 0.18 / 0.0508 | 0 / 0 |

⁸ **MariaDB-only bulk protocol.** On MariaDB this uses the bulk-execute protocol (COM_STMT_BULK_EXECUTE). Percona Server does not have it, so the driver falls back to one execute per row there, or the test is n/a.  
⁹ **Connector/J batch defaults.** With default settings Connector/J's executeBatch() sends one INSERT per row; rewriteBatchedStatements=true (tuned) rewrites the batch into multi-row INSERTs.  
¹¹ **Three round trips per parameterized query.** Without client-side interpolation (go-sql-driver: interpolateParams=true, tuned) each parameterized call prepares, executes and closes a server-side statement.  

### T3 — memory growth since connect, MB (Percona / MariaDB)

| stack | config | binary-buffered | binary-streamed | text-buffered | text-buffered+tls | text-streamed | text-streamed+tls |
|---|---|---|---|---|---|---|---|
| c-libmysqlclient | default | 30.5 / 30.5 | 0.0703 / 0.0742 | 45.8 / 45.8 | 45.8⁷ / 45.7⁷ | 0.0703 / 0.0703 | 0.0625⁷ / 0.0625⁷ |
| c-mariadb-connc | default | 30.5 / 30.5 | 0.0703 / 0.0742 | 45.8 / 45.8 | 45.8 / 45.8 | 0.0625 / 0.0625 | 0.0625 / 0.0742 |
| go-sql-driver | default | n/a / n/a | 5.41 / 5.21 | n/a / n/a | n/a / n/a | 5.62 / 6.03 | 5.54 / 5.1 |
| go-sql-driver | tuned | n/a / n/a | 5.47 / 5.36 | n/a / n/a | n/a / n/a | 5.46 / 5.74 | 5.92 / 5.19 |
| go-mysql | default | 141 / 142 | 0.672 / 0.66 | 144 / 144 | 138 / 152 | 1.29 / 0.652 | 1.14 / 0.75 |
| java-connector-j | default | 1,404 / 1,405 | 25 / 24.7 | 1,393 / 1,403 | 1,948 / 1,954 | 24.3 / 24.3 | 26.8 / 33.8 |
| java-connector-j | tuned | 1,946 / 1,408 | 26.4 / 24.7 | 1,945 / 1,407 | 2,022¹⁶ / 1,988 | 24.8 / 24.3 | 36.3 / 30.6 |
| java-mariadb-j | default | 274 / 274 | 28.8 / 28.8 | 274 / 260 | 246 / 251 | 28.9 / 29.8 | 34.9 / 38.5 |
| java-mariadb-j | tuned | 274 / 276 | 28.4 / 29.7 | 274 / 263 | 247 / 245 | 29.1 / 29.8 | 34.9 / 28.6 |
| py-mysqlclient | default | n/a / n/a | n/a / n/a | 153 / 153 | 153 / 153 | 0.0781 / 0.0859 | 0.0625 / 0.0664 |
| py-mysql-connector-c | default | 0 / 0 | 0 / 0 | 99.6 / 99.6 | 99.5 / 99.5 | 0 / 0 | 0 / 0 |
| py-mariadb | default | 30.5 / 30.6 | 0.105 / 0.0977 | 45.7 / 45.8 | 45.7 / 45.8 | 0.082 / 0.0938 | 0.0703 / 0.082 |
| py-pymysql | default | n/a / n/a | n/a / n/a | 107 / 107 | 107 / 107 | 0.0703 / 0.0703 | 0.0625 / 0.0625 |
| py-mysql-connector-pure | default | 0 / 0 | 0 / 0 | 214 / 214 | 214 / 214 | 0 / 0 | 0 / 0 |

⁷ **Two TLS reads per row.** libmysqlclient issues two SSL_read calls per row (2M for 1M rows; MariaDB Connector/C about 700), so TLS doubles its per-row cost.  
¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  

### T4 — memory growth since connect, MB (Percona / MariaDB)

| stack | config | int-binary | int-text | mix-binary | mix-text |
|---|---|---|---|---|---|
| c-libmysqlclient | default | 4.45 / 4.45 | 14.7 / 14.7 | 15.6 / 15.6 | 25.8 / 25.8 |
| c-mariadb-connc | default | 4.36 / 4.36 | 15.5 / 15.5 | 15.5 / 15.5 | 26.7 / 26.7 |
| go-sql-driver | default | 5.39 / 5.36 | 5.41 / 5.8 | 5.51 / 5.86 | 5.82 / 6.01 |
| go-sql-driver | tuned | 5.33 / 5.16 | 5.66 / 6.17 | 5.4 / 5.8 | 5.77 / 5.8 |
| go-mysql | default | 118 / 111 | 148 / 145 | 222 / 208 | 210 / 210 |
| java-connector-j | default | 364 / 279 | 727 / 734 | 843¹⁶ / 508 | 636 / 746 |
| java-connector-j | tuned | 799 / 411 | 389 / 445 | 813¹⁶ / 826¹⁶ | 465 / 1,383¹⁶ |
| java-mariadb-j | default | 34.1 / 33.8 | 43 / 42.2 | 261 / 260 | 294 / 414 |
| java-mariadb-j | tuned | 33.9 / 34.2 | 40.5 / 41.4 | 249 / 367 | 357 / 322 |
| py-mysqlclient | default | n/a / n/a | 54.8 / 54.9 | n/a / n/a | 89.4 / 89.5 |
| py-mysql-connector-c | default | 0.293 / 0.285 | 39.3 / 39.3 | 0.398 / 0.395 | 60.2 / 60.2 |
| py-mariadb | default | 4.29 / 4.48 | 15.7 / 15.8 | 15.6 / 15.7 | 26.9 / 26.8 |
| py-pymysql | default | n/a / n/a | 39.5 / 39.5 | n/a / n/a | 61 / 61 |
| py-mysql-connector-pure | default | 0.0586 / 0.0625 | 93.8 / 93.8 | 0.148 / 0.156 | 124 / 124 |

¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  

### T5 — memory growth since connect, MB (Percona / MariaDB)

| stack | config | 100k-doc | 100k-doc+tls | 100k-doc_bin | 10k-doc | 10k-doc_bin | 1k-doc | 1k-doc_bin | mix-doc | mix-doc_bin | 10k-doc-parse |
|---|---|---|---|---|---|---|---|---|---|---|---|
| c-libmysqlclient | default | 108⁵ / 97.9 | 108⁵ / 97.8 | 97.9 / 97.9 | 10.8⁵ / 9.84 | 9.83 / 9.84 | 1.08⁵ / 0.953 | 0.949 / 0.953 | 8.95⁵ / 8.17 | 8.18 / 8.17 | n/a⁵ / n/a |
| c-mariadb-connc | default | 109⁵ / 98.8 | 109⁵ / 98.8 | 98.8 / 98.8 | 11⁵ / 10 | 10 / 10 | 1⁵ / 0.875 | 0.879 / 0.875 | 8.95⁵ / 8.06 | 8.07 / 8.06 | n/a⁵ / n/a |
| go-sql-driver | default | 5.19⁵ / 5.6 | 5.45⁵ / 6.06 | 5.45 / 5.42 | 5.27⁵ / 5.84 | 5.9 / 5.89 | 5.56⁵ / 4.97 | 5.22 / 5.15 | 5.36⁵ / 5.94 | 5.92 / 5.77 | 11.2⁵ / 6.91 |
| go-sql-driver | tuned | 5.32⁵ / 5.35 | 5.45⁵ / 5.64 | 5.56 / 5.45 | 5.27⁵ / 5.83 | 5.84 / 5.87 | 5.53⁵ / 4.94 | 4.92 / 5.16 | 5.36⁵ / 5.54 | 5.94 / 5.6 | 8.52⁵ / 6.86 |
| go-mysql | default | 722⁵ / 668 | 722⁵ / 668 | 668 / 668 | 76.1⁵ / 65.1 | 65.1 / 65.4 | 7.5⁵ / 7.83 | 7.48 / 7.48 | 64.8⁵ / 49.6 | 49.7 / 49.6 | 62.9⁵ / 55.6 |
| java-connector-j | default | 2,008⁵ / 2,032 | 2,008⁵ / 2,018 | 1,977 / 1,998 | 868⁵ / 456 | 463 / 969 | 27.8⁵ / 27.1 | 28 / 28.2 | 497⁵ / 912 | 533 / 558 | n/a⁵ / n/a |
| java-connector-j | tuned | 2,008⁵ / 2,034 | 2,010⁵ / 2,019 | 1,980 / 1,979 | 866⁵ / 669 | 920 / 975 | 27.2⁵ / 26.6 | 28.4 / 28.5 | 502⁵ / 427 | 533 / 1,056 | n/a⁵ / n/a |
| java-mariadb-j | default | 1,898⁵ / 1,543 | 1,697⁵ / 1,870 | 1,844 / 1,843 | 1,132⁵ / 904 | 1,918 / 1,933 | 32.3⁵ / 32.5 | 32.6 / 31.9 | 1,241⁵ / 992 | 991 / 1,929 | n/a⁵ / n/a |
| java-mariadb-j | tuned | 1,898⁵ / 1,571 | 1,683⁵ / 1,907 | 1,843 / 1,842 | 1,147⁵ / 1,746 | 1,737 / 1,021 | 32.3⁵ / 32.2 | 32.1 / 31.7 | 1,914⁵ / 1,035 | 978 / 977 | n/a⁵ / n/a |
| py-mysqlclient | default | 333⁵ / 313 | 333⁵ / 313 | 313 / 313 | 32.5⁵ / 29.6 | 29.5 / 29.6 | 3.31⁵ / 3.48 | 3.49 / 3.49 | 26.7⁵ / 26.7 | 28 / 26.7 | 32.6⁵ / 29.7 |
| py-mysql-connector-c | default | 215⁵ / 195 | 215⁵ / 195 | 195 / 195 | 21.5⁵ / 19.6 | 19.6 / 19.6 | 2.07⁵ / 1.92 | 2.03 / 2.04 | 17.6⁵ / 16.2 | 16.2 / 16.2 | 21.6⁵ / 19.6 |
| py-mariadb | default | 323⁵˒⁶ / 294 | 323⁵˒⁶ / 294 | 294 / 294 | 32.6⁵˒⁶ / 29.8 | 29.6 / 29.8 | 3.25⁵˒⁶ / 3.09 | 3.09 / 3.1 | 26.7⁵˒⁶ / 24.9 | 24.5 / 24.6 | 32.7⁵˒⁶ / 29.9 |
| py-pymysql | default | 217⁵ / 198 | 217⁵ / 197 | 196 / 196 | 21.8⁵ / 19.9 | 19.7 / 19.7 | 2.26⁵ / 2.11 | 2.07 / 2.08 | 18.4⁵ / 16.7 | 16.5 / 16.5 | 21.9⁵ / 19.9 |
| py-mysql-connector-pure | default | 217⁵ / 200 | 218⁵ / 200 | 198 / 198 | 21.4⁵ / 19.5 | 19.6 / 19.6 | 2.08⁵ / 1.87 | 1.87 / 1.88 | 17.9⁵ / 16.3 | 16.4 / 16.4 | 21.4⁵ / 19.5 |

⁵ **Percona converts JSON on every read.** Percona Server (like MySQL) stores JSON in a binary format and converts it to text on every read: about 13× the server CPU of the same bytes as LONGBLOB, and ~10% larger output. The slower send makes most clients spend more CPU per KB than reading the same documents from MariaDB, which stores JSON as text.  
⁶ **Returns JSON as bytes on Percona.** MariaDB Connector/Python returns Percona's JSON column as raw bytes (no UTF-8 decoding) but MariaDB's JSON column as a decoded string. Not comparable with other drivers or across servers.  

### T6 — memory growth since connect, MB (Percona / MariaDB)

| stack | config | multiparam | sqltext | batch |
|---|---|---|---|---|
| c-libmysqlclient | default | 2.07 / 2.06 | 0.168 / 0.168 | n/a / n/a |
| c-mariadb-connc | default | 0.879 / 0.875 | 0.0938 / 0.0898 | n/a⁸ / 0.148⁸ |
| go-sql-driver | default | 5.56¹¹ / 5.57¹¹ | 5.56 / 5.69 | n/a / n/a |
| go-sql-driver | tuned | 5.54 / 5.31 | 5.81 / 5.68 | n/a / n/a |
| go-mysql | default | 5.29 / 5.3 | 5.59 / 5.67 | n/a / n/a |
| java-connector-j | default | 55.5 / 51.4 | 47.8 / 43.2 | 34.9⁹ / 33.4⁹ |
| java-connector-j | tuned | 50.1 / 73.3 | 47.5 / 46.2 | 52.8⁹ / 53.9⁹ |
| java-mariadb-j | default | 34.8 / 34.9 | 37 / 36.3 | 40.4⁸ / 39.5⁸ |
| java-mariadb-j | tuned | 35.5 / 33.7 | 36.3 / 36.8 | 41.4⁸ / 39.3⁸ |
| py-mysqlclient | default | 0.824 / 0.824 | 0.566 / 0.566 | 0.77 / 0.77 |
| py-mysql-connector-c | default | 1.4 / 1.4 | 0.453 / 0.453 | 0.656 / 0.66 |
| py-mariadb | default | 2.37 / 2.31 | 0.547 / 0.543 | 0.465⁸ / 0.742⁸ |
| py-pymysql | default | 0.688 / 0.688 | 0.375 / 0.375 | 0.543 / 0.543 |
| py-mysql-connector-pure | default | 1.33 / 1.32 | 0.41 / 0.406 | 0.59 / 0.648 |

⁸ **MariaDB-only bulk protocol.** On MariaDB this uses the bulk-execute protocol (COM_STMT_BULK_EXECUTE). Percona Server does not have it, so the driver falls back to one execute per row there, or the test is n/a.  
⁹ **Connector/J batch defaults.** With default settings Connector/J's executeBatch() sends one INSERT per row; rewriteBatchedStatements=true (tuned) rewrites the batch into multi-row INSERTs.  
¹¹ **Three round trips per parameterized query.** Without client-side interpolation (go-sql-driver: interpolateParams=true, tuned) each parameterized call prepares, executes and closes a server-side statement.  
