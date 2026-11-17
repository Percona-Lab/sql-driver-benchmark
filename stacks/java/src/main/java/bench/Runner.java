package bench;

// Java runner: MySQL Connector/J and MariaDB Connector/J through plain JDBC.
// Same CLI/env contract as the other runners (SPEC.md section 5).

import java.io.*;
import java.lang.management.*;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.sql.*;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.*;

public class Runner {
    static String test = "T0", variant = "", config = "default", server = "ps", out = null, driverName = "connector-j";
    static int warmup = 2, iters = 5;
    static boolean floor = false;
    static long ops;
    static boolean mariadb;

    static class NA extends RuntimeException { NA(String m) { super(m); } }

    static String env(String k, String d) { String v = System.getenv(k); return v == null || v.isEmpty() ? d : v; }

    // ------------------------------------------------------------ harness
    static final com.sun.management.OperatingSystemMXBean OS =
        (com.sun.management.OperatingSystemMXBean) ManagementFactory.getOperatingSystemMXBean();
    static final com.sun.management.ThreadMXBean TM = (com.sun.management.ThreadMXBean) ManagementFactory.getThreadMXBean();
    static FileOutputStream perfCtl; static FileInputStream perfAck;

    static void perfOpen() throws IOException {
        String c = System.getenv("PERF_CTL"), a = System.getenv("PERF_ACK");
        if (c != null && a != null) { perfCtl = new FileOutputStream(c); perfAck = new FileInputStream(a); }
    }
    static void perf(String cmd) throws IOException {
        if (perfCtl == null) return;
        perfCtl.write(cmd.getBytes()); perfCtl.flush(); perfAck.read(new byte[8]);
    }
    static long statusKb(String key) throws IOException {
        for (String l : Files.readAllLines(Path.of("/proc/self/status")))
            if (l.startsWith(key)) return Long.parseLong(l.split("\\s+")[1]);
        return -1;
    }
    static long srvTicks() {
        String pid = System.getenv("MYSQLD_PID");
        if (pid == null) return -1;
        try {
            String s = Files.readString(Path.of("/proc/" + pid + "/stat"));
            String[] f = s.substring(s.lastIndexOf(')') + 2).split(" ");
            return Long.parseLong(f[11]) + Long.parseLong(f[12]);
        } catch (IOException e) { return -1; }
    }
    static long[] gc() {
        long n = 0, t = 0;
        for (GarbageCollectorMXBean b : ManagementFactory.getGarbageCollectorMXBeans()) { n += b.getCollectionCount(); t += b.getCollectionTime(); }
        return new long[]{n, t};
    }
    static long cpu0, wall0, srv0, alloc0; static long[] gc0;
    static void begin() throws IOException {
        Files.writeString(Path.of("/proc/self/clear_refs"), "5");
        gc0 = gc(); alloc0 = TM.getCurrentThreadAllocatedBytes(); srv0 = srvTicks();
        perf("enable\n");
        wall0 = System.nanoTime(); cpu0 = OS.getProcessCpuTime();
    }
    static String end(Object ck) throws IOException {
        long cpu = OS.getProcessCpuTime(), wall = System.nanoTime();
        perf("disable\n");
        long s = srvTicks(); long[] g = gc();
        return String.format("{\"cpu_ns\":%d,\"wall_ns\":%d,\"srv_ticks\":%d,\"rss_peak_kb\":%d,\"rss_end_kb\":%d,"
                + "\"checksum\":\"%s\",\"alloc_bytes\":%d,\"gc_count\":%d,\"gc_ms\":%d}",
            cpu - cpu0, wall - wall0, s >= 0 && srv0 >= 0 ? s - srv0 : -1, statusKb("VmHWM:"), statusKb("VmRSS:"),
            ck, TM.getCurrentThreadAllocatedBytes() - alloc0, g[0] - gc0[0], g[1] - gc0[1]);
    }

    // ------------------------------------------------------------ connections
    static Driver drv;
    static String lib;

