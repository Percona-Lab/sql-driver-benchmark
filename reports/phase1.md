# Phase 1 report — C, Go, Python (Java pending)

Run: 2026-11-17 23:09 → 2026-11-18 19:20 UTC on one bare-metal host (EPYC 4245P, client alone on an
isolated core, 3.9 GHz fixed). Servers: Percona Server 9.7.2-3 and MariaDB 12.3.4, identical
configuration. Method: [SPEC.md](../SPEC.md); host pitfalls fixed before this run: [measurement-pitfalls](../docs/measurement-pitfalls.md).

- 829 test cells (stack × server × test × variant × config), each 5 fresh timed processes (no `perf`
  attached) + 2 hardware-counter processes; every iteration checksum-verified. **0 failures.**
- Repeatability: median coefficient of variation across the 5 processes **0.47%**; 95% of cells under 2.6%
  (outliers are T0, a single cold start).
- **Java is pending.** The Java runner read process CPU from `OperatingSystemMXBean`, which only advances in
  10 ms ticks on Linux, so its per-op numbers are too coarse. Fixed (ns `clock_gettime` via FFM); Java is being
  rerun and is left out of the tables below.
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

**Footprint (T0)**
- Startup + connect: Go 0.1 ms / ~10 MB RSS, C 0.4–0.7 ms / 8–11 MB, Python 0.9–5.6 ms / 23–36 MB
  (PyMySQL the largest).

