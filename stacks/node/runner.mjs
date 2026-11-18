// Node.js runner: mysql2, mariadb (MariaDB Connector/Node.js), mysql (legacy).
// Same CLI/env contract as the other runners (SPEC.md section 5).
import fs from "node:fs";
import path from "node:path";
import { PerformanceObserver } from "node:perf_hooks";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
// read a package version from node_modules (some packages' export maps block require("pkg/package.json"))
const pkgVersion = name => JSON.parse(fs.readFileSync(new URL(`./node_modules/${name}/package.json`, import.meta.url), "utf8")).version;

const rssStartKb = statusKb("VmRSS:");
const A = { driver: "mysql2", test: "T0", variant: "", config: "default", server: "ps", out: null, warmup: 2, iters: 5, floor: false };
for (let i = 2; i < process.argv.length; i++) {
  const k = process.argv[i].replace(/^--/, "");
  if (k === "floor") A.floor = true; else A[k] = ["warmup", "iters"].includes(k) ? +process.argv[++i] : process.argv[++i];
}
const V = A.variant, E = (k, d) => process.env[k] || d;
class NA extends Error {}

// ------------------------------------------------------------------ harness
function statusKb(key) {
  for (const l of fs.readFileSync("/proc/self/status", "utf8").split("\n")) if (l.startsWith(key)) return +l.split(/\s+/)[1];
  return -1;
}
function srvTicks() {
  const pid = process.env.MYSQLD_PID; if (!pid) return -1;
  try { const s = fs.readFileSync(`/proc/${pid}/stat`, "utf8"); const f = s.slice(s.lastIndexOf(")") + 2).split(" "); return +f[11] + +f[12]; }
  catch { return -1; }
}
let ctl = null, ack = null;
function perfOpen() { if (process.env.PERF_CTL && process.env.PERF_ACK) { ctl = fs.openSync(process.env.PERF_CTL, "w"); ack = fs.openSync(process.env.PERF_ACK, "r"); } }
function perf(cmd) { if (ctl === null) return; fs.writeSync(ctl, cmd); fs.readSync(ack, Buffer.alloc(8)); }
let gcCount = 0, gcMs = 0;
new PerformanceObserver(l => { for (const e of l.getEntries()) { gcCount++; gcMs += e.duration; } }).observe({ entryTypes: ["gc"] });
const cpuNs = () => { const u = process.cpuUsage(); return (u.user + u.system) * 1000; };
class Meter {
  begin() { fs.writeFileSync("/proc/self/clear_refs", "5"); this.gc = gcCount; this.gcMs = gcMs; this.srv = srvTicks(); perf("enable\n"); this.wall = process.hrtime.bigint(); this.cpu = cpuNs(); }
  end(ck) {
    const cpu = cpuNs(), wall = process.hrtime.bigint(); perf("disable\n"); const s = srvTicks();
    return { cpu_ns: cpu - this.cpu, wall_ns: Number(wall - this.wall), srv_ticks: s >= 0 && this.srv >= 0 ? s - this.srv : -1,
      rss_peak_kb: statusKb("VmHWM:"), rss_end_kb: statusKb("VmRSS:"), checksum: String(ck), gc_count: gcCount - this.gc, gc_ms: Math.round(gcMs - this.gcMs) };
  }
}

// ------------------------------------------------------------------ adapters
const INT_T = new Set([1, 2, 3, 8, 9]), STR_T = new Set([15, 253, 254]);
function tlsOpt(tls) {
  if (tls === "off") return undefined;
  if (tls === "on") return { rejectUnauthorized: false };
  return { ca: fs.readFileSync(E("DB_CA")), rejectUnauthorized: true };
}
function base(sock) {
  const o = { user: E("DB_USER", "bench"), password: E("DB_PASS", "bench"), database: E("DB_NAME", "bench") };
  if (sock) o.socketPath = E("DB_SOCKET"); else Object.assign(o, { host: E("DB_HOST", "127.0.0.1"), port: +E("DB_PORT", "3306") });
  return o;
}
const tuned = A.config === "tuned";

