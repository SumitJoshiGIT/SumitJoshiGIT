#!/usr/bin/env python3
"""Render the profile README visuals from public GitHub data.

Uses only the standard library and no third-party image service, so the
profile cannot break when a hosted stats card goes down. Reads the public
contribution calendar and repository languages, writes SVGs to assets/, and
refreshes the plain-text stats block in README.md.

Run from anywhere: python3 scripts/generate.py
Set GITHUB_TOKEN to raise the REST rate limit (optional).
"""
import datetime as dt
import json
import os
import pathlib
import re
import urllib.request
from collections import Counter
from xml.sax.saxutils import escape

USER = "SumitJoshiGIT"
FIRST_YEAR = 2023
ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
README = ROOT / "README.md"
LANGUAGE_CACHE = ASSETS / "languages.json"

# Notebook bytes are mostly embedded output, and HTML is mostly generated, so
# neither says much about what was written by hand.
SKIP_LANGUAGES = {"Jupyter Notebook", "HTML"}

INK = "#0A1130"
PANEL = "#111A44"
LINE = "#2A3670"
TEXT = "#D7E0FF"
DIM = "#8FA0DC"
COLD = "#4FD6E8"
HOT = "#FFB547"
# Thermal ramp, indexed by GitHub contribution level 0-4.
HEAT = ["#1A2452", "#1F5C86", "#2FA9BE", "#FFB547", "#FFF1C9"]

FONT = ("ui-monospace,'JetBrains Mono','Cascadia Mono','SF Mono',Menlo,"
        "Consolas,'DejaVu Sans Mono',monospace")

STYLE = f"""
text{{font-family:{FONT};fill:{TEXT}}}
.dim{{fill:{DIM}}}.hot{{fill:{HOT}}}.cold{{fill:{COLD}}}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important}}}}
"""

GLYPHS = {
    "S": "01111 10000 10000 01110 00001 00001 11110",
    "U": "10001 10001 10001 10001 10001 10001 01110",
    "M": "10001 11011 10101 10101 10001 10001 10001",
    "I": "11111 00100 00100 00100 00100 00100 11111",
    "T": "11111 00100 00100 00100 00100 00100 00100",
    "J": "00111 00010 00010 00010 00010 10010 01100",
    "O": "01110 10001 10001 10001 10001 10001 01110",
    "H": "10001 10001 10001 11111 10001 10001 10001",
    " ": "00000 00000 00000 00000 00000 00000 00000",
}

# Coldest (furthest from the machine) to hottest (the hardware itself).
STACK = [
    ("interface", "React, Next.js, Tailwind CSS, TypeScript, Socket.io client"),
    ("services", "Node.js, NestJS, Express.js, FastAPI, Django, REST, WebSockets"),
    ("intelligence", "PyTorch, TensorFlow, scikit-learn, RAG, YOLO, Gemini API"),
    ("data", "PostgreSQL, pgvector, MongoDB, Redis, Pinecone, BullMQ"),
    ("platform", "Linux, Docker, GitHub Actions, AWS EC2, Playwright, Selenium"),
    ("systems", "C, C++20, Java, Python, POSIX sockets, threads, epoll"),
    ("metal", "Raspberry Pi, Arduino, sensor fusion, Edge AI for microcontrollers"),
]
STACK_COLORS = ["#7EA2FF", "#62B4F0", "#4FD6E8", "#7FE3D0", "#FFB547", "#FFD27F", "#FFF1C9"]


def fetch(url, headers=None):
    request = urllib.request.Request(
        url, headers={"User-Agent": f"{USER}-profile", **(headers or {})})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode()


def calendar_html(year=None):
    url = f"https://github.com/users/{USER}/contributions"
    if year:
        url += f"?from={year}-01-01&to={year}-12-31"
    return fetch(url, {"X-Requested-With": "XMLHttpRequest"})


def year_total(html):
    match = re.search(r"<h2[^>]*>\s*([\d,]+)\s+contributions?", html, re.S)
    if not match:
        raise RuntimeError("contribution total not found; calendar markup changed")
    return int(match.group(1).replace(",", ""))


