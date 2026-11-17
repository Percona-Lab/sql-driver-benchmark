#!/bin/bash
# Applied at every boot / before each batch.
set -ux
echo off > /sys/devices/system/cpu/smt/control 2>/dev/null
echo 0 > /sys/devices/system/cpu/cpufreq/boost 2>/dev/null
for c in /sys/devices/system/cpu/cpu[0-9]*/cpufreq; do echo performance > $c/scaling_governor; cat $c/cpuinfo_max_freq > $c/scaling_min_freq; done
echo 0 > /proc/sys/kernel/randomize_va_space || true   # stable addresses for profiles
echo 0 > /proc/sys/kernel/nmi_watchdog   # frees a hardware counter for perf stat
grep . /sys/devices/system/cpu/smt/active /sys/devices/system/cpu/cpufreq/boost 2>/dev/null
grep MHz /proc/cpuinfo | sort | uniq -c
