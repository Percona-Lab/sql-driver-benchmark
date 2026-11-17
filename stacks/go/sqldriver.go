package main

// go-sql-driver/mysql through database/sql (the way Go applications use it).

import (
	"context"
	"database/sql"
	"database/sql/driver"
	"encoding/json"
	"fmt"
	"runtime/debug"
	"strconv"
	"strings"
	"time"

	"github.com/go-sql-driver/mysql"
)

var ctx = context.Background()

type SQLDriver struct {
	tuned bool
	db    *sql.DB
	conn  *sql.Conn
}

func (d *SQLDriver) Name() string { return "go-sql-driver" }
func (d *SQLDriver) Lib() string {
	if bi, ok := debug.ReadBuildInfo(); ok {
		for _, m := range bi.Deps {
			if m.Path == "github.com/go-sql-driver/mysql" {
				return "go-sql-driver/mysql " + m.Version + " (" + bi.GoVersion + ")"
			}
		}
	}
	return "go-sql-driver/mysql"
}

var tlsSeq int

func (d *SQLDriver) cfg(tlsMode string, sock bool) *mysql.Config {
	c := mysql.NewConfig()
	c.User, c.Passwd, c.DBName = env("DB_USER", "bench"), env("DB_PASS", "bench"), env("DB_NAME", "bench")
	if sock {
		c.Net, c.Addr = "unix", env("DB_SOCKET", "")
	} else {
		c.Net, c.Addr = "tcp", env("DB_HOST", "127.0.0.1")+":"+env("DB_PORT", "3306")
	}
	c.ParseTime = true // natural Go typing: DATE/DATETIME -> time.Time
	c.InterpolateParams = d.tuned
	if t := tlsConfig(tlsMode, strings.Contains(fVariant, "resume") && fTest == "T1"); t != nil {
		tlsSeq++
		name := "b" + strconv.Itoa(tlsSeq)
		mysql.RegisterTLSConfig(name, t)
		c.TLSConfig = name
	}
	return c
}

func (d *SQLDriver) Open(tlsMode string) error {
	conn, err := mysql.NewConnector(d.cfg(tlsMode, false))
	if err != nil {
		return err
	}
	d.db = sql.OpenDB(conn)
	d.db.SetMaxOpenConns(1)
	d.db.SetMaxIdleConns(1)
	d.db.SetConnMaxLifetime(0)
	d.conn, err = d.db.Conn(ctx)
	return err
}

func (d *SQLDriver) Close() {
	if d.conn != nil {
		d.conn.Close()
		d.db.Close()
		d.conn = nil
	}
}

func (d *SQLDriver) Cipher() string {
	var n, v string
	if err := d.conn.QueryRowContext(ctx, "SHOW SESSION STATUS LIKE 'Ssl_cipher'").Scan(&n, &v); err != nil || v == "" {
		return "none"
	}
	return v
}

var t1Connector = map[string]driver.Connector{}

func (d *SQLDriver) Connect(tlsMode string, sock bool) (func() error, error) {
	// the connector (config + registered TLS config) is created once; each Connect opens a new connection
	key := fmt.Sprint(tlsMode, sock)
	c, ok := t1Connector[key]
	if !ok {
		cc, err := mysql.NewConnector(d.cfg(tlsMode, sock))
		if err != nil {
			return nil, err
		}
		c = cc
		t1Connector[key] = c
	}
	conn, err := c.Connect(ctx)
	if err != nil {
		return nil, err
	}
	return conn.Close, nil
}

func (d *SQLDriver) Exec(q string) error { _, err := d.conn.ExecContext(ctx, q); return err }

func (d *SQLDriver) T2(variant string, ids []int) (int64, error) {
	var s, v int64
	switch variant {
	case "literal":
		for _, id := range ids {
			if err := d.conn.QueryRowContext(ctx, "SELECT v FROM t_int WHERE id = "+strconv.Itoa(id)).Scan(&v); err != nil {
				return 0, err
			}
			s += v
		}
	case "param": // default: prepare+execute+close per call; tuned (interpolateParams): client-side
		for _, id := range ids {
			if err := d.conn.QueryRowContext(ctx, "SELECT v FROM t_int WHERE id = ?", id).Scan(&v); err != nil {
				return 0, err
			}
			s += v
		}
	default: // prepared once
		st, err := d.conn.PrepareContext(ctx, "SELECT v FROM t_int WHERE id = ?")
		if err != nil {
			return 0, err
		}
		defer st.Close()
		for _, id := range ids {
			if err := st.QueryRowContext(ctx, id).Scan(&v); err != nil {
				return 0, err
			}
			s += v
		}
	}
	return s, nil
}

func (d *SQLDriver) query(binary bool, q string) (*sql.Rows, func(), error) {
	if !binary {
		r, err := d.conn.QueryContext(ctx, q)
		return r, func() {}, err
	}
	st, err := d.conn.PrepareContext(ctx, q)
	if err != nil {
		return nil, nil, err
	}
	r, err := st.QueryContext(ctx)
	return r, func() { st.Close() }, err
}

