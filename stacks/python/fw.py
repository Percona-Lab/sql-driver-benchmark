#!/usr/bin/env python3
"""Phase 3 runner: Python frameworks on top of mysqlclient (the driver measured in Phase 1 as py-mysqlclient).

  sqlalchemy-core  SQLAlchemy 2 Core: Table metadata + select()/insert() constructs on a Connection (NullPool)
  sqlalchemy-orm   SQLAlchemy 2 ORM: mapped classes, Session, entity objects
  django-orm       Django ORM (standalone settings): Model managers, entity objects

default config = the idiom most code uses; tuned = the framework's own performance options (see each test).
Same CLI/env contract and checksums as runner.py (SPEC.md section 5).
"""
import argparse, os, sys

rss_start_kb = None
with open("/proc/self/status") as _f:
    for _l in _f:
        if _l.startswith("VmRSS:"):
            rss_start_kb = int(_l.split()[1])

import bench

E = lambda k, d=None: os.environ.get(k) or d
ap = argparse.ArgumentParser()
for a, d in (("fw", None), ("test", "T0"), ("variant", ""), ("config", "default"), ("server", "ps"), ("out", None)):
    ap.add_argument("--" + a, default=d)
ap.add_argument("--warmup", type=int, default=2)
ap.add_argument("--iters", type=int, default=5)
ap.add_argument("--floor", action="store_true")
A = ap.parse_args()
V, TUNED = A.variant, A.config == "tuned"
ops = 0

TYPES10 = ["int", "bigint", "decimal", "double", "varchar32", "datetime", "date", "tinyint", "varchar255n", "intn"]


def tls_args(tls):
    """mysqlclient connect arguments for a TLS mode (same as the driver runner)."""
    kw = {"ssl_mode": {"off": "DISABLED", "on": "REQUIRED", "verify": "VERIFY_IDENTITY"}[tls]}
    if tls == "verify":
        kw["ssl"] = {"ca": E("DB_CA")}
    return kw


def touch_values(vals_iter):
    """T4 checksum over an iterable of value sequences (column 0 = id, skipped)."""
    nn = isum = slen = n = 0
    for row in vals_iter:
        n += 1
        for v in row[1:]:
            if v is None:
                continue
            nn += 1
            t = type(v)
            if t is int: isum += v
            elif t is str: slen += len(v)
    return nn + isum + slen, n


def touch_docs(vals):
    c = 0
    for v in vals:
        if type(v) is memoryview: v = bytes(v)
        c += len(v) + (sum(v[0::64]) if type(v) is bytes else sum(map(ord, v[0::64])))
    return c


def rowb(i): return ("o'k-" if i % 10 == 0 else "name-") + str(i)


def t5_parts():
    cls, col = V.split("-", 1)
    parse = col.endswith("-parse")
    return cls, col.removesuffix("-parse"), parse


