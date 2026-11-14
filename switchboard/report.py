"""Local activity report: one self-contained HTML page built from ~/.switchboard. No network.
The only script is the bundled sticker player (stickers/report.ts), pinned by a CSP hash so nothing else can run."""
from __future__ import annotations

import base64
import hashlib
import html
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from switchboard import choices, paths

MAX_WEEKS = 26
TOP_N = 10
STICKERS = (Path(__file__).parent / "stickers.js").read_text()
CSP = ("default-src 'none'; style-src 'unsafe-inline'; script-src 'sha256-"
       + base64.b64encode(hashlib.sha256(STICKERS.encode()).digest()).decode() + "'")


def _week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _picks(rows):
    """Rows that record a real pick: a valid date and a chosen id."""
    out = []
    for r in rows:
        if not isinstance(r, dict) or not isinstance(r.get("chosen"), str):
            continue
        try:
            d = datetime.strptime(str(r.get("date")), "%Y-%m-%d").date()
        except ValueError:
            continue
        offered = [x for x in (r.get("offered") or []) if isinstance(x, str)]
        out.append((d, str(r.get("category") or "other"), offered, r["chosen"]))
    return out


def summarise(inventory: dict, profiles: dict, rows: list) -> dict:
    installed = {sid: p for sid, p in profiles.items() if sid in inventory}
    picks = _picks(rows)

    weeks = []
    if picks:
        counts = Counter(_week(d) for d, *_ in picks)
        first, last = min(d for d, *_ in picks), max(d for d, *_ in picks)
        first = max(first, last - timedelta(weeks=MAX_WEEKS - 1))
        d = first - timedelta(days=first.weekday())
        while d <= last:
            weeks.append((_week(d), counts.get(_week(d), 0)))
            d += timedelta(weeks=1)

    chosen = Counter(c for *_, c in picks)
    offered = Counter(x for _, _, off, _ in picks for x in set(off))
    top = sorted(chosen, key=lambda s: (-chosen[s], s))[:TOP_N]

    cat_picks, cat_over = Counter(), Counter()
    for _, cat, off, c in picks:
        cat_picks[cat] += 1
        cat_over[cat] += bool(off) and c != off[0]

    src_all = Counter(str(r.get("source", "?")) for r in inventory.values())
    src_prof = Counter(str(inventory[s].get("source", "?")) for s in installed)
    return {
        "generated": date.today().isoformat(),
        "skills": len(inventory),
        "profiled": len(installed),
        "stale": sum(1 for s, p in installed.items() if p.get("content_hash") != inventory[s].get("content_hash")),
        "picks": len(picks),
        "overrides": sum(cat_over.values()),
        "weeks": weeks,
        "top_skills": [(s, chosen[s], offered[s]) for s in top],
        "by_category": sorted(((c, cat_picks[c], cat_over[c]) for c in cat_picks), key=lambda x: (-x[1], x[0])),
        "by_source": sorted((s, src_all[s], src_prof[s]) for s in src_all),
        "audit": choices.audit_rows(rows),
        "profiled_skills": sorted(
            ((s, ", ".join(str(c) for c in (p.get("categories") or [])), str(p.get("does") or ""),
              chosen[s], offered[s], p.get("content_hash") != inventory[s].get("content_hash"))
             for s, p in installed.items()), key=lambda x: (-x[3], -x[4], x[0])),
    }


def _pct(n, d):
    return f"{round(100 * n / d)}%" if d else "–"


CSS = """
:root{--bg:#F5F5F5;--card:#FFFFFF;--ink:#333333;--muted:#5f6b7a;--head:#0A2540;--bar:#1A3A5C;--accent:#F9C642;--rule:#e3e6ea}
@media (prefers-color-scheme:dark){:root{--bg:#0A2540;--card:#1A3A5C;--ink:#FFFFFF;--muted:#c3cdd8;--head:#FFFFFF;--bar:#F9C642;--rule:#2c4b6e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
header{background:#0A2540;color:#fff;padding:20px 16px;border-bottom:4px solid var(--accent)}
header h1{margin:0;font-size:20px}header p{margin:4px 0 0;color:#c3cdd8;font-size:13px}
main{max-width:960px;margin:0 auto;padding:16px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:16px}
.tile,section{background:var(--card);border:1px solid var(--rule);border-radius:8px;padding:14px 16px}
.tile b{display:block;font-size:26px;color:var(--head);font-variant-numeric:tabular-nums}.tile span{color:var(--muted);font-size:12px}
section{margin-bottom:16px}h2{margin:0 0 10px;font-size:15px;color:var(--head)}
.chart{display:flex;align-items:flex-end;gap:2px;height:140px;border-bottom:1px solid var(--rule);overflow-x:auto}
.col{flex:1 0 18px;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:100%}
.col i{display:block;width:100%;max-width:28px;background:var(--bar);border-radius:4px 4px 0 0;min-height:1px}
.col:hover i{opacity:.8}.col small{font-size:10px;color:var(--muted)}
.axis{display:flex;justify-content:space-between;color:var(--muted);font-size:11px;margin-top:4px}
.hbar{display:grid;grid-template-columns:minmax(120px,1fr) 2fr 70px;gap:8px;align-items:center;margin:4px 0}
.hbar code{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.track{height:12px}.track i{display:block;height:100%;background:var(--bar);border-radius:0 4px 4px 0}
.num{text-align:right;font-variant-numeric:tabular-nums;color:var(--muted)}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--rule)}th{color:var(--muted);font-weight:600}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.empty{color:var(--muted)}footer{color:var(--muted);font-size:12px;text-align:center;padding:8px 16px 24px}
.tile{display:flex;align-items:center;justify-content:space-between;gap:8px}
.st{display:block;flex:none;width:56px;height:56px}h2 .st{width:36px;height:36px}.empty .st{width:96px;height:96px;margin:0 auto 8px}
h2{display:flex;align-items:center;gap:8px}
"""


