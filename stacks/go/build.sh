#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
export PATH=/opt/go/bin:$PATH
[ -f go.mod ] || go mod init dbbench/gorunner
go get github.com/go-sql-driver/mysql@latest github.com/go-mysql-org/go-mysql@latest golang.org/x/sys@latest
go mod tidy
go build -o runner .
go version; grep -E "go-sql-driver|go-mysql-org" go.mod
