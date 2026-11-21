package bench.fw;

import static bench.Runner.*;
import static org.jooq.impl.DSL.*;

import bench.Runner;
import java.math.BigDecimal;
import java.nio.file.*;
import java.sql.*;
import java.util.*;
import org.hibernate.*;
import org.hibernate.cfg.Configuration;
import org.jooq.BatchBindStep;
import org.jooq.Cursor;
import org.jooq.DSLContext;
import org.jooq.InsertValuesStep4;
import org.jooq.Record1;
import org.jooq.SQLDialect;
import org.jooq.impl.DSL;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;

/**
 * Phase 3 runner: Java frameworks on MySQL Connector/J (the driver measured in Phase 1 as java-connector-j).
 *   hibernate     Hibernate ORM (native API): entities, Session / StatelessSession, HQL
 *   jooq          jOOQ DSL without code generation (plain SQL names)
 *   jdbctemplate  Spring JdbcTemplate
 * default = the idiom most code uses; tuned = the framework's performance options plus Connector/J's tuned options.
 * Same CLI/env contract, checksums and harness (bench.Runner) as the driver runner.
 */
public class Fw {
    static String fw;
    static boolean TUNED;
    static int[] ids;

    interface Impl {
        String name(); String lib();
        void open(String tls) throws Exception; void close() throws Exception;
        String t1(String tls, boolean sock, int n) throws Exception;
        long t2() throws Exception; long t3(boolean streamed) throws Exception; long[] t4(boolean intTable) throws Exception;
        List<Object> t5(String cls, String col) throws Exception; void t6(String variant) throws Exception;
        Connection jdbc();
    }

    // ------------------------------------------------------------ touch helpers
    static long[] touchRow(Object[] vals, long[] acc) {   // acc = {nn, isum, slen}
        for (Object v : vals) {
            if (v == null) continue;
            acc[0]++;
            if (v instanceof Integer || v instanceof Long || v instanceof Short || v instanceof Byte) acc[1] += ((Number) v).longValue();
            else if (v instanceof String s) acc[2] += s.length();
        }
        return acc;
    }
    static long touchDocs(List<Object> vals) {
        long c = 0;
        for (Object o : vals) {
            if (o instanceof String s) { c += s.length(); for (int i = 0; i < s.length(); i += 64) c += s.charAt(i); }
            else { byte[] b = (byte[]) o; c += b.length; for (int i = 0; i < b.length; i += 64) c += b[i] & 0xff; }
        }
        return c;
    }
    static long docBytes(List<Object> vals) { long n = 0; for (Object o : vals) n += o instanceof String s ? s.length() : ((byte[]) o).length; return n; }
    static String rowB(int i) { return (i % 10 == 0 ? "o'k-" : "name-") + i; }

