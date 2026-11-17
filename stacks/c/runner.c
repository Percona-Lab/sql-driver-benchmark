/* C runner for libmysqlclient (Oracle) and MariaDB Connector/C.
 * Same source, two builds (see build.sh). Implements T0-T6 from SPEC.md.
 *
 * usage: runner --test T3 --variant text-buffered [--config default] [--server ps]
 *               [--warmup 2] [--iters 5] [--floor] [--out file.json]
 * connection from env: DB_HOST DB_PORT DB_SOCKET DB_USER DB_PASS DB_NAME DB_CA DB_TLS(off|on|verify) DATA_DIR
 */
#include "bench.h"
#include <mysql.h>
#include <errno.h>

#ifdef MARIADB_PACKAGE_VERSION
#define STACK "c-mariadb-connc"
#define IS_MARIADB 1
#else
#define STACK "c-libmysqlclient"
#define IS_MARIADB 0
#endif

static const char *E(const char *k, const char *d) { const char *v = getenv(k); return v && *v ? v : d; }
static const char *g_test = "T0", *g_variant = "", *g_config = "default", *g_server = "ps", *g_out = NULL;
static int g_warmup = 2, g_iters = 5, g_floor = 0;
static char g_tls[96] = "";

/* ------------------------------------------------------------------ connections */
enum { TLS_OFF, TLS_ON, TLS_VERIFY };
#if !IS_MARIADB
static void *g_sess = NULL;  /* TLS session data for resumption */
#endif

static MYSQL *db_connect(int tls, int use_socket, int resume) {
  MYSQL *m = mysql_init(NULL);
  if (!m) b_die("mysql_init");
#if IS_MARIADB
  my_bool on = 1, off = 0;
  if (tls == TLS_OFF) {
    mysql_optionsv(m, MYSQL_OPT_SSL_ENFORCE, &off);
    mysql_optionsv(m, MYSQL_OPT_SSL_VERIFY_SERVER_CERT, &off);
  } else {
    mysql_optionsv(m, MYSQL_OPT_SSL_ENFORCE, &on);
    mysql_optionsv(m, MYSQL_OPT_SSL_VERIFY_SERVER_CERT, tls == TLS_VERIFY ? &on : &off);
    if (tls == TLS_VERIFY) mysql_optionsv(m, MYSQL_OPT_SSL_CA, E("DB_CA", ""));
  }
  (void)resume;
#else
  unsigned mode = tls == TLS_OFF ? SSL_MODE_DISABLED : tls == TLS_ON ? SSL_MODE_REQUIRED : SSL_MODE_VERIFY_IDENTITY;
  mysql_options(m, MYSQL_OPT_SSL_MODE, &mode);
  if (tls == TLS_VERIFY) mysql_options(m, MYSQL_OPT_SSL_CA, E("DB_CA", ""));
  if (resume && g_sess) mysql_options(m, MYSQL_OPT_SSL_SESSION_DATA, g_sess);
#endif
  const char *host = use_socket ? "localhost" : E("DB_HOST", "127.0.0.1");
  const char *sock = use_socket ? E("DB_SOCKET", NULL) : NULL;
  if (!use_socket) { unsigned proto = MYSQL_PROTOCOL_TCP; mysql_options(m, MYSQL_OPT_PROTOCOL, &proto); }
  if (!mysql_real_connect(m, host, E("DB_USER", "bench"), E("DB_PASS", "bench"), E("DB_NAME", "bench"),
                          atoi(E("DB_PORT", "3306")), sock, 0))
    b_die("connect: %s", mysql_error(m));
#if !IS_MARIADB
  if (resume) {
    if (g_sess) mysql_free_ssl_session_data(m, g_sess);
    g_sess = mysql_get_ssl_session_data(m, 0, NULL);
  }
#endif
  return m;
}

static int tls_mode(void) {
  const char *t = E("DB_TLS", "off");
  return !strcmp(t, "verify") ? TLS_VERIFY : !strcmp(t, "on") ? TLS_ON : TLS_OFF;
}

static void q(MYSQL *m, const char *sql) {
  if (mysql_query(m, sql)) b_die("%s: %s", sql, mysql_error(m));
  MYSQL_RES *r = mysql_store_result(m); if (r) mysql_free_result(r);
}

