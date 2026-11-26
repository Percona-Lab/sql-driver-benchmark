# Ruby framework runner (Phase 3): ActiveRecord and Sequel, both on the mysql2 gem (compare against rb-mysql2).
# default config: the framework's usual model idiom; tuned: the framework's own lighter API (no model objects / bulk insert),
# exactly as listed in reports/tuned.json.
require_relative "harness"

def conn_opts(tls, sock)
  o = { username: env("DB_USER", "bench"), password: env("DB_PASS", "bench"), database: env("DB_NAME", "bench") }
  sock ? o[:socket] = env("DB_SOCKET") : o.merge!(host: env("DB_HOST", "127.0.0.1"), port: env("DB_PORT", "3306").to_i)
  o[:ssl_mode] = { "off" => :disabled, "on" => :required, "verify" => :verify_identity }[tls]
  o[:sslca] = env("DB_CA") if tls == "verify"
  o
end
def row_b(i) = (i % 10 == 0 ? "o'k-" : "name-") + i.to_s
def bulk_rows(st) = (st...st + 1000).map { |i| { id: i, a: i * 3, b: row_b(i), c: i * 0.5 } }

# ------------------------------------------------------------------ ActiveRecord
class ArFw
  def initialize
    require "mysql2"; require "active_record"
    ActiveRecord.default_timezone = :utc
  end
  def name = "rb-activerecord"
  def lib = "ActiveRecord #{ActiveRecord::VERSION::STRING} on mysql2 #{Mysql2::VERSION} (ruby #{RUBY_VERSION})"
  def open(tls, sock = false)
    ActiveRecord::Base.establish_connection(adapter: "mysql2", pool: 1, **conn_opts(tls, sock))
    unless defined?(::TInt)
      Object.const_set(:TInt, Class.new(ActiveRecord::Base) { self.table_name = "t_int" })
      Object.const_set(:TBlob, Class.new(ActiveRecord::Base) { self.table_name = "t_blob"; attribute :doc, :string })   # JSON column read as text, as in the other stacks
      Object.const_set(:TBulk, Class.new(ActiveRecord::Base) { self.table_name = "t_bulk" })
      Object.const_set(:WideInt, Class.new(ActiveRecord::Base) { self.table_name = "t_wide_int" })
      Object.const_set(:WideMix, Class.new(ActiveRecord::Base) { self.table_name = "t_wide_mix" })
    end
    [TInt, TBlob, TBulk, WideInt, WideMix].each(&:load_schema)   # schema reflection is setup, not measured
  end
  def pool = ActiveRecord::Base.connection_pool
  def raw(sql) = ActiveRecord::Base.lease_connection.select_rows(sql)
  def cipher = (r = raw("SHOW SESSION STATUS LIKE 'Ssl_cipher'").first; r && !r[1].to_s.empty? ? r[1] : "none")
  def close = ActiveRecord::Base.connection_handler.clear_all_connections!
  def t1(n) = n.times { pool.with_connection(&:verify!); pool.disconnect! }   # pool checkout of a new connection (connect + session setup)
  # Point select: find (cached statement) in both configs. Measured alternatives were slower: where(id:).pick(:v) 21.7 us,
  # select(:v).find 24.1 us, prepared_statements: true 14.6 us, vs find 15.0 us (MariaDB, warm).
  def t2(ids) = (s = 0; ids.each { |id| s += TInt.find(id).v }; s)
  def t3(streamed)   # ActiveRecord has no row streaming; the streamed variant is its batched API (find_each / in_batches, keyset pages of 1,000)
    s = 0
    if TUNED
      streamed ? TInt.in_batches(of: 1000) { |b| b.pluck(:v).each { |v| s += v } } : TInt.pluck(:v).each { |v| s += v }
    else
      streamed ? TInt.find_each(batch_size: 1000) { |o| s += o.v } : TInt.all.each { |o| s += o.v }
    end
    s
  end
  def t4(wide)
    k = wide == "int" ? WideInt : WideMix; cols = k.column_names
    return k.pluck(*cols) if TUNED
    ms = cols.map(&:to_sym); k.all.map { |o| ms.map { |m| o.public_send(m) } }
  end
  def t5(cls, col)
    q = TBlob.where(size_class: cls).order(:id)
    TUNED ? q.pluck(col) : q.map { |o| o.public_send(col) }
  end
  def t6
    1.step(1_000_000, 1000) do |st|
      recs = bulk_rows(st)
      if TUNED then TBulk.insert_all(recs)   # one multi-row INSERT, no model objects
      else TBulk.transaction { recs.each { |r| TBulk.create!(r) } }   # model objects, one INSERT each, one transaction per 1,000
      end
    end
  end
end

