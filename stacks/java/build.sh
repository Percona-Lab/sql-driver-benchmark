#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
python3 gen_entities.py
mvn -q -B package -DskipTests
ls target/lib
cat > run <<'EOF'
#!/bin/bash
# JVM defaults (G1, heap sized by ergonomics). JAVA_OPTS adds flags for the profiling pass only.
cd "$(dirname "$0")"
MAIN=bench.Runner
[ "$1" = "--fw" ] && MAIN=bench.fw.Fw
exec java --enable-native-access=ALL-UNNAMED $JAVA_OPTS -cp "target/classes:target/lib/*" $MAIN "$@"
EOF
chmod +x run
java -version 2>&1 | head -1
