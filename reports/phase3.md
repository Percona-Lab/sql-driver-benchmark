# Phase 3 report — frameworks, ORMs and query builders

> **AI-generated results.** This benchmark was designed, run and analyzed with an AI assistant (Claude). Results and findings have been spot-checked by a person, but not every number and explanation has been verified in detail, and some may be wrong. The code and raw data are published so you can verify anything here; please report problems as [issues](https://github.com/Percona-Lab/sql-driver-benchmark/issues).

Run: 2026-11-22 → 2026-11-26, same host, servers and method as [Phase 1](phase1.md) and [Phase 2](phase2.md); JIT cells
were rerun on 2026-11-26 with the plateau check described below. 22 frameworks in eight languages, each measured on the
same tests as the drivers, in two configurations: **default** (the framework's usual idiom: entities/models, its query
builder) and **tuned** (the framework's own lighter API: scalar/array results, streaming, bulk insert — listed exactly
below). Tests that a framework does not change (connects go through the driver) are not repeated here.

| language | frameworks | on driver |
|---|---|---|
| Python 3.14 | SQLAlchemy 2.1.9 Core and ORM, Django 6.1.3 ORM | mysqlclient |
| Java 25 | Spring JDBC 7.1.0 (JdbcTemplate), jOOQ 3.21.10, Hibernate ORM 7.4.17 | MySQL Connector/J 26.10 |
| Go | sqlx 1.4.0, GORM 1.31.2 | go-sql-driver/mysql 1.10.2 |
| Node.js 26 | Knex 3.3.0, Drizzle 0.45.4, TypeORM 1.1.3, Sequelize 6.37.8 | mysql2 3.24.6 |
| Node.js 26 | Prisma 7.10.1 (driver adapter) | mariadb 3.5.5 |
| .NET 10 | Dapper 2.1.100, EF Core 9.0.23 + Pomelo 9.0.0 | MySqlConnector |
| PHP 8.5 | Doctrine DBAL 4.6.0, Doctrine ORM 3.8.0, Eloquent (illuminate/database 13.43.0) | PDO_MySQL (mysqlnd) |
| Ruby 4.0 (YJIT) | Sequel 5.110.0, ActiveRecord 8.1.4.1 | mysql2 0.5.7 |
| Rust | Diesel 2.4.0 | libmysqlclient 9.7 (C) |
| Rust | SeaORM 2.0.4 | sqlx 0.9.1 |

All numbers are **client CPU per operation** (user + kernel, whole process, GC and JIT threads included), median of 5
fresh processes, in steady state, shown as **Percona / MariaDB**; memory tables come from a separate memory pass.
Interactive version: https://percona-lab.github.io/sql-driver-benchmark/ · Method: [SPEC.md](../SPEC.md) ·
host pitfalls we found and fixed: [measurement-pitfalls](../docs/measurement-pitfalls.md).

**Memory measures.** *Memory for the work* is the peak resident memory during a measured iteration minus the memory at its
start. It reads near zero when a runtime keeps freed memory between iterations (Python's allocator, garbage-collected heaps),
so for those *memory growth* is the better measure: the highest peak minus the memory right after connecting, before warm-up.
Growth of JIT/GC runtimes includes heap the runtime chose to keep (the JVM sizes its heap up to a quarter of RAM by default).

**Framework tax** = framework CPU ÷ CPU of the driver it runs on, same server, test and configuration. The driver
baseline is the driver's result for the same variant; for point selects where the driver has no such variant, the
protocol the framework uses (Ruby frameworks: escaped literal SQL; Diesel and SeaORM: prepared statements). For bulk
insert the baseline is the driver's single 1,000-row `INSERT … VALUES (?,?,?,?),…` with bound parameters.

## Correction: steady state for JIT runtimes (2026-11-26)

The adaptive warm-up stopped once three iterations agreed within 5%. Three equal iterations can be a plateau of
not-yet-optimized code: .NET ran streamed reads at about 600 ms per iteration for several iterations, then about 120 ms
once optimized code arrived, so the reported median mixed both. Every timed JIT process is now checked after it runs (first
measured iteration more than 10% above the median of the last three → rerun with 10, 20, then 40 warm-up iterations), and
the 90 earlier JIT cells whose median was more than 5% above their late-iteration level were rerun this way
([SPEC.md](../SPEC.md) section 6). Examples (Percona unless noted, before → after): MySqlConnector streamed rows
480 → **120 ns/row**,
MySql.Data 1,078 → 600 ns/row,
Connector/J buffered rows on MariaDB 272 →
160 ns/row, MariaDB Connector/J 1 KB documents on MariaDB
1,107 → 399 ns/KB. A few JIT cells
still vary between or within processes (GC cycles, or different JIT outcomes per process); they carry the "noisy" note.
The Node.js drivers' streamed results also changed: the runner consumed the driver's stream through an extra async
generator (one more promise per row); it now iterates the driver's stream directly, as an application would (mysql2
288 → 152 ns/row, mariadb
165 → 91.5 ns/row).

## Key findings (Percona; MariaDB is similar, see the tables)

**Point selects: thin layers are nearly free, ORMs are not**
- Dapper 6.07 µs vs MySqlConnector 5.38 µs
  (1.1×); go-sqlx 1.1×; Diesel 5.29 µs vs
  libmysqlclient prepared 4.23 µs; Hibernate with StatelessSession
  6.98 µs vs Connector/J 6.11 µs.
- **Python ORMs are the most expensive per query:** Django 98.4 µs and SQLAlchemy ORM
  76.7 µs vs mysqlclient 6.99 µs
  (14.1× and 11.0×). Building the SQLAlchemy statement once and reusing it
  cuts Core from 45.3 to 15.8 µs.
- Prisma 44.6 µs vs its mariadb driver 7.24 µs
  (6.2×); Eloquent models 48.8 µs vs its query builder
  20.7 µs; Sequelize 36.9 µs.
- In Ruby the model lookup by primary key *is* the fastest path: ActiveRecord `find` 14
  µs, Sequel `Model[pk]` 10.1 µs; the "lighter" APIs we tried were slower (see the tuned list).

**Large results: entities cost 4–28× the driver; the framework's own scalar/array API removes most of it**
- 1M rows as entities, ns/row: Eloquent 4,576, Doctrine ORM
  3,982, SQLAlchemy ORM 3,397, Sequelize
  1,680, Hibernate 1,129, Prisma
  752 — against 162 (PDO),
  218 (mysqlclient), 107 (mysql2),
  268 (Connector/J).
- Tuned (scalars / arrays, no entities): Doctrine DQL scalar 79.7,
  Django `values_list` 202, Hibernate StatelessSession
  304, Sequelize `raw: true`
  219 ns/row. Prisma has no such option
  (703 with `select`).
- **Memory for 1M entities** (growth since connect): Hibernate 1,532 MB,
  ActiveRecord 1,478 MB, Sequelize
  1,309 MB, SQLAlchemy ORM
  1,203 MB, Eloquent 1,204 MB,
  Doctrine 1,059 MB; with `yield_per` SQLAlchemy needs
  3.81 MB, Hibernate StatelessSession
  13.4 MB, Doctrine scalar results
  42.1 MB.
- Streaming through the framework: GORM `Rows` + `ScanRows` 893 ns/row vs go-sql-driver
  101 (8.9×); Drizzle's `iterator()`
  1,829 ns/row vs mysql2 152. ActiveRecord cannot
  stream (its `find_each` runs 1,000 keyset queries); Sequelize and Prisma have no row streaming.

**Wide rows and large values**
- 100 mixed-type columns: Doctrine ORM 640 ns/cell and Eloquent
  802 vs PDO 69.8; Prisma
  893 vs mariadb 216; Diesel
  53.7 vs libmysqlclient 11.1 (its per-column
  deserialization dominates in an otherwise cheap stack).
- Large values cost little extra: on 10 KB BLOBs most frameworks are within 1.1–1.8× of their driver (Dapper
  1.5×, GORM 1.2×, TypeORM
  1.2×); copying the bytes is the driver's work. Defaults that load the whole entity
  also read the row's other large column: SQLAlchemy ORM 2.4× and Diesel
  2.2× by default, 1.1× and
  0.8× selecting only that column. Prisma 2.9×.
- **SeaORM 2.0.4 cannot read a MySQL JSON column as text** (only as parsed JSON), so its text-JSON results are n/a on
  Percona.

**Bulk insert: the API decides, and some "bulk" APIs insert row by row**
- Per-row model inserts (the default ORM idiom), µs per 1,000 rows: Sequel 27,909, ActiveRecord
  26,285, SQLAlchemy ORM unit of work 15,389, Doctrine ORM
  11,009, Hibernate 8,118. With the framework's bulk API:
  Sequel `multi_insert` 1,660, ActiveRecord `insert_all`
  5,408, SQLAlchemy ORM bulk INSERT
  4,400, Hibernate `StatelessSession.insertMultiple()`
  1,762 — against one driver-level 1,000-row INSERT: mysql2 (Ruby)
  351, mysqlclient 1,811, Connector/J
  397.
- **Prisma `createMany`: 33,744 µs per 1,000 rows**, 134.4× its driver's
  multi-row INSERT (251 µs). Drizzle builds one multi-row INSERT but needs
  6,648 µs to do it (33.9×).
- **Dapper's `Execute(sql, list)` runs the statement once per element** (5,613 µs per 1,000 rows),
  as does Doctrine DBAL's `insert()` (6,241). Neither is a multi-row insert.
- **Hibernate's `StatelessSession.insert()` is not batched** even with `hibernate.jdbc.batch_size`: our first tuned run
  used it and measured 6,109 µs per 1,000 rows; `insertMultiple()` batches (1,762 µs).

**Other**
- Diesel runs session-setup statements on every connection: a plain connect costs 63.3 µs vs
  23.9 µs for libmysqlclient alone.
- JdbcTemplate with a global streaming fetch size (`setFetchSize(Integer.MIN_VALUE)`) makes every single-row lookup slower:
  16.2 vs 7.75 µs. Set it per query.

## Framework tax tables

Default and tuned framework CPU next to the driver baseline (Percona). Ratios below 1 happen where the framework uses a
cheaper API than the driver's default (e.g. numeric arrays instead of PDO's FETCH_BOTH, or typed readers).

### Point select (parameterized) — µs/query, Percona

| framework | default | tuned | driver baseline (variant) | default ÷ driver | tuned ÷ driver |
|---|---:|---:|---|---:|---:|
| py-sqlalchemy-core (param) | 45.3 | 15.8 | py-mysqlclient (param) 6.99 | 6.5× | 2.3× |
| py-sqlalchemy-orm (param) | 76.7 | 35.9 | py-mysqlclient (param) 6.99 | 11.0× | 5.1× |
| py-django-orm (param) | 98.4 | 96.5 | py-mysqlclient (param) 6.99 | 14.1× | 13.8× |
| java-jdbctemplate (param) | 7.75 | 16.2 | java-connector-j (param) 6.11 | 1.3× | 2.7× |
| java-jooq (param) | 9.58 | 7.91 | java-connector-j (param) 6.11 | 1.6× | 1.3× |
| java-hibernate (param) | 10.2 | 6.98 | java-connector-j (param) 6.11 | 1.7× | 1.2× |
| go-sqlx (param) | 14.2 | 6.82 | go-sql-driver (param) 13.4 | 1.1× | 1.1× |
| go-gorm (param) | 17.7 | 9.77 | go-sql-driver (param) 13.4 | 1.3× | 1.6× |
| node-knex (param) | 12.9 | – | node-mysql2 (param) 8.86 | 1.5× | – |
| node-drizzle (param) | 21.4 | 10.6 | node-mysql2 (param) 8.86 | 2.4× | 1.2× |
| node-sequelize (param) | 36.9 | 32.6 | node-mysql2 (param) 8.86 | 4.2× | 3.7× |
| node-typeorm (param) | 18.5 | 15 | node-mysql2 (param) 8.86 | 2.1× | 1.7× |
| node-prisma (param) | 44.6 | 43.9 | node-mariadb (param) 7.24 | 6.2× | 6.2× |
| dotnet-dapper (param) | 6.07 | 6.08 | dotnet-mysqlconnector (param) 5.38 | 1.1× | 1.1× |
| dotnet-efcore (param) | 11.9 | 7.65 | dotnet-mysqlconnector (param) 5.38 | 2.2× | 1.4× |
| php-dbal (param) | 7.52 | 5.78 | php-pdo-mysql (param) 4.98 | 1.5× | 1.2× |
| php-doctrine-orm (param) | 14 | 14.5 | php-pdo-mysql (param) 4.98 | 2.8× | 2.9× |
| php-eloquent (param) | 48.8 | 20.7 | php-pdo-mysql (param) 4.98 | 9.8× | 4.2× |
| rb-sequel (param) | 10.1 | 10.1 | rb-mysql2 (literal) 7.7 | 1.3× | 1.3× |
| rb-activerecord (param) | 14 | 13.9 | rb-mysql2 (literal) 7.7 | 1.8× | 1.8× |
| rust-seaorm (param) | 18.8 | 18.5 | rust-sqlx (param) 12.6 | 1.5× | 1.5× |
| rust-diesel (param) | 5.29 | 5.05 | c-libmysqlclient (prepared) 4.23 | 1.3× | 1.2× |

### 1M rows, buffered — ns/row, Percona

| framework | default | tuned | driver baseline (variant) | default ÷ driver | tuned ÷ driver |
|---|---:|---:|---|---:|---:|
| py-sqlalchemy-core (text-buffered) | 483 | 484 | py-mysqlclient (text-buffered) 218 | 2.2× | 2.2× |
| py-sqlalchemy-orm (text-buffered) | 3,397 | 2,137 | py-mysqlclient (text-buffered) 218 | 15.6× | 9.8× |
| py-django-orm (text-buffered) | 1,987 | 202 | py-mysqlclient (text-buffered) 218 | 9.1× | 0.9× |
| java-jdbctemplate (text-buffered) | 289 | 120 | java-connector-j (text-buffered) 268 | 1.1× | 0.5× |
| java-jooq (text-buffered) | 269 | 165 | java-connector-j (text-buffered) 268 | 1.0× | 0.7× |
| java-hibernate (text-buffered) | 1,129 | 304 | java-connector-j (text-buffered) 268 | 4.2× | 1.3× |
| go-sqlx (text-buffered) | 222 | 222 | go-sql-driver (–) – | – | – |
| go-gorm (text-buffered) | 323 | 291 | go-sql-driver (–) – | – | – |
| node-knex (text-buffered) | 103 | – | node-mysql2 (text-buffered) 107 | 1.0× | – |
| node-drizzle (text-buffered) | 217 | 216 | node-mysql2 (text-buffered) 107 | 2.0× | 4.3× |
| node-sequelize (text-buffered) | 1,680 | 219 | node-mysql2 (text-buffered) 107 | 15.7× | 4.4× |
| node-typeorm (text-buffered) | 632 | 108 | node-mysql2 (text-buffered) 107 | 5.9× | 2.2× |
| node-prisma (text-buffered) | 752 | 703 | node-mariadb (text-buffered) 98.6 | 7.6× | 6.1× |
| dotnet-dapper (text-buffered) | 140 | 141 | dotnet-mysqlconnector (–) – | – | – |
| dotnet-efcore (text-buffered) | 1,109 | 310 | dotnet-mysqlconnector (–) – | – | – |
| php-dbal (text-buffered) | 170 | 80 | php-pdo-mysql (text-buffered) 162 | 1.1× | 0.6× |
| php-doctrine-orm (text-buffered) | 3,982 | 79.7 | php-pdo-mysql (text-buffered) 162 | 24.6× | 0.6× |
| php-eloquent (text-buffered) | 4,576 | 230 | php-pdo-mysql (text-buffered) 162 | 28.3× | 1.9× |
| rb-sequel (text-buffered) | 260 | 238 | rb-mysql2 (text-buffered) 232 | 1.1× | 1.3× |
| rb-activerecord (text-buffered) | 630 | 217 | rb-mysql2 (text-buffered) 232 | 2.7× | 1.2× |
| rust-seaorm (binary-buffered) | 325 | 301 | rust-sqlx (binary-buffered) 293 | 1.1× | 1.0× |
| rust-diesel (binary-buffered) | 71.4 | 44.2 | c-libmysqlclient (binary-buffered) 26.8 | 2.7× | 1.6× |

### 1M rows, streamed — ns/row, Percona

| framework | default | tuned | driver baseline (variant) | default ÷ driver | tuned ÷ driver |
|---|---:|---:|---|---:|---:|
| py-sqlalchemy-core (text-streamed) | 351 | 339 | py-mysqlclient (text-streamed) 320 | 1.1× | 1.1× |
| py-sqlalchemy-orm (text-streamed) | 2,121 | 2,122 | py-mysqlclient (text-streamed) 320 | 6.6× | 6.6× |
| py-django-orm (text-streamed) | 1,824 | 184 | py-mysqlclient (text-streamed) 320 | 5.7× | 0.6× |
| java-jdbctemplate (text-streamed) | 147 | 122 | java-connector-j (text-streamed) 149 | 1.0× | 1.0× |
| java-jooq (text-streamed) | 195 | 168 | java-connector-j (text-streamed) 149 | 1.3× | 1.4× |
| java-hibernate (text-streamed) | 1,383 | 313 | java-connector-j (text-streamed) 149 | 9.3× | 2.6× |
| go-sqlx (text-streamed) | 197 | 197 | go-sql-driver (text-streamed) 101 | 1.9× | 2.0× |
| go-gorm (text-streamed) | 893 | 843 | go-sql-driver (text-streamed) 101 | 8.9× | 8.4× |
| node-knex (text-streamed) | 255 | – | node-mysql2 (text-streamed) 152 | 1.7× | – |
| node-drizzle (text-streamed) | 1,829 | 1,829 | node-mysql2 (text-streamed) 152 | 12.0× | 11.6× |
| node-typeorm (text-streamed) | 174 | 176 | node-mysql2 (text-streamed) 152 | 1.1× | 1.1× |
| dotnet-dapper (text-streamed) | 137 | 140 | dotnet-mysqlconnector (text-streamed) 120 | 1.1× | 1.2× |
| dotnet-efcore (text-streamed) | 1,049 | 211 | dotnet-mysqlconnector (text-streamed) 120 | 8.7× | 1.8× |
| php-dbal (text-streamed) | 154 | 155 | php-pdo-mysql (text-streamed) 156 | 1.0× | 1.3× |
| php-doctrine-orm (text-streamed) | 4,135 | 79.3 | php-pdo-mysql (text-streamed) 156 | 26.6× | 0.7× |
| php-eloquent (text-streamed) | 541 | 541 | php-pdo-mysql (text-streamed) 156 | 3.5× | 4.5× |
| rb-sequel (text-streamed) | 241 | 183 | rb-mysql2 (text-streamed) 198 | 1.2× | 1.1× |
| rb-activerecord (text-streamed) | 735 | 228 | rb-mysql2 (text-streamed) 198 | 3.7× | 1.4× |
| rust-seaorm (binary-streamed) | 344 | 319 | rust-sqlx (binary-streamed) 277 | 1.2× | 1.2× |
| rust-diesel (binary-streamed) | 68.6 | 43.7 | c-libmysqlclient (binary-streamed) 24.6 | 2.8× | 1.8× |