def parse_days(html):
    """Return [(date, count, level)] sorted by date."""
    cells = {cell_id: (day, int(level)) for day, cell_id, level in re.findall(
        r'data-date="([\d-]+)" id="([^"]+)" data-level="(\d)"', html)}
    days = []
    for cell_id, count in re.findall(r'for="([^"]+)"[^>]*>(\d+|No) contributions?', html):
        if cell_id in cells:
            day, level = cells[cell_id]
            days.append((dt.date.fromisoformat(day), 0 if count == "No" else int(count), level))
    days.sort()
    if len(days) < 300:
        raise RuntimeError(f"parsed {len(days)} days; calendar markup changed")
    return days


def streaks(days):
    longest = run = 0
    for _, count, _ in days:
        run = run + 1 if count else 0
        longest = max(longest, run)
    # Today may simply not have any activity yet, so it cannot end a streak.
    tail = days[:-1] if days[-1][1] == 0 else days
    current = 0
    for _, count, _ in reversed(tail):
        if not count:
            break
        current += 1
    return current, longest


def languages():
    """Return language byte totals, reusing the last good copy if the API fails."""
    try:
        totals = fetch_languages()
    except (OSError, RuntimeError) as error:
        print(f"language refresh failed, using cached data: {error}")
        return Counter(json.loads(LANGUAGE_CACHE.read_text()))
    LANGUAGE_CACHE.write_text(json.dumps(dict(totals.most_common()), indent=2) + "\n")
    return totals


def fetch_languages():
    headers = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    repos = json.loads(fetch(
        f"https://api.github.com/users/{USER}/repos?per_page=100", headers))
    totals = Counter()
    for repo in repos:
        if not repo["fork"]:
            totals.update(json.loads(fetch(repo["languages_url"], headers)))
    for name in SKIP_LANGUAGES:
        totals.pop(name, None)
    if not totals:
        raise RuntimeError("no language data returned")
    return totals


def svg(width, height, title, desc, body, extra_style=""):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="t d">'
        f'<title id="t">{escape(title)}</title><desc id="d">{escape(desc)}</desc>'
        f"<style>{STYLE}{extra_style}</style>"
        f'<rect width="{width}" height="{height}" rx="10" fill="{INK}"/>{body}</svg>\n'
    )


def hero():
    width, height, pitch, x0, y0 = 1000, 330, 12, 40, 36
    rows = [GLYPHS[c].split() for c in "SUMIT JOSHI"]
    columns = []
    for index, glyph in enumerate(rows):
        offset = index * 6
        for col in range(5):
            cells = "".join(
                f'<rect x="{x0 + (offset + col) * pitch}" y="{y0 + row * pitch}" '
                f'width="{pitch - 2}" height="{pitch - 2}"/>'
                for row in range(7) if glyph[row][col] == "1")
            if cells:
                delay = (offset + col) * 0.022
                columns.append(f'<g class="col" style="animation-delay:{delay:.3f}s">{cells}</g>')
    log = [
        ("0.000", "cpu", "Full-stack, AI/ML and systems engineer"),
        ("0.112", "mount", "/systems  C++20 sockets, an HTTP server from scratch"),
        ("0.238", "mount", "/ai       RAG pipelines, vector search, computer vision"),
        ("0.361", "mount", "/web      React, Next.js, NestJS, FastAPI, PostgreSQL"),
        ("0.494", "ready", "Dehradun, India. B.Tech CSE (AI &amp; ML), class of 2027"),
    ]
    lines = "".join(
        f'<text class="log" xml:space="preserve" x="40" y="{166 + i * 26}" font-size="15" '
        f'style="animation-delay:{1.7 + i * 0.28:.2f}s">'
        f'<tspan class="dim">[{stamp}]</tspan> '
        f'<tspan class="{"hot" if tag == "ready" else "cold"}">{tag}:</tspan> {text}</text>'
        for i, (stamp, tag, text) in enumerate(log))
    prompt_y = 166 + len(log) * 26
    prompt = (
        f'<text class="log" x="40" y="{prompt_y}" font-size="15" style="animation-delay:3.2s">'
        f'<tspan class="hot">sumit@nox</tspan><tspan class="dim">:~$ </tspan>'
        f'<tspan class="hot cursor">\u2588</tspan></text>')
    body = (
        f'<defs><linearGradient id="thermal" gradientUnits="userSpaceOnUse" x1="40" x2="830" '
        f'y1="0" y2="0"><stop offset="0" stop-color="{COLD}"/><stop offset="0.62" '
        f'stop-color="{HOT}"/><stop offset="1" stop-color="{HEAT[4]}"/></linearGradient></defs>'
        f'<g fill="url(#thermal)">{"".join(columns)}</g>{lines}{prompt}')
    css = (
        ".col{opacity:0;animation:on .01s linear forwards}"
        ".log{opacity:0;animation:on .01s linear forwards}"
        ".cursor{animation:blink 1s steps(2,jump-none) 3.2s 6}"
        "@keyframes on{to{opacity:1}}"
        "@keyframes blink{from{opacity:1}to{opacity:0}}"
        "@media (prefers-reduced-motion:reduce){.col,.log{opacity:1}}"
    )
    return svg(width, height, "Sumit Joshi",
               "Dot-matrix name banner above a boot log listing systems, AI and web work.",
               body, css)