def _st(name):
    """Decorative sticker; the text beside it carries the meaning. Names are fixed here, never from data."""
    return f'<canvas class="st" data-sticker="{name}" aria-hidden="true"></canvas>'


def _table(head, rows, numeric=()):
    e = html.escape
    cell = lambda tag, i, v: f'<{tag} class="n">{e(str(v))}</{tag}>' if i in numeric else f"<{tag}>{e(str(v))}</{tag}>"
    th = "".join(cell("th", i, h) for i, h in enumerate(head))
    body = "".join("<tr>" + "".join(cell("td", i, v) for i, v in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="scroll"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def render(s: dict) -> str:
    """Every value from skills or the log is escaped: skill ids and sources are untrusted text."""
    e = html.escape
    tiles = [(s["skills"], "installed skills", "folder"),
             (f'{s["profiled"]} ({_pct(s["profiled"], s["skills"])})', "profiled", "search"),
             (s["picks"], "picks recorded", "pin"),
             (_pct(s["overrides"], s["picks"]), "picks that passed over the top suggestion", "toggle")]
    out = [f'<meta http-equiv="Content-Security-Policy" content="{CSP}">',
           f"<title>Switchboard report</title><style>{CSS}</style>",
           f'<header><h1>Switchboard report</h1><p>Generated {e(s["generated"])} from ~/.switchboard on this machine. '
           "Nothing here leaves your computer.</p></header><main>",
           '<div class="tiles">' + "".join(f'<div class="tile"><div><b>{e(str(v))}</b><span>{e(t)}</span></div>{_st(st)}</div>'
                                           for v, t, st in tiles) + "</div>"]

    if not s["picks"]:
        out.append(f'<section><h2>Activity</h2><p class="empty">{_st("mailbox")}No picks yet. When Switchboard offers you a choice of '
                   "skills and you pick one, it shows up here.</p></section>")
    else:
        peak = max(n for _, n in s["weeks"]) or 1
        cols = "".join(f'<div class="col" title="{e(w)}: {n} picks"><small>{n or ""}</small>'
                       f'<i style="height:{max(1, round(100 * n / peak))}%"></i></div>' for w, n in s["weeks"])
        out.append(f'<section><h2>{_st("calendar")}Picks per week</h2><div class="chart">{cols}</div>'
                   f'<div class="axis"><span>{e(s["weeks"][0][0])}</span><span>{e(s["weeks"][-1][0])}</span></div></section>')
        peak = s["top_skills"][0][1]
        bars = "".join(f'<div class="hbar" title="{e(sid)}: chosen {c} of {o} times offered"><code>{e(sid)}</code>'
                       f'<div class="track"><i style="width:{round(100 * c / peak)}%"></i></div>'
                       f'<span class="num">{c} / {o}</span></div>' for sid, c, o in s["top_skills"])
        out.append(f'<section><h2>{_st("trophy")}Most chosen skills</h2><p class="empty">Times chosen / times offered.</p>{bars}</section>')
        out.append("<section><h2>By task area</h2>" + _table(
            ("Category", "Picks", "Passed over top pick", "Rate"),
            [(c, n, o, _pct(o, n)) for c, n, o in s["by_category"]], numeric=(1, 2, 3)) + "</section>")
        if s["audit"]:
            out.append("<section><h2>Profiles worth a second look</h2>"
                       '<p class="empty">Task types where you passed over the top suggestion at least twice. '
                       "Re-profiling these skills may help (/switchboard:profile).</p>" + _table(
                           ("Category", "Targets", "Focus", "Times", "You chose"),
                           [(g["category"], ", ".join(g["targets"]) or "–", ", ".join(g["focus"]) or "–",
                             g["overrides"], ", ".join(g["chosen"])) for g in s["audit"]], numeric=(3,)) + "</section>")

    coverage = (_table(("Source", "Skills", "Profiled", "Coverage"),
                       [(src, n, p, _pct(p, n)) for src, n, p in s["by_source"]], numeric=(1, 2, 3))
                if s["by_source"] else '<p class="empty">No skills found.</p>')
    stale = (f'<p class="empty">{s["stale"]} profiled skills changed since profiling; '
             "run /switchboard:profile to refresh.</p>" if s["stale"] else "")
    out.append(f"<section><h2>Profiling coverage</h2>{coverage}{stale}</section>")
    if s["profiled_skills"]:
        out.append(f'<section><details><summary><h2 style="display:inline">Profiled skills ({len(s["profiled_skills"])})'
                   '</h2></summary><p class="empty">Most chosen first. Use your browser\'s Find to search. '
                   "* = changed since profiling.</p>" + _table(
                       ("Skill", "Categories", "What it does", "Chosen", "Offered"),
                       [(sid + (" *" if old else ""), cats or "–", does or "–", c, o)
                        for sid, cats, does, c, o, old in s["profiled_skills"]], numeric=(3, 4))
                   + "</details></section>")
    out.append("</main><footer>Switchboard · local report · task features and skill ids only, never prompt text · "
               "stickers by fun-isometric (Kelvin Adithya, MIT)</footer>")
    out.append(f"<script>{STICKERS}</script>")
    return "\n".join(out)


def write(inventory: dict, profiles: dict) -> Path:
    out = paths.home() / "report.html"
    paths.write_private(out, render(summarise(inventory, profiles, choices.rows())))
    return out
