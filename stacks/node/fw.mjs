// Phase 3 runner: Node.js frameworks.
//   knex       Knex query builder (client mysql2)
//   sequelize  Sequelize ORM (dialect mysql = mysql2)
//   typeorm    TypeORM (type mysql = mysql2), EntitySchema definitions
//   drizzle    Drizzle ORM (drizzle-orm/mysql2)
//   prisma     Prisma ORM 7 with @prisma/adapter-mariadb (the mariadb driver)
// default = the idiom most code uses; tuned = the framework's own performance options. Same CLI/env contract as runner.mjs.
import fs from "node:fs";
import path from "node:path";
import { PerformanceObserver } from "node:perf_hooks";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pkgVersion = (name) => JSON.parse(fs.readFileSync(new URL(`./node_modules/${name}/package.json`, import.meta.url), "utf8")).version;

const rssStartKb = statusKb("VmRSS:");
const A = { fw: "knex", test: "T0", variant: "", config: "default", server: "ps", out: null, warmup: 2, iters: 5, floor: false };
for (let i = 2; i < process.argv.length; i++) {
  const k = process.argv[i].replace(/^--/, "");
  if (k === "floor") A.floor = true; else A[k] = ["warmup", "iters"].includes(k) ? +process.argv[++i] : process.argv[++i];
}
const V = A.variant, E = (k, d) => process.env[k] || d, TUNED = A.config === "tuned";
class NA extends Error {}

// ------------------------------------------------------------------ harness (same as runner.mjs)
function statusKb(key) { for (const l of fs.readFileSync("/proc/self/status", "utf8").split("\n")) if (l.startsWith(key)) return +l.split(/\s+/)[1]; return -1; }
function srvTicks() { const pid = process.env.MYSQLD_PID; if (!pid) return -1; try { const s = fs.readFileSync(`/proc/${pid}/stat`, "utf8"); const f = s.slice(s.lastIndexOf(")") + 2).split(" "); return +f[11] + +f[12]; } catch { return -1; } }
let ctl = null, ack = null;
function perfOpen() { if (process.env.PERF_CTL && process.env.PERF_ACK) { ctl = fs.openSync(process.env.PERF_CTL, "w"); ack = fs.openSync(process.env.PERF_ACK, "r"); } }
function perf(cmd) { if (ctl === null) return; fs.writeSync(ctl, cmd); fs.readSync(ack, Buffer.alloc(8)); }
let gcCount = 0, gcMs = 0;
new PerformanceObserver((l) => { for (const e of l.getEntries()) { gcCount++; gcMs += e.duration; } }).observe({ entryTypes: ["gc"] });
const cpuNs = () => { const u = process.cpuUsage(); return (u.user + u.system) * 1000; };
class Meter {
  begin() { fs.writeFileSync("/proc/self/clear_refs", "5"); this.rss = statusKb("VmRSS:"); this.gc = gcCount; this.srv = srvTicks(); perf("enable\n"); this.wall = process.hrtime.bigint(); this.cpu = cpuNs(); }
  end(ck) {
    const cpu = cpuNs(), wall = process.hrtime.bigint(); perf("disable\n"); const s = srvTicks();
    return { cpu_ns: cpu - this.cpu, wall_ns: Number(wall - this.wall), srv_ticks: s >= 0 && this.srv >= 0 ? s - this.srv : -1,
      rss_start_kb: this.rss, rss_peak_kb: statusKb("VmHWM:"), rss_end_kb: statusKb("VmRSS:"), checksum: String(ck), gc_count: gcCount - this.gc };
  }
}

