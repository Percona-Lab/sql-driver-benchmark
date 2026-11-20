# Measurement pitfalls found while building this benchmark

Client-side driver cost is often a few microseconds per operation, much of it in the kernel (socket
setup, send/receive). That makes it sensitive to how the measurement host is set up. These are the
distortions we found, with the numbers from our host (AMD EPYC 4245P, Ubuntu 26.04, kernel 7.0). All
numbers are client CPU per operation for Oracle libmysqlclient 9.7 against Percona Server 9.7 on loopback.

| Pitfall | Effect | Hits | Fix |
|---|---|---|---|
| Hardware counters (`perf stat` with HW events) attached to timed runs | TCP connect 24.0 → 30.3 µs (**+26%**); point select ~+2% | anything with many context switches | collect counters in separate processes |
| `nohz_full` on the isolated client core | TCP connect 23.9 → 27.3 µs (**+14%**); point select +2%; streaming rows 0% | every kernel entry/exit | isolate with `isolcpus` only |
| TIME_WAIT sockets piling up from earlier connects | TCP connect 27 → 57 µs (**+110%**), and dependent on what ran before | connect tests | cap with `net.ipv4.tcp_max_tw_buckets` |
| Package side effects re-pointing `/etc/mysql/my.cnf` | server silently started with defaults (128 MB buffer pool, no TLS cert, binlog on) | everything | verify server variables on every start |
| `caching_sha2_password` cache emptied by a server restart | non-TLS TCP logins fail (or take the slow full-auth path) | connect tests, any non-TLS client | log in once over the Unix socket after each restart |
| A client using too much memory, with no limit on it | the kernel's OOM killer picked **mysqld**; systemd restarted it with an empty auth cache, so later tests failed to log in | any memory-hungry client | protect the servers (`OOMScoreAdjust=-1000`), cap each client (8 GB cgroup), detect a server restart after every process |
| Test CA without `keyUsage` / strict extensions | Python 3.13+ (`VERIFY_X509_STRICT`) rejects it; looks like a driver failure | TLS-verify tests | generate a strict-X.509-clean CA |

## Details

**Hardware counters.** Counting hardware events per process makes the kernel save and restore the
PMU state on every context switch of that process. A connect is a handful of blocking round trips,
so each one pays several times. Software counters (`task-clock`, `context-switches`) cost ~4%. Our
timed runs now have no `perf` attached at all; two extra processes per cell, one per event set,
collect cycles, instructions, IPC and cache/TLB misses. Those ratios are what counters are good for.

**`nohz_full`.** Full dynticks enables context tracking on the core, which adds work to every
user↔kernel transition. It is meant for long-running compute that rarely enters the kernel; a database
client is the opposite. `isolcpus` alone keeps other tasks off the client core without that cost.
After the change, the isolated core measured the same as a normal core (23.5 vs 23.9 µs per connect).

**TIME_WAIT.** The side that closes a TCP connection first keeps a TIME_WAIT entry for 60 s. The client
closes first (`COM_QUIT`, then close), so a connect test running 10,000 connections per iteration
accumulates tens of thousands of entries, and choosing a local port for each new connect gets slower.
Worse, the cost depends on how many connects ran in the previous minute, i.e. on test order. With
`tcp_max_tw_buckets=4096`, three back-to-back runs measured 27.3 µs each. Appropriate on a loopback-only
benchmark host; not a production setting.

**Config drift.** Installing MariaDB client packages pulled in `mariadb-common`, which switched the
`my.cnf` alternative to MariaDB's file, so Percona Server's settings directory was no longer read. The
server started fine, just without the benchmark configuration. `host/dbctl.sh` now resets the
alternative and refuses to continue unless buffer pool size, binlog, flush setting, packet size and TLS
certificate match.

## Not pitfalls, but easy to misread

- **Server pace changes client CPU.** MySQL (and so Percona Server) stores `JSON` in a binary format and
  converts it back to text, reformatted, on every read: ~1.9 µs/KB server CPU for 100 KB documents against
  ~0.15 µs/KB for the same bytes as `LONGBLOB`. MariaDB stores `JSON` as text and returns it unchanged.
  The slower server send means data arrives in smaller pieces and the client makes more `recv` calls, so
  the same client does 10–30% more CPU per KB reading JSON from Percona Server than from MariaDB, while
  `LONGBLOB` costs the same on both. Compare drivers against the same server, or use blob data. (This is
  the cost of whole-document text reads; the binary format has its own benefits: validation on insert,
  path access without parsing, partial updates.)
- **"TLS on" without a CA is not cheap TLS.** Both C client libraries load the full system CA bundle on
  every connection when no CA is configured (~3.6 ms vs ~0.7 ms CPU per connect with a CA file).
