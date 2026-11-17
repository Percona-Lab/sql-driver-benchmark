package main

// go-mysql-org/go-mysql client (used by replication/proxy tools; its own API, no database/sql).

import (
	"fmt"
	"runtime/debug"
	"strconv"
	"strings"

	"github.com/go-mysql-org/go-mysql/client"
	"github.com/go-mysql-org/go-mysql/mysql"
)

type GoMySQL struct{ c *client.Conn }

func (d *GoMySQL) Name() string { return "go-mysql" }
func (d *GoMySQL) Lib() string {
	if bi, ok := debug.ReadBuildInfo(); ok {
		for _, m := range bi.Deps {
			if m.Path == "github.com/go-mysql-org/go-mysql" {
				return "go-mysql " + m.Version + " (" + bi.GoVersion + ")"
			}
		}
	}
	return "go-mysql"
}

func (d *GoMySQL) dial(tlsMode string, sock bool) (*client.Conn, error) {
	addr := env("DB_HOST", "127.0.0.1") + ":" + env("DB_PORT", "3306")
	if sock {
		addr = env("DB_SOCKET", "")
	}
	resume := strings.Contains(fVariant, "resume") && fTest == "T1"
	return client.Connect(addr, env("DB_USER", "bench"), env("DB_PASS", "bench"), env("DB_NAME", "bench"),
		func(c *client.Conn) error {
			if t := tlsConfig(tlsMode, resume); t != nil {
				c.SetTLSConfig(t)
			}
			return nil
		})
}

func (d *GoMySQL) Open(tlsMode string) (err error) { d.c, err = d.dial(tlsMode, false); return }
func (d *GoMySQL) Close() {
	if d.c != nil {
		d.c.Close()
		d.c = nil
	}
}

func (d *GoMySQL) Cipher() string {
	r, err := d.c.Execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
	if err != nil || r.RowNumber() == 0 {
		return "none"
	}
	defer r.Close()
	if v, _ := r.GetString(0, 1); v != "" {
		return v
	}
	return "none"
}

func (d *GoMySQL) Connect(tlsMode string, sock bool) (func() error, error) {
	c, err := d.dial(tlsMode, sock)
	if err != nil {
		return nil, err
	}
	return c.Close, nil
}

func (d *GoMySQL) Exec(q string) error {
	r, err := d.c.Execute(q)
	if err == nil {
		r.Close()
	}
	return err
}

func (d *GoMySQL) T2(variant string, ids []int) (int64, error) {
	var s int64
	switch variant {
	case "literal":
		for _, id := range ids {
			r, err := d.c.Execute("SELECT v FROM t_int WHERE id = " + strconv.Itoa(id))
			if err != nil {
				return 0, err
			}
			s += r.Values[0][0].AsInt64()
			r.Close()
		}
	case "param": // Execute with args: prepare + execute + close per call
		for _, id := range ids {
			r, err := d.c.Execute("SELECT v FROM t_int WHERE id = ?", id)
			if err != nil {
				return 0, err
			}
			s += r.Values[0][0].AsInt64()
			r.Close()
		}
	default:
		st, err := d.c.Prepare("SELECT v FROM t_int WHERE id = ?")
		if err != nil {
			return 0, err
		}
		defer st.Close()
		for _, id := range ids {
			r, err := st.Execute(id)
			if err != nil {
				return 0, err
			}
			s += r.Values[0][0].AsInt64()
			r.Close()
		}
	}
	return s, nil
}

// each row: callback with field values (streamed) or loop over the buffered result
func (d *GoMySQL) rows(variant, q string, fn func(row []mysql.FieldValue, fields []*mysql.Field)) error {
	binary := strings.HasPrefix(variant, "binary") || strings.HasSuffix(variant, "binary")
	streamed := strings.Contains(variant, "streamed")
	var res mysql.Result
	cb := func(row []mysql.FieldValue) error { fn(row, res.Fields); return nil }
	if binary {
		st, err := d.c.Prepare(q)
		if err != nil {
			return err
		}
		defer st.Close()
		if streamed {
			return st.ExecuteSelectStreaming(&res, cb, nil)
		}
		r, err := st.Execute()
		if err != nil {
			return err
		}
		for _, row := range r.Values {
			fn(row, r.Fields)
		}
		r.Close()
		return nil
	}
	if streamed {
		return d.c.ExecuteSelectStreaming(q, &res, cb, nil)
	}
	r, err := d.c.Execute(q)
	if err != nil {
		return err
	}
	for _, row := range r.Values {
		fn(row, r.Fields)
	}
	r.Close()
	return nil
}