### 10,000 × 100 mixed-type columns — ns/cell, Percona

| framework | default | tuned | driver baseline (variant) | default ÷ driver | tuned ÷ driver |
|---|---:|---:|---|---:|---:|
| py-sqlalchemy-core (mix-text) | 205 | 205 | py-mysqlclient (mix-text) 197 | 1.0× | 1.0× |
| py-sqlalchemy-orm (mix-text) | 449 | 367 | py-mysqlclient (mix-text) 197 | 2.3× | 1.9× |
| py-django-orm (mix-text) | 366 | 199 | py-mysqlclient (mix-text) 197 | 1.9× | 1.0× |
| java-jdbctemplate (mix-text) | 64.5 | 60.6 | java-connector-j (mix-text) 87.3 | 0.7× | 0.7× |
| java-jooq (mix-text) | 249 | 221 | java-connector-j (mix-text) 87.3 | 2.8× | 2.5× |
| java-hibernate (mix-text) | 263 | 234 | java-connector-j (mix-text) 87.3 | 3.0× | 2.6× |
| go-sqlx (mix-text) | 127 | 131 | go-sql-driver (mix-text) 61.9 | 2.1× | 2.1× |
| go-gorm (mix-text) | 222 | 207 | go-sql-driver (mix-text) 61.9 | 3.6× | 3.4× |
| node-knex (mix-text) | 132 | – | node-mysql2 (mix-text) 131 | 1.0× | – |
| node-drizzle (mix-text) | 287 | 288 | node-mysql2 (mix-text) 131 | 2.2× | 2.9× |
| node-sequelize (mix-text) | 462 | 303 | node-mysql2 (mix-text) 131 | 3.5× | 3.1× |
| node-typeorm (mix-text) | 260 | 304 | node-mysql2 (mix-text) 131 | 2.0× | 3.1× |
| node-prisma (mix-text) | 893 | 900 | node-mariadb (mix-text) 216 | 4.1× | 8.1× |
| dotnet-dapper (mix-text) | 217 | 159 | dotnet-mysqlconnector (mix-text) 122 | 1.8× | 1.3× |
| dotnet-efcore (mix-text) | 316 | 84.1 | dotnet-mysqlconnector (mix-text) 122 | 2.6× | 0.7× |
| php-dbal (mix-text) | 124 | 102 | php-pdo-mysql (mix-text) 69.8 | 1.8× | 2.4× |
| php-doctrine-orm (mix-text) | 640 | 432 | php-pdo-mysql (mix-text) 69.8 | 9.2× | 10.1× |
| php-eloquent (mix-text) | 802 | 140 | php-pdo-mysql (mix-text) 69.8 | 11.5× | 3.3× |
| rb-sequel (mix-text) | 317 | 246 | rb-mysql2 (mix-text) 261 | 1.2× | 1.3× |
| rb-activerecord (mix-text) | 562 | 313 | rb-mysql2 (mix-text) 261 | 2.2× | 1.6× |
| rust-seaorm (mix-binary) | 145 | 144 | rust-sqlx (mix-binary) 132 | 1.1× | 1.1× |
| rust-diesel (mix-binary) | 53.7 | 53.1 | c-libmysqlclient (mix-binary) 11.1 | 4.9× | 4.8× |

### 1,000 × 10 KB BLOBs — ns/KB, Percona

| framework | default | tuned | driver baseline (variant) | default ÷ driver | tuned ÷ driver |
|---|---:|---:|---|---:|---:|
| py-sqlalchemy-core (10k-doc_bin) | 379 | 377 | py-mysqlclient (10k-doc_bin) 349 | 1.1× | 1.1× |
| py-sqlalchemy-orm (10k-doc_bin) | 855 | 378 | py-mysqlclient (10k-doc_bin) 349 | 2.4× | 1.1× |
| py-django-orm (10k-doc_bin) | 514 | 370 | py-mysqlclient (10k-doc_bin) 349 | 1.5× | 1.1× |
| java-jdbctemplate (10k-doc_bin) | 460 | 303 | java-connector-j (10k-doc_bin) 385 | 1.2× | 0.8× |
| java-jooq (10k-doc_bin) | 498 | 526 | java-connector-j (10k-doc_bin) 385 | 1.3× | 1.4× |
| java-hibernate (10k-doc_bin) | 480 | 481 | java-connector-j (10k-doc_bin) 385 | 1.2× | 1.3× |
| go-sqlx (10k-doc_bin) | 306 | 307 | go-sql-driver (10k-doc_bin) 257 | 1.2× | 1.2× |
| go-gorm (10k-doc_bin) | 314 | 309 | go-sql-driver (10k-doc_bin) 257 | 1.2× | 1.2× |
| node-knex (10k-doc_bin) | 615 | – | node-mysql2 (10k-doc_bin) 505 | 1.2× | – |
| node-drizzle (10k-doc_bin) | 666 | 682 | node-mysql2 (10k-doc_bin) 505 | 1.3× | 1.4× |
| node-sequelize (10k-doc_bin) | 889 | 707 | node-mysql2 (10k-doc_bin) 505 | 1.8× | 1.4× |
| node-typeorm (10k-doc_bin) | 629 | 647 | node-mysql2 (10k-doc_bin) 505 | 1.2× | 1.3× |
| node-prisma (10k-doc_bin) | 1,472 | 1,479 | node-mariadb (10k-doc_bin) 514 | 2.9× | 3.0× |
| dotnet-dapper (10k-doc_bin) | 435 | 432 | dotnet-mysqlconnector (10k-doc_bin) 300 | 1.5× | 1.4× |
| dotnet-efcore (10k-doc_bin) | 513 | 514 | dotnet-mysqlconnector (10k-doc_bin) 300 | 1.7× | 1.7× |
| php-dbal (10k-doc_bin) | 791 | 789 | php-pdo-mysql (10k-doc_bin) 569 | 1.4× | 1.4× |
| php-doctrine-orm (10k-doc_bin) | 792 | 771 | php-pdo-mysql (10k-doc_bin) 569 | 1.4× | 1.4× |
| php-eloquent (10k-doc_bin) | 670 | 669 | php-pdo-mysql (10k-doc_bin) 569 | 1.2× | 1.2× |
| rb-sequel (10k-doc_bin) | 925 | 608 | rb-mysql2 (10k-doc_bin) 569 | 1.6× | 1.0× |
| rb-activerecord (10k-doc_bin) | 945 | 574 | rb-mysql2 (10k-doc_bin) 569 | 1.7× | 0.9× |
| rust-seaorm (10k-doc_bin) | 267 | 255 | rust-sqlx (10k-doc_bin) 222 | 1.2× | 1.1× |
| rust-diesel (10k-doc_bin) | 512 | 178 | c-libmysqlclient (10k-doc_bin) 230 | 2.2× | 0.8× |

### Bulk insert, 1M rows — µs/1,000 rows, Percona

| framework | default | tuned | driver baseline (variant) | default ÷ driver | tuned ÷ driver |
|---|---:|---:|---|---:|---:|
| py-sqlalchemy-core (batch) | 3,225 | 3,264 | py-mysqlclient (multiparam) 1,811 | 1.8× | 1.8× |
| py-sqlalchemy-orm (batch) | 15,389 | 4,400 | py-mysqlclient (multiparam) 1,811 | 8.5× | 2.4× |
| py-django-orm (batch) | 8,014 | 8,028 | py-mysqlclient (multiparam) 1,811 | 4.4× | 4.4× |
| java-jdbctemplate (batch) | 5,661 | 1,488 | java-connector-j (multiparam) 397 | 14.2× | 5.1× |
| java-jooq (batch) | 6,097 | 1,793 | java-connector-j (multiparam) 397 | 15.3× | 6.1× |
| java-hibernate (batch) | 8,118 | 1,762 | java-connector-j (multiparam) 397 | 20.4× | 6.0× |
| go-sqlx (batch) | 466 | 379 | go-sql-driver (multiparam) 312 | 1.5× | 1.7× |
| go-gorm (batch) | 619 | 454 | go-sql-driver (multiparam) 312 | 2.0× | 2.0× |
| node-knex (batch) | 379 | – | node-mysql2 (multiparam) 196 | 1.9× | – |
| node-drizzle (batch) | 6,648 | 6,665 | node-mysql2 (multiparam) 196 | 33.9× | 34.0× |
| node-sequelize (batch) | 2,833 | 728 | node-mysql2 (multiparam) 196 | 14.4× | 3.7× |
| node-typeorm (batch) | 8,163 | 3,826 | node-mysql2 (multiparam) 196 | 41.6× | 19.5× |
| node-prisma (batch) | 33,744 | 33,261 | node-mariadb (multiparam) 251 | 134.4× | 132.4× |
| dotnet-dapper (batch) | 5,613 | 5,595 | dotnet-mysqlconnector (multiparam) 405 | 13.9× | 13.8× |
| dotnet-efcore (batch) | 3,252 | 4,121 | dotnet-mysqlconnector (multiparam) 405 | 8.0× | 10.2× |
| php-dbal (batch) | 6,241 | 6,225 | php-pdo-mysql (multiparam) 467 | 13.4× | 13.4× |
| php-doctrine-orm (batch) | 11,009 | 11,007 | php-pdo-mysql (multiparam) 467 | 23.6× | 23.6× |
| php-eloquent (batch) | 1,600 | 1,599 | php-pdo-mysql (multiparam) 467 | 3.4× | 3.4× |
| rb-sequel (batch) | 27,909 | 1,660 | rb-mysql2 (multiparam) 351 | 79.5× | 4.7× |
| rb-activerecord (batch) | 26,285 | 5,408 | rb-mysql2 (multiparam) 351 | 74.9× | 15.4× |
| rust-seaorm (batch) | 316 | 318 | rust-sqlx (multiparam) 87.6 | 3.6× | 3.6× |
| rust-diesel (batch) | 1,137 | 1,138 | c-libmysqlclient (multiparam) 65.9 | 17.2× | 17.3× |

## What "tuned" changes

Every "tuned" result uses exactly these changes from the library defaults (server settings are never tuned). Stacks not listed have no tuned configuration.

- **py-sqlalchemy-core**: Point select: statement built once with bindparam() and reused, instead of building select() on every call. Other tests identical to default.
- **py-sqlalchemy-orm**: Point select: column query select(TInt.v) instead of loading entities; large results: execution_options(yield_per=1000); JSON/BLOB: column query; bulk insert: ORM bulk INSERT session.execute(insert(TBulk), list_of_dicts) instead of add_all() + flush (unit of work).
- **py-django-orm**: values_list() (tuples, no model instances) instead of model instances for point select, large results, wide rows and JSON/BLOB; bulk insert identical (bulk_create, batch_size=1000, in both configs).
- **java-hibernate**: hibernate.jdbc.batch_size=1000, hibernate.order_inserts=true, StatelessSession (no persistence context) for reads, bulk insert via StatelessSession.insertMultiple() (one JDBC batch per 1,000 rows), plus all Connector/J tuned options above.
- **java-jooq**: Point select: query built once, keepStatement(true), rebound per call; large results: fetchLazy() with row streaming (fetchSize=Integer.MIN_VALUE); plus all Connector/J tuned options above.
- **java-jdbctemplate**: setFetchSize(Integer.MIN_VALUE) on the template (Connector/J row streaming for every query, which slows single-row lookups); wide rows: RowCallbackHandler instead of RowMapper into a List; plus all Connector/J tuned options above.
- **go-sqlx**: go-sql-driver interpolateParams=true; framework code identical to default.
- **go-gorm**: gorm.Config{SkipDefaultTransaction: true, PrepareStmt: true} plus go-sql-driver interpolateParams=true.
- **node-sequelize**: raw: true (plain objects instead of model instances); bulk insert: queryInterface.bulkInsert() instead of Model.bulkCreate().
- **node-typeorm**: Query builder with getRawOne()/getRawMany() (no entities) for point select, large results and wide rows; bulk insert: repository.insert() instead of repository.save().
- **node-drizzle**: Point select: prepared query with sql.placeholder(), built once. Other tests identical to default.
- **node-prisma**: select only the needed field (select: { v: true }) for point select and large results; other tests identical to default.
- **dotnet-dapper**: buffered: false (streamed rows) for large results and wide rows; bulk insert: one explicit transaction per 1,000 rows.
- **dotnet-efcore**: Point select: EF.CompileQuery with AsNoTracking; large results and wide rows: AsNoTracking(); bulk insert: ChangeTracker.AutoDetectChangesEnabled=false and Pomelo MaxBatchSize(1000).
- **php-dbal**: Connection::fetchOne()/fetchFirstColumn()/fetchAllNumeric() instead of the query builder and associative arrays.
- **php-doctrine-orm**: DQL with scalar/array hydration (getSingleScalarResult, getSingleColumnResult, getArrayResult) instead of entities; bulk insert identical (persist + flush per 1,000 rows).
- **php-eloquent**: Query builder (DB::table / toBase(), value(), pluck()) instead of Eloquent model instances; bulk insert identical (Model::insert of 1,000 rows).
- **rb-activerecord**: pluck() (arrays, no model objects) for large results, wide rows and JSON/BLOB; large results streamed variant: in_batches(of: 1000) + pluck instead of find_each; bulk insert: insert_all (one multi-row INSERT per 1,000 rows) instead of create! per row in a transaction. Point select identical (find, which uses a cached statement; pick, select(:v) and prepared_statements: true were all slower).
- **rb-sequel**: Datasets without models: select_map (arrays/values) for large results, wide rows and JSON/BLOB, stream for the streamed variant; bulk insert: multi_insert (one multi-row INSERT per 1,000 rows) instead of Model.create per row in a transaction. Point select identical (Model[pk]; a prepared statement, get(:v) and bound variables were all slower).
- **rust-diesel**: select() of only the needed column (t_int.v, t_blob.doc / doc_bin) instead of loading the Queryable struct for point select, large results and JSON/BLOB; wide rows and bulk insert identical (all columns needed; insert_into().values(&Vec) is one multi-row INSERT in both).
- **rust-seaorm**: select_only().column(..).into_tuple() (no Model) for point select, large results and JSON/BLOB; wide rows and bulk insert identical (insert_many is one multi-row INSERT in both).

## Full tables

Superscript numbers mark results with a note; the notes follow each table. Connects (T1) appear only for frameworks that
open their own connections.

### T1 — client CPU, µs/connect (Percona / MariaDB)

| stack | config | tcp | tls | tls-verify | socket | tcp@ed25519 | tls-verify-resume | tls-resume |
|---|---|---|---|---|---|---|---|---|
| py-sqlalchemy-core | default | 63.3³ / 60.7³ | 3,735 / 4,009¹ | 863 / 1,153¹ | 41.5³ / 41.1³ | n/a / n/a | n/a / n/a¹ | n/a / n/a¹ |
| py-sqlalchemy-core | tuned | 63.4³ / 60.5³ | 3,736 / 4,008¹ | 863 / 1,156¹ | 41.7³ / 40.4³ | n/a / n/a | n/a / n/a¹ | n/a / n/a¹ |
| py-sqlalchemy-orm | default | 95.9³ / 92.8³ | 3,797 / 4,066¹ | 917 / 1,207¹ | 68.7³ / 67.9³ | n/a / n/a | n/a / n/a¹ | n/a / n/a¹ |
| py-sqlalchemy-orm | tuned | 96.9³ / 93.3³ | 3,794 / 4,066¹ | 916 / 1,208¹ | 68.7³ / 67.4³ | n/a / n/a | n/a / n/a¹ | n/a / n/a¹ |
| py-django-orm | default | 86.4³ / 83.1³ | 3,784 / 4,049¹ | 903 / 1,192¹ | 61.9³ / 59.5³ | n/a / n/a | n/a / n/a¹ | n/a / n/a¹ |
| py-django-orm | tuned | 86.6³ / 83.1³ | 3,786 / 4,048¹ | 904 / 1,192¹ | 61.8³ / 60³ | n/a / n/a | n/a / n/a¹ | n/a / n/a¹ |
| java-hibernate | default | 73.1³ / 67.5³ | 1,651¹⁵ / 6,971¹˒¹⁵ | 4,389 / 10,183¹ | n/a³ / n/a³ | n/a / n/a | n/a / n/a¹ | n/a / n/a¹ |
| java-hibernate | tuned | 55.9³ / 51.7³ | 1,498¹⁵ / 7,716¹˒¹⁵ | 4,410 / 10,264¹ | n/a³ / n/a³ | n/a / n/a | n/a / n/a¹ | n/a / n/a¹ |
| rb-sequel | default | 48.6³ / 45³ | 3,824² / 4,100¹˒² | 829 / 1,118¹ | 30.4³ / 28.5³ | n/a / n/a | n/a / n/a¹ | n/a² / n/a¹˒² |
| rb-sequel | tuned | 48.5³ / 45.3³ | 3,824² / 4,102¹˒² | 829 / 1,119¹ | 30.4³ / 28.5³ | n/a / n/a | n/a / n/a¹ | n/a² / n/a¹˒² |
| rb-activerecord | default | 53.5³ / 49.7³ | 3,870² / 4,136¹˒² | 852 / 1,142¹ | 33.1³ / 31.2³ | n/a / n/a | n/a / n/a¹ | n/a² / n/a¹˒² |
| rb-activerecord | tuned | 53.8³ / 49.8³ | 3,872² / 4,140¹˒² | 853 / 1,143¹ | 33.2³ / 31.3³ | n/a / n/a | n/a / n/a¹ | n/a² / n/a¹˒² |
| rust-diesel | default | 63.3³ / 62.2³ | 3,674 / 3,944¹ | 811 / 1,104¹ | 38³ / 37.9³ | n/a / n/a | n/a / n/a¹ | n/a / n/a¹ |
| rust-diesel | tuned | 63.3³ / 62.5³ | 3,668 / 3,944¹ | 811 / 1,103¹ | 38.1³ / 37.9³ | n/a / n/a | n/a / n/a¹ | n/a / n/a¹ |
| rust-seaorm | default | 40.6³ / 37.5³ | 197 / 712¹ | 262 / 779¹ | 26.4³ / 24.8³ | n/a / n/a | n/a / n/a¹ | n/a / n/a¹ |
| rust-seaorm | tuned | 40.8³ / 37.4³ | 197 / 712¹ | 261 / 779¹ | 26.4³ / 24.9³ | n/a / n/a | n/a / n/a¹ | n/a / n/a¹ |

