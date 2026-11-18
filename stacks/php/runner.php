<?php
// PHP runner: mysqli and PDO_MySQL (both on mysqlnd). Same CLI/env contract as the other runners.
// default config: the idioms most code uses (fetch_assoc / PDO::FETCH_BOTH, strings from the text protocol)
// tuned config:   numeric arrays + native int/float types (MYSQLI_OPT_INT_AND_FLOAT_NATIVE / PDO::FETCH_NUM)
error_reporting(E_ALL & ~E_DEPRECATED);
$rssStart = statusKb("VmRSS:");
$A = ["driver" => "mysqli", "test" => "T0", "variant" => "", "config" => "default", "server" => "ps", "out" => null,
      "warmup" => 2, "iters" => 5, "floor" => false];
for ($i = 1; $i < $argc; $i++) {
    $k = substr($argv[$i], 2);
    if ($k === "floor") $A["floor"] = true; else $A[$k] = $argv[++$i];
}
$V = $A["variant"]; $TUNED = $A["config"] === "tuned";
class NA extends Exception {}
function E($k, $d = null) { $v = getenv($k); return $v === false || $v === "" ? $d : $v; }

// ------------------------------------------------------------------ harness
function statusKb($key) {
    foreach (file("/proc/self/status") as $l) if (str_starts_with($l, $key)) return (int)preg_split('/\s+/', $l)[1];
    return -1;
}
function srvTicks() {
    $pid = getenv("MYSQLD_PID"); if (!$pid) return -1;
    $s = @file_get_contents("/proc/$pid/stat"); if ($s === false) return -1;
    $f = explode(" ", substr($s, strrpos($s, ")") + 2));
    return (int)$f[11] + (int)$f[12];
}
$CTL = $ACK = null;
function perfOpen() { global $CTL, $ACK; if (getenv("PERF_CTL") && getenv("PERF_ACK")) { $CTL = fopen(getenv("PERF_CTL"), "w"); $ACK = fopen(getenv("PERF_ACK"), "r"); } }
function perf($cmd) { global $CTL, $ACK; if (!$CTL) return; fwrite($CTL, $cmd); fflush($CTL); fread($ACK, 8); }
function cpuNs() { $r = getrusage(); return ($r["ru_utime.tv_sec"] + $r["ru_stime.tv_sec"]) * 1000000000 + ($r["ru_utime.tv_usec"] + $r["ru_stime.tv_usec"]) * 1000; }
class Meter {
    function begin() { file_put_contents("/proc/self/clear_refs", "5"); $this->gc = gc_status()["runs"]; $this->srv = srvTicks(); perf("enable\n"); $this->wall = hrtime(true); $this->cpu = cpuNs(); }
    function end($ck) {
        $cpu = cpuNs(); $wall = hrtime(true); perf("disable\n"); $s = srvTicks();
        return ["cpu_ns" => $cpu - $this->cpu, "wall_ns" => $wall - $this->wall, "srv_ticks" => ($s >= 0 && $this->srv >= 0) ? $s - $this->srv : -1,
                "rss_peak_kb" => statusKb("VmHWM:"), "rss_end_kb" => statusKb("VmRSS:"), "checksum" => (string)$ck,
                "gc_count" => gc_status()["runs"] - $this->gc, "php_mem_peak" => memory_get_peak_usage()];
    }
}

// ------------------------------------------------------------------ adapters
const INT_T = [1, 2, 3, 8, 9]; const STR_T = [15, 253, 254];
const PDO_INT = ["TINY", "SHORT", "LONG", "LONGLONG", "INT24"]; const PDO_STR = ["VAR_STRING", "STRING", "VARCHAR"];

