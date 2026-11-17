/* Shared measurement harness for native runners (C / C++).
 * Implements the runner contract of SPEC.md section 5: per-iteration process CPU,
 * wall time, server CPU ticks, peak RSS, and perf-stat enable/disable via FIFOs. */
#pragma once
#define _GNU_SOURCE
#include <fcntl.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

typedef struct {
  long long cpu_ns, wall_ns, srv_ticks, rss_peak_kb, rss_end_kb;
  char checksum[96];
} iter_t;

static int b_perf_ctl = -1, b_perf_ack = -1;
static long long b_cpu0, b_wall0, b_srv0;

static long long b_clock(clockid_t c) {
  struct timespec ts; clock_gettime(c, &ts);
  return (long long)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

static long long b_srv_ticks(void) {
  const char *pid = getenv("MYSQLD_PID");
  if (!pid) return -1;
  char path[64], buf[2048]; snprintf(path, sizeof path, "/proc/%s/stat", pid);
  FILE *f = fopen(path, "r"); if (!f) return -1;
  size_t n = fread(buf, 1, sizeof buf - 1, f); fclose(f); buf[n] = 0;
  char *p = strrchr(buf, ')'); if (!p) return -1;
  long long ut = 0, st = 0;
  /* fields after ")": state(3) ... utime(14) stime(15) */
  sscanf(p + 2, "%*c %*d %*d %*d %*d %*d %*u %*u %*u %*u %*u %lld %lld", &ut, &st);
  return ut + st;
}

static long long b_status_kb(const char *key) {
  FILE *f = fopen("/proc/self/status", "r"); char line[256]; long long v = -1;
  size_t kl = strlen(key);
  while (f && fgets(line, sizeof line, f))
    if (!strncmp(line, key, kl)) { v = atoll(line + kl + 1); break; }
  if (f) fclose(f);
  return v;
}

static void b_perf_open(void) {
  const char *c = getenv("PERF_CTL"), *a = getenv("PERF_ACK");
  if (c && a) { b_perf_ctl = open(c, O_WRONLY); b_perf_ack = open(a, O_RDONLY); }
}

static void b_perf_cmd(const char *cmd) {
  if (b_perf_ctl < 0) return;
  if (write(b_perf_ctl, cmd, strlen(cmd)) < 0) return;
  char ack[8]; if (read(b_perf_ack, ack, sizeof ack) < 0) return;
}

static void b_begin(void) {
  int fd = open("/proc/self/clear_refs", O_WRONLY);
  if (fd >= 0) { if (write(fd, "5", 1) < 0) {} close(fd); }
  b_srv0 = b_srv_ticks();
  b_perf_cmd("enable\n");
  b_wall0 = b_clock(CLOCK_MONOTONIC);
  b_cpu0 = b_clock(CLOCK_PROCESS_CPUTIME_ID);
}

static void b_end(iter_t *it) {
  long long cpu = b_clock(CLOCK_PROCESS_CPUTIME_ID), wall = b_clock(CLOCK_MONOTONIC);
  b_perf_cmd("disable\n");
  it->cpu_ns = cpu - b_cpu0; it->wall_ns = wall - b_wall0;
  long long s = b_srv_ticks(); it->srv_ticks = (s >= 0 && b_srv0 >= 0) ? s - b_srv0 : -1;
  it->rss_peak_kb = b_status_kb("VmHWM:"); it->rss_end_kb = b_status_kb("VmRSS:");
}

static void b_na(const char *why) { fprintf(stderr, "n/a: %s\n", why); exit(3); }
static void b_die(const char *fmt, ...) {
  va_list ap; va_start(ap, fmt); vfprintf(stderr, fmt, ap); va_end(ap); fputc('\n', stderr); exit(1);
}

/* Write the result file (JSON). extra: preformatted JSON members (may be ""). */
static void b_write(const char *out, const char *stack, const char *lib, const char *test, const char *variant,
                    const char *config, const char *server, const char *tls, long long ops, int warmup,
                    iter_t *its, int n, const char *extra) {
  FILE *f = out ? fopen(out, "w") : stdout;
  if (!f) b_die("cannot write %s", out);
  fprintf(f, "{\"stack\":\"%s\",\"lib\":\"%s\",\"test\":\"%s\",\"variant\":\"%s\",\"config\":\"%s\","
             "\"server\":\"%s\",\"tls\":\"%s\",\"ops_per_iter\":%lld,\"warmup\":%d%s%s,\"iters\":[",
          stack, lib, test, variant, config, server, tls, ops, warmup, *extra ? "," : "", extra);
  for (int i = 0; i < n; i++)
    fprintf(f, "%s{\"cpu_ns\":%lld,\"wall_ns\":%lld,\"srv_ticks\":%lld,\"rss_peak_kb\":%lld,"
               "\"rss_end_kb\":%lld,\"checksum\":\"%s\"}", i ? "," : "",
            its[i].cpu_ns, its[i].wall_ns, its[i].srv_ticks, its[i].rss_peak_kb, its[i].rss_end_kb, its[i].checksum);
  fprintf(f, "]}\n");
  if (out) fclose(f);
}