    // ------------------------------------------------------------ Hibernate
    static class Hib implements Impl {
        SessionFactory sf; Session s; StatelessSession ss; Connection aux;   // aux: setup, checksums, cipher
        public String name() { return "java-hibernate"; }
        public String lib() { return "Hibernate " + org.hibernate.Version.getVersionString() + " on " + Runner.lib; }
        SessionFactory factory() {
            if (sf != null) return sf;
            Configuration c = new Configuration()
                .addAnnotatedClass(Entities.TInt.class).addAnnotatedClass(Entities.TBlob.class).addAnnotatedClass(Entities.TBulk.class)
                .addAnnotatedClass(WideInt.class).addAnnotatedClass(WideMix.class)
                .setProperty("hibernate.connection.provider_class", NonPooled.class.getName())
                .setProperty("hibernate.dialect", "org.hibernate.dialect.MySQLDialect")
                .setProperty("hibernate.boot.allow_jdbc_metadata_access", "false")
                .setProperty("hibernate.hbm2ddl.auto", "none")
                .setProperty("hibernate.connection.handling_mode", "DELAYED_ACQUISITION_AND_HOLD");   // one connection per session
            if (TUNED) c.setProperty("hibernate.jdbc.batch_size", "1000").setProperty("hibernate.order_inserts", "true");
            return sf = c.buildSessionFactory();
        }
        public void open(String tls) throws Exception {
            NonPooled.tls = tls; NonPooled.sock = false; factory(); s = sf.openSession(); ss = sf.openStatelessSession();
            aux = Runner.connect(tls, false);
        }
        public void close() throws Exception { s.close(); ss.close(); aux.close(); }
        public Connection jdbc() { return aux; }
        public String t1(String tls, boolean sock, int n) {
            NonPooled.tls = tls; NonPooled.sock = sock;
            for (int i = 0; i < n; i++) try (Session x = sf.openSession()) { x.doWork(c -> {}); }   // forces a connection
            NonPooled.tls = "off"; NonPooled.sock = false;
            return Integer.toString(n);
        }
        public long t2() {
            long sum = 0;
            if (TUNED) for (int id : ids) sum += ss.get(Entities.TInt.class, id).v;                  // StatelessSession: no persistence context
            else for (int id : ids) { sum += s.find(Entities.TInt.class, id).v; s.clear(); }      // find + clear (fresh lookups, as per request)
            return sum;
        }
        public long t3(boolean streamed) {
            long sum = 0;
            if (streamed || TUNED) {
                var q = (TUNED ? ss.createSelectionQuery("from TInt", Entities.TInt.class) : s.createSelectionQuery("from TInt", Entities.TInt.class))
                    .setFetchSize(Integer.MIN_VALUE);
                try (var st = q.getResultStream()) { sum = st.mapToLong(e -> e.v).sum(); }
            } else for (Entities.TInt e : s.createSelectionQuery("from TInt", Entities.TInt.class).getResultList()) sum += e.v;
            s.clear();
            return sum;
        }
        public long[] t4(boolean intTable) {
            long[] acc = new long[3]; long rows = 0;
            List<?> l = intTable ? (TUNED ? ss : s).createSelectionQuery("from WideInt", WideInt.class).getResultList()
                                 : (TUNED ? ss : s).createSelectionQuery("from WideMix", WideMix.class).getResultList();
            for (Object o : l) { rows++; touchRow(o instanceof WideInt w ? w.values() : ((WideMix) o).values(), acc); }
            s.clear();
            return new long[]{acc[0] + acc[1] + acc[2], rows};
        }
        public List<Object> t5(String cls, String col) {
            String attr = col.equals("doc") ? "doc" : "docBin";
            var q = (TUNED ? ss : s).createSelectionQuery("select b." + attr + " from TBlob b where b.sizeClass = :c order by b.id", Object.class);
            List<Object> r = q.setParameter("c", cls).getResultList(); s.clear(); return r;
        }
        public void t6(String variant) {
            if (!variant.equals("batch")) throw new NA("Hibernate inserts entities (the batch variant)");
            for (int st = 1; st <= 1000000; st += 1000) {
                if (TUNED) {
                    org.hibernate.Transaction tx = ss.beginTransaction();
                    for (int i = st; i < st + 1000; i++) ss.insert(new Entities.TBulk(i, i * 3, rowB(i), i * 0.5));
                    tx.commit();
                } else {
                    org.hibernate.Transaction tx = s.beginTransaction();
                    for (int i = st; i < st + 1000; i++) s.persist(new Entities.TBulk(i, i * 3, rowB(i), i * 0.5));
                    tx.commit(); s.clear();
                }
            }
        }
    }

