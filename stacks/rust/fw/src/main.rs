//! Rust framework runner (Phase 3): Diesel (sync, on libmysqlclient) and SeaORM (async, on sqlx, tokio current-thread).
//! default config: the framework's usual idiom (load model structs); tuned: select only the needed columns
//! (exactly as listed in reports/tuned.json). Same CLI/env contract as the other runners (SPEC.md section 5).
use std::{env, fs};

#[path = "../../src/harness.rs"]
mod harness;
mod wide;
use harness::*;

#[derive(Debug)]
pub struct NA(pub String);
impl std::fmt::Display for NA { fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result { write!(f, "{}", self.0) } }
impl std::error::Error for NA {}
type R<T> = Result<T, Box<dyn std::error::Error>>;
fn na<T>(m: &str) -> R<T> { Err(Box::new(NA(m.into()))) }

pub struct Args { fw: String, test: String, variant: String, config: String, server: String, out: Option<String>, warmup: usize, iters: usize }
fn e(k: &str, d: &str) -> String { env::var(k).ok().filter(|v| !v.is_empty()).unwrap_or_else(|| d.to_string()) }
fn t1_mode(v: &str) -> &'static str { if v.starts_with("tls-verify") { "verify" } else if v.starts_with("tls") { "on" } else { "off" } }
fn row_b(i: i32) -> String { if i % 10 == 0 { format!("o'k-{i}") } else { format!("name-{i}") } }
fn touch(b: &[u8]) -> i64 { let mut c = b.len() as i64; let mut i = 0; while i < b.len() { c += b[i] as i64; i += 64; } c }
fn t5_parts(v: &str) -> (String, String, bool) {
    let (cls, col) = v.split_once('-').unwrap();
    (cls.to_string(), col.trim_end_matches("-parse").to_string(), col.ends_with("-parse"))
}
/// Connection URL (both frameworks take one). tls: off/on/verify.
fn url(tls: &str, sock: bool, diesel: bool) -> String {
    let (u, p, d) = (e("DB_USER", "bench"), e("DB_PASS", "bench"), e("DB_NAME", "bench"));
    let mut q: Vec<String> = vec![];
    let host = if sock {
        q.push(format!("{}={}", if diesel { "unix_socket" } else { "socket" }, e("DB_SOCKET", ""))); "localhost".to_string()
    } else { format!("{}:{}", e("DB_HOST", "127.0.0.1"), e("DB_PORT", "3306")) };
    let (mode_k, ca_k) = if diesel { ("ssl_mode", "ssl_ca") } else { ("ssl-mode", "ssl-ca") };
    match tls {
        "off" => q.push(format!("{mode_k}=disabled")),
        "on" => q.push(format!("{mode_k}=required")),
        _ => { q.push(format!("{mode_k}=verify_identity")); q.push(format!("{ca_k}={}", e("DB_CA", ""))); }
    }
    format!("mysql://{u}:{p}@{host}/{d}?{}", q.join("&"))
}

// ======================================================================== Diesel
mod dsl {
    diesel::table! { t_int (id) { id -> Integer, v -> Integer, } }
    diesel::table! { t_blob (id) { id -> Integer, size_class -> Varchar, doc -> Text, doc_bin -> Blob, } }
    diesel::table! { t_bulk (id) { id -> Integer, a -> Integer, b -> Varchar, c -> Double, } }
}
mod diesel_fw {
    use super::*;
    use diesel::{prelude::*, sql_types::*, mysql::MysqlConnection, connection::DefaultLoadingMode};
    use dsl::*;
    #[derive(Queryable, Selectable)] #[diesel(table_name = t_int, check_for_backend(diesel::mysql::Mysql))]
    pub struct TInt { pub id: i32, pub v: i32 }
    #[derive(Queryable, Selectable)] #[diesel(table_name = t_blob, check_for_backend(diesel::mysql::Mysql))]
    pub struct TBlob { pub id: i32, pub size_class: String, pub doc: String, pub doc_bin: Vec<u8> }
    #[derive(Insertable)] #[diesel(table_name = t_bulk)]
    pub struct NewBulk { pub id: i32, pub a: i32, pub b: String, pub c: f64 }
    #[derive(QueryableByName)] struct Kv { #[diesel(sql_type = Text, column_name = "Value")] value: String }
    #[derive(QueryableByName)] struct Ck { #[diesel(sql_type = BigInt)] n: i64, #[diesel(sql_type = BigInt)] sa: i64, #[diesel(sql_type = BigInt)] sb: i64 }

