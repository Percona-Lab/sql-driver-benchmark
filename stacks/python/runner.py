#!/usr/bin/env python3
"""Python runner: mysqlclient, mysql-connector-python (C ext / pure), PyMySQL, MariaDB Connector/Python.

usage: runner.py --driver mysqlclient --test T3 --variant text-buffered [--config default] ...
Same CLI and env contract as the C runner (SPEC.md section 5).
"""
import argparse, os, sys, time

rss_start_kb = None
with open("/proc/self/status") as _f:  # before any driver import (T0)
    for _l in _f:
        if _l.startswith("VmRSS:"):
            rss_start_kb = int(_l.split()[1])

import bench

E = lambda k, d=None: os.environ.get(k) or d
ap = argparse.ArgumentParser()
for a, d in (("driver", None), ("test", "T0"), ("variant", ""), ("config", "default"), ("server", "ps"), ("out", None)):
    ap.add_argument("--" + a, default=d)
ap.add_argument("--warmup", type=int, default=2)
ap.add_argument("--iters", type=int, default=5)
ap.add_argument("--floor", action="store_true")
A = ap.parse_args()
V = A.variant


# ------------------------------------------------------------------ adapters
class Adapter:
    """Driver differences. tls: 'off' | 'on' (no verification) | 'verify'."""
    paramstyle = "%s"
    prepared = False       # server-side prepared statements available
    streaming = True
    escapes = True

    def common(self, sock):
        kw = dict(user=E("DB_USER", "bench"), password=E("DB_PASS", "bench"), database=E("DB_NAME", "bench"))
        if sock:
            kw.update(unix_socket=E("DB_SOCKET"))
        else:
            kw.update(host=E("DB_HOST", "127.0.0.1"), port=int(E("DB_PORT", "3306")))
        return kw


class MySQLclient(Adapter):
    name = "py-mysqlclient"

    def __init__(self):
        import MySQLdb, MySQLdb.cursors
        self.m, self.cur_mod = MySQLdb, MySQLdb.cursors
        self.lib = f"mysqlclient {MySQLdb.version_info} / libmysqlclient {MySQLdb._mysql.get_client_info()}"

    def connect(self, tls="off", sock=False, resume=False):
        kw = self.common(sock)
        if "unix_socket" in kw:
            kw["host"] = "localhost"
        kw["ssl_mode"] = {"off": "DISABLED", "on": "REQUIRED", "verify": "VERIFY_IDENTITY"}[tls]
        if tls == "verify":
            kw["ssl"] = {"ca": E("DB_CA")}
        c = self.m.connect(**kw)
        c.autocommit(True)
        return c

    def cursor(self, c, streamed=False, binary=False):
        if binary: raise bench.NA("mysqlclient has no server-side prepared statements")
        return c.cursor(self.cur_mod.SSCursor) if streamed else c.cursor()

    def escape(self, c, s): return c.literal(s).decode()


class PyMySQL(Adapter):
    name = "py-pymysql"

    def __init__(self):
        import pymysql, pymysql.cursors
        self.m, self.cur_mod = pymysql, pymysql.cursors
        self.lib = f"PyMySQL {pymysql.__version__}"

    def connect(self, tls="off", sock=False, resume=False):
        kw = self.common(sock)
        if tls == "on":
            kw.update(ssl={}, ssl_verify_cert=False, ssl_verify_identity=False)
        elif tls == "verify":
            kw.update(ssl_ca=E("DB_CA"), ssl_verify_cert=True, ssl_verify_identity=True)
        return self.m.connect(autocommit=True, **kw)

    def cursor(self, c, streamed=False, binary=False):
        if binary: raise bench.NA("PyMySQL has no server-side prepared statements")
        return c.cursor(self.cur_mod.SSCursor) if streamed else c.cursor()

    def escape(self, c, s): return c.escape(s)


class Connector(Adapter):
    """mysql-connector-python; pure=True forces the pure-Python protocol implementation."""
    prepared = True

    def __init__(self, pure):
        import mysql.connector
        self.m, self.pure = mysql.connector, pure
        self.name = "py-mysql-connector-" + ("pure" if pure else "c")
        if not pure and not mysql.connector.HAVE_CEXT:
            raise SystemExit("C extension not available")
        self.lib = f"mysql-connector-python {mysql.connector.__version__} ({'pure' if pure else 'C ext'})"

    def connect(self, tls="off", sock=False, resume=False):
        kw = self.common(sock)
        kw.update(use_pure=self.pure, autocommit=True)
        if tls == "off":
            kw["ssl_disabled"] = True
        elif tls == "on":
            kw.update(ssl_disabled=False, ssl_verify_cert=False)
        else:
            kw.update(ssl_disabled=False, ssl_ca=E("DB_CA"), ssl_verify_cert=True, ssl_verify_identity=True)
        return self.m.connect(**kw)

    def cursor(self, c, streamed=False, binary=False):
        if binary:
            return c.cursor(prepared=True)          # binary protocol; rows fetched on demand
        return c.cursor(buffered=not streamed)

    def escape(self, c, s):
        if self.pure:
            return "'" + c.converter.escape(s) + "'"
        return "'" + c._cmysql.escape_string(s).decode() + "'"


