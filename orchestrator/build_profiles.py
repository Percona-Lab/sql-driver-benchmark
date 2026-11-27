#!/usr/bin/env python3
"""Write reports/profiles.md (where the client CPU goes) from profile_report.py output.

usage: build_profiles.py results/profile-summary.json
Flame graphs (one SVG per profile) are made on the box with inferno-flamegraph into results/profiles/svg/ and linked
from the tables.
"""
import json, os, sys

P = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "results/profile-summary.json"))
sys.path.insert(0, os.path.dirname(__file__))
from fwtax import BASE   # framework -> driver

WORK = ["compiled code", "memory copy", "allocation & GC", "interpreter / VM", "TLS crypto",
        "kernel: network send", "kernel: network receive", "kernel: page faults", "kernel: memory mapping",
        "kernel: waiting & scheduling", "kernel: other"]
SHORT = {"compiled code": "code", "memory copy": "copy", "allocation & GC": "alloc+GC", "interpreter / VM": "interp/VM",
         "TLS crypto": "crypto", "kernel: network send": "k:send", "kernel: network receive": "k:recv",
         "kernel: page faults": "k:faults", "kernel: memory mapping": "k:mmap", "kernel: waiting & scheduling": "k:wait",
         "kernel: other": "k:other"}
OWN = ["driver", "framework", "benchmark", "runtime & stdlib"]
CELLS = [("T1", "tls-verify", "Verified TLS connect"), ("T2", None, "Point select"),
         ("T3", "buffered", "1M rows, buffered"), ("T3", "streamed", "1M rows, streamed"),
         ("T4", None, "10,000 × 100 mixed columns"), ("T5", "10k-doc", "1,000 × 10 KB JSON documents"),
         ("T6", None, "Bulk insert, 1M rows")]
# preferred variant per test when a stack has several
PREF = {"T2": ["literal", "param"], "T3buffered": ["text-buffered", "binary-buffered"], "T3streamed": ["text-streamed", "binary-streamed"],
        "T4": ["mix-text", "mix-binary"], "T6": ["multiparam", "batch"]}


def W(stack, test, variant, cat, view="work"):
    r = next((r for r in P if r["stack"] == stack and r["test"] == test and r["variant"] == variant), None)
    if not r:
        return "n/a"
    v = sum(x for k, x in r[view].items() if k == cat or (cat.endswith("*") and k.startswith(cat[:-1])))
    return f"{v:.0f}%"


# Shares measured from the folded stacks (orchestrator/profile_stats.py; raw stacks are in the release archive)
STACKED = json.load(open("results/profile-stats.json"))


def pick(stack, test, sel):
    rows = [r for r in P if r["stack"] == stack and r["test"] == test]
    key = test + (sel if sel in ("buffered", "streamed") else "")
    if sel and sel not in ("buffered", "streamed"):
        return next((r for r in rows if r["variant"] == sel), None)
    for v in PREF.get(key, []):
        r = next((r for r in rows if r["variant"] == v), None)
        if r:
            return r
    return None


def svg(r):
    return f"../results/profiles/svg/{r['server']}/{r['stack']}/{r['test']}-{r['variant']}-{r['config']}.svg"