    pub fn connect(tls: &str, sock: bool) -> R<MysqlConnection> { Ok(MysqlConnection::establish(&url(tls, sock, true))?) }
    pub fn exec(c: &mut MysqlConnection, sql: &str) -> R<()> { diesel::sql_query(sql).execute(c)?; Ok(()) }
    pub fn cipher(c: &mut MysqlConnection) -> String {
        diesel::sql_query("SHOW SESSION STATUS LIKE 'Ssl_cipher'").load::<Kv>(c).ok().and_then(|v| v.into_iter().next())
            .map(|k| k.value).filter(|v| !v.is_empty()).unwrap_or("none".into())
    }
    pub fn verify6(c: &mut MysqlConnection) -> R<String> {
        let r = diesel::sql_query("SELECT COUNT(*) AS n, CAST(SUM(a) AS SIGNED) AS sa, CAST(SUM(CHAR_LENGTH(b)) AS SIGNED) AS sb FROM t_bulk").get_result::<Ck>(c)?;
        Ok(format!("{}:{}:{}", r.n, r.sa, r.sb))
    }
    pub fn step(a: &Args, c: &mut MysqlConnection, ids: &[i32], ops: &mut i64) -> R<String> {
        let (v, tuned) = (a.variant.as_str(), a.config == "tuned");
        match a.test.as_str() {
            "T1" => { let n = if t1_mode(v) == "off" { 3000 } else { 2000 }; for _ in 0..n { drop(connect(t1_mode(v), v == "socket")?); } *ops = n; Ok(n.to_string()) }
            "T2" => {
                let mut s = 0i64;
                if tuned { for id in ids { s += t_int::table.find(id).select(t_int::v).first::<i32>(c)? as i64; } }
                else { for id in ids { s += t_int::table.find(id).select(TInt::as_select()).first(c)?.v as i64; } }
                *ops = ids.len() as i64; Ok(s.to_string())
            }
            "T3" => {
                let mut s = 0i64;
                match (tuned, v.ends_with("streamed")) {
                    (false, false) => for r in t_int::table.select(TInt::as_select()).load(c)? { s += r.v as i64 },
                    (false, true) => for r in t_int::table.select(TInt::as_select()).load_iter::<TInt, DefaultLoadingMode>(c)? { s += r?.v as i64 },
                    (true, false) => for x in t_int::table.select(t_int::v).load::<i32>(c)? { s += x as i64 },
                    (true, true) => for x in t_int::table.select(t_int::v).load_iter::<i32, DefaultLoadingMode>(c)? { s += x? as i64 },
                }
                *ops = 1_000_000; Ok(s.to_string())
            }
            "T4" => {
                let (mut nn, mut isum, mut slen, mut n) = (0i64, 0i64, 0i64, 0i64);
                let mut add = |t: (i64, i64, i64)| { nn += t.0; isum += t.1; slen += t.2; n += 1; };
                if v.starts_with("int") { for r in wide::d_t_wide_int::t_wide_int::table.select(wide::DWideInt::as_select()).load(c)? { add(r.touch()) } }
                else { for r in wide::d_t_wide_mix::t_wide_mix::table.select(wide::DWideMix::as_select()).load(c)? { add(r.touch()) } }
                *ops = n * 100; Ok((nn + isum + slen).to_string())
            }
            "T5" => {
                let (cls, col, parse) = t5_parts(v); let (mut ck, mut bytes) = (0i64, 0i64);
                for _ in 0..20 {
                    ck = 0;
                    let q = t_blob::table.filter(t_blob::size_class.eq(&cls)).order(t_blob::id);
                    let mut f = |d: &[u8]| -> R<()> { ck += touch(d); bytes += d.len() as i64; if parse { let _: serde_json::Value = serde_json::from_slice(d)?; } Ok(()) };
                    match (tuned, col.as_str()) {
                        (false, "doc") => for r in q.select(TBlob::as_select()).load(c)? { f(r.doc.as_bytes())? },
                        (false, _) => for r in q.select(TBlob::as_select()).load(c)? { f(&r.doc_bin)? },
                        (true, "doc") => for d in q.select(t_blob::doc).load::<String>(c)? { f(d.as_bytes())? },
                        (true, _) => for d in q.select(t_blob::doc_bin).load::<Vec<u8>>(c)? { f(&d)? },
                    }
                }
                *ops = bytes / 1024; Ok(ck.to_string())
            }
            _ => {
                for st in (1..=1_000_000i32).step_by(1000) {
                    let rows: Vec<NewBulk> = (st..st + 1000).map(|i| NewBulk { id: i, a: i * 3, b: row_b(i), c: i as f64 * 0.5 }).collect();
                    diesel::insert_into(t_bulk::table).values(&rows).execute(c)?;   // one multi-row INSERT
                }
                *ops = 1000; Ok(String::new())
            }
        }
    }
}