static void record_tls(MYSQL *m) {
  if (mysql_query(m, "SHOW SESSION STATUS LIKE 'Ssl_cipher'")) b_die("%s", mysql_error(m));
  MYSQL_RES *r = mysql_store_result(m); MYSQL_ROW row = mysql_fetch_row(r);
  snprintf(g_tls, sizeof g_tls, "%s", row && row[1] && *row[1] ? row[1] : "none");
  mysql_free_result(r);
}

static MYSQL_STMT *prep(MYSQL *m, const char *sql) {
  MYSQL_STMT *s = mysql_stmt_init(m);
  if (mysql_stmt_prepare(s, sql, strlen(sql))) b_die("prepare %s: %s", sql, mysql_stmt_error(s));
  return s;
}

/* ------------------------------------------------------------------ tests
 * Each test function runs ONE measured iteration's work and writes its checksum.
 * Setup that must not be measured happens in the *_setup step in main(). */
static MYSQL *g_m;
static int *g_ids; static int g_nids;
static long long g_ops;

/* T1: connect */
static void t1(char *ck) {
  int n = 2000, sock = !strcmp(g_variant, "socket"), resume = !strcmp(g_variant, "tls-resume");
  int tls = !strcmp(g_variant, "tls") || resume ? TLS_ON : !strcmp(g_variant, "tls-verify") ? TLS_VERIFY : TLS_OFF;
  for (int i = 0; i < n; i++) { MYSQL *m = db_connect(tls, sock, resume); mysql_close(m); }
  g_ops = n; snprintf(ck, 96, "%d", n);
}

/* T2: point select */
static void t2(char *ck) {
  long long sum = 0;
  if (!strcmp(g_variant, "literal")) {
    char sql[96];
    for (int i = 0; i < g_nids; i++) {
      int len = snprintf(sql, sizeof sql, "SELECT v FROM t_int WHERE id = %d", g_ids[i]);
      if (mysql_real_query(g_m, sql, len)) b_die("%s", mysql_error(g_m));
      MYSQL_RES *r = mysql_store_result(g_m); MYSQL_ROW row = mysql_fetch_row(r);
      sum += strtol(row[0], NULL, 10); mysql_free_result(r);
    }
  } else { /* prepared */
    static MYSQL_STMT *s; static MYSQL_BIND pb, rb; static int id, v;
    if (!s) {
      s = prep(g_m, "SELECT v FROM t_int WHERE id = ?");
      pb.buffer_type = MYSQL_TYPE_LONG; pb.buffer = &id; mysql_stmt_bind_param(s, &pb);
      rb.buffer_type = MYSQL_TYPE_LONG; rb.buffer = &v; mysql_stmt_bind_result(s, &rb);
    }
    for (int i = 0; i < g_nids; i++) {
      id = g_ids[i];
      if (mysql_stmt_execute(s)) b_die("%s", mysql_stmt_error(s));
      if (mysql_stmt_fetch(s)) b_die("fetch");
      sum += v; mysql_stmt_free_result(s);
    }
  }
  g_ops = g_nids; snprintf(ck, 96, "%lld", sum);
}

/* T3: 1M ints */
static void t3(char *ck) {
  long long sum = 0;
  int streamed = strstr(g_variant, "streamed") != NULL;
  if (!strncmp(g_variant, "text", 4)) {
    if (mysql_query(g_m, "SELECT v FROM t_int")) b_die("%s", mysql_error(g_m));
    MYSQL_RES *r = streamed ? mysql_use_result(g_m) : mysql_store_result(g_m); MYSQL_ROW row;
    while ((row = mysql_fetch_row(r))) sum += strtol(row[0], NULL, 10);
    mysql_free_result(r);
  } else {
    MYSQL_STMT *s = prep(g_m, "SELECT v FROM t_int"); MYSQL_BIND rb; int v;
    memset(&rb, 0, sizeof rb); rb.buffer_type = MYSQL_TYPE_LONG; rb.buffer = &v;
    if (mysql_stmt_execute(s)) b_die("%s", mysql_stmt_error(s));
    mysql_stmt_bind_result(s, &rb);
    if (!streamed && mysql_stmt_store_result(s)) b_die("%s", mysql_stmt_error(s));
    while (!mysql_stmt_fetch(s)) sum += v;
    mysql_stmt_close(s);
  }
  g_ops = 1000000; snprintf(ck, 96, "%lld", sum);
}