func (d *GoMySQL) T3(variant string) (int64, error) {
	var s int64
	err := d.rows(variant, "SELECT v FROM t_int", func(row []mysql.FieldValue, _ []*mysql.Field) { s += row[0].AsInt64() })
	return s, err
}

func isIntType(t byte) bool {
	return t == mysql.MYSQL_TYPE_TINY || t == mysql.MYSQL_TYPE_SHORT || t == mysql.MYSQL_TYPE_LONG ||
		t == mysql.MYSQL_TYPE_LONGLONG || t == mysql.MYSQL_TYPE_INT24
}
func isStrType(t byte) bool {
	return t == mysql.MYSQL_TYPE_VAR_STRING || t == mysql.MYSQL_TYPE_STRING || t == mysql.MYSQL_TYPE_VARCHAR
}

func (d *GoMySQL) T4(variant string) (int64, int, error) {
	q := "SELECT * FROM t_wide_mix"
	if strings.HasPrefix(variant, "int") {
		q = "SELECT * FROM t_wide_int"
	}
	var nn, isum, slen int64
	n := 0
	err := d.rows(variant, q, func(row []mysql.FieldValue, f []*mysql.Field) {
		n++
		for i := 1; i < len(row); i++ {
			v := &row[i]
			if v.Type == mysql.FieldValueTypeNull {
				continue
			}
			nn++
			switch {
			case isIntType(f[i].Type):
				if v.Type == mysql.FieldValueTypeString { // text protocol: value arrives as text
					x, _ := strconv.ParseInt(string(v.AsString()), 10, 64)
					isum += x
				} else {
					isum += v.AsInt64()
				}
			case isStrType(f[i].Type):
				slen += int64(len(v.AsString()))
			}
		}
	})
	return nn + isum + slen, n, err
}

func (d *GoMySQL) T5(q string, fn func(v []byte, s string, isStr bool)) error {
	r, err := d.c.Execute(q)
	if err != nil {
		return err
	}
	for _, row := range r.Values {
		fn(row[0].AsString(), "", false)
	}
	r.Close()
	return nil
}

func (d *GoMySQL) T6(variant string) error {
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
				fmt.Fprintf(&sb, "(%d,%d,'%s',%s)", i, i*3, mysql.Escape(rowB(i)), strconv.FormatFloat(float64(i)*0.5, 'g', -1, 64))
			}
			r, err := d.c.Execute(sb.String())
			if err != nil {
				return err
			}
			r.Close()
		}
	case "multiparam":
		q := "INSERT INTO t_bulk (id,a,b,c) VALUES " + strings.TrimSuffix(strings.Repeat("(?,?,?,?),", 1000), ",")
		st, err := d.c.Prepare(q)
		if err != nil {
			return err
		}
		defer st.Close()
		args := make([]any, 4000)
		for start := 1; start <= 1000000; start += 1000 {
			for k := 0; k < 1000; k++ {
				i := start + k
				args[4*k], args[4*k+1], args[4*k+2], args[4*k+3] = i, i*3, rowB(i), float64(i)*0.5
			}
			r, err := st.Execute(args...)
			if err != nil {
				return err
			}
			r.Close()
		}
	default:
		return na("go-mysql has no batch API")
	}
	return nil
}

func (d *GoMySQL) Verify6() (string, error) {
	r, err := d.c.Execute("SELECT COUNT(*), SUM(a), SUM(CHAR_LENGTH(b)) FROM t_bulk")
	if err != nil {
		return "", err
	}
	defer r.Close()
	parts := make([]string, 3)
	for i := range parts {
		parts[i] = string(r.Values[0][i].AsString())
		if r.Values[0][i].Type != mysql.FieldValueTypeString {
			parts[i] = fmt.Sprint(r.Values[0][i].Value())
		}
	}
	return strings.Join(parts, ":"), nil
}