# ====================================================================== SQLAlchemy
class SA:
    def __init__(self, orm):
        import sqlalchemy as sa
        from sqlalchemy.pool import NullPool
        self.sa, self.orm = sa, orm
        self.name = "py-sqlalchemy-orm" if orm else "py-sqlalchemy-core"
        self.lib = f"SQLAlchemy {sa.__version__} on mysqlclient"
        self.NullPool = NullPool
        md = sa.MetaData()
        I, BI, D, F, S, DT, DA, TI = (sa.Integer, sa.BigInteger, sa.Numeric(15, 2), sa.Float, sa.String, sa.DateTime, sa.Date, sa.SmallInteger)
        self.t_int = sa.Table("t_int", md, sa.Column("id", I, primary_key=True), sa.Column("v", I))
        self.t_wide_int = sa.Table("t_wide_int", md, sa.Column("id", I, primary_key=True),
                                   *[sa.Column(f"c{k:03d}", I) for k in range(1, 101)])
        mix = {"int": I, "bigint": BI, "decimal": D, "double": F, "varchar32": S(32), "datetime": DT, "date": DA,
               "tinyint": TI, "varchar255n": S(255), "intn": I}
        self.t_wide_mix = sa.Table("t_wide_mix", md, sa.Column("id", I, primary_key=True),
                                   *[sa.Column(f"c{k:03d}", mix[TYPES10[(k - 1) % 10]]) for k in range(1, 101)])
        self.t_blob = sa.Table("t_blob", md, sa.Column("id", I, primary_key=True), sa.Column("size_class", S(8)),
                               sa.Column("doc", sa.Text), sa.Column("doc_bin", sa.LargeBinary))
        self.t_bulk = sa.Table("t_bulk", md, sa.Column("id", I, primary_key=True), sa.Column("a", I), sa.Column("b", S(32)),
                               sa.Column("c", F))
        if orm:
            from sqlalchemy.orm import registry, Session
            self.Session = Session
            reg = registry()
            self.TInt = type("TInt", (), {}); reg.map_imperatively(self.TInt, self.t_int)
            self.TWideInt = type("TWideInt", (), {}); reg.map_imperatively(self.TWideInt, self.t_wide_int)
            self.TWideMix = type("TWideMix", (), {}); reg.map_imperatively(self.TWideMix, self.t_wide_mix)
            self.TBlob = type("TBlob", (), {}); reg.map_imperatively(self.TBlob, self.t_blob)
            self.TBulk = type("TBulk", (), {}); reg.map_imperatively(self.TBulk, self.t_bulk)
        self.engines = {}

    def engine(self, tls="off", sock=False):
        key = (tls, sock)
        if key not in self.engines:
            host = "localhost" if sock else E("DB_HOST", "127.0.0.1")
            url = self.sa.URL.create("mysql+mysqldb", username=E("DB_USER", "bench"), password=E("DB_PASS", "bench"),
                                     host=host, port=None if sock else int(E("DB_PORT", "3306")), database=E("DB_NAME", "bench"))
            ca = tls_args(tls)
            if sock: ca["unix_socket"] = E("DB_SOCKET")
            self.engines[key] = self.sa.create_engine(url, poolclass=self.NullPool, connect_args=ca)
        return self.engines[key]

    # connection used by the tests
    def open(self, tls):
        self.conn = self.engine(tls).connect()
        if self.orm:
            self.sess = self.Session(bind=self.conn)
        return self

    def close(self):
        if self.orm: self.sess.close()
        self.conn.close()

    def cipher(self):
        r = self.conn.exec_driver_sql("SHOW SESSION STATUS LIKE 'Ssl_cipher'").first()
        return r[1] if r and r[1] else "none"

    def raw(self, sql):
        r = self.conn.exec_driver_sql(sql)
        try: return r.fetchall()
        except Exception: return None
        finally: self.conn.commit()

    def t1(self, tls, sock, n):
        eng = self.engine(tls, sock)
        for _ in range(n):
            if self.orm:
                with self.Session(eng) as s: s.connection()      # a Session checks out a real connection
            else:
                eng.connect().close()

    def t2(self, ids):
        sa = self.sa; s = 0
        if self.orm:
            if TUNED:   # ORM column query (no entity objects)
                q = sa.select(self.TInt.v).where(self.TInt.id == sa.bindparam("i"))
                for i in ids: s += self.sess.execute(q, {"i": i}).scalar_one()
            else:       # entity load, the usual ORM idiom
                for i in ids:
                    s += self.sess.execute(sa.select(self.TInt).where(self.TInt.id == i)).scalar_one().v
        else:
            if TUNED:   # statement built once, bound parameter
                q = sa.select(self.t_int.c.v).where(self.t_int.c.id == sa.bindparam("i"))
                for i in ids: s += self.conn.execute(q, {"i": i}).scalar_one()
            else:       # statement built per call (SQLAlchemy's compiled cache still applies)
                for i in ids: s += self.conn.execute(sa.select(self.t_int.c.v).where(self.t_int.c.id == i)).scalar_one()
        return s

    def rows(self, table, entity, streamed):
        """Yield value sequences (id first) for a SELECT * (Core) or entity objects (ORM)."""
        sa = self.sa
        if self.orm:
            q = sa.select(entity)
            if TUNED or streamed:   # yield_per: server-side cursor + batches, the documented way for large results
                q = q.execution_options(yield_per=1000)
            cols = [c.key for c in table.columns]
            for o in self.sess.scalars(q):
                yield [getattr(o, k) for k in cols]
            self.sess.expunge_all()
        else:
            q = sa.select(table)
            res = self.conn.execution_options(stream_results=True, yield_per=1000).execute(q) if streamed else self.conn.execute(q)
            yield from res

    def t3(self, streamed):
        s = 0
        if self.orm:
            for r in self.rows(self.t_int, self.TInt, streamed): s += r[1]
        else:
            for r in self.rows(self.t_int, None, streamed): s += r.v
        return s

    def t4(self, wide):
        t, e = (self.t_wide_int, getattr(self, "TWideInt", None)) if wide == "int" else (self.t_wide_mix, getattr(self, "TWideMix", None))
        return touch_values(self.rows(t, e, False))

    def t5(self, cls, col):
        sa = self.sa
        if self.orm and not TUNED:
            q = sa.select(self.TBlob).where(self.TBlob.size_class == cls).order_by(self.TBlob.id)
            vals = [getattr(o, col) for o in self.sess.scalars(q)]; self.sess.expunge_all()
        else:
            c = getattr(self.t_blob.c, col)
            q = sa.select(c).where(self.t_blob.c.size_class == cls).order_by(self.t_blob.c.id)
            vals = list((self.sess if self.orm else self.conn).execute(q).scalars())
        return vals

    def t6(self, variant):
        sa = self.sa
        for st in range(1, 1000001, 1000):
            recs = [{"id": i, "a": i * 3, "b": rowb(i), "c": i * 0.5} for i in range(st, st + 1000)]
            if self.orm:
                if variant == "batch":
                    if TUNED:   # ORM bulk INSERT (list of dicts), no unit of work
                        self.sess.execute(sa.insert(self.TBulk), recs)
                    else:       # unit of work: entity objects, flushed with insertmanyvalues batching
                        objs = []
                        for r in recs:
                            o = self.TBulk(); o.id, o.a, o.b, o.c = r["id"], r["a"], r["b"], r["c"]; objs.append(o)
                        self.sess.add_all(objs)
                    self.sess.commit(); self.sess.expunge_all()
                else:
                    raise bench.NA("ORM inserts use the batch variant (unit of work / bulk insert)")
            else:
                if variant == "batch":       # executemany (insertmanyvalues)
                    self.conn.execute(sa.insert(self.t_bulk), recs)
                elif variant == "multiparam":  # one multi-row INSERT ... VALUES construct
                    self.conn.execute(sa.insert(self.t_bulk).values(recs))
                else:
                    raise bench.NA("SQLAlchemy Core builds SQL itself; app-built SQL text is the driver test")
                self.conn.commit()


