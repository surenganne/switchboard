"""Local activity report: one self-contained HTML page built from ~/.switchboard. No network.
The only script is the bundled sticker player (stickers/report.ts), pinned by a CSP hash so nothing else can run."""
from __future__ import annotations

import base64
import hashlib
import html
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from switchboard import choices, hygiene, paths, usage

MAX_WEEKS = 26
TOP_N = 10
KIND_ORDER = {"skill": 0, "command": 1, "agent": 2}
OWN = "(your user and project entries)"  # not a plugin: no settings key to turn off
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


def _weeks(days: list) -> list:
    """(ISO week, count) from the first to the last date, gaps filled, at most MAX_WEEKS."""
    if not days:
        return []
    counts = Counter(_week(d) for d in days)
    first, last = min(days), max(days)
    first = max(first, last - timedelta(weeks=MAX_WEEKS - 1))
    d, out = first - timedelta(days=first.weekday()), []
    while d <= last:
        out.append((_week(d), counts.get(_week(d), 0)))
        d += timedelta(weeks=1)
    return out


def _uses(rows):
    """Usage-log rows with a valid date: (date, id)."""
    out = []
    for r in rows:
        try:
            out.append((datetime.strptime(str(r.get("date")), "%Y-%m-%d").date(), str(r["id"])))
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return out


def _kind(inventory, sid):
    return str(inventory[sid].get("kind", "skill")) if sid in inventory else "removed"


