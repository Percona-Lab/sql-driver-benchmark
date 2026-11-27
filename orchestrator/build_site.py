#!/usr/bin/env python3
"""Build the GitHub Pages site (docs/index.html) from the report page source (reports/artifact/index.html).

The artifact page runs inside claude.ai's dashboard runtime (dash.data / dash.draw / dash.calc / dash.colors and its
theme tokens). This wraps the same markup and scripts in a standalone page with its own theme and a small stand-in for
that runtime that loads docs/data/cells.json and docs/data/notes.json.

usage: build_site.py   (run from the repo root; data files are written by artifact_data.py and copied separately)
"""
import re

SRC = "reports/artifact/index.html"
OUT = "docs/index.html"

TOKENS = """
:root {
  --color-bg: #fbfbfa; --color-fg: #1d2023; --color-fg-muted: #5c636b; --color-panel: #ffffff; --color-border-line: #e3e5e8;
  --color-warn: #b45309;
  --c1: #3b6fd8; --c2: #0f9d8a; --c3: #d9622b; --c4: #8a56c9; --c5: #c23b73; --c6: #6b7f2a; --c7: #2f8fb3; --c8: #b8860b; --c9: #5a6acf; --c10: #a0442a;
  --cds-chart-grid: #eceef1; --cds-chart-axis: #c9cdd3; --cds-text-secondary: #5c636b;
  --cds-surface-popover: #ffffff; --cds-border: #e3e5e8; --cds-shadow-popover: 0 6px 24px rgba(20,30,50,.12);
  --font-anthropic-sans: "Inter", system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-anthropic-serif: "Source Serif 4", Georgia, serif;
  --cds-font-size-caption: 12.5px; --cds-font-size-body: 15px; --cds-font-size-heading: 18px; --cds-font-size-title: 22px;
  --cds-font-weight-medium: 600;
  --cds-gap-xs: 4px; --cds-gap-sm: 8px; --cds-gap-md: 14px; --cds-gap-lg: 20px; --cds-gap-xl: 36px;
  --cds-pad-sm: 8px; --cds-pad-md: 14px; --cds-pad-lg: 18px; --cds-radius: 8px;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { %DARK% } }
:root[data-theme="dark"] { %DARK% }
body { margin: 0; background: var(--color-bg); color: var(--color-fg); font-family: var(--font-anthropic-sans); font-size: var(--cds-font-size-body); }
.site { max-width: 1080px; margin: 0 auto; padding-block: 32px 64px; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
.site h1 { font-family: var(--font-anthropic-serif); font-weight: 400; font-size: clamp(28px, 4vw, 40px); margin: 0 0 8px; text-wrap: balance; }
.site .eyebrow { font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: var(--color-fg-muted); }
.site a { color: var(--c1); }
.dash-select { font: inherit; font-size: var(--cds-font-size-caption); padding: 6px 10px; border: 1px solid var(--color-border-line); border-radius: var(--cds-radius); background-color: var(--color-panel); color: var(--color-fg); }
.rp-foot { margin-top: 40px; font-size: var(--cds-font-size-caption); color: var(--color-fg-muted); }
code { font-size: .92em; }
"""
DARK = ("--color-bg: #15171a; --color-fg: #e8eaed; --color-fg-muted: #a1a8b1; --color-panel: #1d2024; --color-border-line: #2e3238; "
        "--color-warn: #f0a050; --c1: #6e9bf0; --c2: #3cc3ad; --c3: #f08a55; --c4: #b18be6; --c5: #e86d9f; --c6: #a6bd5a; "
        "--c7: #5fbfe0; --c8: #e0b84a; --c9: #8d98ec; --c10: #e07a5a; "
        "--cds-chart-grid: #262a2f; --cds-chart-axis: #3a3f46; --cds-text-secondary: #a1a8b1; "
        "--cds-surface-popover: #22262b; --cds-border: #353a41; --cds-shadow-popover: 0 6px 24px rgba(0,0,0,.5); color-scheme: dark;")

