// C++ runner: MySQL Connector/C++ (classic JDBC-style API) and MariaDB Connector/C++.
// One source, two builds (-DMARIADB_CPP for MariaDB). Uses the shared C harness (stacks/c/bench.h).
// Same CLI/env contract as the other runners (SPEC.md section 5).
extern "C" {
#include "../c/bench.h"
}
#include <memory>
#include <string>
#include <vector>
#include <fstream>
#ifdef MARIADB_CPP
#include <conncpp.hpp>
#define STACK "cpp-mariadb"
#define GET_LONG getLong
#define SET_LONG setLong
static std::string S(const sql::SQLString& s) { return std::string(s.c_str(), s.length()); }
#else
#include <mysql/jdbc.h>
#define STACK "cpp-mysql-connector"
#define GET_LONG getInt64
#define SET_LONG setInt64
static std::string S(const sql::SQLString& s) { return s.asStdString(); }
#endif

static const char* E(const char* k, const char* d) { const char* v = getenv(k); return v && *v ? v : d; }
static std::string g_test = "T0", g_variant, g_config = "default", g_server = "ps";
static const char* g_out = nullptr;
static int g_warmup = 2, g_iters = 5;
static long long g_ops;
struct NA { std::string why; };

static bool server_prep() { return g_variant == "prepared" || g_variant.rfind("binary", 0) == 0 || g_variant.find("binary") != std::string::npos; }

static sql::Connection* connect_(const std::string& tls, bool sock) {
#ifdef MARIADB_CPP
  sql::Driver* d = sql::mariadb::get_driver_instance();
  sql::Properties p;
  p["user"] = E("DB_USER", "bench"); p["password"] = E("DB_PASS", "bench");
  if (tls == "on") { p["useTls"] = "true"; p["trustServerCertificate"] = "true"; }
  else if (tls == "verify") { p["useTls"] = "true"; p["tlsCA"] = E("DB_CA", ""); }
  if (server_prep()) p["useServerPrepStmts"] = "true";
  std::string url = std::string("jdbc:mariadb://") + E("DB_HOST", "127.0.0.1") + ":" + E("DB_PORT", "3306") + "/" + E("DB_NAME", "bench");
  if (sock) p["localSocket"] = E("DB_SOCKET", "");
  return d->connect(url, p);
#else
  sql::mysql::MySQL_Driver* d = sql::mysql::get_mysql_driver_instance();
  sql::ConnectOptionsMap o;
  o["hostName"] = sock ? sql::SQLString(std::string("unix://") + E("DB_SOCKET", ""))
                       : sql::SQLString(std::string("tcp://") + E("DB_HOST", "127.0.0.1") + ":" + E("DB_PORT", "3306"));
  o["userName"] = sql::SQLString(E("DB_USER", "bench")); o["password"] = sql::SQLString(E("DB_PASS", "bench"));
  o["schema"] = sql::SQLString(E("DB_NAME", "bench"));
  o["OPT_SSL_MODE"] = tls == "off" ? sql::SSL_MODE_DISABLED : tls == "on" ? sql::SSL_MODE_REQUIRED : sql::SSL_MODE_VERIFY_IDENTITY;
  if (tls == "verify") o["sslCA"] = sql::SQLString(E("DB_CA", ""));
  // Connector/C++ 9.x+ loads mysql_native_password as a plugin; point it at the unpacked Oracle client plugins
  o["pluginDir"] = sql::SQLString(E("CPP_PLUGIN_DIR", "/opt/oracle/usr/lib/x86_64-linux-gnu/mysql/libmysqlcppconn10/plugin"));
  return d->connect(o);
#endif
}

static std::string cipher(sql::Connection* c) {
  std::unique_ptr<sql::Statement> st(c->createStatement());
  std::unique_ptr<sql::ResultSet> r(st->executeQuery("SHOW SESSION STATUS LIKE 'Ssl_cipher'"));
  std::string v = r->next() ? S(r->getString(2)) : "";
  return v.empty() ? "none" : v;
}
static void exec(sql::Connection* c, const char* q) {
  std::unique_ptr<sql::Statement> st(c->createStatement());
  if (st->execute(q)) { std::unique_ptr<sql::ResultSet> r(st->getResultSet()); while (r->next()) {} }   // consume, or the next query is out of sync
}

