#!/usr/bin/env python3
"""Benchmark orchestrator (runs on the bench host as root).

Runs each (server, stack, test, variant, config) as N fresh processes pinned to the
client CPU, wrapped in `perf stat` that only counts measured iterations (runner
toggles it through FIFOs), validates checksums, and stores one JSON per process.

usage: run.py --stacks c-libmysqlclient,c-mariadb-connc [--servers ps,maria]
              [--tests T0,T1,...] [--configs default,tuned] [--repeats 5] [--variants REGEX]
"""
import argparse, json, os, re, subprocess, sys, tempfile, time

ROOT = "/root/bench"
SRC = f"{ROOT}/src"
RESULTS = f"{ROOT}/results"
CLIENT_CPU = "5"

SERVERS = {
    "ps":    {"port": "3306", "socket": "/var/run/mysqld/mysqld.sock"},
    "maria": {"port": "3307", "socket": "/run/mariadb/mariadb.sock"},
}

# Variants per test. "+tls": run with DB_TLS=on. "@ed25519": run as bench_ed (maria only).
VARIANTS = {
    "T0": ["-"],
    "T1": ["tcp", "tls", "tls-verify", "tls-resume", "socket", "tcp@ed25519"],
    "T2": ["literal", "param", "prepared"],
    "T3": ["text-buffered", "text-streamed", "binary-buffered", "binary-streamed", "text-buffered+tls"],
    "T4": ["int-text", "mix-text", "int-binary", "mix-binary"],
    "T5": [f"{c}-{col}" for c in ("1k", "10k", "100k", "mix") for col in ("doc", "doc_bin")]
          + ["100k-doc+tls", "10k-doc-parse"],
    "T6": ["sqltext", "multiparam", "batch"],
}
# measured iterations / warm-up per test (JIT runtimes get a longer warm-up from the stack entry)
ITERS = {"T0": 1, "T1": 3, "T2": 3, "T3": 10, "T4": 20, "T5": 5, "T6": 3}

# Stack registry: name -> (working dir, argv prefix, jit?)
STACKS = {
    "c-libmysqlclient": ("stacks/c", ["./run-libmysqlclient"], False),
    "c-mariadb-connc":  ("stacks/c", ["./run-mariadb-connc"], False),
}

# Hardware counter sets (<= 6 HW counters each so the PMU never multiplexes; NMI watchdog is off)
EVENTS = {
    "A": "task-clock,context-switches,page-faults,cycles:u,cycles:k,instructions:u,instructions:k,branch-misses",
    "B": "task-clock,cycles,instructions,L1-dcache-load-misses,cache-misses,dTLB-load-misses,iTLB-load-misses",
}


def expected_checksum(exp, test, variant):
    v = variant.split("+")[0].split("@")[0]
    if test == "T2": return str(exp["T2"])
    if test == "T3": return str(exp["T3"])
    if test == "T4": return str(exp["T4_int" if v.startswith("int") else "T4_mix"])
    if test == "T5":
        cls, col = v.split("-", 1)
        col = "doc" if col == "doc-parse" else col
        return str(exp["T5"][f"{cls}-{col}"]["checksum"])
    if test == "T6": return f"{exp['T6']['rows']}:{exp['T6']['sum_a']}:{exp['T6']['sum_len_b']}"
    return None  # T0/T1: count only


def parse_perf(path):
    out = {}
    for line in open(path):
        f = line.strip().split(",")
        if len(f) < 3 or line.startswith("#"):
            continue
        val, name = f[0], f[2]
        if val in ("<not counted>", "<not supported>", ""):
            continue
        out[name] = float(val)
        if len(f) > 4 and f[4] and f[4] != "100.00":
            out[name + ":pct_running"] = float(f[4])
    return out