SHIM = """
// Minimal runtime standing in for the claude.ai dashboard API: load the data files, draw on demand.
window.dash = (() => {
  const store = {}, calcs = {}, draws = {};
  const colors = Array.from({ length: 10 }, (_, i) => `var(--c${i + 1})`);
  function data(id) {
    if (calcs[id]) {
      const ins = calcs[id].inputs.map((i) => store[i]);
      if (ins.some((x) => !x || x.status !== 'ok')) return { status: 'loading', data: null };
      return { status: 'ok', data: calcs[id].fn(...ins.map((x) => x.data)) };
    }
    return store[id] || { status: 'loading', data: [] };
  }
  function runDraw(name) {
    const d = draws[name]; if (!d) return;
    document.querySelectorAll('[data-draw="' + name + '"]').forEach((el) => {
      if (typeof d === 'function') return d(el);
      if (!el.__made) el.__made = d.mount(el);
      d.update(el, el.__made);
    });
  }
  function drawAll() { Object.keys(draws).forEach(runDraw); }
  async function load(id, url) {
    try { const r = await fetch(url); if (!r.ok) throw new Error(r.status); store[id] = { status: 'ok', data: await r.json() }; }
    catch (e) { store[id] = { status: 'error', data: [], message: String(e) }; }
    drawAll();
  }
  let w = window.innerWidth;
  window.addEventListener('resize', () => { if (Math.abs(window.innerWidth - w) > 20) { w = window.innerWidth; drawAll(); } });
  return { colors, data, load, calc: (id, def) => { calcs[id] = def; }, draw: (name, fn) => { if (fn) draws[name] = fn; runDraw(name); } };
})();
"""

src = open(SRC).read()
style = re.search(r"<style>(.*?)</style>", src, re.S).group(1)
body = src[src.index('<div class="rp" id="report">'):src.index("<script>")]
scripts = re.findall(r"<script>(.*?)</script>", src, re.S)
body = body.replace("please report problems as issues on GitHub.</p>",
                    'please report problems as <a href="https://github.com/Percona-Lab/sql-driver-benchmark/issues">issues on GitHub</a>.</p>', 1)

html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>SQL Driver Benchmark</title>
<meta name="description" content="Client-side CPU and memory cost of 24 MySQL and MariaDB drivers and 22 frameworks in ten languages, measured on bare metal.">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&family=Source+Serif+4:wght@400&display=swap">
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>
<style>{TOKENS.replace('%DARK%', DARK)}{style}</style>
</head>
<body>
<main class="site">
  <div class="eyebrow">Percona Lab · MySQL &amp; MariaDB drivers in ten languages</div>
  <h1>SQL Driver Benchmark</h1>
{body}
  <p class="rp-foot">Code, raw data and method: <a href="https://github.com/Percona-Lab/sql-driver-benchmark">github.com/Percona-Lab/sql-driver-benchmark</a> · Reports: <a href="https://github.com/Percona-Lab/sql-driver-benchmark/blob/main/reports/phase3.md">frameworks</a>, <a href="https://github.com/Percona-Lab/sql-driver-benchmark/blob/main/reports/profiles.md">where the CPU goes (profiles)</a> · Data: <a href="data/cells.json">cells.json</a>, <a href="data/notes.json">notes.json</a>, <a href="data/tuned.json">tuned.json</a> · Apache License 2.0</p>
</main>
<script>{SHIM}</script>
""" + "".join(f"<script>{s}</script>\n" for s in scripts) + """<script>
  dash.load('cells', 'data/cells.json');
  dash.load('notes', 'data/notes.json');
  dash.load('tuned', 'data/tuned.json');
</script>
</body>
</html>
"""
open(OUT, "w").write(html)
print(f"wrote {OUT} ({len(html)} bytes)")