// ------------------------------------------------------------------ shared schema
const TYPES10 = ["int", "bigint", "decimal", "double", "varchar32", "datetime", "date", "tinyint", "varchar255n", "intn"];
const COLS = Array.from({ length: 100 }, (_, i) => "c" + String(i + 1).padStart(3, "0"));
const mixType = (k) => TYPES10[k % 10];
const conn = () => ({ host: E("DB_HOST", "127.0.0.1"), port: +E("DB_PORT", "3306"), user: E("DB_USER", "bench"), password: E("DB_PASS", "bench"), database: E("DB_NAME", "bench") });
const sslOpt = (tls) => tls === "off" ? undefined : tls === "on" ? { rejectUnauthorized: false } : { ca: fs.readFileSync(E("DB_CA")), rejectUnauthorized: true };
const rowB = (i) => (i % 10 === 0 ? "o'k-" : "name-") + i;
const num = (v) => typeof v === "bigint" ? Number(v) : v;
const isInt = (k) => ["int", "bigint", "tinyint", "intn"].includes(mixType(k)), isStr = (k) => ["varchar32", "varchar255n"].includes(mixType(k));
function touchRow(o, intTable, acc) {   // acc = [nn, isum, slen]; o = object keyed by column name
  for (let k = 0; k < 100; k++) {
    const v = o[COLS[k]]; if (v === null || v === undefined) continue; acc[0]++;
    if (intTable || isInt(k)) acc[1] += Number(v); else if (isStr(k)) acc[2] += v.length;
  }
}
function touchDoc(v) { let c = v.length; if (typeof v === "string") for (let i = 0; i < v.length; i += 64) c += v.charCodeAt(i); else for (let i = 0; i < v.length; i += 64) c += v[i]; return c; }

// ------------------------------------------------------------------ frameworks
const FW = {};

FW.knex = () => {
  const knex = require("knex");
  let db;
  return {
    name: "node-knex", lib: `Knex ${pkgVersion("knex")} on mysql2 ${pkgVersion("mysql2")}`,
    async open(tls) { db = knex({ client: "mysql2", connection: { ...conn(), ssl: sslOpt(tls), jsonStrings: true }, pool: { min: 1, max: 1 } }); },
    async close() { await db.destroy(); },
    raw: async (sql) => (await db.raw(sql))[0],
    async t2(ids) { let s = 0; for (const id of ids) s += (await db("t_int").select("v").where("id", id).first()).v; return s; },
    async t3(streamed) {
      let s = 0;
      if (streamed) { for await (const r of db("t_int").select("v").stream()) s += r.v; }
      else for (const r of await db("t_int").select("v")) s += r.v;
      return s;
    },
    async t4(intTable) { return db(intTable ? "t_wide_int" : "t_wide_mix").select("*"); },
    async t5(cls, col) { return (await db("t_blob").select(col).where("size_class", cls).orderBy("id")).map((r) => r[col]); },
    async t6(rows) { await db("t_bulk").insert(rows); },
  };
};

