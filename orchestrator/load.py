#!/usr/bin/env python3
"""Create the benchmark schema, users and data on one server, then compute the
expected checksums from what the server actually returns (MySQL normalizes JSON
on output, so checksums are per server).

usage: load.py ps|maria   (run on the bench host as root; uses the CLI over the socket)
"""
import json, os, random, subprocess, sys, zlib

SRV = sys.argv[1]
CLI = {"ps": ["mysql", "-uroot"],
       "maria": ["/opt/mariadb/bin/mariadb", "-uroot", "-S", "/run/mariadb/mariadb.sock"]}[SRV]
OUT = f"/root/bench/data/expected-{SRV}.json"
os.makedirs(os.path.dirname(OUT), exist_ok=True)


def sql(text, db="bench", capture=False):
    args = CLI + ([db] if db else []) + (["-N", "-B", "--raw"] if capture else [])
    r = subprocess.run(args, input=text.encode(), capture_output=True)
    if r.returncode:
        sys.exit(r.stderr.decode())
    return r.stdout


def esc(s):
    return s.replace("\\", "\\\\").replace("'", "\\'")


# ---------------------------------------------------------------- schema/users
users = {"ps": """
CREATE USER IF NOT EXISTS 'bench'@'%' IDENTIFIED WITH caching_sha2_password BY 'bench';
GRANT ALL ON bench.* TO 'bench'@'%';
""", "maria": """
DROP USER IF EXISTS ''@'localhost';
DROP USER IF EXISTS ''@'dbdrivers';
CREATE USER IF NOT EXISTS 'bench'@'%' IDENTIFIED BY 'bench';
CREATE USER IF NOT EXISTS 'bench_ed'@'%' IDENTIFIED VIA ed25519 USING PASSWORD('bench');
GRANT ALL ON bench.* TO 'bench'@'%';
GRANT ALL ON bench.* TO 'bench_ed'@'%';
"""}[SRV]
sql("DROP DATABASE IF EXISTS bench; CREATE DATABASE bench CHARACTER SET utf8mb4;" + users, db=None)

TYPES = ["INT NOT NULL", "BIGINT NOT NULL", "DECIMAL(15,2) NOT NULL", "DOUBLE NOT NULL",
         "VARCHAR(32) NOT NULL", "DATETIME(6) NOT NULL", "DATE NOT NULL", "TINYINT NOT NULL",
         "VARCHAR(255) NULL", "INT NULL"]
cols_int = ",".join(f"c{k:03d} INT NOT NULL" for k in range(1, 101))
cols_mix = ",".join(f"c{k:03d} {TYPES[(k - 1) % 10]}" for k in range(1, 101))
sql(f"""
CREATE TABLE t_int (id INT PRIMARY KEY, v INT NOT NULL) ENGINE=InnoDB;
CREATE TABLE t_wide_int (id INT PRIMARY KEY, {cols_int}) ENGINE=InnoDB;
CREATE TABLE t_wide_mix (id INT PRIMARY KEY, {cols_mix}) ENGINE=InnoDB;
CREATE TABLE t_blob (id INT PRIMARY KEY, size_class VARCHAR(8) NOT NULL, doc JSON NOT NULL,
                     doc_bin LONGBLOB NOT NULL, KEY (size_class)) ENGINE=InnoDB;
CREATE TABLE t_bulk (id INT PRIMARY KEY, a INT NOT NULL, b VARCHAR(32) NOT NULL, c DOUBLE NOT NULL) ENGINE=InnoDB;
CREATE TABLE digits (d INT PRIMARY KEY);
INSERT INTO digits VALUES (0),(1),(2),(3),(4),(5),(6),(7),(8),(9);
INSERT INTO t_int (id, v)
  SELECT n + 1, ((n + 1) * 7919) % 1000003 FROM (
    SELECT a.d + b.d*10 + c.d*100 + d.d*1000 + e.d*10000 + f.d*100000 AS n
    FROM digits a, digits b, digits c, digits d, digits e, digits f) x;
DROP TABLE digits;
""")

