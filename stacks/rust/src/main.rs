//! Rust runner: `mysql` crate (sync) and `sqlx` (async, tokio current-thread runtime).
//! Same CLI/env contract as the other runners (SPEC.md section 5).
use std::{env, fs};

mod harness;
use harness::*;

#[derive(Debug)]
pub struct NA(pub String);
impl std::fmt::Display for NA { fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result { write!(f, "{}", self.0) } }
impl std::error::Error for NA {}
type R<T> = Result<T, Box<dyn std::error::Error>>;
fn na<T>(m: &str) -> R<T> { Err(Box::new(NA(m.into()))) }

pub struct Args { pub driver: String, pub test: String, pub variant: String, pub config: String, pub server: String, pub out: Option<String>, pub warmup: usize, pub iters: usize }
fn e(k: &str, d: &str) -> String { env::var(k).ok().filter(|v| !v.is_empty()).unwrap_or_else(|| d.to_string()) }
fn t1_mode(v: &str) -> &'static str { if v.starts_with("tls-verify") { "verify" } else if v.starts_with("tls") { "on" } else { "off" } }
fn row_b(i: i64) -> String { if i % 10 == 0 { format!("o'k-{i}") } else { format!("name-{i}") } }
fn esc(s: &str) -> String { s.replace('\\', "\\\\").replace('\'', "\\'") }   // neither crate exports an escaping function
fn touch(b: &[u8]) -> i64 { let mut c = b.len() as i64; let mut i = 0; while i < b.len() { c += b[i] as i64; i += 64; } c }
fn t5_sql(v: &str) -> (String, bool) {
    let (cls, col) = v.split_once('-').unwrap(); let parse = col.ends_with("-parse");
    (format!("SELECT {} FROM t_blob WHERE size_class = '{cls}' ORDER BY id", col.trim_end_matches("-parse")), parse)
}
const INT_T: [u8; 5] = [1, 2, 3, 8, 9];
const STR_T: [u8; 3] = [15, 253, 254];