¹ **MariaDB TLS key exchange.** MariaDB 12.3 negotiates ECDH on P-521 (secp521r1); Percona Server uses P-256. Much of the extra client CPU per TLS connect on MariaDB is that server-side choice, not the driver.  
² **TLS without a CA loads the system trust store.** With no CA configured, libmysqlclient, MariaDB Connector/C and the drivers built on them (Connector/C++, mysqlclient, MariaDB Connector/Python, Ruby mysql2) and trilogy load and parse the full system CA bundle (120 certificates) on every connection although they verify nothing.  
³ **Different default authentication.** Each server uses its own default authentication: Percona Server caching_sha2_password (SHA-256 plus an extra round trip on the fast path), MariaDB mysql_native_password. Part of the Percona-vs-MariaDB difference in plain connect cost comes from this, not the driver.  
¹⁵ **Higher run-to-run spread.** The 5 processes for this result differ by more than 5% (coefficient of variation). Small differences against it are not meaningful.  

### T2 — client CPU, µs/query (Percona / MariaDB)

| stack | config | param | prepared | literal |
|---|---|---|---|---|
| py-sqlalchemy-core | default | 45.3 / 45.7 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-core | tuned | 15.8 / 16.1 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-orm | default | 76.7 / 76.4 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-orm | tuned | 35.9 / 35.3 | n/a / n/a | n/a / n/a |
| py-django-orm | default | 98.4 / 97.4 | n/a / n/a | n/a / n/a |
| py-django-orm | tuned | 96.5 / 95.2 | n/a / n/a | n/a / n/a |
| java-jdbctemplate | default | 7.75 / 7.5 | n/a / n/a | n/a / n/a |
| java-jdbctemplate | tuned | 16.2 / 15.8 | n/a / n/a | n/a / n/a |
| java-jooq | default | 9.58 / 9.36 | n/a / n/a | n/a / n/a |
| java-jooq | tuned | 7.91 / 7.81 | n/a / n/a | n/a / n/a |
| java-hibernate | default | 10.2¹⁵ / 9.96¹⁵ | n/a / n/a | n/a / n/a |
| java-hibernate | tuned | 6.98 / 6.82 | n/a / n/a | n/a / n/a |
| go-sqlx | default | 14.2 / 14.7 | n/a / n/a | n/a / n/a |
| go-sqlx | tuned | 6.82 / 6.84 | n/a / n/a | n/a / n/a |
| go-gorm | default | 17.7 / 17.5 | n/a / n/a | n/a / n/a |
| go-gorm | tuned | 9.77 / 9.66 | n/a / n/a | n/a / n/a |
| node-knex | default | 12.9 / 12.9 | n/a / n/a | n/a / n/a |
| node-drizzle | default | 21.4 / 21.5 | n/a / n/a | n/a / n/a |
| node-drizzle | tuned | 10.6 / 10.6 | n/a / n/a | n/a / n/a |
| node-typeorm | default | 18.5 / 18.7 | n/a / n/a | n/a / n/a |
| node-typeorm | tuned | 15 / 15.1 | n/a / n/a | n/a / n/a |
| node-sequelize | default | 36.9 / 36.6 | n/a / n/a | n/a / n/a |
| node-sequelize | tuned | 32.6 / 33.2 | n/a / n/a | n/a / n/a |
| node-prisma | default | 44.6 / 45.2 | n/a / n/a | n/a / n/a |
| node-prisma | tuned | 43.9 / 44.8 | n/a / n/a | n/a / n/a |
| dotnet-dapper | default | 6.07 / 6.08 | n/a / n/a | n/a / n/a |
| dotnet-dapper | tuned | 6.08 / 6.07 | n/a / n/a | n/a / n/a |
| dotnet-efcore | default | 11.9 / 11.8 | n/a / n/a | n/a / n/a |
| dotnet-efcore | tuned | 7.65 / 7.66 | n/a / n/a | n/a / n/a |
| php-dbal | default | 7.52 / 7.48 | n/a / n/a | n/a / n/a |
| php-dbal | tuned | 5.78 / 5.75 | n/a / n/a | n/a / n/a |
| php-doctrine-orm | default | 14 / 14 | n/a / n/a | n/a / n/a |
| php-doctrine-orm | tuned | 14.5 / 14.5 | n/a / n/a | n/a / n/a |
| php-eloquent | default | 48.8 / 48.4 | n/a / n/a | n/a / n/a |
| php-eloquent | tuned | 20.7 / 20.6 | n/a / n/a | n/a / n/a |
| rb-sequel | default | 10.1²⁰ / 9.97²⁰ | n/a²⁰ / n/a²⁰ | n/a²⁰ / n/a²⁰ |
| rb-sequel | tuned | 10.1²⁰ / 9.98²⁰ | n/a²⁰ / n/a²⁰ | n/a²⁰ / n/a²⁰ |
| rb-activerecord | default | 14²⁰ / 13.9²⁰ | n/a²⁰ / n/a²⁰ | n/a²⁰ / n/a²⁰ |
| rb-activerecord | tuned | 13.9²⁰ / 13.9²⁰ | n/a²⁰ / n/a²⁰ | n/a²⁰ / n/a²⁰ |
| rust-diesel | default | 5.29 / 5.27 | n/a / n/a | n/a / n/a |
| rust-diesel | tuned | 5.05 / 5.07 | n/a / n/a | n/a / n/a |
| rust-seaorm | default | 18.8 / 18.7 | n/a / n/a | n/a / n/a |
| rust-seaorm | tuned | 18.5 / 18.4 | n/a / n/a | n/a / n/a |

¹⁵ **Higher run-to-run spread.** The 5 processes for this result differ by more than 5% (coefficient of variation). Small differences against it are not meaningful.  
²⁰ **Ruby point select: tuned = default.** The cached primary-key lookup (ActiveRecord find, Sequel Model[pk]) was the fastest framework path measured; pick/select/prepared statements and Sequel bound variables were slower, so tuned uses the same code.  

### T3 — client CPU, ns/row (Percona / MariaDB)

| stack | config | text-buffered | text-buffered+tls | text-streamed | text-streamed+tls | binary-buffered | binary-streamed |
|---|---|---|---|---|---|---|---|
| py-sqlalchemy-core | default | 483 / 484 | 523 / 522 | 351 / 338 | 384 / 380 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-core | tuned | 484 / 485 | 522 / 525 | 339 / 339 | 379 / 379 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-orm | default | 3,397 / 3,439 | 3,463 / 3,471 | 2,121 / 2,145 | 2,154 / 2,163 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-orm | tuned | 2,137 / 2,123 | 2,160 / 2,163 | 2,122 / 2,130 | 2,172 / 2,161 | n/a / n/a | n/a / n/a |
| py-django-orm | default | 1,987 / 1,979 | 2,030 / 2,028 | 1,824 / 1,818 | 1,869 / 1,851 | n/a / n/a | n/a / n/a |
| py-django-orm | tuned | 202 / 203 | 244 / 243 | 184 / 184 | 225 / 225 | n/a / n/a | n/a / n/a |
| java-jdbctemplate | default | 289 / 274 | 173¹⁵˒¹⁶ / 171¹⁵˒¹⁶ | 147 / 146 | 152 / 147 | n/a / n/a | n/a / n/a |
| java-jdbctemplate | tuned | 120 / 120 | 126 / 121 | 122 / 118 | 123 / 122 | n/a / n/a | n/a / n/a |
| java-jooq | default | 269¹⁵˒¹⁶ / 282¹⁵˒¹⁶ | 308¹⁵˒¹⁶ / 280¹⁵˒¹⁶ | 195 / 198 | 204 / 205 | n/a / n/a | n/a / n/a |
| java-jooq | tuned | 165 / 166 | 167 / 167 | 168 / 166 | 168 / 168 | n/a / n/a | n/a / n/a |
| java-hibernate | default | 1,129¹⁵˒¹⁶ / 1,120¹⁵˒¹⁶ | 1,521¹⁵˒¹⁶ / 1,613¹⁵˒¹⁶ | 1,383¹⁵˒¹⁶ / 1,124¹⁵˒¹⁶ | 1,246¹⁵˒¹⁶ / 1,005¹⁵˒¹⁶ | n/a / n/a | n/a / n/a |
| java-hibernate | tuned | 304 / 312 | 316 / 311 | 313 / 302 | 313 / 323 | n/a / n/a | n/a / n/a |
| go-sqlx | default | 222 / 221 | 228 / 231 | 197 / 198 | 196 / 202 | n/a / n/a | n/a / n/a |
| go-sqlx | tuned | 222 / 223 | 225 / 229 | 197 / 197 | 197 / 201 | n/a / n/a | n/a / n/a |
| go-gorm | default | 323 / 323 | 325 / 328 | 893 / 895 | 907 / 944 | n/a / n/a | n/a / n/a |
| go-gorm | tuned | 291 / 288 | 291 / 290 | 843 / 842 | 855 / 891 | n/a / n/a | n/a / n/a |
| node-knex | default | 103 / 103¹⁵˒¹⁶ | 105¹⁶ / 106¹⁶ | 255 / 270 | 256 / 255 | n/a / n/a | n/a / n/a |
| node-drizzle | default | 217¹⁶ / 216¹⁶ | 221¹⁶ / 231¹⁵˒¹⁶ | 1,829 / 1,847¹⁶ | 1,837¹⁶ / 1,896¹⁶ | n/a / n/a | n/a / n/a |
| node-drizzle | tuned | 216¹⁶ / 215¹⁵˒¹⁶ | 222¹⁵˒¹⁶ / 226¹⁵˒¹⁶ | 1,829 / 1,859 | 1,791¹⁶ / 1,898¹⁶ | n/a / n/a | n/a / n/a |
| node-typeorm | default | 632 / 679¹⁵˒¹⁶ | 630 / 659¹⁵˒¹⁶ | 174¹⁵ / 189¹⁵ | 175 / 187¹⁵ | n/a / n/a | n/a / n/a |
| node-typeorm | tuned | 108 / 105¹⁵˒¹⁶ | 111 / 114¹⁶ | 176¹⁵ / 180¹⁵ | 184 / 178¹⁵ | n/a / n/a | n/a / n/a |
| node-sequelize | default | 1,680 / 1,666¹⁶ | 1,674 / 1,665¹⁶ | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a |
| node-sequelize | tuned | 219¹⁶ / 218¹⁶ | 226¹⁵˒¹⁶ / 215¹⁵˒¹⁶ | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a |
| node-prisma | default | 752¹⁶ / 728¹⁵˒¹⁶ | 775 / 751 | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a |
| node-prisma | tuned | 703¹⁶ / 669¹⁶ | 685 / 689 | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a |
| dotnet-dapper | default | 140¹⁵ / 137¹⁵ | 137 / 139 | 137 / 139¹⁵ | 128¹⁵ / 129¹⁵ | n/a / n/a | n/a / n/a |
| dotnet-dapper | tuned | 141 / 140¹⁵ | 132¹⁵ / 129¹⁵ | 140¹⁵ / 135¹⁵ | 132¹⁵ / 129 | n/a / n/a | n/a / n/a |
| dotnet-efcore | default | 1,109 / 1,118 | 1,103 / 1,122 | 1,049 / 1,049 | 1,070 / 1,051 | n/a / n/a | n/a / n/a |
| dotnet-efcore | tuned | 310 / 310 | 313 / 316 | 211 / 193 | 214 / 197 | n/a / n/a | n/a / n/a |
| php-dbal | default | 170 / 169 | 173 / 171 | 154 / 155 | 155 / 155 | n/a / n/a | n/a / n/a |
| php-dbal | tuned | 80 / 80.8 | 82.6 / 81.6 | 155 / 155 | 155 / 155 | n/a / n/a | n/a / n/a |
| php-doctrine-orm | default | 3,982 / 3,936 | 3,994 / 3,947 | 4,135 / 4,102 | 4,123 / 4,093 | n/a / n/a | n/a / n/a |
| php-doctrine-orm | tuned | 79.7 / 79.8 | 81.3 / 81.5 | 79.3 / 80.4 | 81.6 / 81.8 | n/a / n/a | n/a / n/a |
| php-eloquent | default | 4,576 / 4,579 | 4,601 / 4,608 | 541 / 541 | 540 / 540 | n/a / n/a | n/a / n/a |
| php-eloquent | tuned | 230 / 229 | 230 / 229 | 541 / 541 | 540 / 543 | n/a / n/a | n/a / n/a |
| rb-sequel | default | 260 / 257 | 301 / 297 | 241 / 237 | 295 / 289 | n/a / n/a | n/a / n/a |
| rb-sequel | tuned | 238 / 239 | 280 / 280 | 183 / 183 | 227 / 229 | n/a / n/a | n/a / n/a |
| rb-activerecord | default | 630 / 621 | 661 / 667 | 735¹⁸ / 733¹⁸ | 778¹⁸ / 777¹⁸ | n/a / n/a | n/a¹⁸ / n/a¹⁸ |
| rb-activerecord | tuned | 217 / 216 | 258 / 258 | 228¹⁸ / 227¹⁸ | 273¹⁸ / 273¹⁸ | n/a / n/a | n/a¹⁸ / n/a¹⁸ |
| rust-diesel | default | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | 71.4 / 70.1 | 68.6 / 67.6 |
| rust-diesel | tuned | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | 44.2 / 44.2 | 43.7 / 44.3 |
| rust-seaorm | default | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | 325 / 332 | 344 / 344 |
| rust-seaorm | tuned | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | 301 / 302 | 319 / 321 |

¹⁵ **Higher run-to-run spread.** The 5 processes for this result differ by more than 5% (coefficient of variation). Small differences against it are not meaningful.  
¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  
¹⁸ **ActiveRecord has no row streaming.** ActiveRecord cannot stream a result set. The streamed variant uses its batch API (find_each / in_batches, 1,000 rows per keyset page), i.e. 1,000 queries instead of one.  

### T4 — client CPU, ns/cell (Percona / MariaDB)

| stack | config | int-text | mix-text | int-binary | mix-binary |
|---|---|---|---|---|---|
| py-sqlalchemy-core | default | 68.1 / 68.1 | 205 / 204 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-core | tuned | 67.7 / 68.1 | 205 / 204 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-orm | default | 273 / 276 | 449 / 447 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-orm | tuned | 242 / 238 | 367 / 361 | n/a / n/a | n/a / n/a |
| py-django-orm | default | 183 / 182 | 366 / 363 | n/a / n/a | n/a / n/a |
| py-django-orm | tuned | 68.5 / 69.4 | 199 / 203 | n/a / n/a | n/a / n/a |
| java-jdbctemplate | default | 105¹⁵ / 88.8 | 64.5¹⁶ / 64.2¹⁶ | n/a / n/a | n/a / n/a |
| java-jdbctemplate | tuned | 52 / 54.3 | 60.6 / 60.6 | n/a / n/a | n/a / n/a |
| java-jooq | default | 131 / 136 | 249 / 248 | n/a / n/a | n/a / n/a |
| java-jooq | tuned | 126 / 129 | 221 / 222 | n/a / n/a | n/a / n/a |
| java-hibernate | default | 69.1¹⁵ / 63 | 263 / 267 | n/a / n/a | n/a / n/a |
| java-hibernate | tuned | 56.7¹⁶ / 55.9 | 234 / 127¹⁶ | n/a / n/a | n/a / n/a |
| go-sqlx | default | 86.8 / 86.7 | 127 / 129 | n/a / n/a | n/a / n/a |
| go-sqlx | tuned | 87.2 / 87.3 | 131 / 130 | n/a / n/a | n/a / n/a |
| go-gorm | default | 151 / 150 | 222 / 224 | n/a / n/a | n/a / n/a |
| go-gorm | tuned | 136 / 135 | 207 / 206 | n/a / n/a | n/a / n/a |
| node-knex | default | 38.8 / 39.8 | 132 / 137 | n/a / n/a | n/a / n/a |
| node-drizzle | default | 91.4¹⁵ / 90.4 | 287 / 288 | n/a / n/a | n/a / n/a |
| node-drizzle | tuned | 91.2¹⁵ / 91.3¹⁵ | 288 / 288 | n/a / n/a | n/a / n/a |
| node-typeorm | default | 125¹⁶ / 125¹⁶ | 260 / 263 | n/a / n/a | n/a / n/a |
| node-typeorm | tuned | 159 / 159 | 304 / 286 | n/a / n/a | n/a / n/a |
| node-sequelize | default | 278 / 275 | 462¹⁵˒¹⁶ / 460¹⁵˒¹⁶ | n/a / n/a | n/a / n/a |
| node-sequelize | tuned | 93.7 / 94.7 | 303¹⁵ / 317¹⁵˒¹⁶ | n/a / n/a | n/a / n/a |
| node-prisma | default | 370¹⁶ / 373¹⁶ | 893¹⁶ / 854¹⁵˒¹⁶ | n/a / n/a | n/a / n/a |
| node-prisma | tuned | 391¹⁶ / 381¹⁶ | 900¹⁵˒¹⁶ / 865¹⁶ | n/a / n/a | n/a / n/a |
| dotnet-dapper | default | 111 / 111 | 217 / 216 | n/a / n/a | n/a / n/a |
| dotnet-dapper | tuned | 108 / 107 | 159 / 159 | n/a / n/a | n/a / n/a |
| dotnet-efcore | default | 196 / 196 | 316¹⁵ / 318¹⁵ | n/a / n/a | n/a / n/a |
| dotnet-efcore | tuned | 108 / 108 | 84.1¹⁶ / 85.1¹⁶ | n/a / n/a | n/a / n/a |
| php-dbal | default | 70.1 / 70 | 124 / 123 | n/a / n/a | n/a / n/a |
| php-dbal | tuned | 56.9 / 56.6 | 102 / 101 | n/a / n/a | n/a / n/a |
| php-doctrine-orm | default | 329 / 328 | 640 / 637 | n/a / n/a | n/a / n/a |
| php-doctrine-orm | tuned | 164 / 162 | 432 / 432 | n/a / n/a | n/a / n/a |
| php-eloquent | default | 709 / 708 | 802 / 798 | n/a / n/a | n/a / n/a |
| php-eloquent | tuned | 66.6 / 67 | 140 / 139 | n/a / n/a | n/a / n/a |
| rb-sequel | default | 167 / 167 | 317 / 324 | n/a / n/a | n/a / n/a |
| rb-sequel | tuned | 93.8 / 94 | 246 / 247 | n/a / n/a | n/a / n/a |
| rb-activerecord | default | 285 / 281 | 562¹⁶ / 564 | n/a / n/a | n/a / n/a |
| rb-activerecord | tuned | 81.4 / 81.8 | 313 / 296¹⁵ | n/a / n/a | n/a / n/a |
| rust-diesel | default | n/a / n/a | n/a / n/a | 22.9 / 22.8 | 53.7 / 53.7 |
| rust-diesel | tuned | n/a / n/a | n/a / n/a | 23 / 22.8 | 53.1 / 53.7 |
| rust-seaorm | default | n/a / n/a | n/a / n/a | 38.3 / 38.2 | 145 / 144 |
| rust-seaorm | tuned | n/a / n/a | n/a / n/a | 38.4 / 38.1 | 144 / 144 |