def contributions(days, stats):
    cell, gap, x0, y0 = 15, 2, 74, 62
    pitch = cell + gap
    first = days[0][0]
    start = first - dt.timedelta(days=(first.weekday() + 1) % 7)  # Sunday column
    cells, weekly, months = [], Counter(), {}
    for day, count, level in days:
        delta = (day - start).days
        week, weekday = delta // 7, delta % 7
        weekly[week] += count
        label = f"{day:%b %-d}: {count}"
        cells.append(
            f'<rect x="{x0 + week * pitch}" y="{y0 + weekday * pitch}" width="{cell}" '
            f'height="{cell}" rx="2" fill="{HEAT[level]}"><title>{label}</title></rect>')
        if day.day <= 7 and weekday == 0:
            months[week] = f"{day:%b}"
    weeks = max(weekly) + 1
    labels = "".join(
        f'<text class="dim" x="{x0 + week * pitch}" y="{y0 - 10}" font-size="12">{name}</text>'
        for week, name in months.items())
    addresses = "".join(
        f'<text class="dim" x="24" y="{y0 + row * pitch + 12}" font-size="12">0x{row * 0x10:02X}</text>'
        for row in range(7))

    # Logic-analyzer trace: one rail per week, height on a sqrt scale so a
    # single huge week cannot flatten everything else.
    rail = y0 + 7 * pitch + 66
    amplitude = 44
    peak = max(weekly.values()) or 1
    points = [f"M{x0} {rail}"]
    for week in range(weeks):
        y = rail - amplitude * (weekly[week] / peak) ** 0.5
        points += [f"L{x0 + week * pitch} {y:.1f}", f"L{x0 + (week + 1) * pitch} {y:.1f}"]
    trace = (
        f'<line x1="{x0}" x2="{x0 + weeks * pitch}" y1="{rail}" y2="{rail}" stroke="{LINE}"/>'
        f'<path d="{" ".join(points)}" fill="none" stroke="{COLD}" stroke-width="1.5"/>'
        f'<text class="dim" x="24" y="{rail - 2}" font-size="12">wk</text>')

    readouts = [
        (f"{stats['year']:,}", "last 12 months"),
        (f"{stats['lifetime']:,}", f"since {FIRST_YEAR}"),
        (str(stats["active"]), "active days"),
        (f"{stats['longest']}d", "longest streak"),
        (f"{stats['current']}d", "current streak"),
        (str(stats["peak"]), "busiest day"),
    ]
    readout_y = rail + 44
    readout = "".join(
        f'<text class="hot" x="{x0 + i * 150}" y="{readout_y}" font-size="22" '
        f'font-weight="700">{value}</text>'
        f'<text class="dim" x="{x0 + i * 150}" y="{readout_y + 20}" font-size="12">{name}</text>'
        for i, (value, name) in enumerate(readouts))

    grid_height = 7 * pitch
    sweep = (f'<rect class="sweep" x="{x0}" y="{y0 - 4}" width="2" height="{grid_height + 8}" '
             f'fill="{HEAT[4]}"/>')
    css = (
        f".sweep{{opacity:0;animation:sweep 3.5s cubic-bezier(.4,0,.6,1) .3s 1}}"
        f"@keyframes sweep{{0%{{opacity:.9;transform:translateX(0)}}"
        f"99%{{opacity:.9}}100%{{opacity:0;transform:translateX({weeks * pitch}px)}}}}"
    )
    body = (
        f'<text x="24" y="26" font-size="14"><tspan class="hot">$</tspan> '
        f'xxd --heat /proc/{USER}/contributions</text>'
        f'{labels}{addresses}{"".join(cells)}{sweep}{trace}{readout}')
    desc = (f"Thermal heatmap of {stats['year']} contributions over the last 12 months with a "
            f"weekly activity waveform.")
    return svg(1000, readout_y + 42, "GitHub contribution memory map", desc, body, css)