/* T4: wide rows; checksum = non-null cells + integer sum + string lengths */
static int is_int(enum enum_field_types t) {
  return t == MYSQL_TYPE_TINY || t == MYSQL_TYPE_SHORT || t == MYSQL_TYPE_LONG || t == MYSQL_TYPE_LONGLONG || t == MYSQL_TYPE_INT24;
}
static int is_str(enum enum_field_types t) {
  return t == MYSQL_TYPE_VAR_STRING || t == MYSQL_TYPE_STRING || t == MYSQL_TYPE_VARCHAR;
}
static void t4(char *ck) {
  const char *sql = !strncmp(g_variant, "int", 3) ? "SELECT * FROM t_wide_int" : "SELECT * FROM t_wide_mix";
  long long nn = 0, isum = 0, slen = 0, rows = 0;
  if (strstr(g_variant, "text")) {
    if (mysql_query(g_m, sql)) b_die("%s", mysql_error(g_m));
    MYSQL_RES *r = mysql_store_result(g_m);
    unsigned nf = mysql_num_fields(r); MYSQL_FIELD *f = mysql_fetch_fields(r); MYSQL_ROW row;
    while ((row = mysql_fetch_row(r))) {
      unsigned long *len = mysql_fetch_lengths(r); rows++;
      for (unsigned c = 1; c < nf; c++) {           /* column 0 is id, not part of the checksum */
        if (!row[c]) continue;
        nn++;
        if (is_int(f[c].type)) isum += strtoll(row[c], NULL, 10);
        else if (is_str(f[c].type)) slen += len[c];
      }
    }
    mysql_free_result(r);
  } else {
    MYSQL_STMT *s = prep(g_m, sql);
    if (mysql_stmt_execute(s)) b_die("%s", mysql_stmt_error(s));
    MYSQL_RES *meta = mysql_stmt_result_metadata(s);
    unsigned nf = mysql_num_fields(meta); MYSQL_FIELD *f = mysql_fetch_fields(meta);
    MYSQL_BIND *b = calloc(nf, sizeof *b);
    union cell { long long ll; double d; MYSQL_TIME t; char s[264]; } *cells = calloc(nf, sizeof *cells);
    unsigned long *lens = calloc(nf, sizeof *lens);
#if IS_MARIADB
    my_bool *nulls = calloc(nf, sizeof *nulls);
#else
    bool *nulls = calloc(nf, sizeof *nulls);
#endif
    for (unsigned c = 0; c < nf; c++) {
      b[c].buffer = &cells[c]; b[c].is_null = &nulls[c]; b[c].length = &lens[c];
      if (is_int(f[c].type)) b[c].buffer_type = MYSQL_TYPE_LONGLONG;
      else if (f[c].type == MYSQL_TYPE_DOUBLE) b[c].buffer_type = MYSQL_TYPE_DOUBLE;
      else if (f[c].type == MYSQL_TYPE_DATETIME || f[c].type == MYSQL_TYPE_DATE) b[c].buffer_type = f[c].type;
      else { b[c].buffer_type = MYSQL_TYPE_STRING; b[c].buffer_length = sizeof cells[c].s; } /* DECIMAL, VARCHAR */
    }
    mysql_stmt_bind_result(s, b);
    if (mysql_stmt_store_result(s)) b_die("%s", mysql_stmt_error(s));
    while (!mysql_stmt_fetch(s)) {
      rows++;
      for (unsigned c = 1; c < nf; c++) {
        if (nulls[c]) continue;
        nn++;
        if (is_int(f[c].type)) isum += cells[c].ll;
        else if (is_str(f[c].type)) slen += lens[c];
      }
    }
    mysql_free_result(meta); mysql_stmt_close(s); free(b); free(cells); free(lens); free(nulls);
  }
  g_ops = rows * 100; snprintf(ck, 96, "%lld", nn + isum + slen);
}