¹⁵ **Higher run-to-run spread.** The 5 processes for this result differ by more than 5% (coefficient of variation). Small differences against it are not meaningful.  
¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  

### T5 — client CPU, ns/KB (Percona / MariaDB)

| stack | config | 100k-doc | 100k-doc+tls | 100k-doc_bin | 10k-doc | 10k-doc_bin | 1k-doc | 1k-doc_bin | mix-doc | mix-doc_bin | 10k-doc-parse |
|---|---|---|---|---|---|---|---|---|---|---|---|
| py-sqlalchemy-core | default | 353⁵ / 359 | 481⁵ / 492 | 255 / 261 | 489⁵ / 485 | 379 / 373 | 876⁵ / 921 | 728 / 731 | 481⁵ / 378 | 267 / 269 | 3,918⁵ / 4,337 |
| py-sqlalchemy-core | tuned | 352⁵ / 358 | 481⁵ / 494 | 255 / 261 | 491⁵ / 486 | 377 / 375 | 934⁵ / 919 | 733 / 731 | 483⁵ / 379 | 269 / 268 | 3,952⁵ / 4,317 |
| py-sqlalchemy-orm | default | 591⁵ / 734 | 824⁵ / 983 | 668 / 666 | 882⁵ / 961 | 855 / 885 | 2,890⁵ / 3,141 | 3,058 / 2,996 | 848⁵ / 892 | 828 / 810 | 4,394⁵ / 4,894 |
| py-sqlalchemy-orm | tuned | 353⁵ / 358 | 481⁵ / 492 | 256 / 261 | 492⁵ / 493 | 378 / 383 | 945⁵ / 932 | 740 / 738 | 483⁵ / 381 | 269 / 267 | 3,925⁵ / 4,380 |
| py-django-orm | default | 374⁵ / 379 | 500⁵ / 513 | 276 / 279 | 613⁵ / 615 | 514 / 505 | 2,656⁵ / 2,908 | 2,730 / 2,736 | 610⁵ / 626 | 519 / 515 | 4,237⁵ / 4,529 |
| py-django-orm | tuned | 351⁵ / 359 | 481⁵ / 492 | 256 / 259 | 485⁵ / 478 | 370 / 366 | 762⁵ / 800 | 606 / 606 | 380⁵ / 367 | 256 / 252 | 4,033⁵ / 4,423 |
| java-jdbctemplate | default | 477⁵˒¹⁵˒¹⁶ / 496¹⁵˒¹⁶ | 647⁵˒¹⁵ / 526¹⁵ | 344¹⁵˒¹⁶ / 291¹⁵˒¹⁶ | 548⁵ / 472 | 460¹⁵ / 339¹⁵ | 764⁵˒¹⁵˒¹⁶ / 1,723¹⁵ | 1,463¹⁵˒¹⁶ / 696¹⁵˒¹⁶ | 411⁵ / 389¹⁵ | 385¹⁶ / 388¹⁵˒¹⁶ | n/a⁵ / n/a |
| java-jdbctemplate | tuned | 169⁵ / 172 | 387⁵ / 416 | 162 / 166 | 329⁵ / 316¹⁵ | 303¹⁵ / 295 | 632⁵˒¹⁵ / 506¹⁵˒¹⁶ | 781¹⁵˒¹⁶ / 534¹⁵˒¹⁶ | 290⁵˒¹⁵ / 253¹⁵ | 257¹⁵˒¹⁶ / 241¹⁵˒¹⁶ | n/a⁵ / n/a |
| java-jooq | default | 400⁵˒¹⁵˒¹⁶ / 292¹⁵ | 588⁵˒¹⁵ / 530¹⁵ | 338¹⁵˒¹⁶ / 370¹⁵˒¹⁶ | 390⁵˒¹⁵˒¹⁶ / 521¹⁵ | 498¹⁵˒¹⁶ / 405¹⁵˒¹⁶ | 1,065⁵˒¹⁵˒¹⁶ / 1,886¹⁵˒¹⁶ | 2,177¹⁵˒¹⁶ / 1,733¹⁵˒¹⁶ | 438⁵˒¹⁵˒¹⁶ / 463¹⁵˒¹⁶ | 423¹⁵˒¹⁶ / 462¹⁵˒¹⁶ | n/a⁵ / n/a |
| java-jooq | tuned | 321⁵˒¹⁵˒¹⁶ / 290 | 697⁵˒¹⁵ / 533¹⁵ | 288 / 385¹⁵˒¹⁶ | 551⁵˒¹⁵ / 523 | 526¹⁵ / 525 | 979⁵˒¹⁵˒¹⁶ / 1,046¹⁵˒¹⁶ | 2,082¹⁵ / 2,064¹⁵˒¹⁶ | 529⁵ / 434¹⁵˒¹⁶ | 304¹⁶ / 308¹⁵˒¹⁶ | n/a⁵ / n/a |
| java-hibernate | default | 361⁵˒¹⁵˒¹⁶ / 262¹⁵˒¹⁶ | 514⁵˒¹⁵ / 535¹⁵ | 394¹⁵˒¹⁶ / 440¹⁵˒¹⁶ | 487⁵˒¹⁵ / 501 | 480¹⁵ / 496 | 772⁵˒¹⁵˒¹⁶ / 755¹⁵˒¹⁶ | 730¹⁵˒¹⁶ / 896¹⁵˒¹⁶ | 450⁵ / 421 | 413 / 417¹⁵ | n/a⁵ / n/a |
| java-hibernate | tuned | 355⁵˒¹⁵˒¹⁶ / 409¹⁵ | 613⁵˒¹⁵˒¹⁶ / 607¹⁵ | 428¹⁵˒¹⁶ / 484¹⁵˒¹⁶ | 515⁵˒¹⁵ / 492¹⁵ | 481¹⁵ / 491 | 1,020⁵˒¹⁵˒¹⁶ / 1,944¹⁵ | 1,783¹⁵˒¹⁶ / 1,922 | 452⁵ / 433¹⁵ | 453¹⁵ / 411¹⁵ | n/a⁵ / n/a |
| go-sqlx | default | 244⁵ / 189 | 426⁵ / 375 | 196 / 192 | 482⁵ / 301 | 306 / 306 | 698⁵ / 689 | 694 / 699 | 368⁵ / 238 | 241 / 237 | 14,638⁵ / 16,088 |
| go-sqlx | tuned | 251⁵ / 189 | 436⁵ / 371 | 196 / 194 | 478⁵ / 301 | 307 / 302 | 696⁵ / 692 | 694 / 701 | 367⁵ / 235 | 228 / 236 | 14,684⁵ / 16,084 |
| go-gorm | default | 248⁵ / 189 | 424⁵ / 371 | 199 / 194 | 486⁵ / 308 | 314 / 309 | 715⁵ / 713 | 715 / 725 | 370⁵ / 228 | 231 / 231 | 14,564⁵ / 16,077 |
| go-gorm | tuned | 245⁵ / 193 | 429⁵ / 367 | 196 / 194 | 495⁵ / 308 | 309 / 307 | 723⁵ / 708 | 716 / 720 | 383⁵ / 246 | 245 / 242 | 14,672⁵ / 16,078 |
| node-knex | default | 454⁵ / 460 | 614⁵ / 614 | 472 / 464 | 544⁵ / 439¹⁶ | 615 / 600 | 582⁵ / 562¹⁵ | 451¹⁶ / 446¹⁶ | 409⁵˒¹⁶ / 380¹⁵ | 588¹⁶ / 584¹⁵ | 2,320⁵ / 2,363 |
| node-drizzle | default | 460⁵ / 466 | 617⁵ / 617 | 498 / 498 | 587⁵˒¹⁵˒¹⁶ / 432 | 666 / 650 | 717⁵˒¹⁵ / 658¹⁵ | 487¹⁵ / 484 | 397⁵˒¹⁵˒¹⁶ / 371 | 623 / 636 | 2,396⁵ / 2,406 |
| node-drizzle | tuned | 457⁵ / 463 | 623⁵ / 618 | 486 / 483 | 577⁵˒¹⁵ / 435 | 682 / 660 | 656⁵˒¹⁵ / 646¹⁵ | 588¹⁵ / 587¹⁵ | 409⁵˒¹⁵˒¹⁶ / 383 | 637¹⁵ / 640¹⁵ | 2,330⁵ / 2,432 |
| node-typeorm | default | 460⁵ / 459 | 619⁵ / 618 | 513 / 520 | 517⁵˒¹⁵ / 448 | 629 / 622 | 618⁵˒¹⁵ / 566¹⁵˒¹⁶ | 442¹⁵ / 455¹⁵ | 412⁵ / 390 | 623¹⁶ / 618¹⁵ | 2,349⁵ / 2,351 |
| node-typeorm | tuned | 463⁵ / 460 | 624⁵ / 616 | 514 / 529 | 484⁵˒¹⁶ / 448 | 647 / 644 | 615⁵ / 564 | 487¹⁵ / 437¹⁶ | 411⁵ / 390¹⁵ | 607¹⁵ / 620¹⁶ | 2,349⁵ / 2,361 |
| node-sequelize | default | 493⁵ / 492 | 642⁵ / 646 | 563 / 569 | 669⁵˒¹⁵ / 573¹⁵ | 889 / 883 | 1,820⁵ / 1,949 | 1,807¹⁵ / 2,069 | 562⁵˒¹⁵˒¹⁶ / 531 | 884¹⁵ / 827¹⁶ | 2,509⁵ / 2,494 |
| node-sequelize | tuned | 470⁵ / 478 | 635⁵ / 633 | 543 / 549 | 520⁵˒¹⁵˒¹⁶ / 456 | 707 / 682 | 740⁵ / 753¹⁵ | 541¹⁵ / 520¹⁵ | 428⁵ / 392 | 730¹⁶ / 671¹⁶ | 2,407⁵ / 2,375 |
| node-prisma | default | 464⁵ / 474 | 631⁵ / 627 | 1,358 / 1,347 | 806⁵ / 761 | 1,472 / 1,495 | 1,353⁵˒¹⁵˒¹⁶ / 1,444¹⁶ | 3,038¹⁵˒¹⁶ / 2,448¹⁵˒¹⁶ | 752⁵ / 769 | 1,581 / 1,582 | 2,714⁵ / 2,671 |
| node-prisma | tuned | 472⁵ / 472 | 629⁵ / 622 | 1,391 / 1,350 | 805⁵ / 765 | 1,479 / 1,489 | 1,313⁵˒¹⁶ / 1,416¹⁶ | 2,889¹⁵˒¹⁶ / 2,876¹⁵˒¹⁶ | 747⁵ / 754 | 1,577 / 1,585 | 2,718⁵ / 2,666 |
| dotnet-dapper | default | 246⁵˒¹⁶ / 299¹⁵ | 412⁵ / 423¹⁵ | 213 / 220¹⁵ | 848⁵ / 789 | 435 / 433 | 1,248⁵ / 1,235 | 1,107 / 1,110 | 602⁵ / 582 | 398 / 386 | n/a⁵ / n/a |
| dotnet-dapper | tuned | 247⁵ / 292¹⁵ | 401⁵ / 418¹⁵ | 215¹⁵ / 187¹⁵ | 848⁵ / 795 | 432 / 434 | 1,244⁵ / 1,237 | 1,114 / 1,105 | 608⁵ / 577 | 383 / 383 | n/a⁵ / n/a |
| dotnet-efcore | default | 255⁵ / 325¹⁵ | 410⁵ / 579 | 193¹⁵ / 217¹⁵ | 954⁵ / 878 | 513 / 496 | 1,502⁵ / 1,514 | 1,373 / 1,384 | 709⁵ / 678 | 489 / 487 | n/a⁵ / n/a |
| dotnet-efcore | tuned | 261⁵ / 350 | 422⁵ / 581 | 227¹⁵ / 234¹⁵ | 963⁵ / 876 | 514 / 514 | 1,501⁵ / 1,494 | 1,370 / 1,383 | 755⁵ / 679 | 491 / 484 | n/a⁵ / n/a |
| php-dbal | default | 730⁵ / 719 | 894⁵ / 870 | 771 / 725 | 778⁵ / 763 | 791 / 781 | 578⁵ / 599 | 597 / 607 | 486⁵ / 388 | 388 / 390 | n/a⁵ / n/a |
| php-dbal | tuned | 730⁵ / 728 | 895⁵ / 865 | 770 / 728 | 774⁵ / 777 | 789 / 772 | 579⁵ / 598 | 599 / 601 | 487⁵ / 387 | 389 / 386 | n/a⁵ / n/a |
| php-doctrine-orm | default | 744⁵ / 731 | 901⁵ / 871 | 770 / 729 | 770⁵ / 752 | 792 / 768 | 608⁵ / 628 | 632 / 629 | 486⁵ / 394 | 405 / 408 | n/a⁵ / n/a |
| php-doctrine-orm | tuned | 745⁵ / 733 | 898⁵ / 863 | 775 / 724 | 783⁵ / 760 | 771 / 753 | 605⁵ / 629 | 629 / 628 | 476⁵ / 393 | 402 / 396 | n/a⁵ / n/a |
| php-eloquent | default | 700⁵ / 713 | 851⁵ / 856 | 754 / 712 | 658⁵ / 669 | 670 / 663 | 665⁵ / 703 | 701 / 702 | 516⁵ / 407 | 411 / 408 | n/a⁵ / n/a |
| php-eloquent | tuned | 693⁵ / 713 | 846⁵ / 858 | 756 / 713 | 661⁵ / 666 | 669 / 667 | 666⁵ / 697 | 704 / 702 | 521⁵ / 404 | 408 / 408 | n/a⁵ / n/a |
| rb-sequel | default | 742⁵ / 797 | 1,127⁵ / 1,126 | 788 / 765 | 874⁵ / 903 | 925 / 923 | 1,480⁵ / 1,541 | 1,609 / 1,530 | 860⁵ / 871 | 897 / 874 | 2,802⁵ / 3,030 |
| rb-sequel | tuned | 549⁵ / 580 | 717⁵ / 740 | 575 / 574 | 608⁵ / 606 | 608 / 610 | 967⁵ / 986 | 966 / 973 | 588⁵ / 594 | 585 / 593 | 2,479⁵ / 2,563 |
| rb-activerecord | default | 866⁵˒¹⁵ / 847 | 1,256⁵˒¹⁵ / 1,227 | 830¹⁵ / 871 | 913⁵ / 941 | 945 / 921 | 1,874⁵ / 2,007 | 1,930 / 1,824 | 850⁵ / 892 | 879 / 875 | 3,457⁵ / 3,741 |
| rb-activerecord | tuned | 594⁵ / 606 | 765⁵ / 777 | 590 / 601 | 587⁵ / 585 | 574 / 573 | 969⁵ / 1,011 | 935 / 936 | 587⁵ / 584 | 574 / 572 | 2,665⁵ / 2,866 |
| rust-diesel | default | 660⁵ / 714 | 1,080⁵ / 1,105 | 743 / 713 | 468⁵ / 497 | 512 / 493 | 585⁵ / 609 | 646 / 614 | 395⁵ / 402 | 432 / 402 | 4,724⁵ / 5,149 |
| rust-diesel | tuned | 383⁵ / 418 | 524⁵ / 555 | 373 / 400 | 208⁵ / 199 | 178 / 179 | 293⁵ / 299 | 269 / 268 | 189⁵ / 181 | 155 / 161 | 4,413⁵ / 4,791 |
| rust-seaorm | default | n/a⁵˒¹⁷ / 269¹⁵˒¹⁷ | n/a⁵˒¹⁷ / 584¹⁷ | 256¹⁷ / 255¹⁷ | n/a⁵˒¹⁷ / 289¹⁷ | 267¹⁷ / 267¹⁷ | n/a⁵˒¹⁷ / 740¹⁷ | 693¹⁷ / 698¹⁷ | n/a⁵˒¹⁷ / 231¹⁷ | 207¹⁷ / 206¹⁷ | n/a⁵˒¹⁷ / 5,113¹⁷ |
| rust-seaorm | tuned | n/a⁵˒¹⁷ / 286¹⁷ | n/a⁵˒¹⁷ / 594¹⁵˒¹⁷ | 275¹⁵˒¹⁷ / 281¹⁷ | n/a⁵˒¹⁷ / 275¹⁷ | 255¹⁷ / 254¹⁷ | n/a⁵˒¹⁷ / 613¹⁷ | 614¹⁷ / 619¹⁷ | n/a⁵˒¹⁷ / 208¹⁷ | 190¹⁷ / 189¹⁷ | n/a⁵˒¹⁷ / 4,994¹⁷ |