# ------------------------------------------------------------------ Sequel
class SequelFw
  def initialize = (require "mysql2"; require "sequel")
  def name = "rb-sequel"
  def lib = "Sequel #{Sequel.version} on mysql2 #{Mysql2::VERSION} (ruby #{RUBY_VERSION})"
  def open(tls, sock = false)
    @db = Sequel.connect(adapter: "mysql2", max_connections: 1, **conn_opts(tls, sock))
    @db.timezone = :utc
    m = ->(t) { Class.new(Sequel::Model(@db[t])) }
    @m = { int: m.(:t_int), blob: m.(:t_blob), bulk: m.(:t_bulk), wint: m.(:t_wide_int), wmix: m.(:t_wide_mix) }
    @m[:bulk].unrestrict_primary_key
  end
  def raw(sql) = @db.fetch(sql).map { |h| h.values }
  def cipher = (r = raw("SHOW SESSION STATUS LIKE 'Ssl_cipher'").first; r && !r[1].to_s.empty? ? r[1] : "none")
  def close = @db.disconnect
  def t1(n) = n.times { @db.synchronize { |_c| }; @db.disconnect }   # pool creates a new connection (connect + session setup)
  # Point select: Model[pk] (cached primary-key lookup) in both configs. Measured alternatives were slower: prepared
  # statement 12.1 us, where(id:).get(:v) 15.1 us, with_pk 15.8 us, bound-variable call 60.3 us, vs Model[pk] 11.0 us.
  def t2(ids) = (s = 0; k = @m[:int]; ids.each { |id| s += k[id].v }; s)
  def t3(streamed)
    s = 0
    if TUNED
      streamed ? @db[:t_int].select(:v).stream.each { |h| s += h[:v] } : @db[:t_int].select_map(:v).each { |v| s += v }
    else
      ds = @m[:int].dataset; (streamed ? ds.stream : ds).each { |o| s += o.v }
    end
    s
  end
  def t4(wide)
    k = @m[wide == "int" ? :wint : :wmix]; cols = k.columns
    return @db[k.table_name].select_map(cols) if TUNED
    k.all.map { |o| cols.map { |c| o.public_send(c) } }
  end
  def t5(cls, col)
    TUNED ? @db[:t_blob].where(size_class: cls).order(:id).select_map(col.to_sym) : @m[:blob].where(size_class: cls).order(:id).all.map { |o| o[col.to_sym] }
  end
  def t6
    k = @m[:bulk]
    1.step(1_000_000, 1000) do |st|
      recs = bulk_rows(st)
      if TUNED then @db[:t_bulk].multi_insert(recs)   # one multi-row INSERT, no model objects
      else @db.transaction { recs.each { |r| k.create(r) } }   # model objects, one INSERT each, one transaction per 1,000
      end
    end
  end
end

# ------------------------------------------------------------------ tests (touch rules identical to runner.rb)
def touch(v) = (c = v.bytesize; 0.step(v.bytesize - 1, 64) { |i| c += v.getbyte(i) }; c)
def touch_rows(rows)
  nn = isum = slen = 0
  rows.each do |a|
    1.upto(a.size - 1) do |i|
      v = a[i]; next if v.nil?
      nn += 1
      case v when Integer then isum += v when String then slen += v.size end   # DECIMAL->BigDecimal, DATE->Date, DATETIME->Time
    end
  end
  [nn + isum + slen, rows.size]
end

D = { "activerecord" => ArFw, "sequel" => SequelFw }.fetch(A[:fw]).new
def main
  meta = { stack: D.name, lib: D.lib, test: A[:test], variant: V, config: A[:config], server: A[:server] }
  write = ->(iters) { s = JSON.generate(meta.merge(iters: iters)); A[:out] ? File.write(A[:out], s) : puts(s) }
  tls = env("DB_TLS", "off")
  if A[:test] == "T0"
    perf_open; m = Meter.new; m.begin_; D.open(tls); D.raw("SELECT 1"); r = m.end_(1)
    meta.merge!(tls: D.cipher, ops_per_iter: 1, warmup: 0, rss_start_kb: RSS_START); write.([r]); return
  end
  raise NA, "frameworks are measured on tcp, socket, tls and tls-verify" if A[:test] == "T1" && (V.include?("resume") || V.include?("@"))
  raise NA, "frameworks bind parameters themselves (variant: param)" if A[:test] == "T2" && V != "param"
  raise NA, "the frameworks use mysql2 text protocol queries" if (A[:test] == "T3" && V.start_with?("binary")) || (A[:test] == "T4" && V.end_with?("binary"))
  raise NA, "ORM inserts use the batch variant" if A[:test] == "T6" && V != "batch"
  t1tls = V.start_with?("tls-verify") ? "verify" : V.start_with?("tls") ? "on" : "off"
  D.open(A[:test] == "T1" ? t1tls : tls, A[:test] == "T1" && V == "socket")
  meta[:tls] = D.cipher
  ids = A[:test] == "T2" ? File.readlines(File.join(env("DATA_DIR", "/root/bench/data"), "ids_200k.txt")).map(&:to_i) : nil
  ops = 0
  fn = case A[:test]
       when "T1" then -> { n = t1tls == "off" ? 3000 : 2000; D.t1(n); ops = n; n }
       when "T2" then -> { ops = ids.size; D.t2(ids) }
       when "T3" then -> { ops = 1_000_000; D.t3(V.include?("streamed")) }
       when "T4" then -> { ck, n = touch_rows(D.t4(V.start_with?("int") ? "int" : "mix")); ops = n * 100; ck }
       when "T5"
         cls, col = V.split("-", 2); parse = col.end_with?("-parse"); col = col.delete_suffix("-parse")
         -> { ck = b = 0; 20.times { ck = 0; D.t5(cls, col).each { |v| ck += touch(v); b += v.bytesize; JSON.parse(v) if parse } }; ops = b / 1024; ck }
       when "T6" then -> { D.t6; ops = 1000; "" }
       end
  meta[:rss_baseline_kb] = status_kb("VmRSS:")   # after load + connect + schema reflection, before warm-up
  t6 = A[:test] == "T6"
  iters = iterate(meta, fn, reset: t6 ? -> { D.raw("TRUNCATE TABLE t_bulk") } : nil,
                  post: t6 ? -> { { checksum: D.raw("SELECT COUNT(*), SUM(a), SUM(CHAR_LENGTH(b)) FROM t_bulk").first.map { |v| v.to_i.to_s }.join(":") } } : nil)
  meta.merge!(ops_per_iter: ops, warmup: A[:warmup]); write.(iters)
end
begin
  main
rescue NA => e
  warn "n/a: #{e.message}"; exit 3
end