// Statement configured for buffered (default) or streamed results
static sql::Statement* stmt_for(sql::Connection* c, bool streamed) {
  sql::Statement* st = c->createStatement();
#ifdef MARIADB_CPP
  if (streamed) st->setFetchSize(1000);
#else
  if (streamed) st->setResultSetType(sql::ResultSet::TYPE_FORWARD_ONLY);  // mysql_use_result
#endif
  return st;
}

static std::vector<int> g_ids;
static std::string t1_mode() { return g_variant.rfind("tls-verify", 0) == 0 ? "verify" : g_variant.rfind("tls", 0) == 0 ? "on" : "off"; }

static std::string t1(sql::Connection*) {
  int n = t1_mode() == "off" ? 10000 : 2000;
  for (int i = 0; i < n; i++) delete connect_(t1_mode(), g_variant == "socket");
  g_ops = n; return std::to_string(n);
}
static std::string t2(sql::Connection* c) {
  long long s = 0;
  if (g_variant == "literal") {
    std::unique_ptr<sql::Statement> st(c->createStatement());
    for (int id : g_ids) { std::unique_ptr<sql::ResultSet> r(st->executeQuery("SELECT v FROM t_int WHERE id = " + std::to_string(id))); r->next(); s += r->getInt(1); }
  } else {
#ifndef MARIADB_CPP
    if (g_variant == "param") throw NA{"Connector/C++ PreparedStatement is always server-side; no client-side parameters"};
#endif
    // MariaDB: param = client-side PreparedStatement (default); prepared = useServerPrepStmts=true
    std::unique_ptr<sql::PreparedStatement> ps(c->prepareStatement("SELECT v FROM t_int WHERE id = ?"));
    for (int id : g_ids) { ps->setInt(1, id); std::unique_ptr<sql::ResultSet> r(ps->executeQuery()); r->next(); s += r->getInt(1); }
  }
  g_ops = g_ids.size(); return std::to_string(s);
}
static sql::ResultSet* run_query(sql::Connection* c, const std::string& q, bool streamed, bool binary,
                                 std::unique_ptr<sql::Statement>& st, std::unique_ptr<sql::PreparedStatement>& ps) {
  if (binary) {
#ifdef MARIADB_CPP
    ps.reset(c->prepareStatement(q)); if (streamed) ps->setFetchSize(1000);
#else
    if (streamed) throw NA{"Connector/C++ cannot stream prepared-statement results"};
    ps.reset(c->prepareStatement(q));
#endif
    return ps->executeQuery();
  }
  st.reset(stmt_for(c, streamed)); return st->executeQuery(q);
}
static std::string t3(sql::Connection* c) {
  std::unique_ptr<sql::Statement> st; std::unique_ptr<sql::PreparedStatement> ps;
  std::unique_ptr<sql::ResultSet> r(run_query(c, "SELECT v FROM t_int", g_variant.find("streamed") != std::string::npos, g_variant.rfind("binary", 0) == 0, st, ps));
  long long s = 0; while (r->next()) s += r->getInt(1);
  g_ops = 1000000; return std::to_string(s);
}
static std::string t4(sql::Connection* c) {
  std::unique_ptr<sql::Statement> st; std::unique_ptr<sql::PreparedStatement> ps;
  bool binary = g_variant.size() > 6 && g_variant.compare(g_variant.size() - 6, 6, "binary") == 0;
  std::unique_ptr<sql::ResultSet> r(run_query(c, g_variant.rfind("int", 0) == 0 ? "SELECT * FROM t_wide_int" : "SELECT * FROM t_wide_mix", false, binary, st, ps));
  sql::ResultSetMetaData* md = r->getMetaData();
  int n = md->getColumnCount();
  std::vector<int> kind(n + 1);
  for (int i = 1; i <= n; i++) {
    std::string t = S(md->getColumnTypeName(i));
    for (auto& ch : t) ch = toupper(ch);
    kind[i] = t.find("INT") != std::string::npos ? 1 : (t == "VARCHAR" || t == "CHAR") ? 2 : t == "DECIMAL" ? 3 : t == "DOUBLE" ? 4 : 5;
  }
  long long nn = 0, isum = 0, slen = 0, rows = 0;
  while (r->next()) {
    rows++;
    for (int i = 2; i <= n; i++) {
      if (r->isNull(i)) continue;
      nn++;
      switch (kind[i]) {
        case 1: isum += r->GET_LONG(i); break;
        case 2: slen += r->getString(i).length(); break;
        case 4: (void)r->getDouble(i); break;
        default: (void)r->getString(i); break;   // DECIMAL / DATE / DATETIME: the API offers strings
      }
    }
  }
  g_ops = rows * 100; return std::to_string(nn + isum + slen);
}
static std::string t5(sql::Connection* c) {
  size_t dash = g_variant.find('-'); std::string cls = g_variant.substr(0, dash), col = g_variant.substr(dash + 1);
  if (col.find("-parse") != std::string::npos) throw NA{"C++ has no standard JSON library"};
  std::string q = "SELECT " + col + " FROM t_blob WHERE size_class = '" + cls + "' ORDER BY id";
  long long ck = 0, bytes = 0;
  std::unique_ptr<sql::Statement> st(c->createStatement());
  for (int rep = 0; rep < 20; rep++) {
    ck = 0;
    std::unique_ptr<sql::ResultSet> r(st->executeQuery(q));
    while (r->next()) {
      sql::SQLString v = r->getString(1);
      const unsigned char* p = (const unsigned char*)v.c_str(); size_t len = v.length();
      ck += len; bytes += len;
      for (size_t i = 0; i < len; i += 64) ck += p[i];
    }
  }
  g_ops = bytes / 1024; return std::to_string(ck);
}
static std::string row_b(int i) { return (i % 10 == 0 ? "o'k-" : "name-") + std::to_string(i); }
static std::string esc(const std::string& s) {   // neither connector exposes an escaping function in its public API
  std::string o; o.reserve(s.size() + 4);
  for (char ch : s) { if (ch == '\'' || ch == '\\') o += '\\'; o += ch; }
  return o;
}
static std::string t6(sql::Connection* c) {
  if (g_variant == "sqltext") {
    std::unique_ptr<sql::Statement> st(c->createStatement());
    std::string q; char num[64];
    for (int s0 = 1; s0 <= 1000000; s0 += 1000) {
      q = "INSERT INTO t_bulk (id,a,b,c) VALUES ";
      for (int i = s0; i < s0 + 1000; i++) {
        snprintf(num, sizeof num, "%.17g", i * 0.5);
        if (i > s0) q += ',';
        q += "(" + std::to_string(i) + "," + std::to_string(i * 3) + ",'" + esc(row_b(i)) + "'," + num + ")";
      }
      st->execute(q);
    }
  } else if (g_variant == "multiparam") {
    std::string q = "INSERT INTO t_bulk (id,a,b,c) VALUES ";
    for (int k = 0; k < 1000; k++) q += k ? ",(?,?,?,?)" : "(?,?,?,?)";
    std::unique_ptr<sql::PreparedStatement> ps(c->prepareStatement(q));
    for (int s0 = 1; s0 <= 1000000; s0 += 1000) {
      for (int k = 0; k < 1000; k++) {
        int i = s0 + k;
        ps->setInt(4 * k + 1, i); ps->setInt(4 * k + 2, i * 3); ps->setString(4 * k + 3, row_b(i)); ps->setDouble(4 * k + 4, i * 0.5);
      }
      ps->executeUpdate();
    }
  } else {
#ifdef MARIADB_CPP
    std::unique_ptr<sql::PreparedStatement> ps(c->prepareStatement("INSERT INTO t_bulk (id,a,b,c) VALUES (?,?,?,?)"));
    for (int s0 = 1; s0 <= 1000000; s0 += 1000) {
      for (int i = s0; i < s0 + 1000; i++) { ps->setInt(1, i); ps->setInt(2, i * 3); ps->setString(3, row_b(i)); ps->setDouble(4, i * 0.5); ps->addBatch(); }
      ps->executeBatch(); ps->clearBatch();   // MariaDB Connector/C++ keeps the batch after executeBatch()
    }
#else
    throw NA{"Connector/C++ has no batch API"};
#endif
  }
  g_ops = 1000; return "";
}

