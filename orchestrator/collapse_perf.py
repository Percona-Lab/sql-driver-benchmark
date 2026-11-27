#!/usr/bin/env python3
"""Collapse `perf script` output into folded stacks that keep each frame's library.

Each frame is written as  symbol{dso}  (dso = file basename, "kernel" for the kernel, "jit" for code named by a
perf map), root first, separated by ';', followed by a space and the summed sample period (cycles).
usage: perf script -i perf.data | collapse_perf.py > out.folded
"""
import os, re, sys
from collections import Counter

HDR = re.compile(r"^(\S.*?)\s+\d+(?:/\d+)?\s+(?:\[\d+\]\s+)?[\d.]+:\s+(\d+)\s+\S+:")   # comm pid/tid [cpu] time: period event:
FRM = re.compile(r"^\s+[0-9a-f]+\s+(.*?)\s+\((.*)\)\s*$")


def dso_name(d):
    if d.startswith("[kernel") or d.startswith("[") and "kallsyms" in d:
        return "kernel"
    if d.startswith("/tmp/perf-") and d.endswith(".map"):
        return "jit"
    if d.startswith("["):
        return d.strip("[]")
    return os.path.basename(d).replace(" (deleted)", "")


def main():
    out = Counter()
    comm, period, frames = None, 0, []

    def flush():
        if comm is not None and frames:
            out[";".join([comm] + frames[::-1])] += period

    for line in sys.stdin:
        if not line.strip():
            flush(); comm, frames = None, []
            continue
        m = HDR.match(line)
        if m and not line.startswith((" ", "\t")):
            flush()
            comm, period, frames = m.group(1).strip().replace(" ", "_").replace(";", ":"), int(m.group(2)), []
            continue
        f = FRM.match(line)
        if f and comm is not None:
            sym = f.group(1)
            sym = re.sub(r"\+0x[0-9a-f]+$", "", sym)
            d = dso_name(f.group(2))
            if sym in ("[unknown]", ""):
                sym = "[unknown]"
            frames.append(f"{sym}{{{d}}}".replace(";", ":"))
    flush()
    for k, v in out.items():
        sys.stdout.write(f"{k} {v}\n")


if __name__ == "__main__":
    main()