    /** tls: off | on (no verification) | verify. Variant-specific options come from the test variant. */
    static Connection connect(String tls, boolean sock) throws SQLException {
        Properties p = new Properties();
        p.setProperty("user", env("DB_USER", "bench")); p.setProperty("password", env("DB_PASS", "bench"));
        boolean serverPrep = variant.equals("prepared") || variant.startsWith("binary") || variant.endsWith("binary");
        if (!mariadb) {
            p.setProperty("sslMode", switch (tls) { case "off" -> "DISABLED"; case "on" -> "REQUIRED"; default -> "VERIFY_IDENTITY"; });
            if (tls.equals("verify")) {
                p.setProperty("trustCertificateKeyStoreUrl", "file:" + env("DB_CA", "").replace(".pem", ".p12"));
                p.setProperty("trustCertificateKeyStoreType", "PKCS12");
                p.setProperty("trustCertificateKeyStorePassword", "changeit");
            }
            if (serverPrep) p.setProperty("useServerPrepStmts", "true");
            if (config.equals("tuned")) {
                p.setProperty("useServerPrepStmts", "true"); p.setProperty("cachePrepStmts", "true");
                p.setProperty("prepStmtCacheSize", "250"); p.setProperty("rewriteBatchedStatements", "true");
                p.setProperty("cacheServerConfiguration", "true"); p.setProperty("useLocalSessionState", "true");
                p.setProperty("maintainTimeStats", "false");
            }
            if (sock) throw new NA("Connector/J has no Unix socket support without a third-party socket factory");
        } else {
            p.setProperty("sslMode", switch (tls) { case "off" -> "disable"; case "on" -> "trust"; default -> "verify-full"; });
            if (tls.equals("verify")) p.setProperty("serverSslCert", env("DB_CA", ""));
            if (serverPrep) p.setProperty("useServerPrepStmts", "true");
            if (config.equals("tuned")) {
                p.setProperty("useServerPrepStmts", "true"); p.setProperty("cachePrepStmts", "true");
                p.setProperty("prepStmtCacheSize", "250"); p.setProperty("useBulkStmts", "true");
            }
            if (sock) p.setProperty("localSocket", env("DB_SOCKET", ""));
        }
        String url = (mariadb ? "jdbc:mariadb://" : "jdbc:mysql://") + env("DB_HOST", "127.0.0.1") + ":" + env("DB_PORT", "3306")
            + "/" + env("DB_NAME", "bench");
        Connection c = drv.connect(url, p);
        c.setAutoCommit(true);
        return c;
    }

    static String cipher(Connection c) throws SQLException {
        try (Statement s = c.createStatement(); ResultSet r = s.executeQuery("SHOW SESSION STATUS LIKE 'Ssl_cipher'")) {
            return r.next() && r.getString(2) != null && !r.getString(2).isEmpty() ? r.getString(2) : "none";
        }
    }

    // ------------------------------------------------------------ tests
    static int[] ids;

    static String t1(Connection unused) throws SQLException {
        String tls = variant.startsWith("tls-verify") ? "verify" : variant.startsWith("tls") ? "on" : "off";
        int n = tls.equals("off") ? 10000 : 2000;
        boolean sock = variant.equals("socket");
        for (int i = 0; i < n; i++) connect(tls, sock).close();
        ops = n; return Integer.toString(n);
    }

    static String t2(Connection c) throws SQLException {
        long s = 0;
        if (variant.equals("literal")) {
            try (Statement st = c.createStatement()) {
                for (int id : ids) try (ResultSet r = st.executeQuery("SELECT v FROM t_int WHERE id = " + id)) { r.next(); s += r.getInt(1); }
            }
        } else { // param: PreparedStatement with driver defaults (client-side); prepared: useServerPrepStmts=true
            try (PreparedStatement ps = c.prepareStatement("SELECT v FROM t_int WHERE id = ?")) {
                for (int id : ids) { ps.setInt(1, id); try (ResultSet r = ps.executeQuery()) { r.next(); s += r.getInt(1); } }
            }
        }
        ops = ids.length; return Long.toString(s);
    }

