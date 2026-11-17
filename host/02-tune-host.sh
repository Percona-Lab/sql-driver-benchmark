#!/bin/bash
# CPU isolation for benchmarking: SMT off, boost off, performance governor,
# client core isolated. Needs a reboot after the first run (kernel cmdline).
set -euxo pipefail
NCPU=$(lscpu -p=CORE | grep -v '^#' | sort -u | wc -l)
CLIENT_CORE=$((NCPU-1))
if ! grep -q "isolcpus=" /proc/cmdline; then
  sed -i "s/^GRUB_CMDLINE_LINUX_DEFAULT=\"/GRUB_CMDLINE_LINUX_DEFAULT=\"nosmt isolcpus=$CLIENT_CORE nohz_full=$CLIENT_CORE rcu_nocbs=$CLIENT_CORE amd_pstate=passive /" /etc/default/grub
  update-grub
  echo "REBOOT NEEDED"
fi
# T1 opens thousands of loopback connections: avoid TIME_WAIT port exhaustion
cat > /etc/sysctl.d/90-dbbench.conf <<SYS
net.ipv4.ip_local_port_range=10000 65000
net.ipv4.tcp_tw_reuse=1
kernel.perf_event_paranoid=-1
kernel.kptr_restrict=0
SYS
sysctl --system >/dev/null
