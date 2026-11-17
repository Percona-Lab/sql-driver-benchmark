package main

// Go runner: go-sql-driver/mysql (via database/sql) and go-mysql-org/go-mysql client.
// Same CLI/env contract as the other runners (SPEC.md section 5).

import (
	"bufio"
	"crypto/tls"
	"crypto/x509"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

type Driver interface {
	Name() string
	Lib() string
	Open(tlsMode string) error // control connection
	Cipher() string
	Connect(tlsMode string, sock bool) (func() error, error) // T1: returns close func
	T2(variant string, ids []int) (int64, error)
	T3(variant string) (int64, error)
	T4(variant string) (int64, int, error) // checksum, rows
	T5(sql string, fn func(v []byte, s string, isStr bool)) error
	T6(variant string) error
	Exec(sql string) error
	Verify6() (string, error)
	Close()
}

var (
	fTest, fVariant, fConfig, fServer, fOut, fDriver string
	fWarmup, fIters                                  int
	fFloor                                           bool
	sessCache                                        = tls.NewLRUClientSessionCache(64)
)

// tlsConfig: "off" -> nil, "on" -> no verification, "verify" -> CA + hostname.
func tlsConfig(mode string, resume bool) *tls.Config {
	switch mode {
	case "off":
		return nil
	case "on":
		c := &tls.Config{InsecureSkipVerify: true}
		if resume {
			c.ClientSessionCache = sessCache
		}
		return c
	}
	pem, err := os.ReadFile(env("DB_CA", ""))
	if err != nil {
		panic(err)
	}
	pool := x509.NewCertPool()
	pool.AppendCertsFromPEM(pem)
	c := &tls.Config{RootCAs: pool, ServerName: "localhost"}
	if resume {
		c.ClientSessionCache = sessCache
	}
	return c
}

func t1Mode() (string, bool) {
	resume := strings.Contains(fVariant, "resume")
	switch {
	case strings.HasPrefix(fVariant, "tls-verify"):
		return "verify", resume
	case strings.HasPrefix(fVariant, "tls"):
		return "on", resume
	}
	return "off", false
}

func main() {
	flag.StringVar(&fDriver, "driver", "go-sql-driver", "")
	flag.StringVar(&fTest, "test", "T0", "")
	flag.StringVar(&fVariant, "variant", "", "")
	flag.StringVar(&fConfig, "config", "default", "")
	flag.StringVar(&fServer, "server", "ps", "")
	flag.StringVar(&fOut, "out", "", "")
	flag.IntVar(&fWarmup, "warmup", 2, "")
	flag.IntVar(&fIters, "iters", 5, "")
	flag.BoolVar(&fFloor, "floor", false, "")
	flag.Parse()
	rssStart := statusKB("VmRSS:")
	if err := run(rssStart); err != nil {
		if why, ok := isNA(err); ok {
			fmt.Fprintln(os.Stderr, "n/a: "+why)
			os.Exit(3)
		}
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run(rssStart int64) error {
	var d Driver
	switch fDriver {
	case "go-sql-driver":
		d = &SQLDriver{tuned: fConfig == "tuned"}
	case "go-mysql":
		if fConfig != "default" {
			return na("go-mysql has no driver options to tune")
		}
		d = &GoMySQL{}
	default:
		return fmt.Errorf("unknown driver %s", fDriver)
	}
	meta := map[string]any{"stack": d.Name(), "lib": d.Lib(), "test": fTest, "variant": fVariant, "config": fConfig,
		"server": fServer}
	tlsMode := env("DB_TLS", "off")

	if fTest == "T0" {
		perfOpen()
		var m meter
		m.begin()
		if err := d.Open(tlsMode); err != nil {
			return err
		}
		if err := d.Exec("SELECT 1"); err != nil {
			return err
		}
		r := m.end("1")
		meta["tls"], meta["ops_per_iter"], meta["warmup"], meta["rss_start_kb"] = d.Cipher(), 1, 0, rssStart
		writeResult(fOut, meta, []IterRec{r})
		return nil
	}
	if fTest == "T1" {
		mode, _ := t1Mode()
		closeFn, err := d.Connect(mode, fVariant == "socket")
		if err != nil {
			return err
		}
		closeFn()
		// cipher of a variant-style connection, via a control connection opened the same way
		if err := d.Open(mode); err != nil {
			return err
		}
		meta["tls"] = d.Cipher()
		d.Close()
	}
	if err := d.Open(tlsMode); err != nil {
		return err
	}
	if fTest != "T1" {
		meta["tls"] = d.Cipher()
	}
	var ids []int
	if fTest == "T2" {
		f, err := os.Open(filepath.Join(env("DATA_DIR", "/root/bench/data"), "ids_200k.txt"))
		if err != nil {
			return err
		}
		sc := bufio.NewScanner(f)
		for sc.Scan() {
			v, _ := strconv.Atoi(sc.Text())
			ids = append(ids, v)
		}
		f.Close()
	}

	var ops int64
	var floorData any
	step := func() (string, error) {
		if fFloor {
			return floor(d, &floorData, &ops)
		}
		switch fTest {
		case "T1":
			mode, resume := t1Mode()
			n := 2000
			if mode == "off" {
				n = 10000
			}
			if resume && strings.HasPrefix(fVariant, "tls") {
				_ = resume // session cache is set in tlsConfig via the variant name
			}
			for i := 0; i < n; i++ {
				c, err := d.Connect(mode, fVariant == "socket")
				if err != nil {
					return "", err
				}
				c()
			}
			ops = int64(n)
			return strconv.Itoa(n), nil
		case "T2":
			s, err := d.T2(fVariant, ids)
			ops = int64(len(ids))
			return strconv.FormatInt(s, 10), err
		case "T3":
			s, err := d.T3(fVariant)
			ops = 1000000
			return strconv.FormatInt(s, 10), err
		case "T4":
			ck, rows, err := d.T4(fVariant)
			ops = int64(rows) * 100
			return strconv.FormatInt(ck, 10), err
		case "T5":
			sql, parse := t5SQL()
			var ck, bytes int64
			for rep := 0; rep < 20; rep++ {
				ck = 0
				var perr error
				err := d.T5(sql, func(v []byte, s string, isStr bool) {
					if isStr {
						ck += touchStr(s)
						bytes += int64(len(s))
						if parse {
							perr = parseJSON([]byte(s))
						}
					} else {
						ck += touch(v)
						bytes += int64(len(v))
						if parse {
							perr = parseJSON(v)
						}
					}
				})
				if err != nil {
					return "", err
				}
				if perr != nil {
					return "", perr
				}
			}
			ops = bytes / 1024
			return strconv.FormatInt(ck, 10), nil
		case "T6":
			ops = 1000
			return "", d.T6(fVariant)
		}
		return "", fmt.Errorf("unknown test %s", fTest)
	}

	perfOpen()
	var iters []IterRec
	for i := 0; i < fWarmup+fIters; i++ {
		if fTest == "T6" {
			if err := d.Exec("TRUNCATE TABLE t_bulk"); err != nil {
				return err
			}
		}
		if i < fWarmup {
			if _, err := step(); err != nil {
				return err
			}
			continue
		}
		var m meter
		m.begin()
		ck, err := step()
		r := m.end(ck)
		if err != nil {
			return err
		}
		if fTest == "T6" && !fFloor {
			if r.Checksum, err = d.Verify6(); err != nil {
				return err
			}
		}
		iters = append(iters, r)
	}
	meta["ops_per_iter"], meta["warmup"] = ops, fWarmup
	writeResult(fOut, meta, iters)
	d.Close()
	return nil
}

func t5SQL() (string, bool) {
	cls, col, _ := strings.Cut(fVariant, "-")
	parse := strings.HasSuffix(col, "-parse")
	col = strings.TrimSuffix(col, "-parse")
	return fmt.Sprintf("SELECT %s FROM t_blob WHERE size_class = '%s' ORDER BY id", col, cls), parse
}

// floor: the same touch loops over in-memory data (T3, T5)
func floor(d Driver, data *any, ops *int64) (string, error) {
	switch fTest {
	case "T3":
		if *data == nil {
			v := make([]int64, 1000000)
			for i := range v {
				v[i] = int64((i + 1) * 7919 % 1000003)
			}
			*data = v
		}
		var s int64
		for _, x := range (*data).([]int64) {
			s += x
		}
		*ops = 1000000
		return strconv.FormatInt(s, 10), nil
	case "T5":
		if *data == nil {
			var docs [][]byte
			sql, _ := t5SQL()
			d.T5(sql, func(v []byte, s string, isStr bool) {
				if isStr {
					docs = append(docs, []byte(s))
				} else {
					docs = append(docs, append([]byte(nil), v...))
				}
			})
			*data = docs
		}
		var ck, b int64
		for rep := 0; rep < 20; rep++ {
			ck = 0
			for _, v := range (*data).([][]byte) {
				ck += touch(v)
				b += int64(len(v))
			}
		}
		*ops = b / 1024
		return strconv.FormatInt(ck, 10), nil
	}
	return "", na("floor defined for T3 and T5 in Go")
}