class Mysqli_ {
    public $name = "php-mysqli";
    function lib() { return "mysqli/mysqlnd " . mysqli_get_client_info() . " (PHP " . PHP_VERSION . ")"; }
    function connect($tls = "off", $sock = false) {
        global $TUNED;
        $m = mysqli_init();
        if ($TUNED) $m->options(MYSQLI_OPT_INT_AND_FLOAT_NATIVE, 1);
        $flags = 0;
        if ($tls === "on") { $flags = MYSQLI_CLIENT_SSL | MYSQLI_CLIENT_SSL_DONT_VERIFY_SERVER_CERT; }
        elseif ($tls === "verify") { $m->ssl_set(null, null, E("DB_CA"), null, null); $flags = MYSQLI_CLIENT_SSL; $m->options(MYSQLI_OPT_SSL_VERIFY_SERVER_CERT, true); }
        $m->real_connect($sock ? "localhost" : E("DB_HOST", "127.0.0.1"), E("DB_USER", "bench"), E("DB_PASS", "bench"), E("DB_NAME", "bench"),
            (int)E("DB_PORT", "3306"), $sock ? E("DB_SOCKET") : null, $flags);
        return $m;
    }
    function close($c) { $c->close(); }
    function exec($c, $sql) { $c->query($sql); }
    function rows($c, $sql, $streamed = false, $binary = false) {  // returns [iterable rows (numeric arrays), column types]
        global $TUNED;
        if ($binary) {
            $st = $c->prepare($sql); $st->execute();
            if ($streamed) {  // unbuffered binary: bind_result + fetch
                $meta = $st->result_metadata(); $types = array_map(fn($f) => $f->type, $meta->fetch_fields());
                $row = array_fill(0, count($types), null); $refs = []; foreach ($row as $k => &$v) $refs[] = &$v;
                $st->bind_result(...$refs);
                $gen = (function () use ($st, &$row) { while ($st->fetch()) yield array_values($row); $st->close(); })();
                return [$gen, $types];
            }
            $r = $st->get_result();
        } else $r = $c->query($sql, $streamed ? MYSQLI_USE_RESULT : MYSQLI_STORE_RESULT);
        $types = array_map(fn($f) => $f->type, $r->fetch_fields());
        $gen = $TUNED ? (function () use ($r) { while ($x = $r->fetch_row()) yield $x; $r->free(); })()
                      : (function () use ($r) { while ($x = $r->fetch_assoc()) yield array_values($x); $r->free(); })();
        return [$gen, $types];
    }
    function intType($t) { return in_array($t, INT_T, true); }
    function strType($t) { return in_array($t, STR_T, true); }
    function lookup($c, $variant, $ids) {
        $s = 0;
        if ($variant === "literal") { foreach ($ids as $id) $s += (int)$c->query("SELECT v FROM t_int WHERE id = $id")->fetch_row()[0]; }
        elseif ($variant === "param") {  // mysqli has no client-side parameters: execute_query = prepare+execute+close
            foreach ($ids as $id) $s += (int)$c->execute_query("SELECT v FROM t_int WHERE id = ?", [$id])->fetch_row()[0];
        } else {
            $st = $c->prepare("SELECT v FROM t_int WHERE id = ?"); $p = 0; $v = 0;
            $st->bind_param("i", $p); $st->bind_result($v);   // bound by reference: assign, don't rebind via foreach
            foreach ($ids as $id) { $p = $id; $st->execute(); $st->fetch(); $s += $v; $st->free_result(); }
            $st->close();
        }
        return $s;
    }
    function escape($c, $s) { return "'" . $c->real_escape_string($s) . "'"; }
    function multiparam($c, $sql, $paramsFn) {
        $st = $c->prepare($sql);
        for ($start = 1; $start <= 1000000; $start += 1000) $st->execute($paramsFn($start));
        $st->close();
    }
    function batch($c) { throw new NA("mysqli has no batch API"); }
    function cipher($c) { $r = $c->query("SHOW SESSION STATUS LIKE 'Ssl_cipher'")->fetch_row(); return $r && $r[1] ? $r[1] : "none"; }
}

