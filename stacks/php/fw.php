<?php
// Phase 3 runner: PHP frameworks on PDO_MySQL (the driver measured as php-pdo-mysql).
//   dbal      Doctrine DBAL 4 (query builder / Connection API)
//   doctrine  Doctrine ORM 3 (entities, EntityManager, DQL)
//   eloquent  Laravel Eloquent (illuminate/database standalone)
// default = the idiom most code uses; tuned = the framework's lighter path (plain arrays / query builder instead of entities).
error_reporting(E_ALL & ~E_DEPRECATED & ~E_USER_DEPRECATED);
$rssStart = (function () { foreach (file("/proc/self/status") as $l) if (str_starts_with($l, "VmRSS:")) return (int)preg_split('/\s+/', $l)[1]; })();
require __DIR__ . "/vendor/autoload.php";
foreach (glob(__DIR__ . "/entities/*.php") as $f) require_once $f;

$A = ["fw" => "dbal", "test" => "T0", "variant" => "", "config" => "default", "server" => "ps", "out" => null, "warmup" => 2, "iters" => 5];
for ($i = 1; $i < $argc; $i++) { $k = substr($argv[$i], 2); if ($k === "floor") continue; $A[$k] = $argv[++$i]; }
$V = $A["variant"]; $TUNED = $A["config"] === "tuned";
class NA extends Exception {}
function E($k, $d = null) { $v = getenv($k); return $v === false || $v === "" ? $d : $v; }

// ------------------------------------------------------------------ harness (as runner.php)
function statusKb($key) { foreach (file("/proc/self/status") as $l) if (str_starts_with($l, $key)) return (int)preg_split('/\s+/', $l)[1]; return -1; }
function srvTicks() { $pid = getenv("MYSQLD_PID"); if (!$pid) return -1; $s = @file_get_contents("/proc/$pid/stat"); if ($s === false) return -1;
    $f = explode(" ", substr($s, strrpos($s, ")") + 2)); return (int)$f[11] + (int)$f[12]; }
$CTL = $ACK = null;
function perfOpen() { global $CTL, $ACK; if (getenv("PERF_CTL") && getenv("PERF_ACK")) { $CTL = fopen(getenv("PERF_CTL"), "w"); $ACK = fopen(getenv("PERF_ACK"), "r"); } }
function perf($cmd) { global $CTL, $ACK; if (!$CTL) return; fwrite($CTL, $cmd); fflush($CTL); fgets($ACK); }
function cpuNs() { $r = getrusage(); return ($r["ru_utime.tv_sec"] + $r["ru_stime.tv_sec"]) * 1000000000 + ($r["ru_utime.tv_usec"] + $r["ru_stime.tv_usec"]) * 1000; }
class Meter {
    public $rss, $srv, $wall, $cpu;
    function begin() { file_put_contents("/proc/self/clear_refs", "5"); $this->rss = statusKb("VmRSS:"); $this->srv = srvTicks(); perf("enable\n"); $this->wall = hrtime(true); $this->cpu = cpuNs(); }
    function end($ck) { $cpu = cpuNs(); $wall = hrtime(true); perf("disable\n"); $s = srvTicks();
        return ["cpu_ns" => $cpu - $this->cpu, "wall_ns" => $wall - $this->wall, "srv_ticks" => ($s >= 0 && $this->srv >= 0) ? $s - $this->srv : -1,
                "rss_start_kb" => $this->rss, "rss_peak_kb" => statusKb("VmHWM:"), "rss_end_kb" => statusKb("VmRSS:"), "checksum" => (string)$ck]; }
}

// ------------------------------------------------------------------ shared
const TYPES10 = ["int", "bigint", "decimal", "double", "varchar32", "datetime", "date", "tinyint", "varchar255n", "intn"];
function colName($k) { return sprintf("c%03d", $k + 1); }
function touchRow($vals, $intTable, &$acc) {   // $vals: values in column order (after id)
    $k = 0;
    foreach ($vals as $v) {
        if ($v !== null) {
            $acc[0]++; $t = TYPES10[$k % 10];
            if ($intTable || $t === "int" || $t === "bigint" || $t === "tinyint" || $t === "intn") $acc[1] += (int)$v;
            elseif ($t === "varchar32" || $t === "varchar255n") $acc[2] += strlen($v);
        }
        $k++;
    }
}
function touchDoc($v) { if (is_resource($v)) $v = stream_get_contents($v); $n = strlen($v); $c = $n; for ($i = 0; $i < $n; $i += 64) $c += ord($v[$i]); return [$c, $n]; }
function rowB($i) { return ($i % 10 === 0 ? "o'k-" : "name-") . $i; }
function pdoOpts($tls) {
    $M = class_exists("Pdo\\Mysql") ? "Pdo\\Mysql::" : "PDO::MYSQL_"; $o = [];
    if ($tls !== "off") { $o[constant($M . "ATTR_SSL_CA")] = E("DB_CA"); $o[constant($M . "ATTR_SSL_VERIFY_SERVER_CERT")] = $tls === "verify"; }
    return $o;
}