class MariaDB(Adapter):
    name = "py-mariadb"
    paramstyle = "?"
    prepared = True

    def __init__(self):
        import mariadb
        self.m = mariadb
        self.lib = f"mariadb {mariadb.__version__} / Connector/C {mariadb.client_version_info}"

    def connect(self, tls="off", sock=False, resume=False):
        kw = self.common(sock)
        kw["autocommit"] = True
        if tls == "off":
            kw["ssl"] = False
        elif tls == "on":
            kw.update(ssl=True, ssl_verify_cert=False)
        else:
            kw.update(ssl=True, ssl_ca=E("DB_CA"), ssl_verify_cert=True)
        return self.m.connect(**kw)

    def cursor(self, c, streamed=False, binary=False):
        return c.cursor(buffered=not streamed, binary=binary)

    def escape(self, c, s): return "'" + c.escape_string(s) + "'"


ADAPTERS = {"mysqlclient": MySQLclient, "pymysql": PyMySQL, "mysql-connector-c": lambda: Connector(False),
            "mysql-connector-pure": lambda: Connector(True), "mariadb": MariaDB}
if A.config != "default":
    print("n/a: Python driver options are covered by the explicit variants (streaming, prepared, executemany)",
          file=sys.stderr); sys.exit(3)

try:
    D = ADAPTERS[A.driver]()
except bench.NA as e:
    print(f"n/a: {e}", file=sys.stderr); sys.exit(3)
TLS = E("DB_TLS", "off")
ops = 0


def cipher(c):
    cur = c.cursor(); cur.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
    r = cur.fetchall(); cur.close()
    return (r[0][1] if r and r[0][1] else "none")


def q(c, sql):
    cur = c.cursor(); cur.execute(sql)
    try: cur.fetchall()
    except Exception: pass
    cur.close()


# ------------------------------------------------------------------ tests
def t1(_c):
    global ops
    tls = "verify" if V.startswith("tls-verify") else "on" if V.startswith("tls") else "off"
    n = 2000 if tls != "off" else 5000
    for _ in range(n):
        D.connect(tls, V == "socket").close()
    ops = n
    return n


def t2(c):
    global ops
    ids = IDS; s = 0
    if V == "literal":
        cur = c.cursor()
        for i in ids:
            cur.execute(f"SELECT v FROM t_int WHERE id = {i}")
            s += cur.fetchone()[0]
    elif V == "param":
        cur = c.cursor(); sql = f"SELECT v FROM t_int WHERE id = {D.paramstyle}"
        for i in ids:
            cur.execute(sql, (i,))
            s += cur.fetchone()[0]
    else:  # prepared: server-side prepare once, execute N
        if not D.prepared: raise bench.NA(f"{A.driver} has no server-side prepared statements")
        cur = D.cursor(c, binary=True); sql = f"SELECT v FROM t_int WHERE id = {D.paramstyle}"
        for i in ids:
            cur.execute(sql, (i,))
            s += cur.fetchone()[0]
    cur.close()
    ops = len(ids)
    return s


def t3(c):
    global ops
    cur = D.cursor(c, streamed="streamed" in V, binary=V.startswith("binary"))
    cur.execute("SELECT v FROM t_int")
    s = 0
    for (v,) in cur:
        s += v
    cur.close()
    ops = 1000000
    return s


def touch_rows(rows):
    nn = isum = slen = n = 0
    for row in rows:
        n += 1
        for v in row[1:]:
            if v is None:
                continue
            nn += 1
            t = type(v)
            if t is int: isum += v
            elif t is str: slen += len(v)
    return nn + isum + slen, n


def t4(c):
    global ops
    cur = D.cursor(c, binary=V.endswith("binary"))
    cur.execute("SELECT * FROM t_wide_int" if V.startswith("int") else "SELECT * FROM t_wide_mix")
    ck, n = touch_rows(cur)
    cur.close()
    ops = n * 100
    return ck


def touch_docs(vals):
    c = b = 0
    for v in vals:
        n = len(v); b += n
        c += n + (sum(v[0::64]) if type(v) is bytes else sum(map(ord, v[0::64])))
    return c, b


def t5_parts():
    cls, col = V.split("-", 1)
    parse = col.endswith("-parse")
    return f"SELECT {col.removesuffix('-parse')} FROM t_blob WHERE size_class = '{cls}' ORDER BY id", parse


def t5(c):
    global ops
    import json
    sql, parse = t5_parts(); ck = tot = 0
    for _ in range(20):
        cur = c.cursor(); cur.execute(sql)
        vals = [r[0] for r in cur]
        cur.close()
        ck, b = touch_docs(vals); tot += b
        if parse:
            for v in vals: json.loads(v)
    ops = tot // 1024
    return ck


