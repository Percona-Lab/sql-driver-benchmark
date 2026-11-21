package main

// Phase 3: Go frameworks on go-sql-driver/mysql (the driver measured as go-sql-driver).
//   sqlx  jmoiron/sqlx: struct scanning, Get/Select/NamedExec on database/sql
//   gorm  GORM v2 with gorm.io/driver/mysql (go-sql-driver underneath)
// default = the idiom most code uses; tuned = framework options plus go-sql-driver's interpolateParams.

import (
	"database/sql"
	"fmt"
	"runtime/debug"
	"strings"
	"time"

	"github.com/go-sql-driver/mysql"
	"github.com/jmoiron/sqlx"
	gmysql "gorm.io/driver/mysql"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

func depVersion(path string) string {
	if bi, ok := debug.ReadBuildInfo(); ok {
		for _, m := range bi.Deps {
			if m.Path == path {
				return m.Version
			}
		}
	}
	return "?"
}

// Decimal holds a DECIMAL column as text (Go has no decimal type); the touch rule counts it as non-NULL only.
type Decimal string

// touchValues: T4 checksum over the column values of one row (after id).
func touchValues(vals []any, nn, isum, slen *int64) {
	for _, v := range vals {
		switch x := v.(type) {
		case int64:
			*nn++
			*isum += x
		case string:
			*nn++
			*slen += int64(len(x))
		case sql.NullString:
			if x.Valid {
				*nn++
				*slen += int64(len(x.String))
			}
		case sql.NullInt64:
			if x.Valid {
				*nn++
				*isum += x.Int64
			}
		case float64, time.Time, Decimal:
			*nn++
		}
	}
}

type TInt struct {
	ID int64 `db:"id" gorm:"column:id;primaryKey"`
	V  int64 `db:"v" gorm:"column:v"`
}

func (TInt) TableName() string { return "t_int" }

type TBulk struct {
	ID int64   `db:"id" gorm:"column:id;primaryKey"`
	A  int64   `db:"a" gorm:"column:a"`
	B  string  `db:"b" gorm:"column:b"`
	C  float64 `db:"c" gorm:"column:c"`
}

func (TBulk) TableName() string { return "t_bulk" }

// ---------------------------------------------------------------------------------------------- sqlx
type Sqlx struct {
	SQLDriver
	x *sqlx.DB
}

func (d *Sqlx) Name() string { return "go-sqlx" }
func (d *Sqlx) Lib() string {
	return "sqlx " + depVersion("github.com/jmoiron/sqlx") + " on go-sql-driver/mysql " + depVersion("github.com/go-sql-driver/mysql")
}
func (d *Sqlx) Open(tlsMode string) error {
	if err := d.SQLDriver.Open(tlsMode); err != nil {
		return err
	}
	d.db.SetMaxOpenConns(2) // the base driver pins one connection (setup, checksums); the framework uses the other
	d.db.SetMaxIdleConns(2)
	d.x = sqlx.NewDb(d.db, "mysql")
	return nil
}
func (d *Sqlx) Connect(string, bool) (func() error, error) {
	return nil, na("sqlx uses database/sql connections (see go-sql-driver)")
}
func (d *Sqlx) T2(variant string, ids []int) (int64, error) {
	if variant != "param" {
		return 0, na("frameworks bind parameters themselves (variant: param)")
	}
	var s, v int64
	for _, id := range ids {
		if err := d.x.Get(&v, "SELECT v FROM t_int WHERE id = ?", id); err != nil {
			return 0, err
		}
		s += v
	}
	return s, nil
}
func (d *Sqlx) T3(variant string) (int64, error) {
	if strings.HasPrefix(variant, "binary") {
		return 0, na("measured on the text protocol")
	}
	var s int64
	if strings.Contains(variant, "streamed") {
		rows, err := d.x.Queryx("SELECT * FROM t_int")
		if err != nil {
			return 0, err
		}
		var r TInt
		for rows.Next() {
			if err := rows.StructScan(&r); err != nil {
				return 0, err
			}
			s += r.V
		}
		return s, rows.Close()
	}
	var all []TInt // Select: whole result into a slice of structs
	if err := d.x.Select(&all, "SELECT * FROM t_int"); err != nil {
		return 0, err
	}
	for i := range all {
		s += all[i].V
	}
	return s, nil
}
func (d *Sqlx) T4(variant string) (int64, int, error) {
	if strings.HasSuffix(variant, "binary") {
		return 0, 0, na("measured on the text protocol")
	}
	var nn, isum, slen int64
	if strings.HasPrefix(variant, "int") {
		var all []WideInt
		if err := d.x.Select(&all, "SELECT * FROM t_wide_int"); err != nil {
			return 0, 0, err
		}
		for i := range all {
			touchValues(all[i].Values(), &nn, &isum, &slen)
		}
		return nn + isum + slen, len(all), nil
	}
	var all []WideMix
	if err := d.x.Select(&all, "SELECT * FROM t_wide_mix"); err != nil {
		return 0, 0, err
	}
	for i := range all {
		touchValues(all[i].Values(), &nn, &isum, &slen)
	}
	return nn + isum + slen, len(all), nil
}
func (d *Sqlx) T5(q string, fn func(v []byte, s string, isStr bool)) error {
	if strings.Contains(q, "doc_bin") {
		var all [][]byte
		if err := d.x.Select(&all, q); err != nil {
			return err
		}
		for _, v := range all {
			fn(v, "", false)
		}
		return nil
	}
	var all []string
	if err := d.x.Select(&all, q); err != nil {
		return err
	}
	for _, v := range all {
		fn(nil, v, true)
	}
	return nil
}
func (d *Sqlx) T6(variant string) error {
	if variant != "batch" {
		return na("sqlx inserts with NamedExec over a slice (the batch variant)")
	}
	rows := make([]TBulk, 1000)
	for st := 1; st <= 1000000; st += 1000 {
		for k := range rows {
			i := st + k
			rows[k] = TBulk{int64(i), int64(i * 3), rowB(i), float64(i) * 0.5}
		}
		// NamedExec with a slice expands to one multi-row INSERT
		if _, err := d.x.NamedExec("INSERT INTO t_bulk (id,a,b,c) VALUES (:id,:a,:b,:c)", rows); err != nil {
			return err
		}
	}
	return nil
}

// ---------------------------------------------------------------------------------------------- GORM
type Gorm struct {
	SQLDriver
	g *gorm.DB
}

func (d *Gorm) Name() string { return "go-gorm" }
func (d *Gorm) Lib() string {
	return "GORM " + depVersion("gorm.io/gorm") + " on go-sql-driver/mysql " + depVersion("github.com/go-sql-driver/mysql")
}
func (d *Gorm) Open(tlsMode string) error {
	if err := d.SQLDriver.Open(tlsMode); err != nil {
		return err
	}
	d.db.SetMaxOpenConns(2) // the base driver pins one connection (setup, checksums); the framework uses the other
	d.db.SetMaxIdleConns(2)
	cfg := &gorm.Config{Logger: logger.Default.LogMode(logger.Silent)}
	if d.tuned { // documented performance options
		cfg.SkipDefaultTransaction = true
		cfg.PrepareStmt = true
	}
	g, err := gorm.Open(gmysql.New(gmysql.Config{Conn: d.db, SkipInitializeWithVersion: true}), cfg)
	d.g = g
	return err
}
func (d *Gorm) Connect(string, bool) (func() error, error) {
	return nil, na("GORM uses database/sql connections (see go-sql-driver)")
}
func (d *Gorm) T2(variant string, ids []int) (int64, error) {
	if variant != "param" {
		return 0, na("frameworks bind parameters themselves (variant: param)")
	}
	var s int64
	var r TInt
	for _, id := range ids {
		r = TInt{}
		if err := d.g.First(&r, id).Error; err != nil {
			return 0, err
		}
		s += r.V
	}
	return s, nil
}
func (d *Gorm) T3(variant string) (int64, error) {
	if strings.HasPrefix(variant, "binary") {
		return 0, na("measured on the text protocol")
	}
	var s int64
	if strings.Contains(variant, "streamed") {
		rows, err := d.g.Model(&TInt{}).Rows()
		if err != nil {
			return 0, err
		}
		var r TInt
		for rows.Next() {
			if err := d.g.ScanRows(rows, &r); err != nil {
				return 0, err
			}
			s += r.V
		}
		return s, rows.Close()
	}
	var all []TInt
	if err := d.g.Find(&all).Error; err != nil {
		return 0, err
	}
	for i := range all {
		s += all[i].V
	}
	return s, nil
}
func (d *Gorm) T4(variant string) (int64, int, error) {
	if strings.HasSuffix(variant, "binary") {
		return 0, 0, na("measured on the text protocol")
	}
	var nn, isum, slen int64
	if strings.HasPrefix(variant, "int") {
		var all []WideInt
		if err := d.g.Find(&all).Error; err != nil {
			return 0, 0, err
		}
		for i := range all {
			touchValues(all[i].Values(), &nn, &isum, &slen)
		}
		return nn + isum + slen, len(all), nil
	}
	var all []WideMix
	if err := d.g.Find(&all).Error; err != nil {
		return 0, 0, err
	}
	for i := range all {
		touchValues(all[i].Values(), &nn, &isum, &slen)
	}
	return nn + isum + slen, len(all), nil
}
func (d *Gorm) T5(q string, fn func(v []byte, s string, isStr bool)) error {
	cls := q[strings.Index(q, "'")+1 : strings.LastIndex(q, "'")]
	col := "doc"
	if strings.Contains(q, "doc_bin") {
		col = "doc_bin"
		var all [][]byte
		if err := d.g.Table("t_blob").Where("size_class = ?", cls).Order("id").Pluck(col, &all).Error; err != nil {
			return err
		}
		for _, v := range all {
			fn(v, "", false)
		}
		return nil
	}
	var all []string
	if err := d.g.Table("t_blob").Where("size_class = ?", cls).Order("id").Pluck(col, &all).Error; err != nil {
		return err
	}
	for _, v := range all {
		fn(nil, v, true)
	}
	return nil
}
func (d *Gorm) T6(variant string) error {
	if variant != "batch" {
		return na("GORM inserts with Create on a slice (the batch variant)")
	}
	rows := make([]TBulk, 1000)
	for st := 1; st <= 1000000; st += 1000 {
		for k := range rows {
			i := st + k
			rows[k] = TBulk{int64(i), int64(i * 3), rowB(i), float64(i) * 0.5}
		}
		if err := d.g.Create(&rows).Error; err != nil { // one multi-row INSERT per slice
			return err
		}
	}
	return nil
}

var _ = fmt.Sprint
var _ = mysql.NewConfig