# ====================================================================== Django
class DJ:
    name = "py-django-orm"

    def __init__(self):
        import django
        from django.conf import settings
        self.lib = f"Django {django.get_version()} on mysqlclient"
        self.dj = django
        self.settings = settings
        self.models = None

    def setup(self, tls):
        if self.models is None:
            opts = tls_args(tls)
            self.settings.configure(
                DATABASES={"default": {"ENGINE": "django.db.backends.mysql", "NAME": E("DB_NAME", "bench"), "USER": E("DB_USER", "bench"),
                                       "PASSWORD": E("DB_PASS", "bench"), "HOST": E("DB_HOST", "127.0.0.1"), "PORT": E("DB_PORT", "3306"),
                                       "CONN_MAX_AGE": 0, "OPTIONS": opts}},
                INSTALLED_APPS=[], USE_TZ=False, DEFAULT_AUTO_FIELD="django.db.models.AutoField")
            self.dj.setup()
            from django.db import models, connections
            self.connections = connections
            m = models

            def model(name, table, fields):
                attrs = {"__module__": __name__, "Meta": type("Meta", (), {"app_label": "bench", "db_table": table, "managed": False})}
                attrs.update(fields)
                return type(name, (m.Model,), attrs)
            self.TInt = model("TInt", "t_int", {"id": m.IntegerField(primary_key=True), "v": m.IntegerField()})
            self.TWideInt = model("TWideInt", "t_wide_int", {"id": m.IntegerField(primary_key=True),
                                  **{f"c{k:03d}": m.IntegerField() for k in range(1, 101)}})
            fmap = {"int": lambda: m.IntegerField(), "bigint": lambda: m.BigIntegerField(),
                    "decimal": lambda: m.DecimalField(max_digits=15, decimal_places=2), "double": lambda: m.FloatField(),
                    "varchar32": lambda: m.CharField(max_length=32), "datetime": lambda: m.DateTimeField(), "date": lambda: m.DateField(),
                    "tinyint": lambda: m.SmallIntegerField(), "varchar255n": lambda: m.CharField(max_length=255, null=True),
                    "intn": lambda: m.IntegerField(null=True)}
            self.TWideMix = model("TWideMix", "t_wide_mix", {"id": m.IntegerField(primary_key=True),
                                  **{f"c{k:03d}": fmap[TYPES10[(k - 1) % 10]]() for k in range(1, 101)}})
            self.TBlob = model("TBlob", "t_blob", {"id": m.IntegerField(primary_key=True), "size_class": m.CharField(max_length=8),
                               "doc": m.TextField(), "doc_bin": m.BinaryField()})
            self.TBulk = model("TBulk", "t_bulk", {"id": m.IntegerField(primary_key=True), "a": m.IntegerField(),
                               "b": m.CharField(max_length=32), "c": m.FloatField()})
            self.models = True
            self.base_opts = opts

    def open(self, tls):
        self.setup(tls)
        self.c = self.connections["default"]
        self.c.ensure_connection()
        return self

    def close(self): self.c.close()

    def cipher(self):
        with self.c.cursor() as cur:
            cur.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'"); r = cur.fetchone()
        return r[1] if r and r[1] else "none"

    def raw(self, sql):
        with self.c.cursor() as cur:
            cur.execute(sql)
            try: return cur.fetchall()
            except Exception: return None

    def t1(self, tls, sock, n):
        from django.db.backends.mysql.base import DatabaseWrapper
        cfg = dict(self.c.settings_dict)
        cfg["OPTIONS"] = dict(tls_args(tls))
        if sock:
            cfg["HOST"] = E("DB_SOCKET")
        for _ in range(n):   # a fresh connection through Django's backend wrapper (what CONN_MAX_AGE=0 does per request)
            w = DatabaseWrapper(cfg, alias="t1"); w.ensure_connection(); w.close()

    def t2(self, ids):
        s = 0
        if TUNED:
            q = self.TInt.objects
            for i in ids: s += q.filter(id=i).values_list("v", flat=True)[0]
        else:
            for i in ids: s += self.TInt.objects.get(id=i).v
        return s

    def rows(self, model, streamed):
        names = [f.attname for f in model._meta.concrete_fields]
        if TUNED:     # values_list: tuples, no model instances
            qs = model.objects.values_list(*names)
            yield from (qs.iterator(chunk_size=2000) if streamed else qs)
        else:
            qs = model.objects.all()
            for o in (qs.iterator(chunk_size=2000) if streamed else qs):
                yield [getattr(o, n) for n in names]

    def t3(self, streamed):
        s = 0
        for r in self.rows(self.TInt, streamed): s += r[1]
        return s

    def t4(self, wide):
        return touch_values(self.rows(self.TWideInt if wide == "int" else self.TWideMix, False))

    def t5(self, cls, col):
        qs = self.TBlob.objects.filter(size_class=cls).order_by("id")
        if TUNED:
            return list(qs.values_list(col, flat=True))
        return [getattr(o, col) for o in qs.only(col)]

    def t6(self, variant):
        if variant != "batch":
            raise bench.NA("Django inserts use bulk_create (the batch variant)")
        from django.db import transaction
        for st in range(1, 1000001, 1000):
            objs = [self.TBulk(id=i, a=i * 3, b=rowb(i), c=i * 0.5) for i in range(st, st + 1000)]
            with transaction.atomic():
                self.TBulk.objects.bulk_create(objs, batch_size=1000)