FW.sequelize = () => {
  const { Sequelize, DataTypes: T } = require("sequelize");
  let sq, M = {};
  const wide = (intTable) => Object.fromEntries(COLS.map((c, k) => [c, {
    type: intTable ? T.INTEGER : { int: T.INTEGER, bigint: T.BIGINT, decimal: T.DECIMAL(15, 2), double: T.DOUBLE, varchar32: T.STRING(32),
      datetime: T.DATE(6), date: T.DATEONLY, tinyint: T.TINYINT, varchar255n: T.STRING(255), intn: T.INTEGER }[mixType(k)] }]));
  return {
    name: "node-sequelize", lib: `Sequelize ${pkgVersion("sequelize")} on mysql2 ${pkgVersion("mysql2")}`,
    async open(tls) {
      sq = new Sequelize(E("DB_NAME", "bench"), E("DB_USER", "bench"), E("DB_PASS", "bench"), {
        host: E("DB_HOST", "127.0.0.1"), port: +E("DB_PORT", "3306"), dialect: "mysql", logging: false, pool: { max: 1, min: 1 },
        dialectOptions: { ssl: sslOpt(tls), jsonStrings: true, supportBigNumbers: true }, define: { timestamps: false, freezeTableName: true } });
      const id = { type: T.INTEGER, primaryKey: true };
      M.TInt = sq.define("t_int", { id, v: T.INTEGER });
      M.WideInt = sq.define("t_wide_int", { id, ...wide(true) });
      M.WideMix = sq.define("t_wide_mix", { id, ...wide(false) });
      M.TBlob = sq.define("t_blob", { id, size_class: T.STRING(8), doc: T.TEXT, doc_bin: T.BLOB("long") });
      M.TBulk = sq.define("t_bulk", { id, a: T.INTEGER, b: T.STRING(32), c: T.DOUBLE });
      await sq.authenticate();
    },
    async close() { await sq.close(); },
    raw: async (sql) => (await sq.query(sql))[0],
    async t2(ids) {   // default: model instance; tuned: raw plain object
      let s = 0; for (const id of ids) s += (await M.TInt.findByPk(id, TUNED ? { raw: true } : {})).v; return s;
    },
    async t3(streamed) {
      if (streamed) throw new NA("Sequelize has no row streaming");
      let s = 0; for (const r of await M.TInt.findAll(TUNED ? { raw: true } : {})) s += r.v; return s;
    },
    async t4(intTable) { const rows = await (intTable ? M.WideInt : M.WideMix).findAll(TUNED ? { raw: true } : {}); return TUNED ? rows : rows.map((r) => r.dataValues); },
    async t5(cls, col) { return (await M.TBlob.findAll({ attributes: [col], where: { size_class: cls }, order: [["id", "ASC"]], raw: TUNED })).map((r) => TUNED ? r[col] : r.get(col)); },
    async t6(rows) { if (TUNED) await sq.getQueryInterface().bulkInsert("t_bulk", rows); else await M.TBulk.bulkCreate(rows); },
  };
};

FW.typeorm = () => {
  const { DataSource, EntitySchema } = require("typeorm");
  let ds, R = {};
  const col = (type, extra = {}) => ({ type, ...extra });
  const wideCols = (intTable) => Object.fromEntries(COLS.map((c, k) => [c, intTable ? col("int") : {
    int: col("int"), bigint: col("bigint", { bigNumberStrings: false }), decimal: col("decimal", { precision: 15, scale: 2 }), double: col("double"),
    varchar32: col("varchar", { length: 32 }), datetime: col("datetime", { precision: 6 }), date: col("date"), tinyint: col("tinyint"),
    varchar255n: col("varchar", { length: 255, nullable: true }), intn: col("int", { nullable: true }) }[mixType(k)]]));
  const ent = (name, table, columns) => new EntitySchema({ name, tableName: table, columns: { id: { type: "int", primary: true }, ...columns } });
  const E_ = { TInt: ent("TInt", "t_int", { v: col("int") }), WideInt: ent("WideInt", "t_wide_int", wideCols(true)), WideMix: ent("WideMix", "t_wide_mix", wideCols(false)),
    TBlob: ent("TBlob", "t_blob", { size_class: col("varchar", { length: 8 }), doc: col("longtext"), doc_bin: col("longblob") }),
    TBulk: ent("TBulk", "t_bulk", { a: col("int"), b: col("varchar", { length: 32 }), c: col("double") }) };
  return {
    name: "node-typeorm", lib: `TypeORM ${pkgVersion("typeorm")} on mysql2 ${pkgVersion("mysql2")}`,
    async open(tls) {
      ds = new DataSource({ type: "mysql", ...conn(), ssl: sslOpt(tls), entities: Object.values(E_), synchronize: false, logging: false,
        poolSize: 1, extra: { jsonStrings: true }, supportBigNumbers: true, bigNumberStrings: false });
      await ds.initialize();
      for (const [k, e] of Object.entries(E_)) R[k] = ds.getRepository(e);
    },
    async close() { await ds.destroy(); },
    raw: async (sql) => ds.query(sql),
    async t2(ids) {   // default: entity via repository; tuned: query builder raw value
      let s = 0;
      if (TUNED) for (const id of ids) s += (await R.TInt.createQueryBuilder("t").select("t.v", "v").where("t.id = :id", { id }).getRawOne()).v;
      else for (const id of ids) s += (await R.TInt.findOneBy({ id })).v;
      return s;
    },
    async t3(streamed) {
      let s = 0;
      if (streamed) { const st = await R.TInt.createQueryBuilder("t").stream(); for await (const r of st) s += r.t_v; }
      else if (TUNED) for (const r of await R.TInt.createQueryBuilder("t").select("t.v", "v").getRawMany()) s += r.v;
      else for (const r of await R.TInt.find()) s += r.v;
      return s;
    },
    async t4(intTable) {
      const repo = intTable ? R.WideInt : R.WideMix;
      if (!TUNED) return repo.find();
      return (await repo.createQueryBuilder("t").getRawMany()).map((r) => Object.fromEntries(Object.entries(r).map(([k, v]) => [k.slice(2), v])));
    },
    async t5(cls, col) {
      return (await R.TBlob.createQueryBuilder("t").select(`t.${col}`, "x").where("t.size_class = :cls", { cls }).orderBy("t.id").getRawMany()).map((r) => r.x);
    },
    async t6(rows) { if (TUNED) await R.TBulk.insert(rows); else await R.TBulk.save(rows.map((r) => R.TBulk.create(r))); },
  };
};

