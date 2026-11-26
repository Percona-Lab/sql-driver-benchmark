#!/usr/bin/env python3
"""Framework tax: client CPU of each framework vs the driver it runs on (same server, test, config).

Baseline variant: the driver's result for the same variant when the driver has one; otherwise the variant the framework
actually uses on the wire (FALLBACK). Bulk insert (framework "batch" = its bulk API, one multi-row INSERT per 1,000 rows,
or per-row model inserts where the ORM idiom is that) is compared with the driver's "multiparam" (one 1,000-row INSERT
with bound parameters), else "sqltext".

usage: fwtax.py summary.json [--server ps] [--md]   -> JSON rows (or a Markdown table with --md)
"""
import argparse, json

# framework -> underlying driver stack
BASE = {"py-sqlalchemy-core": "py-mysqlclient", "py-sqlalchemy-orm": "py-mysqlclient", "py-django-orm": "py-mysqlclient",
        "java-jdbctemplate": "java-connector-j", "java-jooq": "java-connector-j", "java-hibernate": "java-connector-j",
        "go-sqlx": "go-sql-driver", "go-gorm": "go-sql-driver",
        "node-knex": "node-mysql2", "node-drizzle": "node-mysql2", "node-sequelize": "node-mysql2", "node-typeorm": "node-mysql2",
        "node-prisma": "node-mariadb",
        "dotnet-dapper": "dotnet-mysqlconnector", "dotnet-efcore": "dotnet-mysqlconnector",
        "php-dbal": "php-pdo-mysql", "php-doctrine-orm": "php-pdo-mysql", "php-eloquent": "php-pdo-mysql",
        "rb-sequel": "rb-mysql2", "rb-activerecord": "rb-mysql2",
        "rust-seaorm": "rust-sqlx", "rust-diesel": "c-libmysqlclient"}
# (framework, test) -> driver variants to try when the driver has no result for the framework's variant
FALLBACK = {("rb-sequel", "T2"): ["literal"], ("rb-activerecord", "T2"): ["literal"],
            ("rust-diesel", "T2"): ["prepared"], ("rust-seaorm", "T2"): ["prepared"]}
# headline cells: (test, framework variants in order of preference)
HEAD = [("T2", ["param"]), ("T3", ["text-buffered", "binary-buffered"]), ("T3", ["text-streamed", "binary-streamed"]),
        ("T4", ["mix-text", "mix-binary"]), ("T5", ["10k-doc_bin"]), ("T6", ["batch"])]
DIV = {"T2": 1e3, "T3": 1, "T4": 1, "T5": 1, "T6": 1e3}
UNIT = {"T2": "µs/query", "T3": "ns/row", "T4": "ns/cell", "T5": "ns/KB", "T6": "µs/1,000 rows"}


def load(path):
    return {(r["server"], r["stack"], r["test"], r["variant"], r["config"]): r for r in json.load(open(path)) if "cpu_ns_op" in r}


def base_row(rows, srv, fw, test, variant, config):
    drv = BASE[fw]
    cands = [variant] if test != "T6" else ["multiparam", "sqltext"]
    cands += FALLBACK.get((fw, test), [])
    for v in cands:
        for cfg in (config, "default"):   # driver tuned options mirror the framework's tuned driver options where both exist
            r = rows.get((srv, drv, test, v, cfg))
            if r:
                return r
    return None


def compute(rows, srv):
    out = []
    for fw in BASE:
        for test, variants in HEAD:
            for cfg in ("default", "tuned"):
                f = next((rows[k] for v in variants if (k := (srv, fw, test, v, cfg)) in rows), None)
                if not f:
                    continue
                b = base_row(rows, srv, fw, test, f["variant"], cfg)
                out.append({"server": srv, "framework": fw, "driver": BASE[fw], "test": test, "variant": f["variant"], "config": cfg,
                            "fw": f["cpu_ns_op"] / DIV[test], "base": b["cpu_ns_op"] / DIV[test] if b else None,
                            "base_variant": b["variant"] if b else None, "base_config": b["config"] if b else None,
                            "ratio": f["cpu_ns_op"] / b["cpu_ns_op"] if b else None})
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("summary"); ap.add_argument("--server", default="ps"); ap.add_argument("--md", action="store_true")
    a = ap.parse_args()
    res = compute(load(a.summary), a.server)
    if not a.md:
        print(json.dumps(res, indent=1)); raise SystemExit
    for test, variants in HEAD:
        sub = [r for r in res if r["test"] == test and r["variant"] in variants]
        print(f"\n{test} {sub[0]['variant'] if sub else ''} ({UNIT[test]})\n")
        print("| framework | default | tuned | driver baseline | default × | tuned × |\n|---|---:|---:|---|---:|---:|")
        for fw in BASE:
            d = next((r for r in sub if r["framework"] == fw and r["config"] == "default"), None)
            t = next((r for r in sub if r["framework"] == fw and r["config"] == "tuned"), None)
            if not d and not t:
                continue
            ref = d or t
            f = lambda v: "n/a" if v is None else (f"{v:,.0f}" if v >= 100 else f"{v:.3g}")
            x = lambda r: "" if not r or r["ratio"] is None else f"{r['ratio']:.1f}×"
            print(f"| {fw} | {f(d['fw']) if d else 'n/a'} | {f(t['fw']) if t else 'n/a'} | {BASE[fw]} {ref['base_variant'] or ''} "
                  f"{f(ref['base']) if ref['base'] is not None else 'n/a'} | {x(d)} | {x(t)} |")
