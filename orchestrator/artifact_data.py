#!/usr/bin/env python3
"""Flatten report.py output into display-ready rows for the report artifact.
usage: artifact_data.py summary.json out.json [--stacks prefix,prefix]"""
import json, sys

UNIT = {"T0": ("ms", 1e6), "T1": ("µs", 1e3), "T2": ("µs", 1e3), "T3": ("ns", 1), "T4": ("ns", 1), "T5": ("ns", 1), "T6": ("µs", 1e3)}
LANG = {"c": "C", "go": "Go", "java": "Java", "py": "Python", "node": "Node.js", "php": "PHP", "rb": "Ruby",
        "dotnet": ".NET", "rust": "Rust", "cpp": "C++"}
NAME = {"c-libmysqlclient": "libmysqlclient 9.7", "c-mariadb-connc": "MariaDB Connector/C 3.4",
        "go-sql-driver": "go-sql-driver/mysql 1.10", "go-mysql": "go-mysql 1.16",
        "java-connector-j": "MySQL Connector/J 26.10", "java-mariadb-j": "MariaDB Connector/J 4.0",
        "py-mysqlclient": "mysqlclient 2.3", "py-mysql-connector-c": "mysql-connector 26.10 (C ext)",
        "py-mysql-connector-pure": "mysql-connector 26.10 (pure)", "py-pymysql": "PyMySQL 1.2",
        "py-mariadb": "MariaDB Connector/Python 1.1",
        "cpp-mysql-connector": "MySQL Connector/C++ 26.10", "cpp-mariadb": "MariaDB Connector/C++ 1.1",
        "rust-mysql": "mysql crate 28 (Rust)", "rust-sqlx": "sqlx 0.9 (Rust)",
        "dotnet-mysqlconnector": "MySqlConnector 3.0", "dotnet-mysql-data": "MySql.Data 26.10",
        "node-mysql2": "mysql2 3.24 (Node)", "node-mariadb": "mariadb 3.5 (Node)", "node-mysql": "mysql 2.18 (Node, legacy)",
        "php-mysqli": "mysqli (PHP 8.5)", "php-pdo-mysql": "PDO_MySQL (PHP 8.5)",
        "rb-mysql2": "mysql2 0.5 (Ruby)", "rb-trilogy": "trilogy 2.13 (Ruby)"}


def sig(v, n=3):
    if v is None:
        return None
    if v == 0:
        return 0
    from math import floor, log10
    d = n - 1 - floor(log10(abs(v)))
    r = round(v, max(d, 0))
    return int(r) if d <= 0 else r


import argparse
ap = argparse.ArgumentParser()
ap.add_argument("summary"); ap.add_argument("out")
ap.add_argument("--stacks", help="comma-separated stack prefixes to keep")
ap.add_argument("--mem", help="report.py output of the memory pass; its memory fields are merged in")
A = ap.parse_args()
rows = json.load(open(A.summary))
prefixes = A.stacks.split(",") if A.stacks else None
MEM = {}
if A.mem:
    for r in json.load(open(A.mem)):
        if "mem_work_kb" in r:
            MEM[(r["server"], r["stack"], r["test"], r["variant"], r["config"])] = r
out = []
for r in rows:
    st = r["stack"]
    if prefixes and not any(st.startswith(p) for p in prefixes):
        continue
    unit, div = UNIT[r["test"]]
    o = {"server": r["server"], "stack": st, "driver": NAME.get(st, st), "lang": LANG[st.split("-")[0]],
         "test": r["test"], "variant": r["variant"], "config": r["config"], "unit": unit}
    if "status" in r:
        o.update(status=r["status"], reason=r["reason"], cpu=None)
    else:
        o.update(status="ok", reason="", cpu=sig(r["cpu_ns_op"] / div), wall=sig(r["wall_ns_op"] / div),
                 server_cpu=sig(r["srv_ns_op"] / div), cv_pct=round(r["cv_pct"], 2),
                 rss_mb=round(r["rss_peak_kb"] / 1024, 1),
                 ipc=round(r["ipc"], 2) if r.get("ipc") else None,
                 instr=sig(r["instr_op"]) if r.get("instr_op") else None,
                 kernel_pct=round(r["kernel_pct"], 1) if r.get("kernel_pct") is not None else None,
                 tls=r.get("tls", ""))
        mem = MEM.get((r["server"], st, r["test"], r["variant"], r["config"]), r)
        for k in ("mem_baseline_kb", "mem_work_kb", "mem_retained_kb", "mem_growth_kb"):
            if k in mem:
                o[k.replace("_kb", "_mb")] = round(mem[k] / 1024, 2)
        for k in ("warmup_mean", "warmup_unstable"):
            if k in r:
                o[k] = r[k]
        if r["test"] == "T0":
            o["rss_start_mb"] = round((r.get("rss_start_kb") or 0) / 1024, 1)
    out.append(o)
out.sort(key=lambda o: (o["test"], o["variant"], o["server"], o["stack"], o["config"]))
json.dump(out, open(A.out, "w"), ensure_ascii=False, separators=(",", ":"))
print(len(out), "rows")