FW.drizzle = () => {
  const { drizzle } = require("drizzle-orm/mysql2");
  const { mysqlTable, int, bigint, decimal, double, varchar, datetime, date, tinyint, text, customType } = require("drizzle-orm/mysql-core");
  const { eq, asc, sql } = require("drizzle-orm");
  const mysql = require("mysql2/promise");
  const longblob = customType({ dataType: () => "longblob" });
  const mixCol = { int: (c) => int(c).notNull(), bigint: (c) => bigint(c, { mode: "number" }).notNull(), decimal: (c) => decimal(c, { precision: 15, scale: 2 }).notNull(),
    double: (c) => double(c).notNull(), varchar32: (c) => varchar(c, { length: 32 }).notNull(), datetime: (c) => datetime(c, { fsp: 6 }).notNull(),
    date: (c) => date(c).notNull(), tinyint: (c) => tinyint(c).notNull(), varchar255n: (c) => varchar(c, { length: 255 }), intn: (c) => int(c) };
  const tInt = mysqlTable("t_int", { id: int("id").primaryKey(), v: int("v").notNull() });
  const wideInt = mysqlTable("t_wide_int", { id: int("id").primaryKey(), ...Object.fromEntries(COLS.map((c) => [c, int(c).notNull()])) });
  const wideMix = mysqlTable("t_wide_mix", { id: int("id").primaryKey(), ...Object.fromEntries(COLS.map((c, k) => [c, mixCol[mixType(k)](c)])) });
  const tBlob = mysqlTable("t_blob", { id: int("id").primaryKey(), size_class: varchar("size_class", { length: 8 }), doc: text("doc"), doc_bin: longblob("doc_bin") });
  const tBulk = mysqlTable("t_bulk", { id: int("id").primaryKey(), a: int("a"), b: varchar("b", { length: 32 }), c: double("c") });
  let c, db;
  return {
    name: "node-drizzle", lib: `Drizzle ${pkgVersion("drizzle-orm")} on mysql2 ${pkgVersion("mysql2")}`,
    async open(tls) { c = await mysql.createConnection({ ...conn(), ssl: sslOpt(tls), jsonStrings: true }); db = drizzle(c); },
    async close() { await c.end(); },
    raw: async (q) => (await c.query(q))[0],
    async t2(ids) {
      let s = 0;
      if (TUNED) {   // prepared query with a placeholder, built once
        const p = db.select({ v: tInt.v }).from(tInt).where(eq(tInt.id, sql.placeholder("id"))).prepare();
        for (const id of ids) s += (await p.execute({ id }))[0].v;
      } else for (const id of ids) s += (await db.select({ v: tInt.v }).from(tInt).where(eq(tInt.id, id)))[0].v;
      return s;
    },
    async t3(streamed) {
      let s = 0;
      if (streamed) { for await (const r of db.select({ v: tInt.v }).from(tInt).iterator()) s += r.v; }
      else for (const r of await db.select({ v: tInt.v }).from(tInt)) s += r.v;
      return s;
    },
    async t4(intTable) { return db.select().from(intTable ? wideInt : wideMix); },
    async t5(cls, col) { return (await db.select({ x: tBlob[col] }).from(tBlob).where(eq(tBlob.size_class, cls)).orderBy(asc(tBlob.id))).map((r) => r.x); },
    async t6(rows) { await db.insert(tBulk).values(rows); },
  };
};