const Mysql2 = {
  name: "node-mysql2", mod: () => require("mysql2/promise"),
  lib() { return "mysql2 " + pkgVersion("mysql2") + " (node " + process.version + ")"; },
  async connect(tls = "off", sock = false) {
    const o = { ...base(sock), jsonStrings: true, rowsAsArray: tuned };
    const t = tlsOpt(tls); if (t) o.ssl = t;
    return this.mod().createConnection(o);
  },
  close: c => c.end(),
  query: async (c, sql, p) => (await c.query(sql, p))[0],
  queryMeta: async (c, sql, binary) => { const [rows, fields] = binary ? await c.execute(sql) : await c.query(sql); return [rows, fields.map(f => f.columnType)]; },
  execute: async (c, sql, p) => (await c.execute(sql, p))[0],
  async *stream(c, sql, binary) {
    if (binary) throw new NA("mysql2 execute() cannot stream rows");
    yield* c.connection.query(sql).stream();
  },
  escape: (c, s) => c.escape(s),
  async batch(c, rows) { await c.query("INSERT INTO t_bulk (id,a,b,c) VALUES ?", [rows]); }, // nested-array multi-row expansion
};

const MariaDB = {
  name: "node-mariadb", mod: () => require("mariadb"),
  lib() { return "mariadb " + pkgVersion("mariadb") + " (node " + process.version + ")"; },
  async connect(tls = "off", sock = false) {
    const o = { ...base(sock), autoJsonMap: false, jsonStrings: true, rowsAsArray: tuned };
    const t = tlsOpt(tls); o.ssl = t || false;
    return this.mod().createConnection(o);
  },
  close: c => c.end(),
  query: (c, sql, p) => c.query(sql, p),
  async queryMeta(c, sql, binary) { const rows = binary ? await c.execute(sql) : await c.query(sql); return [rows, rows.meta.map(m => m.columnType)]; },
  execute: (c, sql, p) => c.execute(sql, p),
  async *stream(c, sql, binary) {
    if (binary) { const p = await c.prepare(sql); try { yield* p.executeStream([]); } finally { p.close(); } }
    else yield* c.queryStream(sql);
  },
  escape: (c, s) => c.escape(s),
  async batch(c, rows) {
    try { await c.batch("INSERT INTO t_bulk (id,a,b,c) VALUES (?,?,?,?)", rows); }
    catch (e) { if (/bulk/i.test(e.message)) throw new NA("server has no bulk execute"); throw e; }
  },
};

const Legacy = {
  name: "node-mysql", mod: () => require("mysql"),
  lib() { return "mysql " + pkgVersion("mysql") + " (node " + process.version + ")"; },
  connect(tls = "off", sock = false) {
    const o = base(sock); const t = tlsOpt(tls); if (t) o.ssl = t;
    const c = this.mod().createConnection(o);
    return new Promise((res, rej) => c.connect(e => e ? rej(e.code === "ER_NOT_SUPPORTED_AUTH_MODE"
      ? new NA("legacy mysql package does not support caching_sha2_password") : e) : res(c)));
  },
  close: c => new Promise(r => c.end(() => r())),
  query: (c, sql, p) => new Promise((res, rej) => c.query(sql, p, (e, r) => e ? rej(e) : res(r))),
  queryMeta: (c, sql, binary) => {
    if (binary) throw new NA("legacy mysql package has no binary protocol");
    return new Promise((res, rej) => c.query(sql, (e, r, f) => e ? rej(e) : res([r, f.map(x => x.type)])));
  },
  execute() { throw new NA("legacy mysql package has no server-side prepared statements"); },
  async *stream(c, sql, binary) {
    if (binary) throw new NA("legacy mysql package has no binary protocol");
    // the legacy package's stream() is an old readable-stream (not async-iterable): use its row events
    const q = c.query(sql); const buf = []; let done = false, err = null, wake = null;
    q.on("result", r => { buf.push(r); if (buf.length >= 1000) c.pause(); if (wake) { wake(); wake = null; } })
     .on("error", e => { err = e; if (wake) wake(); }).on("end", () => { done = true; if (wake) wake(); });
    while (true) {
      while (buf.length) yield buf.shift();
      if (err) throw err; if (done) return;
      c.resume(); await new Promise(r => (wake = r));
    }
  },
  escape: (c, s) => c.escape(s),
  async batch(c, rows) { await this.query(c, "INSERT INTO t_bulk (id,a,b,c) VALUES ?", [rows]); },
};

