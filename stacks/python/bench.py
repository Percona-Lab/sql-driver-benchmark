"""Shared measurement harness for Python runners (SPEC.md section 5)."""
import gc, json, os, sys, time

_ctl = _ack = None


def status_kb(key):
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith(key):
                return int(line.split()[1])
    return -1


def srv_ticks():
    pid = os.environ.get("MYSQLD_PID")
    if not pid:
        return -1
    with open(f"/proc/{pid}/stat") as f:
        s = f.read()
    fields = s[s.rindex(")") + 2:].split()
    return int(fields[11]) + int(fields[12])


def perf_open():
    global _ctl, _ack
    c, a = os.environ.get("PERF_CTL"), os.environ.get("PERF_ACK")
    if c and a:
        _ctl = os.open(c, os.O_WRONLY)
        _ack = os.open(a, os.O_RDONLY)


def _perf(cmd):
    if _ctl is not None:
        os.write(_ctl, cmd)
        os.read(_ack, 8)


class Iter:
    def begin(self):
        with open("/proc/self/clear_refs", "w") as f:
            f.write("5")
        self.gc0 = sum(s["collections"] for s in gc.get_stats())
        self.srv0 = srv_ticks()
        _perf(b"enable\n")
        self.wall0 = time.monotonic_ns()
        self.cpu0 = time.process_time_ns()

    def end(self, checksum):
        cpu, wall = time.process_time_ns(), time.monotonic_ns()
        _perf(b"disable\n")
        s = srv_ticks()
        return {"cpu_ns": cpu - self.cpu0, "wall_ns": wall - self.wall0,
                "srv_ticks": s - self.srv0 if s >= 0 and self.srv0 >= 0 else -1,
                "rss_peak_kb": status_kb("VmHWM:"), "rss_end_kb": status_kb("VmRSS:"), "checksum": str(checksum),
                "gc_count": sum(st["collections"] for st in gc.get_stats()) - self.gc0}


class NA(Exception):
    pass


def write(out, meta, iters):
    doc = dict(meta, iters=iters)
    if out:
        with open(out, "w") as f:
            json.dump(doc, f)
    else:
        json.dump(doc, sys.stdout)
