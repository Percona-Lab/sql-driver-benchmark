#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
dotnet publish -c Release -o out runner.csproj
cat > run <<'EOF'
#!/bin/bash
cd "$(dirname "$0")"
exec ./out/runner "$@"
EOF
chmod +x run
dotnet --version; ls out | grep -iE "^(MySqlConnector|MySql\.Data).*dll$"
