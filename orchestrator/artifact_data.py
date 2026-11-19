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
        "py-mariadb": "MariaDB Connector/Python 1.1"}


def sig(v, n=3):
    if v is None:
        return None
    if v == 0:
        return 0
    from math import floor, log10
    d = n - 1 - floor(log10(abs(v)))
    r = round(v, max(d, 0))
    return int(r) if d <= 0 else r


rows = json.load(open(sys.argv[1]))
prefixes = sys.argv[3].split(",") if len(sys.argv) > 3 else None
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
        if r["test"] == "T0":
            o["rss_start_mb"] = round((r.get("rss_start_kb") or 0) / 1024, 1)
    out.append(o)
out.sort(key=lambda o: (o["test"], o["variant"], o["server"], o["stack"], o["config"]))
json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False, separators=(",", ":"))
print(len(out), "rows")
