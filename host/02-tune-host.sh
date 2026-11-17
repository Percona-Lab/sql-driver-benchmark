#!/bin/bash
# CPU isolation for benchmarking: SMT off, boost off, performance governor,
# client core isolated from the scheduler (isolcpus). NOT nohz_full: its context tracking adds cost to
# every kernel entry/exit (+14% on a TCP connect), which would penalise syscall-heavy drivers. Needs a reboot after the first run (kernel cmdline).
set -euxo pipefail
NCPU=$(lscpu -p=CORE | grep -v '^#' | sort -u | wc -l)
CLIENT_CORE=$((NCPU-1))
if ! grep -q "isolcpus=" /proc/cmdline; then
  sed -i "s/^GRUB_CMDLINE_LINUX_DEFAULT=\"/GRUB_CMDLINE_LINUX_DEFAULT=\"nosmt isolcpus=$CLIENT_CORE amd_pstate=passive /" /etc/default/grub
  update-grub
  echo "REBOOT NEEDED"
fi
# T1 opens thousands of loopback connections: avoid TIME_WAIT port exhaustion
cat > /etc/sysctl.d/90-dbbench.conf <<SYS
net.ipv4.ip_local_port_range=10000 65000
net.ipv4.tcp_tw_reuse=1
kernel.perf_event_paranoid=-1
kernel.kptr_restrict=0
# cap TIME_WAIT sockets: T1 opens 10k connections per iteration; a growing TIME_WAIT table slows
# ephemeral port selection and makes connect cost depend on what ran before
net.ipv4.tcp_max_tw_buckets=4096
SYS
sysctl --system >/dev/null
