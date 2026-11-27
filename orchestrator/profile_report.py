#!/usr/bin/env python3
"""Where the client CPU goes: breakdowns of the profiling pass (perf record of the measured iterations).

Input: folded stacks from collapse_perf.py, each frame written as  symbol{library}  ("kernel", "jit" for code named by
a runtime's perf map, "inlined" for inlined frames). Weights are sampled CPU cycles.

Two views per profile:
  work  — what the CPU was doing where the sample landed: kernel time split by what entered the kernel (network
          send/receive, page faults, other), TLS crypto, memory allocation and GC, memory copies, interpreter / VM,
          and compiled code (everything else: the driver's, framework's or benchmark's own instructions).
  owner — whose code: the innermost frame that belongs to the framework, the driver or the benchmark loop; samples with
          none of those above them are "runtime & stdlib". Kernel samples count for the code that entered the kernel.

usage: profile_report.py results-prof/ > profile-summary.json
"""
import glob, json, re, sys
from collections import Counter

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/root/bench/results-prof"
FR = re.compile(r"^(.*)\{([^{}]*)\}$")


def split(frame):
    m = FR.match(frame)
    return (m.group(1), m.group(2)) if m else (frame, "")


# ------------------------------------------------------------------ work
K_SEND = re.compile(r"__x64_sys_(sendto|sendmsg|write|writev)\b|tcp_sendmsg|sock_write_iter")
K_RECV = re.compile(r"__x64_sys_(recvfrom|recvmsg|read|readv)\b|tcp_recvmsg|sock_read_iter")
K_FAULT = re.compile(r"asm_exc_page_fault|exc_page_fault|do_user_addr_fault|handle_mm_fault")
K_MEM = re.compile(r"__x64_sys_(mmap|munmap|brk|madvise|mprotect|mremap)\b")
K_WAIT = re.compile(r"__x64_sys_(poll|ppoll|epoll_wait|epoll_pwait|select|pselect6|futex|nanosleep|clock_nanosleep|sched_yield)\b|schedule\b")
K_NETIRQ = re.compile(r"net_rx_action|__netif_receive|ip_rcv|tcp_v4_rcv|do_softirq")

CRYPTO_DSO = re.compile(r"^(libssl|libcrypto|libgnutls|libnettle|libgcrypt|libSystem\.Security\.Cryptography)")
CRYPTO_SYM = re.compile(r"\baws_lc|\bring::|\bring_core|\brustls|\bEVP_|\bossl_|\bOPENSSL_|_nistz256|\becp_|\bx25519|\bX25519|curve25519|\bfe_mul|\baes|\bAES|aesni|_gcm|gcm_|\bGCM|ghash|sha256|sha512|SHA256|SHA512|\bchacha|poly1305|\bbn_mul|\bbn_sqr|\bBN_|\bcrypto/|javax\.crypto|sun\.security|com\.sun\.crypto|System\.Security\.Cryptography|BouncyCastle|SslStream|\bssl3_|\bSSL_|\btls13|\btls12|\bTls[A-Z]")
COPY = re.compile(r"memmove|memcpy|__memcpy|memset|arraycopy|jlong_disjoint|BlockCopy|Buffer::Memmove|Memmove|CopyTo|copy_nonoverlapping|copy_from_slice|Array::Copy|ArrayCopy|zend_string_init|rep_movs")
ALLOC = re.compile(r"malloc|calloc|realloc|\bfree\b|cfree|_int_free|_int_malloc|tcache|arena_|sysmalloc|mallocgc|runtime\.(gc|scan|mark|sweep|heap|mspan|mcache|mcentral|newobject|growslice|makeslice|bgsweep|nextFree|memclr|wbBuf|gcDrain|greyobject|findObject)|Scavenge|RememberedSet|MarkCompact|MinorMC|Heap::|heap::base|cppgc|SerialFullGC|SerialHeap|DefNewGeneration|TenuredGeneration|G1|PSPromotion|ParallelGC|ZGC|OopOopIterate|CardTable|MemAllocator|ObjAllocator|gc_heap|GCHeap|WKS::|SVR::|_PyObject_GC|PyObject_Malloc|_PyObject_Free|_PyMem|pymalloc|gc_collect|_Py_Dealloc|subtype_dealloc|rb_gc|gc_sweep|gc_mark|gc_marks|heap_page|newobj|rb_newobj|rb_ec_|rb_wb_|zend_mm_|_emalloc|_efree|gc_possible_root|zend_gc|zval_ptr_dtor|rc_dtor|__rust_alloc|__rust_dealloc|je_|mi_")
INTERP_DSO = re.compile(r"^(python3|libpython|php|libphp|libruby|ruby|libjvm|libcoreclr|libclrjit|node)$|^python3\.\d+$|^php\d")
INTERP_SYM = re.compile(r"_PyEval|_Py_|Py[A-Z][A-Za-z]+_|execute_ex|ZEND_|zend_|vm_exec|rb_vm|vm_call|vm_|rb_call|Builtins_|Interpreter|LoadIC|StoreIC|KeyedLoad|Megamorphic|v8::internal|InterpreterRuntime|SharedRuntime|OptoRuntime|JVM_|__tls_get_addr")