class Pdo_ {
    public $name = "php-pdo-mysql";
    function lib() { return "PDO_MySQL/mysqlnd " . (new ReflectionExtension("pdo_mysql"))->getVersion() . " (PHP " . PHP_VERSION . ")"; }
    function connect($tls = "off", $sock = false, $emulate = true) {
        global $TUNED, $V;
        $dsn = $sock ? "mysql:unix_socket=" . E("DB_SOCKET") . ";dbname=" . E("DB_NAME", "bench")
                     : "mysql:host=" . E("DB_HOST", "127.0.0.1") . ";port=" . E("DB_PORT", "3306") . ";dbname=" . E("DB_NAME", "bench");
        $M = class_exists("Pdo\\Mysql") ? "Pdo\\Mysql::" : "PDO::MYSQL_";
        $o = [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
              PDO::ATTR_EMULATE_PREPARES => !($V === "prepared" || str_starts_with($V, "binary") || str_ends_with($V, "binary"))];
        if ($TUNED) $o[PDO::ATTR_DEFAULT_FETCH_MODE] = PDO::FETCH_NUM;
        if ($tls !== "off") {  // PDO enables TLS only when an SSL option is set: the CA is passed in both modes
            $o[constant($M . "ATTR_SSL_CA")] = E("DB_CA");
            $o[constant($M . "ATTR_SSL_VERIFY_SERVER_CERT")] = $tls === "verify";
        }
        return new PDO($dsn, E("DB_USER", "bench"), E("DB_PASS", "bench"), $o);
    }
    function close($c) { $c = null; }
    function exec($c, $sql) { $c->query($sql)->fetchAll(); }   // consume any result so the connection stays usable
    function rows($c, $sql, $streamed = false, $binary = false) {
        global $TUNED;
        $M = class_exists("Pdo\\Mysql") ? "Pdo\\Mysql::" : "PDO::MYSQL_";
        $c->setAttribute(constant($M . "ATTR_USE_BUFFERED_QUERY"), !$streamed);
        $st = $binary ? $c->prepare($sql) : null;
        if ($binary) $st->execute(); else $st = $c->query($sql);
        $types = []; for ($i = 0; $i < $st->columnCount(); $i++) $types[] = $st->getColumnMeta($i)["native_type"] ?? "";
        $gen = $TUNED ? (function () use ($st, $c, $M) { while ($x = $st->fetch()) yield $x; $st->closeCursor(); $c->setAttribute(constant($M . "ATTR_USE_BUFFERED_QUERY"), true); })()
                      : (function () use ($st, $c, $M) {  // FETCH_BOTH (PDO default): use the numeric half
                            while ($x = $st->fetch()) { $n = []; foreach ($x as $k => $v) if (is_int($k)) $n[] = $v; yield $n; }
                            $st->closeCursor(); $c->setAttribute(constant($M . "ATTR_USE_BUFFERED_QUERY"), true); })();
        return [$gen, $types];
    }
    function intType($t) { return in_array($t, PDO_INT, true); }
    function strType($t) { return in_array($t, PDO_STR, true); }
    function lookup($c, $variant, $ids) {
        $s = 0;
        if ($variant === "literal") { foreach ($ids as $id) $s += (int)$c->query("SELECT v FROM t_int WHERE id = $id")->fetch()[0]; }
        else {  // param: emulated (client-side) prepare; prepared: real server-side prepare (connection opened without emulation)
            $st = $c->prepare("SELECT v FROM t_int WHERE id = ?");
            foreach ($ids as $id) { $st->execute([$id]); $s += (int)$st->fetch()[0]; $st->closeCursor(); }
        }
        return $s;
    }
    function escape($c, $s) { return $c->quote($s); }
    function multiparam($c, $sql, $paramsFn) {
        $st = $c->prepare($sql);
        for ($start = 1; $start <= 1000000; $start += 1000) $st->execute($paramsFn($start));
    }
    function batch($c) { throw new NA("PDO has no batch API"); }
    function cipher($c) { $r = $c->query("SHOW SESSION STATUS LIKE 'Ssl_cipher'")->fetch(PDO::FETCH_NUM); return $r && $r[1] ? $r[1] : "none"; }
}