/* T5: blobs. variant: <class>-<doc|doc_bin>, e.g. 100k-doc. 20 queries per iteration. */
static void t5(char *ck) {
  char cls[16], col[16], sql[128];
  if (sscanf(g_variant, "%15[^-]-%15s", cls, col) != 2) b_die("bad variant");
  if (!strcmp(col, "doc-parse")) b_na("C has no standard JSON library");
  snprintf(sql, sizeof sql, "SELECT %s FROM t_blob WHERE size_class = '%s' ORDER BY id", col, cls);
  long long ck1 = 0, bytes = 0;
  for (int rep = 0; rep < 20; rep++) {
    long long c = 0;
    if (mysql_query(g_m, sql)) b_die("%s", mysql_error(g_m));
    MYSQL_RES *r = mysql_store_result(g_m); MYSQL_ROW row;
    while ((row = mysql_fetch_row(r))) {
      unsigned long len = mysql_fetch_lengths(r)[0];
      const unsigned char *p = (const unsigned char *)row[0];
      c += len; bytes += len;
      for (unsigned long i = 0; i < len; i += 64) c += p[i];
    }
    mysql_free_result(r);
    ck1 = c;  /* every repetition must give the same checksum; report the last */
  }
  g_ops = bytes / 1024;  /* KB */
  snprintf(ck, 96, "%lld", ck1);
}

/* T6: bulk insert, 1M rows, 1000 rows/statement, autocommit (= commit per statement) */
#define T6_ROWS 1000000
#define T6_BATCH 1000
static void row_b(int i, char *buf) { sprintf(buf, i % 10 == 0 ? "o'k-%d" : "name-%d", i); }
static void t6(char *ck) {
  if (!strcmp(g_variant, "sqltext")) {
    size_t cap = T6_BATCH * 160 + 64; char *sql = malloc(cap); char b[32], eb[72];
    for (int start = 1; start <= T6_ROWS; start += T6_BATCH) {
      char *p = sql + sprintf(sql, "INSERT INTO t_bulk (id,a,b,c) VALUES ");
      for (int i = start; i < start + T6_BATCH; i++) {
        row_b(i, b);
        mysql_real_escape_string(g_m, eb, b, strlen(b));
        p += sprintf(p, "%s(%d,%d,'%s',%.17g)", i == start ? "" : ",", i, i * 3, eb, i * 0.5);
      }
      if (mysql_real_query(g_m, sql, p - sql)) b_die("%s", mysql_error(g_m));
    }
    free(sql);
  } else if (!strcmp(g_variant, "multiparam")) {
    size_t cap = 64 + T6_BATCH * 12; char *sql = malloc(cap);
    char *p = sql + sprintf(sql, "INSERT INTO t_bulk (id,a,b,c) VALUES ");
    for (int i = 0; i < T6_BATCH; i++) p += sprintf(p, "%s(?,?,?,?)", i ? "," : "");
    MYSQL_STMT *s = prep(g_m, sql);
    MYSQL_BIND *pb = calloc(T6_BATCH * 4, sizeof *pb);
    int *ids = calloc(T6_BATCH, sizeof *ids), *as = calloc(T6_BATCH, sizeof *as);
    double *cs = calloc(T6_BATCH, sizeof *cs);
    char (*bs)[32] = calloc(T6_BATCH, 32); unsigned long *bl = calloc(T6_BATCH, sizeof *bl);
    for (int k = 0; k < T6_BATCH; k++) {
      pb[4 * k].buffer_type = MYSQL_TYPE_LONG; pb[4 * k].buffer = &ids[k];
      pb[4 * k + 1].buffer_type = MYSQL_TYPE_LONG; pb[4 * k + 1].buffer = &as[k];
      pb[4 * k + 2].buffer_type = MYSQL_TYPE_STRING; pb[4 * k + 2].buffer = bs[k]; pb[4 * k + 2].length = &bl[k];
      pb[4 * k + 3].buffer_type = MYSQL_TYPE_DOUBLE; pb[4 * k + 3].buffer = &cs[k];
    }
    mysql_stmt_bind_param(s, pb);
    for (int start = 1; start <= T6_ROWS; start += T6_BATCH) {
      for (int k = 0; k < T6_BATCH; k++) {
        int i = start + k; ids[k] = i; as[k] = i * 3; cs[k] = i * 0.5; row_b(i, bs[k]); bl[k] = strlen(bs[k]);
      }
      if (mysql_stmt_execute(s)) b_die("%s", mysql_stmt_error(s));
    }
    mysql_stmt_close(s); free(sql); free(pb); free(ids); free(as); free(cs); free(bs); free(bl);
  } else { /* batch: MariaDB array binding (COM_STMT_BULK_EXECUTE on MariaDB servers) */
#if IS_MARIADB
    MYSQL_STMT *s = prep(g_m, "INSERT INTO t_bulk (id,a,b,c) VALUES (?,?,?,?)");
    unsigned int asize = T6_BATCH;
    mysql_stmt_attr_set(s, STMT_ATTR_ARRAY_SIZE, &asize);
    int *ids = calloc(T6_BATCH, sizeof *ids), *as = calloc(T6_BATCH, sizeof *as);
    double *cs = calloc(T6_BATCH, sizeof *cs);
    char **bp = calloc(T6_BATCH, sizeof *bp); char (*bs)[32] = calloc(T6_BATCH, 32);
    unsigned long *bl = calloc(T6_BATCH, sizeof *bl);
    MYSQL_BIND pb[4]; memset(pb, 0, sizeof pb);
    pb[0].buffer_type = MYSQL_TYPE_LONG; pb[0].buffer = ids;
    pb[1].buffer_type = MYSQL_TYPE_LONG; pb[1].buffer = as;
    pb[2].buffer_type = MYSQL_TYPE_STRING; pb[2].buffer = bp; pb[2].length = bl;
    pb[3].buffer_type = MYSQL_TYPE_DOUBLE; pb[3].buffer = cs;
    for (int k = 0; k < T6_BATCH; k++) bp[k] = bs[k];
    mysql_stmt_bind_param(s, pb);
    for (int start = 1; start <= T6_ROWS; start += T6_BATCH) {
      for (int k = 0; k < T6_BATCH; k++) {
        int i = start + k; ids[k] = i; as[k] = i * 3; cs[k] = i * 0.5; row_b(i, bs[k]); bl[k] = strlen(bs[k]);
      }
      if (mysql_stmt_execute(s)) {
        if (strstr(mysql_stmt_error(s), "Bulk operation")) b_na("server has no bulk execute (MariaDB-only protocol extension)");
        b_die("%s", mysql_stmt_error(s));
      }
    }
    mysql_stmt_close(s); free(ids); free(as); free(cs); free(bp); free(bs); free(bl);
#else
    b_na("libmysqlclient has no array/bulk binding");
#endif
  }
  g_ops = T6_ROWS / T6_BATCH;  /* statements */
  ck[0] = 0;  /* verified on the server after the iteration (see main) */
}