// ======================================================================== mysql (sync)
mod sync_drv {
    use super::*;
    use mysql::{prelude::*, *};
    fn opts(tls: &str, sock: bool) -> Opts {
        let mut b = OptsBuilder::new().user(Some(e("DB_USER", "bench"))).pass(Some(e("DB_PASS", "bench"))).db_name(Some(e("DB_NAME", "bench")))
            .prefer_socket(false);   // default true: would silently switch 127.0.0.1 connections to the Unix socket
        b = if sock { b.socket(Some(e("DB_SOCKET", ""))) } else { b.ip_or_hostname(Some(e("DB_HOST", "127.0.0.1"))).tcp_port(e("DB_PORT", "3306").parse().unwrap()) };
        b = match tls {
            "off" => b,
            "on" => b.ssl_opts(Some(SslOpts::default().with_danger_accept_invalid_certs(true).with_danger_skip_domain_validation(true))),
            _ => b.ssl_opts(Some(SslOpts::default().with_root_cert_path(Some(std::path::PathBuf::from(e("DB_CA", "")))))),
        };
        b.into()
    }
    pub fn connect(tls: &str, sock: bool) -> R<Conn> { Ok(Conn::new(opts(tls, sock))?) }
    pub fn cipher(c: &mut Conn) -> String {
        c.query_first::<(String, String), _>("SHOW SESSION STATUS LIKE 'Ssl_cipher'").ok().flatten().map(|r| r.1).filter(|v| !v.is_empty()).unwrap_or("none".into())
    }
    pub fn step(a: &Args, c: &mut Conn, ids: &[i32], ops: &mut i64) -> R<String> {
        let v = a.variant.as_str();
        match a.test.as_str() {
            "T1" => { let n = if t1_mode(v) == "off" { 10000 } else { 2000 }; for _ in 0..n { drop(connect(t1_mode(v), v == "socket")?); } *ops = n; Ok(n.to_string()) }
            "T2" => {
                let mut s = 0i64;
                match v {
                    "literal" => for id in ids { s += c.query_first::<i64, _>(format!("SELECT v FROM t_int WHERE id = {id}"))?.unwrap(); },
                    "param" => for id in ids { s += c.exec_first::<i64, _, _>("SELECT v FROM t_int WHERE id = ?", (id,))?.unwrap(); }, // statement cache
                    _ => { let st = c.prep("SELECT v FROM t_int WHERE id = ?")?; for id in ids { s += c.exec_first::<i64, _, _>(&st, (id,))?.unwrap(); } }
                }
                *ops = ids.len() as i64; Ok(s.to_string())
            }
            "T3" => {
                let mut s = 0i64; let sql = "SELECT v FROM t_int";
                match v {
                    "text-buffered" => for x in c.query::<i64, _>(sql)? { s += x },
                    "text-streamed" => for r in c.query_iter(sql)? { s += r?.get::<i64, _>(0).unwrap() },
                    "binary-buffered" => for x in c.exec::<i64, _, _>(sql, ())? { s += x },
                    _ => for r in c.exec_iter(sql, ())? { s += r?.get::<i64, _>(0).unwrap() },
                }
                *ops = 1_000_000; Ok(s.to_string())
            }
            "T4" => {
                let sql = if v.starts_with("int") { "SELECT * FROM t_wide_int" } else { "SELECT * FROM t_wide_mix" };
                let (mut nn, mut isum, mut slen, mut n) = (0i64, 0i64, 0i64, 0i64);
                let mut each = |row: Row| {
                    n += 1;
                    let types: Vec<u8> = row.columns_ref().iter().map(|c| c.column_type() as u8).collect();
                    for (i, val) in row.unwrap().into_iter().enumerate().skip(1) {
                        if val == Value::NULL { continue; }
                        nn += 1;
                        if INT_T.contains(&types[i]) { isum += from_value::<i64>(val); }
                        else if STR_T.contains(&types[i]) { slen += from_value::<String>(val).len() as i64; }
                    }
                };
                if v.ends_with("binary") { for r in c.exec_iter(sql, ())? { each(r?) } } else { for r in c.query_iter(sql)? { each(r?) } }
                *ops = n * 100; Ok((nn + isum + slen).to_string())
            }
            "T5" => {
                let (sql, parse) = t5_sql(v); let (mut ck, mut bytes) = (0i64, 0i64);
                for _ in 0..20 {
                    ck = 0;
                    for doc in c.query::<Vec<u8>, _>(&sql)? {
                        ck += touch(&doc); bytes += doc.len() as i64;
                        if parse { let _: serde_json::Value = serde_json::from_slice(&doc)?; }
                    }
                }
                *ops = bytes / 1024; Ok(ck.to_string())
            }
            _ => {
                match v {
                    "sqltext" => for st in (1..=1_000_000i64).step_by(1000) {
                        let vals: Vec<String> = (st..st + 1000).map(|i| format!("({i},{},'{}',{})", i * 3, esc(&row_b(i)), i as f64 * 0.5)).collect();
                        c.query_drop(format!("INSERT INTO t_bulk (id,a,b,c) VALUES {}", vals.join(",")))?;
                    },
                    "multiparam" => {
                        let st = c.prep(format!("INSERT INTO t_bulk (id,a,b,c) VALUES {}", vec!["(?,?,?,?)"; 1000].join(",")))?;
                        for s0 in (1..=1_000_000i64).step_by(1000) {
                            let p: Vec<Value> = (s0..s0 + 1000).flat_map(|i| [Value::from(i), Value::from(i * 3), Value::from(row_b(i)), Value::from(i as f64 * 0.5)]).collect();
                            c.exec_drop(&st, Params::Positional(p))?;
                        }
                    }
                    _ => {   // exec_batch: the crate's batch API (executes the prepared statement once per row)
                        let st = c.prep("INSERT INTO t_bulk (id,a,b,c) VALUES (?,?,?,?)")?;
                        for s0 in (1..=1_000_000i64).step_by(1000) {
                            c.exec_batch(&st, (s0..s0 + 1000).map(|i| (i, i * 3, row_b(i), i as f64 * 0.5)))?;
                        }
                    }
                }
                *ops = 1000; Ok(String::new())
            }
        }
    }
    pub fn exec(c: &mut Conn, sql: &str) -> R<()> { Ok(c.query_drop(sql)?) }
    pub fn verify6(c: &mut Conn) -> R<String> {
        let r: (i64, i64, i64) = c.query_first("SELECT COUNT(*), CAST(SUM(a) AS SIGNED), CAST(SUM(CHAR_LENGTH(b)) AS SIGNED) FROM t_bulk")?.unwrap();
        Ok(format!("{}:{}:{}", r.0, r.1, r.2))
    }
}

