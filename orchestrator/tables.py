#!/usr/bin/env python3
"""Markdown pivot tables from report.py output: one table per test, rows = stack/config, columns = variants,
cells = client CPU per op as 'ps / maria'. usage: tables.py summary.json [--tests T1,T3] [--metric cpu_ns_op]"""
import argparse, json, os, re
from collections import defaultdict

SUP = str.maketrans("0123456789,", "⁰¹²³⁴⁵⁶⁷⁸⁹˒")
NOTES = json.load(open(os.path.join(os.path.dirname(__file__), "..", "reports", "notes.json")))


def notes_for(r):
    """1-based note numbers that apply to a summary row (same rules as the report artifact)."""
    out = []
    for i, n in enumerate(NOTES, 1):
        if n.get("auto") == "cv":
            if r.get("cv_pct", 0) > 5 and r["test"] != "T0":
                out.append(i)
        elif n.get("auto") == "warmup":
            if r.get("warmup_unstable", 0) > 0:
                out.append(i)
        elif all(re.fullmatch(p, str(r.get(k, ""))) for k, p in n["match"].items()):
            out.append(i)
    return out

UNIT = {"T0": ("ms", 1e6), "T1": ("µs/connect", 1e3), "T2": ("µs/query", 1e3), "T3": ("ns/row", 1),
        "T4": ("ns/cell", 1), "T5": ("ns/KB", 1), "T6": ("µs/1000-row stmt", 1e3)}
ORDER = ["c-libmysqlclient", "c-mariadb-connc", "cpp-mysql-connector", "cpp-mariadb", "go-sql-driver", "go-mysql", "java-connector-j", "java-mariadb-j",
         "rust-mysql", "rust-sqlx", "dotnet-mysqlconnector", "dotnet-mysql-data", "node-mysql2", "node-mariadb", "node-mysql",
         "php-mysqli", "php-pdo-mysql", "rb-mysql2", "rb-trilogy",
         "py-mysqlclient", "py-mysql-connector-c", "py-mariadb", "py-pymysql", "py-mysql-connector-pure"]

ap = argparse.ArgumentParser()
ap.add_argument("summary")
ap.add_argument("--tests", default="T1,T2,T3,T4,T5,T6")
ap.add_argument("--metric", default="cpu_ns_op", help="cpu_ns_op, or mem_work_kb / mem_growth_kb / mem_baseline_kb (shown in MB)")
ap.add_argument("--stacks", help="comma-separated stack prefixes to include")
a = ap.parse_args()
rows = json.load(open(a.summary))
if a.stacks:
    rows = [r for r in rows if any(r["stack"].startswith(p) for p in a.stacks.split(","))]
MEM = a.metric.startswith("mem_")
if MEM:
    rows = [r for r in rows if "status" in r or a.metric in r]
cell = {}
variants = defaultdict(list)
for r in rows:
    k = (r["test"], r["stack"], r["config"], r["variant"])
    if r["variant"] not in variants[r["test"]]:
        variants[r["test"]].append(r["variant"])
    cell.setdefault(k, {})[r["server"]] = r
for t in a.tests.split(","):
    unit, div = (("MB", 1024) if MEM else UNIT[t])
    vs = variants[t]
    stacks = sorted({(k[1], k[2]) for k in cell if k[0] == t},
                    key=lambda s: (ORDER.index(s[0]) if s[0] in ORDER else 99, s[1]))
    what = {"mem_work_kb": "memory for the work", "mem_growth_kb": "memory growth since connect",
            "mem_baseline_kb": "memory after connect"}.get(a.metric, "client CPU")
    if not vs: continue
    print(f"\n### {t} — {what}, {unit} (Percona / MariaDB)\n")
    print("| stack | config | " + " | ".join(vs) + " |")
    print("|---|---|" + "---|" * len(vs))
    used = set()
    for st, cfg in stacks:
        out = []
        for v in vs:
            c = cell.get((t, st, cfg, v), {})
            parts = []
            for srv in ("ps", "maria"):
                r = c.get(srv)
                if not r: parts.append("–"); continue
                ns = notes_for(r); used.update(ns)
                mark = ",".join(map(str, ns)).translate(SUP)
                if "status" in r: parts.append(("n/a" if r["status"] == "n/a" else "FAIL") + mark)
                else:
                    v_ = max(0, r[a.metric] / div) if MEM else r[a.metric] / div
                    if MEM and v_ < 0.05: v_ = 0
                    parts.append((f"{v_:,.3g}" if v_ < 100 else f"{v_:,.0f}") + mark)
            out.append(" / ".join(parts))
        if all(p.startswith(("n/a", "–")) for cell_ in out for p in cell_.split(" / ")):
            continue   # e.g. a "tuned" config the driver does not have
        print(f"| {st} | {cfg} | " + " | ".join(out) + " |")
    if used:
        print()
        for i in sorted(used):
            n = NOTES[i - 1]
            print(f"{str(i).translate(SUP)} **{n['title']}.** {n['text']}  ")