    // ------------------------------------------------------------ jOOQ
    static class Jooq implements Impl {
        Connection c; DSLContext ctx;
        public String name() { return "java-jooq"; }
        public String lib() { return "jOOQ " + org.jooq.Constants.FULL_VERSION + " on " + Runner.lib; }
        public void open(String tls) throws Exception { c = Runner.connect(tls, false); ctx = using(c, SQLDialect.MYSQL); }
        public void close() throws Exception { c.close(); }
        public Connection jdbc() { return c; }
        public String t1(String tls, boolean sock, int n) { throw new NA("jOOQ uses the driver's connections (see java-connector-j)"); }
        public long t2() {
            long sum = 0;
            if (TUNED) {   // query built once, statement kept open, rebound per call
                try (var q = ctx.select(field(DSL.name("v"), Integer.class)).from(table(DSL.name("t_int"))).where(field(DSL.name("id"), Integer.class).eq(0)).keepStatement(true)) {
                    for (int id : ids) { q.bind(1, id); sum += q.fetchOne(0, int.class); }
                }
            } else for (int id : ids)
                sum += ctx.select(field(DSL.name("v"), Integer.class)).from(table(DSL.name("t_int"))).where(field(DSL.name("id"), Integer.class).eq(id)).fetchOne(0, int.class);
            return sum;
        }
        public long t3(boolean streamed) {
            long sum = 0;
            var q = ctx.select(field(DSL.name("v"), Integer.class)).from(table(DSL.name("t_int")));
            if (streamed || TUNED) {
                try (Cursor<Record1<Integer>> cur = q.fetchSize(Integer.MIN_VALUE).fetchLazy()) { for (Record1<Integer> r : cur) sum += r.value1(); }
            } else for (Record1<Integer> r : q.fetch()) sum += r.value1();
            return sum;
        }
        public long[] t4(boolean intTable) {
            long[] acc = new long[3]; long rows = 0;
            for (org.jooq.Record r : ctx.selectFrom(table(DSL.name(intTable ? "t_wide_int" : "t_wide_mix"))).fetch()) {
                rows++; Object[] v = r.intoArray(); touchRow(Arrays.copyOfRange(v, 1, v.length), acc);
            }
            return new long[]{acc[0] + acc[1] + acc[2], rows};
        }
        public List<Object> t5(String cls, String col) {
            Class<?> t = col.equals("doc") ? String.class : byte[].class;
            return new ArrayList<>(ctx.select(field(DSL.name(col), t)).from(table(DSL.name("t_blob"))).where(field(DSL.name("size_class"), String.class).eq(cls))
                .orderBy(field(DSL.name("id"))).fetch(0, t));
        }
        public void t6(String variant) {
            var T = table(DSL.name("t_bulk")); var ID = field(DSL.name("id"), Integer.class); var A = field(DSL.name("a"), Integer.class);
            var B = field(DSL.name("b"), String.class); var C = field(DSL.name("c"), Double.class);
            for (int st = 1; st <= 1000000; st += 1000) {
                if (variant.equals("multiparam")) {
                    var ins = ctx.insertInto(T, ID, A, B, C);
                    InsertValuesStep4<org.jooq.Record, Integer, Integer, String, Double> s = null;
                    for (int i = st; i < st + 1000; i++) s = (s == null ? ins : s).values(i, i * 3, rowB(i), i * 0.5);
                    s.execute();
                } else if (variant.equals("batch")) {
                    BatchBindStep b = ctx.batch(ctx.insertInto(T, ID, A, B, C).values((Integer) null, null, null, null));
                    for (int i = st; i < st + 1000; i++) b = b.bind(i, i * 3, rowB(i), i * 0.5);
                    b.execute();
                } else throw new NA("jOOQ builds the SQL itself; app-built SQL text is the driver test");
            }
        }
    }

