#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
export PATH=/root/.cargo/bin:$PATH
cargo build --release
cargo build --release   # second pass so build.rs sees the generated Cargo.lock
grep -A1 -E '^name = "(mysql|sqlx)"$' Cargo.lock