def language_table(totals):
    top = totals.most_common(8)
    grand = sum(totals.values())
    x_bar, bar_width, row = 250, 620, 30
    rows, address = [], 0
    for i, (name, size) in enumerate(top):
        share = size / grand
        y = 62 + i * row
        fill = HOT if i == 0 else COLD
        rows.append(
            f'<text class="dim" x="24" y="{y + 13}" font-size="13">0x{address:06X}</text>'
            f'<text x="116" y="{y + 13}" font-size="14">{escape(name)}</text>'
            f'<rect x="{x_bar}" y="{y}" width="{bar_width}" height="16" fill="{HEAT[0]}"/>'
            f'<rect x="{x_bar}" y="{y}" width="{max(share * bar_width, 2):.1f}" height="16" fill="{fill}"/>'
            f'<text class="dim" x="976" y="{y + 13}" font-size="13" text-anchor="end">{share * 100:.1f}%</text>')
        address += size
    body = (f'<text x="24" y="26" font-size="14"><tspan class="hot">$</tspan> '
            f'readelf --sections {USER}</text>{"".join(rows)}')
    desc = "Top languages by bytes: " + ", ".join(
        f"{name} {size / grand * 100:.1f}%" for name, size in top) + "."
    return svg(1000, 62 + len(top) * row + 14, "Languages across public repositories", desc, body)


def stack():
    y0, row, x_text = 58, 44, 188
    rows = []
    for i, ((layer, items), color) in enumerate(zip(STACK, STACK_COLORS)):
        y = y0 + i * row
        rows.append(
            f'<rect x="24" y="{y}" width="952" height="{row - 6}" rx="3" fill="{PANEL}"/>'
            f'<rect x="24" y="{y}" width="6" height="{row - 6}" rx="1" fill="{color}"/>'
            f'<text x="44" y="{y + 24}" font-size="15" font-weight="700" fill="{color}" '
            f'style="fill:{color}">{layer}</text>'
            f'<text x="{x_text}" y="{y + 24}" font-size="14.5">{escape(items)}</text>')
    body = (f'<text x="24" y="26" font-size="14"><tspan class="hot">$</tspan> '
            f'traceroute --from ui --to silicon</text>{"".join(rows)}')
    desc = "Skills by abstraction layer. " + " ".join(f"{a}: {b}." for a, b in STACK)
    return svg(1000, y0 + len(STACK) * row + 14, "Skill stack", desc, body)


def update_readme(stats):
    text = README.read_text()
    line = (
        f"**{stats['year']:,}** contributions in the last 12 months, "
        f"**{stats['lifetime']:,}** since {FIRST_YEAR}, across **{stats['active']}** active days "
        f"in the last year. Longest streak: **{stats['longest']}** days. "
        f"Top language: **{stats['language']}**."
    )
    updated, found = re.subn(
        r"(<!-- stats:start -->\n).*?(<!-- stats:end -->)",
        lambda match: f"{match.group(1)}{line}\n{match.group(2)}", text, flags=re.S)
    if not found:
        raise RuntimeError("stats markers missing from README.md")
    README.write_text(updated)


def main():
    days = parse_days(calendar_html())
    current, longest = streaks(days)
    totals = languages()
    stats = {
        "year": sum(count for _, count, _ in days),
        "lifetime": sum(year_total(calendar_html(year))
                        for year in range(FIRST_YEAR, dt.date.today().year + 1)),
        "active": sum(1 for _, count, _ in days if count),
        "peak": max(count for _, count, _ in days),
        "current": current,
        "longest": longest,
        "language": totals.most_common(1)[0][0],
    }
    ASSETS.mkdir(exist_ok=True)
    (ASSETS / "hero.svg").write_text(hero())
    (ASSETS / "contributions.svg").write_text(contributions(days, stats))
    (ASSETS / "languages.svg").write_text(language_table(totals))
    (ASSETS / "stack.svg").write_text(stack())
    update_readme(stats)
    print(stats)


if __name__ == "__main__":
    main()