/* ------------------------------------------------------------------ language floor */
static void floor_run(char *ck) {
  /* Same touch loops over in-memory data, no driver. */
  static int *ints; static char **docs; static unsigned long *dl; static int nd;
  long long c = 0;
  if (!strcmp(g_test, "T3")) {
    if (!ints) { ints = malloc(sizeof(int) * 1000000); for (int i = 0; i < 1000000; i++) ints[i] = ((i + 1) * 7919LL) % 1000003; }
    for (int i = 0; i < 1000000; i++) c += ints[i];
    g_ops = 1000000;
  } else if (!strcmp(g_test, "T5")) {
    if (!docs) {
      char cls[16], col[16], sql[128]; sscanf(g_variant, "%15[^-]-%15s", cls, col);
      snprintf(sql, sizeof sql, "SELECT %s FROM t_blob WHERE size_class = '%s' ORDER BY id", col, cls);
      q(g_m, "DO 1");
      if (mysql_query(g_m, sql)) b_die("%s", mysql_error(g_m));
      MYSQL_RES *r = mysql_store_result(g_m); MYSQL_ROW row; nd = mysql_num_rows(r);
      docs = malloc(nd * sizeof *docs); dl = malloc(nd * sizeof *dl);
      for (int i = 0; (row = mysql_fetch_row(r)); i++) { dl[i] = mysql_fetch_lengths(r)[0]; docs[i] = malloc(dl[i]); memcpy(docs[i], row[0], dl[i]); }
      mysql_free_result(r);
    }
    long long bytes = 0;
    for (int rep = 0; rep < 20; rep++) {
      c = 0;
      for (int i = 0; i < nd; i++) {
        const unsigned char *p = (const unsigned char *)docs[i]; c += dl[i]; bytes += dl[i];
        for (unsigned long k = 0; k < dl[i]; k += 64) c += p[k];
      }
    }
    g_ops = bytes / 1024;
  } else b_na("floor implemented for T3 and T5 in C (T4 floor = 0 in C)");
  snprintf(ck, 96, "%lld", c);
}