def rowb(i): return ("o'k-" if i % 10 == 0 else "name-") + str(i)


def t6(c):
    global ops
    cur = c.cursor(); ph = D.paramstyle
    if V == "sqltext":
        if not D.escapes: raise bench.NA("no escaping function")
        for start in range(1, 1000001, 1000):
            vals = ",".join(f"({i},{i * 3},{D.escape(c, rowb(i))},{i * 0.5!r})" for i in range(start, start + 1000))
            cur.execute("INSERT INTO t_bulk (id,a,b,c) VALUES " + vals)
    elif V == "multiparam":
        sql = "INSERT INTO t_bulk (id,a,b,c) VALUES " + ",".join([f"({ph},{ph},{ph},{ph})"] * 1000)
        for start in range(1, 1000001, 1000):
            params = []
            for i in range(start, start + 1000):
                params += (i, i * 3, rowb(i), i * 0.5)
            cur.execute(sql, params)
    else:  # batch: executemany (multi-row rewrite in mysqlclient/PyMySQL/connector, bulk execute in mariadb)
        sql = f"INSERT INTO t_bulk (id,a,b,c) VALUES ({ph},{ph},{ph},{ph})"
        for start in range(1, 1000001, 1000):
            try:
                cur.executemany(sql, [(i, i * 3, rowb(i), i * 0.5) for i in range(start, start + 1000)])
            except Exception as e:
                if "Bulk" in str(e): raise bench.NA("server has no bulk execute (MariaDB-only protocol extension)")
                raise
    cur.close()
    ops = 1000
    return ""


# ------------------------------------------------------------------ language floor: touch loops over in-memory data
FLOOR = {}


def floor(c):
    global ops
    if A.test == "T3":
        data = FLOOR.setdefault("d", [(((i + 1) * 7919) % 1000003,) for i in range(1000000)])
        s = 0
        for (v,) in data: s += v
        ops = 1000000; return s
    if A.test == "T4":
        if "d" not in FLOOR:
            cur = c.cursor(); cur.execute("SELECT * FROM t_wide_int" if V.startswith("int") else "SELECT * FROM t_wide_mix")
            FLOOR["d"] = list(cur); cur.close()
        ck, n = touch_rows(FLOOR["d"]); ops = n * 100; return ck
    if A.test == "T5":
        if "d" not in FLOOR:
            cur = c.cursor(); cur.execute(t5_parts()[0]); FLOOR["d"] = [r[0] for r in cur]; cur.close()
        tot = 0
        for _ in range(20):
            ck, b = touch_docs(FLOOR["d"]); tot += b
        ops = tot // 1024; return ck
    raise bench.NA("floor defined for T3-T5")


# ------------------------------------------------------------------ main
def main():
    global IDS
    meta = dict(stack=D.name, lib=D.lib, test=A.test, variant=V, config=A.config, server=A.server,
                python=sys.version.split()[0])
    if A.test == "T0":
        bench.perf_open(); it = bench.Iter(); it.begin()
        c = D.connect(TLS); q(c, "SELECT 1")
        r = it.end(1); meta.update(tls=cipher(c), ops_per_iter=1, warmup=0, rss_start_kb=rss_start_kb)
        bench.write(A.out, meta, [r]); return
    if A.test == "T1" and "resume" in V:
        raise bench.NA("Python drivers expose no TLS session resumption")
    c = D.connect(TLS)
    if A.test == "T1":
        c.close()
        tls = "verify" if V.startswith("tls-verify") else "on" if V.startswith("tls") else "off"
        c2 = D.connect(tls, V == "socket"); meta["tls"] = cipher(c2); c2.close(); c = D.connect("off")
    else:
        meta["tls"] = cipher(c)
    if A.test == "T2":
        with open(os.path.join(E("DATA_DIR", "/root/bench/data"), "ids_200k.txt")) as f:
            IDS = [int(x) for x in f]
    fn = floor if A.floor else {"T1": t1, "T2": t2, "T3": t3, "T4": t4, "T5": t5, "T6": t6}[A.test]
    bench.perf_open()
    iters = []
    for i in range(A.warmup + A.iters):
        if A.test == "T6": q(c, "TRUNCATE TABLE t_bulk")
        if i < A.warmup:
            fn(c); continue
        it = bench.Iter(); it.begin(); ck = fn(c); r = it.end(ck)
        if A.test == "T6" and not A.floor:
            cur = c.cursor(); cur.execute("SELECT COUNT(*), SUM(a), SUM(CHAR_LENGTH(b)) FROM t_bulk")
            r["checksum"] = ":".join(str(int(x)) for x in cur.fetchone()); cur.close()
        iters.append(r)
    meta.update(ops_per_iter=ops, warmup=A.warmup)
    bench.write(A.out, meta, iters)
    c.close()


try:
    main()
except bench.NA as e:
    print(f"n/a: {e}", file=sys.stderr); sys.exit(3)
