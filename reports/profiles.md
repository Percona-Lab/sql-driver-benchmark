# Where the client CPU goes — profiles

> **AI-generated results.** Profiles were collected, classified and summarized with an AI assistant (Claude); the classification rules are heuristics over function and library names (`orchestrator/profile_report.py`). Spot-check anything that matters against the flame graphs.

Each profile samples the **measured iterations only** of one steady-state process (`perf record` at 2,999 Hz with call graphs, gated by the runner; warm-up and start-up are not sampled), on Percona Server with the default configuration. JIT runtimes write perf maps so generated code is named (Java `-XX:+PreserveFramePointer -XX:+DumpPerfMapAtExit`, Node `--perf-basic-prof`, Python 3.14 perf trampoline, .NET `DOTNET_PerfMapEnabled=1` with W^X off, Ruby `--yjit-perf`); native libraries are resolved with their debug symbols (Oracle `libmysqlclient24-dbgsym` 9.7.4, Ubuntu ddebs). Sampling adds some overhead, so use these for shares, not for timings.

**What kind of work** (percent of sampled cycles, by where the sample landed): code = the driver's, framework's or benchmark's own instructions; copy = memmove/memcpy; alloc+GC = allocators and garbage collectors; interp/VM = interpreter dispatch and VM runtime; crypto = TLS; k:send / k:recv = kernel network paths (on loopback the send path also delivers the packet to the server's socket); k:faults = page faults; k:mmap = mmap/brk; k:wait = poll, futex and scheduling (waiting for the server's reply lands here for drivers that poll, and in k:recv for drivers that block in a read); k:other = remaining kernel time.

## Findings

- **Verified TLS connects are mostly key exchange, plus per-connection setup.** TLS crypto is 61% of libmysqlclient's verified connect (P-256 elliptic-curve math). Every driver built on libmysqlclient or MariaDB Connector/C also builds a new OpenSSL context per connection: `SSL_CTX_new` is 11–13% of the connect, loading the CA file 5–8%, parsing cipher lists up to 10%. A connection pool avoids all of it.
- **MySQL Connector/J builds a new `SSLContext` for every connection** (`ExportControlled$SslContextBuilder.build()`: 63% of a verified connect): it reloads and decrypts the PKCS12 trust store each time (PBKDF2 key derivation, SHA-256 in JVM intrinsic stubs). This is why its verified TLS connect costs several milliseconds. (JVM stubs are not named, so Java's crypto share in the table is understated.)
- **Point selects are kernel work.** For native drivers about three quarters of the client CPU is in the kernel (libmysqlclient 77%, Rust `mysql` 78%): the send path (on loopback it also delivers the packet to the server's socket), waking up for the reply, and netfilter rules (5–7%, a property of this host, the same for every driver). Drivers that wait in `poll`/`epoll` (Connector/C, mysqlnd, Go, Rust async, .NET, Node, MariaDB Connector/J) and libmysqlclient, which blocks in `recvfrom`, spend the same total; the time is only charged to different system calls.
- **Oracle's MySql.Data runs its synchronous API on the thread pool:** in a point select half of the samples are on .NET thread-pool workers and 42% is thread hand-off (scheduling, futexes), which is where its extra cost over MySqlConnector goes.
- **Both Go drivers spend a third to a half of each streamed row on synchronization:** 54% of go-sql-driver's streamed-row CPU is atomics and mutexes in `database/sql` (`closingMutex.RLock/RUnlock`, the lock in `Rows.Next`), not the driver; go-mysql, which bypasses `database/sql`, spends 37% in `utils.BytesBufferGet`, a `sync.Pool` buffer fetched per packet.
- **Ruby mysql2 releases the GVL for every row** (`rb_nogvl` around `mysql_fetch_row`), even when the whole result is already in memory: mutex lock/unlock and thread hand-off take 35% of its buffered-row CPU (found with perf, caller confirmed with a bpftrace uprobe on `pthread_mutex_lock`).
- **Garbage collection dominates large results in managed runtimes:** allocation and GC are 41% of Node mysql2's buffered rows (V8's young-generation scavenger), 30% for MariaDB Connector/J, 40% for Hibernate; libmysqlclient instead spends 22% copying rows into its own buffers.
- **Interpreters:** pure-Python drivers spend most of their time in the interpreter (PyMySQL 80% of buffered rows); C-accelerated ones less (mysqlclient 57%, mostly creating Python objects for each row inside the driver's C code).
- **ORMs: the framework, not the driver, is the cost.** In a point select the framework's own code is 85% of Django's CPU, 80% of SQLAlchemy ORM's, 76% of Prisma's, 41% of EF Core's; for 1M rows as entities 92% (SQLAlchemy ORM) and 85% (GORM).
- **Limits of these profiles:** PHP has no perf map for interpreted code, so Doctrine and Eloquent show up as interpreter time, not as framework code. In async Rust, framework and driver code inlined into the caller's future can be counted as the benchmark. Stack unwinding uses frame pointers, which loses the direct caller of a leaf function that has no frame of its own (bpftrace confirmed the mysql2 caller).

**Whose code**: the innermost frame belonging to the driver, the framework or the benchmark loop (kernel time counts for the code that made the system call); runtime = everything else (language runtime, standard library).

## Verified TLS connect

| stack (variant) | code | copy | alloc+GC | interp/VM | crypto | k:send | k:recv | k:faults | k:mmap | k:wait | k:other | driver | framework | bench | runtime | flame graph |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| c-libmysqlclient (tls-verify) | 20 | 1 | 5 |  | 61 | 4 | 4 |  |  |  | 4 | 82 |  |  | 18 | [svg](../results/profiles/svg/ps/c-libmysqlclient/T1-tls-verify-default.svg) |
| c-mariadb-connc (tls-verify) | 17 | 1 | 6 |  | 62 | 4 | 3 |  |  | 2 | 5 | 80 |  |  | 20 | [svg](../results/profiles/svg/ps/c-mariadb-connc/T1-tls-verify-default.svg) |
| cpp-mariadb (tls-verify) | 21 | 2 | 6 |  | 57 | 5 | 4 |  |  | 2 | 5 | 82 |  |  | 18 | [svg](../results/profiles/svg/ps/cpp-mariadb/T1-tls-verify-default.svg) |
| cpp-mysql-connector (tls-verify) | 22 | 2 | 5 |  | 58 | 4 | 5 |  |  |  | 4 | 82 |  |  | 18 | [svg](../results/profiles/svg/ps/cpp-mysql-connector/T1-tls-verify-default.svg) |
| dotnet-mysqlconnector (tls-verify) | 20 | 1 | 7 |  | 61 | 3 | 3 |  |  |  | 5 | 72 |  | 7 | 21 | [svg](../results/profiles/svg/ps/dotnet-mysqlconnector/T1-tls-verify-default.svg) |
| go-mysql (tls-verify) | 38 | 1 | 6 |  | 40 | 4 | 3 |  |  | 3 | 5 | 69 |  |  | 31 | [svg](../results/profiles/svg/ps/go-mysql/T1-tls-verify-default.svg) |
| go-sql-driver (tls-verify) | 38 | 1 | 3 |  | 44 | 5 | 3 |  |  | 4 | 4 | 69 |  |  | 31 | [svg](../results/profiles/svg/ps/go-sql-driver/T1-tls-verify-default.svg) |
| java-connector-j (tls-verify) | 68 |  |  |  | 28 | 1 | 1 |  |  |  | 1 | 98 |  |  | 2 | [svg](../results/profiles/svg/ps/java-connector-j/T1-tls-verify-default.svg) |
| java-mariadb-j (tls-verify) | 38 |  |  |  | 55 | 2 | 1 |  |  | 1 | 2 | 96 |  |  | 4 | [svg](../results/profiles/svg/ps/java-mariadb-j/T1-tls-verify-default.svg) |
| node-mariadb (tls-verify) | 10 | 1 | 8 | 42 | 28 | 4 | 2 |  |  | 2 | 4 | 37 |  | 5 | 58 | [svg](../results/profiles/svg/ps/node-mariadb/T1-tls-verify-default.svg) |
| node-mysql2 (tls-verify) | 10 | 3 | 12 | 42 | 24 | 4 | 2 |  |  | 1 | 3 | 32 |  | 8 | 61 | [svg](../results/profiles/svg/ps/node-mysql2/T1-tls-verify-default.svg) |
| php-mysqli (tls-verify) | 18 | 2 | 6 | 1 | 61 | 4 | 2 |  |  | 2 | 4 | 82 |  |  | 18 | [svg](../results/profiles/svg/ps/php-mysqli/T1-tls-verify-default.svg) |
| php-pdo-mysql (tls-verify) | 17 | 1 | 6 | 2 | 61 | 4 | 2 |  |  | 2 | 4 | 81 |  |  | 19 | [svg](../results/profiles/svg/ps/php-pdo-mysql/T1-tls-verify-default.svg) |
| py-mariadb (tls-verify) | 17 | 1 | 6 | 2 | 60 | 4 | 3 |  |  | 2 | 5 | 80 |  | 2 | 19 | [svg](../results/profiles/svg/ps/py-mariadb/T1-tls-verify-default.svg) |
| py-mysql-connector-c (tls-verify) | 20 | 2 | 6 | 6 | 53 | 5 | 4 |  |  |  | 5 | 83 |  | 1 | 16 | [svg](../results/profiles/svg/ps/py-mysql-connector-c/T1-tls-verify-default.svg) |
| py-mysql-connector-pure (tls-verify) | 17 | 2 | 13 | 2 | 63 | 1 | 1 |  |  |  | 1 | 94 |  | 4 | 2 | [svg](../results/profiles/svg/ps/py-mysql-connector-pure/T1-tls-verify-default.svg) |
| py-mysqlclient (tls-verify) | 20 | 1 | 5 | 3 | 57 | 5 | 4 |  |  |  | 5 | 83 |  | 1 | 16 | [svg](../results/profiles/svg/ps/py-mysqlclient/T1-tls-verify-default.svg) |
| py-pymysql (tls-verify) | 16 | 1 | 6 | 12 | 52 | 4 | 4 |  |  |  | 5 | 83 |  | 2 | 15 | [svg](../results/profiles/svg/ps/py-pymysql/T1-tls-verify-default.svg) |
| rb-mysql2 (tls-verify) | 20 | 1 | 7 | 1 | 58 | 4 | 4 |  |  |  | 4 | 82 |  | 1 | 17 | [svg](../results/profiles/svg/ps/rb-mysql2/T1-tls-verify-default.svg) |
| rb-trilogy (tls-verify) | 17 | 2 | 11 | 1 | 47 | 5 | 6 |  | 1 | 1 | 10 | 86 |  | 1 | 14 | [svg](../results/profiles/svg/ps/rb-trilogy/T1-tls-verify-default.svg) |
| rust-mysql (tls-verify) | 21 | 3 | 6 |  | 47 | 7 | 9 |  |  |  | 6 | 52 |  |  | 47 | [svg](../results/profiles/svg/ps/rust-mysql/T1-tls-verify-default.svg) |
| rust-sqlx (tls-verify) | 14 | 3 | 2 |  | 58 | 8 | 5 |  |  | 5 | 5 | 48 |  | 5 | 47 | [svg](../results/profiles/svg/ps/rust-sqlx/T1-tls-verify-default.svg) |
| java-hibernate (tls-verify) | 70 |  |  |  | 26 | 1 | 1 |  |  |  | 1 | 95 |  |  | 5 | [svg](../results/profiles/svg/ps/java-hibernate/T1-tls-verify-default.svg) |
| py-django-orm (tls-verify) | 20 | 1 | 6 | 7 | 52 | 5 | 4 |  |  |  | 5 | 80 | 5 |  | 15 | [svg](../results/profiles/svg/ps/py-django-orm/T1-tls-verify-default.svg) |
| py-sqlalchemy-core (tls-verify) | 20 | 1 | 6 | 6 | 54 | 5 | 4 |  |  |  | 4 | 81 | 4 |  | 15 | [svg](../results/profiles/svg/ps/py-sqlalchemy-core/T1-tls-verify-default.svg) |
| py-sqlalchemy-orm (tls-verify) | 20 | 1 | 6 | 8 | 52 | 5 | 4 |  |  |  | 5 | 79 | 7 |  | 14 | [svg](../results/profiles/svg/ps/py-sqlalchemy-orm/T1-tls-verify-default.svg) |
| rb-activerecord (tls-verify) | 21 | 1 | 8 | 3 | 54 | 4 | 4 |  |  | 1 | 4 | 79 | 4 | 1 | 16 | [svg](../results/profiles/svg/ps/rb-activerecord/T1-tls-verify-default.svg) |
| rb-sequel (tls-verify) | 21 | 1 | 7 | 2 | 56 | 4 | 4 |  |  | 1 | 4 | 81 | 1 | 1 | 17 | [svg](../results/profiles/svg/ps/rb-sequel/T1-tls-verify-default.svg) |
| rust-diesel (tls-verify) | 20 | 1 | 5 |  | 58 | 6 | 5 |  |  |  | 4 | 82 | 1 |  | 16 | [svg](../results/profiles/svg/ps/rust-diesel/T1-tls-verify-default.svg) |
| rust-seaorm (tls-verify) | 16 | 3 | 2 |  | 55 | 8 | 5 |  |  | 5 | 6 | 50 | 1 | 5 | 44 | [svg](../results/profiles/svg/ps/rust-seaorm/T1-tls-verify-default.svg) |

## Point select

| stack (variant) | code | copy | alloc+GC | interp/VM | crypto | k:send | k:recv | k:faults | k:mmap | k:wait | k:other | driver | framework | bench | runtime | flame graph |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| c-libmysqlclient (literal) | 18 | 3 | 2 |  |  | 52 | 21 |  |  |  | 4 | 98 |  | 2 |  | [svg](../results/profiles/svg/ps/c-libmysqlclient/T2-literal-default.svg) |
| c-mariadb-connc (literal) | 16 | 3 | 1 |  |  | 50 | 7 |  |  | 18 | 6 | 98 |  | 2 |  | [svg](../results/profiles/svg/ps/c-mariadb-connc/T2-literal-default.svg) |
| cpp-mariadb (literal) | 21 | 2 | 4 |  |  | 44 | 6 |  |  | 18 | 5 | 99 |  |  | 1 | [svg](../results/profiles/svg/ps/cpp-mariadb/T2-literal-default.svg) |
| cpp-mysql-connector (literal) | 26 | 4 | 4 |  |  | 45 | 18 |  |  |  | 3 | 97 |  |  | 3 | [svg](../results/profiles/svg/ps/cpp-mysql-connector/T2-literal-default.svg) |
| dotnet-mysql-data (literal) | 20 |  |  |  |  | 7 | 7 |  |  | 42 | 24 | 30 |  | 8 | 62 | [svg](../results/profiles/svg/ps/dotnet-mysql-data/T2-literal-default.svg) |
| dotnet-mysqlconnector (literal) | 32 |  |  | 1 |  | 42 | 5 |  |  | 17 | 4 | 72 |  | 27 | 1 | [svg](../results/profiles/svg/ps/dotnet-mysqlconnector/T2-literal-default.svg) |
| go-mysql (literal) | 26 | 1 | 2 |  |  | 41 | 7 |  |  | 20 | 4 | 70 |  | 2 | 28 | [svg](../results/profiles/svg/ps/go-mysql/T2-literal-default.svg) |
| go-sql-driver (literal) | 28 |  | 3 |  |  | 38 | 6 |  |  | 21 | 4 | 63 |  | 8 | 29 | [svg](../results/profiles/svg/ps/go-sql-driver/T2-literal-default.svg) |
| java-connector-j (literal) | 42 |  |  |  |  | 33 | 18 |  |  |  | 7 | 97 |  |  | 2 | [svg](../results/profiles/svg/ps/java-connector-j/T2-literal-default.svg) |
| java-mariadb-j (literal) | 14 |  |  |  |  | 54 | 9 |  |  | 17 | 5 | 98 |  |  | 1 | [svg](../results/profiles/svg/ps/java-mariadb-j/T2-literal-default.svg) |
| node-mariadb (literal) | 11 |  | 5 | 30 |  | 33 | 4 |  |  | 14 | 2 | 54 |  | 2 | 44 | [svg](../results/profiles/svg/ps/node-mariadb/T2-literal-default.svg) |
| node-mysql2 (literal) | 12 |  | 5 | 40 |  | 27 | 3 |  |  | 11 | 2 | 42 |  | 22 | 35 | [svg](../results/profiles/svg/ps/node-mysql2/T2-literal-default.svg) |
| php-mysqli (literal) | 15 | 4 | 2 | 6 |  | 46 | 5 |  |  | 18 | 4 | 96 |  |  | 4 | [svg](../results/profiles/svg/ps/php-mysqli/T2-literal-default.svg) |
| php-pdo-mysql (literal) | 15 | 3 | 2 | 6 |  | 46 | 5 |  |  | 18 | 4 | 94 |  |  | 6 | [svg](../results/profiles/svg/ps/php-pdo-mysql/T2-literal-default.svg) |
| py-mariadb (literal) | 15 | 1 | 4 | 22 |  | 36 | 5 |  |  | 12 | 4 | 96 |  | 4 | 1 | [svg](../results/profiles/svg/ps/py-mariadb/T2-literal-default.svg) |
| py-mysql-connector-c (literal) | 16 | 2 | 7 | 48 |  | 18 | 8 |  |  |  | 2 | 98 |  | 2 |  | [svg](../results/profiles/svg/ps/py-mysql-connector-c/T2-literal-default.svg) |
| py-mysql-connector-pure (literal) | 12 | 0 | 7 | 60 |  | 8 | 8 |  |  |  | 4 | 98 |  | 1 | 1 | [svg](../results/profiles/svg/ps/py-mysql-connector-pure/T2-literal-default.svg) |
| py-mysqlclient (literal) | 22 | 2 | 4 | 23 |  | 33 | 14 |  |  |  | 3 | 96 |  | 4 |  | [svg](../results/profiles/svg/ps/py-mysqlclient/T2-literal-default.svg) |
| py-pymysql (literal) | 10 | 0 | 5 | 60 |  | 17 | 6 |  |  |  | 1 | 98 |  | 2 |  | [svg](../results/profiles/svg/ps/py-pymysql/T2-literal-default.svg) |
| rb-mysql2 (literal) | 25 | 1 | 16 | 11 |  | 30 | 3 |  |  | 11 | 2 | 92 |  | 7 | 2 | [svg](../results/profiles/svg/ps/rb-mysql2/T2-literal-default.svg) |
| rb-trilogy (literal) | 20 | 0 | 3 | 9 |  | 42 | 7 |  |  | 15 | 4 | 95 |  | 2 | 2 | [svg](../results/profiles/svg/ps/rb-trilogy/T2-literal-default.svg) |
| rust-mysql (literal) | 18 | 2 | 3 |  |  | 52 | 21 |  |  |  | 4 | 98 |  | 1 | 1 | [svg](../results/profiles/svg/ps/rust-mysql/T2-literal-default.svg) |
| rust-sqlx (literal) | 35 | 1 | 1 |  |  | 41 | 5 |  |  | 13 | 4 | 76 |  | 23 | 1 | [svg](../results/profiles/svg/ps/rust-sqlx/T2-literal-default.svg) |
| dotnet-dapper (param) | 40 |  |  | 1 |  | 37 | 4 |  |  | 15 | 3 | 69 | 6 | 24 | 1 | [svg](../results/profiles/svg/ps/dotnet-dapper/T2-param-default.svg) |
| dotnet-efcore (param) | 67 | 0 |  | 2 |  | 19 | 2 |  |  | 7 | 2 | 37 | 41 | 22 |  | [svg](../results/profiles/svg/ps/dotnet-efcore/T2-param-default.svg) |
| go-gorm (param) | 33 |  | 6 |  |  | 38 | 5 |  |  | 15 | 3 | 58 | 18 |  | 23 | [svg](../results/profiles/svg/ps/go-gorm/T2-param-default.svg) |
| go-sqlx (param) | 26 |  | 2 |  |  | 44 | 7 |  |  | 18 | 2 | 68 | 7 |  | 25 | [svg](../results/profiles/svg/ps/go-sqlx/T2-param-default.svg) |
| java-hibernate (param) | 54 |  |  |  |  | 26 | 14 |  |  |  | 6 | 90 | 9 |  | 1 | [svg](../results/profiles/svg/ps/java-hibernate/T2-param-default.svg) |
| java-jdbctemplate (param) | 50 |  |  |  |  | 29 | 15 |  |  |  | 6 | 95 | 1 |  | 3 | [svg](../results/profiles/svg/ps/java-jdbctemplate/T2-param-default.svg) |
| java-jooq (param) | 59 |  |  |  |  | 24 | 12 |  |  |  | 5 | 74 | 24 | 1 | 1 | [svg](../results/profiles/svg/ps/java-jooq/T2-param-default.svg) |
| node-drizzle (param) | 18 |  | 2 | 61 |  | 11 | 1 |  |  | 5 | 1 | 21 | 60 | 3 | 17 | [svg](../results/profiles/svg/ps/node-drizzle/T2-param-default.svg) |
| node-knex (param) | 18 |  | 3 | 47 |  | 19 | 2 |  |  | 8 | 2 | 32 | 26 | 11 | 31 | [svg](../results/profiles/svg/ps/node-knex/T2-param-default.svg) |
| node-prisma (param) | 15 |  | 7 | 53 |  | 16 | 1 |  |  | 5 | 1 |  | 76 |  | 24 | [svg](../results/profiles/svg/ps/node-prisma/T2-param-default.svg) |
| node-sequelize (param) | 18 |  | 2 | 66 |  | 8 | 1 |  |  | 4 | 1 | 17 | 48 | 18 | 17 | [svg](../results/profiles/svg/ps/node-sequelize/T2-param-default.svg) |
| node-typeorm (param) | 20 |  | 2 | 55 |  | 14 | 2 |  |  | 6 | 1 | 28 | 49 | 2 | 21 | [svg](../results/profiles/svg/ps/node-typeorm/T2-param-default.svg) |
| php-dbal (param) | 14 | 2 | 6 | 30 |  | 30 | 3 |  |  | 12 | 3 | 62 |  |  | 38 | [svg](../results/profiles/svg/ps/php-dbal/T2-param-default.svg) |
| php-doctrine-orm (param) | 12 | 2 | 7 | 52 |  | 17 | 2 |  |  | 6 | 2 | 36 |  |  | 64 | [svg](../results/profiles/svg/ps/php-doctrine-orm/T2-param-default.svg) |
| php-eloquent (param) | 11 | 2 | 7 | 58 |  | 15 | 1 |  |  | 4 | 2 | 29 |  |  | 71 | [svg](../results/profiles/svg/ps/php-eloquent/T2-param-default.svg) |
| py-django-orm (param) | 15 | 0 | 7 | 72 |  | 4 | 2 |  |  |  | 0 | 14 | 85 | 1 |  | [svg](../results/profiles/svg/ps/py-django-orm/T2-param-default.svg) |
| py-sqlalchemy-core (param) | 20 | 1 | 6 | 64 |  | 6 | 3 |  |  |  | 1 | 22 | 73 | 3 | 1 | [svg](../results/profiles/svg/ps/py-sqlalchemy-core/T2-param-default.svg) |
| py-sqlalchemy-orm (param) | 19 | 1 | 6 | 67 |  | 5 | 2 |  |  |  | 1 | 16 | 80 | 3 | 1 | [svg](../results/profiles/svg/ps/py-sqlalchemy-orm/T2-param-default.svg) |
| rb-activerecord (param) | 40 | 1 | 10 | 24 |  | 16 | 2 |  |  | 6 | 1 | 48 | 45 | 5 | 2 | [svg](../results/profiles/svg/ps/rb-activerecord/T2-param-default.svg) |
| rb-sequel (param) | 28 | 1 | 20 | 16 |  | 23 | 2 |  |  | 8 | 2 | 81 | 14 | 0 | 5 | [svg](../results/profiles/svg/ps/rb-sequel/T2-param-default.svg) |
| rust-diesel (param) | 28 | 3 | 6 |  |  | 43 | 17 |  |  |  | 3 | 86 | 14 |  |  | [svg](../results/profiles/svg/ps/rust-diesel/T2-param-default.svg) |
| rust-seaorm (param) | 33 | 5 | 2 |  |  | 36 | 5 |  |  | 15 | 4 | 64 | 9 | 25 | 1 | [svg](../results/profiles/svg/ps/rust-seaorm/T2-param-default.svg) |

## 1M rows, buffered

| stack (variant) | code | copy | alloc+GC | interp/VM | crypto | k:send | k:recv | k:faults | k:mmap | k:wait | k:other | driver | framework | bench | runtime | flame graph |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| c-libmysqlclient (text-buffered) | 62 | 22 |  |  |  |  | 4 | 9 | 2 |  |  | 77 |  | 22 | 1 | [svg](../results/profiles/svg/ps/c-libmysqlclient/T3-text-buffered-default.svg) |
| c-mariadb-connc (text-buffered) | 60 | 17 |  |  |  |  | 2 | 15 | 4 | 2 |  | 80 |  | 19 | 1 | [svg](../results/profiles/svg/ps/c-mariadb-connc/T3-text-buffered-default.svg) |
| cpp-mariadb (text-buffered) | 73 | 9 | 6 |  |  |  | 2 | 7 | 2 | 1 |  | 100 |  |  | 0 | [svg](../results/profiles/svg/ps/cpp-mariadb/T3-text-buffered-default.svg) |
| cpp-mysql-connector (text-buffered) | 75 | 15 |  |  |  |  | 3 | 6 | 1 |  |  | 98 |  |  | 2 | [svg](../results/profiles/svg/ps/cpp-mysql-connector/T3-text-buffered-default.svg) |
| go-mysql (text-buffered) | 74 | 22 |  |  |  |  | 1 |  |  | 2 | 1 | 95 |  | 3 | 2 | [svg](../results/profiles/svg/ps/go-mysql/T3-text-buffered-default.svg) |
| java-connector-j (text-buffered) | 90 |  | 8 | 1 |  |  | 1 |  |  |  |  | 72 |  | 18 | 11 | [svg](../results/profiles/svg/ps/java-connector-j/T3-text-buffered-default.svg) |
| java-mariadb-j (text-buffered) | 57 | 1 | 30 | 0 |  |  | 2 | 6 | 1 | 2 | 1 | 36 |  | 20 | 44 | [svg](../results/profiles/svg/ps/java-mariadb-j/T3-text-buffered-default.svg) |
| node-mariadb (text-buffered) | 22 | 1 | 44 | 25 |  |  | 1 | 4 | 1 | 1 | 1 | 44 |  | 2 | 54 | [svg](../results/profiles/svg/ps/node-mariadb/T3-text-buffered-default.svg) |
| node-mysql2 (text-buffered) | 26 | 1 | 41 | 26 |  |  | 1 | 3 | 1 | 1 | 0 | 44 |  | 9 | 47 | [svg](../results/profiles/svg/ps/node-mysql2/T3-text-buffered-default.svg) |
| php-mysqli (text-buffered) | 34 | 1 | 12 | 46 |  |  | 1 | 4 | 1 |  |  | 48 |  |  | 52 | [svg](../results/profiles/svg/ps/php-mysqli/T3-text-buffered-default.svg) |
| php-pdo-mysql (text-buffered) | 41 | 1 | 6 | 45 |  |  | 1 | 4 | 1 |  |  | 40 |  |  | 60 | [svg](../results/profiles/svg/ps/php-pdo-mysql/T3-text-buffered-default.svg) |
| py-mariadb (text-buffered) | 27 | 3 | 5 | 60 |  |  | 0 | 3 | 1 |  |  | 76 |  | 23 | 1 | [svg](../results/profiles/svg/ps/py-mariadb/T3-text-buffered-default.svg) |
| py-mysql-connector-c (text-buffered) | 21 | 1 | 9 | 66 |  |  |  | 2 | 0 |  |  | 90 |  | 10 |  | [svg](../results/profiles/svg/ps/py-mysql-connector-c/T3-text-buffered-default.svg) |
| py-mysql-connector-pure (text-buffered) | 11 |  | 11 | 59 |  |  | 11 | 1 |  |  | 6 | 97 |  | 2 | 2 | [svg](../results/profiles/svg/ps/py-mysql-connector-pure/T3-text-buffered-default.svg) |
| py-mysqlclient (text-buffered) | 20 | 4 | 8 | 57 |  |  | 1 | 8 | 2 |  |  | 86 |  | 14 |  | [svg](../results/profiles/svg/ps/py-mysqlclient/T3-text-buffered-default.svg) |
| py-pymysql (text-buffered) | 11 | 0 | 8 | 80 |  |  |  | 1 |  |  |  | 97 |  | 3 |  | [svg](../results/profiles/svg/ps/py-pymysql/T3-text-buffered-default.svg) |
| rb-mysql2 (text-buffered) | 62 | 3 | 12 | 20 |  |  | 1 | 0 | 1 |  |  | 91 |  | 9 |  | [svg](../results/profiles/svg/ps/rb-mysql2/T3-text-buffered-default.svg) |
| rb-trilogy (text-buffered) | 59 | 2 | 21 | 15 |  |  | 1 | 2 |  |  |  | 54 |  | 19 | 27 | [svg](../results/profiles/svg/ps/rb-trilogy/T3-text-buffered-default.svg) |
| rust-mysql (text-buffered) | 93 | 2 | 5 |  |  |  | 0 |  |  |  |  | 100 |  |  |  | [svg](../results/profiles/svg/ps/rust-mysql/T3-text-buffered-default.svg) |
| rust-sqlx (text-buffered) | 94 |  | 1 |  |  |  | 0 | 4 | 1 |  |  | 100 |  |  |  | [svg](../results/profiles/svg/ps/rust-sqlx/T3-text-buffered-default.svg) |
| dotnet-dapper (text-buffered) | 94 |  |  | 3 |  |  | 1 | 1 |  |  |  | 68 | 28 | 2 | 2 | [svg](../results/profiles/svg/ps/dotnet-dapper/T3-text-buffered-default.svg) |
| dotnet-efcore (text-buffered) | 95 | 1 |  | 1 |  |  |  | 2 | 1 |  |  | 11 | 63 | 15 | 11 | [svg](../results/profiles/svg/ps/dotnet-efcore/T3-text-buffered-default.svg) |
| go-gorm (text-buffered) | 85 | 2 | 8 |  | 0 |  | 1 | 3 | 1 |  |  | 14 | 85 |  | 1 | [svg](../results/profiles/svg/ps/go-gorm/T3-text-buffered-default.svg) |
| go-sqlx (text-buffered) | 83 | 5 | 7 |  |  |  | 1 | 3 | 1 |  |  | 21 | 78 |  | 1 | [svg](../results/profiles/svg/ps/go-sqlx/T3-text-buffered-default.svg) |
| java-hibernate (text-buffered) | 56 |  | 40 | 4 |  |  |  |  |  |  |  | 24 | 35 | 1 | 41 | [svg](../results/profiles/svg/ps/java-hibernate/T3-text-buffered-default.svg) |
| java-jdbctemplate (text-buffered) | 60 | 0 | 32 | 1 |  |  | 0 | 6 |  |  |  | 50 | 10 |  | 40 | [svg](../results/profiles/svg/ps/java-jdbctemplate/T3-text-buffered-default.svg) |
| java-jooq (text-buffered) | 63 |  | 36 |  |  |  |  |  | 1 |  |  | 49 | 12 | 1 | 38 | [svg](../results/profiles/svg/ps/java-jooq/T3-text-buffered-default.svg) |
| node-drizzle (text-buffered) | 36 | 1 | 29 | 28 |  |  | 1 | 4 | 1 | 1 |  | 29 | 28 | 1 | 42 | [svg](../results/profiles/svg/ps/node-drizzle/T3-text-buffered-default.svg) |
| node-knex (text-buffered) | 24 | 1 | 40 | 28 |  |  | 1 | 4 | 1 |  | 0 | 48 |  | 2 | 50 | [svg](../results/profiles/svg/ps/node-knex/T3-text-buffered-default.svg) |
| node-prisma (text-buffered) | 20 |  | 38 | 39 |  |  |  | 1 | 1 |  |  |  | 58 |  | 42 | [svg](../results/profiles/svg/ps/node-prisma/T3-text-buffered-default.svg) |
| node-sequelize (text-buffered) | 11 |  | 30 | 54 |  |  |  | 1 |  | 1 | 1 | 5 | 54 |  | 41 | [svg](../results/profiles/svg/ps/node-sequelize/T3-text-buffered-default.svg) |
| node-typeorm (text-buffered) | 13 | 0 | 29 | 54 |  |  |  | 2 | 0 |  | 0 | 9 | 59 |  | 32 | [svg](../results/profiles/svg/ps/node-typeorm/T3-text-buffered-default.svg) |
| php-dbal (text-buffered) | 43 | 2 | 21 | 21 |  |  | 1 | 8 | 2 |  |  | 44 |  |  | 56 | [svg](../results/profiles/svg/ps/php-dbal/T3-text-buffered-default.svg) |
| php-doctrine-orm (text-buffered) | 14 | 1 | 20 | 63 |  |  |  | 2 | 0 |  |  | 4 |  |  | 96 | [svg](../results/profiles/svg/ps/php-doctrine-orm/T3-text-buffered-default.svg) |
| php-eloquent (text-buffered) | 12 | 3 | 15 | 70 |  |  |  | 0 |  |  |  | 2 |  |  | 98 | [svg](../results/profiles/svg/ps/php-eloquent/T3-text-buffered-default.svg) |
| py-django-orm (text-buffered) | 16 | 1 | 10 | 70 |  |  |  | 3 | 1 |  |  | 6 | 85 | 8 |  | [svg](../results/profiles/svg/ps/py-django-orm/T3-text-buffered-default.svg) |
| py-sqlalchemy-core (text-buffered) | 22 | 2 | 10 | 60 |  |  | 0 | 5 | 1 |  |  | 44 | 35 | 20 | 2 | [svg](../results/profiles/svg/ps/py-sqlalchemy-core/T3-text-buffered-default.svg) |
| py-sqlalchemy-orm (text-buffered) | 21 | 1 | 6 | 66 |  |  |  | 5 | 1 |  |  | 3 | 92 | 5 |  | [svg](../results/profiles/svg/ps/py-sqlalchemy-orm/T3-text-buffered-default.svg) |
| rb-activerecord (text-buffered) | 57 | 2 | 18 | 20 |  |  |  | 2 | 1 |  |  | 28 | 55 |  | 16 | [svg](../results/profiles/svg/ps/rb-activerecord/T3-text-buffered-default.svg) |
| rb-sequel (text-buffered) | 69 | 3 | 5 | 22 |  |  | 1 | 0 |  |  |  | 89 | 10 | 1 |  | [svg](../results/profiles/svg/ps/rb-sequel/T3-text-buffered-default.svg) |
| rust-diesel (binary-buffered) | 78 | 15 |  |  |  |  | 3 | 3 |  |  |  | 42 | 58 |  |  | [svg](../results/profiles/svg/ps/rust-diesel/T3-binary-buffered-default.svg) |
| rust-seaorm (binary-buffered) | 94 | 0 | 0 |  |  |  |  | 4 | 1 |  |  | 98 | 2 |  |  | [svg](../results/profiles/svg/ps/rust-seaorm/T3-binary-buffered-default.svg) |

## 1M rows, streamed

| stack (variant) | code | copy | alloc+GC | interp/VM | crypto | k:send | k:recv | k:faults | k:mmap | k:wait | k:other | driver | framework | bench | runtime | flame graph |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| c-libmysqlclient (text-streamed) | 84 | 10 |  |  |  |  | 5 |  |  |  | 0 | 86 |  | 13 | 1 | [svg](../results/profiles/svg/ps/c-libmysqlclient/T3-text-streamed-default.svg) |
| c-mariadb-connc (text-streamed) | 91 | 4 |  |  |  |  | 2 |  |  | 1 |  | 70 |  | 28 | 2 | [svg](../results/profiles/svg/ps/c-mariadb-connc/T3-text-streamed-default.svg) |
| cpp-mariadb (text-streamed) | 80 | 4 | 15 |  |  |  | 1 |  |  |  |  | 100 |  |  |  | [svg](../results/profiles/svg/ps/cpp-mariadb/T3-text-streamed-default.svg) |
| cpp-mysql-connector (text-streamed) | 93 | 4 |  |  |  |  | 3 |  |  |  |  | 98 |  |  | 2 | [svg](../results/profiles/svg/ps/cpp-mysql-connector/T3-text-streamed-default.svg) |
| dotnet-mysql-data (text-streamed) | 39 |  |  |  |  |  | 57 |  |  |  | 3 | 36 |  | 63 | 1 | [svg](../results/profiles/svg/ps/dotnet-mysql-data/T3-text-streamed-default.svg) |
| dotnet-mysqlconnector (text-streamed) | 97 |  |  | 2 |  |  | 1 |  |  |  |  | 81 |  | 19 |  | [svg](../results/profiles/svg/ps/dotnet-mysqlconnector/T3-text-streamed-default.svg) |
| go-mysql (text-streamed) | 76 | 21 |  |  |  |  | 1 |  |  | 1 | 1 | 98 |  |  | 2 | [svg](../results/profiles/svg/ps/go-mysql/T3-text-streamed-default.svg) |
| go-sql-driver (text-streamed) | 83 | 1 | 14 |  |  |  | 1 |  |  |  |  | 30 |  | 70 |  | [svg](../results/profiles/svg/ps/go-sql-driver/T3-text-streamed-default.svg) |
| java-connector-j (text-streamed) | 98 |  |  | 1 |  |  | 1 |  |  |  |  | 63 |  | 34 | 3 | [svg](../results/profiles/svg/ps/java-connector-j/T3-text-streamed-default.svg) |
| java-mariadb-j (text-streamed) | 92 |  |  |  |  |  | 4 |  |  | 2 | 1 | 57 |  | 40 | 3 | [svg](../results/profiles/svg/ps/java-mariadb-j/T3-text-streamed-default.svg) |
| node-mariadb (text-streamed) | 49 |  | 1 | 48 |  |  | 1 |  |  |  |  | 37 |  | 39 | 24 | [svg](../results/profiles/svg/ps/node-mariadb/T3-text-streamed-default.svg) |
| node-mysql2 (text-streamed) | 54 |  | 1 | 44 |  |  | 1 |  |  |  | 0 | 62 |  | 27 | 12 | [svg](../results/profiles/svg/ps/node-mysql2/T3-text-streamed-default.svg) |
| php-mysqli (text-streamed) | 37 | 1 | 11 | 50 |  |  |  |  |  |  |  | 44 |  |  | 56 | [svg](../results/profiles/svg/ps/php-mysqli/T3-text-streamed-default.svg) |
| php-pdo-mysql (text-streamed) | 42 | 1 | 7 | 49 |  |  |  |  |  |  |  | 38 |  |  | 62 | [svg](../results/profiles/svg/ps/php-pdo-mysql/T3-text-streamed-default.svg) |
| py-mariadb (text-streamed) | 13 | 1 | 3 | 83 |  |  |  |  |  |  |  | 89 |  | 9 | 2 | [svg](../results/profiles/svg/ps/py-mariadb/T3-text-streamed-default.svg) |
| py-mysql-connector-c (text-streamed) | 16 | 0 | 8 | 75 |  |  |  |  |  |  |  | 93 |  | 7 |  | [svg](../results/profiles/svg/ps/py-mysql-connector-c/T3-text-streamed-default.svg) |
| py-mysql-connector-pure (text-streamed) | 14 | 0 | 9 | 64 |  |  | 8 |  |  |  | 4 | 97 |  | 2 | 1 | [svg](../results/profiles/svg/ps/py-mysql-connector-pure/T3-text-streamed-default.svg) |
| py-mysqlclient (text-streamed) | 32 |  | 6 | 61 |  |  |  |  |  |  |  | 87 |  | 12 |  | [svg](../results/profiles/svg/ps/py-mysqlclient/T3-text-streamed-default.svg) |
| py-pymysql (text-streamed) | 11 |  | 8 | 80 |  |  |  |  |  |  |  | 96 |  | 4 |  | [svg](../results/profiles/svg/ps/py-pymysql/T3-text-streamed-default.svg) |
| rb-mysql2 (text-streamed) | 72 | 1 | 7 | 19 |  |  | 1 |  |  |  |  | 87 |  | 12 |  | [svg](../results/profiles/svg/ps/rb-mysql2/T3-text-streamed-default.svg) |
| rust-mysql (text-streamed) | 89 | 1 | 9 |  |  |  |  |  |  |  |  | 97 |  | 3 |  | [svg](../results/profiles/svg/ps/rust-mysql/T3-text-streamed-default.svg) |
| rust-sqlx (text-streamed) | 99 |  |  |  |  |  |  |  |  |  |  | 99 |  | 1 |  | [svg](../results/profiles/svg/ps/rust-sqlx/T3-text-streamed-default.svg) |
| dotnet-dapper (text-streamed) | 96 |  |  | 4 |  |  | 1 |  |  |  |  | 73 | 21 | 6 |  | [svg](../results/profiles/svg/ps/dotnet-dapper/T3-text-streamed-default.svg) |
| dotnet-efcore (text-streamed) | 95 | 1 |  | 1 |  |  |  | 2 | 1 |  | 0 | 12 | 66 | 12 | 10 | [svg](../results/profiles/svg/ps/dotnet-efcore/T3-text-streamed-default.svg) |
| go-gorm (text-streamed) | 78 | 1 | 20 |  | 1 |  |  |  |  |  |  | 10 | 85 | 5 |  | [svg](../results/profiles/svg/ps/go-gorm/T3-text-streamed-default.svg) |
| go-sqlx (text-streamed) | 88 | 2 | 10 |  |  |  | 1 |  |  |  |  | 28 | 52 | 19 |  | [svg](../results/profiles/svg/ps/go-sqlx/T3-text-streamed-default.svg) |
| java-hibernate (text-streamed) | 45 |  | 52 | 2 |  |  |  | 1 |  |  |  | 15 | 19 |  | 66 | [svg](../results/profiles/svg/ps/java-hibernate/T3-text-streamed-default.svg) |
| java-jdbctemplate (text-streamed) | 98 |  |  | 1 |  |  | 1 |  |  |  |  | 60 | 37 |  | 3 | [svg](../results/profiles/svg/ps/java-jdbctemplate/T3-text-streamed-default.svg) |
| java-jooq (text-streamed) | 99 |  |  |  |  |  | 1 |  |  |  |  | 58 | 40 | 1 | 1 | [svg](../results/profiles/svg/ps/java-jooq/T3-text-streamed-default.svg) |
| node-drizzle (text-streamed) | 22 |  | 22 | 54 |  |  |  | 1 |  |  |  | 10 | 25 | 6 | 60 | [svg](../results/profiles/svg/ps/node-drizzle/T3-text-streamed-default.svg) |
| node-knex (text-streamed) | 60 |  | 1 | 39 |  |  |  |  |  |  |  | 34 |  | 27 | 39 | [svg](../results/profiles/svg/ps/node-knex/T3-text-streamed-default.svg) |
| node-typeorm (text-streamed) | 54 |  | 1 | 43 |  |  | 1 |  |  |  | 1 | 59 |  | 30 | 11 | [svg](../results/profiles/svg/ps/node-typeorm/T3-text-streamed-default.svg) |
| php-dbal (text-streamed) | 52 | 1 | 7 | 39 |  |  |  |  |  |  |  | 42 |  |  | 58 | [svg](../results/profiles/svg/ps/php-dbal/T3-text-streamed-default.svg) |
| php-doctrine-orm (text-streamed) | 13 | 1 | 18 | 67 |  |  |  | 1 |  |  |  | 3 |  |  | 97 | [svg](../results/profiles/svg/ps/php-doctrine-orm/T3-text-streamed-default.svg) |
| php-eloquent (text-streamed) | 20 |  | 10 | 67 |  |  |  | 2 |  |  |  | 16 |  |  | 84 | [svg](../results/profiles/svg/ps/php-eloquent/T3-text-streamed-default.svg) |
| py-django-orm (text-streamed) | 15 | 1 | 13 | 69 |  |  |  | 1 |  |  |  | 8 | 80 | 13 |  | [svg](../results/profiles/svg/ps/py-django-orm/T3-text-streamed-default.svg) |
| py-sqlalchemy-core (text-streamed) | 28 |  | 14 | 57 |  |  |  |  |  |  |  | 19 | 53 | 25 | 3 | [svg](../results/profiles/svg/ps/py-sqlalchemy-core/T3-text-streamed-default.svg) |
| py-sqlalchemy-orm (text-streamed) | 19 |  | 8 | 73 |  |  |  |  |  |  |  | 4 | 88 | 8 |  | [svg](../results/profiles/svg/ps/py-sqlalchemy-orm/T3-text-streamed-default.svg) |
| rb-activerecord (text-streamed) | 60 | 1 | 10 | 28 |  | 0 |  |  |  |  |  | 25 | 65 | 1 | 9 | [svg](../results/profiles/svg/ps/rb-activerecord/T3-text-streamed-default.svg) |
| rb-sequel (text-streamed) | 69 |  | 4 | 25 |  |  | 1 |  |  |  |  | 90 | 9 | 1 | 1 | [svg](../results/profiles/svg/ps/rb-sequel/T3-text-streamed-default.svg) |
| rust-diesel (binary-streamed) | 82 | 11 |  |  |  |  | 3 | 3 |  |  | 1 | 42 | 58 |  |  | [svg](../results/profiles/svg/ps/rust-diesel/T3-binary-streamed-default.svg) |
| rust-seaorm (binary-streamed) | 99 |  |  |  |  |  |  |  |  |  |  | 98 | 2 |  |  | [svg](../results/profiles/svg/ps/rust-seaorm/T3-binary-streamed-default.svg) |

## 10,000 × 100 mixed columns

| stack (variant) | code | copy | alloc+GC | interp/VM | crypto | k:send | k:recv | k:faults | k:mmap | k:wait | k:other | driver | framework | bench | runtime | flame graph |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| c-libmysqlclient (mix-text) | 52 | 15 |  |  |  |  | 16 | 13 | 3 |  | 2 | 74 |  | 24 | 2 | [svg](../results/profiles/svg/ps/c-libmysqlclient/T4-mix-text-default.svg) |
| c-mariadb-connc (mix-text) | 50 | 14 |  |  |  |  | 4 | 22 | 3 | 6 | 2 | 76 |  | 21 | 3 | [svg](../results/profiles/svg/ps/c-mariadb-connc/T4-mix-text-default.svg) |
| cpp-mariadb (mix-text) | 84 | 9 | 3 |  |  |  | 3 |  |  | 1 |  | 97 |  |  | 3 | [svg](../results/profiles/svg/ps/cpp-mariadb/T4-mix-text-default.svg) |
| cpp-mysql-connector (mix-text) | 83 | 8 | 4 |  |  |  | 5 |  |  |  |  | 88 |  |  | 12 | [svg](../results/profiles/svg/ps/cpp-mysql-connector/T4-mix-text-default.svg) |
| dotnet-mysql-data (mix-text) | 86 | 1 |  | 11 |  |  | 1 |  |  |  |  | 92 |  | 6 | 3 | [svg](../results/profiles/svg/ps/dotnet-mysql-data/T4-mix-text-default.svg) |
| dotnet-mysqlconnector (mix-text) | 97 |  |  | 1 |  |  | 1 |  |  |  | 1 | 97 |  | 3 |  | [svg](../results/profiles/svg/ps/dotnet-mysqlconnector/T4-mix-text-default.svg) |
| go-mysql (mix-text) | 78 | 5 |  |  |  |  | 8 |  |  | 7 | 2 | 76 |  | 14 | 10 | [svg](../results/profiles/svg/ps/go-mysql/T4-mix-text-default.svg) |
| go-sql-driver (mix-text) | 71 | 2 | 22 |  |  |  | 4 |  |  |  |  | 54 |  | 45 | 0 | [svg](../results/profiles/svg/ps/go-sql-driver/T4-mix-text-default.svg) |
| java-connector-j (mix-text) | 69 | 1 | 17 | 5 |  |  | 2 | 4 | 0 |  | 1 | 54 |  | 2 | 44 | [svg](../results/profiles/svg/ps/java-connector-j/T4-mix-text-default.svg) |
| java-mariadb-j (mix-text) | 80 | 1 | 2 |  |  |  | 4 | 10 |  | 3 | 1 | 33 |  | 40 | 27 | [svg](../results/profiles/svg/ps/java-mariadb-j/T4-mix-text-default.svg) |
| node-mariadb (mix-text) | 13 | 2 | 20 | 62 |  |  | 1 |  |  |  | 1 | 54 |  | 7 | 39 | [svg](../results/profiles/svg/ps/node-mariadb/T4-mix-text-default.svg) |
| node-mysql2 (mix-text) | 29 | 0 | 25 | 42 |  |  | 1 | 1 |  |  | 1 | 51 |  | 12 | 38 | [svg](../results/profiles/svg/ps/node-mysql2/T4-mix-text-default.svg) |
| php-mysqli (mix-text) | 19 | 3 | 13 | 52 |  |  | 6 | 4 | 1 | 2 | 1 | 46 |  |  | 54 | [svg](../results/profiles/svg/ps/php-mysqli/T4-mix-text-default.svg) |
| php-pdo-mysql (mix-text) | 28 | 1 | 7 | 55 |  |  | 3 | 3 | 0 | 2 |  | 32 |  |  | 68 | [svg](../results/profiles/svg/ps/php-pdo-mysql/T4-mix-text-default.svg) |
| py-mariadb (mix-text) | 61 | 2 | 7 | 26 |  |  | 2 | 1 |  | 1 |  | 72 |  | 26 | 2 | [svg](../results/profiles/svg/ps/py-mariadb/T4-mix-text-default.svg) |
| py-mysql-connector-c (mix-text) | 37 |  | 9 | 50 |  |  | 1 | 2 | 1 |  |  | 80 |  | 20 |  | [svg](../results/profiles/svg/ps/py-mysql-connector-c/T4-mix-text-default.svg) |
| py-mysql-connector-pure (mix-text) | 14 | 1 | 10 | 68 |  |  | 1 | 3 | 1 |  | 1 | 92 |  | 8 |  | [svg](../results/profiles/svg/ps/py-mysql-connector-pure/T4-mix-text-default.svg) |
| py-mysqlclient (mix-text) | 22 | 2 | 12 | 57 |  |  | 2 | 4 | 1 |  |  | 82 |  | 18 |  | [svg](../results/profiles/svg/ps/py-mysqlclient/T4-mix-text-default.svg) |
| py-pymysql (mix-text) | 14 | 1 | 11 | 72 |  |  |  | 1 |  |  |  | 93 |  | 7 |  | [svg](../results/profiles/svg/ps/py-pymysql/T4-mix-text-default.svg) |
| rb-mysql2 (mix-text) | 61 | 2 | 12 | 24 |  |  | 1 |  |  |  |  | 83 |  | 17 |  | [svg](../results/profiles/svg/ps/rb-mysql2/T4-mix-text-default.svg) |
| rb-trilogy (mix-text) | 52 | 1 | 22 | 24 |  |  | 1 |  |  |  |  | 42 |  | 22 | 36 | [svg](../results/profiles/svg/ps/rb-trilogy/T4-mix-text-default.svg) |
| rust-mysql (mix-text) | 61 | 5 | 30 |  |  |  | 4 |  |  |  |  | 88 |  | 12 |  | [svg](../results/profiles/svg/ps/rust-mysql/T4-mix-text-default.svg) |
| rust-sqlx (mix-text) | 92 | 0 | 2 |  |  |  | 4 |  |  | 1 | 0 | 96 |  | 4 |  | [svg](../results/profiles/svg/ps/rust-sqlx/T4-mix-text-default.svg) |
| dotnet-dapper (mix-text) | 91 | 1 |  | 6 |  |  |  | 1 |  |  | 0 | 79 | 1 | 14 | 6 | [svg](../results/profiles/svg/ps/dotnet-dapper/T4-mix-text-default.svg) |
| dotnet-efcore (mix-text) | 91 |  |  | 6 |  |  | 0 | 1 | 1 |  |  | 38 | 33 | 13 | 16 | [svg](../results/profiles/svg/ps/dotnet-efcore/T4-mix-text-default.svg) |
| go-gorm (mix-text) | 69 | 3 | 20 |  |  |  | 1 | 5 | 1 |  |  | 17 | 71 | 7 | 5 | [svg](../results/profiles/svg/ps/go-gorm/T4-mix-text-default.svg) |
| go-sqlx (mix-text) | 62 | 4 | 23 |  |  |  | 3 | 7 | 2 |  | 0 | 32 | 49 | 15 | 5 | [svg](../results/profiles/svg/ps/go-sqlx/T4-mix-text-default.svg) |
| java-hibernate (mix-text) | 54 | 1 | 37 |  |  |  | 1 | 6 |  |  | 1 | 41 | 6 | 3 | 49 | [svg](../results/profiles/svg/ps/java-hibernate/T4-mix-text-default.svg) |
| java-jdbctemplate (mix-text) | 72 | 1 | 13 | 6 |  |  | 3 | 4 |  |  | 1 | 63 |  | 5 | 32 | [svg](../results/profiles/svg/ps/java-jdbctemplate/T4-mix-text-default.svg) |
| java-jooq (mix-text) | 65 | 1 | 27 |  |  |  | 1 | 4 |  |  | 1 | 44 | 14 | 2 | 40 | [svg](../results/profiles/svg/ps/java-jooq/T4-mix-text-default.svg) |
| node-drizzle (mix-text) | 21 |  | 16 | 61 |  |  | 1 |  |  |  | 1 | 22 | 26 | 10 | 42 | [svg](../results/profiles/svg/ps/node-drizzle/T4-mix-text-default.svg) |
| node-knex (mix-text) | 29 |  | 26 | 41 |  |  | 2 | 1 |  |  | 1 | 57 |  | 10 | 33 | [svg](../results/profiles/svg/ps/node-knex/T4-mix-text-default.svg) |
| node-prisma (mix-text) | 16 | 2 | 26 | 56 |  |  |  |  |  |  |  |  | 63 | 2 | 35 | [svg](../results/profiles/svg/ps/node-prisma/T4-mix-text-default.svg) |
| node-sequelize (mix-text) | 14 |  | 16 | 69 |  |  | 0 |  |  |  |  | 13 | 58 |  | 29 | [svg](../results/profiles/svg/ps/node-sequelize/T4-mix-text-default.svg) |
| node-typeorm (mix-text) | 24 | 1 | 28 | 44 |  |  | 1 | 1 |  |  |  | 29 | 29 | 4 | 38 | [svg](../results/profiles/svg/ps/node-typeorm/T4-mix-text-default.svg) |
| php-dbal (mix-text) | 21 | 0 | 12 | 56 |  |  | 2 | 6 | 2 | 0 |  | 19 |  |  | 81 | [svg](../results/profiles/svg/ps/php-dbal/T4-mix-text-default.svg) |
| php-doctrine-orm (mix-text) | 18 | 4 | 12 | 64 |  |  |  |  |  |  |  | 4 |  |  | 96 | [svg](../results/profiles/svg/ps/php-doctrine-orm/T4-mix-text-default.svg) |
| php-eloquent (mix-text) | 10 | 2 | 7 | 80 |  |  |  |  |  |  |  | 5 |  |  | 95 | [svg](../results/profiles/svg/ps/php-eloquent/T4-mix-text-default.svg) |
| py-django-orm (mix-text) | 28 | 2 | 9 | 58 |  |  | 1 | 2 |  |  |  | 42 | 32 | 26 |  | [svg](../results/profiles/svg/ps/py-django-orm/T4-mix-text-default.svg) |
| py-sqlalchemy-core (mix-text) | 26 | 2 | 11 | 56 |  |  | 1 | 3 | 1 |  |  | 78 | 4 | 17 | 2 | [svg](../results/profiles/svg/ps/py-sqlalchemy-core/T4-mix-text-default.svg) |
| py-sqlalchemy-orm (mix-text) | 25 | 1 | 7 | 64 |  |  | 1 | 1 | 0 |  |  | 33 | 42 | 24 | 1 | [svg](../results/profiles/svg/ps/py-sqlalchemy-orm/T4-mix-text-default.svg) |
| rb-activerecord (mix-text) | 51 | 2 | 11 | 36 |  |  | 0 |  |  |  |  | 27 | 52 | 8 | 13 | [svg](../results/profiles/svg/ps/rb-activerecord/T4-mix-text-default.svg) |
| rb-sequel (mix-text) | 49 | 2 | 12 | 36 |  |  | 1 | 1 |  |  |  | 65 | 5 | 9 | 21 | [svg](../results/profiles/svg/ps/rb-sequel/T4-mix-text-default.svg) |
| rust-diesel (mix-binary) | 71 | 9 | 10 |  |  |  | 6 | 4 |  |  |  | 23 | 70 | 7 |  | [svg](../results/profiles/svg/ps/rust-diesel/T4-mix-binary-default.svg) |
| rust-seaorm (mix-binary) | 74 | 14 | 10 |  |  |  | 1 |  |  |  |  | 92 | 6 | 2 |  | [svg](../results/profiles/svg/ps/rust-seaorm/T4-mix-binary-default.svg) |

## 1,000 × 10 KB JSON documents

| stack (variant) | code | copy | alloc+GC | interp/VM | crypto | k:send | k:recv | k:faults | k:mmap | k:wait | k:other | driver | framework | bench | runtime | flame graph |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| c-libmysqlclient (10k-doc) | 14 | 8 |  |  |  |  | 37 | 32 | 5 |  | 4 | 95 |  | 5 |  | [svg](../results/profiles/svg/ps/c-libmysqlclient/T5-10k-doc-default.svg) |
| c-mariadb-connc (10k-doc) | 15 | 8 | 0 |  |  |  | 13 | 36 | 7 | 16 | 6 | 96 |  | 3 | 1 | [svg](../results/profiles/svg/ps/c-mariadb-connc/T5-10k-doc-default.svg) |
| cpp-mariadb (10k-doc) | 13 | 11 | 1 |  |  |  | 13 | 36 | 6 | 17 | 5 | 97 |  |  | 3 | [svg](../results/profiles/svg/ps/cpp-mariadb/T5-10k-doc-default.svg) |
| cpp-mysql-connector (10k-doc) | 11 | 15 | 0 |  |  |  | 36 | 27 | 5 |  | 5 | 93 |  |  | 7 | [svg](../results/profiles/svg/ps/cpp-mysql-connector/T5-10k-doc-default.svg) |
| dotnet-mysql-data (10k-doc) | 23 | 2 |  | 1 |  |  | 4 |  |  | 45 | 25 | 27 |  | 2 | 71 | [svg](../results/profiles/svg/ps/dotnet-mysql-data/T5-10k-doc-default.svg) |
| dotnet-mysqlconnector (10k-doc) | 54 | 6 |  | 4 |  |  | 13 |  |  | 19 | 3 | 70 |  | 30 |  | [svg](../results/profiles/svg/ps/dotnet-mysqlconnector/T5-10k-doc-default.svg) |
| go-mysql (10k-doc) | 28 | 20 |  |  |  |  | 12 |  |  | 36 | 5 | 51 |  | 6 | 43 | [svg](../results/profiles/svg/ps/go-mysql/T5-10k-doc-default.svg) |
| go-sql-driver (10k-doc) | 47 | 2 | 11 |  |  |  | 13 |  |  | 23 | 3 | 27 |  | 15 | 58 | [svg](../results/profiles/svg/ps/go-sql-driver/T5-10k-doc-default.svg) |
| java-connector-j (10k-doc) | 50 | 3 | 4 | 2 |  |  | 24 | 10 | 1 |  | 6 | 67 |  | 4 | 29 | [svg](../results/profiles/svg/ps/java-connector-j/T5-10k-doc-default.svg) |
| java-mariadb-j (10k-doc) | 34 | 1 | 3 | 1 |  |  | 21 | 23 |  | 14 | 3 | 63 |  | 24 | 14 | [svg](../results/profiles/svg/ps/java-mariadb-j/T5-10k-doc-default.svg) |
| node-mariadb (10k-doc) | 15 | 15 | 10 | 33 |  |  | 13 | 0 |  | 11 | 2 | 24 |  | 9 | 67 | [svg](../results/profiles/svg/ps/node-mariadb/T5-10k-doc-default.svg) |
| node-mysql2 (10k-doc) | 15 | 15 | 9 | 33 |  |  | 13 | 1 |  | 12 | 2 | 26 |  | 9 | 65 | [svg](../results/profiles/svg/ps/node-mysql2/T5-10k-doc-default.svg) |
| php-mysqli (10k-doc) | 5 | 4 | 2 | 39 |  |  | 12 | 22 | 4 | 10 | 2 | 60 |  |  | 40 | [svg](../results/profiles/svg/ps/php-mysqli/T5-10k-doc-default.svg) |
| php-pdo-mysql (10k-doc) | 6 | 4 | 3 | 39 |  |  | 12 | 19 | 4 | 10 | 3 | 58 |  |  | 42 | [svg](../results/profiles/svg/ps/php-pdo-mysql/T5-10k-doc-default.svg) |
| py-mariadb (10k-doc) | 16 | 12 | 2 | 14 |  |  | 10 | 20 | 6 | 16 | 5 | 78 |  | 22 | 1 | [svg](../results/profiles/svg/ps/py-mariadb/T5-10k-doc-default.svg) |
| py-mysql-connector-c (10k-doc) | 17 | 4 | 3 | 42 |  |  | 15 | 14 | 3 |  | 2 | 71 |  | 29 |  | [svg](../results/profiles/svg/ps/py-mysql-connector-c/T5-10k-doc-default.svg) |
| py-mysql-connector-pure (10k-doc) | 16 | 6 | 8 | 54 |  |  | 12 | 2 | 0 |  | 3 | 83 |  | 17 |  | [svg](../results/profiles/svg/ps/py-mysql-connector-pure/T5-10k-doc-default.svg) |
| py-mysqlclient (10k-doc) | 20 | 9 | 2 | 27 |  |  | 17 | 16 | 5 |  | 4 | 65 |  | 35 |  | [svg](../results/profiles/svg/ps/py-mysqlclient/T5-10k-doc-default.svg) |
| py-pymysql (10k-doc) | 17 | 6 | 6 | 48 |  |  | 22 |  |  |  | 1 | 76 |  | 24 |  | [svg](../results/profiles/svg/ps/py-pymysql/T5-10k-doc-default.svg) |
| rb-mysql2 (10k-doc) | 35 | 7 | 10 | 30 |  |  | 16 |  |  |  | 1 | 36 |  | 64 |  | [svg](../results/profiles/svg/ps/rb-mysql2/T5-10k-doc-default.svg) |
| rb-trilogy (10k-doc) | 49 | 6 | 6 | 18 |  |  | 10 |  |  | 10 | 2 | 37 |  | 63 |  | [svg](../results/profiles/svg/ps/rb-trilogy/T5-10k-doc-default.svg) |
| rust-mysql (10k-doc) | 12 | 8 | 2 |  |  |  | 28 | 41 | 7 |  | 2 | 90 |  | 10 |  | [svg](../results/profiles/svg/ps/rust-mysql/T5-10k-doc-default.svg) |
| rust-sqlx (10k-doc) | 23 | 6 | 2 |  |  |  | 12 | 34 | 5 | 15 | 3 | 76 |  | 23 | 1 | [svg](../results/profiles/svg/ps/rust-sqlx/T5-10k-doc-default.svg) |
| dotnet-dapper (10k-doc) | 46 | 7 |  |  |  |  | 9 | 17 | 7 | 11 | 3 | 7 | 7 | 77 | 10 | [svg](../results/profiles/svg/ps/dotnet-dapper/T5-10k-doc-default.svg) |
| dotnet-efcore (10k-doc) | 56 | 5 |  | 3 |  |  | 6 | 14 | 7 | 6 | 2 | 66 | 4 | 16 | 15 | [svg](../results/profiles/svg/ps/dotnet-efcore/T5-10k-doc-default.svg) |
| go-gorm (10k-doc) | 38 | 4 | 8 |  |  |  | 12 | 12 | 3 | 20 | 3 | 22 | 30 | 3 | 45 | [svg](../results/profiles/svg/ps/go-gorm/T5-10k-doc-default.svg) |
| go-sqlx (10k-doc) | 37 | 4 | 6 |  |  |  | 11 | 13 | 4 | 21 | 4 | 19 | 28 | 3 | 49 | [svg](../results/profiles/svg/ps/go-sqlx/T5-10k-doc-default.svg) |
| java-hibernate (10k-doc) | 60 | 1 |  | 5 |  |  | 25 |  |  |  | 8 | 76 | 7 | 6 | 11 | [svg](../results/profiles/svg/ps/java-hibernate/T5-10k-doc-default.svg) |
| java-jdbctemplate (10k-doc) | 45 | 3 | 5 | 2 |  |  | 19 | 17 | 1 | 0 | 6 | 59 | 3 | 4 | 33 | [svg](../results/profiles/svg/ps/java-jdbctemplate/T5-10k-doc-default.svg) |
| java-jooq (10k-doc) | 52 | 3 | 6 | 4 |  |  | 18 | 10 | 1 |  | 6 | 53 | 7 | 5 | 36 | [svg](../results/profiles/svg/ps/java-jooq/T5-10k-doc-default.svg) |
| node-drizzle (10k-doc) | 18 | 15 | 9 | 33 |  |  | 11 |  |  | 12 | 2 | 26 | 4 | 8 | 62 | [svg](../results/profiles/svg/ps/node-drizzle/T5-10k-doc-default.svg) |
| node-knex (10k-doc) | 18 | 17 | 11 | 32 |  |  | 7 |  |  | 12 | 2 | 28 | 1 | 10 | 60 | [svg](../results/profiles/svg/ps/node-knex/T5-10k-doc-default.svg) |
| node-prisma (10k-doc) | 15 | 17 | 12 | 35 |  | 0 | 10 |  |  | 8 | 1 |  | 24 |  | 76 | [svg](../results/profiles/svg/ps/node-prisma/T5-10k-doc-default.svg) |
| node-sequelize (10k-doc) | 17 | 12 | 9 | 39 |  |  | 9 | 1 |  | 11 | 2 | 21 | 13 | 9 | 57 | [svg](../results/profiles/svg/ps/node-sequelize/T5-10k-doc-default.svg) |
| node-typeorm (10k-doc) | 17 | 16 | 9 | 35 |  |  | 8 |  |  | 13 | 2 | 28 | 2 | 9 | 61 | [svg](../results/profiles/svg/ps/node-typeorm/T5-10k-doc-default.svg) |
| php-dbal (10k-doc) | 5 | 4 | 2 | 31 |  |  | 11 | 30 | 6 | 8 | 3 | 61 |  |  | 39 | [svg](../results/profiles/svg/ps/php-dbal/T5-10k-doc-default.svg) |
| php-doctrine-orm (10k-doc) | 6 | 5 | 2 | 32 |  |  | 10 | 29 | 5 | 8 | 2 | 60 |  |  | 40 | [svg](../results/profiles/svg/ps/php-doctrine-orm/T5-10k-doc-default.svg) |
| php-eloquent (10k-doc) | 5 | 6 | 2 | 39 |  |  | 12 | 21 | 4 | 9 | 2 | 55 |  |  | 45 | [svg](../results/profiles/svg/ps/php-eloquent/T5-10k-doc-default.svg) |
| py-django-orm (10k-doc) | 20 | 8 | 5 | 45 |  |  | 15 | 4 | 1 |  | 2 | 42 | 32 | 26 |  | [svg](../results/profiles/svg/ps/py-django-orm/T5-10k-doc-default.svg) |
| py-sqlalchemy-core (10k-doc) | 20 | 7 | 3 | 30 |  |  | 16 | 17 | 4 |  | 3 | 60 | 5 | 34 |  | [svg](../results/profiles/svg/ps/py-sqlalchemy-core/T5-10k-doc-default.svg) |
| py-sqlalchemy-orm (10k-doc) | 21 | 13 | 4 | 35 |  |  | 20 | 4 | 1 |  | 2 | 54 | 26 | 20 |  | [svg](../results/profiles/svg/ps/py-sqlalchemy-orm/T5-10k-doc-default.svg) |
| rb-activerecord (10k-doc) | 40 | 12 | 8 | 19 |  |  | 19 |  |  |  | 2 | 48 | 9 | 43 |  | [svg](../results/profiles/svg/ps/rb-activerecord/T5-10k-doc-default.svg) |
| rb-sequel (10k-doc) | 29 | 15 | 8 | 25 |  |  | 20 |  |  |  | 2 | 55 | 1 | 43 | 1 | [svg](../results/profiles/svg/ps/rb-sequel/T5-10k-doc-default.svg) |
| rust-diesel (10k-doc) | 22 | 32 | 7 |  |  |  | 35 |  |  |  | 4 | 69 | 28 | 3 |  | [svg](../results/profiles/svg/ps/rust-diesel/T5-10k-doc-default.svg) |

## Bulk insert, 1M rows

| stack (variant) | code | copy | alloc+GC | interp/VM | crypto | k:send | k:recv | k:faults | k:mmap | k:wait | k:other | driver | framework | bench | runtime | flame graph |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| c-libmysqlclient (multiparam) | 70 | 16 | 5 |  |  | 6 | 2 |  |  |  |  | 57 |  | 39 | 4 | [svg](../results/profiles/svg/ps/c-libmysqlclient/T6-multiparam-default.svg) |
| c-mariadb-connc (multiparam) | 70 | 17 |  |  |  | 11 |  |  |  | 1 | 1 | 47 |  | 48 | 6 | [svg](../results/profiles/svg/ps/c-mariadb-connc/T6-multiparam-default.svg) |
| cpp-mariadb (multiparam) | 78 | 16 | 5 |  |  | 1 |  |  |  |  |  | 96 |  |  | 4 | [svg](../results/profiles/svg/ps/cpp-mariadb/T6-multiparam-default.svg) |
| cpp-mysql-connector (multiparam) | 60 | 15 | 21 |  |  | 3 | 1 |  |  |  |  | 67 |  |  | 33 | [svg](../results/profiles/svg/ps/cpp-mysql-connector/T6-multiparam-default.svg) |
| dotnet-mysql-data (multiparam) | 74 | 10 |  | 3 |  | 1 |  |  |  | 7 | 5 | 83 |  | 5 | 12 | [svg](../results/profiles/svg/ps/dotnet-mysql-data/T6-multiparam-default.svg) |
| dotnet-mysqlconnector (multiparam) | 87 | 9 |  | 2 |  | 1 |  |  |  |  |  | 89 |  | 10 | 1 | [svg](../results/profiles/svg/ps/dotnet-mysqlconnector/T6-multiparam-default.svg) |
| go-mysql (multiparam) | 54 | 6 | 36 |  |  | 2 |  |  |  | 2 |  | 61 |  | 20 | 19 | [svg](../results/profiles/svg/ps/go-mysql/T6-multiparam-default.svg) |
| go-sql-driver (multiparam) | 67 | 2 | 22 |  |  | 2 | 2 |  |  | 4 | 1 | 50 |  | 30 | 20 | [svg](../results/profiles/svg/ps/go-sql-driver/T6-multiparam-default.svg) |
| java-connector-j (multiparam) | 94 |  | 2 |  |  | 2 | 1 |  |  |  | 1 | 90 |  |  | 9 | [svg](../results/profiles/svg/ps/java-connector-j/T6-multiparam-default.svg) |
| java-mariadb-j (multiparam) | 93 |  | 1 |  |  | 4 |  |  |  | 1 |  | 72 |  | 20 | 8 | [svg](../results/profiles/svg/ps/java-mariadb-j/T6-multiparam-default.svg) |
| node-mariadb (multiparam) | 35 |  | 4 | 56 |  | 2 |  |  |  | 1 | 1 | 19 |  | 44 | 37 | [svg](../results/profiles/svg/ps/node-mariadb/T6-multiparam-default.svg) |
| node-mysql2 (multiparam) | 29 |  | 4 | 63 |  | 2 |  | 1 |  | 1 | 0 | 21 |  | 56 | 23 | [svg](../results/profiles/svg/ps/node-mysql2/T6-multiparam-default.svg) |
| php-mysqli (multiparam) | 20 | 19 | 11 | 47 |  | 2 |  |  |  |  |  | 72 |  |  | 28 | [svg](../results/profiles/svg/ps/php-mysqli/T6-multiparam-default.svg) |
| php-pdo-mysql (multiparam) | 24 | 14 | 24 | 36 |  | 1 |  |  |  |  |  | 18 |  |  | 82 | [svg](../results/profiles/svg/ps/php-pdo-mysql/T6-multiparam-default.svg) |
| py-mariadb (multiparam) | 38 | 4 | 9 | 40 |  | 1 |  | 6 | 1 |  |  | 86 |  | 11 | 3 | [svg](../results/profiles/svg/ps/py-mariadb/T6-multiparam-default.svg) |
| py-mysql-connector-c (multiparam) | 26 | 2 | 18 | 54 |  | 1 |  |  |  |  |  | 88 |  | 12 |  | [svg](../results/profiles/svg/ps/py-mysql-connector-c/T6-multiparam-default.svg) |
| py-mysql-connector-pure (multiparam) | 18 | 1 | 9 | 71 |  |  |  |  |  |  |  | 96 |  | 4 |  | [svg](../results/profiles/svg/ps/py-mysql-connector-pure/T6-multiparam-default.svg) |
| py-mysqlclient (multiparam) | 25 | 1 | 7 | 66 |  |  |  |  |  |  |  | 92 |  | 8 |  | [svg](../results/profiles/svg/ps/py-mysqlclient/T6-multiparam-default.svg) |
| py-pymysql (multiparam) | 18 | 1 | 6 | 74 |  |  |  |  |  |  |  | 92 |  | 8 |  | [svg](../results/profiles/svg/ps/py-pymysql/T6-multiparam-default.svg) |
| rb-mysql2 (multiparam) | 28 | 11 | 45 | 14 |  | 2 | 0 |  |  |  |  | 54 |  | 26 | 20 | [svg](../results/profiles/svg/ps/rb-mysql2/T6-multiparam-default.svg) |
| rust-mysql (multiparam) | 70 | 7 | 16 |  |  | 5 | 1 |  |  |  | 1 | 100 |  |  |  | [svg](../results/profiles/svg/ps/rust-mysql/T6-multiparam-default.svg) |
| rust-sqlx (multiparam) | 78 | 10 | 7 |  |  | 3 | 0 |  |  | 1 |  | 69 |  | 31 |  | [svg](../results/profiles/svg/ps/rust-sqlx/T6-multiparam-default.svg) |
| dotnet-dapper (batch) | 34 | 1 |  | 1 |  | 40 | 5 |  |  | 16 | 3 | 73 | 2 | 25 | 0 | [svg](../results/profiles/svg/ps/dotnet-dapper/T6-batch-default.svg) |
| dotnet-efcore (batch) | 89 | 3 |  | 2 |  | 2 | 2 |  |  | 1 | 1 | 18 | 77 | 5 |  | [svg](../results/profiles/svg/ps/dotnet-efcore/T6-batch-default.svg) |
| go-gorm (batch) | 72 | 2 | 16 |  |  | 2 | 1 |  |  | 3 | 2 | 26 | 47 | 5 | 21 | [svg](../results/profiles/svg/ps/go-gorm/T6-batch-default.svg) |
| go-sqlx (batch) | 72 | 3 | 16 |  |  | 2 | 1 | 1 |  | 3 | 1 | 31 | 42 | 6 | 21 | [svg](../results/profiles/svg/ps/go-sqlx/T6-batch-default.svg) |
| java-hibernate (batch) | 51 |  | 0 |  |  | 28 | 14 |  |  |  | 6 | 88 | 10 |  | 2 | [svg](../results/profiles/svg/ps/java-hibernate/T6-batch-default.svg) |
| java-jdbctemplate (multiparam) | 96 |  | 1 | 2 |  | 1 |  |  |  |  |  | 74 | 18 | 3 | 6 | [svg](../results/profiles/svg/ps/java-jdbctemplate/T6-multiparam-default.svg) |
| java-jooq (multiparam) | 95 |  | 2 | 1 |  | 1 |  |  |  |  |  | 42 | 52 | 2 | 5 | [svg](../results/profiles/svg/ps/java-jooq/T6-multiparam-default.svg) |
| node-drizzle (batch) | 15 | 0 | 14 | 70 |  |  |  |  |  |  |  |  | 72 | 2 | 26 | [svg](../results/profiles/svg/ps/node-drizzle/T6-batch-default.svg) |
| node-knex (batch) | 29 |  | 4 | 63 |  | 2 |  |  |  | 1 | 0 | 19 | 35 | 33 | 13 | [svg](../results/profiles/svg/ps/node-knex/T6-batch-default.svg) |
| node-prisma (batch) | 49 | 1 | 6 | 43 |  |  |  |  |  |  |  |  | 91 |  | 8 | [svg](../results/profiles/svg/ps/node-prisma/T6-batch-default.svg) |
| node-sequelize (batch) | 20 |  | 4 | 75 |  |  |  |  |  |  |  |  | 87 | 5 | 8 | [svg](../results/profiles/svg/ps/node-sequelize/T6-batch-default.svg) |
| node-typeorm (batch) | 16 |  | 6 | 76 |  | 0 |  |  |  |  |  | 1 | 83 | 3 | 13 | [svg](../results/profiles/svg/ps/node-typeorm/T6-batch-default.svg) |
| php-dbal (multiparam) | 19 | 7 | 17 | 56 |  | 1 |  |  |  |  |  | 10 |  |  | 90 | [svg](../results/profiles/svg/ps/php-dbal/T6-multiparam-default.svg) |
| php-doctrine-orm (batch) | 12 | 0 | 6 | 47 |  | 21 | 2 |  |  | 9 | 2 | 41 |  |  | 59 | [svg](../results/profiles/svg/ps/php-doctrine-orm/T6-batch-default.svg) |
| php-eloquent (batch) | 18 | 4 | 10 | 67 |  | 1 |  |  |  |  |  | 17 |  |  | 83 | [svg](../results/profiles/svg/ps/php-eloquent/T6-batch-default.svg) |
| py-django-orm (batch) | 17 | 1 | 7 | 74 |  |  |  |  |  |  |  | 20 | 74 | 6 |  | [svg](../results/profiles/svg/ps/py-django-orm/T6-batch-default.svg) |
| py-sqlalchemy-core (multiparam) | 20 | 1 | 8 | 71 |  |  |  |  |  |  |  | 8 | 91 | 2 |  | [svg](../results/profiles/svg/ps/py-sqlalchemy-core/T6-multiparam-default.svg) |
| py-sqlalchemy-orm (batch) | 18 | 1 | 6 | 75 |  |  |  |  |  |  |  | 14 | 82 | 4 |  | [svg](../results/profiles/svg/ps/py-sqlalchemy-orm/T6-batch-default.svg) |
| rb-activerecord (batch) | 46 | 1 | 8 | 31 |  | 9 | 1 |  |  | 3 | 1 | 20 | 77 | 3 |  | [svg](../results/profiles/svg/ps/rb-activerecord/T6-batch-default.svg) |
| rb-sequel (batch) | 34 | 1 | 14 | 25 |  | 17 | 2 |  |  | 6 | 1 | 52 | 41 | 1 | 7 | [svg](../results/profiles/svg/ps/rb-sequel/T6-batch-default.svg) |
| rust-diesel (batch) | 56 | 4 | 38 |  |  | 1 | 1 |  |  |  |  | 75 | 22 | 3 |  | [svg](../results/profiles/svg/ps/rust-diesel/T6-batch-default.svg) |
| rust-seaorm (batch) | 78 | 3 | 14 |  |  | 3 |  |  |  | 1 |  | 12 | 74 | 14 |  | [svg](../results/profiles/svg/ps/rust-seaorm/T6-batch-default.svg) |