int main(int argc, char** argv) {
  long long rss0 = b_status_kb("VmRSS:");
  for (int i = 1; i < argc; i++) {
    std::string a = argv[i]; const char* v = i + 1 < argc ? argv[i + 1] : "";
    if (a == "--test") g_test = v, i++; else if (a == "--variant") g_variant = v, i++; else if (a == "--config") g_config = v, i++;
    else if (a == "--server") g_server = v, i++; else if (a == "--warmup") g_warmup = atoi(v), i++; else if (a == "--iters") g_iters = atoi(v), i++;
    else if (a == "--out") g_out = v, i++; else if (a == "--floor") b_na("floor: see the C runner (native code, same loops)");
  }
  try {
    if (g_config != "default") throw NA{"C++ driver options are covered by the explicit variants"};
    if (g_test == "T1" && g_variant.find("resume") != std::string::npos) throw NA{"C++ connectors expose no TLS session resumption control"};
#ifndef MARIADB_CPP
    if (std::string(E("DB_USER", "")) == "bench_ed") throw NA{"Connector/C++ has no ed25519 client plugin"};
#endif
    std::string lib =
#ifdef MARIADB_CPP
      "MariaDB Connector/C++ " MACPP_VERSION;
#else
      "MySQL Connector/C++ " MYCPP_VERSION;
#endif
    std::vector<iter_t> its(g_iters);
    std::string tls_name;
    if (g_test == "T0") {
      b_perf_open(); b_begin();
      std::unique_ptr<sql::Connection> c(connect_(E("DB_TLS", "off"), false)); exec(c.get(), "SELECT 1");
      b_end(&its[0]); strcpy(its[0].checksum, "1");
      char extra[64]; snprintf(extra, sizeof extra, "\"rss_start_kb\":%lld", rss0);
      b_write(g_out, STACK, lib.c_str(), g_test.c_str(), g_variant.c_str(), g_config.c_str(), g_server.c_str(), cipher(c.get()).c_str(), 1, 0, its.data(), 1, extra);
      return 0;
    }
    if (g_test == "T1") { std::unique_ptr<sql::Connection> c2(connect_(t1_mode(), g_variant == "socket")); tls_name = cipher(c2.get()); }
    std::unique_ptr<sql::Connection> c(connect_(E("DB_TLS", "off"), false));
    if (g_test != "T1") tls_name = cipher(c.get());
    if (g_test == "T2") { std::ifstream f(std::string(E("DATA_DIR", "/root/bench/data")) + "/ids_200k.txt"); int x; while (f >> x) g_ids.push_back(x); }
    std::string (*fn)(sql::Connection*) = g_test == "T1" ? t1 : g_test == "T2" ? t2 : g_test == "T3" ? t3 : g_test == "T4" ? t4 : g_test == "T5" ? t5 : t6;
    char extra[64]; snprintf(extra, sizeof extra, "\"rss_baseline_kb\":%lld", b_status_kb("VmRSS:"));
    b_perf_open();
    for (int i = 0; i < g_warmup + g_iters; i++) {
      if (g_test == "T6") exec(c.get(), "TRUNCATE TABLE t_bulk");
      if (i < g_warmup) { fn(c.get()); continue; }
      iter_t* it = &its[i - g_warmup];
      b_begin(); std::string ck = fn(c.get()); b_end(it);
      snprintf(it->checksum, sizeof it->checksum, "%s", ck.c_str());
      if (g_test == "T6") {
        std::unique_ptr<sql::Statement> st(c->createStatement());
        std::unique_ptr<sql::ResultSet> r(st->executeQuery("SELECT COUNT(*), CAST(SUM(a) AS SIGNED), CAST(SUM(CHAR_LENGTH(b)) AS SIGNED) FROM t_bulk"));
        r->next(); snprintf(it->checksum, sizeof it->checksum, "%lld:%lld:%lld", (long long)r->GET_LONG(1), (long long)r->GET_LONG(2), (long long)r->GET_LONG(3));
      }
    }
    b_write(g_out, STACK, lib.c_str(), g_test.c_str(), g_variant.c_str(), g_config.c_str(), g_server.c_str(), tls_name.c_str(), g_ops, g_warmup, its.data(), g_iters, extra);
  } catch (NA& e) { fprintf(stderr, "n/a: %s\n", e.why.c_str()); return 3; }
  catch (sql::SQLException& e) {
    if (std::string(e.what()).find("Bulk") != std::string::npos) { fprintf(stderr, "n/a: server has no bulk execute\n"); return 3; }
    fprintf(stderr, "SQLException: %s\n", e.what()); return 1;
  }
  return 0;
}