// ======================================================================== SeaORM
mod ent {
    pub mod t_int {
        use sea_orm::entity::prelude::*;
        #[derive(Clone, Debug, PartialEq, DeriveEntityModel)]
        #[sea_orm(table_name = "t_int")]
        pub struct Model { #[sea_orm(primary_key, auto_increment = false)] pub id: i32, pub v: i32 }
        #[derive(Copy, Clone, Debug, EnumIter, DeriveRelation)] pub enum Relation {}
        impl ActiveModelBehavior for ActiveModel {}
    }
    pub mod t_blob {
        use sea_orm::entity::prelude::*;
        #[derive(Clone, Debug, PartialEq, DeriveEntityModel)]
        #[sea_orm(table_name = "t_blob")]
        pub struct Model { #[sea_orm(primary_key, auto_increment = false)] pub id: i32, pub size_class: String, pub doc: String }
        #[derive(Copy, Clone, Debug, EnumIter, DeriveRelation)] pub enum Relation {}
        impl ActiveModelBehavior for ActiveModel {}
    }
    // t_blob is mapped as two entities (doc / doc_bin): SeaORM 2.0.4 cannot read a MySQL JSON column into String
    // (only Json, which parses), so on Percona an entity that includes doc cannot be loaded at all.
    pub mod t_blob_bin {
        use sea_orm::entity::prelude::*;
        #[derive(Clone, Debug, PartialEq, DeriveEntityModel)]
        #[sea_orm(table_name = "t_blob")]
        pub struct Model { #[sea_orm(primary_key, auto_increment = false)] pub id: i32, pub size_class: String, pub doc_bin: Vec<u8> }
        #[derive(Copy, Clone, Debug, EnumIter, DeriveRelation)] pub enum Relation {}
        impl ActiveModelBehavior for ActiveModel {}
    }
    pub mod t_bulk {
        use sea_orm::entity::prelude::*;
        #[derive(Clone, Debug, PartialEq, DeriveEntityModel)]
        #[sea_orm(table_name = "t_bulk")]
        pub struct Model { #[sea_orm(primary_key, auto_increment = false)] pub id: i32, pub a: i32, pub b: String, pub c: f64 }
        #[derive(Copy, Clone, Debug, EnumIter, DeriveRelation)] pub enum Relation {}
        impl ActiveModelBehavior for ActiveModel {}
    }
}
mod sea_fw {
    use super::*;
    use futures_util::TryStreamExt;
    use sea_orm::{entity::*, query::*, ConnectOptions, ConnectionTrait, Database, DatabaseConnection, FromQueryResult, Statement};
    use ent::*;
    pub async fn connect(tls: &str, sock: bool) -> R<DatabaseConnection> {
        let mut o = ConnectOptions::new(url(tls, sock, false));
        o.max_connections(1).min_connections(1);
        Ok(Database::connect(o).await?)
    }
    pub async fn exec(c: &DatabaseConnection, sql: &str) -> R<()> { c.execute_unprepared(sql).await?; Ok(()) }
    #[allow(non_snake_case)] #[derive(FromQueryResult)] struct Kv { Value: String }   // SHOW STATUS column name; from_col is not honoured
    #[derive(FromQueryResult)] struct Ck { n: i64, sa: i64, sb: i64 }
    pub async fn cipher(c: &DatabaseConnection) -> String {
        match Kv::find_by_statement(Statement::from_string(c.get_database_backend(), "SHOW SESSION STATUS LIKE 'Ssl_cipher'")).one(c).await {
            Ok(Some(k)) if !k.Value.is_empty() => k.Value, Ok(_) => "none".into(), Err(e) => { eprintln!("cipher: {e}"); "none".into() } }
    }
    pub async fn verify6(c: &DatabaseConnection) -> R<String> {
        let r = Ck::find_by_statement(Statement::from_string(c.get_database_backend(),
            "SELECT COUNT(*) AS n, CAST(SUM(a) AS SIGNED) AS sa, CAST(SUM(CHAR_LENGTH(b)) AS SIGNED) AS sb FROM t_bulk")).one(c).await?.unwrap();
        Ok(format!("{}:{}:{}", r.n, r.sa, r.sb))
    }
    pub async fn step(a: &Args, c: &DatabaseConnection, ids: &[i32], ops: &mut i64) -> R<String> {
        let (v, tuned) = (a.variant.as_str(), a.config == "tuned");
        match a.test.as_str() {
            "T1" => { let n = if t1_mode(v) == "off" { 3000 } else { 2000 }; for _ in 0..n { connect(t1_mode(v), v == "socket").await?.close().await?; } *ops = n; Ok(n.to_string()) }
            "T2" => {
                let mut s = 0i64;
                if tuned {
                    for id in ids { s += t_int::Entity::find_by_id(*id).select_only().column(t_int::Column::V).into_tuple::<i32>().one(c).await?.unwrap() as i64; }
                } else {
                    for id in ids { s += t_int::Entity::find_by_id(*id).one(c).await?.unwrap().v as i64; }
                }
                *ops = ids.len() as i64; Ok(s.to_string())
            }
            "T3" => {
                let mut s = 0i64;
                match (tuned, v.ends_with("streamed")) {
                    (false, false) => for m in t_int::Entity::find().all(c).await? { s += m.v as i64 },
                    (false, true) => { let mut st = t_int::Entity::find().stream(c).await?; while let Some(m) = st.try_next().await? { s += m.v as i64 } }
                    (true, false) => for x in t_int::Entity::find().select_only().column(t_int::Column::V).into_tuple::<i32>().all(c).await? { s += x as i64 },
                    (true, true) => { let mut st = t_int::Entity::find().select_only().column(t_int::Column::V).into_tuple::<i32>().stream(c).await?;
                                      while let Some(x) = st.try_next().await? { s += x as i64 } }
                }
                *ops = 1_000_000; Ok(s.to_string())
            }
            "T4" => {
                let (mut nn, mut isum, mut slen, mut n) = (0i64, 0i64, 0i64, 0i64);
                let mut add = |t: (i64, i64, i64)| { nn += t.0; isum += t.1; slen += t.2; n += 1; };
                if v.starts_with("int") { for m in wide::s_t_wide_int::Entity::find().all(c).await? { add(m.touch()) } }
                else { for m in wide::s_t_wide_mix::Entity::find().all(c).await? { add(m.touch()) } }
                *ops = n * 100; Ok((nn + isum + slen).to_string())
            }
            "T5" => {
                let (cls, col, parse) = t5_parts(v); let (mut ck, mut bytes) = (0i64, 0i64);
                for _ in 0..20 {
                    ck = 0;
                    let q = t_blob::Entity::find().filter(t_blob::Column::SizeClass.eq(cls.as_str())).order_by_asc(t_blob::Column::Id);
                    let qb = t_blob_bin::Entity::find().filter(t_blob_bin::Column::SizeClass.eq(cls.as_str())).order_by_asc(t_blob_bin::Column::Id);
                    let mut f = |d: &[u8]| -> R<()> { ck += touch(d); bytes += d.len() as i64; if parse { let _: serde_json::Value = serde_json::from_slice(d)?; } Ok(()) };
                    match (tuned, col.as_str()) {
                        (false, "doc") => for m in q.all(c).await? { f(m.doc.as_bytes())? },
                        (false, _) => for m in qb.all(c).await? { f(&m.doc_bin)? },
                        (true, "doc") => for d in q.select_only().column(t_blob::Column::Doc).into_tuple::<String>().all(c).await? { f(d.as_bytes())? },
                        (true, _) => for d in qb.select_only().column(t_blob_bin::Column::DocBin).into_tuple::<Vec<u8>>().all(c).await? { f(&d)? },
                    }
                }
                *ops = bytes / 1024; Ok(ck.to_string())
            }
            _ => {
                for st in (1..=1_000_000i32).step_by(1000) {
                    let rows = (st..st + 1000).map(|i| t_bulk::ActiveModel { id: Set(i), a: Set(i * 3), b: Set(row_b(i)), c: Set(i as f64 * 0.5) });
                    t_bulk::Entity::insert_many(rows).exec(c).await?;   // one multi-row INSERT
                }
                *ops = 1000; Ok(String::new())
            }
        }
    }
}

// ======================================================================== main
fn main() {
    let rss_start = status_kb("VmRSS:");
    let _ = rustls::crypto::aws_lc_rs::default_provider().install_default();
    let mut a = Args { fw: "diesel".into(), test: "T0".into(), variant: String::new(), config: "default".into(), server: "ps".into(), out: None, warmup: 2, iters: 5 };
    let argv: Vec<String> = env::args().collect();
    let mut i = 1;
    while i < argv.len() {
        let v = argv.get(i + 1).cloned().unwrap_or_default();
        match argv[i].as_str() {
            "--fw" => a.fw = v, "--test" => a.test = v, "--variant" => a.variant = v, "--config" => a.config = v,
            "--server" => a.server = v, "--out" => a.out = Some(v), "--warmup" => a.warmup = v.parse().unwrap(), "--iters" => a.iters = v.parse().unwrap(),
            "--floor" => { eprintln!("n/a: floor not implemented in Rust"); std::process::exit(3) }
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
    let v = a.variant.as_str();
    if a.test == "T1" && v.contains("resume") { return na("frameworks are measured on tcp, socket, tls and tls-verify"); }
    if a.test == "T2" && v != "param" { return na("frameworks bind parameters themselves (variant: param)"); }
    if a.test == "T3" && v.starts_with("text") { return na("both frameworks use prepared statements (binary protocol)"); }
    if a.test == "T4" && v.ends_with("text") { return na("both frameworks use prepared statements (binary protocol)"); }
    if a.test == "T6" && v != "batch" { return na("frameworks insert through their bulk API (the batch variant)"); }
    if a.fw == "seaorm" && a.server == "ps" && a.test == "T5" && v.contains("-doc") && !v.contains("doc_bin") {
        return na("SeaORM 2.0.4 cannot read a MySQL JSON column as text (String: mismatched types); only as Json, which parses every value");
    }
    let diesel = a.fw == "diesel";
    let (stack, lib) = if diesel { ("rust-diesel", format!("Diesel {} on libmysqlclient", env!("DIESEL_VERSION"))) }
                       else { ("rust-seaorm", format!("SeaORM {} on sqlx {}", env!("SEAORM_VERSION"), env!("SQLX_VERSION"))) };
    let mut meta = serde_json::json!({"stack": stack, "lib": lib, "test": a.test, "variant": a.variant, "config": a.config, "server": a.server});
    let tls = e("DB_TLS", "off");
    let ids: Vec<i32> = if a.test == "T2" { fs::read_to_string(format!("{}/ids_200k.txt", e("DATA_DIR", "/root/bench/data")))?.lines().map(|l| l.parse().unwrap()).collect() } else { vec![] };
    let (mut iters, mut ops) = (vec![], 0i64);
    let mut perf = Perf::open();
    if diesel {
        if a.test == "T0" {
            perf = Perf::open(); let m = Meter::begin(&mut perf);
            let mut c = diesel_fw::connect(&tls, false)?; diesel_fw::exec(&mut c, "SELECT 1")?;
            iters.push(m.end(&mut perf, "1".into())); meta["tls"] = diesel_fw::cipher(&mut c).into(); meta["rss_start_kb"] = rss_start.into(); ops = 1;
        } else {
            if a.test == "T1" { let mut c2 = diesel_fw::connect(t1_mode(v), v == "socket")?; meta["tls"] = diesel_fw::cipher(&mut c2).into(); }
            let mut c = diesel_fw::connect(&tls, false)?;
            if a.test != "T1" { meta["tls"] = diesel_fw::cipher(&mut c).into(); }
            meta["rss_baseline_kb"] = status_kb("VmRSS:").into();
            perf = Perf::open();
            for k in 0..a.warmup + a.iters {
                if a.test == "T6" { diesel_fw::exec(&mut c, "TRUNCATE TABLE t_bulk")?; }
                if k < a.warmup { diesel_fw::step(a, &mut c, &ids, &mut ops)?; continue; }
                let m = Meter::begin(&mut perf); let ck = diesel_fw::step(a, &mut c, &ids, &mut ops); let mut r = m.end(&mut perf, ck?);
                if a.test == "T6" { r["checksum"] = diesel_fw::verify6(&mut c)?.into(); }
                iters.push(r);
            }
        }
    } else {
        let rt = tokio::runtime::Builder::new_current_thread().enable_all().build()?;
        rt.block_on(async {
            if a.test == "T0" {
                perf = Perf::open(); let m = Meter::begin(&mut perf);
                let c = sea_fw::connect(&tls, false).await?; sea_fw::exec(&c, "SELECT 1").await?;
                iters.push(m.end(&mut perf, "1".into())); meta["tls"] = sea_fw::cipher(&c).await.into(); meta["rss_start_kb"] = rss_start.into(); ops = 1;
                return Ok::<(), Box<dyn std::error::Error>>(());
            }
            if a.test == "T1" { let c2 = sea_fw::connect(t1_mode(v), v == "socket").await?; meta["tls"] = sea_fw::cipher(&c2).await.into(); c2.close().await?; }
            let c = sea_fw::connect(&tls, false).await?;
            if a.test != "T1" { meta["tls"] = sea_fw::cipher(&c).await.into(); }
            meta["rss_baseline_kb"] = status_kb("VmRSS:").into();
            perf = Perf::open();
            for k in 0..a.warmup + a.iters {
                if a.test == "T6" { sea_fw::exec(&c, "TRUNCATE TABLE t_bulk").await?; }
                if k < a.warmup { sea_fw::step(a, &c, &ids, &mut ops).await?; continue; }
                let m = Meter::begin(&mut perf); let ck = sea_fw::step(a, &c, &ids, &mut ops).await; let mut r = m.end(&mut perf, ck?);
                if a.test == "T6" { r["checksum"] = sea_fw::verify6(&c).await?.into(); }
                iters.push(r);
            }
            Ok(())
        })?;
    }
    meta["ops_per_iter"] = ops.into(); meta["warmup"] = (if a.test == "T0" { 0 } else { a.warmup }).into(); meta["iters"] = iters.into();
    let s = meta.to_string();
    match &a.out { Some(p) => fs::write(p, s)?, None => println!("{s}") }
    Ok(())
}