$D = $A["driver"] === "pdo" ? new Pdo_() : new Mysqli_();
$ops = 0;

// ------------------------------------------------------------------ tests
function t1mode() { global $V; return str_starts_with($V, "tls-verify") ? "verify" : (str_starts_with($V, "tls") ? "on" : "off"); }
function t1($c) { global $D, $V, $ops; $tls = t1mode(); $n = $tls === "off" ? 5000 : 2000;
    for ($i = 0; $i < $n; $i++) $D->close($D->connect($tls, $V === "socket")); $ops = $n; return $n; }
function t2($c) { global $D, $V, $ops, $IDS; $ops = count($IDS); return $D->lookup($c, $V, $IDS); }
function t3($c) { global $D, $V, $ops; [$rows] = $D->rows($c, "SELECT v FROM t_int", str_contains($V, "streamed"), str_starts_with($V, "binary"));
    $s = 0; foreach ($rows as $r) $s += (int)$r[0]; $ops = 1000000; return $s; }
function t4($c) {
    global $D, $V, $ops;
    [$rows, $types] = $D->rows($c, str_starts_with($V, "int") ? "SELECT * FROM t_wide_int" : "SELECT * FROM t_wide_mix", false, str_ends_with($V, "binary"));
    $n = count($types); $isInt = []; $isStr = [];
    for ($i = 0; $i < $n; $i++) { $isInt[$i] = $D->intType($types[$i]); $isStr[$i] = $D->strType($types[$i]); }
    $nn = $isum = $slen = $cnt = 0;
    foreach ($rows as $r) {
        $cnt++;
        for ($i = 1; $i < $n; $i++) {
            $v = $r[$i]; if ($v === null) continue; $nn++;
            if ($isInt[$i]) $isum += (int)$v; elseif ($isStr[$i]) $slen += strlen($v);
        }
    }
    $ops = $cnt * 100; return $nn + $isum + $slen;
}
function touch_($v) { $n = strlen($v); $c = $n; for ($i = 0; $i < $n; $i += 64) $c += ord($v[$i]); return $c; }
function t5sql() { global $V; [$cls, $col] = explode("-", $V, 2); $parse = str_ends_with($col, "-parse");
    $col = preg_replace('/-parse$/', "", $col); return ["SELECT $col FROM t_blob WHERE size_class = '$cls' ORDER BY id", $parse]; }
function t5($c) {
    global $D, $ops; [$sql, $parse] = t5sql(); $ck = $bytes = 0;
    for ($rep = 0; $rep < 20; $rep++) {
        $ck = 0; [$rows] = $D->rows($c, $sql);
        foreach ($rows as $r) { $v = $r[0]; $ck += touch_($v); $bytes += strlen($v); if ($parse) json_decode($v); }
    }
    $ops = intdiv($bytes, 1024); return $ck;
}
function rowB($i) { return ($i % 10 === 0 ? "o'k-" : "name-") . $i; }
function t6($c) {
    global $D, $V, $ops;
    if ($V === "sqltext") {
        for ($start = 1; $start <= 1000000; $start += 1000) {
            $p = [];
            for ($i = $start; $i < $start + 1000; $i++) $p[] = "($i," . ($i * 3) . "," . $D->escape($c, rowB($i)) . "," . ($i * 0.5) . ")";
            $D->exec($c, "INSERT INTO t_bulk (id,a,b,c) VALUES " . implode(",", $p));
        }
    } elseif ($V === "multiparam") {
        $sql = "INSERT INTO t_bulk (id,a,b,c) VALUES " . implode(",", array_fill(0, 1000, "(?,?,?,?)"));
        $D->multiparam($c, $sql, function ($start) { $p = []; for ($i = $start; $i < $start + 1000; $i++) array_push($p, $i, $i * 3, rowB($i), $i * 0.5); return $p; });
    } else $D->batch($c);
    $ops = 1000; return "";
}
$FLOOR = null;
function floor_($c) {
    global $A, $D, $ops, $FLOOR;
    if ($A["test"] === "T3") { $FLOOR ??= array_map(fn($i) => [(($i + 1) * 7919) % 1000003], range(0, 999999));
        $s = 0; foreach ($FLOOR as $r) $s += $r[0]; $ops = 1000000; return $s; }
    if ($A["test"] === "T5") { if ($FLOOR === null) { [$rows] = $D->rows($c, t5sql()[0]); $FLOOR = []; foreach ($rows as $r) $FLOOR[] = $r[0]; }
        $ck = $b = 0; for ($rep = 0; $rep < 20; $rep++) { $ck = 0; foreach ($FLOOR as $v) { $ck += touch_($v); $b += strlen($v); } }
        $ops = intdiv($b, 1024); return $ck; }
    throw new NA("floor defined for T3 and T5 in PHP");
}

