#!/usr/bin/env python3
"""Clean 'snake weaves through the last 3 months of contributions' animation.

Fetches the contribution calendar for [first-of-two-months-ago .. today] from the GitHub GraphQL API
and renders an animated SVG: the board stays FULL and alive (every contribution keeps its real colour),
and a clearly visible snake — an eyed, chomping head plus a fixed-length trailing body — weaves along the
grid (boustrophedon by week). Each contribution gives a soft pulse as the head passes over it; nothing is
erased. Writes dist/*.svg. Deterministic, stdlib only, no AI. Speed via SNAKE_SECS_PER_CELL (higher = slower).
"""
import datetime as dt
import json
import os
import sys
import urllib.request

USER = os.environ.get("PROFILE_USER", "stanleys12")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
OUT_DIR = os.environ.get("SNAKE_OUT", "dist")
SECS_PER_CELL = float(os.environ.get("SNAKE_SECS_PER_CELL", "0.3"))   # higher = slower
BODY_LEN = int(os.environ.get("SNAKE_BODY", "6"))                     # trailing body length (cells)

CELL, GAP, PAD, TOP = 30, 7, 10, 40
PITCH = CELL + GAP

PALETTES = {
    "light": {"empty": "#ebedf0", "label": "#57606a",
              "levels": ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"],
              "head": "#5a6fe0", "tail": "#aeb8f3", "glow": "#ffffff"},
    "dark":  {"empty": "#161b22", "label": "#8b949e",
              "levels": ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"],
              "head": "#9db0ff", "tail": "#3b4493", "glow": "#ffffff"},
}


def level(c):
    return 0 if c == 0 else 1 if c <= 2 else 2 if c <= 5 else 3 if c <= 9 else 4


