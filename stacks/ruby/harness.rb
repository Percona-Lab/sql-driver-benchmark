# Shared harness for runner.rb (drivers) and fw.rb (frameworks): argument parsing, CPU/RSS/perf metering.
require "json"
RSS_START = File.foreach("/proc/self/status").find { |l| l.start_with?("VmRSS:") }.split[1].to_i
A = { driver: "mysql2", test: "T0", variant: "", config: "default", server: "ps", out: nil, warmup: 2, iters: 5, floor: false }
i = 0
while i < ARGV.size
  k = ARGV[i].sub(/^--/, "").to_sym
  if k == :floor then A[:floor] = true else A[k] = %i[warmup iters].include?(k) ? ARGV[i += 1].to_i : ARGV[i += 1] end
  i += 1
end
V = A[:variant]; TUNED = A[:config] == "tuned"
class NA < StandardError; end
def env(k, d = nil) = (v = ENV[k]) && !v.empty? ? v : d

# ------------------------------------------------------------------ harness
def status_kb(key) = File.foreach("/proc/self/status").find { |l| l.start_with?(key) }&.split&.[](1).to_i
def srv_ticks
  pid = ENV["MYSQLD_PID"] or return -1
  s = File.read("/proc/#{pid}/stat"); f = s[(s.rindex(")") + 2)..].split
  f[11].to_i + f[12].to_i
rescue Errno::ENOENT
  -1
end
$ctl = $ack = nil
def perf_open
  return unless ENV["PERF_CTL"] && ENV["PERF_ACK"]
  $ctl = File.open(ENV["PERF_CTL"], "w"); $ack = File.open(ENV["PERF_ACK"], "r")
end
def perf(cmd) = $ctl && ($ctl.write(cmd); $ctl.flush; $ack.readpartial(8))
class Meter
  def begin_
    File.write("/proc/self/clear_refs", "5"); @rss = status_kb("VmRSS:"); @gc = GC.count; @alloc = GC.stat(:total_allocated_objects); @srv = srv_ticks
    perf("enable\n"); @wall = Process.clock_gettime(Process::CLOCK_MONOTONIC, :nanosecond)
    @cpu = Process.clock_gettime(Process::CLOCK_PROCESS_CPUTIME_ID, :nanosecond)
  end
  def end_(ck)
    cpu = Process.clock_gettime(Process::CLOCK_PROCESS_CPUTIME_ID, :nanosecond); wall = Process.clock_gettime(Process::CLOCK_MONOTONIC, :nanosecond)
    perf("disable\n"); s = srv_ticks
    { cpu_ns: cpu - @cpu, wall_ns: wall - @wall, srv_ticks: s >= 0 && @srv >= 0 ? s - @srv : -1, rss_start_kb: @rss, rss_peak_kb: status_kb("VmHWM:"),
      rss_end_kb: status_kb("VmRSS:"), checksum: ck.to_s, gc_count: GC.count - @gc, alloc_objects: GC.stat(:total_allocated_objects) - @alloc }
  end
end


# Warm-up + measured iterations. reset: called before every iteration (e.g. TRUNCATE); post: (result) -> extra fields.
# Adaptive warm-up (YJIT): warm up until the last 3 iterations are within 5% of each other (min --warmup, cap WARMUP_CAP iterations / WARMUP_CAP_S seconds)
def iterate(meta, fn, reset: nil, post: nil)
  perf_open; iters = []; start = 0
  if ENV["ADAPTIVE_WARMUP"]
    w = []; t0 = Process.clock_gettime(Process::CLOCK_MONOTONIC); cap = env("WARMUP_CAP", "40").to_i; cap_s = env("WARMUP_CAP_S", "120").to_f
    meta[:warmup_stable] = true
    loop do
      reset&.call
      a = Process.clock_gettime(Process::CLOCK_PROCESS_CPUTIME_ID, :nanosecond); fn.call
      w << Process.clock_gettime(Process::CLOCK_PROCESS_CPUTIME_ID, :nanosecond) - a
      if w.size >= [3, A[:warmup]].max
        l = w.last(3).sort; break if l[2] - l[0] <= 0.05 * l[1]
      end
      if w.size >= cap || Process.clock_gettime(Process::CLOCK_MONOTONIC) - t0 > cap_s
        meta[:warmup_stable] = false; break
      end
    end
    A[:warmup] = w.size; start = w.size; meta[:warmup_adaptive] = true
  end
  (start...(A[:warmup] + A[:iters])).each do |i|
    reset&.call
    (fn.call; next) if i < A[:warmup]
    m = Meter.new; m.begin_; ck = fn.call; r = m.end_(ck)
    r.merge!(post.call) if post
    iters << r
  end
  iters
end