    static Statement stmtFor(Connection c, boolean streamed, boolean binary, String sql) throws SQLException {
        Statement st = binary ? c.prepareStatement(sql, ResultSet.TYPE_FORWARD_ONLY, ResultSet.CONCUR_READ_ONLY)
                              : c.createStatement(ResultSet.TYPE_FORWARD_ONLY, ResultSet.CONCUR_READ_ONLY);
        if (streamed) st.setFetchSize(mariadb ? 1000 : Integer.MIN_VALUE); // Connector/J: MIN_VALUE = row streaming
        return st;
    }
    static ResultSet exec(Statement st, String sql) throws SQLException {
        return st instanceof PreparedStatement ps ? ps.executeQuery() : st.executeQuery(sql);
    }

    static String t3(Connection c) throws SQLException {
        String sql = "SELECT v FROM t_int"; long s = 0;
        try (Statement st = stmtFor(c, variant.contains("streamed"), variant.startsWith("binary"), sql); ResultSet r = exec(st, sql)) {
            while (r.next()) s += r.getInt(1);
        }
        ops = 1000000; return Long.toString(s);
    }

    static String t4(Connection c) throws SQLException {
        String sql = variant.startsWith("int") ? "SELECT * FROM t_wide_int" : "SELECT * FROM t_wide_mix";
        long nn = 0, isum = 0, slen = 0; int rows = 0;
        try (Statement st = stmtFor(c, false, variant.endsWith("binary"), sql); ResultSet r = exec(st, sql)) {
            ResultSetMetaData md = r.getMetaData(); int n = md.getColumnCount();
            int[] kind = new int[n + 1];
            for (int i = 1; i <= n; i++) {
                kind[i] = switch (md.getColumnType(i)) {
                    case Types.INTEGER, Types.BIGINT, Types.TINYINT, Types.SMALLINT -> 1;
                    case Types.VARCHAR, Types.CHAR -> 2;
                    case Types.DECIMAL, Types.NUMERIC -> 3;
                    case Types.DOUBLE, Types.FLOAT, Types.REAL -> 4;
                    case Types.DATE -> 5;
                    case Types.BIT, Types.BOOLEAN -> 1;
                    default -> 6; // TIMESTAMP / DATETIME
                };
            }
            while (r.next()) {
                rows++;
                for (int i = 2; i <= n; i++) {
                    switch (kind[i]) {
                        case 1 -> { long v = r.getLong(i); if (!r.wasNull()) { nn++; isum += v; } }
                        case 2 -> { String v = r.getString(i); if (v != null) { nn++; slen += v.length(); } }
                        case 3 -> { BigDecimal v = r.getBigDecimal(i); if (v != null) nn++; }
                        case 4 -> { r.getDouble(i); if (!r.wasNull()) nn++; }
                        case 5 -> { if (r.getObject(i, LocalDate.class) != null) nn++; }
                        default -> { if (r.getObject(i, LocalDateTime.class) != null) nn++; }
                    }
                }
            }
        }
        ops = rows * 100L; return Long.toString(nn + isum + slen);
    }

    static String[] t5parts() {
        String[] p = variant.split("-", 2);
        if (p[1].endsWith("-parse")) throw new NA("Java has no standard-library JSON parser");
        return new String[]{"SELECT " + p[1] + " FROM t_blob WHERE size_class = '" + p[0] + "' ORDER BY id", p[1]};
    }
    static long touch(String v) { long c = v.length(); for (int i = 0; i < v.length(); i += 64) c += v.charAt(i); return c; }
    static long touch(byte[] v) { long c = v.length; for (int i = 0; i < v.length; i += 64) c += v[i] & 0xff; return c; }

    static String t5(Connection c) throws SQLException {
        String[] p = t5parts(); boolean bin = p[1].equals("doc_bin");
        long ck = 0, bytes = 0;
        try (Statement st = c.createStatement()) {
            for (int rep = 0; rep < 20; rep++) {
                ck = 0;
                try (ResultSet r = st.executeQuery(p[0])) {
                    while (r.next()) {
                        if (bin) { byte[] v = r.getBytes(1); ck += touch(v); bytes += v.length; }
                        else { String v = r.getString(1); ck += touch(v); bytes += v.length(); }
                    }
                }
            }
        }
        ops = bytes / 1024; return Long.toString(ck);
    }

