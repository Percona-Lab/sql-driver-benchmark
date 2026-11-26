# Ruby runner: mysql2 (libmysqlclient) and trilogy (own protocol implementation).
# default config: hashes (the gems' default row format); tuned: arrays (as: :array) and, for mysql2, cache_rows off.
require_relative "harness"

# ------------------------------------------------------------------ adapters
class Mysql2Ad
  def initialize = require("mysql2")
  def name = "rb-mysql2"
  def lib = "mysql2 #{Mysql2::VERSION} / #{Mysql2::Client.info[:version]} (ruby #{RUBY_VERSION})"
  def connect(tls = "off", sock = false)
    o = { username: env("DB_USER", "bench"), password: env("DB_PASS", "bench"), database: env("DB_NAME", "bench") }
    sock ? o[:socket] = env("DB_SOCKET") : o.merge!(host: env("DB_HOST", "127.0.0.1"), port: env("DB_PORT", "3306").to_i)
    o[:ssl_mode] = { "off" => :disabled, "on" => :required, "verify" => :verify_identity }[tls]
    o[:sslca] = env("DB_CA") if tls == "verify"
    Mysql2::Client.new(**o)
  end
  def close(c) = c.close
  def opts(streamed = false) = TUNED ? { as: :array, cache_rows: false, stream: streamed } : { stream: streamed, cache_rows: !streamed }
  def query(c, sql, streamed: false) = c.query(sql, **opts(streamed))
  def lookup(c, variant, ids)
    s = 0
    case variant
    when "literal" then ids.each { |id| s += first(c.query("SELECT v FROM t_int WHERE id = #{id}", **opts)) }
    when "param" then raise NA, "mysql2 has no client-side parameter binding (only escape + string building)"
    else st = c.prepare("SELECT v FROM t_int WHERE id = ?"); ids.each { |id| s += first(st.execute(id, **opts)) }; st.close
    end
    s
  end
  def first(r) = (row = r.first; row.is_a?(Array) ? row[0] : row.values[0])
  def binary(c, sql, streamed) = (st = c.prepare(sql); [st.execute(**opts(streamed)), st])
  def escape(c, s) = "'#{c.escape(s)}'"
  def multiparam(c, sql) = (st = c.prepare(sql); yield(->(p) { st.execute(*p) }); st.close)
  def cipher(c) = (r = c.query("SHOW SESSION STATUS LIKE 'Ssl_cipher'", as: :array).first; r && !r[1].to_s.empty? ? r[1] : "none")
  def exec(c, sql) = c.query(sql)
end

class TrilogyAd
  def initialize = require("trilogy")
  def name = "rb-trilogy"
  def lib = "trilogy #{Trilogy::VERSION} (ruby #{RUBY_VERSION})"
  def connect(tls = "off", sock = false)
    o = { username: env("DB_USER", "bench"), password: env("DB_PASS", "bench"), database: env("DB_NAME", "bench") }
    sock ? o[:socket] = env("DB_SOCKET") : o.merge!(host: env("DB_HOST", "127.0.0.1"), port: env("DB_PORT", "3306").to_i)
    if tls == "on" then o.merge!(ssl: true, ssl_mode: Trilogy::SSL_REQUIRED_NOVERIFY)
    elsif tls == "verify"   # trilogy verifies host names only (not IP SANs): connect by name
      o.merge!(ssl: true, ssl_mode: Trilogy::SSL_VERIFY_IDENTITY, ssl_ca: env("DB_CA")); o[:host] = "localhost" unless sock
    end
    Trilogy.new(o)
  end
  def close(c) = c.close
  def query(c, sql, streamed: false)
    raise NA, "trilogy has no streaming result API" if streamed
    r = c.query(sql)
    TUNED ? r.rows : r.each_hash   # rows: arrays; each_hash: hashes (what Rails-style code iterates)
  end
  def lookup(c, variant, ids)
    raise NA, "trilogy has no parameter binding or prepared statements" unless variant == "literal"
    s = 0; ids.each { |id| s += c.query("SELECT v FROM t_int WHERE id = #{id}").rows[0][0] }; s
  end
  def binary(*) = raise(NA, "trilogy has no prepared statements / binary protocol")
  def escape(c, s) = "'#{c.escape(s)}'"
  def multiparam(*) = raise(NA, "trilogy has no parameter binding")
  def cipher(c) = (r = c.query("SHOW SESSION STATUS LIKE 'Ssl_cipher'").rows.first; r && !r[1].to_s.empty? ? r[1] : "none")
  def exec(c, sql) = c.query(sql)
end

D = A[:driver] == "trilogy" ? TrilogyAd.new : Mysql2Ad.new
$ops = 0

# ------------------------------------------------------------------ tests
def t1mode = V.start_with?("tls-verify") ? "verify" : V.start_with?("tls") ? "on" : "off"
def vals(row) = row.is_a?(Array) ? row : row.values
def t1(_c) = (n = t1mode == "off" ? 5000 : 2000; n.times { D.close(D.connect(t1mode, V == "socket")) }; $ops = n; n)
def t2(c) = ($ops = $ids.size; D.lookup(c, V, $ids))
def rows_for(c, sql, streamed, binary)
  return D.binary(c, sql, streamed)[0] if binary
  D.query(c, sql, streamed: streamed)