⁵ **Percona converts JSON on every read.** Percona Server (like MySQL) stores JSON in a binary format and converts it to text on every read: about 13× the server CPU of the same bytes as LONGBLOB, and ~10% larger output. The slower send makes most clients spend more CPU per KB than reading the same documents from MariaDB, which stores JSON as text.  
¹⁵ **Higher run-to-run spread.** The 5 processes for this result differ by more than 5% (coefficient of variation). Small differences against it are not meaningful.  
¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  
¹⁷ **SeaORM and MySQL JSON columns.** SeaORM 2.0.4 cannot read a MySQL JSON column into a String (sqlx reports mismatched types); it only maps JSON to Json, which parses every value. The text-read doc cells are therefore n/a on Percona; on MariaDB JSON is LONGTEXT and works. t_blob is mapped as two entities (doc / doc_bin) so the default model can be loaded at all.  

### T6 — client CPU, µs/1000-row stmt (Percona / MariaDB)

| stack | config | batch | multiparam | sqltext |
|---|---|---|---|---|
| py-sqlalchemy-core | default | 3,225 / 3,253 | 23,770 / 23,639 | n/a / n/a |
| py-sqlalchemy-core | tuned | 3,264 / 3,250 | 23,871 / 23,791 | n/a / n/a |
| py-sqlalchemy-orm | default | 15,389 / 15,473 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-orm | tuned | 4,400 / 4,425 | n/a / n/a | n/a / n/a |
| py-django-orm | default | 8,014 / 7,929 | n/a / n/a | n/a / n/a |
| py-django-orm | tuned | 8,028 / 7,953 | n/a / n/a | n/a / n/a |
| java-jdbctemplate | default | 5,661 / 5,563 | 779 / 814 | n/a / n/a |
| java-jdbctemplate | tuned | 1,488 / 1,451 | 1,295 / 1,201 | n/a / n/a |
| java-jooq | default | 6,097 / 5,986 | 1,358¹⁵ / 1,342 | n/a / n/a |
| java-jooq | tuned | 1,793 / 1,819 | 1,913 / 1,855 | n/a / n/a |
| java-hibernate | default | 8,118 / 7,983 | n/a / n/a | n/a / n/a |
| java-hibernate | tuned | 1,762¹⁵ / 1,751¹⁵ | n/a / n/a | n/a / n/a |
| go-sqlx | default | 466 / 466 | n/a / n/a | n/a / n/a |
| go-sqlx | tuned | 379 / 377 | n/a / n/a | n/a / n/a |
| go-gorm | default | 619 / 618 | n/a / n/a | n/a / n/a |
| go-gorm | tuned | 454 / 452 | n/a / n/a | n/a / n/a |
| node-knex | default | 379 / 365 | n/a / n/a | n/a / n/a |
| node-drizzle | default | 6,648 / 6,646 | n/a / n/a | n/a / n/a |
| node-drizzle | tuned | 6,665 / 6,695 | n/a / n/a | n/a / n/a |
| node-typeorm | default | 8,163 / 8,092 | n/a / n/a | n/a / n/a |
| node-typeorm | tuned | 3,826 / 3,865 | n/a / n/a | n/a / n/a |
| node-sequelize | default | 2,833 / 2,824 | n/a / n/a | n/a / n/a |
| node-sequelize | tuned | 728 / 727 | n/a / n/a | n/a / n/a |
| node-prisma | default | 33,744 / 33,580 | n/a / n/a | n/a / n/a |
| node-prisma | tuned | 33,261 / 33,511 | n/a / n/a | n/a / n/a |
| dotnet-dapper | default | 5,613 / 5,578 | n/a / n/a | n/a / n/a |
| dotnet-dapper | tuned | 5,595 / 5,562 | n/a / n/a | n/a / n/a |
| dotnet-efcore | default | 3,252 / 3,220 | n/a / n/a | n/a / n/a |
| dotnet-efcore | tuned | 4,121 / 4,134 | n/a / n/a | n/a / n/a |
| php-dbal | default | 6,241 / 6,193 | 812 / 803 | n/a / n/a |
| php-dbal | tuned | 6,225 / 6,188 | 820 / 808 | n/a / n/a |
| php-doctrine-orm | default | 11,009¹⁹ / 10,975¹⁹ | n/a¹⁹ / n/a¹⁹ | n/a¹⁹ / n/a¹⁹ |
| php-doctrine-orm | tuned | 11,007 / 10,959 | n/a / n/a | n/a / n/a |
| php-eloquent | default | 1,600 / 1,581 | n/a / n/a | n/a / n/a |
| php-eloquent | tuned | 1,599 / 1,578 | n/a / n/a | n/a / n/a |
| rb-sequel | default | 27,909¹⁹ / 19,088¹⁹ | n/a¹⁹ / n/a¹⁹ | n/a¹⁹ / n/a¹⁹ |
| rb-sequel | tuned | 1,660 / 1,651 | n/a / n/a | n/a / n/a |
| rb-activerecord | default | 26,285¹⁹ / 29,890¹⁹ | n/a¹⁹ / n/a¹⁹ | n/a¹⁹ / n/a¹⁹ |
| rb-activerecord | tuned | 5,408 / 5,633 | n/a / n/a | n/a / n/a |
| rust-diesel | default | 1,137 / 1,113 | n/a / n/a | n/a / n/a |
| rust-diesel | tuned | 1,138 / 1,104 | n/a / n/a | n/a / n/a |
| rust-seaorm | default | 316 / 326 | n/a / n/a | n/a / n/a |
| rust-seaorm | tuned | 318 / 326 | n/a / n/a | n/a / n/a |

¹⁵ **Higher run-to-run spread.** The 5 processes for this result differ by more than 5% (coefficient of variation). Small differences against it are not meaningful.  
¹⁹ **Per-row ORM inserts.** Default config inserts model objects one INSERT per row (1,000,000 statements, one transaction per 1,000 rows), the ORM's usual idiom; the tuned config uses the framework's bulk insert (one multi-row INSERT per 1,000 rows). Sequel Model.create also re-reads each row after INSERT.  

### T3 — memory for the work, MB (Percona / MariaDB)

| stack | config | text-buffered | text-buffered+tls | text-streamed | text-streamed+tls | binary-buffered | binary-streamed |
|---|---|---|---|---|---|---|---|
| py-sqlalchemy-core | default | 193 / 193 | 193 / 193 | 0 / 0 | 0 / 0 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-core | tuned | 193 / 193 | 193 / 193 | 0 / 0 | 0 / 0 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-orm | default | 1,187 / 1,187 | 1,187 / 1,187 | 0 / 0 | 0 / 0 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-orm | tuned | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | n/a / n/a | n/a / n/a |
| py-django-orm | default | 299 / 299 | 299 / 299 | 192 / 192 | 192 / 192 | n/a / n/a | n/a / n/a |
| py-django-orm | tuned | 178 / 178 | 178 / 178 | 192 / 192 | 192 / 192 | n/a / n/a | n/a / n/a |
| java-jdbctemplate | default | 120 / 108 | 67.9 / 91.2 | 0 / 0.121 | 0 / 0 | n/a / n/a | n/a / n/a |
| java-jdbctemplate | tuned | 0.0977 / 0.0586 | 0 / 0 | 0 / 0.102 | 0 / 0 | n/a / n/a | n/a / n/a |
| java-jooq | default | 0¹⁶ / 0¹⁶ | 0¹⁶ / 0 | 0 / 0 | 0 / 0 | n/a / n/a | n/a / n/a |
| java-jooq | tuned | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | n/a / n/a | n/a / n/a |
| java-hibernate | default | 324 / 185 | 233 / 337¹⁶ | 129¹⁶ / 83.4 | 5.18¹⁶ / 235¹⁶ | n/a / n/a | n/a / n/a |
| java-hibernate | tuned | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | n/a / n/a | n/a / n/a |
| go-sqlx | default | 10.2 / 11.6 | 11.8 / 7.05 | 0 / 0.0859 | 0 / 0 | n/a / n/a | n/a / n/a |
| go-sqlx | tuned | 11.1 / 4.29 | 9.45 / 14.3 | 0 / 0.312 | 0 / 0.285 | n/a / n/a | n/a / n/a |
| go-gorm | default | 16.1 / 12.9 | 7.74 / 8.65 | 0.0664 / 0 | 0 / 0 | n/a / n/a | n/a / n/a |
| go-gorm | tuned | 7.18 / 7.23 | 10.7 / 7.33 | 0 / 0.43 | 0 / 0 | n/a / n/a | n/a / n/a |
| node-knex | default | 17.4 / 23¹⁶ | 25.9 / 16.6¹⁶ | 0.0625 / 0.0508 | 0.145 / 0.148 | n/a / n/a | n/a / n/a |
| node-drizzle | default | 35.1 / 34.3 | 35.4¹⁶ / 35.9 | 0.164 / 0.316 | 43 / 26.5 | n/a / n/a | n/a / n/a |
| node-drizzle | tuned | 32.3¹⁶ / 35.2 | 36.8 / 33.9¹⁶ | 15.6 / 0.082 | 0.203 / 0¹⁶ | n/a / n/a | n/a / n/a |
| node-typeorm | default | 34.7 / 89.1 | 110 / 36.6 | 0.133 / 0.117 | 0.0898 / 0.117 | n/a / n/a | n/a / n/a |
| node-typeorm | tuned | 27.5 / 28.3 | 27.2 / 6.95¹⁶ | 0.129 / 0.188 | 0.0938 / 0.121 | n/a / n/a | n/a / n/a |
| node-sequelize | default | 39.9 / 41 | 40.3 / 38.4 | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a |
| node-sequelize | tuned | 38.4¹⁶ / 38.6 | 10.9 / 35.7¹⁶ | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a |
| node-prisma | default | 59.9¹⁶ / 67.4¹⁶ | 0 / 44.5 | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a |
| node-prisma | tuned | 44.4¹⁶ / 67.1 | 59.9 / 44.7 | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a |
| dotnet-dapper | default | 0.137 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | n/a / n/a | n/a / n/a |
| dotnet-dapper | tuned | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | n/a / n/a | n/a / n/a |
| dotnet-efcore | default | 34.5 / 122 | 27.2 / 27.2 | 31.6 / 31.6 | 40 / 35.2 | n/a / n/a | n/a / n/a |
| dotnet-efcore | tuned | 10.5 / 6.41 | 10.9 / 9.82 | 0 / 0 | 0 / 0 | n/a / n/a | n/a / n/a |
| php-dbal | default | 31.3 / 31.2 | 31.2 / 31.3 | 0 / 0 | 0 / 0 | n/a / n/a | n/a / n/a |
| php-dbal | tuned | 38.5 / 38.5 | 38.5 / 38.5 | 0 / 0 | 0 / 0 | n/a / n/a | n/a / n/a |
| php-doctrine-orm | default | 200 / 200 | 200 / 200 | 154 / 154 | 154 / 154 | n/a / n/a | n/a / n/a |
| php-doctrine-orm | tuned | 36.4 / 36.4 | 36.4 / 36.5 | 36.4 / 36.4 | 36.4 / 36.5 | n/a / n/a | n/a / n/a |
| php-eloquent | default | 47.1 / 47 | 47 / 47.1 | 40.7 / 40.6 | 40.6 / 40.7 | n/a / n/a | n/a / n/a |
| php-eloquent | tuned | 35.2 / 35.2 | 35.2 / 35.2 | 40.7 / 40.6 | 40.6 / 40.7 | n/a / n/a | n/a / n/a |
| rb-sequel | default | 60.8 / 60.8 | 60.8 / 60.8 | 0 / 0 | 0 / 0 | n/a / n/a | n/a / n/a |
| rb-sequel | tuned | 18 / 17.7 | 17.7 / 17.7 | 0 / 0 | 0 / 0 | n/a / n/a | n/a / n/a |
| rb-activerecord | default | 40.2 / 40.2 | 40.1 / 40.1 | 0¹⁸ / 0¹⁸ | 0¹⁸ / 0¹⁸ | n/a / n/a | n/a¹⁸ / n/a¹⁸ |
| rb-activerecord | tuned | 13.6 / 13.6 | 13.6 / 13.6 | 0.0703¹⁸ / 0.0664¹⁸ | 0.0625¹⁸ / 0.0664¹⁸ | n/a / n/a | n/a¹⁸ / n/a¹⁸ |
| rust-diesel | default | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | 0 / 0 | 0 / 0 |
| rust-diesel | tuned | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | 12.9 / 12.9 | 12.9 / 12.9 |
| rust-seaorm | default | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | 76.2 / 76.2 | 0 / 0 |
| rust-seaorm | tuned | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | 76.2 / 76.2 | 0 / 0 |

¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  
¹⁸ **ActiveRecord has no row streaming.** ActiveRecord cannot stream a result set. The streamed variant uses its batch API (find_each / in_batches, 1,000 rows per keyset page), i.e. 1,000 queries instead of one.  

### T4 — memory for the work, MB (Percona / MariaDB)

| stack | config | int-text | mix-text | int-binary | mix-binary |
|---|---|---|---|---|---|
| py-sqlalchemy-core | default | 27 / 27.2 | 46.3 / 44.9 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-core | tuned | 27 / 27.2 | 44.9 / 44.9 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-orm | default | 45.7 / 45.7 | 49.9 / 48.9 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-orm | tuned | 0 / 0 | 2.17 / 2.17 | n/a / n/a | n/a / n/a |
| py-django-orm | default | 43.9 / 42.9 | 47.9 / 47.9 | n/a / n/a | n/a / n/a |
| py-django-orm | tuned | 37.9 / 39.9 | 70.1 / 72 | n/a / n/a | n/a / n/a |
| java-jdbctemplate | default | 47.2 / 47.4 | 128 / 0 | n/a / n/a | n/a / n/a |
| java-jdbctemplate | tuned | 0 / 0 | 0 / 0 | n/a / n/a | n/a / n/a |
| java-jooq | default | 52.4 / 52.4 | 79.1 / 79.2 | n/a / n/a | n/a / n/a |
| java-jooq | tuned | 52.4 / 52.3 | 81.8 / 80.6 | n/a / n/a | n/a / n/a |
| java-hibernate | default | 48.5 / 0 | 82.4 / 82.1 | n/a / n/a | n/a / n/a |
| java-hibernate | tuned | 0 / 0 | 86.2 / 0¹⁶ | n/a / n/a | n/a / n/a |
| go-sqlx | default | 0.0977 / 2.51 | 1.84 / 0.617 | n/a / n/a | n/a / n/a |
| go-sqlx | tuned | 0.18 / 3.19 | 13.2 / 4.7 | n/a / n/a | n/a / n/a |
| go-gorm | default | 5.15 / 0.723 | 3.74 / 3.25 | n/a / n/a | n/a / n/a |
| go-gorm | tuned | 1.38 / 0.152 | 1.46 / 2.59 | n/a / n/a | n/a / n/a |
| node-knex | default | 8.92 / 9.16 | 1.38 / 0.148 | n/a / n/a | n/a / n/a |
| node-drizzle | default | 16.2 / 2.5 | 0.0586 / 0.754 | n/a / n/a | n/a / n/a |
| node-drizzle | tuned | 17.2 / 16.1 | 0.254 / 0 | n/a / n/a | n/a / n/a |
| node-typeorm | default | 0.441¹⁶ / 0.816 | 0.492 / 0.492 | n/a / n/a | n/a / n/a |
| node-typeorm | tuned | 17 / 17.2 | 0 / 0 | n/a / n/a | n/a / n/a |
| node-sequelize | default | 0 / 0 | 0 / 0.0547 | n/a / n/a | n/a / n/a |
| node-sequelize | tuned | 0 / 16.9 | 0 / 0 | n/a / n/a | n/a / n/a |
| node-prisma | default | 0¹⁶ / 0.0742 | 0¹⁶ / 0.0586¹⁶ | n/a / n/a | n/a / n/a |
| node-prisma | tuned | 0¹⁶ / 0¹⁶ | 0 / 0¹⁶ | n/a / n/a | n/a / n/a |
| dotnet-dapper | default | 0.727 / 0.723 | 8.55 / 13.8 | n/a / n/a | n/a / n/a |
| dotnet-dapper | tuned | 0 / 0 | 0 / 0 | n/a / n/a | n/a / n/a |
| dotnet-efcore | default | 1.92 / 1.92 | 22.5 / 17.8 | n/a / n/a | n/a / n/a |
| dotnet-efcore | tuned | 0 / 0 | 9.25¹⁶ / 17.2 | n/a / n/a | n/a / n/a |
| php-dbal | default | 30.2 / 30.2 | 44.2 / 44.2 | n/a / n/a | n/a / n/a |
| php-dbal | tuned | 6 / 5.94 | 18 / 17.9 | n/a / n/a | n/a / n/a |
| php-doctrine-orm | default | 5.36 / 5.8 | 18.3 / 16.3 | n/a / n/a | n/a / n/a |
| php-doctrine-orm | tuned | 6.99 / 6.93 | 17.6 / 17.9 | n/a / n/a | n/a / n/a |
| php-eloquent | default | 4.24 / 4.18 | 15.9 / 15.9 | n/a / n/a | n/a / n/a |
| php-eloquent | tuned | 3.38 / 3.31 | 14.9 / 15 | n/a / n/a | n/a / n/a |
| rb-sequel | default | 0 / 0 | 13.5 / 22.4 | n/a / n/a | n/a / n/a |
| rb-sequel | tuned | 0.34 / 0.184 | 2.38 / 2.19 | n/a / n/a | n/a / n/a |
| rb-activerecord | default | 0.0625 / 0.0625 | 1.44 / 0.625 | n/a / n/a | n/a / n/a |
| rb-activerecord | tuned | 0 / 0 | 0 / 0 | n/a / n/a | n/a / n/a |
| rust-diesel | default | n/a / n/a | n/a / n/a | 0.422 / 0.418 | 0 / 0 |
| rust-diesel | tuned | n/a / n/a | n/a / n/a | 0.422 / 0.418 | 0 / 0 |
| rust-seaorm | default | n/a / n/a | n/a / n/a | 1.39 / 0 | 0 / 0 |
| rust-seaorm | tuned | n/a / n/a | n/a / n/a | 0.191 / 0 | 0 / 0 |

¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  

### T5 — memory for the work, MB (Percona / MariaDB)

| stack | config | 100k-doc | 100k-doc+tls | 100k-doc_bin | 10k-doc | 10k-doc_bin | 1k-doc | 1k-doc_bin | mix-doc | mix-doc_bin | 10k-doc-parse |
|---|---|---|---|---|---|---|---|---|---|---|---|
| py-sqlalchemy-core | default | 332⁵ / 312 | 332⁵ / 311 | 312 / 312 | 32.3⁵ / 29.4 | 29.3 / 29.3 | 1.86⁵ / 0 | 0 / 0 | 24.6⁵ / 0 | 0 / 0 | 32.3⁵ / 29.3 |
| py-sqlalchemy-core | tuned | 332⁵ / 312 | 332⁵ / 311 | 312 / 312 | 32.3⁵ / 29.3 | 29.3 / 29.3 | 2.98⁵ / 0 | 0 / 0 | 26.2⁵ / 0 | 0 / 0 | 32.3⁵ / 29.3 |
| py-sqlalchemy-orm | default | 577⁵ / 504 | 577⁵ / 504 | 523 / 502 | 54.4⁵ / 50.6 | 0 / 50.7 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0.0547 | 0.0781 / 0 | 54.4⁵ / 50.7 |
| py-sqlalchemy-orm | tuned | 332⁵ / 312 | 332⁵ / 312 | 312 / 312 | 32.3⁵ / 29.4 | 29.3 / 29.3 | 2.98⁵ / 0 | 0 / 0 | 26.2⁵ / 0 | 0 / 0 | 32.3⁵ / 29.3 |
| py-django-orm | default | 332⁵ / 312 | 309⁵ / 312 | 312 / 312 | 35.1⁵ / 29.7 | 29.7 / 29.7 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0 | 0 / 0 | 35.1⁵ / 29.7 |
| py-django-orm | tuned | 332⁵ / 311 | 332⁵ / 311 | 311 / 311 | 32.2⁵ / 29.3 | 29.2 / 29.2 | 1.38⁵ / 0 | 0 / 0 | 0⁵ / 0 | 0 / 0 | 32.2⁵ / 29.3 |
| java-jdbctemplate | default | 299⁵˒¹⁶ / 589¹⁶ | 908⁵ / 0.105 | 582¹⁶ / 73.9 | 95.6⁵ / 79.6 | 73.4 / 78.4 | 0.082⁵ / 0.602 | 0 / 0.164¹⁶ | 58.6⁵ / 1.89¹⁶ | 39.2 / 48.6 | n/a⁵ / n/a |
| java-jdbctemplate | tuned | 0.129⁵ / 0.105 | 0.121⁵ / 0.0742 | 0 / 0.0742 | 6.97⁵ / 10.1 | 10.4 / 8.04 | 0⁵ / 0.25 | 0¹⁶ / 0¹⁶ | 4.21⁵ / 3.05 | 3.6 / 5.08 | n/a⁵ / n/a |
| java-jooq | default | 136⁵ / 104 | 667⁵ / 0.102 | 205 / 161 | 90.1⁵ / 78 | 69.2 / 76.2 | 0.242⁵ / 0¹⁶ | 0.156 / 0.246 | 5.76⁵ / 44.3 | 40.8 / 39.6 | n/a⁵ / n/a |
| java-jooq | tuned | 380⁵ / 227 | 411⁵ / 0.141 | 0.27 / 58.5 | 89.7⁵ / 75.1 | 76.2 / 76.4 | 0.113⁵ / 0.195 | 0.0742 / 0.0625 | 54.5⁵ / 47.3 | 40.3 / 33.8 | n/a⁵ / n/a |
| java-hibernate | default | 261⁵ / 0.129 | 144⁵ / 0.0781 | 404 / 319¹⁶ | 0⁵ / 70.6 | 70.7 / 65.1 | 0.188⁵ / 0.0664 | 0.0625 / 0¹⁶ | 52⁵ / 49.1 | 40.9 / 44.2 | n/a⁵ / n/a |
| java-hibernate | tuned | 138⁵ / 555 | 415⁵ / 542 | 589¹⁶ / 518¹⁶ | 102⁵ / 83 | 72 / 73.8 | 0.129⁵ / 0.0742 | 0.0586 / 0.082 | 51.9⁵ / 11.6 | 44.2 / 0¹⁶ | n/a⁵ / n/a |
| go-sqlx | default | 47.1⁵ / 33.8 | 62.8⁵ / 10.9 | 27.3 / 2.61 | 12.1⁵ / 6.62 | 4.11 / 5.48 | 0⁵ / 0 | 0 / 0 | 0.0781⁵ / 0.191 | 0.0547 / 0.188 | 1.9⁵ / 4.54 |
| go-sqlx | tuned | 46.5⁵ / 57.3 | 11.7⁵ / 44.1 | 25.8 / 73.6 | 5.96⁵ / 10.1 | 3.39 / 3.57 | 0⁵ / 0 | 0 / 0 | 1.88⁵ / 4.08 | 1.86 / 0.996 | 2.89⁵ / 4.75 |
| go-gorm | default | 55.3⁵ / 82.7 | 91.8⁵ / 25.2 | 39.5 / 19.5 | 2.15⁵ / 4.67 | 4.29 / 0.559 | 0⁵ / 0 | 0 / 0 | 1.98⁵ / 0.0742 | 0 / 0.176 | 3.61⁵ / 4.27 |
| go-gorm | tuned | 13.5⁵ / 0.398 | 31.6⁵ / 0.641 | 58.6 / 56.9 | 1.2⁵ / 0 | 4.19 / 1.8 | 0⁵ / 0 | 0 / 0 | 5.25⁵ / 4.91 | 3.8 / 0.121 | 2.88⁵ / 4.52 |
| node-knex | default | 3⁵ / 2.44 | 2.37⁵ / 4.11 | 14.9 / 0 | 0⁵ / 0.578¹⁶ | 4.63 / 7.75 | 0.0625⁵ / 0 | 0 / 0 | 0.207⁵˒¹⁶ / 1.72 | 5.34 / 0.27 | 0⁵ / 1.91 |
| node-drizzle | default | 3.86⁵ / 17.3 | 2.77⁵ / 3.34 | 23.3 / 2.96 | 2.03⁵ / 9.88 | 0.953 / 2.22 | 1⁵ / 0 | 0 / 0 | 0.527⁵˒¹⁶ / 3.57 | 11 / 15.4 | 0.422⁵ / 1.57 |
| node-drizzle | tuned | 2.46⁵ / 6.03 | 46⁵ / 9.43 | 23.5 / 47.6 | 3.67⁵ / 9.87 | 1.98 / 5.7 | 1.02⁵ / 0 | 0 / 0 | 0.0664⁵˒¹⁶ / 2.94 | 10.2 / 13.2 | 0.0625⁵ / 0 |
| node-typeorm | default | 3.26⁵ / 7.19 | 7.23⁵ / 4.9 | 0 / 9.81 | 0⁵ / 10.2 | 0 / 0 | 0⁵ / 0 | 0 / 0.324 | 0.121⁵ / 3.81 | 1.62¹⁶ / 5 | 0.0547⁵ / 6.36 |
| node-typeorm | tuned | 3.38⁵ / 12.4 | 4.27⁵ / 4.75 | 0 / 6.89 | 0⁵˒¹⁶ / 10.9 | 0 / 6.81 | 0⁵ / 0 | 0 / 0.418 | 4.57⁵ / 0.184 | 0.621 / 2.38 | 0.0742⁵ / 5.68 |
| node-sequelize | default | 4.89⁵ / 7.84 | 8.98⁵ / 8.09 | 0 / 21.7 | 0⁵ / 0 | 0 / 0 | 1.27⁵ / 1.14 | 2.67 / 2.67 | 1.02⁵ / 2.68 | 3.79 / 0¹⁶ | 0.0664⁵ / 0 |
| node-sequelize | tuned | 2.68⁵ / 5.02 | 3.75⁵ / 3.29 | 11.8 / 28.6 | 10.9⁵ / 2.37 | 0.082 / 0 | 0⁵ / 0 | 0 / 0 | 6.75⁵ / 5.57 | 0.906 / 6.75 | 0⁵ / 6.67 |
| node-prisma | default | 2.97⁵ / 14.2 | 4.22⁵ / 5.7 | 8.91 / 0 | 0.0625⁵ / 0 | 0 / 0 | 0⁵˒¹⁶ / 0¹⁶ | 0¹⁶ / 0¹⁶ | 1.46⁵ / 2.32 | 6.63 / 0 | 0⁵ / 1.38 |
| node-prisma | tuned | 8.32⁵ / 6.8 | 3.97⁵ / 5.41 | 14.8 / 24.5 | 1.78⁵ / 0 | 0 / 0 | 0⁵˒¹⁶ / 0¹⁶ | 0¹⁶ / 0.25 | 0.195⁵ / 2.36 | 6.59 / 6.57 | 0.262⁵ / 0.0742 |
| dotnet-dapper | default | 1.03⁵ / 0.0703 | 64⁵ / 65 | 32 / 0 | 14.4⁵ / 8.88 | 0 / 0 | 0⁵ / 0 | 0 / 0 | 20.3⁵ / 23.9 | 18.4 / 12 | n/a⁵ / n/a |
| dotnet-dapper | tuned | 64.2⁵ / 34.6 | 31.6⁵ / 32.4 | 26 / 0.141 | 14.2⁵ / 15.4 | 0 / 0 | 0⁵ / 0 | 0 / 0 | 1.25⁵ / 26.9 | 20.8 / 19.9 | n/a⁵ / n/a |
| dotnet-efcore | default | 32.1⁵ / 0 | 0.281⁵ / 25 | 3.85 / 0.215 | 29.7⁵ / 11.4 | 2.04 / 7.5 | 0⁵ / 0 | 0 / 0 | 26.4⁵ / 25.6 | 16.8 / 14.1 | n/a⁵ / n/a |
| dotnet-efcore | tuned | 32.2⁵ / 0 | 32.8⁵ / 0.465 | 28.5 / 30.3 | 25.4⁵ / 13.4 | 7.62 / 7.55 | 0⁵ / 0 | 0 / 0 | 33.4⁵ / 29.5 | 14.9 / 22.5 | n/a⁵ / n/a |
| php-dbal | default | 218⁵ / 199 | 218⁵ / 199 | 199 / 199 | 22.8⁵ / 22.7 | 22.8 / 22.7 | 0⁵ / 0 | 0 / 0 | 4.88⁵ / 0 | 0 / 0 | n/a⁵ / n/a |
| php-dbal | tuned | 218⁵ / 199 | 218⁵ / 199 | 199 / 199 | 22.8⁵ / 22.7 | 22.8 / 22.7 | 0⁵ / 0 | 0 / 0 | 4.88⁵ / 0 | 0 / 0 | n/a⁵ / n/a |
| php-doctrine-orm | default | 218⁵ / 199 | 218⁵ / 199 | 199 / 199 | 19.8⁵ / 19.8 | 19.8 / 19.8 | 0⁵ / 0 | 0 / 0 | 2.86⁵ / 0 | 0 / 0 | n/a⁵ / n/a |
| php-doctrine-orm | tuned | 218⁵ / 199 | 218⁵ / 199 | 199 / 199 | 19.8⁵ / 19.8 | 19.8 / 19.8 | 0⁵ / 0 | 0 / 0 | 2.86⁵ / 0 | 0 / 0 | n/a⁵ / n/a |
| php-eloquent | default | 193⁵ / 189 | 193⁵ / 189 | 189 / 189 | 13.5⁵ / 13.3 | 13.3 / 13.3 | 0⁵ / 0 | 0 / 0 | 6.12⁵ / 0 | 0 / 0 | n/a⁵ / n/a |
| php-eloquent | tuned | 193⁵ / 189 | 193⁵ / 189 | 189 / 189 | 13.5⁵ / 13.3 | 13.3 / 13.3 | 0⁵ / 0 | 0 / 0 | 6.12⁵ / 0 | 0 / 0 | n/a⁵ / n/a |
| rb-sequel | default | 245⁵ / 220 | 255⁵ / 220 | 291 / 187 | 0⁵ / 0 | 0 / 0 | 0.0938⁵ / 0 | 0 / 0 | 12.8⁵ / 0.137 | 9.64 / 0 | 0⁵ / 0 |
| rb-sequel | tuned | 144⁵ / 43.8 | 0⁵ / 20.1 | 41.8 / 22.9 | 0.121⁵ / 0 | 0 / 0 | 0⁵ / 0 | 0 / 0.0703 | 0⁵ / 0 | 0 / 0 | 21.6⁵ / 19.6 |
| rb-activerecord | default | 0.0625⁵ / 52.2 | 0.352⁵ / 20.2 | 0.273 / 20.6 | 0.0508⁵ / 0 | 0.0547 / 0 | 0⁵ / 0.0859 | 0.125 / 0 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0 |
| rb-activerecord | tuned | 56⁵ / 2.99 | 45.4⁵ / 35.4 | 2.93 / 0 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0 | 0 / 0 | 10.7⁵ / 0 |
| rust-diesel | default | 192⁵ / 182 | 205⁵ / 195 | 192 / 182 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0 |
| rust-diesel | tuned | 107⁵ / 97.1 | 107⁵ / 97.1 | 97.1 / 97.1 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0 | 0 / 0 | 0⁵ / 0 |
| rust-seaorm | default | n/a⁵˒¹⁷ / 0.168¹⁷ | n/a⁵˒¹⁷ / 69.9¹⁷ | 14¹⁷ / 3.24¹⁷ | n/a⁵˒¹⁷ / 0¹⁷ | 0¹⁷ / 0¹⁷ | n/a⁵˒¹⁷ / 0¹⁷ | 0¹⁷ / 0¹⁷ | n/a⁵˒¹⁷ / 0¹⁷ | 0¹⁷ / 0.102¹⁷ | n/a⁵˒¹⁷ / 0¹⁷ |
| rust-seaorm | tuned | n/a⁵˒¹⁷ / 1.39¹⁷ | n/a⁵˒¹⁷ / 120¹⁷ | 77.1¹⁷ / 15.4¹⁷ | n/a⁵˒¹⁷ / 0.168¹⁷ | 0¹⁷ / 0¹⁷ | n/a⁵˒¹⁷ / 0¹⁷ | 0¹⁷ / 0¹⁷ | n/a⁵˒¹⁷ / 0¹⁷ | 0¹⁷ / 0.199¹⁷ | n/a⁵˒¹⁷ / 0¹⁷ |

⁵ **Percona converts JSON on every read.** Percona Server (like MySQL) stores JSON in a binary format and converts it to text on every read: about 13× the server CPU of the same bytes as LONGBLOB, and ~10% larger output. The slower send makes most clients spend more CPU per KB than reading the same documents from MariaDB, which stores JSON as text.  
¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  
¹⁷ **SeaORM and MySQL JSON columns.** SeaORM 2.0.4 cannot read a MySQL JSON column into a String (sqlx reports mismatched types); it only maps JSON to Json, which parses every value. The text-read doc cells are therefore n/a on Percona; on MariaDB JSON is LONGTEXT and works. t_blob is mapped as two entities (doc / doc_bin) so the default model can be loaded at all.  

### T6 — memory for the work, MB (Percona / MariaDB)

| stack | config | batch | multiparam | sqltext |
|---|---|---|---|---|
| py-sqlalchemy-core | default | 0 / 0 | 0 / 0 | n/a / n/a |
| py-sqlalchemy-core | tuned | 0 / 0 | 0 / 0 | n/a / n/a |
| py-sqlalchemy-orm | default | 0 / 0 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-orm | tuned | 0 / 0 | n/a / n/a | n/a / n/a |
| py-django-orm | default | 0 / 0 | n/a / n/a | n/a / n/a |
| py-django-orm | tuned | 0 / 0 | n/a / n/a | n/a / n/a |
| java-jdbctemplate | default | 0 / 0 | 0 / 0 | n/a / n/a |
| java-jdbctemplate | tuned | 0.0664 / 0 | 2.36 / 0 | n/a / n/a |
| java-jooq | default | 0 / 0 | 0 / 0 | n/a / n/a |
| java-jooq | tuned | 0 / 0 | 0.0547 / 0 | n/a / n/a |
| java-hibernate | default | 0 / 0 | n/a / n/a | n/a / n/a |
| java-hibernate | tuned | 0 / 0 | n/a / n/a | n/a / n/a |
| go-sqlx | default | 0.402 / 0.227 | n/a / n/a | n/a / n/a |
| go-sqlx | tuned | 0.336 / 0.316 | n/a / n/a | n/a / n/a |
| go-gorm | default | 0.293 / 0.312 | n/a / n/a | n/a / n/a |
| go-gorm | tuned | 0.254 / 0 | n/a / n/a | n/a / n/a |
| node-knex | default | 0.578 / 0.293 | n/a / n/a | n/a / n/a |
| node-drizzle | default | 3.08 / 2.99 | n/a / n/a | n/a / n/a |
| node-drizzle | tuned | 3.1 / 3.45 | n/a / n/a | n/a / n/a |
| node-typeorm | default | 4.48 / 3.52 | n/a / n/a | n/a / n/a |
| node-typeorm | tuned | 6.27 / 4.72 | n/a / n/a | n/a / n/a |
| node-sequelize | default | 0.207 / 0.109 | n/a / n/a | n/a / n/a |
| node-sequelize | tuned | 0.172 / 0 | n/a / n/a | n/a / n/a |
| node-prisma | default | 27.6 / 7.15 | n/a / n/a | n/a / n/a |
| node-prisma | tuned | 28.1 / 6.55 | n/a / n/a | n/a / n/a |
| dotnet-dapper | default | 0 / 0 | n/a / n/a | n/a / n/a |
| dotnet-dapper | tuned | 0 / 0 | n/a / n/a | n/a / n/a |
| dotnet-efcore | default | 0.0859 / 0 | n/a / n/a | n/a / n/a |
| dotnet-efcore | tuned | 7.12 / 7.5 | n/a / n/a | n/a / n/a |
| php-dbal | default | 0 / 0 | 0 / 0 | n/a / n/a |
| php-dbal | tuned | 0 / 0 | 0 / 0 | n/a / n/a |
| php-doctrine-orm | default | 0¹⁹ / 0¹⁹ | n/a¹⁹ / n/a¹⁹ | n/a¹⁹ / n/a¹⁹ |
| php-doctrine-orm | tuned | 0 / 0 | n/a / n/a | n/a / n/a |
| php-eloquent | default | 0 / 0 | n/a / n/a | n/a / n/a |
| php-eloquent | tuned | 0 / 0 | n/a / n/a | n/a / n/a |
| rb-sequel | default | 0¹⁹ / 0¹⁹ | n/a¹⁹ / n/a¹⁹ | n/a¹⁹ / n/a¹⁹ |
| rb-sequel | tuned | 0.125 / 0 | n/a / n/a | n/a / n/a |
| rb-activerecord | default | 0¹⁹ / 0.465¹⁹ | n/a¹⁹ / n/a¹⁹ | n/a¹⁹ / n/a¹⁹ |
| rb-activerecord | tuned | 0 / 0 | n/a / n/a | n/a / n/a |
| rust-diesel | default | 0 / 0 | n/a / n/a | n/a / n/a |
| rust-diesel | tuned | 0 / 0 | n/a / n/a | n/a / n/a |
| rust-seaorm | default | 0 / 0 | n/a / n/a | n/a / n/a |
| rust-seaorm | tuned | 0 / 0 | n/a / n/a | n/a / n/a |

