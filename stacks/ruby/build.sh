#!/bin/bash
# Gems installed into ./vendor; mysql2 built against Oracle libmysqlclient 9.7 (/opt/oracle).
set -euo pipefail
cd "$(dirname "$0")"
export PATH=/opt/ruby/bin:$PATH GEM_HOME=$PWD/vendor GEM_PATH=$PWD/vendor
gem install --no-document mysql2 -- --with-mysql-config=/opt/oracle/usr/bin/mysql_config \
  --with-ldflags="-Wl,-rpath,/opt/oracle/usr/lib/x86_64-linux-gnu"
gem install --no-document trilogy bigdecimal
cat > run <<'EOF'
#!/bin/bash
# YJIT on: the default for production Ruby (Rails enables it)
cd "$(dirname "$0")"
export GEM_HOME=$PWD/vendor GEM_PATH=$PWD/vendor
exec /opt/ruby/bin/ruby --yjit runner.rb "$@"
EOF
chmod +x run
/opt/ruby/bin/ruby -v; GEM_HOME=$PWD/vendor /opt/ruby/bin/gem list | grep -E "mysql2|trilogy"