const D = { mysql2: Mysql2, mariadb: MariaDB, mysql: Legacy }[A.driver];
let ops = 0;

// ------------------------------------------------------------------ tests
const t1mode = () => V.startsWith("tls-verify") ? "verify" : V.startsWith("tls") ? "on" : "off";
const val0 = r => Array.isArray(r) ? r[0] : r.v;   // rowsAsArray (tuned) vs objects (default)
const num = v => typeof v === "bigint" ? Number(v) : v;

async function t1() {
  const tls = t1mode(), n = tls === "off" ? 5000 : 2000;
  for (let i = 0; i < n; i++) await D.close(await D.connect(tls, V === "socket"));
  ops = n; return n;
}
async function t2(c) {
  let s = 0;
  if (V === "literal") for (const id of IDS) s += num(val0((await D.query(c, "SELECT v FROM t_int WHERE id = " + id))[0]));
  else if (V === "param") for (const id of IDS) s += num(val0((await D.query(c, "SELECT v FROM t_int WHERE id = ?", [id]))[0]));
  else for (const id of IDS) s += num(val0((await D.execute(c, "SELECT v FROM t_int WHERE id = ?", [id]))[0]));
  ops = IDS.length; return s;
}
async function t3(c) {
  const binary = V.startsWith("binary"), sql = "SELECT v FROM t_int"; let s = 0;
  if (V.includes("streamed")) { for await (const r of D.stream(c, sql, binary)) s += num(val0(r)); }
  else { const [rows] = await D.queryMeta(c, sql, binary); for (const r of rows) s += num(val0(r)); }
  ops = 1e6; return s;
}
async function t4(c) {
  const [rows, types] = await D.queryMeta(c, V.startsWith("int") ? "SELECT * FROM t_wide_int" : "SELECT * FROM t_wide_mix", V.endsWith("binary"));
  let nn = 0, isum = 0, slen = 0;
  const n = types.length, names = rows.length && !Array.isArray(rows[0]) ? Object.keys(rows[0]) : null;
  for (const r of rows) {
    for (let i = 1; i < n; i++) {
      const v = names ? r[names[i]] : r[i];
      if (v === null || v === undefined) continue;
      nn++;
      if (INT_T.has(types[i])) isum += num(v); else if (STR_T.has(types[i])) slen += v.length;
    }
  }
  ops = rows.length * 100; return nn + isum + slen;
}
function touch(v) {
  let c = v.length;
  if (typeof v === "string") for (let i = 0; i < v.length; i += 64) c += v.charCodeAt(i);
  else for (let i = 0; i < v.length; i += 64) c += v[i];
  return c;
}
function t5sql() {
  const [cls, ...rest] = V.split("-"); let col = rest.join("-"); const parse = col.endsWith("-parse");
  col = col.replace(/-parse$/, "");
  return [`SELECT ${col} FROM t_blob WHERE size_class = '${cls}' ORDER BY id`, parse];
}
async function t5(c) {
  const [sql, parse] = t5sql(); let ck = 0, bytes = 0;
  for (let rep = 0; rep < 20; rep++) {
    ck = 0;
    for (const r of await D.query(c, sql)) {
      const v = val0(Array.isArray(r) ? r : Object.values(r));
      ck += touch(v); bytes += v.length;
      if (parse) JSON.parse(typeof v === "string" ? v : v.toString("latin1"));
    }
  }
  ops = Math.floor(bytes / 1024); return ck;
}
const rowB = i => (i % 10 === 0 ? "o'k-" : "name-") + i;
async function t6(c) {
  if (V === "sqltext") {
    for (let start = 1; start <= 1e6; start += 1000) {
      const parts = new Array(1000);
      for (let k = 0; k < 1000; k++) { const i = start + k; parts[k] = `(${i},${i * 3},${D.escape(c, rowB(i))},${i * 0.5})`; }
      await D.query(c, "INSERT INTO t_bulk (id,a,b,c) VALUES " + parts.join(","));
    }
  } else if (V === "multiparam") {
    const sql = "INSERT INTO t_bulk (id,a,b,c) VALUES " + new Array(1000).fill("(?,?,?,?)").join(",");
    for (let start = 1; start <= 1e6; start += 1000) {
      const p = new Array(4000);
      for (let k = 0; k < 1000; k++) { const i = start + k; p[4 * k] = i; p[4 * k + 1] = i * 3; p[4 * k + 2] = rowB(i); p[4 * k + 3] = i * 0.5; }
      await D.query(c, sql, p);
    }
  } else {
    for (let start = 1; start <= 1e6; start += 1000) {
      const rows = new Array(1000);
      for (let k = 0; k < 1000; k++) { const i = start + k; rows[k] = [i, i * 3, rowB(i), i * 0.5]; }
      await D.batch(c, rows);
    }
  }
  ops = 1000; return "";
}

