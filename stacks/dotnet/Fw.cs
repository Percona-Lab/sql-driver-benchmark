// Phase 3: .NET frameworks on MySqlConnector (the driver measured as dotnet-mysqlconnector).
//   dapper  Dapper micro-ORM over MySqlConnection
//   efcore  EF Core 9 with Pomelo.EntityFrameworkCore.MySql (MySqlConnector underneath)
// default = the idiom most code uses; tuned = framework performance options (no-tracking, compiled queries, streaming).
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;
using System.Data.Common;
using Dapper;
using Microsoft.EntityFrameworkCore;

[Table("t_int")] public class TInt { [Key, DatabaseGenerated(DatabaseGeneratedOption.None)] public int id { get; set; } public int v { get; set; } }
[Table("t_blob")] public class TBlob
{
    [Key, DatabaseGenerated(DatabaseGeneratedOption.None)] public int id { get; set; }
    public string size_class { get; set; } = ""; public string doc { get; set; } = ""; public byte[] doc_bin { get; set; } = [];
}
[Table("t_bulk")] public class TBulk
{
    [Key, DatabaseGenerated(DatabaseGeneratedOption.None)] public int id { get; set; }
    public int a { get; set; } public string b { get; set; } = ""; public double c { get; set; }
}

public class BenchCtx : DbContext
{
    readonly string cs; readonly bool maria, tuned;
    public BenchCtx(string cs, bool maria, bool tuned) { this.cs = cs; this.maria = maria; this.tuned = tuned; }
    public DbSet<TInt> TInts => Set<TInt>();
    public DbSet<WideInt> WideInts => Set<WideInt>();
    public DbSet<WideMix> WideMixes => Set<WideMix>();
    public DbSet<TBlob> TBlobs => Set<TBlob>();
    public DbSet<TBulk> TBulks => Set<TBulk>();
    protected override void OnConfiguring(DbContextOptionsBuilder o) =>
        o.UseMySql(cs, maria ? ServerVersion.Parse("12.3.4-mariadb") : ServerVersion.Parse("9.7.2-mysql"),   // fixed version: no detection round trip
            m => { if (tuned) m.MaxBatchSize(1000); });
}

static partial class P
{
    static readonly Func<BenchCtx, int, int> compiledV = EF.CompileQuery((BenchCtx c, int id) => c.TInts.AsNoTracking().Where(t => t.id == id).Select(t => t.v).Single());

    static long[] TouchRow(object?[] vals, long[] acc)
    {
        foreach (var v in vals)
        {
            if (v == null) continue;
            acc[0]++;
            switch (v) { case int i: acc[1] += i; break; case long l: acc[1] += l; break; case sbyte b: acc[1] += b; break; case string s: acc[2] += s.Length; break; }
        }
        return acc;
    }
    static long TouchDoc(object v)
    {
        if (v is string s) { long c = s.Length; for (int i = 0; i < s.Length; i += 64) c += s[i]; return c; }
        var b = (byte[])v; long d = b.Length; for (int i = 0; i < b.Length; i += 64) d += b[i]; return d;
    }