end
def t3(c)
  s = 0; rows_for(c, "SELECT v FROM t_int", V.include?("streamed"), V.start_with?("binary")).each { |r| s += vals(r)[0] }
  $ops = 1_000_000; s
end
def t4(c)
  nn = isum = slen = n = 0
  rows_for(c, V.start_with?("int") ? "SELECT * FROM t_wide_int" : "SELECT * FROM t_wide_mix", false, V.end_with?("binary")).each do |r|
    n += 1; a = vals(r)
    1.upto(a.size - 1) do |i|
      v = a[i]; next if v.nil?
      nn += 1
      case v when Integer then isum += v when String then slen += v.size end   # DECIMAL->BigDecimal, DATE->Date, DATETIME->Time
    end
  end
  $ops = n * 100; nn + isum + slen
end
def touch(v) = (c = v.bytesize; 0.step(v.bytesize - 1, 64) { |i| c += v.getbyte(i) }; c)
def t5sql
  cls, col = V.split("-", 2); parse = col.end_with?("-parse")
  ["SELECT #{col.delete_suffix('-parse')} FROM t_blob WHERE size_class = '#{cls}' ORDER BY id", parse]
end
def t5(c)
  sql, parse = t5sql; ck = bytes = 0
  20.times do
    ck = 0
    D.query(c, sql).each { |r| v = vals(r)[0]; ck += touch(v); bytes += v.bytesize; JSON.parse(v) if parse }
  end
  $ops = bytes / 1024; ck
end
def row_b(i) = (i % 10 == 0 ? "o'k-" : "name-") + i.to_s
def t6(c)
  case V
  when "sqltext"
    1.step(1_000_000, 1000) do |st|
      D.exec(c, "INSERT INTO t_bulk (id,a,b,c) VALUES " + (st...st + 1000).map { |i| "(#{i},#{i * 3},#{D.escape(c, row_b(i))},#{i * 0.5})" }.join(","))
    end
  when "multiparam"
    sql = "INSERT INTO t_bulk (id,a,b,c) VALUES " + (["(?,?,?,?)"] * 1000).join(",")
    D.multiparam(c, sql) { |ex| 1.step(1_000_000, 1000) { |st| ex.((st...st + 1000).flat_map { |i| [i, i * 3, row_b(i), i * 0.5] }) } }
  else raise NA, "no batch API in #{D.name}"
  end
  $ops = 1000; ""
end
def floor_(c)
  case A[:test]
  when "T3" then $floor ||= Array.new(1_000_000) { |i| [((i + 1) * 7919) % 1_000_003] }; s = 0; $floor.each { |r| s += r[0] }; $ops = 1_000_000; s
  when "T5"
    $floor ||= D.query(c, t5sql[0]).map { |r| vals(r)[0] }
    ck = b = 0; 20.times { ck = 0; $floor.each { |v| ck += touch(v); b += v.bytesize } }; $ops = b / 1024; ck
  else raise NA, "floor defined for T3 and T5 in Ruby"
  end
end

# ------------------------------------------------------------------ main
def main
  meta = { stack: D.name, lib: D.lib, test: A[:test], variant: V, config: A[:config], server: A[:server] }
  write = ->(iters) { s = JSON.generate(meta.merge(iters: iters)); A[:out] ? File.write(A[:out], s) : puts(s) }
  raise NA, "Ruby drivers expose no TLS session resumption control" if A[:test] == "T1" && V.include?("resume")
  if A[:test] == "T0"
    perf_open; m = Meter.new; m.begin_; c = D.connect(env("DB_TLS", "off")); D.exec(c, "SELECT 1")
    r = m.end_(1); meta.merge!(tls: D.cipher(c), ops_per_iter: 1, warmup: 0, rss_start_kb: RSS_START); write.([r]); return
  end
  if A[:test] == "T1" then c2 = D.connect(t1mode, V == "socket"); meta[:tls] = D.cipher(c2); D.close(c2) end
  c = D.connect(env("DB_TLS", "off"))
  meta[:tls] = D.cipher(c) unless A[:test] == "T1"
  $ids = File.readlines(File.join(env("DATA_DIR", "/root/bench/data"), "ids_200k.txt")).map(&:to_i) if A[:test] == "T2"
  meta[:rss_baseline_kb] = status_kb("VmRSS:")   # after load + connect + setup, before warm-up
  fn = A[:floor] ? method(:floor_) : method({ "T1" => :t1, "T2" => :t2, "T3" => :t3, "T4" => :t4, "T5" => :t5, "T6" => :t6 }[A[:test]])
  t6 = A[:test] == "T6"
  iters = iterate(meta, -> { fn.(c) }, reset: t6 ? -> { D.exec(c, "TRUNCATE TABLE t_bulk") } : nil,
                  post: t6 && !A[:floor] ? -> { { checksum: vals(D.query(c, "SELECT COUNT(*), SUM(a), SUM(CHAR_LENGTH(b)) FROM t_bulk").first).map { |v| v.to_i.to_s }.join(":") } } : nil)
  meta.merge!(ops_per_iter: $ops, warmup: A[:warmup]); write.(iters)
end
begin
  main
rescue NA => e
  warn "n/a: #{e.message}"; exit 3
end