// ------------------------------------------------------------------ Doctrine DBAL
class Dbal {
    public $name = "php-dbal", $c;
    function lib() { return "Doctrine DBAL " . \Composer\InstalledVersions::getPrettyVersion("doctrine/dbal") . " on PDO_MySQL"; }
    function open($tls) {
        $this->c = \Doctrine\DBAL\DriverManager::getConnection(["driver" => "pdo_mysql", "host" => E("DB_HOST", "127.0.0.1"), "port" => (int)E("DB_PORT", "3306"),
            "user" => E("DB_USER", "bench"), "password" => E("DB_PASS", "bench"), "dbname" => E("DB_NAME", "bench"), "driverOptions" => pdoOpts($tls)]);
        $this->c->executeQuery("SELECT 1");
    }
    function raw($sql) { return $this->c->fetchAllNumeric($sql); }
    function t2($ids) {
        global $TUNED; $s = 0;
        if ($TUNED) foreach ($ids as $id) $s += (int)$this->c->fetchOne("SELECT v FROM t_int WHERE id = ?", [$id]);
        else foreach ($ids as $id) $s += (int)$this->c->createQueryBuilder()->select("v")->from("t_int")->where("id = ?")->setParameter(0, $id)->fetchOne();
        return $s;
    }
    function t3($streamed) {
        global $TUNED; $s = 0;
        if ($streamed) { $this->buffered(false); foreach ($this->c->executeQuery("SELECT v FROM t_int")->iterateNumeric() as $r) $s += $r[0]; $this->buffered(true); }
        elseif ($TUNED) foreach ($this->c->fetchFirstColumn("SELECT v FROM t_int") as $v) $s += $v;
        else foreach ($this->c->fetchAllAssociative("SELECT v FROM t_int") as $r) $s += $r["v"];
        return $s;
    }
    function buffered($on) { $M = class_exists("Pdo\\Mysql") ? "Pdo\\Mysql::" : "PDO::MYSQL_";
        $this->c->getNativeConnection()->setAttribute(constant($M . "ATTR_USE_BUFFERED_QUERY"), $on); }
    function t4($intTable) {
        global $TUNED; $sql = "SELECT * FROM " . ($intTable ? "t_wide_int" : "t_wide_mix");
        $rows = $TUNED ? $this->c->fetchAllNumeric($sql) : array_map("array_values", $this->c->fetchAllAssociative($sql));
        return array_map(fn($r) => array_slice($r, 1), $rows);
    }
    function t5($cls, $col) { return $this->c->fetchFirstColumn("SELECT $col FROM t_blob WHERE size_class = ? ORDER BY id", [$cls]); }
    function t6($variant) {
        for ($st = 1; $st <= 1000000; $st += 1000) {
            if ($variant === "batch") {   // DBAL's insert() per row, one transaction per 1,000 rows
                $this->c->beginTransaction();
                for ($i = $st; $i < $st + 1000; $i++) $this->c->insert("t_bulk", ["id" => $i, "a" => $i * 3, "b" => rowB($i), "c" => $i * 0.5]);
                $this->c->commit();
            } else {
                $p = []; for ($i = $st; $i < $st + 1000; $i++) array_push($p, $i, $i * 3, rowB($i), $i * 0.5);
                $this->c->executeStatement("INSERT INTO t_bulk (id,a,b,c) VALUES " . implode(",", array_fill(0, 1000, "(?,?,?,?)")), $p);
            }
        }
    }
}

