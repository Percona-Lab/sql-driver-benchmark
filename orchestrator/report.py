#!/usr/bin/env python3
"""Aggregate result files into one row per (server, stack, test, variant, config).

CPU per op = median over processes of the per-process median iteration CPU.
Hardware counters are totals over all measured iterations, divided by total ops.
usage: report.py [results_dir] > summary.json
"""
import glob, json, os, statistics as st, sys

RES = sys.argv[1] if len(sys.argv) > 1 else "/root/bench/results"
UNIT = {"T0": 1, "T1": 1, "T2": 1, "T3": 1, "T4": 1, "T5": 1, "T6": 1}
rows = {}
for f in glob.glob(f"{RES}/*/*/*.json"):
    d = json.load(open(f))
    key = (d["server"], d["stack"], d["test"], d["variant"], d["config"])
    rows.setdefault(key, []).append(d)

out = []
for (server, stack, test, variant, config), allruns in sorted(rows.items()):
    runs = [r for r in allruns if not r.get("event_set")]          # timed processes (no perf attached)
    counted = [r for r in allruns if r.get("event_set")]           # hardware-counter processes
    if not runs:
        continue
    ops = runs[0]["ops_per_iter"]
    proc_cpu = [st.median(it["cpu_ns"] for it in r["iters"]) / ops for r in runs]
    proc_wall = [st.median(it["wall_ns"] for it in r["iters"]) / ops for r in runs]
    srv = [st.median(it["srv_ticks"] for it in r["iters"]) * 1e7 / ops for r in runs]  # 10 ms ticks -> ns
    rss = [max(it["rss_peak_kb"] for it in r["iters"]) for r in runs]
    row = {"server": server, "stack": stack, "test": test, "variant": variant, "config": config,
           "procs": len(runs), "ops_per_iter": ops, "tls": runs[0]["tls"], "lib": runs[0]["lib"],
           "cpu_ns_op": st.median(proc_cpu), "cv_pct": 100 * st.pstdev(proc_cpu) / st.mean(proc_cpu),
           "wall_ns_op": st.median(proc_wall), "srv_ns_op": st.median(srv), "rss_peak_kb": st.median(rss),
           "checksum_ok": all(r.get("checksum_ok", True) for r in runs)}
    if test == "T0":
        row["rss_start_kb"] = runs[0].get("rss_start_kb")
    # hardware counters: per op, per event set
    for evset in ("A", "B"):
        rs = [r for r in counted if r.get("event_set") == evset and r.get("perf")]
        if not rs:
            continue
        tot = {}
        for r in rs:
            n = ops * len(r["iters"])
            for k, v in r["perf"].items():
                if not k.endswith("pct_running"):
                    tot.setdefault(k, []).append(v / n)
        med = {k: st.median(v) for k, v in tot.items()}
        if evset == "A":
            cu, ck = med.get("cycles:u", 0), med.get("cycles:k", 0)
            iu, ik = med.get("instructions:u", 0), med.get("instructions:k", 0)
            row.update(cycles_op=cu + ck, instr_op=iu + ik, ipc=(iu + ik) / (cu + ck) if cu + ck else None,
                       kernel_pct=100 * ck / (cu + ck) if cu + ck else None,
                       branch_miss_op=med.get("branch-misses"), faults_op=med.get("page-faults"),
                       ctxsw_op=med.get("context-switches"))
        else:
            row.update(l1d_miss_op=med.get("L1-dcache-load-misses"), llc_miss_op=med.get("cache-misses"),
                       dtlb_miss_op=med.get("dTLB-load-misses"), itlb_miss_op=med.get("iTLB-load-misses"))
    out.append(row)

for f in glob.glob(f"{RES}/*/*/*.na") + glob.glob(f"{RES}/*/*/*.fail"):
    d = json.load(open(f))
    out.append({k: d[k] for k in ("server", "stack", "test", "variant", "config", "status", "reason")})
json.dump(out, sys.stdout, indent=0)