    static String rowB(int i) { return (i % 10 == 0 ? "o'k-" : "name-") + i; }
    static String esc(String s) { return s.replace("\\", "\\\\").replace("'", "\\'"); } // JDBC exposes no escaping API

    static String t6(Connection c) throws SQLException {
        if (variant.equals("sqltext")) {
            StringBuilder sb = new StringBuilder(64 * 1024);
            try (Statement st = c.createStatement()) {
                for (int start = 1; start <= 1000000; start += 1000) {
                    sb.setLength(0); sb.append("INSERT INTO t_bulk (id,a,b,c) VALUES ");
                    for (int i = start; i < start + 1000; i++) {
                        if (i > start) sb.append(',');
                        sb.append('(').append(i).append(',').append(i * 3).append(",'").append(esc(rowB(i))).append("',").append(i * 0.5).append(')');
                    }
                    st.executeUpdate(sb.toString());
                }
            }
        } else if (variant.equals("multiparam")) {
            String sql = "INSERT INTO t_bulk (id,a,b,c) VALUES " + String.join(",", Collections.nCopies(1000, "(?,?,?,?)"));
            try (PreparedStatement ps = c.prepareStatement(sql)) {
                for (int start = 1; start <= 1000000; start += 1000) {
                    for (int k = 0; k < 1000; k++) {
                        int i = start + k;
                        ps.setInt(4 * k + 1, i); ps.setInt(4 * k + 2, i * 3); ps.setString(4 * k + 3, rowB(i)); ps.setDouble(4 * k + 4, i * 0.5);
                    }
                    ps.executeUpdate();
                }
            }
        } else { // batch: addBatch x1000 + executeBatch (rewrite / bulk depends on driver options)
            try (PreparedStatement ps = c.prepareStatement("INSERT INTO t_bulk (id,a,b,c) VALUES (?,?,?,?)")) {
                for (int start = 1; start <= 1000000; start += 1000) {
                    for (int i = start; i < start + 1000; i++) {
                        ps.setInt(1, i); ps.setInt(2, i * 3); ps.setString(3, rowB(i)); ps.setDouble(4, i * 0.5); ps.addBatch();
                    }
                    ps.executeBatch();
                }
            }
        }
        ops = 1000; return "";
    }

    // ------------------------------------------------------------ floor (T3, T5)
    static Object floorData;
    static String floorRun(Connection c) throws SQLException {
        if (test.equals("T3")) {
            if (floorData == null) { int[] v = new int[1000000]; for (int i = 0; i < v.length; i++) v[i] = (int) ((i + 1L) * 7919 % 1000003); floorData = v; }
            long s = 0; for (int x : (int[]) floorData) s += x;
            ops = 1000000; return Long.toString(s);
        }
        if (test.equals("T5")) {
            String[] p = t5parts();
            if (floorData == null) {
                List<String> l = new ArrayList<>();
                try (Statement st = c.createStatement(); ResultSet r = st.executeQuery(p[0])) {
                    while (r.next()) l.add(p[1].equals("doc_bin") ? new String(r.getBytes(1), StandardCharsets.ISO_8859_1) : r.getString(1));
                }
                floorData = l;
            }
            long ck = 0, b = 0;
            for (int rep = 0; rep < 20; rep++) { ck = 0; for (String v : (List<String>) floorData) { ck += touch(v); b += v.length(); } }
            ops = b / 1024; return Long.toString(ck);
        }
        throw new NA("floor defined for T3 and T5 in Java");
    }

    // ------------------------------------------------------------ main
    public static void main(String[] a) throws Exception {
        long rssStart = statusKb("VmRSS:");
        for (int i = 0; i < a.length; i++) {
            switch (a[i]) {
                case "--driver" -> driverName = a[++i];
                case "--test" -> test = a[++i];
                case "--variant" -> variant = a[++i];
                case "--config" -> config = a[++i];
                case "--server" -> server = a[++i];
                case "--warmup" -> warmup = Integer.parseInt(a[++i]);
                case "--iters" -> iters = Integer.parseInt(a[++i]);
                case "--out" -> out = a[++i];
                case "--floor" -> floor = true;
                default -> throw new IllegalArgumentException(a[i]);
            }
        }
        try { run(rssStart); }
        catch (NA e) { System.err.println("n/a: " + e.getMessage()); System.exit(3); }
    }