/* ------------------------------------------------------------------ main */
int main(int argc, char **argv) {
  for (int i = 1; i < argc; i++) {
    const char *a = argv[i], *v = i + 1 < argc ? argv[i + 1] : "";
    if (!strcmp(a, "--test")) g_test = v, i++;
    else if (!strcmp(a, "--variant")) g_variant = v, i++;
    else if (!strcmp(a, "--config")) g_config = v, i++;
    else if (!strcmp(a, "--server")) g_server = v, i++;
    else if (!strcmp(a, "--warmup")) g_warmup = atoi(v), i++;
    else if (!strcmp(a, "--iters")) g_iters = atoi(v), i++;
    else if (!strcmp(a, "--out")) g_out = v, i++;
    else if (!strcmp(a, "--floor")) g_floor = 1;
    else b_die("unknown arg %s", a);
  }
  if (strcmp(g_config, "default")) b_na("C API has no driver options beyond the explicit variants");
  mysql_library_init(0, NULL, NULL);

  iter_t *its = calloc(g_iters, sizeof *its);
  char extra[512] = "";

  if (!strcmp(g_test, "T0")) {  /* footprint */
    long long rss0 = b_status_kb("VmRSS:");
    b_perf_open(); b_begin();
    g_m = db_connect(tls_mode(), 0, 0); q(g_m, "SELECT 1");
    b_end(&its[0]); record_tls(g_m);
    snprintf(extra, sizeof extra, "\"rss_start_kb\":%lld", rss0);
    strcpy(its[0].checksum, "1");
    b_write(g_out, STACK, mysql_get_client_info(), g_test, g_variant, g_config, g_server, g_tls, 1, 0, its, 1, extra);
    return 0;
  }

  g_m = db_connect(tls_mode(), 0, 0);
  record_tls(g_m);
  if (!strcmp(g_test, "T2")) {
    if (!strcmp(g_variant, "param")) b_na("C API has no client-side parameter binding");
    char path[512]; snprintf(path, sizeof path, "%s/ids_200k.txt", E("DATA_DIR", "/root/bench/data"));
    FILE *f = fopen(path, "r"); if (!f) b_die("open %s", path);
    g_ids = malloc(200000 * sizeof(int)); while (g_nids < 200000 && fscanf(f, "%d", &g_ids[g_nids]) == 1) g_nids++;
    fclose(f);
  }
  if (!strcmp(g_test, "T1") && !strcmp(g_variant, "tls-resume") && IS_MARIADB) b_na("Connector/C has no TLS session resumption API");
  if (!strcmp(g_test, "T1")) {   /* record the cipher of a connection made with the variant's settings */
    mysql_close(g_m);
    int resume = !strcmp(g_variant, "tls-resume");
    int tls = !strcmp(g_variant, "tls") || resume ? TLS_ON : !strcmp(g_variant, "tls-verify") ? TLS_VERIFY : TLS_OFF;
    g_m = db_connect(tls, !strcmp(g_variant, "socket"), resume); record_tls(g_m);
    mysql_close(g_m); g_m = NULL;
  }

  void (*fn)(char *) = g_floor ? floor_run :
      !strcmp(g_test, "T1") ? t1 : !strcmp(g_test, "T2") ? t2 : !strcmp(g_test, "T3") ? t3 :
      !strcmp(g_test, "T4") ? t4 : !strcmp(g_test, "T5") ? t5 : !strcmp(g_test, "T6") ? t6 : NULL;
  if (!fn) b_die("unknown test %s", g_test);

  b_perf_open();
  iter_t scratch;
  for (int i = 0; i < g_warmup + g_iters; i++) {
    iter_t *it = i < g_warmup ? &scratch : &its[i - g_warmup];
    if (!strcmp(g_test, "T6")) q(g_m, "TRUNCATE TABLE t_bulk");
    if (i < g_warmup) { char ck[96]; fn(ck); continue; }
    b_begin(); fn(it->checksum); b_end(it);
    if (!strcmp(g_test, "T6") && !g_floor) {
      if (mysql_query(g_m, "SELECT COUNT(*), SUM(a), SUM(CHAR_LENGTH(b)) FROM t_bulk")) b_die("%s", mysql_error(g_m));
      MYSQL_RES *r = mysql_store_result(g_m); MYSQL_ROW row = mysql_fetch_row(r);
      snprintf(it->checksum, sizeof it->checksum, "%s:%s:%s", row[0], row[1], row[2]); mysql_free_result(r);
    }
  }
  b_write(g_out, STACK, mysql_get_client_info(), g_test, g_variant, g_config, g_server, g_tls, g_ops, g_warmup,
          its, g_iters, extra);
  if (g_m) mysql_close(g_m);
  return 0;
}
