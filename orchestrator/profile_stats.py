#!/usr/bin/env python3
"""Stack-level shares quoted in reports/profiles.md, computed from the folded stacks (results/raw-prof, in the
release archive), saved to results/profile-stats.json for build_profiles.py. usage: profile_stats.py results/raw-prof"""
import re, sys

R = (sys.argv[1] if len(sys.argv) > 1 else "results/raw-prof") + "/ps/"


def share(path, pred, leaf_only=False):
    tot = hit = 0
    for line in open(path):
        st, _, n = line.rstrip("\n").rpartition(" ")
        n = int(n); tot += n
        if pred(st.split(";")[-1] if leaf_only else st):
            hit += n
    return 100 * hit / tot


def rng(vals):
    return f"{min(vals):.0f}–{max(vals):.0f}%"


C_TLS = ["c-libmysqlclient", "c-mariadb-connc", "php-mysqli", "py-mysqlclient", "rb-mysql2"]
t1 = lambda s: R + s + "/T1-tls-verify-default-0.folded"
out = {
    "ssl_ctx_new": rng([share(t1(s), lambda st: "SSL_CTX_new" in st) for s in C_TLS]),
    "ca_load": rng([share(t1(s), lambda st: re.search(r"X509_STORE_load|X509_load_cert|load_locations|PEM_X509_INFO|SSL_CTX_load_verify", st) is not None) for s in C_TLS]),
    "cipher_list": "up to " + rng([share(t1(s), lambda st: re.search(r"ssl_create_cipher_list|SSL_CTX_set_cipher_list|set_ciphersuites", st) is not None) for s in C_TLS]).split("–")[1],
    "cj_sslcontext": f"{share(t1('java-connector-j'), lambda st: 'SslContextBuilder.build' in st):.0f}%",
    "go_sql_locks": f"{share(R + 'go-sql-driver/T3-text-streamed-default-0.folded', lambda leaf: re.search(r'CompareAndSwap|Mutex', leaf) is not None, leaf_only=True):.0f}%",
    "go_mysql_pool": f"{share(R + 'go-mysql/T3-text-streamed-default-0.folded', lambda st: 'BytesBufferGet' in st):.0f}%",
    "netfilter": rng([share(R + s + "/T2-literal-default-0.folded", lambda st: "nft_do_chain" in st) for s in ["c-libmysqlclient", "go-sql-driver", "java-connector-j", "py-mysqlclient"]]),
    "rb_mysql2_mutex": f"{share(R + 'rb-mysql2/T3-text-buffered-default-0.folded', lambda leaf: re.search(r'pthread_mutex|lll_mutex|thread_sched|rb_nogvl', leaf) is not None, leaf_only=True):.0f}%",
}
import json
json.dump(out, open('results/profile-stats.json', 'w'), indent=1, ensure_ascii=False)
print(out)