    // ------------------------------------------------------------ Spring JdbcTemplate
    static class Tmpl implements Impl {
        Connection c; JdbcTemplate jt;
        public String name() { return "java-jdbctemplate"; }
        public String lib() { return "Spring JDBC " + org.springframework.core.SpringVersion.getVersion() + " on " + Runner.lib; }
        public void open(String tls) throws Exception {
            c = Runner.connect(tls, false); jt = new JdbcTemplate(new SingleConnectionDataSource(c, true));
            if (TUNED) jt.setFetchSize(Integer.MIN_VALUE);   // Connector/J row streaming for every query
        }
        public void close() throws Exception { c.close(); }
        public Connection jdbc() { return c; }
        public String t1(String tls, boolean sock, int n) { throw new NA("JdbcTemplate uses a DataSource's connections (see java-connector-j)"); }
        public long t2() {
            long sum = 0;
            for (int id : ids) sum += jt.queryForObject("SELECT v FROM t_int WHERE id = ?", Integer.class, id);
            return sum;
        }
        public long t3(boolean streamed) {
            long[] sum = {0};
            if (streamed || TUNED) {
                JdbcTemplate t = streamed && !TUNED ? streaming() : jt;
                t.query("SELECT v FROM t_int", (ResultSet rs) -> { sum[0] += rs.getInt(1); });   // RowCallbackHandler
            } else for (Integer v : jt.queryForList("SELECT v FROM t_int", Integer.class)) sum[0] += v;
            return sum[0];
        }
        JdbcTemplate streaming() { JdbcTemplate t = new JdbcTemplate(jt.getDataSource()); t.setFetchSize(Integer.MIN_VALUE); return t; }
        public long[] t4(boolean intTable) {
            long[] acc = new long[3]; long[] rows = {0};
            String sql = "SELECT * FROM " + (intTable ? "t_wide_int" : "t_wide_mix");
            if (TUNED) jt.query(sql, (ResultSet rs) -> { rows[0]++; touchRow(rowValues(rs), acc); });
            else for (Object[] r : jt.query(sql, (rs, i) -> rowValues(rs))) { rows[0]++; touchRow(r, acc); }   // RowMapper -> List
            return new long[]{acc[0] + acc[1] + acc[2], rows[0]};
        }
        static Object[] rowValues(ResultSet rs) throws SQLException {   // typed getters by column type, like the driver runner
            ResultSetMetaData md = rs.getMetaData(); int n = md.getColumnCount(); Object[] v = new Object[n - 1];
            for (int i = 2; i <= n; i++) {
                Object x = switch (md.getColumnType(i)) {
                    case Types.INTEGER, Types.TINYINT, Types.SMALLINT, Types.BIGINT -> rs.getLong(i);
                    case Types.DECIMAL -> rs.getBigDecimal(i);
                    case Types.DOUBLE -> rs.getDouble(i);
                    case Types.DATE -> rs.getObject(i, java.time.LocalDate.class);
                    case Types.TIMESTAMP -> rs.getObject(i, java.time.LocalDateTime.class);
                    default -> rs.getString(i);
                };
                v[i - 2] = rs.wasNull() ? null : x;
            }
            return v;
        }
        public List<Object> t5(String cls, String col) {
            Class<?> t = col.equals("doc") ? String.class : byte[].class;
            return new ArrayList<>(jt.queryForList("SELECT " + col + " FROM t_blob WHERE size_class = ? ORDER BY id", t, cls));
        }
        public void t6(String variant) {
            for (int st = 1; st <= 1000000; st += 1000) {
                if (variant.equals("batch")) {
                    List<Object[]> args = new ArrayList<>(1000);
                    for (int i = st; i < st + 1000; i++) args.add(new Object[]{i, i * 3, rowB(i), i * 0.5});
                    jt.batchUpdate("INSERT INTO t_bulk (id,a,b,c) VALUES (?,?,?,?)", args);
                } else if (variant.equals("multiparam")) {
                    Object[] a = new Object[4000];
                    for (int k = 0; k < 1000; k++) { int i = st + k; a[4 * k] = i; a[4 * k + 1] = i * 3; a[4 * k + 2] = rowB(i); a[4 * k + 3] = i * 0.5; }
                    jt.update("INSERT INTO t_bulk (id,a,b,c) VALUES " + String.join(",", Collections.nCopies(1000, "(?,?,?,?)")), a);
                } else throw new NA("app-built SQL text is the driver test");
            }
        }
    }

    // ------------------------------------------------------------ main
    public static void main(String[] a) throws Exception {
        long rssStart = statusKb("VmRSS:");
        List<String> rest = new ArrayList<>();
        for (int i = 0; i < a.length; i++) { if (a[i].equals("--fw")) fw = a[++i]; else rest.add(a[i]); }
        String[] r = rest.toArray(new String[0]);
        for (int i = 0; i < r.length; i++)
            switch (r[i]) {
                case "--test" -> test = r[++i]; case "--variant" -> variant = r[++i]; case "--config" -> config = r[++i];
                case "--server" -> server = r[++i]; case "--warmup" -> warmup = Integer.parseInt(r[++i]); case "--iters" -> iters = Integer.parseInt(r[++i]);
                case "--out" -> out = r[++i]; case "--floor" -> floor = true; default -> throw new IllegalArgumentException(r[i]);
            }
        TUNED = config.equals("tuned");
        try { run(rssStart); } catch (NA e) { System.err.println("n/a: " + e.getMessage()); System.exit(3); }
        System.exit(0);
    }

