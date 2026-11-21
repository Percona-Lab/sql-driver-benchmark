#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
export PATH=/opt/go/bin:$PATH
[ -f go.mod ] || go mod init dbbench/gorunner
python3 gen_wide.py
go get github.com/go-sql-driver/mysql@v1.10.2 github.com/go-mysql-org/go-mysql@v1.16.0 golang.org/x/sys@v0.50.0 github.com/jmoiron/sqlx@v1.4.0 gorm.io/gorm@v1.31.2 gorm.io/driver/mysql@v1.6.0   # measured versions
go mod tidy
go build -o runner .
go version; grep -E "go-sql-driver|go-mysql-org" go.mod