// ======================================================================== sqlx (async)
mod sqlx_drv {
    use super::*;
    use futures_util::TryStreamExt;
    use sqlx::{mysql::*, AssertSqlSafe, Column, ConnectOptions, Connection, Executor, Row, TypeInfo, ValueRef};
    fn opts(tls: &str, sock: bool) -> MySqlConnectOptions {
        let mut o = MySqlConnectOptions::new().username(&e("DB_USER", "bench")).password(&e("DB_PASS", "bench")).database(&e("DB_NAME", "bench"));
        o = if sock { o.socket(e("DB_SOCKET", "")) } else { o.host(&e("DB_HOST", "127.0.0.1")).port(e("DB_PORT", "3306").parse().unwrap()) };
        match tls { "off" => o.ssl_mode(MySqlSslMode::Disabled), "on" => o.ssl_mode(MySqlSslMode::Required),
                    _ => o.ssl_mode(MySqlSslMode::VerifyIdentity).ssl_ca(e("DB_CA", "")) }
    }
    pub async fn connect(tls: &str, sock: bool) -> R<MySqlConnection> { Ok(opts(tls, sock).connect().await?) }
    pub async fn cipher(c: &mut MySqlConnection) -> String {
        match sqlx::query("SHOW SESSION STATUS LIKE 'Ssl_cipher'").fetch_optional(&mut *c).await {
            Ok(Some(r)) => r.try_get::<String, _>(1).ok().filter(|v| !v.is_empty()).unwrap_or("none".into()), _ => "none".into() }
    }
    pub async fn step(a: &Args, c: &mut MySqlConnection, ids: &[i32], ops: &mut i64) -> R<String> {
        let v = a.variant.as_str();
        match a.test.as_str() {
            "T1" => { let n = if t1_mode(v) == "off" { 10000 } else { 2000 }; for _ in 0..n { connect(t1_mode(v), v == "socket").await?.close().await?; } *ops = n; Ok(n.to_string()) }
            "T2" => {
                let mut s = 0i64;
                for id in ids {
                    s += match v {
                        "literal" => { let r = sqlx::raw_sql(AssertSqlSafe(format!("SELECT v FROM t_int WHERE id = {id}"))).fetch_one(&mut *c).await?; r.try_get::<i32, _>(0)? as i64 }
                        "param" => sqlx::query_scalar::<_, i32>("SELECT v FROM t_int WHERE id = ?").bind(id).persistent(false).fetch_one(&mut *c).await? as i64,
                        _ => sqlx::query_scalar::<_, i32>("SELECT v FROM t_int WHERE id = ?").bind(id).fetch_one(&mut *c).await? as i64,  // cached prepare
                    };
                }
                *ops = ids.len() as i64; Ok(s.to_string())
            }
            "T3" => {
                let mut s = 0i64; let sql = "SELECT v FROM t_int";
                match v {
                    "text-buffered" => for r in sqlx::raw_sql(sql).fetch_all(&mut *c).await? { s += r.try_get::<i32, _>(0)? as i64 },
                    "text-streamed" => { let mut st = sqlx::raw_sql(sql).fetch(&mut *c); while let Some(r) = st.try_next().await? { s += r.try_get::<i32, _>(0)? as i64 } }
                    "binary-buffered" => for r in sqlx::query(sql).fetch_all(&mut *c).await? { s += r.try_get::<i32, _>(0)? as i64 },
                    _ => { let mut st = sqlx::query(sql).fetch(&mut *c); while let Some(r) = st.try_next().await? { s += r.try_get::<i32, _>(0)? as i64 } }
                }
                *ops = 1_000_000; Ok(s.to_string())
            }
            "T4" => {
                let sql = if v.starts_with("int") { "SELECT * FROM t_wide_int" } else { "SELECT * FROM t_wide_mix" };
                let rows = if v.ends_with("binary") { sqlx::query(sql).fetch_all(&mut *c).await? } else { sqlx::raw_sql(sql).fetch_all(&mut *c).await? };
                let (mut nn, mut isum, mut slen) = (0i64, 0i64, 0i64);
                for r in &rows {
                    for i in 1..r.len() {
                        if r.try_get_raw(i)?.is_null() { continue; }
                        nn += 1;
                        match r.column(i).type_info().name() {
                            "INT" | "BIGINT" | "TINYINT" | "SMALLINT" | "MEDIUMINT" => isum += r.try_get::<i64, _>(i)?,
                            "VARCHAR" | "CHAR" => slen += r.try_get::<String, _>(i)?.len() as i64,
                            "DECIMAL" => { r.try_get::<rust_decimal::Decimal, _>(i)?; }
                            "DOUBLE" | "FLOAT" => { r.try_get::<f64, _>(i)?; }
                            "DATE" => { r.try_get::<chrono::NaiveDate, _>(i)?; }
                            _ => { r.try_get::<chrono::NaiveDateTime, _>(i)?; }
                        }
                    }
                }
                *ops = rows.len() as i64 * 100; Ok((nn + isum + slen).to_string())
            }
            "T5" => {
                let (sql, parse) = t5_sql(v); let (mut ck, mut bytes) = (0i64, 0i64);
                for _ in 0..20 {
                    ck = 0;
                    for r in sqlx::raw_sql(AssertSqlSafe(sql.clone())).fetch_all(&mut *c).await? {
                        let raw = r.try_get_raw(0)?;
                        let doc: &[u8] = <&[u8] as sqlx::Decode<MySql>>::decode(raw).map_err(|e| e.to_string())?;
                        ck += touch(doc); bytes += doc.len() as i64;
                        if parse { let _: serde_json::Value = serde_json::from_slice(doc)?; }
                    }
                }
                *ops = bytes / 1024; Ok(ck.to_string())
            }
            _ => {
                match v {
                    "sqltext" => for st in (1..=1_000_000i64).step_by(1000) {
                        let vals: Vec<String> = (st..st + 1000).map(|i| format!("({i},{},'{}',{})", i * 3, esc(&row_b(i)), i as f64 * 0.5)).collect();
                        c.execute(sqlx::raw_sql(AssertSqlSafe(format!("INSERT INTO t_bulk (id,a,b,c) VALUES {}", vals.join(","))))).await?;
                    },
                    "multiparam" => {
                        let sql = format!("INSERT INTO t_bulk (id,a,b,c) VALUES {}", vec!["(?,?,?,?)"; 1000].join(","));
                        for s0 in (1..=1_000_000i64).step_by(1000) {
                            let mut q = sqlx::query(AssertSqlSafe(sql.clone()));
                            for i in s0..s0 + 1000 { q = q.bind(i).bind(i * 3).bind(row_b(i)).bind(i as f64 * 0.5); }
                            q.execute(&mut *c).await?;
                        }
                    }
                    _ => return na("sqlx has no batch API (QueryBuilder::push_values builds the multiparam statement)"),
                }
                *ops = 1000; Ok(String::new())
            }
        }
    }
    pub async fn exec(c: &mut MySqlConnection, sql: &str) -> R<()> { c.execute(sqlx::raw_sql(AssertSqlSafe(sql.to_string()))).await?; Ok(()) }
    pub async fn verify6(c: &mut MySqlConnection) -> R<String> {
        let r = sqlx::query("SELECT COUNT(*), CAST(SUM(a) AS SIGNED), CAST(SUM(CHAR_LENGTH(b)) AS SIGNED) FROM t_bulk").fetch_one(&mut *c).await?;
        Ok(format!("{}:{}:{}", r.try_get::<i64, _>(0)?, r.try_get::<i64, _>(1)?, r.try_get::<i64, _>(2)?))
    }
}

