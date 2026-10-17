#!/usr/bin/env python3
"""Rewrite the 'Open-source contributions' section of README.md from merged PRs.

Queries GitHub for pull requests authored by USER that got merged, keeps the repos that
aren't the user's own, and writes a sorted list between the CONTRIBUTIONS markers. Runs in
CI (GitHub Actions) with GITHUB_TOKEN; no external deps, stdlib only. Deterministic — it
only ever reads public contribution data and rewrites one README section.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request

USER = os.environ.get("PROFILE_USER", "stanleys12")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
README = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "README.md")
START, END = "<!-- CONTRIBUTIONS:START -->", "<!-- CONTRIBUTIONS:END -->"

# Ranking: these flagship projects lead in this order (what a reader recognises first); every other repo
# follows by GitHub stars, so new merges slot in on their own. Edit this list to re-rank the top.
FLAGSHIP = [
    "numpy/numpy",
    "puppeteer/puppeteer",
    "openclaw/openclaw",
    "openai/codex-security",
    "sgl-project/sglang",
    "jaegertracing/jaeger",
]


def api(url):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{USER}-profile-readme",
        **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}),
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def merged_repos():
    """{'' owner/repo '': merged_pr_count} for repos the user doesn't own."""
    counts = {}
    q = urllib.parse.quote(f"type:pr author:{USER} is:merged")
    page = 1
    while page <= 10:  # search caps at 1000 results; 10 pages * 100 is plenty
        data = api(f"https://api.github.com/search/issues?q={q}&per_page=100&page={page}")
        items = data.get("items", [])
        if not items:
            break
        for it in items:
            full = "/".join(it["repository_url"].split("/")[-2:])
            if full.lower().startswith(f"{USER.lower()}/"):
                continue  # skip own repos — this section is about contributing to others
            counts[full] = counts.get(full, 0) + 1
        if len(items) < 100:
            break
        page += 1
    return counts


def stars(full):
    try:
        return int(api(f"https://api.github.com/repos/{full}").get("stargazers_count") or 0)
    except Exception:  # noqa: BLE001 — a missing star count only affects ordering
        return 0


def fmt_stars(n):
    if n >= 1000:
        return f"{n / 1000:.1f}".rstrip("0").rstrip(".") + "k"
    return str(n)


def render(counts):
    if not counts:
        return "_No merged external contributions found yet._"
    flag = {r.lower(): i for i, r in enumerate(FLAGSHIP)}
    star = {full: stars(full) for full in counts}
    rows = sorted(counts, key=lambda f: (flag.get(f.lower(), len(flag)), -star[f], f.lower()))
    lines = []
    for full in rows:
        n = counts[full]
        times = f" · {n} PRs" if n > 1 else ""
        st = f" · ★ {fmt_stars(star[full])}" if star[full] else ""
        lines.append(f"- [{full}](https://github.com/{full}){st}{times}")
    return "\n".join(lines)


def main():
    with open(README, encoding="utf-8") as f:
        text = f.read()
    if START not in text or END not in text:
        print("markers not found in README; nothing to do", file=sys.stderr)
        return 1
    try:
        body = render(merged_repos())
    except Exception as e:  # noqa: BLE001 — never let a transient API hiccup rewrite the section to empty
        print(f"skip update (API error): {e}", file=sys.stderr)
        return 0
    new = re.sub(re.escape(START) + r".*?" + re.escape(END),
                 f"{START}\n{body}\n{END}", text, flags=re.S)
    if new != text:
        with open(README, "w", encoding="utf-8") as f:
            f.write(new)
        print("README contributions section updated")
    else:
        print("no change")
    return 0


if __name__ == "__main__":
    sys.exit(main())
