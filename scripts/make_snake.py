#!/usr/bin/env python3
"""Custom 'snake eats the LAST 2 MONTHS of contributions' animation — our own, since Platane/snk is
year-only and fixed-speed.

Fetches the contribution calendar for [first-of-previous-month .. today] from the GitHub GraphQL API and
renders an animated SVG: a snake snakes through the grid (boustrophedon by week) and eats the days that
have contributions; eaten days regrow each loop. Writes dist/github-contribution-grid-snake.svg (light)
and ...-dark.svg. Deterministic, stdlib only, no AI. Speed via SNAKE_SECS_PER_CELL (higher = slower).
"""
import datetime as dt
import json
import os
import sys
import urllib.request

USER = os.environ.get("PROFILE_USER", "stanleys12")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
OUT_DIR = os.environ.get("SNAKE_OUT", "dist")
SECS_PER_CELL = float(os.environ.get("SNAKE_SECS_PER_CELL", "0.5"))   # higher = slower
SNAKE_LEN = 5                 # snake body length, in cells
SEG_PER_CELL = 3              # sub-cell segments so the body reads as ONE continuous snake, not dots

CELL, GAP, PAD, TOP = 30, 7, 10, 40     # bigger cells so it reads large on the profile
PITCH = CELL + GAP

PALETTES = {
    "light": {"empty": "#ebedf0", "label": "#57606a",
              "levels": ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"],
              "snake": ["#6e7fea", "#808ff0", "#95a1f4", "#abb4f7", "#c2c9fb", "#d5daff"]},
    "dark":  {"empty": "#161b22", "label": "#8b949e",
              "levels": ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"],
              "snake": ["#9db0ff", "#8b9bff", "#6e7fea", "#5a6bd8", "#4a5ac0", "#3a4aa8"]},
}


def level(c):
    return 0 if c == 0 else 1 if c <= 2 else 2 if c <= 5 else 3 if c <= 9 else 4