FW.prisma = () => {
  const { PrismaClient } = require("./prisma-client/index.js");
  const { PrismaMariaDb } = require("@prisma/adapter-mariadb");
  let p;
  return {
    name: "node-prisma", lib: `Prisma ${pkgVersion("@prisma/client")} on mariadb ${pkgVersion("mariadb")} (driver adapter)`,
    async open(tls) {
      const s = sslOpt(tls);
      p = new PrismaClient({ adapter: new PrismaMariaDb({ ...conn(), connectionLimit: 1, ssl: s ?? false, allowPublicKeyRetrieval: false }) });
      await p.$connect();
    },
    async close() { await p.$disconnect(); },
    raw: async (sql) => p.$queryRawUnsafe(sql),
    async t2(ids) {   // default: whole row; tuned: select only the needed field
      let s = 0; for (const id of ids) s += (await p.tInt.findUnique({ where: { id }, ...(TUNED ? { select: { v: true } } : {}) })).v; return s;
    },
    async t3(streamed) {
      if (streamed) throw new NA("Prisma has no row streaming");
      let s = 0; for (const r of await p.tInt.findMany(TUNED ? { select: { v: true } } : {})) s += r.v; return s;
    },
    async t4(intTable) { return intTable ? p.wideInt.findMany() : p.wideMix.findMany(); },
    async t5(cls, col) { return (await p.tBlob.findMany({ where: { size_class: cls }, orderBy: { id: "asc" }, select: { [col]: true } })).map((r) => r[col]); },
    async t6(rows) { await p.tBulk.createMany({ data: rows }); },
  };
};

