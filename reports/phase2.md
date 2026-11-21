# Phase 2 report — C++, Rust, .NET, Node.js, PHP, Ruby

> **AI-generated results.** This benchmark was designed, run and analyzed with an AI assistant (Claude). Results and findings have been spot-checked by a person, but not every number and explanation has been verified in detail, and some may be wrong. The code and raw data are published so you can verify anything here; please report problems as [issues](https://github.com/Percona-Lab/sql-driver-benchmark/issues).

Run: 2026-11-18 → 2026-11-21, same host, servers and method as [Phase 1](phase1.md). JIT runtimes (.NET, Node.js, Ruby YJIT)
were measured with adaptive warm-up (until three iterations agree within 5%). Drivers: MySQL Connector/C++ 26.10, MariaDB
Connector/C++ 1.1.9, Rust `mysql` 28.0.4 and `sqlx` 0.9.1, MySqlConnector 3.0.0 and MySql.Data 26.10.0, Node mysql2 3.24.6,
mariadb 3.5.5 and mysql 2.18.1, PHP 8.5 mysqli and PDO_MySQL (mysqlnd), Ruby mysql2 0.5.7 and trilogy 2.13.3.

All numbers are **client CPU per operation** (user + kernel, whole process, GC and JIT threads included), median of 5
fresh processes, in steady state, shown as **Percona / MariaDB**; memory tables come from a separate memory pass.
Interactive version: https://percona-lab.github.io/sql-driver-benchmark/ · Method: [SPEC.md](../SPEC.md) ·
host pitfalls we found and fixed: [measurement-pitfalls](../docs/measurement-pitfalls.md).

**Memory measures.** *Memory for the work* is the peak resident memory during a measured iteration minus the memory at its
start. It reads near zero when a runtime keeps freed memory between iterations (Python's allocator, garbage-collected heaps),
so for those *memory growth* is the better measure: the highest peak minus the memory right after connecting, before warm-up.
Growth of JIT/GC runtimes includes heap the runtime chose to keep (the JVM sizes its heap up to a quarter of RAM by default).

For comparison, libmysqlclient (C) on Percona: plain connect 23.9 µs, point select
4.32 µs, 1M buffered rows 37.1 ns/row.

## Key findings

- **PHP is as cheap as C for connections and point selects.** mysqli: plain connect 25.5 µs,
  point select 4.81 µs (mysqlnd is C inside PHP). Row-heavy work costs more:
  147 ns/row on defaults, 121 with
  numeric arrays and native types.
- **Oracle's MySql.Data costs several times MySqlConnector:** plain connect 760 vs
  80.2 µs, point select 21.2 vs
  5.41 µs, streamed rows 1,078 vs
  480 ns/row. MySql.Data also cannot verify a server against a CA file
  without a client certificate.
- **Rust: cheapest TLS and near-C binary decoding.** The `mysql` crate: verified TLS connect
  243 µs (rustls), wide mixed-type binary rows 17.3 ns/cell.
  `sqlx` is slower on large results (270 ns/row vs 89.4).
  The `mysql` crate ships without TLS unless a TLS feature is enabled, and by default silently switches 127.0.0.1
  connections to the Unix socket (`prefer_socket`).
- **Row format matters in scripting languages.** Returning rows as arrays instead of objects/hashes: Node mysql2
  107 → 49.9 ns/row, Ruby trilogy
  173 → 62.9 ns/row.
- **Ruby mysql2's prepared-statement streaming costs 4,268 ns/row**, about 20× its text
  path (198).
- **Ruby mysql2 tuned (`as: :array, cache_rows: false`) runs out of memory on 100 KB documents**: past the 8 GB client cap on
  both servers (before the cap existed it pushed the host into the kernel OOM killer twice). Unfreed results hold C buffers
  that Ruby's garbage collector does not account for.
- **Node connects slowly:** mysql2 317 µs, mariadb 102 µs per plain
  connect. The legacy `mysql` package cannot authenticate with `caching_sha2_password`, so it only works against MariaDB here.
- **C++:** MySQL Connector/C++ point select 5.02 µs; MariaDB Connector/C++'s
  4,000-placeholder insert 903 µs vs 185 for MySQL
  Connector/C++. Connector/C++ needs `pluginDir` to find `mysql_native_password`; MariaDB Connector/C++ keeps the batch
  after `executeBatch()` (call `clearBatch()`).
- **trilogy verifies certificates by host name only**, not by IP address.
- Memory after connecting: Rust 6.74–8.44 MB,
  PHP 43.3 MB, .NET 64.3 MB,
  Node 75.5–79.9 MB.

## Tables

Superscript numbers mark results with a note; the notes follow each table.

### T1 — client CPU, µs/connect (Percona / MariaDB)

| stack | config | socket | tcp | tcp@ed25519 | tls | tls-verify | tls-resume | tls-verify-resume |
|---|---|---|---|---|---|---|---|---|
| cpp-mysql-connector | default | 30.9³ / 27.2³ | 45.1³ / 39.8³ | n/a / n/a | 3,631² / 3,890¹˒² | 762 / 1,052¹ | n/a² / n/a¹˒² | n/a / n/a¹ |
| cpp-mariadb | default | 27.4³˒⁴ / 26.5³˒⁴ | 45.1³˒⁴ / 42.8³˒⁴ | n/a⁴ / 90⁴ | 3,694²˒⁴ / 3,902¹˒²˒⁴ | 749⁴ / 1,039¹˒⁴ | n/a²˒⁴ / n/a¹˒²˒⁴ | n/a⁴ / n/a¹˒⁴ |
| rust-mysql | default | 19.1³ / 18.3³ | 34.1³ / 34.9³ | n/a / n/a | 147 / 274¹ | 243 / 371¹ | n/a / n/a¹ | n/a / n/a¹ |
| rust-sqlx | default | 17.2³ / 15.7³ | 29.4³ / 26.7³ | n/a / n/a | 178 / 692¹ | 239 / 755¹ | n/a / n/a¹ | n/a / n/a¹ |
| dotnet-mysqlconnector | default | 37.5³ / 30.8³ | 80.2³ / 78.7³˒¹⁵ | n/a / 107 | 1,088 / 1,046¹ | 1,336 / 1,272¹ | n/a / n/a¹ | n/a / n/a¹ |
| dotnet-mysql-data | default | 533³ / 1,474³ | 760³ / 1,668³ | n/a / n/a | 1,530 / 1,778¹ | n/a / n/a¹ | n/a / n/a¹ | n/a / n/a¹ |
| node-mysql2 | default | 284³ / 271³ | 317³ / 303³ | n/a / n/a | 1,200 / 3,639¹ | 1,361 / 3,875¹ | n/a / n/a¹ | n/a / n/a¹ |
| node-mysql2 | tuned | 285³ / 271³ | 317³ / 302³ | n/a / n/a | 1,201 / 3,650¹ | 1,380 / 3,872¹ | n/a / n/a¹ | n/a / n/a¹ |
| node-mariadb | default | 77.6³ / 64.9³ | 102³ / 84.9³ | n/a / 5,085 | 993 / 3,452¹ | 1,183 / 3,688¹ | n/a / n/a¹ | n/a / n/a¹ |
| node-mariadb | tuned | 78.2³ / 64.8³ | 102³ / 85.5³ | n/a / 5,088 | 995 / 3,452¹ | 1,188 / 3,688¹ | n/a / n/a¹ | n/a / n/a¹ |
| node-mysql | default | n/a³ / 44.8³ | n/a³ / 68.7³ | n/a / n/a | n/a / 3,359¹ | n/a / 3,509¹ | n/a / n/a¹ | n/a / n/a¹ |
| php-mysqli | default | 11.5³ / 10³ | 25.5³ / 22.5³ | n/a / n/a | 629 / 907¹ | 742 / 1,032¹ | n/a / n/a¹ | n/a / n/a¹ |
| php-mysqli | tuned | 11.6³ / 10.1³ | 25.6³ / 22.6³ | n/a / n/a | 629 / 908¹ | 743 / 1,032¹ | n/a / n/a¹ | n/a / n/a¹ |
| php-pdo-mysql | default | 11.4³ / 10³ | 25.6³ / 22.7³ | n/a / n/a | 636 / 913¹ | 746 / 1,034¹ | n/a / n/a¹ | n/a / n/a¹ |
| php-pdo-mysql | tuned | 11.5³ / 10³ | 25.7³ / 22.7³ | n/a / n/a | 635 / 913¹ | 747 / 1,033¹ | n/a / n/a¹ | n/a / n/a¹ |
| rb-mysql2 | default | 17.8³ / 16.9³ | 31.7³ / 29.4³ | n/a / n/a | 3,704² / 3,975¹˒² | 788 / 1,080¹ | n/a² / n/a¹˒² | n/a / n/a¹ |
| rb-mysql2 | tuned | 17.9³ / 16.9³ | 31.7³ / 29.3³ | n/a / n/a | 3,708² / 3,975¹˒² | 788 / 1,080¹ | n/a² / n/a¹˒² | n/a / n/a¹ |
| rb-trilogy | default | 16³ / 13.4³ | 31.1³ / 27.3³ | n/a / n/a | 3,659² / 3,912¹˒² | 867 / 1,148¹ | n/a² / n/a¹˒² | n/a / n/a¹ |
| rb-trilogy | tuned | 16³ / 13.3³ | 31.1³ / 27.2³ | n/a / n/a | 3,656² / 3,910¹˒² | 866 / 1,149¹ | n/a² / n/a¹˒² | n/a / n/a¹ |

¹ **MariaDB TLS key exchange.** MariaDB 12.3 negotiates ECDH on P-521 (secp521r1); Percona Server uses P-256. Much of the extra client CPU per TLS connect on MariaDB is that server-side choice, not the driver.  
² **TLS without a CA loads the system trust store.** With no CA configured, libmysqlclient, MariaDB Connector/C and the drivers built on them (Connector/C++, mysqlclient, MariaDB Connector/Python, Ruby mysql2) and trilogy load and parse the full system CA bundle (120 certificates) on every connection although they verify nothing.  
³ **Different default authentication.** Each server uses its own default authentication: Percona Server caching_sha2_password (SHA-256 plus an extra round trip on the fast path), MariaDB mysql_native_password. Part of the Percona-vs-MariaDB difference in plain connect cost comes from this, not the driver.  
⁴ **Connector/C sleeps after connect().** MariaDB Connector/C calls usleep(1) after every connect() (about 50 µs on Linux). This adds wall time per connection, not CPU.  
¹⁵ **Higher run-to-run spread.** The 5 processes for this result differ by more than 5% (coefficient of variation). Small differences against it are not meaningful.  

### T2 — client CPU, µs/query (Percona / MariaDB)

| stack | config | literal | param | prepared |
|---|---|---|---|---|
| cpp-mysql-connector | default | 5.02 / 4.98 | n/a / n/a | 5.14 / 5.01 |
| cpp-mariadb | default | 5.13 / 5.14 | 5.17 / 5.26 | 5.16 / 5.05 |
| rust-mysql | default | 4.37 / 4.27 | 4.6 / 4.25 | 4.49 / 4.05 |
| rust-sqlx | default | 5.61 / 5.59 | 12.6 / 12.5 | 5.74 / 5.73 |
| dotnet-mysqlconnector | default | 5.41 / 5.35 | 5.38 / 5.36 | 5.3 / 5.17 |
| dotnet-mysql-data | default | 21.2 / 21.8 | 21.2 / 21.8 | 18.9 / 19.6 |
| node-mysql2 | default | 8.95 / 8.91 | 8.86 / 8.87 | 9.29 / 8.92 |
| node-mysql2 | tuned | 8.98 / 8.95 | 8.85 / 8.84 | 9.35 / 8.98 |
| node-mariadb | default | 7.18 / 7.07 | 7.24 / 7.23 | 7.16 / 7 |
| node-mariadb | tuned | 6.97 / 6.93 | 7.12 / 7.1 | 7.08 / 6.99 |
| node-mysql | default | n/a / 10.7 | n/a / 10.9 | n/a / n/a |
| php-mysqli | default | 4.81 / 4.82 | 11.4 / 11.4 | 4.88 / 4.83 |
| php-mysqli | tuned | 4.79 / 4.81 | 11.3 / 11.4 | 4.86 / 4.88 |
| php-pdo-mysql | default | 4.92 / 4.95 | 4.98 / 5.03 | 4.98 / 5.02 |
| php-pdo-mysql | tuned | 4.92 / 4.93 | 4.96 / 5 | 5 / 5 |
| rb-mysql2 | default | 7.7 / 7.7 | n/a / n/a | 6.76 / 6.79 |
| rb-mysql2 | tuned | 7.68 / 7.68 | n/a / n/a | 8.38 / 8.47 |
| rb-trilogy | default | 5.53 / 5.58 | n/a / n/a | n/a / n/a |
| rb-trilogy | tuned | 5.53 / 5.56 | n/a / n/a | n/a / n/a |

### T3 — client CPU, ns/row (Percona / MariaDB)

| stack | config | binary-buffered | binary-streamed | text-buffered | text-buffered+tls | text-streamed | text-streamed+tls |
|---|---|---|---|---|---|---|---|
| cpp-mysql-connector | default | 49.8 / 49.7 | n/a / n/a | 55 / 55.4 | 96.5 / 96.4 | 46.5 / 46.4 | 87 / 87.5 |
| cpp-mariadb | default | 86.7 / 85.7 | 59.9 / 59.3 | 79.1 / 78.3 | 77.1 / 76.9 | 87.2 / 86.7 | 86.7 / 86.6 |
| rust-mysql | default | 79.9 / 79.8 | 76.5 / 77.3 | 89.4 / 87.5 | 88.9 / 89.2 | 91 / 90.6 | 91.8 / 91.6 |
| rust-sqlx | default | 293 / 293 | 277 / 274 | 270 / 269 | 272 / 272 | 253 / 256 | 255 / 258 |
| dotnet-mysqlconnector | default | n/a / n/a | 375 / 346¹⁵ | n/a / n/a | n/a / n/a | 480¹⁵ / 492 | 475¹⁵ / 471¹⁵ |
| dotnet-mysql-data | default | n/a / n/a | 607 / 597 | n/a / n/a | n/a / n/a | 1,078¹⁵ / 646¹⁵ | 482¹⁵ / 450¹⁵ |
| node-mysql2 | default | 113 / 107 | n/a / n/a | 107 / 107¹⁶ | 111 / 109¹⁶ | 288¹⁵ / 291 | 287¹⁵ / 288¹⁵ |
| node-mysql2 | tuned | 123¹⁵ / 65.3¹⁵˒¹⁶ | n/a / n/a | 49.9¹⁵ / 129¹⁵˒¹⁶ | 132¹⁶ / 64.4¹⁵ | 279 / 284¹⁵ | 285¹⁵ / 283 |
| node-mariadb | default | 92.2¹⁶ / 88¹⁶ | 171 / 176¹⁵ | 98.6¹⁶ / 98.5¹⁶ | 97.8¹⁶ / 99 | 165¹⁵ / 165 | 173 / 166 |
| node-mariadb | tuned | 111¹⁵˒¹⁶ / 115¹⁵˒¹⁶ | 176 / 172¹⁵ | 114¹⁶ / 114¹⁵˒¹⁶ | 122¹⁶ / 124¹⁵˒¹⁶ | 167 / 168 | 172 / 182 |
| node-mysql | default | n/a / n/a | n/a / n/a | n/a / 205¹⁵ | n/a / 216¹⁶ | n/a / 274 | n/a / 287¹⁵ |
| php-mysqli | default | 130 / 128 | 100 / 99.9 | 147 / 146 | 148 / 148 | 142 / 141 | 146 / 146 |
| php-mysqli | tuned | 112 / 112 | 100 / 100 | 121 / 121 | 123 / 123 | 117 / 117 | 119 / 118 |
| php-pdo-mysql | default | 157 / 157 | 158 / 154 | 162 / 161 | 163 / 163 | 156 / 154 | 157 / 155 |
| php-pdo-mysql | tuned | 121 / 121 | 116 / 116 | 124 / 123 | 125 / 125 | 119 / 119 | 121 / 121 |
| rb-mysql2 | default | 244 / 243 | 4,268 / 4,313 | 232 / 233 | 278 / 277 | 198 / 198 | 260 / 261 |
| rb-mysql2 | tuned | 189 / 190 | 4,186 / 4,261 | 180 / 180 | 224 / 223 | 164 / 163 | 212 / 211 |
| rb-trilogy | default | n/a / n/a | n/a / n/a | 173 / 170¹⁵ | 163 / 159¹⁵ | n/a / n/a | n/a / n/a |
| rb-trilogy | tuned | n/a / n/a | n/a / n/a | 62.9¹⁶ / 62.9¹⁶ | 68.9 / 68.8 | n/a / n/a | n/a / n/a |

¹⁵ **Higher run-to-run spread.** The 5 processes for this result differ by more than 5% (coefficient of variation). Small differences against it are not meaningful.  
¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  

### T4 — client CPU, ns/cell (Percona / MariaDB)

| stack | config | int-binary | int-text | mix-binary | mix-text |
|---|---|---|---|---|---|
| cpp-mysql-connector | default | 22.4 / 22.5 | 25.9 / 25.5 | 50.5 / 50.5 | 63.8 / 63.7 |
| cpp-mariadb | default | 54 / 53.5 | 24.7 / 24.7 | 130 / 129 | 85.8 / 85.5 |
| rust-mysql | default | 11.1 / 11.5 | 35.1 / 34.9 | 17.3 / 17.5 | 36.9 / 37.3 |
| rust-sqlx | default | 29.6 / 29.7 | 32.8 / 32.9 | 132 / 131 | 75.5 / 75.5 |
| dotnet-mysqlconnector | default | 103 / 103 | 80.2 / 79.6 | 124 / 122 | 122 / 123 |
| dotnet-mysql-data | default | 148 / 149 | 161 / 161 | 212 / 210 | 258 / 255 |
| node-mysql2 | default | 38.6 / 41¹⁵ | 41.2 / 41.2 | 119 / 118 | 131¹⁶ / 140¹⁶ |
| node-mysql2 | tuned | 15.4¹⁵˒¹⁶ / 13.6 | 19.4¹⁶ / 18.6¹⁶ | 86.1¹⁶ / 86.9¹⁶ | 99¹⁶ / 97¹⁶ |
| node-mariadb | default | 85.4 / 83¹⁵ | 85.3 / 86.2 | 193¹⁶ / 191¹⁶ | 216 / 213 |
| node-mariadb | tuned | 12.5¹⁶ / 12.4¹⁵˒¹⁶ | 17¹⁶ / 15.5¹⁵˒¹⁶ | 92.1¹⁶ / 94.3¹⁶ | 111¹⁶ / 113¹⁶ |
| node-mysql | default | n/a / n/a | n/a / 176 | n/a / n/a | n/a / 288¹⁶ |
| php-mysqli | default | 28.1 / 27.9 | 46.1 / 46.4 | 52.4 / 52 | 48 / 47.9 |
| php-mysqli | tuned | 25.7 / 25.5 | 34.4 / 34.8 | 48.6 / 48.5 | 39.6 / 39.6 |
| php-pdo-mysql | default | 54.6 / 54.3 | 62.1 / 62.4 | 80 / 79.7 | 69.8 / 70.3 |
| php-pdo-mysql | tuned | 30.4 / 30.2 | 38.1 / 38.1 | 53.7 / 53.4 | 42.9 / 43 |
| rb-mysql2 | default | 77.7 / 77.5 | 83.2 / 83.2 | 204 / 202 | 261 / 261 |
| rb-mysql2 | tuned | 43.7 / 43.7 | 48.4 / 48.3 | 151 / 151 | 192 / 193 |
| rb-trilogy | default | n/a / n/a | 76.1 / 76.5 | n/a / n/a | 173 / 170 |
| rb-trilogy | tuned | n/a / n/a | 33.1 / 32.8 | n/a / n/a | 108¹⁶ / 110¹⁶ |

¹⁵ **Higher run-to-run spread.** The 5 processes for this result differ by more than 5% (coefficient of variation). Small differences against it are not meaningful.  
¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  

### T5 — client CPU, ns/KB (Percona / MariaDB)

| stack | config | 100k-doc | 100k-doc+tls | 100k-doc_bin | 10k-doc | 10k-doc_bin | 1k-doc | 1k-doc_bin | mix-doc | mix-doc_bin | 10k-doc-parse |
|---|---|---|---|---|---|---|---|---|---|---|---|
| cpp-mysql-connector | default | 263⁵ / 268 | 392⁵ / 380 | 253 / 264 | 233⁵ / 240 | 240 / 241 | 328⁵ / 309¹⁵ | 310¹⁵ / 309 | 239⁵ / 211 | 210 / 210 | n/a⁵ / n/a |
| cpp-mariadb | default | 311⁵ / 329 | 447⁵ / 423 | 291 / 305 | 358⁵ / 324 | 325 / 323 | 424⁵ / 280 | 281 / 281 | 300⁵ / 267 | 266 / 267 | n/a⁵ / n/a |
| rust-mysql | default | 293⁵ / 296 | 406⁵ / 407 | 283 / 297 | 301⁵˒¹⁵ / 308 | 302 / 307 | 425⁵ / 435 | 428 / 442 | 301⁵ / 257 | 255 / 257 | 4,542⁵ / 5,008 |
| rust-sqlx | default | 273⁵ / 213¹⁵ | 500⁵ / 468¹⁵ | 202 / 197 | 202⁵˒¹⁵ / 218 | 222 / 221 | 572⁵ / 485 | 474 / 474¹⁵ | 180⁵ / 162 | 157 / 158 | 4,781⁵ / 5,176 |
| dotnet-mysqlconnector | default | 417⁵ / 264 | 585⁵ / 526 | 256 / 253 | 381⁵ / 351 | 300 / 297 | 1,034⁵ / 1,003 | 925 / 914 | 387⁵ / 392 | 296 / 296 | 2,200⁵˒¹⁵ / 2,172¹⁵ |
| dotnet-mysql-data | default | 698⁵˒¹⁵ / 283 | 927⁵ / 519 | 160¹⁵ / 152 | 1,947⁵ / 342 | 330 / 330¹⁵ | 2,801⁵ / 1,401 | 1,441 / 1,456 | 1,266⁵˒¹⁵˒¹⁶ / 466 | 365 / 355 | 3,019⁵˒¹⁵ / 3,058¹⁵ |
| node-mysql2 | default | 443⁵ / 449 | 599⁵ / 600 | 403 / 395 | 550⁵ / 422¹⁶ | 505 / 496 | 590⁵˒¹⁵ / 572 | 482¹⁵ / 453¹⁵ | 429⁵ / 363¹⁵˒¹⁶ | 460 / 456 | 2,336⁵˒¹⁵ / 2,396 |
| node-mysql2 | tuned | 436⁵ / 443 | 601⁵ / 595 | 398 / 396 | 525⁵ / 442¹⁶ | 494 / 506¹⁶ | 555⁵ / 578 | 467¹⁵˒¹⁶ / 426¹⁵˒¹⁶ | 421⁵ / 369¹⁶ | 445 / 456 | 2,352⁵ / 2,352 |
| node-mariadb | default | 441⁵ / 451 | 600⁵ / 601 | 385 / 381 | 552⁵˒¹⁵˒¹⁶ / 445 | 514 / 515¹⁵ | 587⁵˒¹⁵ / 618¹⁵ | 468¹⁵ / 465¹⁵˒¹⁶ | 426⁵˒¹⁵ / 372¹⁵ | 443 / 445 | 2,321⁵˒¹⁵ / 2,327 |
| node-mariadb | tuned | 438⁵ / 444 | 590⁵ / 594 | 388 / 381 | 528⁵ / 420 | 498 / 504¹⁶ | 508⁵˒¹⁵˒¹⁶ / 540 | 398¹⁵˒¹⁶ / 425¹⁵˒¹⁶ | 415⁵ / 364¹⁵˒¹⁶ | 433¹⁵ / 425¹⁵ | 2,392⁵˒¹⁵ / 2,328 |
| node-mysql | default | n/a⁵ / 460 | n/a⁵ / 602 | n/a / 530 | n/a⁵ / 592 | n/a / 668 | n/a⁵ / 746¹⁵˒¹⁶ | n/a / 1,083¹⁵˒¹⁶ | n/a⁵ / 439¹⁶ | n/a / 661 | n/a⁵ / 2,411 |
| php-mysqli | default | 509⁵ / 539 | 651⁵ / 676 | 532 / 541 | 569⁵ / 560 | 561 / 561 | 595⁵ / 579 | 620 / 621 | 483⁵ / 463 | 457 / 461 | 5,594⁵ / 5,960 |
| php-mysqli | tuned | 511⁵ / 541 | 650⁵ / 676 | 538 / 540 | 594⁵ / 557 | 556 / 560 | 577⁵ / 600 | 598 / 597 | 482⁵ / 456 | 457 / 458 | 5,588⁵ / 5,953 |
| php-pdo-mysql | default | 510⁵ / 536 | 651⁵ / 680 | 538 / 536 | 602⁵ / 563 | 569 / 563 | 614⁵ / 641 | 643 / 642 | 491⁵ / 464 | 466 / 467 | 5,613⁵ / 5,976 |
| php-pdo-mysql | tuned | 511⁵ / 537 | 650⁵ / 673 | 535 / 540 | 564⁵ / 561 | 562 / 557 | 585⁵ / 576 | 558 / 600 | 485⁵ / 459 | 460 / 459 | 5,560⁵ / 5,961 |
| rb-mysql2 | default | 537⁵ / 591 | 711⁵ / 747 | 601 / 579 | 564⁵ / 564 | 569 / 577 | 897⁵ / 935 | 925 / 939 | 560⁵ / 546 | 552 / 558 | 2,576⁵ / 2,693 |
| rb-mysql2 | tuned | FAIL⁵˒¹⁴ / 620¹⁴ | FAIL⁵˒¹⁴ / 741¹⁴ | FAIL¹⁴ / 636¹⁴ | 633⁵ / 623 | 627 / 622 | 881⁵ / 914 | 885 / 871 | 586⁵ / 584 | 589 / 593 | 2,546⁵ / 2,667 |
| rb-trilogy | default | 487⁵ / 504 | 619⁵ / 635 | 506 / 499 | 598⁵ / 586 | 588 / 586 | 784⁵ / 789 | 786 / 799 | 546⁵ / 526 | 525 / 526 | 2,488⁵ / 2,556 |
| rb-trilogy | tuned | 483⁵ / 513 | 618⁵ / 633 | 515 / 512 | 589⁵ / 581 | 572 / 578 | 708⁵ / 722 | 703 / 716 | 534⁵ / 524 | 514 / 521 | 2,469⁵ / 2,544 |

⁵ **Percona converts JSON on every read.** Percona Server (like MySQL) stores JSON in a binary format and converts it to text on every read: about 13× the server CPU of the same bytes as LONGBLOB, and ~10% larger output. The slower send makes most clients spend more CPU per KB than reading the same documents from MariaDB, which stores JSON as text.  
¹⁴ **Runs out of memory.** With as: :array and cache_rows: false, mysql2 kept growing past the 8 GB client cap on 100 KB documents and was killed (on both servers; before the cap existed it pushed the host into the kernel OOM killer twice). Results that are not freed explicitly hold their C buffers, which Ruby's garbage collector does not account for.  
¹⁵ **Higher run-to-run spread.** The 5 processes for this result differ by more than 5% (coefficient of variation). Small differences against it are not meaningful.  
¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  

### T6 — client CPU, µs/1000-row stmt (Percona / MariaDB)

| stack | config | batch | multiparam | sqltext |
|---|---|---|---|---|
| cpp-mysql-connector | default | n/a / n/a | 185 / 163 | 259 / 257 |
| cpp-mariadb | default | 4,728 / 285 | 903 / 880 | 263 / 261 |
| rust-mysql | default | 3,981 / 130 | 75.9 / 74.9 | 258 / 257 |
| rust-sqlx | default | n/a / n/a | 87.6 / 87.3 | 254 / 256 |
| dotnet-mysqlconnector | default | 3,033 / 3,021 | 405 / 407 | 217 / 214 |
| dotnet-mysql-data | default | n/a / n/a | 710 / 705 | 568 / 564 |
| node-mysql2 | default | 203 / 200 | 196 / 197 | 264 / 261 |
| node-mysql2 | tuned | 206 / 204 | 196 / 195 | 264 / 262 |
| node-mariadb | default | 5,390 / 5,904 | 251 / 244 | 209 / 203 |
| node-mariadb | tuned | 5,403 / 5,531 | 251 / 245 | 208 / 204 |
| node-mysql | default | n/a / 208 | n/a / 285 | n/a / 180 |
| php-mysqli | default | n/a / n/a | 267 / 265 | 345 / 347 |
| php-mysqli | tuned | n/a / n/a | 266 / 265 | 345 / 346 |
| php-pdo-mysql | default | n/a / n/a | 467 / 462 | 319 / 320 |
| php-pdo-mysql | tuned | n/a / n/a | 466 / 463 | 318 / 320 |
| rb-mysql2 | default | n/a / n/a | 351 / 344 | 746 / 753 |
| rb-mysql2 | tuned | n/a / n/a | 351 / 344 | 747 / 747 |
| rb-trilogy | default | n/a / n/a | n/a / n/a | 1,234 / 1,239 |
| rb-trilogy | tuned | n/a / n/a | n/a / n/a | 1,241 / 1,233 |

### T3 — memory for the work, MB (Percona / MariaDB)

| stack | config | binary-buffered | binary-streamed | text-buffered | text-buffered+tls | text-streamed | text-streamed+tls |
|---|---|---|---|---|---|---|---|
| cpp-mysql-connector | default | 30.3 / 30.3 | n/a / n/a | 30.2 / 30.2 | 30.3 / 30.3 | 0 / 0 | 0 / 0 |
| cpp-mariadb | default | 0 / 0 | 0 / 0 | 45.6 / 45.6 | 45.6 / 45.6 | 0 / 0 | 0 / 0 |
| rust-mysql | default | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| rust-sqlx | default | 76.2 / 82.1 | 0 / 0 | 76.2 / 76.2 | 76.2 / 76.2 | 0 / 0 | 0 / 0 |
| dotnet-mysqlconnector | default | n/a / n/a | 0 / 0 | n/a / n/a | n/a / n/a | 0.0664 / 0 | 0 / 0 |
| dotnet-mysql-data | default | n/a / n/a | 0 / 0 | n/a / n/a | n/a / n/a | 0 / 0 | 0 / 0 |
| node-mysql2 | default | 24.2 / 22.7 | n/a / n/a | 21.4 / 21.5 | 21.8¹⁶ / 21.2 | 0.0508 / 0.0742 | 0.0977 / 0.0938 |
| node-mysql2 | tuned | 15.2 / 22.4 | n/a / n/a | 21.1 / 23.8 | 10.9 / 2.29 | 0.0781 / 0.0586 | 0.0898 / 0.0898 |
| node-mariadb | default | 21.6¹⁶ / 21.2 | 0 / 0 | 21.5 / 21.9 | 20.9 / 17.4¹⁶ | 0 / 0 | 0.145 / 0.0781 |
| node-mariadb | tuned | 21.9 / 21.2 | 0 / 0 | 21.5 / 21 | 23.5¹⁶ / 6.64¹⁶ | 0 / 0 | 0.0781 / 0.102 |
| node-mysql | default | n/a / n/a | n/a / n/a | n/a / 28.2 | n/a / 25.4¹⁶ | n/a / 0 | n/a / 0 |
| php-mysqli | default | 31.9 / 32 | 0 / 0 | 31.9 / 31.9 | 31.9 / 31.9 | 0 / 0 | 0 / 0 |
| php-mysqli | tuned | 31.9 / 32 | 0 / 0 | 31.9 / 31.9 | 31.9 / 31.9 | 0 / 0 | 0 / 0 |
| php-pdo-mysql | default | 31.9 / 32 | 0 / 0 | 31.9 / 32 | 31.9 / 31.9 | 0 / 0 | 0 / 0 |
| php-pdo-mysql | tuned | 31.9 / 32 | 0 / 0 | 31.9 / 32 | 31.9 / 31.9 | 0 / 0 | 0 / 0 |
| rb-mysql2 | default | 7.63 / 7.63 | 0 / 0 | 0 / 0 | 0 / 0 | 0.0625 / 0.0625 | 0 / 0 |
| rb-mysql2 | tuned | 0.0625 / 0.0625 | 0 / 0 | 45.6 / 45.6 | 45.6 / 45.7 | 0 / 0 | 0 / 0 |
| rb-trilogy | default | n/a / n/a | n/a / n/a | 0 / 0 | 0 / 0 | n/a / n/a | n/a / n/a |
| rb-trilogy | tuned | n/a / n/a | n/a / n/a | 0¹⁶ / 0¹⁶ | 0 / 0 | n/a / n/a | n/a / n/a |

¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  

### T4 — memory for the work, MB (Percona / MariaDB)

| stack | config | int-binary | int-text | mix-binary | mix-text |
|---|---|---|---|---|---|
| cpp-mysql-connector | default | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| cpp-mariadb | default | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| rust-mysql | default | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| rust-sqlx | default | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| dotnet-mysqlconnector | default | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| dotnet-mysql-data | default | 0.0781 / 0.0781 | 0.0781 / 0.0781 | 0.113 / 0.109 | 0.125 / 0.129 |
| node-mysql2 | default | 1.85 / 9.05 | 0.258 / 8.43 | 0 / 0 | 0.254¹⁶ / 0 |
| node-mysql2 | tuned | 0 / 0 | 0¹⁶ / 0¹⁶ | 0.629¹⁶ / 0.188¹⁶ | 0 / 0 |
| node-mariadb | default | 0 / 0 | 0.418 / 0 | 0.0625 / 0¹⁶ | 0 / 0.0938 |
| node-mariadb | tuned | 0¹⁶ / 0¹⁶ | 0¹⁶ / 0 | 0 / 0.0586¹⁶ | 0.383¹⁶ / 1.62 |
| node-mysql | default | n/a / n/a | n/a / 0 | n/a / n/a | n/a / 0 |
| php-mysqli | default | 0 / 0 | 1.95 / 1.95 | 13.6 / 13.5 | 16.4 / 16.5 |
| php-mysqli | tuned | 0 / 0 | 1.95 / 1.96 | 13.6 / 13.5 | 16.4 / 16.5 |
| php-pdo-mysql | default | 1.2 / 1.25 | 3.82 / 3.88 | 13.6 / 13.5 | 16.4 / 16.5 |
| php-pdo-mysql | tuned | 1.2 / 1.25 | 3.82 / 3.88 | 13.6 / 13.5 | 16.4 / 16.5 |
| rb-mysql2 | default | 0 / 0 | 0 / 0 | 0.0625 / 0.0625 | 0 / 0.0625 |
| rb-mysql2 | tuned | 0 / 0 | 0.73 / 0.734 | 0 / 0 | 25.7 / 25.7 |
| rb-trilogy | default | n/a / n/a | 0 / 0 | n/a / n/a | 0.188 / 0.191 |
| rb-trilogy | tuned | n/a / n/a | 0 / 0 | n/a / n/a | 0.0625¹⁶ / 0.0625¹⁶ |

¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  

### T5 — memory for the work, MB (Percona / MariaDB)

| stack | config | 100k-doc | 100k-doc+tls | 100k-doc_bin | 10k-doc | 10k-doc_bin | 1k-doc | 1k-doc_bin | mix-doc | mix-doc_bin | 10k-doc-parse |
|---|---|---|---|---|---|---|---|---|---|---|---|
| cpp-mysql-connector | default | 84.4⁵ / 74.4 | 84.5⁵ / 74.5 | 74.4 / 74.4 | 6.06⁵ / 6.56 | 6.56 / 6.56 | 0.422⁵ / 0.297 | 0.297 / 0.297 | 5.91⁵ / 4.9 | 4.9 / 4.9 | n/a⁵ / n/a |
| cpp-mariadb | default | 108⁵ / 97.1 | 108⁵ / 97.1 | 97.1 / 97.1 | 10.9⁵ / 9.94 | 9.94 / 9.94 | 0.828⁵ / 0 | 0 / 0 | 8.56⁵ / 7.81 | 7.81 / 7.81 | n/a⁵ / n/a |
| rust-mysql | default | 107⁵ / 97.4 | 91.9⁵ / 97.1 | 97.4 / 97.4 | 10.4⁵ / 9.53 | 9.41 / 9.53 | 0.656⁵ / 0.656 | 0.656 / 0.656 | 8.66⁵ / 7.91 | 7.78 / 7.91 | 0⁵ / 4.53 |
| rust-sqlx | default | 81.6⁵ / 16.3 | 106⁵ / 98.7 | 14.3 / 6.14 | 0⁵ / 0 | 0.0547 / 0 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0.371 | 0.082 / 0 | 0⁵ / 0 |
| dotnet-mysqlconnector | default | 2.39⁵ / 0.984 | 2.8⁵ / 0.941 | 2.01 / 2.32 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0 | 0 / 0 | 0.422⁵ / 1.31 | 1.79 / 1.8 | 0⁵ / 0 |
| dotnet-mysql-data | default | 0.242⁵ / 0.805 | 0.191⁵˒¹⁶ / 0.789 | 0 / 0.0625 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0 | 0 / 0 | 0⁵˒¹⁶ / 1.12 | 1.76 / 1.75 | 0⁵ / 0 |
| node-mysql2 | default | 2.54⁵ / 2.04 | 2.96⁵ / 3.88 | 15.3 / 31.9 | 1.12⁵ / 0.0586¹⁶ | 1.99 / 3.38 | 0⁵ / 0.0508 | 0 / 0 | 0.297⁵ / 2.34 | 4.34 / 2.19 | 0.441⁵ / 0.23 |
| node-mysql2 | tuned | 4.83⁵ / 4.43 | 6.99⁵ / 3.17 | 2.81 / 20 | 0.508⁵ / 0¹⁶ | 1.99 / 1.62 | 0⁵ / 0 | 0.199 / 0 | 7.96⁵ / 0.336 | 0.73 / 0 | 21.9⁵ / 0.164 |
| node-mariadb | default | 3.45⁵ / 2.84 | 5.05⁵ / 2.21 | 24.3 / 22.7 | 0.402⁵ / 5.12 | 0.723 / 1.6 | 0⁵ / 0 | 0.219 / 0 | 0.641⁵ / 2.59 | 4.03 / 0 | 0⁵ / 0.508 |
| node-mariadb | tuned | 2.26⁵ / 5.83 | 2.64⁵ / 3.35 | 21.8 / 15.4 | 0⁵ / 0.738 | 1.81 / 1.55 | 0⁵˒¹⁶ / 0 | 0.0625 / 0 | 0.363⁵ / 0.449 | 0.164 / 0 | 0⁵ / 0.109 |
| node-mysql | default | n/a⁵ / 6.47 | n/a⁵ / 9.45 | n/a / 0 | n/a⁵ / 6.2 | n/a / 4.87 | n/a⁵ / 0.625¹⁶ | n/a / 0 | n/a⁵ / 6.56 | n/a / 0 | n/a⁵ / 0 |
| php-mysqli | default | 107⁵ / 97.8 | 107⁵ / 97.7 | 97.7 / 97.8 | 10.3⁵ / 10.4 | 10.3 / 10.4 | 0⁵ / 0 | 0 / 0 | 6.45⁵ / 5.75 | 5.7 / 5.75 | 7.82⁵ / 7.88 |
| php-mysqli | tuned | 107⁵ / 97.8 | 107⁵ / 97.7 | 97.7 / 97.8 | 10.3⁵ / 10.4 | 10.3 / 10.4 | 0⁵ / 0 | 0 / 0 | 6.45⁵ / 5.75 | 5.7 / 5.75 | 7.82⁵ / 7.88 |
| php-pdo-mysql | default | 107⁵ / 97.8 | 107⁵ / 97.7 | 97.7 / 97.8 | 10.3⁵ / 10.4 | 10.3 / 10.4 | 0⁵ / 0 | 0 / 0 | 6.45⁵ / 5.75 | 5.7 / 5.75 | 9.34⁵ / 9.39 |
| php-pdo-mysql | tuned | 107⁵ / 97.8 | 107⁵ / 97.7 | 97.7 / 97.8 | 10.3⁵ / 10.4 | 10.3 / 10.4 | 0⁵ / 0 | 0 / 0 | 6.45⁵ / 5.75 | 5.7 / 5.75 | 7.84⁵ / 7.89 |
| rb-mysql2 | default | 29.6⁵ / 77.8 | 16.7⁵ / 105 | 102 / 99.6 | 0⁵ / 0 | 0 / 0 | 0.273⁵ / 0 | 0 / 0.254 | 0⁵ / 0 | 0 / 0 | 0.129⁵ / 11.5 |
| rb-mysql2 | tuned | FAIL⁵˒¹⁴ / FAIL¹⁴ | FAIL⁵˒¹⁴ / FAIL¹⁴ | FAIL¹⁴ / FAIL¹⁴ | 30.6⁵ / 15.8 | 18 / 18.4 | 1.12⁵ / 1.87 | 1.54 / 1.97 | 2.22⁵ / 6.29 | 6.45 / 6.44 | 217⁵ / 197 |
| rb-trilogy | default | 9.64⁵ / 35.7 | 7.44⁵ / 29 | 36.3 / 36.3 | 0⁵ / 0.0625 | 0 / 0 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0 | 0 / 1.26 | 0⁵ / 0 |
| rb-trilogy | tuned | 5.35⁵ / 43.7 | 65.2⁵ / 0 | 43.7 / 43.6 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0 | 0 / 0 | 0.0742⁵ / 9.83 |

⁵ **Percona converts JSON on every read.** Percona Server (like MySQL) stores JSON in a binary format and converts it to text on every read: about 13× the server CPU of the same bytes as LONGBLOB, and ~10% larger output. The slower send makes most clients spend more CPU per KB than reading the same documents from MariaDB, which stores JSON as text.  
¹⁴ **Runs out of memory.** With as: :array and cache_rows: false, mysql2 kept growing past the 8 GB client cap on 100 KB documents and was killed (on both servers; before the cap existed it pushed the host into the kernel OOM killer twice). Results that are not freed explicitly hold their C buffers, which Ruby's garbage collector does not account for.  
¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  

### T6 — memory for the work, MB (Percona / MariaDB)

| stack | config | batch | multiparam | sqltext |
|---|---|---|---|---|
| cpp-mysql-connector | default | n/a / n/a | 0 / 0 | 0 / 0 |
| cpp-mariadb | default | 0 / 0 | 0.125 / 0.0703 | 0 / 0.0547 |
| rust-mysql | default | 0 / 0.0586 | 0.0508 / 0.0508 | 0.0547 / 0.0547 |
| rust-sqlx | default | n/a / n/a | 0 / 0 | 0 / 0 |
| dotnet-mysqlconnector | default | 0.156 / 0 | 0 / 0.145 | 0.133 / 0 |
| dotnet-mysql-data | default | n/a / n/a | 0.0938 / 0 | 0 / 0.156 |
| node-mysql2 | default | 0.289 / 0.547 | 0.156 / 0 | 0 / 0.621 |
| node-mysql2 | tuned | 0 / 0.0742 | 0 / 0 | 0 / 0 |
| node-mariadb | default | 0.176 / 0 | 0.23 / 0.688 | 0.484 / 0 |
| node-mariadb | tuned | 0.914 / 0 | 0.605 / 0.543 | 1.44 / 0.125 |
| node-mysql | default | n/a / 0.918 | n/a / 0 | n/a / 0.176 |
| php-mysqli | default | n/a / n/a | 0 / 0 | 0 / 0 |
| php-mysqli | tuned | n/a / n/a | 0 / 0 | 0 / 0 |
| php-pdo-mysql | default | n/a / n/a | 0 / 0 | 0 / 0 |
| php-pdo-mysql | tuned | n/a / n/a | 0 / 0 | 0 / 0 |
| rb-mysql2 | default | n/a / n/a | 0 / 0 | 0.0625 / 0.0625 |
| rb-mysql2 | tuned | n/a / n/a | 0 / 0 | 0.0625 / 0.0625 |
| rb-trilogy | default | n/a / n/a | n/a / n/a | 0 / 0 |
| rb-trilogy | tuned | n/a / n/a | n/a / n/a | 0 / 0 |

### T3 — memory growth since connect, MB (Percona / MariaDB)

| stack | config | binary-buffered | binary-streamed | text-buffered | text-buffered+tls | text-streamed | text-streamed+tls |
|---|---|---|---|---|---|---|---|
| cpp-mysql-connector | default | 30.5 / 30.5 | n/a / n/a | 45.8 / 45.8 | 45.8 / 45.8 | 0.0703 / 0.0742 | 0.0625 / 0.0625 |
| cpp-mariadb | default | 115 / 115 | 0.242 / 0.242 | 45.8 / 45.8 | 45.8 / 45.8 | 0.18 / 0.176 | 0.141 / 0.168 |
| rust-mysql | default | 11.4 / 11.4 | 4.07 / 4.07 | 11.4 / 11.4 | 11.6 / 11.7 | 4.07 / 4.07 | 4.07 / 4.09 |
| rust-sqlx | default | 117 / 116 | 0 / 0 | 118 / 118 | 122 / 122 | 0.0547 / 0.0586 | 0.0859 / 0.0977 |
| dotnet-mysqlconnector | default | n/a / n/a | 2.73 / 2.91 | n/a / n/a | n/a / n/a | 3.13 / 2.83 | 2.72 / 2.51 |
| dotnet-mysql-data | default | n/a / n/a | 19.3 / 19.4 | n/a / n/a | n/a / n/a | 20.3 / 19.3 | 17.8 / 17.5 |
| node-mysql2 | default | 409 / 412 | n/a / n/a | 473 / 415 | 385¹⁶ / 381 | 67 / 75.3 | 68.7 / 67.6 |
| node-mysql2 | tuned | 441 / 493 | n/a / n/a | 464 / 376 | 392 / 349 | 67.8 / 76.9 | 78.4 / 67.8 |
| node-mariadb | default | 410¹⁶ / 400 | 115 / 115 | 403 / 396 | 397 / 389¹⁶ | 116 / 74.2 | 117 / 77.4 |
| node-mariadb | tuned | 456 / 401 | 79.5 / 113 | 423 / 396 | 477¹⁶ / 427¹⁶ | 75.6 / 116 | 111 / 80.1 |
| node-mysql | default | n/a / n/a | n/a / n/a | n/a / 399 | n/a / 300¹⁶ | n/a / 46.9 | n/a / 49.2 |
| php-mysqli | default | 35.1 / 35.1 | 0 / 0 | 35 / 35.1 | 35 / 35 | 0 / 0 | 0 / 0 |
| php-mysqli | tuned | 35.1 / 35.1 | 0 / 0 | 35 / 35.1 | 35 / 35 | 0 / 0 | 0 / 0 |
| php-pdo-mysql | default | 35.1 / 35.1 | 0 / 0 | 35 / 35.1 | 35 / 35 | 0 / 0 | 0 / 0 |
| php-pdo-mysql | tuned | 35.1 / 35.1 | 0 / 0 | 35 / 35.1 | 35 / 35 | 0 / 0 | 0 / 0 |
| rb-mysql2 | default | 461 / 461 | 1.43 / 1.43 | 400 / 400 | 400 / 400 | 1.44 / 1.45 | 1.15 / 1.16 |
| rb-mysql2 | tuned | 208 / 208 | 0.469 / 0.469 | 230 / 230 | 230 / 230 | 0.375 / 0.379 | 0.277 / 0.281 |
| rb-trilogy | default | n/a / n/a | n/a / n/a | 330 / 318 | 341 / 214 | n/a / n/a | n/a / n/a |
| rb-trilogy | tuned | n/a / n/a | n/a / n/a | 163¹⁶ / 163¹⁶ | 109 / 110 | n/a / n/a | n/a / n/a |

¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  

### T4 — memory growth since connect, MB (Percona / MariaDB)

| stack | config | int-binary | int-text | mix-binary | mix-text |
|---|---|---|---|---|---|
| cpp-mysql-connector | default | 4.45 / 4.46 | 14.8 / 14.8 | 15.6 / 15.6 | 26 / 26 |
| cpp-mariadb | default | 51.5 / 51.5 | 15.8 / 15.8 | 73.2 / 73.2 | 26.9 / 26.9 |
| rust-mysql | default | 4 / 4 | 4 / 4 | 4 / 4 | 4 / 4 |
| rust-sqlx | default | 30.6 / 30.6 | 34.6 / 34.6 | 42.9 / 42.9 | 52.2 / 52.2 |
| dotnet-mysqlconnector | default | 1.8 / 1.8 | 1.56 / 1.56 | 18.6 / 18.6 | 18.7 / 18.6 |
| dotnet-mysql-data | default | 18.1 / 17.7 | 18.2 / 17.7 | 19.6 / 19.1 | 19.6 / 19.1 |
| node-mysql2 | default | 209 / 205 | 209 / 214 | 337 / 336 | 226¹⁶ / 319 |
| node-mysql2 | tuned | 79.1 / 82.6 | 93¹⁶ / 100¹⁶ | 302¹⁶ / 302¹⁶ | 311 / 311 |
| node-mariadb | default | 403 / 372 | 390 / 439 | 296 / 425¹⁶ | 407 / 402 |
| node-mariadb | tuned | 78.9¹⁶ / 73.3¹⁶ | 89.7¹⁶ / 71.9 | 283 / 292¹⁶ | 243¹⁶ / 277 |
| node-mysql | default | n/a / n/a | n/a / 379 | n/a / n/a | n/a / 532 |
| php-mysqli | default | 5.14 / 5.14 | 9.13 / 9.13 | 16.9 / 16.8 | 19.6 / 19.7 |
| php-mysqli | tuned | 5.14 / 5.14 | 9.13 / 9.13 | 16.9 / 16.8 | 19.6 / 19.7 |
| php-pdo-mysql | default | 4.45 / 4.45 | 6.94 / 7 | 16.8 / 16.7 | 19.6 / 19.6 |
| php-pdo-mysql | tuned | 4.43 / 4.43 | 6.94 / 7 | 16.8 / 16.7 | 19.6 / 19.6 |
| rb-mysql2 | default | 106 / 106 | 81.5 / 81.6 | 188 / 188 | 201 / 209 |
| rb-mysql2 | tuned | 19.9 / 19.9 | 54.7 / 54.7 | 163 / 163 | 209 / 209 |
| rb-trilogy | default | n/a / n/a | 71 / 71 | n/a / n/a | 201 / 201 |
| rb-trilogy | tuned | n/a / n/a | 27.5 / 27.5 | n/a / n/a | 197¹⁶ / 197¹⁶ |

¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  

### T5 — memory growth since connect, MB (Percona / MariaDB)

| stack | config | 100k-doc | 100k-doc+tls | 100k-doc_bin | 10k-doc | 10k-doc_bin | 1k-doc | 1k-doc_bin | mix-doc | mix-doc_bin | 10k-doc-parse |
|---|---|---|---|---|---|---|---|---|---|---|---|
| cpp-mysql-connector | default | 108⁵ / 97.8 | 108⁵ / 97.9 | 97.8 / 97.8 | 10.8⁵ / 9.77 | 9.77 / 9.77 | 1⁵ / 0.883 | 0.875 / 0.883 | 8.97⁵ / 8.2 | 8.21 / 8.2 | n/a⁵ / n/a |
| cpp-mariadb | default | 109⁵ / 98.9 | 109⁵ / 99 | 98.9 / 98.9 | 11.1⁵ / 10.1 | 10.1 / 10.1 | 1.01⁵ / 1.05 | 1.1 / 1.05 | 8.96⁵ / 8.2 | 8.2 / 8.2 | n/a⁵ / n/a |
| rust-mysql | default | 111⁵ / 101 | 112⁵ / 102 | 101 / 101 | 14.3⁵ / 13.5 | 13.3 / 13.5 | 4.6⁵ / 4.6 | 4.6 / 4.6 | 12.6⁵ / 11.8 | 11.7 / 11.8 | 14.7⁵ / 13.6 |
| rust-sqlx | default | 117⁵ / 130 | 116⁵ / 117 | 131 / 131 | 14.7⁵ / 13.9 | 13.9 / 13.9 | 1.71⁵ / 1.57 | 1.58 / 1.56 | 12.6⁵ / 11.9 | 11.9 / 12 | 14.9⁵ / 14 |
| dotnet-mysqlconnector | default | 17.2⁵ / 12.2 | 16.8⁵ / 8.71 | 14.3 / 13.7 | 24.6⁵ / 23.7 | 23.7 / 23.7 | 23.6⁵ / 23.4 | 23.5 / 23.4 | 13.5⁵ / 13 | 12.7 / 12.7 | 31.3⁵ / 27.7 |
| dotnet-mysql-data | default | 11.5⁵ / 10.8 | 12.5⁵˒¹⁶ / 9.14 | 11.1 / 10.5 | 24.8⁵ / 23.2 | 24.1 / 23.6 | 23⁵ / 22.4 | 23.2 / 22.9 | 21.1⁵˒¹⁶ / 12.6 | 12.8 / 13 | 29.8⁵ / 23.3 |
| node-mysql2 | default | 573⁵ / 590 | 519⁵ / 577 | 197 / 197 | 144⁵ / 153¹⁶ | 88.8 / 89.7 | 80.8⁵ / 85.6 | 42.2 / 40.3 | 139⁵ / 140 | 87 / 87.1 | 204⁵ / 232 |
| node-mysql2 | tuned | 544⁵ / 578 | 546⁵ / 576 | 188 / 191 | 135⁵ / 153¹⁶ | 91.5 / 91 | 82.6⁵ / 84.2 | 48.6 / 70 | 141⁵ / 144 | 84.5 / 86 | 206⁵ / 233 |
| node-mariadb | default | 548⁵ / 606 | 523⁵ / 581 | 192 / 194 | 135⁵ / 149 | 93.4 / 98.7 | 85.7⁵ / 87.8 | 44.3 / 44.8 | 135⁵ / 140 | 91.6 / 92.3 | 209⁵ / 222 |
| node-mariadb | tuned | 549⁵ / 585 | 516⁵ / 577 | 194 / 205 | 148⁵ / 151 | 95 / 93.1 | 83⁵˒¹⁶ / 88 | 50 / 52.6 | 143⁵ / 147 | 101 / 93.8 | 206⁵ / 216 |
| node-mysql | default | n/a⁵ / 602 | n/a⁵ / 580 | n/a / 219 | n/a⁵ / 174 | n/a / 96.1 | n/a⁵ / 114¹⁶ | n/a / 103 | n/a⁵ / 142 | n/a / 100 | n/a⁵ / 225 |
| php-mysqli | default | 110⁵ / 101 | 110⁵ / 101 | 101 / 101 | 11.6⁵ / 11.7 | 11.6 / 11.7 | 1.06⁵ / 0.926 | 0.926 / 0.926 | 9.03⁵ / 8.2 | 8.15 / 8.2 | 12.4⁵ / 12.5 |
| php-mysqli | tuned | 110⁵ / 101 | 110⁵ / 101 | 101 / 101 | 11.6⁵ / 11.7 | 11.6 / 11.7 | 1.06⁵ / 0.926 | 0.926 / 0.938 | 9.03⁵ / 8.2 | 8.15 / 8.2 | 12.4⁵ / 12.5 |
| php-pdo-mysql | default | 110⁵ / 101 | 110⁵ / 101 | 101 / 101 | 11.6⁵ / 11.7 | 11.6 / 11.7 | 1.07⁵ / 0.934 | 0.934 / 0.934 | 9.02⁵ / 8.19 | 8.14 / 8.19 | 12⁵ / 12.1 |
| php-pdo-mysql | tuned | 110⁵ / 101 | 110⁵ / 101 | 101 / 101 | 11.6⁵ / 11.7 | 11.6 / 11.7 | 1.07⁵ / 0.934 | 0.934 / 0.934 | 9.02⁵ / 8.19 | 8.14 / 8.19 | 12.4⁵ / 12.5 |
| rb-mysql2 | default | 476⁵ / 450 | 489⁵ / 469 | 450 / 469 | 97.8⁵ / 73 | 72.3 / 72.3 | 12.4⁵ / 11.3 | 11.3 / 11.6 | 83.8⁵ / 77.3 | 76.8 / 76.8 | 106⁵ / 111 |
| rb-mysql2 | tuned | FAIL⁵˒¹⁴ / FAIL¹⁴ | FAIL⁵˒¹⁴ / FAIL¹⁴ | FAIL¹⁴ / FAIL¹⁴ | 127⁵ / 104 | 106 / 106 | 12.8⁵ / 12.4 | 12.4 / 12.1 | 95.3⁵ / 100 | 98.8 / 98.8 | 1,739⁵ / 1,579 |
| rb-trilogy | default | 442⁵ / 440 | 442⁵ / 435 | 442 / 443 | 76.6⁵ / 62.9 | 63 / 63 | 9.44⁵ / 8.77 | 8.77 / 8.77 | 63.5⁵ / 58.1 | 63.3 / 67.4 | 99.8⁵ / 110 |
| rb-trilogy | tuned | 471⁵ / 451 | 361⁵ / 410 | 451 / 451 | 89⁵ / 81.4 | 81.3 / 81.3 | 8.62⁵ / 7.94 | 7.94 / 7.95 | 81.3⁵ / 54.6 | 54.6 / 54.6 | 111⁵ / 150 |

⁵ **Percona converts JSON on every read.** Percona Server (like MySQL) stores JSON in a binary format and converts it to text on every read: about 13× the server CPU of the same bytes as LONGBLOB, and ~10% larger output. The slower send makes most clients spend more CPU per KB than reading the same documents from MariaDB, which stores JSON as text.  
¹⁴ **Runs out of memory.** With as: :array and cache_rows: false, mysql2 kept growing past the 8 GB client cap on 100 KB documents and was killed (on both servers; before the cap existed it pushed the host into the kernel OOM killer twice). Results that are not freed explicitly hold their C buffers, which Ruby's garbage collector does not account for.  
¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  

### T6 — memory growth since connect, MB (Percona / MariaDB)

| stack | config | batch | multiparam | sqltext |
|---|---|---|---|---|
| cpp-mysql-connector | default | n/a / n/a | 2.52 / 2.08 | 0.176 / 0.176 |
| cpp-mariadb | default | 0.57 / 0.395 | 0.902 / 0.914 | 0.219 / 0.23 |
| rust-mysql | default | 4 / 0.371 | 1.12 / 1.16 | 0.328 / 0.328 |
| rust-sqlx | default | n/a / n/a | 0.305 / 0.305 | 0.25 / 0.25 |
| dotnet-mysqlconnector | default | 31.4 / 31.2 | 31.8 / 31.6 | 27.7 / 27.1 |
| dotnet-mysql-data | default | n/a / n/a | 29.1 / 31.2 | 25.6 / 24.1 |
| node-mysql2 | default | 63.7 / 64 | 64.9 / 64.4 | 65 / 63.4 |
| node-mysql2 | tuned | 64.9 / 65.1 | 64.9 / 64.2 | 62.5 / 63.9 |
| node-mariadb | default | 91.9 / 69.9 | 72.5 / 71.7 | 60.7 / 61.5 |
| node-mariadb | tuned | 93.6 / 70.6 | 72.6 / 74.2 | 59.9 / 61.4 |
| node-mysql | default | n/a / 68.6 | n/a / 70.9 | n/a / 69.5 |
| php-mysqli | default | n/a / n/a | 0.414 / 0.414 | 0.141 / 0.141 |
| php-mysqli | tuned | n/a / n/a | 0.414 / 0.414 | 0.141 / 0.141 |
| php-pdo-mysql | default | n/a / n/a | 1.05 / 1.05 | 0.172 / 0.172 |
| php-pdo-mysql | tuned | n/a / n/a | 1.05 / 1.05 | 0.172 / 0.172 |
| rb-mysql2 | default | n/a / n/a | 3.08 / 3.07 | 0.684 / 0.68 |
| rb-mysql2 | tuned | n/a / n/a | 3.09 / 3.07 | 0.684 / 0.672 |
| rb-trilogy | default | n/a / n/a | n/a / n/a | 4.04 / 4 |
| rb-trilogy | tuned | n/a / n/a | n/a / n/a | 4.12 / 4.04 |