def hexlerp(a, b, t):
    a, b = a.lstrip("#"), b.lstrip("#")
    ch = [round(int(a[i:i + 2], 16) * (1 - t) + int(b[i:i + 2], 16) * t) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(ch)


def fetch_weeks():
    today = dt.date.today()
    first_this = today.replace(day=1)
    range_start = first_this
    for _ in range(2):                                     # step back two whole months → a 3-month window
        range_start = (range_start - dt.timedelta(days=1)).replace(day=1)
    q = {
        "query": "query($u:String!,$f:DateTime!,$t:DateTime!){user(login:$u){contributionsCollection(from:$f,to:$t)"
                 "{contributionCalendar{weeks{contributionDays{date contributionCount weekday}}}}}}",
        "variables": {"u": USER, "f": range_start.isoformat() + "T00:00:00Z", "t": today.isoformat() + "T23:59:59Z"},
    }
    req = urllib.request.Request(
        "https://api.github.com/graphql", data=json.dumps(q).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json",
                 "User-Agent": f"{USER}-snake"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    weeks = d["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    rs = range_start.isoformat()
    cells = []
    for col, w in enumerate(weeks):
        for cd in w["contributionDays"]:
            cells.append({"col": col, "row": cd["weekday"], "date": cd["date"],
                          "count": cd["contributionCount"], "in_range": cd["date"] >= rs})
    return cells, len(weeks), today, range_start


def build_svg(cells, ncols, label, theme):
    pal = PALETTES[theme]
    W = PAD * 2 + ncols * PITCH - GAP
    H = TOP + 7 * PITCH - GAP + PAD
    xy = lambda col, row: (PAD + col * PITCH, TOP + row * PITCH)
    by_pos = {(c["col"], c["row"]): c for c in cells}

    # snake path: boustrophedon down/up each week column (one continuous route)
    path = []
    for col in range(ncols):
        rows = range(7) if col % 2 == 0 else range(6, -1, -1)
        for row in rows:
            path.append((col, row))
    N = max(len(path), 2)
    step = SECS_PER_CELL
    D = round(N * step, 2)
    idx_of = {p: i for i, p in enumerate(path)}

    css = [
        f".lbl{{font:600 15px -apple-system,Segoe UI,sans-serif;fill:{pal['label']}}}",
        f".snk{{width:{CELL}px;height:{CELL}px;will-change:transform}}",
    ]
    stops = []
    for i, (col, row) in enumerate(path):
        x, y = xy(col, row)
        pct = round(i / (N - 1) * 100, 3)
        stops.append(f"{pct}%{{transform:translate({x}px,{y}px)}}")
    css.append("@keyframes snake{" + "".join(stops) + "}")
    eat_cls = {}
    for c in cells:
        if not c["in_range"] or c["count"] == 0:
            continue
        i = idx_of[(c["col"], c["row"])]
        p = min(99.0, round(i / (N - 1) * 100, 3))
        p2 = min(100.0, round(p + 0.6, 3))
        name = f"eat{i}"
        col_hex = pal["levels"][level(c["count"])]
        css.append(f"@keyframes {name}{{0%,{p}%{{fill:{col_hex}}}{p2}%,100%{{fill:{pal['empty']}}}}}")
        eat_cls[(c["col"], c["row"])] = (name, col_hex)

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">']
    parts.append("<style>" + "".join(css) + "</style>")
    parts.append(f'<text class="lbl" x="{PAD}" y="24">{label}</text>')

    for col in range(ncols):
        for row in range(7):
            c = by_pos.get((col, row))
            x, y = xy(col, row)
            if c and c["in_range"] and c["count"] > 0:
                name, col_hex = eat_cls[(col, row)]
                parts.append(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="5" '
                             f'fill="{col_hex}" style="animation:{name} {D}s linear infinite"/>')
            else:
                faint = ' opacity="0.4"' if (c and not c["in_range"]) else ''
                parts.append(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="5" '
                             f'fill="{pal["empty"]}"{faint}/>')

    x0, y0 = xy(*path[0])
    head, tail = pal["snake"][0], pal["snake"][-1]
    M = SNAKE_LEN * SEG_PER_CELL          # body points trailing the head
    sub = step / SEG_PER_CELL             # time gap between adjacent segments (a fraction of a cell)
    for j in range(M, 0, -1):             # body: tail -> just behind the head, so the face draws on top
        colr = hexlerp(head, tail, j / M)
        delay = round(-(D - j * sub), 2)
        parts.append(f'<rect class="snk" width="{CELL}" height="{CELL}" rx="{CELL // 2}" fill="{colr}" '
                     f'style="transform:translate({x0}px,{y0}px);animation:snake {D}s linear infinite;'
                     f'animation-delay:{delay}s"/>')
    # head with a face (two eyes + a smile); rides the same path animation, no trailing delay
    ex, ey, er = CELL * 0.32, CELL * 0.36, CELL * 0.14
    pr, dark = er * 0.52, "#10151c"
    face = (
        f'<rect width="{CELL}" height="{CELL}" rx="{CELL // 2}" fill="{head}"/>'
        f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="{er:.1f}" fill="#fff"/>'
        f'<circle cx="{CELL - ex:.1f}" cy="{ey:.1f}" r="{er:.1f}" fill="#fff"/>'
        f'<circle cx="{ex + pr * 0.3:.1f}" cy="{ey:.1f}" r="{pr:.1f}" fill="{dark}"/>'
        f'<circle cx="{CELL - ex + pr * 0.3:.1f}" cy="{ey:.1f}" r="{pr:.1f}" fill="{dark}"/>'
        f'<path d="M{CELL * 0.32:.1f},{CELL * 0.62:.1f} Q{CELL * 0.5:.1f},{CELL * 0.8:.1f} '
        f'{CELL * 0.68:.1f},{CELL * 0.62:.1f}" stroke="{dark}" stroke-width="1.8" fill="none" stroke-linecap="round"/>'
    )
    parts.append(f'<g class="snk" style="transform:translate({x0}px,{y0}px);'
                 f'animation:snake {D}s linear infinite;animation-delay:0s">{face}</g>')
    parts.append("</svg>")
    return "\n".join(parts)


def main():
    cells, ncols, today, range_start = fetch_weeks()
    if range_start.year == today.year:
        label = f"{range_start:%b}–{today:%b %Y} · contributions"
    else:
        label = f"{range_start:%b %Y} – {today:%b %Y} · contributions"
    os.makedirs(OUT_DIR, exist_ok=True)
    for theme, fname in (("light", "github-contribution-grid-snake.svg"),
                         ("dark", "github-contribution-grid-snake-dark.svg")):
        svg = build_svg(cells, ncols, label, theme)
        with open(os.path.join(OUT_DIR, fname), "w", encoding="utf-8") as f:
            f.write(svg)
    eaten = sum(1 for c in cells if c["in_range"] and c["count"] > 0)
    print(f"wrote {OUT_DIR}/ snake for {label}: {ncols} weeks, {eaten} active days")
    return 0


if __name__ == "__main__":
    sys.exit(main())