    public static int RunFw(string fw, long rssStart)
    {
        driver = "mysqlconnector";
        bool tuned = config == "tuned", maria = server == "maria";
        string name = fw == "dapper" ? "dotnet-dapper" : "dotnet-efcore";
        string libv = fw == "dapper"
            ? $"Dapper {typeof(SqlMapper).Assembly.GetName().Version} on {Lib}"
            : $"EF Core {typeof(DbContext).Assembly.GetName().Version} + Pomelo {typeof(MySqlDbContextOptionsBuilderExtensions).Assembly.GetName().Version} on {Lib}";
        try
        {
            if (test == "T1") throw new NA("frameworks use the driver's connections (see dotnet-mysqlconnector)");
            if (test == "T2" && variant != "param") throw new NA("frameworks bind parameters themselves (variant: param)");
            if ((test == "T3" || test == "T4") && variant.Contains("binary")) throw new NA("measured on the text protocol");
            if (test == "T6" && variant != "batch") throw new NA("frameworks insert through their own API (the batch variant)");
            var meta = new Dictionary<string, object> { ["stack"] = name, ["lib"] = libv, ["test"] = test, ["variant"] = variant, ["config"] = config, ["server"] = server };
            var recs = new List<Dictionary<string, object>>();
            void Write() { meta["iters"] = recs; var s = System.Text.Json.JsonSerializer.Serialize(meta); if (outPath != null) File.WriteAllText(outPath, s); else Console.WriteLine(s); }

            // connection: Dapper uses it directly; EF Core gets the connection string (pooling off, same TLS settings)
            using var conn = Connect(Env("DB_TLS", "off"));
            string cs = conn.ConnectionString + ";Password=" + Env("DB_PASS", "bench");
            BenchCtx NewCtx() => new BenchCtx(cs, maria, tuned);
            using var ctx = NewCtx();
            if (fw == "efcore") ctx.Database.OpenConnection();   // keep one connection for the context's lifetime
            if (test == "T0")
            {
                PerfOpen(); Begin();
                if (fw == "dapper") conn.ExecuteScalar("SELECT 1"); else ctx.Database.ExecuteSqlRaw("SELECT 1");
                recs.Add(End(1)); meta["tls"] = Cipher(conn); meta["ops_per_iter"] = 1; meta["warmup"] = 0; meta["rss_start_kb"] = rssStart; Write(); return 0;
            }
            meta["tls"] = Cipher(conn);
            if (test == "T2") ids = File.ReadAllLines(Path.Combine(Env("DATA_DIR", "/root/bench/data"), "ids_200k.txt")).Select(int.Parse).ToArray();
            long ops = 0;
            string[] t5 = test == "T5" ? variant.Split('-', 2) : [];
            Func<string> step = test switch
            {
                "T2" => () =>
                {
                    long s = 0;
                    if (fw == "dapper") foreach (var id in ids) s += conn.QuerySingle<int>("SELECT v FROM t_int WHERE id = @id", new { id });
                    else if (tuned) foreach (var id in ids) s += compiledV(ctx, id);
                    else foreach (var id in ids) { s += ctx.TInts.Single(t => t.id == id).v; ctx.ChangeTracker.Clear(); }
                    ops = ids.Length; return s.ToString();
                },
                "T3" => () =>
                {
                    long s = 0; bool streamed = variant.Contains("streamed");
                    if (fw == "dapper") foreach (var v in conn.Query<int>("SELECT v FROM t_int", buffered: !(streamed || tuned))) s += v;
                    else
                    {
                        IQueryable<TInt> q = tuned ? ctx.TInts.AsNoTracking() : ctx.TInts;
                        if (streamed) foreach (var e in q.AsEnumerable()) s += e.v; else foreach (var e in q.ToList()) s += e.v;
                        ctx.ChangeTracker.Clear();
                    }
                    ops = 1_000_000; return s.ToString();
                },
                "T4" => () =>
                {
                    var acc = new long[3]; long rows = 0; bool intT = variant.StartsWith("int");
                    if (fw == "dapper")
                    {
                        if (intT) foreach (var r in conn.Query<WideInt>("SELECT * FROM t_wide_int", buffered: !tuned)) { rows++; TouchRow(r.Values(), acc); }
                        else foreach (var r in conn.Query<WideMix>("SELECT * FROM t_wide_mix", buffered: !tuned)) { rows++; TouchRow(r.Values(), acc); }
                    }
                    else
                    {
                        if (intT) foreach (var r in (tuned ? ctx.WideInts.AsNoTracking() : ctx.WideInts).ToList()) { rows++; TouchRow(r.Values(), acc); }
                        else foreach (var r in (tuned ? ctx.WideMixes.AsNoTracking() : ctx.WideMixes).ToList()) { rows++; TouchRow(r.Values(), acc); }
                        ctx.ChangeTracker.Clear();
                    }
                    ops = rows * 100; return (acc[0] + acc[1] + acc[2]).ToString();
                },
                "T5" => () =>
                {
                    if (t5[1].EndsWith("-parse")) throw new NA("parse variant measured in the driver runner");
                    long ck = 0, bytes = 0; bool bin = t5[1] == "doc_bin";
                    for (int rep = 0; rep < 20; rep++)
                    {
                        List<object> vals;
                        if (fw == "dapper")
                            vals = bin ? conn.Query<byte[]>("SELECT doc_bin FROM t_blob WHERE size_class = @c ORDER BY id", new { c = t5[0] }).Cast<object>().ToList()
                                       : conn.Query<string>("SELECT doc FROM t_blob WHERE size_class = @c ORDER BY id", new { c = t5[0] }).Cast<object>().ToList();
                        else
                        {
                            var q = ctx.TBlobs.AsNoTracking().Where(b => b.size_class == t5[0]).OrderBy(b => b.id);
                            vals = bin ? q.Select(b => b.doc_bin).ToList().Cast<object>().ToList() : q.Select(b => b.doc).ToList().Cast<object>().ToList();
                        }
                        ck = 0; foreach (var v in vals) { ck += TouchDoc(v); bytes += v is string s ? s.Length : ((byte[])v).Length; }
                    }
                    ops = bytes / 1024; return ck.ToString();
                },
                _ => () =>
                {
                    for (int st = 1; st <= 1_000_000; st += 1000)
                    {
                        var rows = Enumerable.Range(st, 1000).Select(i => new TBulk { id = i, a = i * 3, b = RowB(i), c = i * 0.5 }).ToList();
                        if (fw == "dapper")
                        {
                            using var tx = tuned ? conn.BeginTransaction() : null;   // tuned: one transaction per 1,000 rows
                            conn.Execute("INSERT INTO t_bulk (id,a,b,c) VALUES (@id,@a,@b,@c)", rows, tx);
                            tx?.Commit();
                        }
                        else
                        {
                            if (tuned) ctx.ChangeTracker.AutoDetectChangesEnabled = false;
                            ctx.TBulks.AddRange(rows); ctx.SaveChanges(); ctx.ChangeTracker.Clear();
                        }
                    }
                    ops = 1000; return "";
                },
            };
            meta["rss_baseline_kb"] = StatusKb("VmRSS:");
            PerfOpen();
            int start = 0;
            if (Env("ADAPTIVE_WARMUP") != "")
            {
                var w = new List<long>(); var t0 = System.Diagnostics.Stopwatch.GetTimestamp();
                int cap = int.Parse(Env("WARMUP_CAP", "40")); double capS = double.Parse(Env("WARMUP_CAP_S", "120")); meta["warmup_stable"] = true;
                while (true)
                {
                    if (test == "T6") Cmd(conn, "TRUNCATE TABLE t_bulk").ExecuteNonQuery();
                    long a = CpuNs(); step(); w.Add(CpuNs() - a);
                    if (w.Count >= Math.Max(3, warmup)) { var l = w.Skip(w.Count - 3).OrderBy(x => x).ToArray(); if (l[2] - l[0] <= 0.05 * l[1]) break; }
                    if (w.Count >= cap || System.Diagnostics.Stopwatch.GetElapsedTime(t0).TotalSeconds > capS) { meta["warmup_stable"] = false; break; }
                }
                warmup = w.Count; start = w.Count; meta["warmup_adaptive"] = true;
            }
            for (int i = start; i < warmup + iters; i++)
            {
                if (test == "T6") Cmd(conn, "TRUNCATE TABLE t_bulk").ExecuteNonQuery();
                if (i < warmup) { step(); continue; }
                Begin(); var ck = step(); var r = End(ck);
                if (test == "T6")
                {
                    using var rd = Cmd(conn, "SELECT COUNT(*), SUM(a), SUM(CHAR_LENGTH(b)) FROM t_bulk").ExecuteReader(); rd.Read();
                    r["checksum"] = $"{Convert.ToInt64(rd.GetValue(0))}:{Convert.ToInt64(rd.GetValue(1))}:{Convert.ToInt64(rd.GetValue(2))}";
                }
                recs.Add(r);
            }
            meta["ops_per_iter"] = ops; meta["warmup"] = warmup; Write();
            return 0;
        }
        catch (NA e) { Console.Error.WriteLine("n/a: " + e.Message); return 3; }
    }
}