// ------------------------------------------------------------------ Doctrine ORM
class Doctrine extends Dbal {
    public $name = "php-doctrine-orm", $em;
    function lib() { return "Doctrine ORM " . \Composer\InstalledVersions::getPrettyVersion("doctrine/orm") . " on PDO_MySQL"; }
    function open($tls) {
        parent::open($tls);
        $cache = new \Symfony\Component\Cache\Adapter\ArrayAdapter();
        $cfg = \Doctrine\ORM\ORMSetup::createAttributeMetadataConfig([__DIR__ . "/entities"], false, sys_get_temp_dir() . "/dbbench-proxies", $cache);
        $cfg->enableNativeLazyObjects(true);
        $this->em = new \Doctrine\ORM\EntityManager($this->c, $cfg);
    }
    function t2($ids) {
        global $TUNED; $s = 0;
        if ($TUNED) { $q = $this->em->createQuery("SELECT t.v FROM Bench\\TInt t WHERE t.id = :id"); foreach ($ids as $id) $s += (int)$q->setParameter("id", $id)->getSingleScalarResult(); }
        else foreach ($ids as $id) { $s += $this->em->find(\Bench\TInt::class, $id)->v; $this->em->clear(); }
        return $s;
    }
    function t3($streamed) {
        global $TUNED; $s = 0;
        $q = $this->em->createQuery("SELECT t FROM Bench\\TInt t");
        if ($TUNED) foreach ($this->em->createQuery("SELECT t.v FROM Bench\\TInt t")->getSingleColumnResult() as $v) $s += $v;
        elseif ($streamed) { foreach ($q->toIterable() as $e) { $s += $e->v; } }
        else foreach ($q->getResult() as $e) $s += $e->v;
        $this->em->clear(); return $s;
    }
    function t4($intTable) {
        global $TUNED; $cls = $intTable ? "Bench\\WideInt" : "Bench\\WideMix";
        $q = $this->em->createQuery("SELECT t FROM $cls t");
        if ($TUNED) $rows = array_map(fn($r) => array_slice(array_values($r), 1), $q->getArrayResult());
        else { $rows = []; foreach ($q->getResult() as $e) { $r = []; for ($k = 0; $k < 100; $k++) $r[] = $e->{colName($k)}; $rows[] = $r; } }
        $this->em->clear(); return $rows;
    }
    function t5($cls, $col) {
        return $this->em->createQuery("SELECT b.$col FROM Bench\\TBlob b WHERE b.size_class = :c ORDER BY b.id")->setParameter("c", $cls)->getSingleColumnResult();
    }
    function t6($variant) {
        if ($variant !== "batch") throw new NA("ORM inserts entities (the batch variant)");
        for ($st = 1; $st <= 1000000; $st += 1000) {
            for ($i = $st; $i < $st + 1000; $i++) { $e = new \Bench\TBulk(); $e->id = $i; $e->a = $i * 3; $e->b = rowB($i); $e->c = $i * 0.5; $this->em->persist($e); }
            $this->em->flush(); $this->em->clear();
        }
    }
}

// ------------------------------------------------------------------ Eloquent
class Eloquent {
    public $name = "php-eloquent", $db;
    function lib() { return "Eloquent (illuminate/database " . \Composer\InstalledVersions::getPrettyVersion("illuminate/database") . ") on PDO_MySQL"; }
    function open($tls) {
        $cap = new \Illuminate\Database\Capsule\Manager();
        $cap->addConnection(["driver" => "mysql", "host" => E("DB_HOST", "127.0.0.1"), "port" => E("DB_PORT", "3306"), "database" => E("DB_NAME", "bench"),
            "username" => E("DB_USER", "bench"), "password" => E("DB_PASS", "bench"), "charset" => "utf8mb4", "collation" => "utf8mb4_0900_ai_ci", "options" => pdoOpts($tls)]);
        $cap->setAsGlobal(); $cap->bootEloquent();
        $this->db = $cap->getConnection(); $this->db->select("SELECT 1");
        foreach (["ETInt" => "t_int", "EWideInt" => "t_wide_int", "EWideMix" => "t_wide_mix", "ETBlob" => "t_blob", "ETBulk" => "t_bulk"] as $c => $t)
            if (!class_exists($c)) eval("class $c extends \\Illuminate\\Database\\Eloquent\\Model { protected \$table = '$t'; public \$timestamps = false; public \$incrementing = false; protected \$guarded = []; }");
    }
    function raw($sql) { return array_map(fn($r) => array_values((array)$r), $this->db->select($sql)); }
    function t2($ids) {
        global $TUNED; $s = 0;
        if ($TUNED) foreach ($ids as $id) $s += (int)$this->db->table("t_int")->where("id", $id)->value("v");
        else foreach ($ids as $id) $s += \ETInt::find($id)->v;
        return $s;
    }
    function t3($streamed) {
        global $TUNED; $s = 0;
        if ($streamed) foreach (\ETInt::query()->toBase()->cursor() as $r) $s += $r->v;
        elseif ($TUNED) foreach ($this->db->table("t_int")->pluck("v") as $v) $s += $v;
        else foreach (\ETInt::all() as $e) $s += $e->v;
        return $s;
    }
    function t4($intTable) {
        global $TUNED; $cls = $intTable ? "\\EWideInt" : "\\EWideMix";
        if ($TUNED) return array_map(fn($r) => array_slice(array_values((array)$r), 1), $cls::query()->toBase()->get()->all());
        $rows = []; foreach ($cls::all() as $e) { $r = []; for ($k = 0; $k < 100; $k++) $r[] = $e->{colName($k)}; $rows[] = $r; }
        return $rows;
    }
    function t5($cls, $col) { return $this->db->table("t_blob")->where("size_class", $cls)->orderBy("id")->pluck($col)->all(); }
    function t6($variant) {
        if ($variant !== "batch") throw new NA("Eloquent inserts with insert() on a list (the batch variant)");
        for ($st = 1; $st <= 1000000; $st += 1000) {
            $rows = []; for ($i = $st; $i < $st + 1000; $i++) $rows[] = ["id" => $i, "a" => $i * 3, "b" => rowB($i), "c" => $i * 0.5];
            \ETBulk::insert($rows);   // one multi-row INSERT
        }
    }
}

