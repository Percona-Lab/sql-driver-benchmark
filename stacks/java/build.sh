#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
mvn -q -B package -DskipTests
ls target/lib
cat > run <<'EOF'
#!/bin/bash
# JVM defaults (G1, heap sized by ergonomics). JAVA_OPTS adds flags for the profiling pass only.
cd "$(dirname "$0")"
exec java $JAVA_OPTS -cp "target/classes:target/lib/*" bench.Runner "$@"
EOF
chmod +x run
java -version 2>&1 | head -1