# ---------------------------------------------------------------- wide tables
def mix_value(r, k):
    t = (k - 1) % 10
    if t == 0: return (r * 31 + k * 7) % 100000
    if t == 1: return r * 1000003 + k
    if t == 2: return "%d.%02d" % divmod((r * 17 + k) % 10000000, 100)
    if t == 3: return r * 1.5 + k * 0.25
    if t == 4: return f"s{r}-{k}"
    if t == 5:
        s = r * 60 + k
        return "2020-01-%02d %02d:%02d:%02d.%06d" % (1 + s // 86400 % 28, s // 3600 % 24, s // 60 % 60, s % 60, r % 1000000)
    if t == 6:
        d = (r + k) % 3650
        return "%04d-%02d-%02d" % (2000 + d // 336, 1 + d // 28 % 12, 1 + d % 28)
    if t == 7: return (r + k) % 128
    if t == 8: return None if (r + k) % 10 == 0 else "x" * ((r * k) % 200 + 10)
    if t == 9: return None if (r * 3 + k) % 10 == 0 else r - k


def lit(v):
    if v is None: return "NULL"
    if isinstance(v, str): return f"'{esc(v)}'"
    return repr(v)


for table, gen in (("t_wide_int", lambda r, k: (r * 131 + k * 17) % 1000000), ("t_wide_mix", mix_value)):
    stmts = []
    for start in range(1, 10001, 500):
        rows = [f"({r}," + ",".join(lit(gen(r, k)) for k in range(1, 101)) + ")" for r in range(start, start + 500)]
        stmts.append(f"INSERT INTO {table} VALUES " + ",".join(rows) + ";")
    sql("\n".join(stmts))

# ---------------------------------------------------------------- blobs
def make_doc(i, size):
    rnd = random.Random(i)
    base = {"id": i, "name": f"doc-{i}", "created": "2026-01-01T00:00:00Z", "tags": ["alpha", "beta", "gamma"]}
    head = json.dumps(base, separators=(",", ":"))[:-1] + ',"items":['
    parts, cur = [], len(head) + 2
    while True:
        it = json.dumps({"k": len(parts), "score": rnd.randint(0, 10**6),
                         "label": "".join(rnd.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(24))},
                        separators=(",", ":"))
        if cur + len(it) + (1 if parts else 0) > size:
            break
        cur += len(it) + (1 if parts else 0)
        parts.append(it)
    return head + ",".join(parts) + "]}"


classes = {"1k": (1, lambda i: 1024), "10k": (1001, lambda i: 10240), "100k": (2001, lambda i: 102400),
           "mix": (3001, lambda i: [1024, 10240, 102400][0 if i % 20 < 14 else (1 if i % 20 < 19 else 2)])}
for cls, (start, size) in classes.items():
    batch, blen = [], 0
    for i in range(start, start + 1000):
        d = esc(make_doc(i, size(i)))
        batch.append(f"({i},'{cls}','{d}','{d}')"); blen += len(d)
        if blen > 8_000_000:
            sql("INSERT INTO t_blob VALUES " + ",".join(batch) + ";"); batch, blen = [], 0
    if batch:
        sql("INSERT INTO t_blob VALUES " + ",".join(batch) + ";")
sql("ANALYZE TABLE t_int, t_wide_int, t_wide_mix, t_blob;")

# ---------------------------------------------------------------- expected checksums
def touch(b):
    """T5 touch: length + sum of code units at stride 64 (ASCII, so bytes == chars)."""
    return len(b) + sum(b[0::64])


exp = {"server": SRV, "version": sql("SELECT VERSION()", capture=True).decode().strip()}
exp["T3"] = int(sql("SELECT SUM(v) FROM t_int", capture=True))
exp["T2_ids"] = "ids_200k.txt"
rnd = random.Random(20261117)
ids = [rnd.randint(1, 1000000) for _ in range(200000)]
with open("/root/bench/data/ids_200k.txt", "w") as f:
    f.write("\n".join(map(str, ids)) + "\n")
exp["T2"] = sum(((i * 7919) % 1000003) for i in ids)
exp["T4_int"] = int(sql("SELECT " + "+".join(f"SUM(c{k:03d})" for k in range(1, 101)) + " + 1000000 FROM t_wide_int", capture=True))
# mix: non-null cells + sum of integer-family values + sum of string lengths
nn = "+".join(f"COUNT(c{k:03d})" for k in range(1, 101))
ints = "+".join(f"COALESCE(SUM(c{k:03d}),0)" for k in range(1, 101) if (k - 1) % 10 in (0, 1, 7, 9))
strs = "+".join(f"COALESCE(SUM(CHAR_LENGTH(c{k:03d})),0)" for k in range(1, 101) if (k - 1) % 10 in (4, 8))
exp["T4_mix"] = int(sql(f"SELECT {nn} + {ints} + {strs} FROM t_wide_mix", capture=True))
exp["T5"] = {}
for cls in classes:
    for col in ("doc", "doc_bin"):
        out = sql(f"SELECT {col} FROM t_blob WHERE size_class='{cls}' ORDER BY id", capture=True)
        vals = out.rstrip(b"\n").split(b"\n")
        assert len(vals) == 1000, (cls, col, len(vals))
        exp["T5"][f"{cls}-{col}"] = {"checksum": sum(touch(v) for v in vals), "bytes": sum(len(v) for v in vals)}
# T6: verified on the server after each iteration
exp["T6"] = {"rows": 1000000, "sum_a": sum(i * 3 for i in range(1, 1000001)),
             "sum_len_b": sum(len(("o'k-" if i % 10 == 0 else "name-") + str(i)) for i in range(1, 1000001))}
with open(OUT, "w") as f:
    json.dump(exp, f, indent=1)
print(json.dumps({k: v for k, v in exp.items() if k != "T5"}), "\nT5:", exp["T5"])