// ------------------------------------------------------------------ main
function main() {
    global $A, $V, $rssStart;
    $D = ["dbal" => fn() => new Dbal(), "doctrine" => fn() => new Doctrine(), "eloquent" => fn() => new Eloquent()][$A["fw"]]();
    $meta = ["stack" => $D->name, "lib" => $D->lib(), "test" => $A["test"], "variant" => $V, "config" => $A["config"], "server" => $A["server"]];
    $write = function ($iters) use (&$meta, $A) { $s = json_encode($meta + ["iters" => $iters]); if ($A["out"]) file_put_contents($A["out"], $s); else echo $s, "\n"; };
    $cipher = function () use ($D) { $r = $D->raw("SHOW SESSION STATUS LIKE 'Ssl_cipher'"); return $r && $r[0][1] ? $r[0][1] : "none"; };
    if ($A["test"] === "T1") throw new NA("frameworks use the driver's connections (see php-pdo-mysql)");
    if ($A["test"] === "T2" && $V !== "param") throw new NA("frameworks bind parameters themselves (variant: param)");
    if (($A["test"] === "T3" || $A["test"] === "T4") && str_contains($V, "binary")) throw new NA("measured on the text protocol");
    if ($A["test"] === "T6" && $V === "sqltext") throw new NA("app-built SQL text is the driver test");
    if ($A["test"] === "T0") {
        perfOpen(); $m = new Meter(); $m->begin(); $D->open(E("DB_TLS", "off")); $D->raw("SELECT 1"); $r = $m->end(1);
        $meta += ["tls" => $cipher(), "ops_per_iter" => 1, "warmup" => 0, "rss_start_kb" => $rssStart]; $write([$r]); return;
    }
    $D->open(E("DB_TLS", "off"));
    $meta["tls"] = $cipher();
    $ids = $A["test"] === "T2" ? array_map("intval", file(E("DATA_DIR", "/root/bench/data") . "/ids_200k.txt", FILE_IGNORE_NEW_LINES)) : null;
    $ops = 0;
    $fn = match ($A["test"]) {
        "T2" => function () use ($D, $ids, &$ops) { $ops = count($ids); return $D->t2($ids); },
        "T3" => function () use ($D, $V, &$ops) { $ops = 1000000; return $D->t3(str_contains($V, "streamed")); },
        "T4" => function () use ($D, $V, &$ops) { $it = str_starts_with($V, "int"); $rows = $D->t4($it); $acc = [0, 0, 0]; foreach ($rows as $r) touchRow($r, $it, $acc); $ops = count($rows) * 100; return $acc[0] + $acc[1] + $acc[2]; },
        "T5" => function () use ($D, $V, &$ops) { [$cls, $col] = explode("-", $V, 2); if (str_ends_with($col, "-parse")) throw new NA("parse variant measured in the driver runner");
            $b = 0; $ck = 0; for ($rep = 0; $rep < 20; $rep++) { $ck = 0; foreach ($D->t5($cls, $col) as $v) { [$c, $n] = touchDoc($v); $ck += $c; $b += $n; } } $ops = intdiv($b, 1024); return $ck; },
        "T6" => function () use ($D, $V, &$ops) { $D->t6($V); $ops = 1000; return ""; },
    };
    $meta["rss_baseline_kb"] = statusKb("VmRSS:");
    perfOpen(); $iters = [];
    for ($i = 0; $i < $A["warmup"] + $A["iters"]; $i++) {
        if ($A["test"] === "T6") $D->raw("TRUNCATE TABLE t_bulk");
        if ($i < $A["warmup"]) { $fn(); continue; }
        $m = new Meter(); $m->begin(); $ck = $fn(); $r = $m->end($ck);
        if ($A["test"] === "T6") { $x = $D->raw("SELECT COUNT(*), SUM(a), SUM(CHAR_LENGTH(b)) FROM t_bulk")[0]; $r["checksum"] = implode(":", array_map(fn($v) => (string)(int)$v, $x)); }
        $iters[] = $r;
    }
    $meta += ["ops_per_iter" => $ops, "warmup" => (int)$A["warmup"]]; $write($iters);
}
try { main(); }
catch (NA $e) { fwrite(STDERR, "n/a: " . $e->getMessage() . "\n"); exit(3); }
catch (Throwable $e) { fwrite(STDERR, get_class($e) . ": " . $e->getMessage() . "\n"); exit(1); }