// ------------------------------------------------------------------ main
let ops = 0;
async function main() {
  if (!FW[A.fw]) throw new Error("unknown framework " + A.fw);
  const D = FW[A.fw]();
  const meta = { stack: D.name, lib: D.lib, test: A.test, variant: V, config: A.config, server: A.server };
  const write = (iters) => { const s = JSON.stringify({ ...meta, iters }); A.out ? fs.writeFileSync(A.out, s) : console.log(s); };
  const cipherOf = async () => { const r = await D.raw("SHOW SESSION STATUS LIKE 'Ssl_cipher'"); const x = r[0]; const v = x ? (x.Value ?? Object.values(x)[1]) : ""; return v || "none"; };
  if (A.test === "T1") throw new NA("frameworks use the driver's connections (see the driver results)");
  if (A.test === "T0") {
    perfOpen(); const m = new Meter(); m.begin(); await D.open(E("DB_TLS", "off")); await D.raw("SELECT 1");
    const r = m.end(1); Object.assign(meta, { tls: await cipherOf(), ops_per_iter: 1, warmup: 0, rss_start_kb: rssStartKb }); write([r]); await D.close(); return;
  }
  if (A.test === "T2" && V !== "param") throw new NA("frameworks bind parameters themselves (variant: param)");
  if ((A.test === "T3" || A.test === "T4") && V.includes("binary")) throw new NA("measured on the text protocol");
  if (A.test === "T6" && V !== "batch") throw new NA("frameworks insert through their bulk API (the batch variant)");
  await D.open(E("DB_TLS", "off"));
  meta.tls = await cipherOf();
  const ids = A.test === "T2" ? fs.readFileSync(path.join(E("DATA_DIR", "/root/bench/data"), "ids_200k.txt"), "utf8").trim().split("\n").map(Number) : null;
  const [cls, col0] = A.test === "T5" ? [V.split("-")[0], V.split("-").slice(1).join("-")] : [];
  const parse = A.test === "T5" && col0.endsWith("-parse"), col = A.test === "T5" ? col0.replace(/-parse$/, "") : null;
  const fn = {
    T2: async () => { ops = ids.length; return D.t2(ids); },
    T3: async () => { ops = 1e6; return D.t3(V.includes("streamed")); },
    T4: async () => { const intTable = V.startsWith("int"); const rows = await D.t4(intTable); const acc = [0, 0, 0]; for (const r of rows) touchRow(r, intTable, acc); ops = rows.length * 100; return acc[0] + acc[1] + acc[2]; },
    T5: async () => { let ck = 0, b = 0; for (let rep = 0; rep < 20; rep++) { const vals = await D.t5(cls, col); ck = 0; for (const v of vals) { ck += touchDoc(v); b += v.length; if (parse) JSON.parse(String(v)); } } ops = Math.floor(b / 1024); return ck; },
    T6: async () => { for (let st = 1; st <= 1e6; st += 1000) { const rows = new Array(1000); for (let k = 0; k < 1000; k++) { const i = st + k; rows[k] = { id: i, a: i * 3, b: rowB(i), c: i * 0.5 }; } await D.t6(rows); } ops = 1000; return ""; },
  }[A.test];
  meta.rss_baseline_kb = statusKb("VmRSS:");
  perfOpen();
  let start = 0;
  if (process.env.ADAPTIVE_WARMUP) {   // same rule as runner.mjs
    const w = [], t0 = Date.now(), cap = +E("WARMUP_CAP", "40"), capMs = 1000 * +E("WARMUP_CAP_S", "120"); meta.warmup_stable = true;
    for (;;) {
      if (A.test === "T6") await D.raw("TRUNCATE TABLE t_bulk");
      const a = cpuNs(); await fn(); w.push(cpuNs() - a);
      if (w.length >= Math.max(3, A.warmup)) { const l = w.slice(-3).sort((x, y) => x - y); if (l[2] - l[0] <= 0.05 * l[1]) break; }
      if (w.length >= cap || Date.now() - t0 > capMs) { meta.warmup_stable = false; break; }
    }
    A.warmup = w.length; start = w.length; meta.warmup_adaptive = true;
  }
  const iters = [];
  for (let i = start; i < A.warmup + A.iters; i++) {
    if (A.test === "T6") await D.raw("TRUNCATE TABLE t_bulk");
    if (i < A.warmup) { await fn(); continue; }
    const m = new Meter(); m.begin(); const ck = await fn(); const r = m.end(ck);
    if (A.test === "T6") { const x = (await D.raw("SELECT COUNT(*) AS n, SUM(a) AS a, SUM(CHAR_LENGTH(b)) AS b FROM t_bulk"))[0]; r.checksum = Object.values(x).map((v) => String(Number(v))).join(":"); }
    iters.push(r);
  }
  Object.assign(meta, { ops_per_iter: ops, warmup: A.warmup });
  write(iters); await D.close();
}
main().then(() => process.exit(0)).catch((e) => {
  if (e instanceof NA) { console.error("n/a: " + e.message); process.exit(3); }
  console.error(e && e.stack || e); process.exit(1);
});