// ------------------------------------------------------------------ floor (T3, T5)
let FLOOR = null;
async function floor(c) {
  if (A.test === "T3") {
    FLOOR ??= Array.from({ length: 1e6 }, (_, i) => ({ v: ((i + 1) * 7919) % 1000003 }));
    let s = 0; for (const r of FLOOR) s += r.v; ops = 1e6; return s;
  }
  if (A.test === "T5") {
    FLOOR ??= (await D.query(c, t5sql()[0])).map(r => val0(Array.isArray(r) ? r : Object.values(r)));
    let ck = 0, b = 0; for (let rep = 0; rep < 20; rep++) { ck = 0; for (const v of FLOOR) { ck += touch(v); b += v.length; } }
    ops = Math.floor(b / 1024); return ck;
  }
  throw new NA("floor defined for T3 and T5 in Node");
}

// ------------------------------------------------------------------ main
async function cipher(c) {
  const r = await D.query(c, "SHOW SESSION STATUS LIKE 'Ssl_cipher'");
  const v = r.length ? (Array.isArray(r[0]) ? r[0][1] : Object.values(r[0])[1]) : "";
  return v || "none";
}
let IDS;
async function main() {
  const meta = { stack: D.name, lib: D.lib(), test: A.test, variant: V, config: A.config, server: A.server };
  const write = iters => { const s = JSON.stringify({ ...meta, iters }); A.out ? fs.writeFileSync(A.out, s) : console.log(s); };
  if (A.config !== "default" && A.driver === "mysql") throw new NA("legacy mysql package has no performance options to tune");
  if (A.test === "T1" && V.includes("resume")) throw new NA("Node drivers expose no TLS session resumption control");
  if (A.test === "T0") {
    perfOpen(); const m = new Meter(); m.begin();
    const c = await D.connect(E("DB_TLS", "off")); await D.query(c, "SELECT 1");
    const r = m.end(1); Object.assign(meta, { tls: await cipher(c), ops_per_iter: 1, warmup: 0, rss_start_kb: rssStartKb });
    write([r]); await D.close(c); return;
  }
  if (A.test === "T1") { const c2 = await D.connect(t1mode(), V === "socket"); meta.tls = await cipher(c2); await D.close(c2); }
  const c = await D.connect(E("DB_TLS", "off"));
  if (A.test !== "T1") meta.tls = await cipher(c);
  if (A.test === "T2") IDS = fs.readFileSync(path.join(E("DATA_DIR", "/root/bench/data"), "ids_200k.txt"), "utf8").trim().split("\n").map(Number);
  const fn = A.floor ? floor : { T1: t1, T2: t2, T3: t3, T4: t4, T5: t5, T6: t6 }[A.test];
  perfOpen();
  const iters = [];
  for (let i = 0; i < A.warmup + A.iters; i++) {
    if (A.test === "T6") await D.query(c, "TRUNCATE TABLE t_bulk");
    if (i < A.warmup) { await fn(c); continue; }
    const m = new Meter(); m.begin(); const ck = await fn(c); const r = m.end(ck);
    if (A.test === "T6" && !A.floor) {
      const x = (await D.query(c, "SELECT COUNT(*) AS n, SUM(a) AS a, SUM(CHAR_LENGTH(b)) AS b FROM t_bulk"))[0];
      r.checksum = (Array.isArray(x) ? x : Object.values(x)).map(v => String(Number(v))).join(":");
    }
    iters.push(r);
  }
  Object.assign(meta, { ops_per_iter: ops, warmup: A.warmup });
  write(iters); await D.close(c);
}
main().then(() => process.exit(0)).catch(e => {
  if (e instanceof NA) { console.error("n/a: " + e.message); process.exit(3); }
  console.error(e && e.stack || e); process.exit(1);
});