def run_one(server, stack, test, variant, config, rep, pid, exp, args):
    cwd, argv, jit = STACKS[stack]
    srv = SERVERS[server]
    base = variant.split("+")[0].split("@")[0]
    env = dict(os.environ, DB_HOST="127.0.0.1", DB_PORT=srv["port"], DB_SOCKET=srv["socket"], DB_USER="bench",
               DB_PASS="bench", DB_NAME="bench", DB_CA="/etc/dbbench/tls/ca.pem", DB_TLS="off",
               DATA_DIR=f"{ROOT}/data", MYSQLD_PID=str(pid))
    if "+tls" in variant:
        env["DB_TLS"] = "on"
    if "@ed25519" in variant:
        if server != "maria":
            return "n/a", "ed25519 auth is MariaDB-only"
        env["DB_USER"] = "bench_ed"
    warmup = (10 if jit else 2) if test != "T1" else (3 if jit else 1)
    outdir = f"{RESULTS}/{server}/{stack}"
    os.makedirs(outdir, exist_ok=True)
    label = f"{test}-{variant}-{config}-{rep}".replace("/", "_")
    res, perfout = f"{outdir}/{label}.json", f"{outdir}/{label}.perf"
    evset = "A" if rep < 3 else "B"
    with tempfile.TemporaryDirectory() as td:
        ctl, ack = f"{td}/ctl", f"{td}/ack"
        os.mkfifo(ctl); os.mkfifo(ack)
        env.update(PERF_CTL=ctl, PERF_ACK=ack)
        cmd = (["taskset", "-c", CLIENT_CPU, "perf", "stat", "-x", ",", "-o", perfout, "-D", "-1",
                "--control", f"fifo:{ctl},{ack}", "-e", EVENTS[evset], "--"]
               + argv + ["--test", test, "--variant", base, "--config", config, "--server", server,
                         "--warmup", str(warmup), "--iters", str(ITERS[test]), "--out", res])
        t0 = time.time()
        p = subprocess.run(cmd, cwd=f"{SRC}/{cwd}", env=env, capture_output=True, text=True, timeout=args.timeout)
    if p.returncode == 3:
        return "n/a", (p.stderr.strip().splitlines() or ["?"])[-1].removeprefix("n/a: ")
    if p.returncode != 0:
        return "fail", (p.stderr.strip().splitlines() or ["?"])[-1][:300]
    d = json.load(open(res))
    want = expected_checksum(exp, test, variant)
    bad = [it["checksum"] for it in d["iters"] if want is not None and it["checksum"] != want]
    d.update(variant=variant, rep=rep, event_set=evset, perf=parse_perf(perfout), elapsed_s=round(time.time() - t0, 2),
             checksum_ok=not bad, expected=want)
    json.dump(d, open(res, "w"))
    os.unlink(perfout)
    if bad:
        return "fail", f"checksum {bad[0]} != {want}"
    cpu = sorted(it["cpu_ns"] for it in d["iters"])[len(d["iters"]) // 2]
    return "ok", f"cpu/op {cpu / d['ops_per_iter'] / 1000:.3f} us  tls={d['tls']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stacks", required=True)
    ap.add_argument("--servers", default="ps,maria")
    ap.add_argument("--tests", default="T0,T1,T2,T3,T4,T5,T6")
    ap.add_argument("--configs", default="default,tuned")
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--variants", default=".*")
    ap.add_argument("--timeout", type=int, default=1800)
    args = ap.parse_args()
    subprocess.run(["/root/03-runtime-cpu.sh"], capture_output=True)
    log = open(f"{ROOT}/run.log", "a")
    for server in args.servers.split(","):
        pid = subprocess.run(["/root/dbctl.sh", "start", server], capture_output=True, text=True, check=True).stdout.split()[-1]
        exp = json.load(open(f"{ROOT}/data/expected-{server}.json"))
        for stack in args.stacks.split(","):
            for test in args.tests.split(","):
                for variant in VARIANTS[test]:
                    if not re.search(args.variants, variant):
                        continue
                    for config in args.configs.split(","):
                        for rep in range(args.repeats if test != "T0" else 3):
                            status, msg = run_one(server, stack, test, variant, config, rep, pid, exp, args)
                            line = f"{time.strftime('%H:%M:%S')} {server:5} {stack:18} {test} {variant:20} {config:7} r{rep} {status:4} {msg}"
                            print(line, flush=True); log.write(line + "\n"); log.flush()
                            if status != "ok":
                                d = f"{RESULTS}/{server}/{stack}"
                                os.makedirs(d, exist_ok=True)
                                json.dump({"stack": stack, "test": test, "variant": variant, "config": config,
                                           "server": server, "status": status, "reason": msg},
                                          open(f"{d}/{test}-{variant}-{config}.{status.replace('/', '')}", "w"))
                                break  # n/a or failure: no point repeating


if __name__ == "__main__":
    main()