// ======================================================================== main
fn main() {
    let rss_start = status_kb("VmRSS:");
    // mysql (rustls-tls) and sqlx (tls-rustls) enable different rustls backends: pick one explicitly
    let _ = rustls::crypto::aws_lc_rs::default_provider().install_default();
    let mut a = Args { driver: "mysql".into(), test: "T0".into(), variant: String::new(), config: "default".into(), server: "ps".into(), out: None, warmup: 2, iters: 5 };
    let argv: Vec<String> = env::args().collect();
    let mut i = 1;
    while i < argv.len() {
        let v = argv.get(i + 1).cloned().unwrap_or_default();
        match argv[i].as_str() {
            "--driver" => a.driver = v, "--test" => a.test = v, "--variant" => a.variant = v, "--config" => a.config = v,
            "--server" => a.server = v, "--out" => a.out = Some(v), "--warmup" => a.warmup = v.parse().unwrap(), "--iters" => a.iters = v.parse().unwrap(),
            "--floor" => { eprintln!("n/a: floor not implemented in Rust (no interpreter overhead to separate)"); std::process::exit(3) }
            x => panic!("unknown arg {x}"),
        }
        i += 2;
    }
    if let Err(err) = run(&a, rss_start) {
        if err.downcast_ref::<NA>().is_some() { eprintln!("n/a: {err}"); std::process::exit(3) }
        eprintln!("{err}"); std::process::exit(1)
    }
}

