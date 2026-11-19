package main

// Shared measurement harness (SPEC.md section 5).

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"runtime"
	"strconv"
	"strings"
	"time"

	"golang.org/x/sys/unix"
)

type NA struct{ Why string }

func (e NA) Error() string { return e.Why }
func na(f string, a ...any) error { return NA{fmt.Sprintf(f, a...)} }
func isNA(err error) (string, bool) {
	var n NA
	if errors.As(err, &n) {
		return n.Why, true
	}
	return "", false
}

type IterRec struct {
	CPU      int64  `json:"cpu_ns"`
	Wall     int64  `json:"wall_ns"`
	Srv      int64  `json:"srv_ticks"`
	RSSStart int64  `json:"rss_start_kb"`
	RSSPeak  int64  `json:"rss_peak_kb"`
	RSSEnd   int64  `json:"rss_end_kb"`
	Checksum string `json:"checksum"`
	Alloc    uint64 `json:"alloc_bytes"`
	GC       uint32 `json:"gc_count"`
	GCns     uint64 `json:"gc_pause_ns"`
}

var perfCtl, perfAck *os.File

func perfOpen() {
	c, a := os.Getenv("PERF_CTL"), os.Getenv("PERF_ACK")
	if c != "" && a != "" {
		perfCtl, _ = os.OpenFile(c, os.O_WRONLY, 0)
		perfAck, _ = os.OpenFile(a, os.O_RDONLY, 0)
	}
}

func perfCmd(cmd string) {
	if perfCtl == nil {
		return
	}
	perfCtl.WriteString(cmd)
	b := make([]byte, 8)
	perfAck.Read(b)
}

func cpuNs() int64 {
	var ts unix.Timespec
	unix.ClockGettime(unix.CLOCK_PROCESS_CPUTIME_ID, &ts)
	return ts.Nano()
}

func statusKB(key string) int64 {
	b, _ := os.ReadFile("/proc/self/status")
	for _, l := range strings.Split(string(b), "\n") {
		if strings.HasPrefix(l, key) {
			f := strings.Fields(l)
			v, _ := strconv.ParseInt(f[1], 10, 64)
			return v
		}
	}
	return -1
}

func srvTicks() int64 {
	pid := os.Getenv("MYSQLD_PID")
	if pid == "" {
		return -1
	}
	b, err := os.ReadFile("/proc/" + pid + "/stat")
	if err != nil {
		return -1
	}
	s := string(b)
	f := strings.Fields(s[strings.LastIndex(s, ")")+2:])
	u, _ := strconv.ParseInt(f[11], 10, 64)
	k, _ := strconv.ParseInt(f[12], 10, 64)
	return u + k
}

type meter struct {
	cpu, wall, srv, rss int64
	ms             runtime.MemStats
}

func (m *meter) begin() {
	os.WriteFile("/proc/self/clear_refs", []byte("5"), 0) // resets VmHWM to the current RSS
	m.rss = statusKB("VmRSS:")
	runtime.ReadMemStats(&m.ms)
	m.srv = srvTicks()
	perfCmd("enable\n")
	m.wall = time.Now().UnixNano()
	m.cpu = cpuNs()
}

func (m *meter) end(ck string) IterRec {
	cpu, wall := cpuNs(), time.Now().UnixNano()
	perfCmd("disable\n")
	var ms runtime.MemStats
	runtime.ReadMemStats(&ms)
	s := srvTicks()
	r := IterRec{CPU: cpu - m.cpu, Wall: wall - m.wall, Srv: -1, RSSStart: m.rss, RSSPeak: statusKB("VmHWM:"), RSSEnd: statusKB("VmRSS:"),
		Checksum: ck, Alloc: ms.TotalAlloc - m.ms.TotalAlloc, GC: ms.NumGC - m.ms.NumGC, GCns: ms.PauseTotalNs - m.ms.PauseTotalNs}
	if s >= 0 && m.srv >= 0 {
		r.Srv = s - m.srv
	}
	return r
}

func writeResult(out string, meta map[string]any, iters []IterRec) {
	meta["iters"] = iters
	b, _ := json.Marshal(meta)
	if out == "" {
		os.Stdout.Write(append(b, '\n'))
	} else {
		os.WriteFile(out, b, 0644)
	}
}

func env(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

// touch for T5: length + code units at stride 64
func touch(b []byte) int64 {
	c := int64(len(b))
	for i := 0; i < len(b); i += 64 {
		c += int64(b[i])
	}
	return c
}

func touchStr(s string) int64 {
	c := int64(len(s))
	for i := 0; i < len(s); i += 64 {
		c += int64(s[i])
	}
	return c
}

func rowB(i int) string {
	if i%10 == 0 {
		return "o'k-" + strconv.Itoa(i)
	}
	return "name-" + strconv.Itoa(i)
}

// application-level escaping for drivers that export none (go-sql-driver)
func escapeApp(s string) string {
	if !strings.ContainsAny(s, "'\\\x00\n\r\x1a\"") {
		return s
	}
	var b strings.Builder
	for _, r := range s {
		switch r {
		case '\'', '\\', '"':
			b.WriteByte('\\')
			b.WriteRune(r)
		case 0:
			b.WriteString("\\0")
		case '\n':
			b.WriteString("\\n")
		case '\r':
			b.WriteString("\\r")
		case 0x1a:
			b.WriteString("\\Z")
		default:
			b.WriteRune(r)
		}
	}
	return b.String()
}