¹⁹ **Per-row ORM inserts.** Default config inserts model objects one INSERT per row (1,000,000 statements, one transaction per 1,000 rows), the ORM's usual idiom; the tuned config uses the framework's bulk insert (one multi-row INSERT per 1,000 rows). Sequel Model.create also re-reads each row after INSERT.  

### T3 — memory growth since connect, MB (Percona / MariaDB)

| stack | config | text-buffered | text-buffered+tls | text-streamed | text-streamed+tls | binary-buffered | binary-streamed |
|---|---|---|---|---|---|---|---|
| py-sqlalchemy-core | default | 199 / 199 | 199 / 199 | 0.32 / 0.332 | 0.285 / 0.281 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-core | tuned | 199 / 199 | 199 / 199 | 0.324 / 0.336 | 0.285 / 0.281 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-orm | default | 1,203 / 1,203 | 1,203 / 1,203 | 3.82 / 3.82 | 3.79 / 3.79 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-orm | tuned | 3.81 / 3.82 | 3.79 / 3.79 | 3.82 / 3.82 | 3.78 / 3.79 | n/a / n/a | n/a / n/a |
| py-django-orm | default | 328 / 328 | 328 / 328 | 199 / 199 | 199 / 199 | n/a / n/a | n/a / n/a |
| py-django-orm | tuned | 201 / 201 | 200 / 201 | 199 / 199 | 199 / 199 | n/a / n/a | n/a / n/a |
| java-jdbctemplate | default | 1,955 / 1,933 | 2,021 / 2,029 | 23.9 / 24.3 | 22.6 / 32.9 | n/a / n/a | n/a / n/a |
| java-jdbctemplate | tuned | 24 / 23.9 | 31.7 / 35 | 24.3 / 23.9 | 27.9 / 27.4 | n/a / n/a | n/a / n/a |
| java-jooq | default | 1,711¹⁶ / 1,839¹⁶ | 1,838¹⁶ / 1,820 | 34.9 / 35 | 39 / 40.4 | n/a / n/a | n/a / n/a |
| java-jooq | tuned | 34.2 / 35.4 | 33.6 / 39.5 | 34.7 / 35.7 | 25.9 / 39.2 | n/a / n/a | n/a / n/a |
| java-hibernate | default | 1,532 / 1,417 | 1,391 / 1,560¹⁶ | 1,709¹⁶ / 1,676 | 1,601¹⁶ / 1,453¹⁶ | n/a / n/a | n/a / n/a |
| java-hibernate | tuned | 13.4 / 15.5 | 15.7 / 13.7 | 18.2 / 11.6 | 9.39 / 17.2 | n/a / n/a | n/a / n/a |
| go-sqlx | default | 66.9 / 67.1 | 66.9 / 84.5 | 5.44 / 5.64 | 6.02 / 5.11 | n/a / n/a | n/a / n/a |
| go-sqlx | tuned | 66.8 / 71.9 | 66.6 / 77.8 | 5.39 / 5.83 | 5.64 / 5.31 | n/a / n/a | n/a / n/a |
| go-gorm | default | 80.3 / 82.4 | 79 / 75.8 | 6.07 / 6.05 | 6.14 / 5.61 | n/a / n/a | n/a / n/a |
| go-gorm | tuned | 65.1 / 65.1 | 81.4 / 65.3 | 5.39 / 30.8 | 5.74 / 5.47 | n/a / n/a | n/a / n/a |
| node-knex | default | 430 / 450¹⁶ | 367 / 392¹⁶ | 65.2 / 66.6 | 66.6 / 68.9 | n/a / n/a | n/a / n/a |
| node-drizzle | default | 662 / 623 | 627¹⁶ / 637 | 1,245 / 1,210 | 1,265 / 1,267 | n/a / n/a | n/a / n/a |
| node-drizzle | tuned | 599¹⁶ / 642 | 635 / 600¹⁶ | 1,212 / 1,211 | 1,267 / 1,267¹⁶ | n/a / n/a | n/a / n/a |
| node-typeorm | default | 965 / 986 | 1,108 / 1,003 | 63.4 / 64.3 | 29.7 / 32.5 | n/a / n/a | n/a / n/a |
| node-typeorm | tuned | 439 / 438 | 397 / 442¹⁶ | 63.6 / 62.4 | 30.9 / 30.5 | n/a / n/a | n/a / n/a |
| node-sequelize | default | 1,309 / 1,247 | 1,363 / 1,250 | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a |
| node-sequelize | tuned | 690¹⁶ / 651 | 622 / 595¹⁶ | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a |
| node-prisma | default | 979¹⁶ / 955¹⁶ | 671 / 705 | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a |
| node-prisma | tuned | 990¹⁶ / 885 | 958 / 723 | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a |
| dotnet-dapper | default | 29.2 / 28.6 | 28 / 28 | 20.5 / 20.5 | 19.3 / 19.4 | n/a / n/a | n/a / n/a |
| dotnet-dapper | tuned | 20.5 / 20.4 | 19.4 / 19.4 | 20.5 / 20.5 | 19.4 / 19.4 | n/a / n/a | n/a / n/a |
| dotnet-efcore | default | 533 / 515 | 539 / 537 | 343 / 343 | 342 / 400 | n/a / n/a | n/a / n/a |
| dotnet-efcore | tuned | 87.7 / 92.1 | 92.7 / 91.2 | 19.8 / 19.7 | 19.4 / 19.8 | n/a / n/a | n/a / n/a |
| php-dbal | default | 403 / 402 | 402 / 403 | 0 / 0 | 0 / 0 | n/a / n/a | n/a / n/a |
| php-dbal | tuned | 40.1 / 40 | 40 / 40.1 | 0 / 0 | 0 / 0 | n/a / n/a | n/a / n/a |
| php-doctrine-orm | default | 1,059 / 1,059 | 1,059 / 1,059 | 980 / 980 | 980 / 980 | n/a / n/a | n/a / n/a |
| php-doctrine-orm | tuned | 42.1 / 42.1 | 42 / 42.2 | 42.1 / 42.1 | 42 / 42.2 | n/a / n/a | n/a / n/a |
| php-eloquent | default | 1,204 / 1,204 | 1,204 / 1,204 | 44.4 / 44.4 | 44.4 / 44.4 | n/a / n/a | n/a / n/a |
| php-eloquent | tuned | 449 / 449 | 448 / 449 | 44.4 / 44.4 | 44.4 / 44.4 | n/a / n/a | n/a / n/a |
| rb-sequel | default | 308 / 308 | 308 / 308 | 2.23 / 2.22 | 2.22 / 2.23 | n/a / n/a | n/a / n/a |
| rb-sequel | tuned | 193 / 183 | 183 / 183 | 5.34 / 5.34 | 5.33 / 5.34 | n/a / n/a | n/a / n/a |
| rb-activerecord | default | 1,478 / 1,478 | 1,478 / 1,478 | 12.3¹⁸ / 12.2¹⁸ | 12.2¹⁸ / 12.2¹⁸ | n/a / n/a | n/a¹⁸ / n/a¹⁸ |
| rb-activerecord | tuned | 188 / 188 | 188 / 188 | 2.74¹⁸ / 2.75¹⁸ | 2.72¹⁸ / 2.75¹⁸ | n/a / n/a | n/a¹⁸ / n/a¹⁸ |
| rust-diesel | default | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | 45.9 / 45.9 | 38.5 / 38.5 |
| rust-diesel | tuned | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | 34.4 / 34.4 | 30.9 / 30.9 |
| rust-seaorm | default | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | 155 / 155 | 0.113 / 0.105 |
| rust-seaorm | tuned | n/a / n/a | n/a / n/a | n/a / n/a | n/a / n/a | 117 / 118 | 0.109 / 0.0977 |

¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  
¹⁸ **ActiveRecord has no row streaming.** ActiveRecord cannot stream a result set. The streamed variant uses its batch API (find_each / in_batches, 1,000 rows per keyset page), i.e. 1,000 queries instead of one.  

### T4 — memory growth since connect, MB (Percona / MariaDB)

| stack | config | int-text | mix-text | int-binary | mix-binary |
|---|---|---|---|---|---|
| py-sqlalchemy-core | default | 54.6 / 55.3 | 90.1 / 86.3 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-core | tuned | 54.6 / 55.3 | 86.3 / 86.3 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-orm | default | 84.3 / 84.3 | 108 / 108 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-orm | tuned | 17.6 / 17.6 | 22.6 / 22.6 | n/a / n/a | n/a / n/a |
| py-django-orm | default | 75.6 / 75.6 | 96.4 / 96.4 | n/a / n/a | n/a / n/a |
| py-django-orm | tuned | 54.4 / 54.4 | 86.2 / 86.2 | n/a / n/a | n/a / n/a |
| java-jdbctemplate | default | 667 / 668 | 1,943 / 2,011 | n/a / n/a | n/a / n/a |
| java-jdbctemplate | tuned | 24.5 / 24.3 | 32.9 / 32 | n/a / n/a | n/a / n/a |
| java-jooq | default | 732 / 1,043 | 1,158 / 1,154 | n/a / n/a | n/a / n/a |
| java-jooq | tuned | 938 / 728 | 1,429 / 1,084 | n/a / n/a | n/a / n/a |
| java-hibernate | default | 1,865 / 1,898 | 1,575 / 1,357 | n/a / n/a | n/a / n/a |
| java-hibernate | tuned | 1,905 / 1,898 | 1,630 / 1,990¹⁶ | n/a / n/a | n/a / n/a |
| go-sqlx | default | 37.3 / 41.1 | 90.9 / 98.8 | n/a / n/a | n/a / n/a |
| go-sqlx | tuned | 41.1 / 42.2 | 91.7 / 100 | n/a / n/a | n/a / n/a |
| go-gorm | default | 47.1 / 42 | 106 / 95.8 | n/a / n/a | n/a / n/a |
| go-gorm | tuned | 47.9 / 42.1 | 96.1 / 90.2 | n/a / n/a | n/a / n/a |
| node-knex | default | 220 / 213 | 340 / 344 | n/a / n/a | n/a / n/a |
| node-drizzle | default | 274 / 266 | 376 / 253 | n/a / n/a | n/a / n/a |
| node-drizzle | tuned | 346 / 278 | 371 / 378 | n/a / n/a | n/a / n/a |
| node-typeorm | default | 412¹⁶ / 399 | 588 / 514 | n/a / n/a | n/a / n/a |
| node-typeorm | tuned | 296 / 328 | 333 / 329 | n/a / n/a | n/a / n/a |
| node-sequelize | default | 327 / 330 | 235 / 230 | n/a / n/a | n/a / n/a |
| node-sequelize | tuned | 283 / 370 | 396 / 392 | n/a / n/a | n/a / n/a |
| node-prisma | default | 542¹⁶ / 589 | 1,095¹⁶ / 1,171¹⁶ | n/a / n/a | n/a / n/a |
| node-prisma | tuned | 668¹⁶ / 571¹⁶ | 1,082 / 1,022¹⁶ | n/a / n/a | n/a / n/a |
| dotnet-dapper | default | 36 / 36.2 | 138 / 119 | n/a / n/a | n/a / n/a |
| dotnet-dapper | tuned | 25 / 24.8 | 25.6 / 25.4 | n/a / n/a | n/a / n/a |
| dotnet-efcore | default | 68.2 / 65.4 | 127 / 140 | n/a / n/a | n/a / n/a |
| dotnet-efcore | tuned | 34.7 / 34.6 | 116¹⁶ / 106 | n/a / n/a | n/a / n/a |
| php-dbal | default | 136 / 136 | 184 / 184 | n/a / n/a | n/a / n/a |
| php-dbal | tuned | 57.7 / 57.6 | 102 / 102 | n/a / n/a | n/a / n/a |
| php-doctrine-orm | default | 138 / 138 | 246 / 246 | n/a / n/a | n/a / n/a |
| php-doctrine-orm | tuned | 115 / 115 | 223 / 223 | n/a / n/a | n/a / n/a |
| php-eloquent | default | 122 / 122 | 166 / 166 | n/a / n/a | n/a / n/a |
| php-eloquent | tuned | 111 / 111 | 155 / 155 | n/a / n/a | n/a / n/a |
| rb-sequel | default | 94.7 / 94.7 | 185 / 186 | n/a / n/a | n/a / n/a |
| rb-sequel | tuned | 98.9 / 98.4 | 192 / 192 | n/a / n/a | n/a / n/a |
| rb-activerecord | default | 202 / 203 | 405 / 406 | n/a / n/a | n/a / n/a |
| rb-activerecord | tuned | 75.7 / 75.7 | 245 / 220 | n/a / n/a | n/a / n/a |
| rust-diesel | default | n/a / n/a | n/a / n/a | 15 / 15 | 65.8 / 65.8 |
| rust-diesel | tuned | n/a / n/a | n/a / n/a | 15 / 15 | 65.8 / 65.8 |
| rust-seaorm | default | n/a / n/a | n/a / n/a | 34.8 / 34.9 | 52.9 / 52.9 |
| rust-seaorm | tuned | n/a / n/a | n/a / n/a | 34.8 / 34.9 | 53 / 52.9 |

¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  

### T5 — memory growth since connect, MB (Percona / MariaDB)