// ------------------------------------------------------------------ main
function main() {
    global $A, $D, $V, $IDS, $ops, $rssStart;
    $meta = ["stack" => $D->name, "lib" => $D->lib(), "test" => $A["test"], "variant" => $V, "config" => $A["config"], "server" => $A["server"]];
    $write = function ($iters) use (&$meta, $A) { $s = json_encode($meta + ["iters" => $iters]); if ($A["out"]) file_put_contents($A["out"], $s); else echo $s, "\n"; };
    if ($A["test"] === "T1" && str_contains($V, "resume")) throw new NA("PHP drivers expose no TLS session resumption control");
    if ($A["test"] === "T0") {
        perfOpen(); $m = new Meter(); $m->begin(); $c = $D->connect(E("DB_TLS", "off")); $D->exec($c, "SELECT 1");
        $r = $m->end(1); $meta += ["tls" => $D->cipher($c), "ops_per_iter" => 1, "warmup" => 0, "rss_start_kb" => $rssStart]; $write([$r]); return;
    }
    if ($A["test"] === "T1") { $c2 = $D->connect(t1mode(), $V === "socket"); $meta["tls"] = $D->cipher($c2); $D->close($c2); }
    $c = $D->connect(E("DB_TLS", "off"));
    if ($A["test"] !== "T1") $meta["tls"] = $D->cipher($c);
    if ($A["test"] === "T2") $IDS = array_map("intval", file(E("DATA_DIR", "/root/bench/data") . "/ids_200k.txt", FILE_IGNORE_NEW_LINES));
    $fn = $A["floor"] ? "floor_" : ["T1" => "t1", "T2" => "t2", "T3" => "t3", "T4" => "t4", "T5" => "t5", "T6" => "t6"][$A["test"]];
    perfOpen(); $iters = [];
    for ($i = 0; $i < $A["warmup"] + $A["iters"]; $i++) {
        if ($A["test"] === "T6") $D->exec($c, "TRUNCATE TABLE t_bulk");
        if ($i < $A["warmup"]) { $fn($c); continue; }
        $m = new Meter(); $m->begin(); $ck = $fn($c); $r = $m->end($ck);
        if ($A["test"] === "T6" && !$A["floor"]) {
            [$rows] = $D->rows($c, "SELECT COUNT(*), SUM(a), SUM(CHAR_LENGTH(b)) FROM t_bulk");
            foreach ($rows as $x) $r["checksum"] = implode(":", array_map(fn($v) => (string)(int)$v, $x));
        }
        $iters[] = $r;
    }
    $meta += ["ops_per_iter" => $ops, "warmup" => (int)$A["warmup"]]; $write($iters);
}
try { main(); }
catch (NA $e) { fwrite(STDERR, "n/a: " . $e->getMessage() . "\n"); exit(3); }
catch (Throwable $e) { fwrite(STDERR, get_class($e) . ": " . $e->getMessage() . "\n"); exit(1); }
