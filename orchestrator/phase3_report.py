# Phase 3 report (frameworks). Executed by build_reports.py, which provides cpu(), mb(), tables(), tuned_section(),
# DISCLOSURE, COMMON, STEADY, SUM. Numbers in the prose are looked up from the data.
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("fwtax", "orchestrator/fwtax.py"); fwtax = _ilu.module_from_spec(_spec); _spec.loader.exec_module(fwtax)
_tax = fwtax.compute(fwtax.load(SUM), "ps")


def tax(fw, test, config="default"):
    """framework / driver CPU ratio on Percona for the headline variant of a test."""
    r = next((r for r in _tax if r["framework"] == fw and r["test"] == test and r["config"] == config
              and (test != "T3" or "buffered" in r["variant"])), None)
    return f"{r['ratio']:.1f}×" if r and r["ratio"] else "n/a"


def ratio(fw, test, variant, config="default"):
    r = next((r for r in _tax if r["framework"] == fw and r["test"] == test and r["variant"] == variant and r["config"] == config), None)
    return f"{r['ratio']:.1f}×" if r and r["ratio"] else "n/a"


_ENT = ["php-eloquent", "php-doctrine-orm", "py-sqlalchemy-orm", "node-sequelize", "java-hibernate", "node-prisma"]
_er = [r["ratio"] for r in _tax if r["framework"] in _ENT and r["test"] == "T3" and r["variant"] == "text-buffered" and r["config"] == "default"]
ENT_RANGE = f"{min(_er):.0f}–{max(_er):.0f}×"


def tax_tables():
    out = []
    for test, variants in fwtax.HEAD:
        sub = [r for r in _tax if r["test"] == test and r["variant"] in variants]
        if not sub:
            continue
        label = {"T2": "Point select (parameterized)", "T3": "1M rows, " + ("buffered" if "buffered" in variants[0] else "streamed"),
                 "T4": "10,000 × 100 mixed-type columns", "T5": "1,000 × 10 KB BLOBs", "T6": "Bulk insert, 1M rows"}[test]
        out.append(f"\n### {label} — {fwtax.UNIT[test]}, Percona\n")
        out.append("| framework | default | tuned | driver baseline (variant) | default ÷ driver | tuned ÷ driver |\n|---|---:|---:|---|---:|---:|")
        for fw in fwtax.BASE:
            d = next((r for r in sub if r["framework"] == fw and r["config"] == "default"), None)
            t = next((r for r in sub if r["framework"] == fw and r["config"] == "tuned"), None)
            if not d and not t:
                continue
            ref = d or t
            f = lambda v: "–" if v is None else (f"{v:,.0f}" if v >= 100 else f"{v:.3g}")
            x = lambda r: "–" if not r or r["ratio"] is None else f"{r['ratio']:.1f}×"
            out.append(f"| {fw} ({ref['variant']}) | {f(d['fw']) if d else '–'} | {f(t['fw']) if t else '–'} | "
                       f"{fwtax.BASE[fw]} ({ref['base_variant'] or '–'}) {f(ref['base'])} | {x(d)} | {x(t)} |")
    return "\n".join(out) + "\n"


FW = ",".join(fwtax.BASE)
P3_FW_LIST = """| language | frameworks | on driver |
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
"""

