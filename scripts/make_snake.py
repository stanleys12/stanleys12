#!/usr/bin/env python3
"""Custom 'snake eats the last 3 months of contributions, and GROWS as it eats' animation.

Fetches the contribution calendar for [first-of-two-months-ago .. today] from the GitHub GraphQL API
and renders an animated SVG: a snake snakes through the grid (boustrophedon by week), chomping, with
eyes; each contribution day dissolves as the head passes, and the snake's tail lags one extra cell for
every day eaten, so the body lengthens over the loop (classic Snake). Writes dist/*.svg. Deterministic,
stdlib only, no AI. Speed via SNAKE_SECS_PER_CELL (higher = slower).
"""
import datetime as dt
import json
import os
import sys
import urllib.request
from collections import deque

USER = os.environ.get("PROFILE_USER", "stanleys12")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
OUT_DIR = os.environ.get("SNAKE_OUT", "dist")
SECS_PER_CELL = float(os.environ.get("SNAKE_SECS_PER_CELL", "0.35"))   # higher = slower
SNAKE_BASE = 3                 # starting body length (cells); grows +1 per contribution eaten

CELL, GAP, PAD, TOP = 30, 7, 10, 40
PITCH = CELL + GAP

PALETTES = {
    "light": {"empty": "#ebedf0", "label": "#57606a",
              "levels": ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"],
              "head": "#6e7fea", "body": "#8b9bf2"},
    "dark":  {"empty": "#161b22", "label": "#8b949e",
              "levels": ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"],
              "head": "#9db0ff", "body": "#6e7fea"},
}


def level(c):
    return 0 if c == 0 else 1 if c <= 2 else 2 if c <= 5 else 3 if c <= 9 else 4


def fetch_weeks():
    today = dt.date.today()
    range_start = today.replace(day=1)
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
    off, fat = GAP / 2, PITCH            # fat/offset so body cells bridge the gaps into one snake

    path = []
    for col in range(ncols):
        for row in (range(7) if col % 2 == 0 else range(6, -1, -1)):
            path.append((col, row))
    N = max(len(path), 2)
    step = SECS_PER_CELL
    D = round(N * step, 2)
    idx_of = {p: i for i, p in enumerate(path)}

    css = [
        f".lbl{{font:600 15px -apple-system,Segoe UI,sans-serif;fill:{pal['label']}}}",
        f".snk{{width:{CELL}px;height:{CELL}px;will-change:transform}}",
        "@keyframes chompc{0%,42%{opacity:1}58%,100%{opacity:0}}",
        "@keyframes chompo{0%,42%{opacity:0}58%,100%{opacity:1}}",
    ]
    # head path keyframes
    stops = [f"{round(i/(N-1)*100,3)}%{{transform:translate({xy(c,r)[0]}px,{xy(c,r)[1]}px)}}"
             for i, (c, r) in enumerate(path)]
    css.append("@keyframes snake{" + "".join(stops) + "}")

    # food cells dissolve as the head passes
    eat_cls = {}
    for c in cells:
        if not c["in_range"] or c["count"] == 0:
            continue
        i = idx_of[(c["col"], c["row"])]
        p = min(99.0, round(i / (N - 1) * 100, 3))
        p2 = min(100.0, round(p + 2.6, 3))
        col_hex = pal["levels"][level(c["count"])]
        css.append(f"@keyframes eat{i}{{0%,{p}%{{fill:{col_hex}}}{p2}%,100%{{fill:{pal['empty']}}}}}")
        eat_cls[(c["col"], c["row"])] = (f"eat{i}", col_hex)

    # GROWING snake: simulate the body as a queue of occupied cells; the tail only drops a cell when
    # the body is longer than its current target length, and the target grows +1 for each food eaten.
    food = [bool(by_pos.get(p) and by_pos[p]["in_range"] and by_pos[p]["count"] > 0) for p in path]
    eaten, dq, t_out = 0, deque(), [N - 1] * N
    for h in range(N):
        dq.append(h)
        if food[h]:
            eaten += 1
        while len(dq) > SNAKE_BASE + eaten:
            t_out[dq.popleft()] = h
    body_rects = []
    for i, (col, row) in enumerate(path):
        pin = max(0.0, round((i - 0.5) / (N - 1) * 100, 3))
        pout = round(t_out[i] / (N - 1) * 100, 3)
        if pout <= pin:
            continue
        # hard on at pin, hard off at pout (duplicate offsets = instant step, so the snake never fades)
        css.append(f"@keyframes b{i}{{0%{{opacity:0}}{pin}%{{opacity:0}}{pin}%{{opacity:1}}"
                   f"{pout}%{{opacity:1}}{pout}%{{opacity:0}}100%{{opacity:0}}}}")
        x, y = xy(col, row)
        body_rects.append(f'<rect x="{x-off:.1f}" y="{y-off:.1f}" width="{fat}" height="{fat}" rx="8" '
                          f'fill="{pal["body"]}" style="opacity:0;animation:b{i} {D}s linear infinite"/>')

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

    parts.extend(body_rects)   # the growing body (lit cells), above the grid

    # head with a chomping face, glides along the path on top of everything
    x0, y0 = xy(*path[0])
    ex, ey, er = CELL * 0.32, CELL * 0.36, CELL * 0.14
    pr, dark = er * 0.52, "#10151c"
    face = (
        f'<rect x="{-off:.1f}" y="{-off:.1f}" width="{fat}" height="{fat}" rx="8" fill="{pal["head"]}"/>'
        f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="{er:.1f}" fill="#fff"/>'
        f'<circle cx="{CELL - ex:.1f}" cy="{ey:.1f}" r="{er:.1f}" fill="#fff"/>'
        f'<circle cx="{ex + pr * 0.3:.1f}" cy="{ey:.1f}" r="{pr:.1f}" fill="{dark}"/>'
        f'<circle cx="{CELL - ex + pr * 0.3:.1f}" cy="{ey:.1f}" r="{pr:.1f}" fill="{dark}"/>'
        f'<path d="M{CELL * 0.33:.1f},{CELL * 0.62:.1f} Q{CELL * 0.5:.1f},{CELL * 0.78:.1f} '
        f'{CELL * 0.67:.1f},{CELL * 0.62:.1f}" stroke="{dark}" stroke-width="1.8" fill="none" '
        f'stroke-linecap="round" style="animation:chompc .45s infinite"/>'
        f'<ellipse cx="{CELL * 0.5:.1f}" cy="{CELL * 0.66:.1f}" rx="{CELL * 0.15:.1f}" ry="{CELL * 0.12:.1f}" '
        f'fill="{dark}" style="animation:chompo .45s infinite"/>'
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
        with open(os.path.join(OUT_DIR, fname), "w", encoding="utf-8") as f:
            f.write(build_svg(cells, ncols, label, theme))
    eaten = sum(1 for c in cells if c["in_range"] and c["count"] > 0)
    print(f"wrote {OUT_DIR}/ snake for {label}: {ncols} weeks, {eaten} active days "
          f"(grows {SNAKE_BASE}→{SNAKE_BASE + eaten} cells)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