def work_of(frames):
    sym, dso = split(frames[-1])
    if dso == "kernel":
        stack = " ".join(f for f in frames)
        if K_FAULT.search(stack): return "kernel: page faults"
        if K_SEND.search(stack): return "kernel: network send"
        if K_RECV.search(stack) or K_NETIRQ.search(stack): return "kernel: network receive"
        if K_MEM.search(stack): return "kernel: memory mapping"
        if K_WAIT.search(stack): return "kernel: waiting & scheduling"
        return "kernel: other"
    if CRYPTO_DSO.search(dso) or CRYPTO_SYM.search(sym): return "TLS crypto"
    if COPY.search(sym): return "memory copy"
    if ALLOC.search(sym): return "allocation & GC"
    if INTERP_DSO.search(dso) or INTERP_SYM.search(sym): return "interpreter / VM"
    return "compiled code"


# ------------------------------------------------------------------ owner
FRAMEWORK = re.compile(r"sqlalchemy|django|org\.hibernate|org\.jooq|org\.springframework|jakarta\.persistence|gorm\.io|jmoiron/sqlx|node_modules/(knex|drizzle-orm|typeorm|sequelize|@prisma|\.prisma)|prisma|Dapper|EntityFrameworkCore|Pomelo|Doctrine|Illuminate|active_record|activerecord|active_support|activesupport|active_model|activemodel|ActiveRecord|ActiveSupport|ActiveModel|/sequel/|Sequel::|diesel|sea_orm|sea_query")
DRIVER_DSO = re.compile(r"^(libmysqlclient|libmariadb|mysqlnd|pdo_mysql|mysqli|mysql2|trilogy|cext|libmysqlcppconn|libmariadbcpp|_mysql|_mysql_connector|_mariadb|MySqlConnector|MySql\.Data)")
DRIVER_SYM = re.compile(r"com\.mysql|org\.mariadb|MySqlConnector|\[MySql\.Data\]|MySql\.Data|go-sql-driver|go-mysql-org|node_modules/(mysql2|mariadb|mysql)/|MySQLdb|pymysql|mysql/connector|mysql\.connector|/mariadb/|py::.*mariadb|mysql2/|Mysql2|Trilogy|trilogy|mysql_common::|mysql::|mysql_async::|sqlx_mysql::|sqlx_core::|mysqlnd|php_mysqlnd|pdo_mysql|mysqli_|mysql_stmt|mysql_fetch|mysql_real|mysql_store|mysql_use|cli_|net_read|net_write|my_net|vio_|mthd_|ma_|mariadb_")
BENCH_SYM = re.compile(r"^t[0-6]$|^touch|bench\.Runner|bench\.fw|/stacks/|runner\.(py|mjs|rb|php)|fw\.(py|mjs|rb|php)|P::T[0-6]|P::Touch|\[runner\]|runner::|fwrunner::|main\.t[0-6]|main\.touch|main\.run|bench\.(touch|run)|harness|sync_drv::|sqlx_drv::|diesel_fw::|sea_fw::|runner::run|fwrunner::run")


def owner_of(frames):
    for f in reversed(frames):
        sym, dso = split(f)
        if dso == "kernel":
            continue
        if FRAMEWORK.search(sym) or FRAMEWORK.search(dso):
            return "framework"
        if DRIVER_DSO.search(dso) or DRIVER_SYM.search(sym):
            return "driver"
        if BENCH_SYM.search(sym):
            return "benchmark"
    return "runtime & stdlib"


def analyze(path):
    work, owner, leaf_top, thread, lib = Counter(), Counter(), Counter(), Counter(), Counter()
    total = 0
    for line in open(path):
        stack, _, n = line.rstrip("\n").rpartition(" ")
        if not stack:
            continue
        n = int(n); frames = stack.split(";")
        thread[frames[0]] += n
        frames = frames[1:]
        if not frames:
            continue
        total += n
        work[work_of(frames)] += n
        owner[owner_of(frames)] += n
        leaf_top[frames[-1]] += n
        lib[split(frames[-1])[1]] += n
    if not total:
        return None
    pct = lambda c: {k: round(100 * v / total, 1) for k, v in c.most_common()}
    return {"work": pct(work), "owner": pct(owner), "lib": pct(Counter(dict(lib.most_common(8)))),
            "top": [[k[:200], round(100 * v / total, 1)] for k, v in leaf_top.most_common(15)],
            "threads": pct(Counter(dict(thread.most_common(6)))), "weight": total}


if __name__ == "__main__":
    out = []
    for f in sorted(glob.glob(f"{ROOT}/*/*/*.folded")):
        srv, stack, name = f.split("/")[-3:]
        test, rest = name.split("-", 1)
        parts = rest[:-len(".folded")].rsplit("-", 2)   # variant-config-rep
        a = analyze(f)
        if a:
            out.append({"server": srv, "stack": stack, "test": test, "variant": parts[0], "config": parts[1], **a})
    json.dump(out, sys.stdout, indent=0)