def hexlerp(c1, c2, t):
    c1, c2 = c1.lstrip("#"), c2.lstrip("#")
    ch = [round(int(c1[i:i + 2], 16) + (int(c2[i:i + 2], 16) - int(c1[i:i + 2], 16)) * t) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(ch)


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
    off, fat = GAP / 2, PITCH            # fat/offset so segments bridge the gaps into one continuous snake

    # Boustrophedon grid path: top→bottom on even columns, bottom→top on odd, left→right (old→new).
    grid = []
    for col in range(ncols):
        for row in (range(7) if col % 2 == 0 else range(6, -1, -1)):
            grid.append(xy(col, row))
    # Off-screen runways so the loop restart (head jumps from exit back to entry) happens out of view —
    # no teleport flash, no fade hacks. Length covers the whole body plus a margin.
    RUN = BODY_LEN + 3
    gx0, gy0 = grid[0]
    gx1, gy1 = grid[-1]
    entry = [(gx0 - PITCH * (RUN - m), gy0) for m in range(RUN)]   # slithers in from the left
    exit_ = [(gx1 + PITCH * (m + 1), gy1) for m in range(RUN)]     # slithers off to the right
    pathpx = entry + grid + exit_
    M = max(len(pathpx), 2)
    D = round(M * SECS_PER_CELL, 2)
    # map a grid cell → its index within pathpx (entry offset + position in boustrophedon order)
    order = {}
    k = 0
    for col in range(ncols):
        for row in (range(7) if col % 2 == 0 else range(6, -1, -1)):
            order[(col, row)] = len(entry) + k
            k += 1

    clamp = lambda v: max(0.0, min(100.0, round(v, 3)))
    pct = lambda s: clamp(s / (M - 1) * 100)

    css = [
        f".lbl{{font:600 15px -apple-system,Segoe UI,sans-serif;fill:{pal['label']}}}",
        f".snk{{width:{CELL}px;height:{CELL}px;will-change:transform}}",
        "@keyframes chompc{0%,42%{opacity:1}58%,100%{opacity:0}}",
        "@keyframes chompo{0%,42%{opacity:0}58%,100%{opacity:1}}",
    ]
    # One shared path keyframe: head and every body segment ride it, the body lagging via animation-delay.
    stops = "".join(f"{pct(i)}%{{transform:translate({x:.1f}px,{y:.1f}px)}}" for i, (x, y) in enumerate(pathpx))
    css.append("@keyframes snake{" + stops + "}")

    # Soft pulse on each real contribution as the head glides over it (board is never erased)
    def kf_pulse(name, lo, mid, hi):
        out, last = [], -1.0
        for o, v in [(0.0, 0), (lo, 0), (mid, 0.5), (hi, 0), (100.0, 0)]:
            o = clamp(o)
            if o <= last:
                o = round(min(100.0, last + 0.01), 3)
            out.append((o, v)); last = o
        return f"@keyframes {name}{{" + "".join(f"{o}%{{opacity:{v}}}" for o, v in out) + "}"

    glow_rects = []
    for c in cells:
        if not (c["in_range"] and c["count"] > 0):
            continue
        i = order[(c["col"], c["row"])]
        b = pct(i)
        css.append(kf_pulse(f"g{i}", clamp(b - 1.2), b, clamp(b + 3.0)))
        x, y = xy(c["col"], c["row"])
        glow_rects.append(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="5" '
                          f'fill="{pal["glow"]}" style="opacity:0;animation:g{i} {D}s linear infinite"/>')

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">']
    parts.append("<style>" + "".join(css) + "</style>")
    parts.append(f'<text class="lbl" x="{PAD}" y="24">{label}</text>')

    # static board — every cell keeps its real colour the whole loop (alive, never wiped)
    for col in range(ncols):
        for row in range(7):
            c = by_pos.get((col, row))
            x, y = xy(col, row)
            if c and c["in_range"] and c["count"] > 0:
                fill = pal["levels"][level(c["count"])]
            else:
                fill = pal["empty"]
            faint = ' opacity="0.45"' if (c and not c["in_range"]) else ''
            parts.append(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="5" fill="{fill}"{faint}/>')

    parts.extend(glow_rects)   # pulses, above the board

    # The snake: a head plus BODY_LEN trailing segments, all on the SAME path keyframe. Each segment k lags
    # the head by k cells via a negative animation-delay (k*step - D keeps it always-running, no first-loop
    # blank). Colour grades head→tail. Drawn tail-first so the head sits on top. All transform-based, so it
    # stays a clean continuous snake with no opacity tricks.
    step = SECS_PER_CELL
    for kk in range(BODY_LEN, 0, -1):
        delay = round(kk * step - D, 2)
        colr = hexlerp(pal["head"], pal["tail"], kk / BODY_LEN)
        parts.append(f'<rect x="{-off:.1f}" y="{-off:.1f}" width="{fat}" height="{fat}" rx="9" fill="{colr}" '
                     f'style="transform:translate({pathpx[0][0]:.1f}px,{pathpx[0][1]:.1f}px);'
                     f'animation:snake {D}s linear infinite;animation-delay:{delay}s"/>')

    # eyed, chomping head — glides along the path on top of everything
    ex, ey, er = CELL * 0.32, CELL * 0.36, CELL * 0.14
    pr, dark = er * 0.52, "#10151c"
    face = (
        f'<rect x="{-off:.1f}" y="{-off:.1f}" width="{fat}" height="{fat}" rx="9" fill="{pal["head"]}"/>'
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
    parts.append(f'<g class="snk" style="transform:translate({pathpx[0][0]:.1f}px,{pathpx[0][1]:.1f}px);'
                 f'animation:snake {D}s linear infinite">{face}</g>')
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
    active = sum(1 for c in cells if c["in_range"] and c["count"] > 0)
    print(f"wrote {OUT_DIR}/ snake for {label}: {ncols} weeks, {active} active days, "
          f"body {BODY_LEN} cells, ~{round(ncols * 7 * SECS_PER_CELL)}s loop")
    return 0


if __name__ == "__main__":
    sys.exit(main())
