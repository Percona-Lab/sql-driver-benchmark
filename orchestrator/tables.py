#!/usr/bin/env python3
"""Markdown pivot tables from report.py output: one table per test, rows = stack/config, columns = variants,
cells = client CPU per op as 'ps / maria'. usage: tables.py summary.json [--tests T1,T3] [--metric cpu_ns_op]"""
import argparse, json
from collections import defaultdict

UNIT = {"T0": ("ms", 1e6), "T1": ("µs/connect", 1e3), "T2": ("µs/query", 1e3), "T3": ("ns/row", 1),
        "T4": ("ns/cell", 1), "T5": ("ns/KB", 1), "T6": ("µs/1000-row stmt", 1e3)}
ORDER = ["c-libmysqlclient", "c-mariadb-connc", "go-sql-driver", "go-mysql", "java-connector-j", "java-mariadb-j",
         "rust-mysql", "rust-sqlx", "dotnet-mysqlconnector", "dotnet-mysql-data", "node-mysql2", "node-mariadb", "node-mysql",
         "php-mysqli", "php-pdo-mysql", "rb-mysql2", "rb-trilogy",
         "py-mysqlclient", "py-mysql-connector-c", "py-mariadb", "py-pymysql", "py-mysql-connector-pure"]

ap = argparse.ArgumentParser()
ap.add_argument("summary")
ap.add_argument("--tests", default="T1,T2,T3,T4,T5,T6")
ap.add_argument("--metric", default="cpu_ns_op")
a = ap.parse_args()
rows = json.load(open(a.summary))
cell = {}
variants = defaultdict(list)
for r in rows:
    k = (r["test"], r["stack"], r["config"], r["variant"])
    if r["variant"] not in variants[r["test"]]:
        variants[r["test"]].append(r["variant"])
    cell.setdefault(k, {})[r["server"]] = r
for t in a.tests.split(","):
    unit, div = UNIT[t]
    vs = variants[t]
    stacks = sorted({(k[1], k[2]) for k in cell if k[0] == t},
                    key=lambda s: (ORDER.index(s[0]) if s[0] in ORDER else 99, s[1]))
    print(f"\n### {t} — client CPU, {unit} (Percona / MariaDB)\n")
    print("| stack | config | " + " | ".join(vs) + " |")
    print("|---|---|" + "---|" * len(vs))
    for st, cfg in stacks:
        out = []
        for v in vs:
            c = cell.get((t, st, cfg, v), {})
            parts = []
            for srv in ("ps", "maria"):
                r = c.get(srv)
                if not r: parts.append("–")
                elif "status" in r: parts.append("n/a" if r["status"] == "n/a" else "FAIL")
                else: parts.append(f"{r[a.metric] / div:,.3g}" if r[a.metric] / div < 100 else f"{r[a.metric] / div:,.0f}")
            out.append(" / ".join(parts))
        print(f"| {st} | {cfg} | " + " | ".join(out) + " |")