| stack | config | 100k-doc | 100k-doc+tls | 100k-doc_bin | 10k-doc | 10k-doc_bin | 1k-doc | 1k-doc_bin | mix-doc | mix-doc_bin | 10k-doc-parse |
|---|---|---|---|---|---|---|---|---|---|---|---|
| py-sqlalchemy-core | default | 333⁵ / 313 | 333⁵ / 313 | 313 / 313 | 32.6⁵ / 29.7 | 29.6 / 29.6 | 3.68⁵ / 3.57 | 3.59 / 3.59 | 27.1⁵ / 26.8 | 28.1 / 28.1 | 32.6⁵ / 29.7 |
| py-sqlalchemy-core | tuned | 333⁵ / 313 | 333⁵ / 313 | 313 / 313 | 32.6⁵ / 29.7 | 29.6 / 29.6 | 3.45⁵ / 3.57 | 3.59 / 3.59 | 26.8⁵ / 26.8 | 28.1 / 28.1 | 32.7⁵ / 29.7 |
| py-sqlalchemy-orm | default | 579⁵ / 508 | 580⁵ / 533 | 526 / 506 | 56.7⁵ / 53.2 | 61.9 / 53.3 | 8.3⁵ / 8.09 | 7.8 / 7.39 | 53.2⁵ / 51.3 | 52.6 / 51.2 | 56.8⁵ / 53.1 |
| py-sqlalchemy-orm | tuned | 333⁵ / 313 | 333⁵ / 313 | 313 / 313 | 32.6⁵ / 29.7 | 29.6 / 29.6 | 3.47⁵ / 3.59 | 3.61 / 3.6 | 26.8⁵ / 26.8 | 26.8 / 26.8 | 32.7⁵ / 29.8 |
| py-django-orm | default | 333⁵ / 314 | 333⁵ / 314 | 314 / 314 | 37.6⁵ / 30.5 | 30.6 / 30.6 | 4.19⁵ / 4.03 | 4 / 4.02 | 28.9⁵ / 27.3 | 27.2 / 27.2 | 37.6⁵ / 30.5 |
| py-django-orm | tuned | 333⁵ / 313 | 333⁵ / 313 | 313 / 313 | 32.8⁵ / 29.9 | 29.8 / 29.9 | 3.99⁵ / 3.88 | 3.77 / 3.77 | 28.6⁵ / 27 | 27 / 27 | 32.9⁵ / 29.9 |
| java-jdbctemplate | default | 1,653⁵˒¹⁶ / 1,598¹⁶ | 1,859⁵ / 1,901 | 1,599¹⁶ / 1,892 | 1,852⁵ / 1,908 | 1,096 / 1,913 | 32.5⁵ / 31.2 | 34.4 / 31.5¹⁶ | 1,269⁵ / 1,935¹⁶ | 1,948 / 731 | n/a⁵ / n/a |
| java-jdbctemplate | tuned | 1,983⁵ / 2,067 | 2,030⁵ / 2,005 | 2,056 / 1,987 | 244⁵ / 250 | 431 / 258 | 27.9⁵ / 27.1 | 27.6¹⁶ / 28.6¹⁶ | 216⁵ / 136 | 74.4 / 78.3 | n/a⁵ / n/a |
| java-jooq | default | 1,569⁵ / 1,895 | 1,890⁵ / 1,861 | 1,689 / 1,656 | 1,409⁵ / 1,908 | 1,115 / 1,888 | 41.5⁵ / 44.4¹⁶ | 39.5 / 41.9 | 1,963⁵ / 1,929 | 1,310 / 1,027 | n/a⁵ / n/a |
| java-jooq | tuned | 1,876⁵ / 1,895 | 1,872⁵ / 1,877 | 1,895 / 1,897 | 867⁵ / 1,921 | 1,125 / 783 | 41.3⁵ / 39.5 | 39.3 / 39 | 899⁵ / 1,267 | 424 / 477 | n/a⁵ / n/a |
| java-hibernate | default | 1,853⁵ / 1,860 | 1,837⁵ / 1,906 | 1,573 / 1,618¹⁶ | 1,925⁵ / 1,254 | 1,073 / 1,214 | 18.4⁵ / 31.1 | 16.5 / 17.2¹⁶ | 474⁵ / 905 | 735 / 673 | n/a⁵ / n/a |
| java-hibernate | tuned | 1,873⁵ / 1,566 | 1,878⁵ / 1,522 | 1,506¹⁶ / 1,598¹⁶ | 1,871⁵ / 1,891 | 1,230 / 1,228 | 19⁵ / 16.4 | 11.2 / 15.2 | 1,197⁵ / 1,886 | 981 / 1,912¹⁶ | n/a⁵ / n/a |
| go-sqlx | default | 218⁵ / 200 | 216⁵ / 198 | 206 / 206 | 26.3⁵ / 27.2 | 29.4 / 29.4 | 4.99⁵ / 5.64 | 5.39 / 5.76 | 13.6⁵ / 21.9 | 19.2 / 23.4 | 34.8⁵ / 35.1 |
| go-sqlx | tuned | 218⁵ / 198 | 213⁵ / 198 | 206 / 206 | 26.2⁵ / 28.6 | 25.3 / 25.9 | 5.04⁵ / 5.66 | 5.31 / 5.51 | 21.2⁵ / 23 | 21.8 / 22.3 | 34.8⁵ / 35.6 |
| go-gorm | default | 219⁵ / 203 | 205⁵ / 201 | 206 / 206 | 24.7⁵ / 21.9 | 22.2 / 21.9 | 5.15⁵ / 5.61 | 5.57 / 5.53 | 21.5⁵ / 19.5 | 19.3 / 19.2 | 35.5⁵ / 35.2 |
| go-gorm | tuned | 212⁵ / 198 | 215⁵ / 201 | 206 / 206 | 25.1⁵ / 25.2 | 25.2 / 28.9 | 4.93⁵ / 5.34 | 5.39 / 5.54 | 20.9⁵ / 24.7 | 27 / 24.7 | 36⁵ / 35.1 |
| node-knex | default | 556⁵ / 780 | 550⁵ / 951 | 193 / 248 | 177⁵ / 194¹⁶ | 87 / 89.4 | 77.2⁵ / 85.7 | 39.2 / 39.6 | 137⁵˒¹⁶ / 140 | 93.4 / 90.2 | 173⁵ / 194 |
| node-drizzle | default | 569⁵ / 870 | 586⁵ / 993 | 283 / 280 | 171⁵ / 159 | 88.7 / 84.3 | 71.3⁵ / 74.4 | 59.3 / 52.6 | 152⁵˒¹⁶ / 156 | 88.8 / 96.5 | 208⁵ / 222 |
| node-drizzle | tuned | 579⁵ / 995 | 613⁵ / 826 | 273 / 282 | 182⁵ / 203 | 90.9 / 89.9 | 71.8⁵ / 73.9 | 59.6 / 55.8 | 152⁵˒¹⁶ / 158 | 97.4 / 93.1 | 217⁵ / 234 |
| node-typeorm | default | 554⁵ / 846 | 588⁵ / 804 | 254 / 198 | 199⁵ / 172 | 85.5 / 88.6 | 76⁵ / 85.9 | 40.7 / 32.1 | 176⁵ / 157 | 87.3¹⁶ / 92.4 | 198⁵ / 253 |
| node-typeorm | tuned | 525⁵ / 781 | 584⁵ / 880 | 241 / 206 | 165⁵˒¹⁶ / 187 | 88.5 / 87.2 | 77.9⁵ / 90.1 | 37 / 37.8 | 164⁵ / 172 | 92 / 91 | 181⁵ / 239 |
| node-sequelize | default | 603⁵ / 924 | 598⁵ / 1,030 | 246 / 193 | 160⁵ / 156 | 104 / 85.2 | 80.2⁵ / 73.3 | 102 / 102 | 213⁵ / 162 | 87.6 / 94.6¹⁶ | 188⁵ / 247 |
| node-sequelize | tuned | 584⁵ / 761 | 582⁵ / 851 | 198 / 201 | 207⁵ / 205 | 91.1 / 87.9 | 76.1⁵ / 72.5 | 52.4 / 54.8 | 152⁵ / 146 | 93.7 / 91.9 | 228⁵ / 250 |
| node-prisma | default | 584⁵ / 810 | 576⁵ / 935 | 519 / 520 | 199⁵ / 194 | 203 / 219 | 103⁵˒¹⁶ / 109¹⁶ | 131¹⁶ / 140¹⁶ | 201⁵ / 224 | 135 / 146 | 218⁵ / 237 |
| node-prisma | tuned | 582⁵ / 888 | 569⁵ / 940 | 520 / 514 | 195⁵ / 180 | 227 / 222 | 112⁵˒¹⁶ / 113¹⁶ | 129¹⁶ / 125 | 208⁵ / 227 | 137 / 137 | 220⁵ / 230 |
| dotnet-dapper | default | 2,077⁵ / 1,855 | 2,100⁵ / 1,846 | 958 / 948 | 124⁵ / 120 | 63.5 / 63.4 | 36.3⁵ / 32.1 | 30.5 / 30.5 | 141⁵ / 149 | 90.5 / 88.7 | n/a⁵ / n/a |
| dotnet-dapper | tuned | 2,078⁵ / 1,850 | 2,005⁵ / 1,843 | 947 / 926 | 124⁵ / 120 | 63.6 / 67.6 | 36.3⁵ / 32.2 | 30.5 / 30.5 | 143⁵ / 173 | 92.2 / 89.8 | n/a⁵ / n/a |
| dotnet-efcore | default | 2,040⁵ / 1,846 | 1,979⁵ / 1,814 | 952 / 947 | 116⁵ / 116 | 62 / 65.8 | 29.8⁵ / 26.2 | 25.6 / 25.7 | 139⁵ / 164 | 81.8 / 84.4 | n/a⁵ / n/a |
| dotnet-efcore | tuned | 2,073⁵ / 1,817 | 2,012⁵ / 1,819 | 920 / 955 | 117⁵ / 117 | 58 / 61.8 | 29.5⁵ / 26.1 | 25.6 / 25.6 | 169⁵ / 167 | 81.9 / 82.5 | n/a⁵ / n/a |
| php-dbal | default | 219⁵ / 201 | 219⁵ / 201 | 201 / 201 | 24.4⁵ / 24.3 | 24.4 / 24.3 | 2.35⁵ / 1.96 | 1.96 / 1.96 | 20.4⁵ / 19.4 | 19.4 / 19.4 | n/a⁵ / n/a |
| php-dbal | tuned | 219⁵ / 201 | 219⁵ / 201 | 201 / 201 | 24.4⁵ / 24.3 | 24.4 / 24.3 | 2.35⁵ / 1.96 | 1.96 / 1.96 | 20.4⁵ / 19.4 | 19.4 / 19.4 | n/a⁵ / n/a |
| php-doctrine-orm | default | 222⁵ / 203 | 221⁵ / 203 | 203 / 203 | 27.2⁵ / 27.2 | 27.2 / 27.2 | 5.62⁵ / 5.16 | 5.11 / 5.15 | 22.5⁵ / 21.6 | 21.7 / 21.6 | n/a⁵ / n/a |
| php-doctrine-orm | tuned | 222⁵ / 203 | 221⁵ / 203 | 203 / 203 | 27.2⁵ / 27.2 | 27.2 / 27.2 | 5.62⁵ / 5.16 | 5.11 / 5.15 | 22.5⁵ / 21.6 | 21.7 / 21.6 | n/a⁵ / n/a |
| php-eloquent | default | 221⁵ / 203 | 221⁵ / 203 | 203 / 203 | 28.7⁵ / 28.5 | 28.5 / 28.4 | 5.24⁵ / 3.73 | 3.73 / 3.73 | 21.8⁵ / 21.7 | 21.7 / 21.7 | n/a⁵ / n/a |
| php-eloquent | tuned | 221⁵ / 203 | 221⁵ / 203 | 203 / 203 | 28.7⁵ / 28.5 | 28.5 / 28.4 | 5.24⁵ / 3.73 | 3.73 / 3.73 | 21.8⁵ / 21.7 | 21.7 / 21.7 | n/a⁵ / n/a |
| rb-sequel | default | 1,194⁵ / 1,167 | 1,194⁵ / 1,159 | 1,194 / 1,167 | 182⁵ / 167 | 197 / 167 | 31.5⁵ / 25.2 | 30.7 / 25.2 | 192⁵ / 158 | 207 / 147 | 147⁵ / 108 |
| rb-sequel | tuned | 823⁵ / 803 | 832⁵ / 803 | 805 / 803 | 201⁵ / 164 | 158 / 158 | 33⁵ / 32.1 | 31.9 / 31.8 | 183⁵ / 201 | 201 / 216 | 170⁵ / 170 |
| rb-activerecord | default | 902⁵ / 866 | 903⁵ / 885 | 918 / 858 | 127⁵ / 126 | 127 / 109 | 29.4⁵ / 27.4 | 35 / 31 | 104⁵ / 112 | 100 / 117 | 114⁵ / 118 |
| rb-activerecord | tuned | 499⁵ / 472 | 483⁵ / 473 | 472 / 472 | 111⁵ / 101 | 130 / 130 | 20.7⁵ / 19.9 | 30.7 / 30.4 | 85.2⁵ / 93.1 | 120 / 110 | 97.4⁵ / 75.7 |
| rust-diesel | default | 411⁵ / 391 | 411⁵ / 391 | 411 / 391 | 41.3⁵ / 39.3 | 41.3 / 39.3 | 4.17⁵ / 3.99 | 4.17 / 3.99 | 34.2⁵ / 32.6 | 34.2 / 32.6 | 41.4⁵ / 39.4 |
| rust-diesel | tuned | 215⁵ / 196 | 215⁵ / 196 | 196 / 196 | 21.7⁵ / 19.7 | 19.7 / 19.7 | 2.2⁵ / 2.01 | 2.01 / 2.01 | 17.9⁵ / 16.3 | 16.3 / 16.3 | 21.8⁵ / 19.8 |
| rust-seaorm | default | n/a⁵˒¹⁷ / 131¹⁷ | n/a⁵˒¹⁷ / 126¹⁷ | 131¹⁷ / 130¹⁷ | n/a⁵˒¹⁷ / 14¹⁷ | 14¹⁷ / 14¹⁷ | n/a⁵˒¹⁷ / 1.75¹⁷ | 1.73¹⁷ / 1.74¹⁷ | n/a⁵˒¹⁷ / 12.1¹⁷ | 12.1¹⁷ / 12.2¹⁷ | n/a⁵˒¹⁷ / 14¹⁷ |
| rust-seaorm | tuned | n/a⁵˒¹⁷ / 131¹⁷ | n/a⁵˒¹⁷ / 125¹⁷ | 131¹⁷ / 131¹⁷ | n/a⁵˒¹⁷ / 14¹⁷ | 14¹⁷ / 14¹⁷ | n/a⁵˒¹⁷ / 1.7¹⁷ | 1.71¹⁷ / 1.7¹⁷ | n/a⁵˒¹⁷ / 12.1¹⁷ | 12.1¹⁷ / 12.2¹⁷ | n/a⁵˒¹⁷ / 14.1¹⁷ |

⁵ **Percona converts JSON on every read.** Percona Server (like MySQL) stores JSON in a binary format and converts it to text on every read: about 13× the server CPU of the same bytes as LONGBLOB, and ~10% larger output. The slower send makes most clients spend more CPU per KB than reading the same documents from MariaDB, which stores JSON as text.  
¹⁶ **Warm-up did not fully settle.** In at least one of the 5 processes the per-iteration cost never came within 5% for 3 iterations in a row before the 40-iteration cap, usually because of garbage collection. The figure is the median of steady-state iterations, but treat small differences as approximate.  
¹⁷ **SeaORM and MySQL JSON columns.** SeaORM 2.0.4 cannot read a MySQL JSON column into a String (sqlx reports mismatched types); it only maps JSON to Json, which parses every value. The text-read doc cells are therefore n/a on Percona; on MariaDB JSON is LONGTEXT and works. t_blob is mapped as two entities (doc / doc_bin) so the default model can be loaded at all.  

### T6 — memory growth since connect, MB (Percona / MariaDB)

| stack | config | batch | multiparam | sqltext |
|---|---|---|---|---|
| py-sqlalchemy-core | default | 1.33 / 1.34 | 3.32 / 3.32 | n/a / n/a |
| py-sqlalchemy-core | tuned | 1.33 / 1.33 | 3.32 / 3.32 | n/a / n/a |
| py-sqlalchemy-orm | default | 4.31 / 4.3 | n/a / n/a | n/a / n/a |
| py-sqlalchemy-orm | tuned | 1.85 / 1.86 | n/a / n/a | n/a / n/a |
| py-django-orm | default | 2.42 / 2.42 | n/a / n/a | n/a / n/a |
| py-django-orm | tuned | 2.42 / 2.42 | n/a / n/a | n/a / n/a |
| java-jdbctemplate | default | 48.4 / 47.9 | 44 / 50.1 | n/a / n/a |
| java-jdbctemplate | tuned | 54.2 / 52.9 | 54.8 / 49.9 | n/a / n/a |
| java-jooq | default | 54.5 / 53.6 | 58.6 / 54.6 | n/a / n/a |
| java-jooq | tuned | 55.9 / 59 | 54.2 / 62.5 | n/a / n/a |
| java-hibernate | default | 24.6 / 34.3 | n/a / n/a | n/a / n/a |
| java-hibernate | tuned | 9.14 / 24 | n/a / n/a | n/a / n/a |
| go-sqlx | default | 5.45 / 5.44 | n/a / n/a | n/a / n/a |
| go-sqlx | tuned | 5.25 / 5.46 | n/a / n/a | n/a / n/a |
| go-gorm | default | 5.45 / 5.43 | n/a / n/a | n/a / n/a |
| go-gorm | tuned | 5.05 / 4.9 | n/a / n/a | n/a / n/a |
| node-knex | default | 61.5 / 64.6 | n/a / n/a | n/a / n/a |
| node-drizzle | default | 115 / 115 | n/a / n/a | n/a / n/a |
| node-drizzle | tuned | 114 / 120 | n/a / n/a | n/a / n/a |
| node-typeorm | default | 141 / 142 | n/a / n/a | n/a / n/a |
| node-typeorm | tuned | 118 / 118 | n/a / n/a | n/a / n/a |
| node-sequelize | default | 99.9 / 101 | n/a / n/a | n/a / n/a |
| node-sequelize | tuned | 101 / 99.7 | n/a / n/a | n/a / n/a |
| node-prisma | default | 514 / 518 | n/a / n/a | n/a / n/a |
| node-prisma | tuned | 513 / 504 | n/a / n/a | n/a / n/a |
| dotnet-dapper | default | 31 / 31.5 | n/a / n/a | n/a / n/a |
| dotnet-dapper | tuned | 31 / 31.1 | n/a / n/a | n/a / n/a |
| dotnet-efcore | default | 30.8 / 30.4 | n/a / n/a | n/a / n/a |
| dotnet-efcore | tuned | 46.3 / 42.1 | n/a / n/a | n/a / n/a |
| php-dbal | default | 0 / 0 | 1.01 / 1.01 | n/a / n/a |
| php-dbal | tuned | 0 / 0 | 1.01 / 1.01 | n/a / n/a |
| php-doctrine-orm | default | 3.67¹⁹ / 3.8¹⁹ | n/a¹⁹ / n/a¹⁹ | n/a¹⁹ / n/a¹⁹ |
| php-doctrine-orm | tuned | 3.67 / 3.8 | n/a / n/a | n/a / n/a |
| php-eloquent | default | 3.77 / 3.77 | n/a / n/a | n/a / n/a |
| php-eloquent | tuned | 3.77 / 3.77 | n/a / n/a | n/a / n/a |
| rb-sequel | default | 13¹⁹ / 10.1¹⁹ | n/a¹⁹ / n/a¹⁹ | n/a¹⁹ / n/a¹⁹ |
| rb-sequel | tuned | 2.91 / 2.54 | n/a / n/a | n/a / n/a |
| rb-activerecord | default | 17.8¹⁹ / 18.3¹⁹ | n/a¹⁹ / n/a¹⁹ | n/a¹⁹ / n/a¹⁹ |
| rb-activerecord | tuned | 4.86 / 4.74 | n/a / n/a | n/a / n/a |
| rust-diesel | default | 2.18 / 2.18 | n/a / n/a | n/a / n/a |
| rust-diesel | tuned | 2.18 / 2.18 | n/a / n/a | n/a / n/a |
| rust-seaorm | default | 1.15 / 1.09 | n/a / n/a | n/a / n/a |
| rust-seaorm | tuned | 1.15 / 1.09 | n/a / n/a | n/a / n/a |

¹⁹ **Per-row ORM inserts.** Default config inserts model objects one INSERT per row (1,000,000 statements, one transaction per 1,000 rows), the ORM's usual idiom; the tuned config uses the framework's bulk insert (one multi-row INSERT per 1,000 rows). Sequel Model.create also re-reads each row after INSERT.  