    static void run(long rssStart) throws Exception {
        driverName = "connector-j"; mariadb = false;
        drv = new com.mysql.cj.jdbc.Driver();
        lib = "MySQL Connector/J " + drv.getMajorVersion() + "." + drv.getMinorVersion();
        Impl D = switch (fw) { case "hibernate" -> new Hib(); case "jooq" -> new Jooq(); default -> new Tmpl(); };
        if (test.equals("T1") && (variant.contains("resume") || variant.contains("@") || variant.equals("socket")))
            throw new NA("frameworks are measured on tcp, tls and tls-verify (Connector/J has no Unix socket)");
        if (test.equals("T2") && !variant.equals("param")) throw new NA("frameworks bind parameters themselves (variant: param)");
        if ((test.equals("T3") || test.equals("T4")) && variant.contains("binary")) throw new NA("measured on the text protocol");
        String tls = env("DB_TLS", "off");
        String t1tls = variant.startsWith("tls-verify") ? "verify" : variant.startsWith("tls") ? "on" : "off";
        StringBuilder meta = new StringBuilder(String.format("{\"stack\":\"%s\",\"lib\":\"%s\",\"test\":\"%s\",\"variant\":\"%s\",\"config\":\"%s\",\"server\":\"%s\"",
            D.name(), D.lib(), test, variant, config, server));
        List<String> recs = new ArrayList<>();
        if (test.equals("T0")) {
            perfOpen(); begin(); D.open(tls);
            try (Statement st = D.jdbc().createStatement()) { st.execute("SELECT 1"); }
            recs.add(end("1"));
            meta.append(String.format(",\"tls\":\"%s\",\"ops_per_iter\":1,\"warmup\":0,\"rss_start_kb\":%d", cipher(D.jdbc()), rssStart));
            write(meta, recs); D.close(); return;
        }
        D.open(test.equals("T1") ? t1tls : tls);
        String tlsName = cipher(D.jdbc());
        if (test.equals("T1")) { D.close(); D.open("off"); }
        if (test.equals("T2")) ids = Files.readAllLines(Path.of(env("DATA_DIR", "/root/bench/data"), "ids_200k.txt")).stream().mapToInt(Integer::parseInt).toArray();
        long[] ops = {0};
        Step step = () -> switch (test) {
            case "T1" -> { int n = t1tls.equals("off") ? 5000 : 1000; ops[0] = n; yield D.t1(t1tls, false, n); }
            case "T2" -> { ops[0] = ids.length; yield Long.toString(D.t2()); }
            case "T3" -> { ops[0] = 1000000; yield Long.toString(D.t3(variant.contains("streamed"))); }
            case "T4" -> { long[] x = D.t4(variant.startsWith("int")); ops[0] = x[1] * 100; yield Long.toString(x[0]); }
            case "T5" -> {
                String[] p = variant.split("-", 2); if (p[1].endsWith("-parse")) throw new NA("Java has no standard-library JSON parser");
                long ck = 0, bytes = 0;
                for (int rep = 0; rep < 20; rep++) { List<Object> v = D.t5(p[0], p[1]); ck = touchDocs(v); bytes += docBytes(v); }
                ops[0] = bytes / 1024; yield Long.toString(ck);
            }
            default -> { D.t6(variant); ops[0] = 1000; yield ""; }
        };
        long rssBase = statusKb("VmRSS:");
        perfOpen();
        // adaptive warm-up (same rule as the driver runner)
        boolean stable = true; int done = 0;
        if (System.getenv("ADAPTIVE_WARMUP") != null) {
            List<Long> w = new ArrayList<>(); long t0 = System.nanoTime();
            int cap = Integer.parseInt(env("WARMUP_CAP", "40")); long capNs = Long.parseLong(env("WARMUP_CAP_S", "120")) * 1_000_000_000L;
            while (true) {
                truncate(D); long c0 = cpuNs(); step.run(); w.add(cpuNs() - c0); int n = w.size();
                if (n >= Math.max(3, warmup)) { List<Long> l = new ArrayList<>(w.subList(n - 3, n)); Collections.sort(l); if (l.get(2) - l.get(0) <= 0.05 * l.get(1)) break; }
                if (n >= cap || System.nanoTime() - t0 > capNs) { stable = false; break; }
            }
            done = w.size();
        } else { for (int i = 0; i < warmup; i++) { truncate(D); step.run(); } done = warmup; }
        for (int i = 0; i < iters; i++) {
            truncate(D);
            begin(); String ck = step.run(); String rec = end(ck);
            if (test.equals("T6")) try (Statement st = D.jdbc().createStatement(); ResultSet rs = st.executeQuery("SELECT COUNT(*), SUM(a), SUM(CHAR_LENGTH(b)) FROM t_bulk")) {
                rs.next(); rec = rec.replace("\"checksum\":\"\"", "\"checksum\":\"" + rs.getLong(1) + ":" + rs.getLong(2) + ":" + rs.getLong(3) + "\"");
            }
            recs.add(rec);
        }
        meta.append(String.format(",\"tls\":\"%s\",\"ops_per_iter\":%d,\"warmup\":%d,\"rss_baseline_kb\":%d,\"warmup_adaptive\":%b,\"warmup_stable\":%b",
            tlsName, ops[0], done, rssBase, System.getenv("ADAPTIVE_WARMUP") != null, stable));
        write(meta, recs); D.close();
    }

    interface Step { String run() throws Exception; }
    static void truncate(Impl D) throws Exception {
        if (test.equals("T6")) try (Statement s = D.jdbc().createStatement()) { s.execute("TRUNCATE TABLE t_bulk"); }
    }
}