# ====================================================================== main
FW = {"sqlalchemy-core": lambda: SA(False), "sqlalchemy-orm": lambda: SA(True), "django-orm": DJ}


def main():
    global ops
    D = FW[A.fw]()
    meta = dict(stack=D.name, lib=D.lib, test=A.test, variant=V, config=A.config, server=A.server, python=sys.version.split()[0])
    tls = E("DB_TLS", "off")
    if A.test == "T1" and ("resume" in V or "@" in V):
        raise bench.NA("frameworks are measured on tcp, socket, tls and tls-verify")
    if A.test == "T0":
        bench.perf_open(); it = bench.Iter(); it.begin()
        D.open(tls); D.raw("SELECT 1"); r = it.end(1)
        meta.update(tls=D.cipher(), ops_per_iter=1, warmup=0, rss_start_kb=rss_start_kb)
        bench.write(A.out, meta, [r]); return
    t1tls = "verify" if V.startswith("tls-verify") else "on" if V.startswith("tls") else "off"
    D.open(t1tls if A.test == "T1" else tls)
    meta["tls"] = D.cipher()
    if A.test == "T1":
        D.close(); D.open("off")
    ids = None
    if A.test == "T2":
        if V != "param":
            raise bench.NA("frameworks bind parameters themselves (variant: param)")
        with open(os.path.join(E("DATA_DIR", "/root/bench/data"), "ids_200k.txt")) as f:
            ids = [int(x) for x in f]
    if A.test == "T3" and V.startswith("binary"):
        raise bench.NA("mysqlclient has no server-side prepared statements")
    if A.test == "T4" and V.endswith("binary"):
        raise bench.NA("mysqlclient has no server-side prepared statements")

    def step():
        global ops
        if A.test == "T1":
            n = 2000 if t1tls != "off" else 3000
            D.t1(t1tls, V == "socket", n); ops = n; return n
        if A.test == "T2":
            ops = len(ids); return D.t2(ids)
        if A.test == "T3":
            ops = 1000000; return D.t3("streamed" in V)
        if A.test == "T4":
            ck, n = D.t4("int" if V.startswith("int") else "mix"); ops = n * 100; return ck
        if A.test == "T5":
            import json
            cls, col, parse = t5_parts(); tot = 0; ck = 0
            for _ in range(20):
                vals = D.t5(cls, col)
                ck = touch_docs(vals); tot += sum(len(v) for v in vals)
                if parse:
                    for v in vals: json.loads(v)
            ops = tot // 1024; return ck
        if A.test == "T6":
            D.t6(V); ops = 1000; return ""

    meta["rss_baseline_kb"] = bench.status_kb("VmRSS:")
    bench.perf_open()
    iters = []
    for i in range(A.warmup + A.iters):
        if A.test == "T6": D.raw("TRUNCATE TABLE t_bulk")
        if i < A.warmup:
            step(); continue
        it = bench.Iter(); it.begin(); ck = step(); r = it.end(ck)
        if A.test == "T6":
            x = D.raw("SELECT COUNT(*), SUM(a), SUM(CHAR_LENGTH(b)) FROM t_bulk")[0]
            r["checksum"] = ":".join(str(int(v)) for v in x)
        iters.append(r)
    meta.update(ops_per_iter=ops, warmup=A.warmup)
    bench.write(A.out, meta, iters)
    D.close()


try:
    main()
except bench.NA as e:
    print(f"n/a: {e}", file=sys.stderr); sys.exit(3)