fn run(a: &Args, rss_start: i64) -> R<()> {
    if a.config != "default" { return na("Rust driver options are covered by the explicit variants"); }
    if a.test == "T1" && a.variant.contains("resume") { return na("Rust drivers expose no TLS session resumption control"); }
    let stack = if a.driver == "sqlx" { "rust-sqlx" } else { "rust-mysql" };
    let lib = if a.driver == "sqlx" { format!("sqlx {}", env!("SQLX_VERSION")) } else { format!("mysql {}", env!("MYSQL_VERSION")) };
    let mut meta = serde_json::json!({"stack": stack, "lib": lib, "test": a.test, "variant": a.variant, "config": a.config, "server": a.server});
    let tls = e("DB_TLS", "off");
    let ids: Vec<i32> = if a.test == "T2" { fs::read_to_string(format!("{}/ids_200k.txt", e("DATA_DIR", "/root/bench/data")))?.lines().map(|l| l.parse().unwrap()).collect() } else { vec![] };
    let mut iters = vec![];
    let mut ops = 0i64;
    let mut perf = Perf::open();
    if a.driver == "sqlx" {
        let rt = tokio::runtime::Builder::new_current_thread().enable_all().build()?;
        rt.block_on(async {
            if a.test == "T0" {
                perf = Perf::open(); let m = Meter::begin(&mut perf);
                let mut c = sqlx_drv::connect(&tls, false).await?; sqlx_drv::exec(&mut c, "SELECT 1").await?;
                iters.push(m.end(&mut perf, "1".into())); meta["tls"] = sqlx_drv::cipher(&mut c).await.into(); meta["rss_start_kb"] = rss_start.into(); ops = 1;
                return Ok::<(), Box<dyn std::error::Error>>(());
            }
            if a.test == "T1" { let mut c2 = sqlx_drv::connect(t1_mode(&a.variant), a.variant == "socket").await?; meta["tls"] = sqlx_drv::cipher(&mut c2).await.into(); }
            let mut c = sqlx_drv::connect(&tls, false).await?;
            if a.test != "T1" { meta["tls"] = sqlx_drv::cipher(&mut c).await.into(); }
            meta["rss_baseline_kb"] = status_kb("VmRSS:").into();
            perf = Perf::open();
            for k in 0..a.warmup + a.iters {
                if a.test == "T6" { sqlx_drv::exec(&mut c, "TRUNCATE TABLE t_bulk").await?; }
                if k < a.warmup { sqlx_drv::step(a, &mut c, &ids, &mut ops).await?; continue; }
                let m = Meter::begin(&mut perf); let ck = sqlx_drv::step(a, &mut c, &ids, &mut ops).await; let mut r = m.end(&mut perf, ck?);
                if a.test == "T6" { r["checksum"] = sqlx_drv::verify6(&mut c).await?.into(); }
                iters.push(r);
            }
            Ok(())
        })?;
    } else {
        if a.test == "T0" {
            perf = Perf::open(); let m = Meter::begin(&mut perf);
            let mut c = sync_drv::connect(&tls, false)?; sync_drv::exec(&mut c, "SELECT 1")?;
            iters.push(m.end(&mut perf, "1".into())); meta["tls"] = sync_drv::cipher(&mut c).into(); meta["rss_start_kb"] = rss_start.into(); ops = 1;
        } else {
            if a.test == "T1" { let mut c2 = sync_drv::connect(t1_mode(&a.variant), a.variant == "socket")?; meta["tls"] = sync_drv::cipher(&mut c2).into(); }
            let mut c = sync_drv::connect(&tls, false)?;
            if a.test != "T1" { meta["tls"] = sync_drv::cipher(&mut c).into(); }
            meta["rss_baseline_kb"] = status_kb("VmRSS:").into();
            perf = Perf::open();
            for k in 0..a.warmup + a.iters {
                if a.test == "T6" { sync_drv::exec(&mut c, "TRUNCATE TABLE t_bulk")?; }
                if k < a.warmup { sync_drv::step(a, &mut c, &ids, &mut ops)?; continue; }
                let m = Meter::begin(&mut perf); let ck = sync_drv::step(a, &mut c, &ids, &mut ops); let mut r = m.end(&mut perf, ck?);
                if a.test == "T6" { r["checksum"] = sync_drv::verify6(&mut c)?.into(); }
                iters.push(r);
            }
        }
    }
    meta["ops_per_iter"] = ops.into(); meta["warmup"] = (if a.test == "T0" { 0 } else { a.warmup }).into(); meta["iters"] = iters.into();
    let s = meta.to_string();
    match &a.out { Some(p) => fs::write(p, s)?, None => println!("{s}") }
    Ok(())
}