func (d *SQLDriver) T3(variant string) (int64, error) {
	if strings.HasSuffix(variant, "buffered") {
		return 0, na("database/sql always streams rows; no buffered result API")
	}
	rows, done, err := d.query(strings.HasPrefix(variant, "binary"), "SELECT v FROM t_int")
	if err != nil {
		return 0, err
	}
	defer done()
	var s, v int64
	for rows.Next() {
		if err := rows.Scan(&v); err != nil {
			return 0, err
		}
		s += v
	}
	return s, rows.Close()
}

func (d *SQLDriver) T4(variant string) (int64, int, error) {
	q := "SELECT * FROM t_wide_mix"
	if strings.HasPrefix(variant, "int") {
		q = "SELECT * FROM t_wide_int"
	}
	rows, done, err := d.query(strings.HasSuffix(variant, "binary"), q)
	if err != nil {
		return 0, 0, err
	}
	defer done()
	cts, _ := rows.ColumnTypes()
	n := len(cts)
	kinds := make([]byte, n) // i=int, s=string, d=decimal(string), f=float, t=time
	dest := make([]any, n)
	for i, ct := range cts {
		switch ct.DatabaseTypeName() {
		case "INT", "BIGINT", "TINYINT", "SMALLINT", "MEDIUMINT":
			kinds[i], dest[i] = 'i', new(sql.NullInt64)
		case "VARCHAR", "CHAR", "TEXT":
			kinds[i], dest[i] = 's', new(sql.NullString)
		case "DECIMAL":
			kinds[i], dest[i] = 'd', new(sql.NullString)
		case "DOUBLE", "FLOAT":
			kinds[i], dest[i] = 'f', new(sql.NullFloat64)
		default:
			kinds[i], dest[i] = 't', new(sql.NullTime)
		}
	}
	var nn, isum, slen int64
	nrows := 0
	for rows.Next() {
		if err := rows.Scan(dest...); err != nil {
			return 0, 0, err
		}
		nrows++
		for i := 1; i < n; i++ {
			switch kinds[i] {
			case 'i':
				if v := dest[i].(*sql.NullInt64); v.Valid {
					nn++
					isum += v.Int64
				}
			case 's':
				if v := dest[i].(*sql.NullString); v.Valid {
					nn++
					slen += int64(len(v.String))
				}
			case 'd':
				if dest[i].(*sql.NullString).Valid {
					nn++
				}
			case 'f':
				if dest[i].(*sql.NullFloat64).Valid {
					nn++
				}
			default:
				if dest[i].(*sql.NullTime).Valid {
					nn++
				}
			}
		}
	}
	return nn + isum + slen, nrows, rows.Close()
}

func (d *SQLDriver) T5(q string, fn func(v []byte, s string, isStr bool)) error {
	rows, err := d.conn.QueryContext(ctx, q)
	if err != nil {
		return err
	}
	isStr := !strings.Contains(q, "doc_bin")
	var s string
	var b []byte
	for rows.Next() {
		if isStr {
			if err := rows.Scan(&s); err != nil {
				return err
			}
			fn(nil, s, true)
		} else {
			if err := rows.Scan(&b); err != nil {
				return err
			}
			fn(b, "", false)
		}
	}
	return rows.Close()
}

func (d *SQLDriver) T6(variant string) error {
	switch variant {
	case "sqltext":
		var sb strings.Builder
		for start := 1; start <= 1000000; start += 1000 {
			sb.Reset()
			sb.WriteString("INSERT INTO t_bulk (id,a,b,c) VALUES ")
			for i := start; i < start+1000; i++ {
				if i > start {
					sb.WriteByte(',')
				}
				fmt.Fprintf(&sb, "(%d,%d,'%s',%s)", i, i*3, escapeApp(rowB(i)), strconv.FormatFloat(float64(i)*0.5, 'g', -1, 64))
			}
			if _, err := d.conn.ExecContext(ctx, sb.String()); err != nil {
				return err
			}
		}
	case "multiparam": // default: prepare+execute+close per statement; tuned: client-side interpolation
		q := "INSERT INTO t_bulk (id,a,b,c) VALUES " + strings.TrimSuffix(strings.Repeat("(?,?,?,?),", 1000), ",")
		args := make([]any, 4000)
		for start := 1; start <= 1000000; start += 1000 {
			for k := 0; k < 1000; k++ {
				i := start + k
				args[4*k], args[4*k+1], args[4*k+2], args[4*k+3] = i, i*3, rowB(i), float64(i)*0.5
			}
			if _, err := d.conn.ExecContext(ctx, q, args...); err != nil {
				return err
			}
		}
	default:
		return na("database/sql has no batch API")
	}
	return nil
}

func (d *SQLDriver) Verify6() (string, error) {
	var a, b, c int64
	err := d.conn.QueryRowContext(ctx, "SELECT COUNT(*), SUM(a), SUM(CHAR_LENGTH(b)) FROM t_bulk").Scan(&a, &b, &c)
	return fmt.Sprintf("%d:%d:%d", a, b, c), err
}

func parseJSON(b []byte) error { var v any; return json.Unmarshal(b, &v) }

var _ = time.Second