stacks = sorted({r["stack"] for r in P}, key=lambda s: (s in BASE, s))
out = ["# Where the client CPU goes — profiles", "",
       "> **AI-generated results.** Profiles were collected, classified and summarized with an AI assistant (Claude); the "
       "classification rules are heuristics over function and library names (`orchestrator/profile_report.py`). Spot-check "
       "anything that matters against the flame graphs.", "",
       "Each profile samples the **measured iterations only** of one steady-state process (`perf record` at 2,999 Hz with call "
       "graphs, gated by the runner; warm-up and start-up are not sampled), on Percona Server with the default configuration. "
       "JIT runtimes write perf maps so generated code is named (Java `-XX:+PreserveFramePointer -XX:+DumpPerfMapAtExit`, "
       "Node `--perf-basic-prof`, Python 3.14 perf trampoline, .NET `DOTNET_PerfMapEnabled=1` with W^X off, Ruby "
       "`--yjit-perf`); native libraries are resolved with their debug symbols (Oracle `libmysqlclient24-dbgsym` 9.7.4, Ubuntu "
       "ddebs). Sampling adds some overhead, so use these for shares, not for timings.", "",
       "**What kind of work** (percent of sampled cycles, by where the sample landed): code = the driver's, framework's or "
       "benchmark's own instructions; copy = memmove/memcpy; alloc+GC = allocators and garbage collectors; interp/VM = "
       "interpreter dispatch and VM runtime; crypto = TLS; k:send / k:recv = kernel network paths (on loopback the send "
       "path also delivers the packet to the server's socket); k:faults = page faults; k:mmap = mmap/brk; k:wait = poll, "
       "futex and scheduling (waiting for the server's reply lands here for drivers that poll, and in k:recv for drivers "
       "that block in a read); k:other = remaining kernel time.", "",
       "## Findings", "",
       f"- **Verified TLS connects are mostly key exchange, plus per-connection setup.** TLS crypto is {W('c-libmysqlclient','T1','tls-verify','TLS crypto')} "
       f"of libmysqlclient's verified connect (P-256 elliptic-curve math). Every driver built on libmysqlclient or MariaDB "
       f"Connector/C also builds a new OpenSSL context per connection: `SSL_CTX_new` is {STACKED['ssl_ctx_new']} of the connect, "
       f"loading the CA file {STACKED['ca_load']}, parsing cipher lists {STACKED['cipher_list']}. A connection pool avoids all of it.",
       f"- **MySQL Connector/J builds a new `SSLContext` for every connection** "
       f"(`ExportControlled$SslContextBuilder.build()`: {STACKED['cj_sslcontext']} of a verified connect): it reloads and "
       "decrypts the PKCS12 trust store each time (PBKDF2 key derivation, SHA-256 in JVM intrinsic stubs). This is why its "
       "verified TLS connect costs several milliseconds. (JVM stubs are not named, so Java's crypto share in the table is "
       "understated.)",
       f"- **Point selects are kernel work.** For native drivers about three quarters of the client CPU is in the kernel "
       f"(libmysqlclient {W('c-libmysqlclient','T2','literal','kernel*')}, Rust `mysql` {W('rust-mysql','T2','literal','kernel*')}): the send path (on loopback it "
       "also delivers the packet to the server's socket), waking up for the reply, and netfilter rules "
       f"({STACKED['netfilter']}, a property of this host, the same for every driver). Drivers that wait in "
       "`poll`/`epoll` (Connector/C, mysqlnd, Go, Rust async, .NET, Node, MariaDB Connector/J) and libmysqlclient, which "
       "blocks in `recvfrom`, spend the same total; the time is only charged to different system calls.",
       f"- **Oracle's MySql.Data runs its synchronous API on the thread pool:** in a point select half of the samples are on "
       f".NET thread-pool workers and {W('dotnet-mysql-data','T2','literal','kernel: waiting & scheduling')} is thread hand-off "
       "(scheduling, futexes), which is where its extra cost over MySqlConnector goes.",
       f"- **Both Go drivers spend a third to a half of each streamed row on synchronization:** {STACKED['go_sql_locks']} of "
       "go-sql-driver's streamed-row CPU is atomics and mutexes in `database/sql` (`closingMutex.RLock/RUnlock`, the lock in "
       f"`Rows.Next`), not the driver; go-mysql, which bypasses `database/sql`, spends {STACKED['go_mysql_pool']} in "
       "`utils.BytesBufferGet`, a `sync.Pool` buffer fetched per packet.",
       "- **Ruby mysql2 releases the GVL for every row** (`rb_nogvl` around `mysql_fetch_row`), even when the whole result is "
       f"already in memory: mutex lock/unlock and thread hand-off take {STACKED['rb_mysql2_mutex']} of its buffered-row CPU "
       "(found with perf, caller confirmed with a bpftrace uprobe on `pthread_mutex_lock`).",
       f"- **Garbage collection dominates large results in managed runtimes:** allocation and GC are "
       f"{W('node-mysql2','T3','text-buffered','allocation & GC')} of Node mysql2's buffered rows (V8's young-generation scavenger), "
       f"{W('java-mariadb-j','T3','text-buffered','allocation & GC')} for MariaDB Connector/J, {W('java-hibernate','T3','text-buffered','allocation & GC')} for "
       f"Hibernate; libmysqlclient instead spends {W('c-libmysqlclient','T3','text-buffered','memory copy')} copying rows into its own buffers.",
       f"- **Interpreters:** pure-Python drivers spend most of their time in the interpreter (PyMySQL "
       f"{W('py-pymysql','T3','text-buffered','interpreter / VM')} of buffered rows); C-accelerated ones less (mysqlclient "
       f"{W('py-mysqlclient','T3','text-buffered','interpreter / VM')}, mostly creating Python objects for each row inside the driver's C code).",
       f"- **ORMs: the framework, not the driver, is the cost.** In a point select the framework's own code is "
       f"{W('py-django-orm','T2','param','framework','owner')} of Django's CPU, {W('py-sqlalchemy-orm','T2','param','framework','owner')} of SQLAlchemy ORM's, "
       f"{W('node-prisma','T2','param','framework','owner')} of Prisma's, {W('dotnet-efcore','T2','param','framework','owner')} of EF Core's; for 1M rows as "
       f"entities {W('py-sqlalchemy-orm','T3','text-buffered','framework','owner')} (SQLAlchemy ORM) and {W('go-gorm','T3','text-buffered','framework','owner')} (GORM).",
       "- **Limits of these profiles:** PHP has no perf map for interpreted code, so Doctrine and Eloquent show up as "
       "interpreter time, not as framework code. In async Rust, framework and driver code inlined into the caller's future "
       "can be counted as the benchmark. Stack unwinding uses frame pointers, which loses the direct caller of a leaf "
       "function that has no frame of its own (bpftrace confirmed the mysql2 caller).", "",
       "**Whose code**: the innermost frame belonging to the driver, the framework or the benchmark loop (kernel time counts "
       "for the code that made the system call); runtime = everything else (language runtime, standard library).", ""]
for test, sel, title in CELLS:
    rows = [(s, pick(s, test, sel)) for s in stacks]
    rows = [(s, r) for s, r in rows if r]
    if not rows:
        continue
    out += [f"## {title}", "", "| stack (variant) | " + " | ".join(SHORT[w] for w in WORK) + " | driver | framework | bench | runtime | flame graph |",
            "|---|" + "---:|" * (len(WORK) + len(OWN)) + "---|"]
    for s, r in rows:
        w = [r["work"].get(k, 0) for k in WORK]
        o = [r["owner"].get(k, 0) for k in OWN]
        cells = [f"{v:.0f}" if v >= 0.5 else "" for v in w + o]
        out.append(f"| {s} ({r['variant']}) | " + " | ".join(cells) + f" | [svg]({svg(r)}) |")
    out.append("")
open("reports/profiles.md", "w").write("\n".join(out) + "\n")
print("wrote reports/profiles.md", len(out), "lines")
