//! Shared harness for the Rust runners (drivers: src/main.rs, frameworks: fw/src/main.rs).
use std::{env, fs, io::{Read, Write}, time::Instant};
pub fn cpu_ns() -> i64 {
    let mut ts = libc::timespec { tv_sec: 0, tv_nsec: 0 };
    unsafe { libc::clock_gettime(libc::CLOCK_PROCESS_CPUTIME_ID, &mut ts) };
    ts.tv_sec * 1_000_000_000 + ts.tv_nsec
}
pub fn status_kb(key: &str) -> i64 {
    fs::read_to_string("/proc/self/status").unwrap().lines().find(|l| l.starts_with(key))
        .and_then(|l| l.split_whitespace().nth(1)).and_then(|v| v.parse().ok()).unwrap_or(-1)
}
pub fn srv_ticks() -> i64 {
    let Ok(pid) = env::var("MYSQLD_PID") else { return -1 };
    let Ok(s) = fs::read_to_string(format!("/proc/{pid}/stat")) else { return -1 };
    let f: Vec<&str> = s[s.rfind(')').unwrap() + 2..].split(' ').collect();
    f[11].parse::<i64>().unwrap() + f[12].parse::<i64>().unwrap()
}
pub struct Perf { ctl: Option<fs::File>, ack: Option<fs::File> }
impl Perf {
    pub fn open() -> Perf {
        match (env::var("PERF_CTL"), env::var("PERF_ACK")) {
            (Ok(c), Ok(a)) => Perf { ctl: Some(fs::OpenOptions::new().write(true).open(c).unwrap()), ack: Some(fs::File::open(a).unwrap()) },
            _ => Perf { ctl: None, ack: None },
        }
    }
    pub fn cmd(&mut self, c: &str) {
        if let (Some(ctl), Some(ack)) = (&mut self.ctl, &mut self.ack) { ctl.write_all(c.as_bytes()).unwrap(); let mut b = [0u8; 8]; let _ = ack.read(&mut b); }
    }
}
pub struct Meter { cpu: i64, wall: Instant, srv: i64, rss: i64 }
impl Meter {
    pub fn begin(p: &mut Perf) -> Meter {
        let _ = fs::write("/proc/self/clear_refs", "5");   // resets VmHWM to the current RSS
        let rss = status_kb("VmRSS:");
        let srv = srv_ticks(); p.cmd("enable\n");
        Meter { wall: Instant::now(), cpu: cpu_ns(), srv, rss }
    }
    pub fn end(self, p: &mut Perf, ck: String) -> serde_json::Value {
        let cpu = cpu_ns(); let wall = self.wall.elapsed().as_nanos() as i64; p.cmd("disable\n"); let s = srv_ticks();
        serde_json::json!({"cpu_ns": cpu - self.cpu, "wall_ns": wall, "srv_ticks": if s >= 0 && self.srv >= 0 { s - self.srv } else { -1 },
            "rss_start_kb": self.rss, "rss_peak_kb": status_kb("VmHWM:"), "rss_end_kb": status_kb("VmRSS:"), "checksum": ck})
    }
}