    static void run(long rssStart) throws Exception {
        mariadb = driverName.equals("mariadb-j");
        drv = mariadb ? new org.mariadb.jdbc.Driver() : new com.mysql.cj.jdbc.Driver();
        lib = (mariadb ? "MariaDB Connector/J " : "MySQL Connector/J ") + drv.getMajorVersion() + "." + drv.getMinorVersion()
            + " (" + drv.getClass().getPackage().getImplementationVersion() + ", Java " + Runtime.version() + ")";
        String stack = mariadb ? "java-mariadb-j" : "java-connector-j";
        String tlsMode = env("DB_TLS", "off");
        if (test.equals("T1") && variant.contains("resume")) throw new NA("JDBC drivers expose no TLS session resumption control");
        if (!mariadb && env("DB_USER", "").equals("bench_ed")) throw new NA("Connector/J has no ed25519 authentication");

        StringBuilder meta = new StringBuilder();
        meta.append(String.format("{\"stack\":\"%s\",\"lib\":\"%s\",\"test\":\"%s\",\"variant\":\"%s\",\"config\":\"%s\",\"server\":\"%s\"",
            stack, lib, test, variant, config, server));
        List<String> recs = new ArrayList<>();
        if (test.equals("T0")) {
            perfOpen(); begin();
            Connection c = connect(tlsMode, false);
            try (Statement s = c.createStatement(); ResultSet r = s.executeQuery("SELECT 1")) { r.next(); }
            recs.add(end("1"));
            meta.append(String.format(",\"tls\":\"%s\",\"ops_per_iter\":1,\"warmup\":0,\"rss_start_kb\":%d", cipher(c), rssStart));
            write(meta, recs); return;
        }
        String tlsName;
        if (test.equals("T1")) {
            String m = variant.startsWith("tls-verify") ? "verify" : variant.startsWith("tls") ? "on" : "off";
            try (Connection c2 = connect(m, variant.equals("socket"))) { tlsName = cipher(c2); }
        } else tlsName = null;
        Connection c = connect(tlsMode, false);
        if (tlsName == null) tlsName = cipher(c);
        if (test.equals("T2")) ids = Files.readAllLines(Path.of(env("DATA_DIR", "/root/bench/data"), "ids_200k.txt")).stream().mapToInt(Integer::parseInt).toArray();

        perfOpen();
        for (int i = 0; i < warmup + iters; i++) {
            if (test.equals("T6")) try (Statement s = c.createStatement()) { s.execute("TRUNCATE TABLE t_bulk"); }
            if (i < warmup) { step(c); continue; }
            begin(); String ck = step(c); String rec = end(ck);
            if (test.equals("T6") && !floor) {
                try (Statement s = c.createStatement(); ResultSet r = s.executeQuery("SELECT COUNT(*), SUM(a), SUM(CHAR_LENGTH(b)) FROM t_bulk")) {
                    r.next(); rec = rec.replace("\"checksum\":\"\"", "\"checksum\":\"" + r.getLong(1) + ":" + r.getLong(2) + ":" + r.getLong(3) + "\"");
                }
            }
            recs.add(rec);
        }
        meta.append(String.format(",\"tls\":\"%s\",\"ops_per_iter\":%d,\"warmup\":%d", tlsName, ops, warmup));
        write(meta, recs);
        c.close();
    }

    static String step(Connection c) throws Exception {
        if (floor) return floorRun(c);
        return switch (test) {
            case "T1" -> t1(c); case "T2" -> t2(c); case "T3" -> t3(c); case "T4" -> t4(c); case "T5" -> t5(c); case "T6" -> t6(c);
            default -> throw new IllegalArgumentException(test);
        };
    }

    static void write(StringBuilder meta, List<String> recs) throws IOException {
        meta.append(",\"iters\":[").append(String.join(",", recs)).append("]}\n");
        if (out == null) System.out.print(meta); else Files.writeString(Path.of(out), meta);
    }
}