def summarise(inventory: dict, profiles: dict, rows: list, usage_rows=(), mcp=None, recording=True,
              today=None) -> dict:
    """`rows` the choice log, `usage_rows` the usage log, `mcp` {plugin key: MCP server names}."""
    installed = {sid: p for sid, p in profiles.items() if sid in inventory}
    picks = _picks(rows)
    weeks = _weeks([d for d, *_ in picks])
    uses = _uses(usage_rows)
    now = today or date.today()
    start = now - timedelta(days=hygiene.DEFAULT_DAYS)
    used_recent = {sid for d, sid in uses if d > start}
    ran = {(d, sid) for d, sid in uses}
    use_n = Counter(sid for _, sid in uses)

    kinds = Counter(_kind(inventory, s) for s in inventory)
    kinds_prof = Counter(_kind(inventory, s) for s in installed)
    by_kind = [(k, kinds[k], kinds_prof[k]) for k in sorted(kinds, key=lambda k: (KIND_ORDER.get(k, 9), k))]

    plugins: dict = {}
    for sid, rec in inventory.items():
        key = rec.get("plugin_key") or OWN
        p = plugins.setdefault(key, Counter())
        p[_kind(inventory, sid)] += 1
        p["tokens"] += hygiene.tokens(rec)
        p["used"] += sid in used_recent
    by_plugin = sorted(((k, c["skill"], c["command"], c["agent"], c["tokens"], c["used"],
                         c["skill"] + c["command"] + c["agent"], ", ".join((mcp or {}).get(k, [])))
                        for k, c in plugins.items()), key=lambda x: (-x[4], x[0]))

    mixed = {}  # picks where both an agent and a skill/command were offered: which kind won
    for _, cat, off, c in picks:
        ks = {_kind(inventory, x) for x in off}
        if "agent" in ks and ks & {"skill", "command"}:
            m = mixed.setdefault(cat, Counter())
            m["agent" if _kind(inventory, c) == "agent" else "skill"] += 1

    chosen = Counter(c for *_, c in picks)
    offered = Counter(x for _, _, off, _ in picks for x in set(off))
    top = sorted(chosen, key=lambda s: (-chosen[s], s))[:TOP_N]

    cat_picks, cat_over = Counter(), Counter()
    for _, cat, off, c in picks:
        cat_picks[cat] += 1
        cat_over[cat] += bool(off) and c != off[0]

    src_all = Counter(str(r.get("source", "?")) for r in inventory.values())
    src_prof = Counter(str(inventory[s].get("source", "?")) for s in installed)
    src_kind = Counter((str(r.get("source", "?")), _kind(inventory, sid)) for sid, r in inventory.items())
    return {
        "generated": now.isoformat(),
        "skills": len(inventory),
        "profiled": len(installed),
        "stale": sum(1 for s, p in installed.items() if p.get("content_hash") != inventory[s].get("content_hash")),
        "picks": len(picks),
        "overrides": sum(cat_over.values()),
        "weeks": weeks,
        "top_skills": [(s, chosen[s], offered[s]) for s in top],
        "by_category": sorted(((c, cat_picks[c], cat_over[c]) for c in cat_picks), key=lambda x: (-x[1], x[0])),
        "by_source": sorted((s, src_all[s], src_prof[s], *(src_kind[(s, k)] for k in KIND_ORDER)) for s in src_all),
        "audit": choices.audit_rows(rows),
        "profiled_skills": sorted(
            ((s, ", ".join(str(c) for c in (p.get("categories") or [])), str(p.get("does") or ""),
              chosen[s], offered[s], p.get("content_hash") != inventory[s].get("content_hash"), _kind(inventory, s))
             for s, p in installed.items()), key=lambda x: (-x[3], -x[4], x[0])),
        "unprofiled": {k: kinds[k] - kinds_prof[k] for k in kinds if kinds[k] > kinds_prof[k]},
        "kinds": {k: kinds[k] for k in kinds},
        "by_kind": by_kind,
        "recording": recording,
        "uses": len(uses),
        "uses_recent": sum(1 for d, _ in uses if d > start),
        "use_weeks": _weeks([d for d, _ in uses]),
        "top_used": [(s, _kind(inventory, s), use_n[s]) for s in sorted(use_n, key=lambda s: (-use_n[s], s))[:TOP_N]],
        # a pick counts as run when the chosen id shows up in the usage log the same day or the next
        "picks_run": sum(1 for d, _, _, c in picks if (d, c) in ran or (d + timedelta(days=1), c) in ran),
        "window_days": hygiene.DEFAULT_DAYS,
        "by_plugin": by_plugin,
        "tokens": sum(x[4] for x in by_plugin),
        "agent_vs_skill": sorted(((cat, m["agent"] + m["skill"], m["agent"], m["skill"]) for cat, m in mixed.items()),
                                 key=lambda x: (-x[1], x[0])),
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
h3{margin:12px 0 6px;font-size:13px;color:var(--muted)}
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


def _chart(weeks, unit):
    e = html.escape
    peak = max(n for _, n in weeks) or 1
    cols = "".join(f'<div class="col" title="{e(w)}: {n} {unit}"><small>{n or ""}</small>'
                   f'<i style="height:{max(1, round(100 * n / peak))}%"></i></div>' for w, n in weeks)
    return (f'<div class="chart">{cols}</div>'
            f'<div class="axis"><span>{e(weeks[0][0])}</span><span>{e(weeks[-1][0])}</span></div>')


def render(s: dict) -> str:
    """Every value from skills or the log is escaped: skill ids and sources are untrusted text."""
    e = html.escape
    k = s["kinds"]
    tiles = [(s["skills"], f'installed: {k.get("skill", 0)} skills · {k.get("command", 0)} commands · '
                           f'{k.get("agent", 0)} agents', "folder"),
             (f'{s["profiled"]} ({_pct(s["profiled"], s["skills"])})', "profiled", "search"),
             (s["picks"], "picks recorded", "pin"),
             (_pct(s["overrides"], s["picks"]), "picks that passed over the top suggestion", "toggle"),
             (s["uses_recent"] if s["recording"] else "off", f'skill and agent runs in the last {s["window_days"]} days',
              "play"),
             (f'≈ {s["tokens"]:,}', "context tokens to list everything installed", "coins")]
    out = [f'<meta http-equiv="Content-Security-Policy" content="{CSP}">',
           f"<title>Switchboard report</title><style>{CSS}</style>",
           f'<header><h1>Switchboard report</h1><p>Generated {e(s["generated"])} from ~/.switchboard on this machine. '
           "Nothing here leaves your computer.</p></header><main>",
           '<div class="tiles">' + "".join(f'<div class="tile"><div><b>{e(str(v))}</b><span>{e(t)}</span></div>{_st(st)}</div>'
                                           for v, t, st in tiles) + "</div>"]

    todo = sum(s["unprofiled"].values()) + s["stale"]
    if todo:
        parts = [f'{n} {kind}{"s" if n != 1 else ""}' for kind, n in s["unprofiled"].items()]
        new = (f'{sum(s["unprofiled"].values())} have no profile yet ({", ".join(parts)})'
               if s["unprofiled"] else "")
        old = f'{s["stale"]} changed since they were profiled' if s["stale"] else ""
        out.append(f'<section><h2>{_st("bulb")}Profiling needed</h2><p>{e(" and ".join(x for x in (new, old) if x))}. '
                   "Switchboard can only offer an entry once it has a current profile. Run "
                   f"<code>/switchboard:profile</code> (about {todo * 3:,}k tokens, roughly 3k each).</p></section>")
    elif s["skills"]:
        out.append(f'<section><h2>{_st("bulb")}Profiling</h2><p class="empty">All {s["skills"]} entries are '
                   "profiled and up to date.</p></section>")

    if not s["picks"]:
        out.append(f'<section><h2>Activity</h2><p class="empty">{_st("mailbox")}No picks yet. When Switchboard offers you a choice of '
                   "skills and you pick one, it shows up here.</p></section>")
    else:
        out.append(f'<section><h2>{_st("calendar")}Picks per week</h2>{_chart(s["weeks"], "picks")}</section>')
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

    if not s["recording"]:
        used = '<p class="empty">Usage logging is off (<code>record_usage: false</code>), so there is nothing to show.</p>'
    elif not s["uses"]:
        used = (f'<p class="empty">{_st("mailbox")}No runs logged yet. Each time Claude starts a skill or an agent, '
                "it shows up here.</p>")
    else:
        peak = s["top_used"][0][2]
        bars = "".join(f'<div class="hbar" title="{e(sid)} ({e(kind)}): run {n} times"><code>{e(sid)}</code>'
                       f'<div class="track"><i style="width:{round(100 * n / peak)}%"></i></div>'
                       f'<span class="num">{n} · {e(kind)}</span></div>' for sid, kind, n in s["top_used"])
        run = (f'<p class="empty">{s["picks_run"]} of {s["picks"]} picks ({_pct(s["picks_run"], s["picks"])}) were run '
               "the same day or the next.</p>" if s["picks"] else "")
        used = (f'<h3>Runs per week</h3>{_chart(s["use_weeks"], "runs")}<h3>Most run</h3>{bars}{run}')
    out.append(f'<section><h2>{_st("play")}Actual usage</h2><p class="empty">What Claude actually started, whether '
               f"or not Switchboard routed it. Skill and agent ids and dates only.</p>{used}</section>")

    if s["agent_vs_skill"]:
        out.append(f'<section><h2>{_st("chat")}Agents vs skills</h2><p class="empty">Picks where both an agent and '
                   "a skill or command were offered.</p>" + _table(
                       ("Category", "Picks", "Chose an agent", "Chose a skill or command"),
                       s["agent_vs_skill"], numeric=(1, 2, 3)) + "</section>")

    if s["by_plugin"]:
        out.append(f'<section><h2>{_st("coins")}Context cost by plugin</h2><p class="empty">Estimated tokens the '
                   "skill and agent listings take in every session (about 4 characters per token). MCP tool listings "
                   f'and hooks are not counted. "Used" counts entries run in the last {s["window_days"]} days.</p>'
                   + _table(("Plugin", "Skills", "Commands", "Agents", "≈ Tokens", "Used", "MCP servers"),
                            [(key, sk, cm, ag, f"{tok:,}", f"{u} of {n}" if s["recording"] else "–", servers or "–")
                             for key, sk, cm, ag, tok, u, n, servers in s["by_plugin"]], numeric=(1, 2, 3, 4))
                   + "</section>")

    kinds = _table(("Kind", "Installed", "Profiled", "Coverage"),
                   [(kind, n, p, _pct(p, n)) for kind, n, p in s["by_kind"]], numeric=(1, 2, 3))
    coverage = (kinds + _table(("Source", "Skills", "Commands", "Agents", "Profiled", "Coverage"),
                               [(src, sk, cm, ag, p, _pct(p, n)) for src, n, p, sk, cm, ag in s["by_source"]],
                               numeric=(1, 2, 3, 4, 5))
                if s["by_source"] else '<p class="empty">No skills found.</p>')
    stale = (f'<p class="empty">{s["stale"]} profiled skills changed since profiling; '
             "run /switchboard:profile to refresh.</p>" if s["stale"] else "")
    out.append(f"<section><h2>Profiling coverage</h2>{coverage}{stale}</section>")
    if s["profiled_skills"]:
        out.append(f'<section><details><summary><h2 style="display:inline">Profiled skills ({len(s["profiled_skills"])})'
                   '</h2></summary><p class="empty">Most chosen first. Use your browser\'s Find to search. '
                   "* = changed since profiling.</p>" + _table(
                       ("Skill or agent", "Kind", "Categories", "What it does", "Chosen", "Offered"),
                       [(sid + (" *" if old else ""), kind, cats or "–", does or "–", c, o)
                        for sid, cats, does, c, o, old, kind in s["profiled_skills"]], numeric=(4, 5))
                   + "</details></section>")
    out.append("</main><footer>Switchboard · local report · task features and skill ids only, never prompt text · "
               "stickers by fun-isometric (Kelvin Adithya, MIT)</footer>")
    out.append(f"<script>{STICKERS}</script>")
    return "\n".join(out)


def write(inventory: dict, profiles: dict, mcp=None) -> Path:
    out = paths.home() / "report.html"
    on = usage.recording_on()
    paths.write_private(out, render(summarise(inventory, profiles, choices.rows(), usage.rows() if on else [],
                                              mcp, on)))
    return out
