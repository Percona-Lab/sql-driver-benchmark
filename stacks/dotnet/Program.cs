// .NET runner: MySqlConnector and MySql.Data (Oracle) through ADO.NET (DbConnection/DbCommand/DbDataReader).
// Same CLI/env contract as the other runners (SPEC.md section 5). Pooling is off everywhere (T1 must open real connections).
using System.Data;
using System.Data.Common;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;

static class P
{
    static string test = "T0", variant = "", config = "default", server = "ps", driver = "mysqlconnector";
    static string? outPath;
    static int warmup = 2, iters = 5;
    static bool floor;
    static long ops;
    class NA : Exception { public NA(string m) : base(m) { } }
    static string Env(string k, string d = "") { var v = Environment.GetEnvironmentVariable(k); return string.IsNullOrEmpty(v) ? d : v; }

    // ------------------------------------------------------------ harness
    [StructLayout(LayoutKind.Sequential)] struct Timespec { public long sec, nsec; }
    [DllImport("libc")] static extern int clock_gettime(int clk, out Timespec ts);
    static long CpuNs() { clock_gettime(2 /* CLOCK_PROCESS_CPUTIME_ID */, out var t); return t.sec * 1_000_000_000 + t.nsec; }
    static long StatusKb(string key)
    {
        foreach (var l in File.ReadLines("/proc/self/status")) if (l.StartsWith(key)) return long.Parse(l.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries)[1]);
        return -1;
    }
    static long SrvTicks()
    {
        var pid = Env("MYSQLD_PID"); if (pid == "") return -1;
        try { var s = File.ReadAllText($"/proc/{pid}/stat"); var f = s[(s.LastIndexOf(')') + 2)..].Split(' '); return long.Parse(f[11]) + long.Parse(f[12]); }
        catch { return -1; }
    }
    static FileStream? ctl, ack;
    static void PerfOpen() { var c = Env("PERF_CTL"); var a = Env("PERF_ACK"); if (c != "" && a != "") { ctl = new FileStream(c, FileMode.Open, FileAccess.Write); ack = new FileStream(a, FileMode.Open, FileAccess.Read); } }
    static void Perf(string cmd) { if (ctl == null) return; var b = Encoding.ASCII.GetBytes(cmd); ctl.Write(b); ctl.Flush(); ack!.Read(new byte[8]); }
    static long cpu0, wall0, srv0, alloc0, rss0; static int gc0;
    static void Begin()
    {
        File.WriteAllText("/proc/self/clear_refs", "5");   // resets VmHWM to the current RSS
        rss0 = StatusKb("VmRSS:");
        gc0 = GC.CollectionCount(0) + GC.CollectionCount(1) + GC.CollectionCount(2); alloc0 = GC.GetTotalAllocatedBytes(); srv0 = SrvTicks();
        Perf("enable\n"); wall0 = Stopwatch.GetTimestamp(); cpu0 = CpuNs();
    }
    static Dictionary<string, object> End(object ck)
    {
        long cpu = CpuNs(), wall = Stopwatch.GetTimestamp(); Perf("disable\n"); long s = SrvTicks();
        return new() {
            ["cpu_ns"] = cpu - cpu0, ["wall_ns"] = (long)((wall - wall0) * (1e9 / Stopwatch.Frequency)), ["srv_ticks"] = s >= 0 && srv0 >= 0 ? s - srv0 : -1,
            ["rss_start_kb"] = rss0, ["rss_peak_kb"] = StatusKb("VmHWM:"), ["rss_end_kb"] = StatusKb("VmRSS:"), ["checksum"] = ck.ToString()!,
            ["gc_count"] = GC.CollectionCount(0) + GC.CollectionCount(1) + GC.CollectionCount(2) - gc0, ["alloc_bytes"] = GC.GetTotalAllocatedBytes() - alloc0 };
    }

    // ------------------------------------------------------------ provider
    static bool connector => driver == "mysqlconnector";
    static DbProviderFactory Factory => connector ? MySqlConnector.MySqlConnectorFactory.Instance : MySql.Data.MySqlClient.MySqlClientFactory.Instance;
    static string Lib => connector
        ? $"MySqlConnector {typeof(MySqlConnector.MySqlConnection).Assembly.GetName().Version} (.NET {Environment.Version})"
        : $"MySql.Data {typeof(MySql.Data.MySqlClient.MySqlConnection).Assembly.GetName().Version} (.NET {Environment.Version})";
    static bool ServerPrep => variant == "prepared" || variant.StartsWith("binary") || variant.EndsWith("binary");

    static DbConnection Connect(string tls = "off", bool sock = false)
    {
        if (!connector && tls == "verify")
            throw new NA("MySql.Data cannot verify the server against a CA file alone (SslCa requires SslCert/SslKey too)");
        var cs = new StringBuilder();
        cs.Append(sock ? $"Server={Env("DB_SOCKET")};Protocol=Unix;" : $"Server={Env("DB_HOST", "127.0.0.1")};Port={Env("DB_PORT", "3306")};");
        cs.Append($"User ID={Env("DB_USER", "bench")};Password={Env("DB_PASS", "bench")};Database={Env("DB_NAME", "bench")};Pooling=false;");
        cs.Append(tls switch { "off" => connector ? "SslMode=None;" : "SslMode=Disabled;", "on" => "SslMode=Required;", _ => $"SslMode=VerifyFull;SslCa={Env("DB_CA")};" });
        var c = Factory.CreateConnection()!; c.ConnectionString = cs.ToString(); c.Open(); return c;
    }
    static DbCommand Cmd(DbConnection c, string sql) { var cmd = c.CreateCommand(); cmd.CommandText = sql; return cmd; }
    static string Cipher(DbConnection c)
    {
        using var r = Cmd(c, "SHOW SESSION STATUS LIKE 'Ssl_cipher'").ExecuteReader();
        return r.Read() && !r.IsDBNull(1) && r.GetString(1) != "" ? r.GetString(1) : "none";
    }

    // ------------------------------------------------------------ tests
    static int[] ids = Array.Empty<int>();
    static string T1Mode => variant.StartsWith("tls-verify") ? "verify" : variant.StartsWith("tls") ? "on" : "off";
    static object T1(DbConnection _) { int n = T1Mode == "off" ? 10000 : 2000; for (int i = 0; i < n; i++) using (Connect(T1Mode, variant == "socket")) { } ops = n; return n; }

    static object T2(DbConnection c)
    {
        long s = 0;
        if (variant == "literal") { using var cmd = c.CreateCommand(); foreach (var id in ids) { cmd.CommandText = "SELECT v FROM t_int WHERE id = " + id; s += Convert.ToInt64(cmd.ExecuteScalar()); } }
        else
        {
            using var cmd = Cmd(c, "SELECT v FROM t_int WHERE id = @id");
            var p = cmd.CreateParameter(); p.ParameterName = "@id"; p.DbType = DbType.Int32; cmd.Parameters.Add(p);
            if (variant == "prepared") cmd.Prepare();
            foreach (var id in ids) { p.Value = id; s += Convert.ToInt64(cmd.ExecuteScalar()); }
        }
        ops = ids.Length; return s;
    }
    static DbDataReader Reader(DbConnection c, string sql, bool binary) { var cmd = Cmd(c, sql); if (binary) cmd.Prepare(); return cmd.ExecuteReader(); }
    static object T3(DbConnection c)
    {
        if (variant.EndsWith("buffered")) throw new NA("ADO.NET data readers always stream; no buffered result API");
        long s = 0; using (var r = Reader(c, "SELECT v FROM t_int", variant.StartsWith("binary"))) while (r.Read()) s += r.GetInt32(0);
        ops = 1_000_000; return s;
    }
    static object T4(DbConnection c)
    {
        long nn = 0, isum = 0, slen = 0; int rows = 0;
        using var r = Reader(c, variant.StartsWith("int") ? "SELECT * FROM t_wide_int" : "SELECT * FROM t_wide_mix", variant.EndsWith("binary"));
        int n = r.FieldCount; var kind = new int[n];
        for (int i = 0; i < n; i++)
        {
            var t = r.GetFieldType(i);
            kind[i] = t == typeof(int) || t == typeof(long) || t == typeof(sbyte) || t == typeof(short) || t == typeof(byte) ? 1
                    : t == typeof(string) ? 2 : t == typeof(decimal) ? 3 : t == typeof(double) || t == typeof(float) ? 4 : 5;
        }
        while (r.Read())
        {
            rows++;
            for (int i = 1; i < n; i++)
            {
                if (r.IsDBNull(i)) continue;
                nn++;
                switch (kind[i])
                {
                    case 1: isum += r.GetInt64(i); break;
                    case 2: slen += r.GetString(i).Length; break;
                    case 3: r.GetDecimal(i); break;
                    case 4: r.GetDouble(i); break;
                    default: r.GetDateTime(i); break;
                }
            }
        }
        ops = rows * 100L; return nn + isum + slen;
    }
    static (string sql, bool parse, bool bin) T5Sql()
    {
        var p = variant.Split('-', 2); var col = p[1]; bool parse = col.EndsWith("-parse"); if (parse) col = col[..^6];
        return ($"SELECT {col} FROM t_blob WHERE size_class = '{p[0]}' ORDER BY id", parse, col == "doc_bin");
    }
    static long Touch(string v) { long c = v.Length; for (int i = 0; i < v.Length; i += 64) c += v[i]; return c; }
    static long Touch(byte[] v) { long c = v.Length; for (int i = 0; i < v.Length; i += 64) c += v[i]; return c; }
    static object T5(DbConnection c)
    {
        var (sql, parse, bin) = T5Sql(); long ck = 0, bytes = 0;
        using var cmd = Cmd(c, sql);
        for (int rep = 0; rep < 20; rep++)
        {
            ck = 0;
            using var r = cmd.ExecuteReader();
            while (r.Read())
            {
                if (bin) { var v = r.GetFieldValue<byte[]>(0); ck += Touch(v); bytes += v.Length; if (parse) JsonDocument.Parse(v).Dispose(); }
                else { var v = r.GetString(0); ck += Touch(v); bytes += v.Length; if (parse) JsonDocument.Parse(v).Dispose(); }
            }
        }
        ops = bytes / 1024; return ck;
    }
    static string RowB(int i) => (i % 10 == 0 ? "o'k-" : "name-") + i;
    static string Esc(string s) => connector ? MySqlConnector.MySqlHelper.EscapeString(s) : MySql.Data.MySqlClient.MySqlHelper.EscapeString(s);
    static object T6(DbConnection c)
    {
        if (variant == "sqltext")
        {
            var sb = new StringBuilder(64 * 1024); using var cmd = c.CreateCommand();
            for (int st = 1; st <= 1_000_000; st += 1000)
            {
                sb.Clear().Append("INSERT INTO t_bulk (id,a,b,c) VALUES ");
                for (int i = st; i < st + 1000; i++) { if (i > st) sb.Append(','); sb.Append('(').Append(i).Append(',').Append(i * 3).Append(",'").Append(Esc(RowB(i))).Append("',").Append((i * 0.5).ToString(System.Globalization.CultureInfo.InvariantCulture)).Append(')'); }
                cmd.CommandText = sb.ToString(); cmd.ExecuteNonQuery();
            }
        }
        else if (variant == "multiparam")
        {
            var sb = new StringBuilder("INSERT INTO t_bulk (id,a,b,c) VALUES ");
            for (int k = 0; k < 1000; k++) sb.Append(k > 0 ? "," : "").Append($"(@a{k},@b{k},@c{k},@d{k})");
            using var cmd = Cmd(c, sb.ToString()); var ps = new DbParameter[4000];
            for (int k = 0; k < 4000; k++) { ps[k] = cmd.CreateParameter(); ps[k].ParameterName = "@" + "abcd"[k % 4] + (k / 4); cmd.Parameters.Add(ps[k]); }
            for (int st = 1; st <= 1_000_000; st += 1000)
            {
                for (int k = 0; k < 1000; k++) { int i = st + k; ps[4 * k].Value = i; ps[4 * k + 1].Value = i * 3; ps[4 * k + 2].Value = RowB(i); ps[4 * k + 3].Value = i * 0.5; }
                cmd.ExecuteNonQuery();
            }
        }
        else
        {
            if (!c.CanCreateBatch) throw new NA("provider has no DbBatch support");
            for (int st = 1; st <= 1_000_000; st += 1000)
            {
                using var b = c.CreateBatch();
                for (int i = st; i < st + 1000; i++)
                {
                    var bc = b.CreateBatchCommand(); bc.CommandText = "INSERT INTO t_bulk (id,a,b,c) VALUES (@a,@b,@c,@d)";
                    foreach (var (n, v) in new (string, object)[] { ("@a", i), ("@b", i * 3), ("@c", RowB(i)), ("@d", i * 0.5) })
                    { var p = bc.CreateParameter(); p.ParameterName = n; p.Value = v; bc.Parameters.Add(p); }
                    b.BatchCommands.Add(bc);
                }
                b.ExecuteNonQuery();
            }
        }
        ops = 1000; return "";
    }
    static object? floorData;
    static object Floor(DbConnection c)
    {
        if (test == "T3")
        {
            floorData ??= Enumerable.Range(0, 1_000_000).Select(i => (int)((i + 1L) * 7919 % 1000003)).ToArray();
            long s = 0; foreach (var x in (int[])floorData) s += x; ops = 1_000_000; return s;
        }
        if (test == "T5")
        {
            var (sql, _, _) = T5Sql();
            if (floorData == null) { var l = new List<string>(); using var r = Cmd(c, sql).ExecuteReader(); while (r.Read()) l.Add(r.GetValue(0) is byte[] b ? Encoding.Latin1.GetString(b) : r.GetString(0)); floorData = l; }
            long ck = 0, bb = 0; for (int rep = 0; rep < 20; rep++) { ck = 0; foreach (var v in (List<string>)floorData) { ck += Touch(v); bb += v.Length; } }
            ops = bb / 1024; return ck;
        }
        throw new NA("floor defined for T3 and T5 in .NET");
    }

    // ------------------------------------------------------------ main
    static int Main(string[] a)
    {
        long rssStart = StatusKb("VmRSS:");
        for (int i = 0; i < a.Length; i++)
            switch (a[i])
            {
                case "--driver": driver = a[++i]; break; case "--test": test = a[++i]; break; case "--variant": variant = a[++i]; break;
                case "--config": config = a[++i]; break; case "--server": server = a[++i]; break; case "--out": outPath = a[++i]; break;
                case "--warmup": warmup = int.Parse(a[++i]); break; case "--iters": iters = int.Parse(a[++i]); break; case "--floor": floor = true; break;
            }
        try { Run(rssStart); return 0; }
        catch (NA e) { Console.Error.WriteLine("n/a: " + e.Message); return 3; }
        catch (Exception e) { var m = e.GetType().Name + ": " + e.Message.Split('\n')[0]; for (var x = e.InnerException; x != null; x = x.InnerException) m += " <- " + x.GetType().Name + ": " + x.Message.Split('\n')[0]; Console.Error.WriteLine(m); return 1; }
    }
    static void Run(long rssStart)
    {
        if (config != "default") throw new NA(".NET driver options are covered by the explicit variants (prepared, batch)");
        if (test == "T1" && variant.Contains("resume")) throw new NA(".NET drivers expose no TLS session resumption control");
        if (connector) MySqlConnector.Authentication.Ed25519.Ed25519AuthenticationPlugin.Install();
        var meta = new Dictionary<string, object> { ["stack"] = connector ? "dotnet-mysqlconnector" : "dotnet-mysql-data", ["lib"] = Lib,
            ["test"] = test, ["variant"] = variant, ["config"] = config, ["server"] = server };
        var recs = new List<Dictionary<string, object>>();
        void Write() { meta["iters"] = recs; var s = JsonSerializer.Serialize(meta); if (outPath != null) File.WriteAllText(outPath, s); else Console.WriteLine(s); }
        if (test == "T0")
        {
            PerfOpen(); Begin(); var c0 = Connect(Env("DB_TLS", "off")); Cmd(c0, "SELECT 1").ExecuteScalar(); recs.Add(End(1));
            meta["tls"] = Cipher(c0); meta["ops_per_iter"] = 1; meta["warmup"] = 0; meta["rss_start_kb"] = rssStart; Write(); return;
        }
        if (test == "T1") using (var c2 = Connect(T1Mode, variant == "socket")) meta["tls"] = Cipher(c2);
        using var c = Connect(Env("DB_TLS", "off"));
        if (test != "T1") meta["tls"] = Cipher(c);
        if (test == "T2") ids = File.ReadAllLines(Path.Combine(Env("DATA_DIR", "/root/bench/data"), "ids_200k.txt")).Select(int.Parse).ToArray();
        meta["rss_baseline_kb"] = StatusKb("VmRSS:");   // after load + connect + setup, before warm-up
        Func<DbConnection, object> fn = floor ? Floor : test switch { "T1" => T1, "T2" => T2, "T3" => T3, "T4" => T4, "T5" => T5, _ => T6 };
        PerfOpen();
        for (int i = 0; i < warmup + iters; i++)
        {
            if (test == "T6") Cmd(c, "TRUNCATE TABLE t_bulk").ExecuteNonQuery();
            if (i < warmup) { fn(c); continue; }
            Begin(); var ck = fn(c); var r = End(ck);
            if (test == "T6" && !floor)
            {
                using var rd = Cmd(c, "SELECT COUNT(*), SUM(a), SUM(CHAR_LENGTH(b)) FROM t_bulk").ExecuteReader(); rd.Read();
                r["checksum"] = $"{Convert.ToInt64(rd.GetValue(0))}:{Convert.ToInt64(rd.GetValue(1))}:{Convert.ToInt64(rd.GetValue(2))}";
            }
            recs.Add(r);
        }
        meta["ops_per_iter"] = ops; meta["warmup"] = warmup; Write();
    }
}