**Not supported (recorded as n/a, with the driver's own reason)**
- ed25519 authentication works only in MariaDB Connector/C and Python, go-mysql, and PyMySQL (with `pynacl`).
  **go-sql-driver fails it against MariaDB 12.3 with "malformed packet"** — a failure, not a missing feature.
- No Python driver exposes TLS session resumption; mysqlclient and PyMySQL have no server-side prepared statements.

## Tables

### T1 — client CPU, µs/connect (Percona / MariaDB)

| stack | config | socket | tcp | tls | tls-resume | tls-verify | tls-verify-resume | tcp@ed25519 |
|---|---|---|---|---|---|---|---|---|
| c-libmysqlclient | default | 11.3 / 10.5 | 23.9 / 21.3 | 3,598 / 3,876 | 3,513 / 3,879 | 727 / 1,020 | 611 / 1,021 | n/a / n/a |
| c-mariadb-connc | default | 12 / 10.8 | 25.6 / 22.8 | 3,586 / 3,797 | n/a / n/a | 669 / 958 | n/a / n/a | n/a / 69.2 |
| go-sql-driver | default | 17.3 / 14.5 | 31.6 / 26.7 | 284 / 2,557 | 233 / 2,560 | 395 / 2,617 | 236 / 2,624 | n/a / n/a |
| go-sql-driver | tuned | 17.2 / 14.5 | 31.7 / 26.6 | 285 / 2,557 | 233 / 2,562 | 395 / 2,618 | 236 / 2,622 | n/a / n/a |
| go-mysql | default | 25 / 22.4 | 39.4 / 34.7 | 314 / 2,606 | 265 / 2,608 | 452 / 2,690 | 292 / 2,701 | n/a / 69.5 |
| go-mysql | tuned | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a |
| py-mysqlclient | default | 29.6 / 28.9 | 46.6 / 44.4 | 3,684 / 3,954 | n/a / n/a | 816 / 1,103 | n/a / n/a | n/a / n/a |
| py-mysql-connector-c | default | 42.4 / 41.7 | 65 / 62.1 | 3,730 / 4,004 | n/a / n/a | 856 / 1,148 | n/a / n/a | n/a / n/a |
| py-mariadb | default | 16.2 / 15 | 31.8 / 29.1 | 3,637 / 3,867 | n/a / n/a | 718 / 1,011 | n/a / n/a | n/a / 76 |
| py-pymysql | default | 3,644 / 3,915 | 3,750 / 4,023 | 3,753 / 4,023 | n/a / n/a | 873 / 1,162 | n/a / n/a | n/a / 4,092 |
| py-mysql-connector-pure | default | 96.4 / 89.3 | 128 / 117 | 7,289 / 7,555 | n/a / n/a | 7,363 / 7,638 | n/a / n/a | n/a / n/a |

### T2 — client CPU, µs/query (Percona / MariaDB)

| stack | config | literal | prepared | param |
|---|---|---|---|---|
| c-libmysqlclient | default | 4.32 / 4.09 | 4.23 / 4.19 | n/a / n/a |
| c-mariadb-connc | default | 4.48 / 4.3 | 4.27 / 4.2 | n/a / n/a |
| go-sql-driver | default | 5.89 / 6.09 | 6.34 / 6.2 | 13.4 / 13.4 |
| go-sql-driver | tuned | 5.94 / 6.08 | 6.3 / 6.21 | 6.04 / 6.26 |
| go-mysql | default | 5.76 / 5.89 | 5.84 / 5.7 | 13.2 / 13.1 |
| go-mysql | tuned | n/a / n/a | n/a / n/a | n/a / n/a |
| py-mysqlclient | default | 6.4 / 6.36 | n/a / n/a | 6.99 / 6.95 |
| py-mysql-connector-c | default | 10.7 / 10.7 | 14.5 / 14.5 | 11.6 / 11.6 |
| py-mariadb | default | 5.92 / 5.98 | 13.1 / 12 | 6.66 / 6.69 |
| py-pymysql | default | 14.8 / 15.1 | n/a / n/a | 15.9 / 16.1 |
| py-mysql-connector-pure | default | 26.2 / 25 | 37.9 / 38.2 | 30.6 / 29.8 |

### T3 — client CPU, ns/row (Percona / MariaDB)

| stack | config | binary-buffered | binary-streamed | text-buffered | text-buffered+tls | text-streamed | text-streamed+tls |
|---|---|---|---|---|---|---|---|
| c-libmysqlclient | default | 26.8 / 26.8 | 24.6 / 25 | 37.1 / 37 | 78.3 / 78.5 | 28.1 / 28.1 | 69.4 / 69.5 |
| c-mariadb-connc | default | 33.5 / 34.9 | 25.4 / 25.4 | 38.1 / 38 | 38 / 37.8 | 28.8 / 29.3 | 29.4 / 29.5 |
| go-sql-driver | default | n/a / n/a | 85.7 / 85.5 | n/a / n/a | n/a / n/a | 101 / 100 | 103 / 105 |
| go-sql-driver | tuned | n/a / n/a | 85.8 / 85.6 | n/a / n/a | n/a / n/a | 101 / 101 | 102 / 107 |
| go-mysql | default | 69.3 / 69.8 | 65.7 / 65.9 | 83.4 / 83.1 | 84.3 / 85.7 | 78.7 / 81.4 | 80.6 / 83.9 |
| go-mysql | tuned | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a |
| py-mysqlclient | default | n/a / n/a | n/a / n/a | 218 / 219 | 260 / 260 | 320 / 319 | 425 / 427 |
| py-mysql-connector-c | default | 1,300 / 1,313 | 1,291 / 1,321 | 500 / 506 | 575 / 585 | 989 / 999 | 1,102 / 1,118 |
| py-mariadb | default | 306 / 305 | 400 / 409 | 196 / 197 | 196 / 197 | 396 / 401 | 402 / 405 |
| py-pymysql | default | n/a / n/a | n/a / n/a | 1,085 / 1,092 | 1,097 / 1,090 | 1,180 / 1,183 | 1,176 / 1,174 |
| py-mysql-connector-pure | default | 3,805 / 3,793 | 3,827 / 3,804 | 2,446 / 2,426 | 2,384 / 2,364 | 3,743 / 3,719 | 3,725 / 3,725 |

### T4 — client CPU, ns/cell (Percona / MariaDB)

| stack | config | int-binary | int-text | mix-binary | mix-text |
|---|---|---|---|---|---|
| c-libmysqlclient | default | 7.07 / 7.08 | 15.3 / 15.2 | 11.1 / 11.1 | 14.5 / 14.5 |
| c-mariadb-connc | default | 8.05 / 8.01 | 16.7 / 16.5 | 13.8 / 13.6 | 16.2 / 16.7 |
| go-sql-driver | default | 35.4 / 35.2 | 50.3 / 50.7 | 48.6 / 48.6 | 61.9 / 61.9 |
| go-sql-driver | tuned | 35.4 / 35.3 | 50.4 / 51 | 48.3 / 48.5 | 61.4 / 61.6 |
| go-mysql | default | 8.96 / 8.79 | 21.8 / 21.9 | 53.5 / 53 | 25.6 / 25.9 |
| go-mysql | tuned | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a |
| py-mysqlclient | default | n/a / n/a | 66.8 / 66.9 | n/a / n/a | 197 / 196 |
| py-mysql-connector-c | default | 107 / 108 | 95.4 / 95.5 | 262 / 261 | 242 / 241 |
| py-mariadb | default | 61.6 / 61.5 | 110 / 109 | 83.2 / 81.3 | 148 / 148 |
| py-pymysql | default | n/a / n/a | 272 / 273 | n/a / n/a | 503 / 501 |
| py-mysql-connector-pure | default | 393 / 391 | 252 / 251 | 651 / 649 | 469 / 469 |

### T5 — client CPU, ns/KB (Percona / MariaDB)

| stack | config | 100k-doc | 100k-doc+tls | 100k-doc_bin | 10k-doc | 10k-doc_bin | 1k-doc | 1k-doc_bin | mix-doc | mix-doc_bin | 10k-doc-parse |
|---|---|---|---|---|---|---|---|---|---|---|---|
| c-libmysqlclient | default | 241 / 232 | 371 / 353 | 231 / 237 | 218 / 226 | 230 / 226 | 289 / 284 | 284 / 283 | 215 / 193 | 193 / 191 | n/a / n/a |
| c-mariadb-connc | default | 295 / 274 | 429 / 392 | 278 / 281 | 335 / 303 | 305 / 312 | 367 / 370 | 367 / 366 | 276 / 244 | 244 / 241 | n/a / n/a |
| go-sql-driver | default | 184 / 147 | 375 / 388 | 148 / 147 | 332 / 255 | 257 / 256 | 526 / 480 | 485 / 485 | 264 / 199 | 199 / 199 | 16,364 / 17,641 |
| go-sql-driver | tuned | 185 / 147 | 373 / 387 | 149 / 148 | 332 / 254 | 257 / 257 | 522 / 477 | 479 / 484 | 264 / 199 | 199 / 199 | 16,378 / 17,576 |
| go-mysql | default | 237 / 225 | 439 / 403 | 223 / 226 | 349 / 265 | 266 / 268 | 424 / 380 | 377 / 382 | 251 / 204 | 196 / 201 | 14,796 / 16,069 |
| go-mysql | tuned | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a |
| py-mysqlclient | default | 351 / 354 | 477 / 486 | 253 / 254 | 463 / 462 | 349 / 350 | 736 / 708 | 516 / 521 | 457 / 349 | 232 / 232 | 3,962 / 4,372 |
| py-mysql-connector-c | default | 376 / 386 | 501 / 499 | 274 / 269 | 515 / 509 | 399 / 393 | 1,604 / 1,599 | 1,346 / 1,350 | 519 / 403 | 281 / 281 | 3,999 / 4,296 |
| py-mariadb | default | 324 / 440 | 455 / 567 | 331 / 330 | 410 / 522 | 406 / 404 | 548 / 757 | 571 / 573 | 274 / 378 | 261 / 253 | 3,990 / 4,406 |
| py-pymysql | default | 497 / 505 | 498 / 508 | 461 / 463 | 627 / 612 | 472 / 474 | 1,853 / 1,927 | 1,641 / 1,650 | 656 / 647 | 489 / 502 | 4,101 / 4,436 |
| py-mysql-connector-pure | default | 418 / 409 | 559 / 563 | 263 / 252 | 785 / 809 | 677 / 674 | 4,751 / 5,100 | 4,786 / 4,838 | 854 / 893 | 750 / 762 | 4,258 / 4,583 |

### T6 — client CPU, µs/1000-row stmt (Percona / MariaDB)

| stack | config | multiparam | sqltext | batch |
|---|---|---|---|---|
| c-libmysqlclient | default | 65.9 / 59 | 268 / 268 | n/a / n/a |
| c-mariadb-connc | default | 54 / 53.2 | 249 / 250 | n/a / 59.1 |
| go-sql-driver | default | 312 / 310 | 259 / 257 | n/a / n/a |
| go-sql-driver | tuned | 225 / 226 | 258 / 257 | n/a / n/a |
| go-mysql | default | 277 / 269 | 282 / 280 | n/a / n/a |
| go-mysql | tuned | n/a / n/a | n/a / n/a | n/a / n/a |
| py-mysqlclient | default | 1,811 / 1,837 | 813 / 821 | 2,326 / 2,351 |
| py-mysql-connector-c | default | 1,208 / 1,219 | 806 / 814 | 2,079 / 2,098 |
| py-mariadb | default | 1,351 / 1,396 | 608 / 612 | 13,733 / 608 |
| py-pymysql | default | 1,598 / 1,610 | 781 / 778 | 2,151 / 2,171 |
| py-mysql-connector-pure | default | 3,143 / 3,177 | 959 / 965 | 4,628 / 4,729 |