p3 = f"""# Phase 3 report — frameworks, ORMs and query builders

{DISCLOSURE}
Run: 2026-11-22 → 2026-11-26, same host, servers and method as [Phase 1](phase1.md) and [Phase 2](phase2.md); JIT cells
were rerun on 2026-11-26 with the plateau check described below. 22 frameworks in eight languages, each measured on the
same tests as the drivers, in two configurations: **default** (the framework's usual idiom: entities/models, its query
builder) and **tuned** (the framework's own lighter API: scalar/array results, streaming, bulk insert — listed exactly
below). Tests that a framework does not change (connects go through the driver) are not repeated here.

{P3_FW_LIST}
{COMMON}
**Framework tax** = framework CPU ÷ CPU of the driver it runs on, same server, test and configuration. The driver
baseline is the driver's result for the same variant; for point selects where the driver has no such variant, the
protocol the framework uses (Ruby frameworks: escaped literal SQL; Diesel and SeaORM: prepared statements). For bulk
insert the baseline is the driver's single 1,000-row `INSERT … VALUES (?,?,?,?),…` with bound parameters.

{STEADY}## Key findings (Percona; MariaDB is similar, see the tables)

**Point selects: thin layers are nearly free, ORMs are not**
- Dapper {cpu('dotnet-dapper','T2','param')} µs vs MySqlConnector {cpu('dotnet-mysqlconnector','T2','param')} µs
  ({tax('dotnet-dapper','T2')}); go-sqlx {tax('go-sqlx','T2')}; Diesel {cpu('rust-diesel','T2','param')} µs vs
  libmysqlclient prepared {cpu('c-libmysqlclient','T2','prepared')} µs; Hibernate with StatelessSession
  {cpu('java-hibernate','T2','param',config='tuned')} µs vs Connector/J {cpu('java-connector-j','T2','param')} µs.
- **Python ORMs are the most expensive per query:** Django {cpu('py-django-orm','T2','param')} µs and SQLAlchemy ORM
  {cpu('py-sqlalchemy-orm','T2','param')} µs vs mysqlclient {cpu('py-mysqlclient','T2','param')} µs
  ({tax('py-django-orm','T2')} and {tax('py-sqlalchemy-orm','T2')}). Building the SQLAlchemy statement once and reusing it
  cuts Core from {cpu('py-sqlalchemy-core','T2','param')} to {cpu('py-sqlalchemy-core','T2','param',config='tuned')} µs.
- Prisma {cpu('node-prisma','T2','param')} µs vs its mariadb driver {cpu('node-mariadb','T2','param')} µs
  ({tax('node-prisma','T2')}); Eloquent models {cpu('php-eloquent','T2','param')} µs vs its query builder
  {cpu('php-eloquent','T2','param',config='tuned')} µs; Sequelize {cpu('node-sequelize','T2','param')} µs.
- In Ruby the model lookup by primary key *is* the fastest path: ActiveRecord `find` {cpu('rb-activerecord','T2','param')}
  µs, Sequel `Model[pk]` {cpu('rb-sequel','T2','param')} µs; the "lighter" APIs we tried were slower (see the tuned list).

**Large results: entities cost {ENT_RANGE} the driver; the framework's own scalar/array API removes most of it**
- 1M rows as entities, ns/row: Eloquent {cpu('php-eloquent','T3','text-buffered')}, Doctrine ORM
  {cpu('php-doctrine-orm','T3','text-buffered')}, SQLAlchemy ORM {cpu('py-sqlalchemy-orm','T3','text-buffered')}, Sequelize
  {cpu('node-sequelize','T3','text-buffered')}, Hibernate {cpu('java-hibernate','T3','text-buffered')}, Prisma
  {cpu('node-prisma','T3','text-buffered')} — against {cpu('php-pdo-mysql','T3','text-buffered')} (PDO),
  {cpu('py-mysqlclient','T3','text-buffered')} (mysqlclient), {cpu('node-mysql2','T3','text-buffered')} (mysql2),
  {cpu('java-connector-j','T3','text-buffered')} (Connector/J).
- Tuned (scalars / arrays, no entities): Doctrine DQL scalar {cpu('php-doctrine-orm','T3','text-buffered',config='tuned')},
  Django `values_list` {cpu('py-django-orm','T3','text-buffered',config='tuned')}, Hibernate StatelessSession
  {cpu('java-hibernate','T3','text-buffered',config='tuned')}, Sequelize `raw: true`
  {cpu('node-sequelize','T3','text-buffered',config='tuned')} ns/row. Prisma has no such option
  ({cpu('node-prisma','T3','text-buffered',config='tuned')} with `select`).
- **Memory for 1M entities** (growth since connect): Hibernate {mb('java-hibernate','T3','text-buffered','mem_growth_kb')} MB,
  ActiveRecord {mb('rb-activerecord','T3','text-buffered','mem_growth_kb')} MB, Sequelize
  {mb('node-sequelize','T3','text-buffered','mem_growth_kb')} MB, SQLAlchemy ORM
  {mb('py-sqlalchemy-orm','T3','text-buffered','mem_growth_kb')} MB, Eloquent {mb('php-eloquent','T3','text-buffered','mem_growth_kb')} MB,
  Doctrine {mb('php-doctrine-orm','T3','text-buffered','mem_growth_kb')} MB; with `yield_per` SQLAlchemy needs
  {mb('py-sqlalchemy-orm','T3','text-buffered','mem_growth_kb',config='tuned')} MB, Hibernate StatelessSession
  {mb('java-hibernate','T3','text-buffered','mem_growth_kb',config='tuned')} MB, Doctrine scalar results
  {mb('php-doctrine-orm','T3','text-buffered','mem_growth_kb',config='tuned')} MB.
- Streaming through the framework: GORM `Rows` + `ScanRows` {cpu('go-gorm','T3','text-streamed')} ns/row vs go-sql-driver
  {cpu('go-sql-driver','T3','text-streamed')} ({ratio('go-gorm','T3','text-streamed')}); Drizzle's `iterator()`
  {cpu('node-drizzle','T3','text-streamed')} ns/row vs mysql2 {cpu('node-mysql2','T3','text-streamed')}. ActiveRecord cannot
  stream (its `find_each` runs 1,000 keyset queries); Sequelize and Prisma have no row streaming.

**Wide rows and large values**
- 100 mixed-type columns: Doctrine ORM {cpu('php-doctrine-orm','T4','mix-text')} ns/cell and Eloquent
  {cpu('php-eloquent','T4','mix-text')} vs PDO {cpu('php-pdo-mysql','T4','mix-text')}; Prisma
  {cpu('node-prisma','T4','mix-text')} vs mariadb {cpu('node-mariadb','T4','mix-text')}; Diesel
  {cpu('rust-diesel','T4','mix-binary')} vs libmysqlclient {cpu('c-libmysqlclient','T4','mix-binary')} (its per-column
  deserialization dominates in an otherwise cheap stack).
- Large values cost little extra: on 10 KB BLOBs most frameworks are within 1.1–1.8× of their driver (Dapper
  {ratio('dotnet-dapper','T5','10k-doc_bin')}, GORM {ratio('go-gorm','T5','10k-doc_bin')}, TypeORM
  {ratio('node-typeorm','T5','10k-doc_bin')}); copying the bytes is the driver's work. Defaults that load the whole entity
  also read the row's other large column: SQLAlchemy ORM {ratio('py-sqlalchemy-orm','T5','10k-doc_bin')} and Diesel
  {ratio('rust-diesel','T5','10k-doc_bin')} by default, {ratio('py-sqlalchemy-orm','T5','10k-doc_bin','tuned')} and
  {ratio('rust-diesel','T5','10k-doc_bin','tuned')} selecting only that column. Prisma {ratio('node-prisma','T5','10k-doc_bin')}.
- **SeaORM 2.0.4 cannot read a MySQL JSON column as text** (only as parsed JSON), so its text-JSON results are n/a on
  Percona.

**Bulk insert: the API decides, and some "bulk" APIs insert row by row**
- Per-row model inserts (the default ORM idiom), µs per 1,000 rows: Sequel {cpu('rb-sequel','T6','batch')}, ActiveRecord
  {cpu('rb-activerecord','T6','batch')}, SQLAlchemy ORM unit of work {cpu('py-sqlalchemy-orm','T6','batch')}, Doctrine ORM
  {cpu('php-doctrine-orm','T6','batch')}, Hibernate {cpu('java-hibernate','T6','batch')}. With the framework's bulk API:
  Sequel `multi_insert` {cpu('rb-sequel','T6','batch',config='tuned')}, ActiveRecord `insert_all`
  {cpu('rb-activerecord','T6','batch',config='tuned')}, SQLAlchemy ORM bulk INSERT
  {cpu('py-sqlalchemy-orm','T6','batch',config='tuned')}, Hibernate `StatelessSession.insertMultiple()`
  {cpu('java-hibernate','T6','batch',config='tuned')} — against one driver-level 1,000-row INSERT: mysql2 (Ruby)
  {cpu('rb-mysql2','T6','multiparam')}, mysqlclient {cpu('py-mysqlclient','T6','multiparam')}, Connector/J
  {cpu('java-connector-j','T6','multiparam')}.
- **Prisma `createMany`: {cpu('node-prisma','T6','batch')} µs per 1,000 rows**, {tax('node-prisma','T6')} its driver's
  multi-row INSERT ({cpu('node-mariadb','T6','multiparam')} µs). Drizzle builds one multi-row INSERT but needs
  {cpu('node-drizzle','T6','batch')} µs to do it ({tax('node-drizzle','T6')}).
- **Dapper's `Execute(sql, list)` runs the statement once per element** ({cpu('dotnet-dapper','T6','batch')} µs per 1,000 rows),
  as does Doctrine DBAL's `insert()` ({cpu('php-dbal','T6','batch')}). Neither is a multi-row insert.
- **Hibernate's `StatelessSession.insert()` is not batched** even with `hibernate.jdbc.batch_size`: our first tuned run
  used it and measured {old('java-hibernate','T6','batch',config='tuned')} µs per 1,000 rows; `insertMultiple()` batches ({cpu('java-hibernate','T6','batch',config='tuned')} µs).

**Other**
- Diesel runs session-setup statements on every connection: a plain connect costs {cpu('rust-diesel','T1','tcp')} µs vs
  {cpu('c-libmysqlclient','T1','tcp')} µs for libmysqlclient alone.
- JdbcTemplate with a global streaming fetch size (`setFetchSize(Integer.MIN_VALUE)`) makes every single-row lookup slower:
  {cpu('java-jdbctemplate','T2','param',config='tuned')} vs {cpu('java-jdbctemplate','T2','param')} µs. Set it per query.

## Framework tax tables

Default and tuned framework CPU next to the driver baseline (Percona). Ratios below 1 happen where the framework uses a
cheaper API than the driver's default (e.g. numeric arrays instead of PDO's FETCH_BOTH, or typed readers).
{tax_tables()}
""" + tuned_section(FW) + """## Full tables

Superscript numbers mark results with a note; the notes follow each table. Connects (T1) appear only for frameworks that
open their own connections.
""" + tables(FW)
