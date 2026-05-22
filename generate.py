#!/usr/bin/env python3
"""
Daily sports box score page generator.
Covers MLB, NHL, NBA, NFL using api-sports.io APIs.
Usage:  python generate.py [YYYY-MM-DD]   (defaults to yesterday)
Output: boxscores/YYYYMMDD.html

Required environment variable:
  API_SPORTS_KEY          Your api-sports.io API key

Optional overrides:
  MLB_LEAGUE_ID           MLB league ID in baseball API   (default: 1)
  NHL_LEAGUE_ID           NHL league ID in hockey API     (default: 57)
  NFL_LEAGUE_ID           NFL league ID in football API   (default: 1)
  NBA_LEAGUE_ID           NBA league slug in NBA API      (default: standard)
  MAX_REQUESTS_PER_SPORT  Daily request cap per sport     (default: 90)

To look up correct league IDs for your account, call the /leagues endpoint on
each sport API, e.g.:  curl -H "x-apisports-key: KEY" https://v1.baseball.api-sports.io/leagues
"""

import sys
import os
import requests
from datetime import date, timedelta

# ── configuration ─────────────────────────────────────────────────────────────

API_KEY = os.environ.get("API_SPORTS_KEY", "")

_BASES = {
    "baseball": "https://v1.baseball.api-sports.io",
    "hockey":   "https://v1.hockey.api-sports.io",
    "nba":      "https://v2.nba.api-sports.io",
    "football": "https://v1.american-football.api-sports.io",
}

MLB_LEAGUE = int(os.environ.get("MLB_LEAGUE_ID", "1"))
NHL_LEAGUE = int(os.environ.get("NHL_LEAGUE_ID", "57"))
NFL_LEAGUE = int(os.environ.get("NFL_LEAGUE_ID", "1"))
NBA_LEAGUE = os.environ.get("NBA_LEAGUE_ID", "standard")

MAX_REQUESTS = int(os.environ.get("MAX_REQUESTS_PER_SPORT", "90"))

# ── request layer ─────────────────────────────────────────────────────────────

_counts = {}

_session = requests.Session()
_session.headers.update({
    "User-Agent": "boxscore-generator/2.0",
    "Accept": "application/json",
})


def _api(sport, path, params=None):
    """Single authenticated call; returns response list or None on failure."""
    if not API_KEY:
        print("  [error] API_SPORTS_KEY is not set.", file=sys.stderr)
        return None
    base = _BASES[sport]
    used = _counts.get(base, 0)
    if used >= MAX_REQUESTS:
        print(f"  [warn] Daily request limit ({MAX_REQUESTS}) reached for {sport}.", file=sys.stderr)
        return None
    try:
        r = _session.get(
            f"{base}{path}",
            params=params,
            timeout=20,
            headers={"x-apisports-key": API_KEY},
        )
        r.raise_for_status()
        _counts[base] = used + 1
        data = r.json()
        errs = data.get("errors", {})
        if errs and errs not in ({}, []):
            print(f"  [warn] API error {path}: {errs}", file=sys.stderr)
        return data.get("response")
    except Exception as e:
        print(f"  [warn] {_BASES[sport]}{path}: {e}", file=sys.stderr)
        return None


# ── season helpers ────────────────────────────────────────────────────────────

def _mlb_season(d: date) -> int:
    return d.year


def _nhl_season(d: date) -> int:
    # NHL season starts in October; 2024-25 season → 2024
    return d.year if d.month >= 9 else d.year - 1


def _nba_season(d: date) -> str:
    # NBA v2 API uses "YYYY-YY" e.g. "2024-25"
    start = d.year if d.month >= 9 else d.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def _nfl_season(d: date) -> int:
    # NFL season starts in September
    return d.year if d.month >= 9 else d.year - 1


# ── misc helpers ──────────────────────────────────────────────────────────────

def fmt_pct(w, l):
    w, l = (w or 0), (l or 0)
    return f"{w/(w+l):.3f}".lstrip("0") if (w + l) else ".000"


def _pad(lst, n):
    return list(lst) + [""] * (n - len(lst))


# ── MLB ───────────────────────────────────────────────────────────────────────

def mlb_games(d: date):
    items = _api("baseball", "/games", {
        "date": d.isoformat(),
        "league": MLB_LEAGUE,
        "season": _mlb_season(d),
    })
    if not items:
        return []
    return [p for g in items
            if g.get("status", {}).get("short") == "FT"
            for p in [_parse_mlb_game(g)] if p]


def _parse_mlb_game(g):
    teams = g.get("teams", {})
    sc = g.get("scores", {})
    hs, as_ = sc.get("home", {}), sc.get("away", {})
    h_inn = hs.get("innings") or {}
    a_inn = as_.get("innings") or {}

    num_keys = sorted([k for k in h_inn if k != "extra"], key=int)
    has_extra = h_inn.get("extra") is not None or a_inn.get("extra") is not None

    labels = num_keys[:]
    a_line = ["" if a_inn.get(k) is None else str(a_inn[k]) for k in num_keys]
    h_line = ["" if h_inn.get(k) is None else str(h_inn[k]) for k in num_keys]

    if has_extra:
        labels.append("E")
        a_line.append("" if a_inn.get("extra") is None else str(a_inn["extra"]))
        h_line.append("" if h_inn.get("extra") is None else str(h_inn["extra"]))

    while len(labels) < 9:
        labels.append(str(len(labels) + 1))
        a_line.append("")
        h_line.append("")

    return {
        "sport": "MLB",
        "away_name": teams.get("away", {}).get("name", "Away"),
        "home_name": teams.get("home", {}).get("name", "Home"),
        "away_score": as_.get("total", ""),
        "home_score": hs.get("total", ""),
        "inning_labels": labels,
        "away_line": a_line,
        "home_line": h_line,
        "away_rhe": [as_.get("total", ""), as_.get("hits", ""), as_.get("errors", "")],
        "home_rhe": [hs.get("total", ""), hs.get("hits", ""), hs.get("errors", "")],
        "away_batters": [],
        "home_batters": [],
        "away_pitchers": [],
        "home_pitchers": [],
        "venue": (g.get("venue") or {}).get("name", ""),
    }


def mlb_standings(d: date):
    items = _api("baseball", "/standings", {
        "league": MLB_LEAGUE,
        "season": _mlb_season(d),
    })
    if not items:
        return {}

    divisions = {}
    for entry in items:
        for group in entry.get("standings", []):
            for rec in (group if isinstance(group, list) else [group]):
                div = (rec.get("group") or {}).get("name", "")
                if not div:
                    continue
                w = (rec.get("all") or {}).get("win", 0)
                l = (rec.get("all") or {}).get("lose", 0)
                divisions.setdefault(div, []).append({
                    "name": (rec.get("team") or {}).get("name", ""),
                    "w": w, "l": l,
                    "pct": fmt_pct(w, l),
                    "gb": "-",
                    "strk": (rec.get("form") or "")[-1:] or "-",
                })

    # Compute GB from division leader
    for teams in divisions.values():
        teams.sort(key=lambda t: (-t["w"], t["l"]))
        lw, ll = teams[0]["w"], teams[0]["l"]
        for t in teams:
            gb = ((lw - t["w"]) + (t["l"] - ll)) / 2
            t["gb"] = "-" if gb == 0 else (str(int(gb)) if gb == int(gb) else str(gb))

    div_order = ["AL East", "AL Central", "AL West", "NL East", "NL Central", "NL West"]
    return {k: divisions[k] for k in div_order if k in divisions} | \
           {k: v for k, v in divisions.items() if k not in div_order}


# ── NHL ───────────────────────────────────────────────────────────────────────

_HOCKEY_FINAL = {"FT", "AOT", "AET", "After OT", "After ET", "Finished"}


def nhl_games(d: date):
    items = _api("hockey", "/games", {
        "date": d.isoformat(),
        "league": NHL_LEAGUE,
        "season": _nhl_season(d),
    })
    if not items:
        return []
    return [p for g in items
            if g.get("status", {}).get("short") in _HOCKEY_FINAL
            for p in [_parse_nhl_game(g)] if p]


def _parse_nhl_game(g):
    teams = g.get("teams", {})
    sc = g.get("scores", {})
    hs, as_ = sc.get("home", {}), sc.get("away", {})

    labels = ["1", "2", "3"]
    a_line = [str(as_.get("period_1", 0)), str(as_.get("period_2", 0)), str(as_.get("period_3", 0))]
    h_line = [str(hs.get("period_1", 0)), str(hs.get("period_2", 0)), str(hs.get("period_3", 0))]

    ot_note = ""
    status_short = g.get("status", {}).get("short", "")
    if status_short in ("AOT", "AET", "After OT", "After ET") or as_.get("overtime") is not None:
        labels.append("OT")
        a_line.append(str(as_.get("overtime", 0)))
        h_line.append(str(hs.get("overtime", 0)))
        ot_note = "OT"

    return {
        "sport": "NHL",
        "away_name": teams.get("away", {}).get("name", "Away"),
        "home_name": teams.get("home", {}).get("name", "Home"),
        "away_score": as_.get("total", ""),
        "home_score": hs.get("total", ""),
        "period_labels": labels,
        "away_line": a_line,
        "home_line": h_line,
        "ot_note": ot_note,
        "team_stats_rows": _nhl_team_stats(g.get("id"), teams),
        "venue": (g.get("venue") or {}).get("name", ""),
    }


def _nhl_team_stats(game_id, teams):
    if not game_id:
        return []
    items = _api("hockey", "/games/statistics", {"id": game_id})
    if not items or len(items) < 2:
        return []

    away_name = teams.get("away", {}).get("name", "")
    home_name = teams.get("home", {}).get("name", "")

    def to_dict(entry):
        return {s.get("type", s.get("name", "")): s.get("value", "")
                for s in entry.get("statistics", [])}

    by_team = {e.get("team", {}).get("name", ""): to_dict(e) for e in items}
    vals = list(by_team.values())
    away_st = by_team.get(away_name) or (vals[0] if vals else {})
    home_st = by_team.get(home_name) or (vals[-1] if vals else {})

    priority = ["Shots on Goal", "Power Plays", "Penalty Minutes",
                "Face Off %", "Hits", "Blocked Shots", "Giveaways", "Takeaways"]
    all_keys = set(away_st) | set(home_st)
    rows = [{"label": k, "away": away_st.get(k, "-"), "home": home_st.get(k, "-")}
            for k in priority if k in all_keys]
    rows += [{"label": k, "away": away_st.get(k, "-"), "home": home_st.get(k, "-")}
             for k in sorted(all_keys - set(priority))]
    return rows


def nhl_standings(d: date):
    items = _api("hockey", "/standings", {
        "league": NHL_LEAGUE,
        "season": _nhl_season(d),
    })
    if not items:
        return {}

    divisions = {}
    for entry in items:
        for group in entry.get("standings", [[]]):
            for rec in (group if isinstance(group, list) else [group]):
                div = (rec.get("group") or {}).get("name", "")
                if not div:
                    continue
                w = (rec.get("all") or {}).get("win", 0)
                l = (rec.get("all") or {}).get("lose", 0)
                otl = (rec.get("all") or {}).get("draw", 0)
                divisions.setdefault(div, []).append({
                    "name": (rec.get("team") or {}).get("name", ""),
                    "w": w, "l": l, "otl": otl,
                    "pts": w * 2 + otl,
                    "strk": (rec.get("form") or "")[-1:] or "-",
                })

    div_order = ["Atlantic", "Metropolitan", "Central", "Pacific"]
    ordered = {}
    for d_name in div_order:
        for k in divisions:
            if d_name.lower() in k.lower():
                ordered[k] = sorted(divisions[k], key=lambda t: -t["pts"])
                break
    for k, v in divisions.items():
        if k not in ordered:
            ordered[k] = sorted(v, key=lambda t: -t["pts"])
    return ordered


# ── NBA ───────────────────────────────────────────────────────────────────────

def nba_games(d: date):
    items = _api("nba", "/games", {
        "date": d.isoformat(),
        "league": NBA_LEAGUE,
        "season": _nba_season(d),
    })
    if not items:
        return []
    games = []
    for g in items:
        short = g.get("status", {}).get("short")
        if short != 3 and str(short) != "3":
            continue
        p = _parse_nba_game(g)
        if p:
            games.append(p)
    return games


def _parse_nba_game(g):
    teams = g.get("teams", {})
    sc = g.get("scores", {})
    vis, home = teams.get("visitors", {}), teams.get("home", {})
    vis_sc, home_sc = sc.get("visitors", {}), sc.get("home", {})

    vis_ls = vis_sc.get("linescore", [])
    home_ls = home_sc.get("linescore", [])
    n = max(len(vis_ls), len(home_ls), 4)

    labels = ["1", "2", "3", "4"] + (["OT"] if n == 5 else [f"OT{i}" for i in range(1, n - 3)] if n > 5 else [])
    a_line = _pad(vis_ls, n)
    h_line = _pad(home_ls, n)

    game_id = g.get("id")
    away_players, home_players = _nba_player_stats(game_id, vis.get("id"), home.get("id"))

    return {
        "sport": "NBA",
        "away_name": f"{vis.get('city', '')} {vis.get('name', '')}".strip(),
        "home_name": f"{home.get('city', '')} {home.get('name', '')}".strip(),
        "away_score": vis_sc.get("points", ""),
        "home_score": home_sc.get("points", ""),
        "period_labels": labels,
        "away_line": a_line,
        "home_line": h_line,
        "away_players": away_players,
        "home_players": home_players,
    }


def _nba_player_stats(game_id, away_id, home_id):
    if not game_id:
        return [], []
    items = _api("nba", "/players/statistics", {"game": game_id})
    if not items:
        return [], []

    away_players, home_players = [], []
    for p in items:
        mins = p.get("min") or ""
        if not mins or mins in ("0:00", "0", ""):
            continue
        player = p.get("player", {})
        name = f"{player.get('firstname', '')} {player.get('lastname', '')}".strip()
        row = {
            "name": name,
            "pos":  p.get("pos", ""),
            "pts":  p.get("points", 0) or 0,
            "reb":  p.get("totReb", 0) or 0,
            "ast":  p.get("assists", 0) or 0,
            "fg":   f"{p.get('fgm', 0)}-{p.get('fga', 0)}",
            "3p":   f"{p.get('tpm', 0)}-{p.get('tpa', 0)}",
            "ft":   f"{p.get('ftm', 0)}-{p.get('fta', 0)}",
        }
        tid = (p.get("team") or {}).get("id")
        if tid == away_id:
            away_players.append(row)
        elif tid == home_id:
            home_players.append(row)

    away_players.sort(key=lambda x: -x["pts"])
    home_players.sort(key=lambda x: -x["pts"])
    return away_players, home_players


def nba_standings(d: date):
    items = _api("nba", "/standings", {
        "league": NBA_LEAGUE,
        "season": _nba_season(d),
    })
    if not items:
        return {}

    confs = {}
    for entry in items:
        conf = (entry.get("conference") or {}).get("name", "").lower()
        label = conf.capitalize() + "ern Conference"
        w = (entry.get("win") or {}).get("total", 0) or 0
        l = (entry.get("loss") or {}).get("total", 0) or 0
        gb = entry.get("gamesBehind")
        streak_n = entry.get("streak")
        win_streak = entry.get("winStreak")
        strk = (("W" if win_streak else "L") + str(streak_n)) if streak_n else "-"
        confs.setdefault(label, []).append({
            "name": (entry.get("team") or {}).get("name", ""),
            "w": w, "l": l,
            "pct": fmt_pct(w, l),
            "gb": "-" if not gb else str(gb),
            "strk": strk,
        })

    ordered = {}
    for c in ["east", "west"]:
        label = c.capitalize() + "ern Conference"
        if label in confs:
            ordered[label] = sorted(confs[label], key=lambda t: (-t["w"], t["l"]))
    for k, v in confs.items():
        if k not in ordered:
            ordered[k] = sorted(v, key=lambda t: (-t["w"], t["l"]))
    return ordered


# ── NFL ───────────────────────────────────────────────────────────────────────

def nfl_games(d: date):
    items = _api("football", "/games", {
        "date": d.isoformat(),
        "league": NFL_LEAGUE,
        "season": _nfl_season(d),
    })
    if not items:
        return []
    return [p for g in items
            if g.get("status", {}).get("short") == "FT"
            for p in [_parse_nfl_game(g)] if p]


def _parse_nfl_game(g):
    teams = g.get("teams", {})
    sc = g.get("scores", {})
    hs, as_ = sc.get("home", {}), sc.get("away", {})

    labels = ["1", "2", "3", "4"]
    a_line = [str(as_.get(f"quarter_{i}") or "") for i in range(1, 5)]
    h_line = [str(hs.get(f"quarter_{i}") or "") for i in range(1, 5)]

    ot_note = ""
    if as_.get("overtime") is not None:
        labels.append("OT")
        a_line.append(str(as_.get("overtime", 0)))
        h_line.append(str(hs.get("overtime", 0)))
        ot_note = "OT"

    return {
        "sport": "NFL",
        "away_name": teams.get("away", {}).get("name", "Away"),
        "home_name": teams.get("home", {}).get("name", "Home"),
        "away_score": as_.get("total", ""),
        "home_score": hs.get("total", ""),
        "period_labels": labels,
        "away_line": a_line,
        "home_line": h_line,
        "ot_note": ot_note,
        "team_stats_rows": _nfl_team_stats(g.get("id"), teams),
        "venue": (g.get("venue") or {}).get("name", ""),
    }


def _nfl_team_stats(game_id, teams):
    if not game_id:
        return []
    items = _api("football", "/games/statistics", {"id": game_id})
    if not items or len(items) < 2:
        return []

    away_name = teams.get("away", {}).get("name", "")
    home_name = teams.get("home", {}).get("name", "")

    def flatten(entry):
        flat = {}
        for group in entry.get("statistics", []):
            for stat in (group.get("statistics") or []):
                flat[stat.get("name", "")] = stat.get("value", "")
        return flat

    by_team = {e.get("team", {}).get("name", ""): flatten(e) for e in items}
    vals = list(by_team.values())
    away_st = by_team.get(away_name) or (vals[0] if vals else {})
    home_st = by_team.get(home_name) or (vals[-1] if vals else {})

    priority = ["Total Yards", "Passing Yards", "Rushing Yards", "First Downs",
                "Third Down Efficiency", "Turnovers", "Sacks",
                "Penalties", "Time of Possession", "Yards Per Play"]
    all_keys = set(away_st) | set(home_st)
    rows = [{"label": k, "away": away_st.get(k, "-"), "home": home_st.get(k, "-")}
            for k in priority if k in all_keys]
    rows += [{"label": k, "away": away_st.get(k, "-"), "home": home_st.get(k, "-")}
             for k in sorted(all_keys - set(priority))]
    return rows


def nfl_standings(d: date):
    items = _api("football", "/standings", {
        "league": NFL_LEAGUE,
        "season": _nfl_season(d),
    })
    if not items:
        return {}

    divisions = {}
    for entry in items:
        conf = (entry.get("conference") or {}).get("name", "")
        div  = (entry.get("division") or {}).get("name", "")
        key  = f"{conf} {div}".strip() if conf or div else "Unknown"
        won  = entry.get("won", 0) or 0
        lost = entry.get("lost", 0) or 0
        ties = entry.get("ties", 0) or 0
        strk = entry.get("streak") or {}
        divisions.setdefault(key, []).append({
            "name": (entry.get("team") or {}).get("name", ""),
            "w": won, "l": lost, "t": ties,
            "pct": entry.get("pct") or fmt_pct(won, lost),
            "pf":  entry.get("points_for", ""),
            "pa":  entry.get("points_against", ""),
            "strk": (strk.get("type", "") + str(strk.get("count", ""))) if strk else "-",
        })

    div_order = ["AFC East", "AFC North", "AFC South", "AFC West",
                 "NFC East", "NFC North", "NFC South", "NFC West"]
    ordered = {k: divisions[k] for k in div_order if k in divisions}
    for k, v in divisions.items():
        if k not in ordered:
            ordered[k] = v
    return ordered


# ── HTML rendering ────────────────────────────────────────────────────────────

CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #f9f7f1;
  --text: #111;
  --border: #111;
  --border-light: #bbb;
  --header-bg: #111;
  --header-fg: #f9f7f1;
  --row-alt: #eeeae0;
  --subhead-bg: #ddd;
  --sport-tag-bg: #111;
  --sport-tag-fg: #f9f7f1;
  --font: "Source Sans 3", "Source Sans Pro", "Helvetica Neue", Arial, sans-serif;
}

body.dark {
  --bg: #121212;
  --text: #e0e0e0;
  --border: #555;
  --border-light: #333;
  --header-bg: #1e1e1e;
  --header-fg: #e0e0e0;
  --row-alt: #1a1a1a;
  --subhead-bg: #2a2a2a;
  --sport-tag-bg: #2a2a2a;
  --sport-tag-fg: #e0e0e0;
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font);
  font-size: 13px;
  line-height: 1.4;
}

a { color: inherit; text-decoration: none; }
a:hover { text-decoration: underline; }

/* ── page header ── */
.page-header {
  border-bottom: 3px double var(--border);
  padding: 10px 16px 8px;
  text-align: center;
}
.site-title {
  font-size: 38px;
  font-weight: 900;
  letter-spacing: -1px;
  text-transform: uppercase;
  line-height: 1;
}
.page-date {
  font-size: 15px;
  letter-spacing: 2px;
  margin-top: 2px;
  text-transform: uppercase;
}
.nav-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 16px;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  gap: 8px;
}
.nav-row a, .nav-row button {
  background: none;
  border: 1px solid var(--border);
  color: var(--text);
  cursor: pointer;
  font-family: var(--font);
  font-size: 12px;
  padding: 2px 8px;
}
.nav-row a:hover, .nav-row button:hover { background: var(--border); color: var(--bg); text-decoration: none; }

.sport-tabs {
  display: flex;
  gap: 0;
  border-bottom: 2px solid var(--border);
  padding: 0 16px;
  overflow-x: auto;
}
.sport-tab {
  padding: 5px 14px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 1px;
  text-transform: uppercase;
  cursor: pointer;
  border: none;
  background: none;
  color: var(--text);
  border-bottom: 3px solid transparent;
  margin-bottom: -2px;
  white-space: nowrap;
  font-family: var(--font);
}
.sport-tab.active {
  border-bottom-color: var(--border);
}

/* ── main layout ── */
.main {
  display: flex;
  gap: 0;
}
.games-col {
  flex: 1 1 0;
  min-width: 0;
  padding: 12px 16px;
  border-right: 1px solid var(--border-light);
}
.sidebar {
  width: 260px;
  flex-shrink: 0;
  padding: 12px 12px;
}

/* ── section title ── */
.section-title {
  font-size: 18px;
  font-weight: 900;
  text-transform: uppercase;
  letter-spacing: 1px;
  border-bottom: 2px solid var(--border);
  padding-bottom: 3px;
  margin-bottom: 10px;
}
.subsection-title {
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1px;
  background: var(--subhead-bg);
  padding: 2px 6px;
  margin: 10px 0 4px;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
}

/* ── games grid ── */
.games-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
}
.game-box {
  border: 1px solid var(--border);
}
.game-header {
  background: var(--header-bg);
  color: var(--header-fg);
  display: grid;
  padding: 4px 8px;
  font-size: 13px;
}
.game-matchup {
  display: flex;
  justify-content: space-between;
  font-weight: 700;
}
.team-name { flex: 1; }
.team-score { font-size: 16px; font-weight: 900; padding-left: 8px; }
.team-score.winner { font-size: 18px; }
.game-meta { font-size: 10px; opacity: 0.8; margin-top: 1px; }

/* ── line score ── */
.linescore-wrap { overflow-x: auto; }
table.linescore {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}
table.linescore th, table.linescore td {
  text-align: right;
  padding: 2px 4px;
  border-left: 1px solid var(--border-light);
  white-space: nowrap;
  min-width: 18px;
}
table.linescore th:first-child, table.linescore td:first-child {
  text-align: left;
  border-left: none;
  font-weight: 700;
  min-width: 90px;
}
table.linescore thead th { background: var(--subhead-bg); font-weight: 700; }
table.linescore .rhe { border-left: 2px solid var(--border); font-weight: 700; }
table.linescore .total { font-weight: 900; }

/* ── stat tables ── */
table.stats {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
  margin-top: 4px;
}
table.stats th {
  background: var(--subhead-bg);
  padding: 2px 4px;
  text-align: right;
  font-weight: 700;
  border-bottom: 1px solid var(--border);
}
table.stats th:first-child { text-align: left; }
table.stats td {
  padding: 2px 4px;
  text-align: right;
  border-bottom: 1px solid var(--border-light);
}
table.stats td:first-child { text-align: left; }
table.stats tr:nth-child(even) td { background: var(--row-alt); }
table.stats tr.total td { font-weight: 700; border-top: 1px solid var(--border); }
table.stats tr.total td:first-child { font-weight: 900; }

/* ── standings ── */
.standings-block { margin-bottom: 16px; }
table.standings {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}
table.standings th {
  background: var(--header-bg);
  color: var(--header-fg);
  padding: 2px 4px;
  text-align: right;
  font-size: 10px;
  font-weight: 700;
}
table.standings th:first-child { text-align: left; }
table.standings td {
  padding: 2px 4px;
  text-align: right;
  border-bottom: 1px solid var(--border-light);
}
table.standings td:first-child { text-align: left; font-weight: 600; }
table.standings tr:nth-child(even) td { background: var(--row-alt); }
.div-title {
  font-size: 11px;
  font-weight: 900;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 4px 4px 2px;
  border-top: 2px solid var(--border);
  margin-top: 8px;
}
.div-title:first-child { border-top: 1px solid var(--border); margin-top: 0; }

/* ── sport section ── */
.sport-section { display: none; }
.sport-section.active { display: block; }

/* ── no games ── */
.no-games { color: #888; font-style: italic; padding: 20px 0; }

/* ── sport badge in multi-sport view ── */
.sport-badge {
  display: inline-block;
  font-size: 9px;
  font-weight: 900;
  letter-spacing: 1px;
  padding: 1px 5px;
  background: var(--sport-tag-bg);
  color: var(--sport-tag-fg);
  vertical-align: middle;
  margin-right: 4px;
}

@media (max-width: 900px) {
  .main { flex-direction: column; }
  .sidebar { width: 100%; border-top: 2px solid var(--border); }
  .games-col { border-right: none; }
  .games-grid { grid-template-columns: 1fr; }
  .site-title { font-size: 26px; }
}

@media print {
  .nav-row, .sport-tabs, body { font-size: 10px; }
  .sport-section { display: block !important; }
  .page-header { border-bottom: 2px solid #000; }
}
"""

JS = """
(function() {
  // dark mode
  var dm = document.getElementById('dark-toggle');
  function applyDark(on) {
    document.body.classList.toggle('dark', on);
    dm.textContent = on ? 'Light Mode' : 'Dark Mode';
    localStorage.setItem('dark', on ? '1' : '');
  }
  applyDark(localStorage.getItem('dark') === '1');
  dm.addEventListener('click', function() { applyDark(!document.body.classList.contains('dark')); });

  // sport tabs
  document.querySelectorAll('.sport-tab').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var sport = btn.dataset.sport;
      document.querySelectorAll('.sport-tab').forEach(function(b) { b.classList.remove('active'); });
      document.querySelectorAll('.sport-section').forEach(function(s) { s.classList.remove('active'); });
      btn.classList.add('active');
      document.querySelectorAll('.sport-section[data-sport="' + sport + '"]').forEach(function(s) { s.classList.add('active'); });
    });
  });

  // activate first tab with content
  var firstActive = document.querySelector('.sport-tab');
  if (firstActive) firstActive.click();
})();
"""


def h(text):
    """HTML escape."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_mlb_game(g):
    il = g["inning_labels"]
    al = g["away_line"]
    hl = g["home_line"]
    ar = g["away_rhe"]
    hr = g["home_rhe"]
    aw = int(g["away_score"]) > int(g["home_score"]) if str(g["away_score"]).isdigit() and str(g["home_score"]).isdigit() else False
    hw = not aw

    headers = "".join(f"<th>{h(x)}</th>" for x in il)
    away_cells = "".join(f"<td>{h(x)}</td>" for x in al)
    home_cells = "".join(f"<td>{h(x)}</td>" for x in hl)

    ls = f"""
    <div class="linescore-wrap">
    <table class="linescore">
      <thead><tr><th></th>{headers}<th class="rhe">R</th><th class="rhe">H</th><th class="rhe">E</th></tr></thead>
      <tbody>
        <tr><td class="{'total' if aw else ''}">{h(g['away_name'])}</td>{away_cells}
          <td class="rhe total">{h(ar[0])}</td><td class="rhe">{h(ar[1])}</td><td class="rhe">{h(ar[2])}</td></tr>
        <tr><td class="{'total' if hw else ''}">{h(g['home_name'])}</td>{home_cells}
          <td class="rhe total">{h(hr[0])}</td><td class="rhe">{h(hr[1])}</td><td class="rhe">{h(hr[2])}</td></tr>
      </tbody>
    </table></div>"""

    def batter_rows(batters):
        rows = ""
        for b in batters:
            cls = ' class="total"' if b.get("total") else ""
            name_cell = h(b["name"]) + (f" <em>{h(b['pos'])}</em>" if b.get("pos") else "")
            rows += f'<tr{cls}><td>{name_cell}</td><td>{h(b["ab"])}</td><td>{h(b["r"])}</td><td>{h(b["h"])}</td><td>{h(b["rbi"])}</td><td>{h(b["bb"])}</td><td>{h(b["so"])}</td><td>{h(b["avg"])}</td></tr>'
        return rows

    def pitcher_rows(pitchers):
        rows = ""
        for p in pitchers:
            note = f' <b>{h(p["note"])}</b>' if p.get("note") else ""
            rows += f'<tr><td>{h(p["name"])}{note}</td><td>{h(p["ip"])}</td><td>{h(p["h"])}</td><td>{h(p["r"])}</td><td>{h(p["er"])}</td><td>{h(p["bb"])}</td><td>{h(p["so"])}</td><td>{h(p["era"])}</td></tr>'
        return rows

    batting_html = ""
    if g["away_batters"] or g["home_batters"]:
        batting_html = f"""
        <div class="subsection-title">{h(g['away_name'])} Batting</div>
        <table class="stats"><thead><tr><th>Batter</th><th>AB</th><th>R</th><th>H</th><th>RBI</th><th>BB</th><th>SO</th><th>AVG</th></tr></thead>
        <tbody>{batter_rows(g['away_batters'])}</tbody></table>
        <div class="subsection-title">{h(g['home_name'])} Batting</div>
        <table class="stats"><thead><tr><th>Batter</th><th>AB</th><th>R</th><th>H</th><th>RBI</th><th>BB</th><th>SO</th><th>AVG</th></tr></thead>
        <tbody>{batter_rows(g['home_batters'])}</tbody></table>"""

    pitching_html = ""
    if g["away_pitchers"] or g["home_pitchers"]:
        pitching_html = f"""
        <div class="subsection-title">{h(g['away_name'])} Pitching</div>
        <table class="stats"><thead><tr><th>Pitcher</th><th>IP</th><th>H</th><th>R</th><th>ER</th><th>BB</th><th>SO</th><th>ERA</th></tr></thead>
        <tbody>{pitcher_rows(g['away_pitchers'])}</tbody></table>
        <div class="subsection-title">{h(g['home_name'])} Pitching</div>
        <table class="stats"><thead><tr><th>Pitcher</th><th>IP</th><th>H</th><th>R</th><th>ER</th><th>BB</th><th>SO</th><th>ERA</th></tr></thead>
        <tbody>{pitcher_rows(g['home_pitchers'])}</tbody></table>"""

    venue = f'<div class="game-meta">{h(g["venue"])}</div>' if g.get("venue") else ""
    aw_cls = " winner" if aw else ""
    hw_cls = " winner" if hw else ""

    return f"""
    <div class="game-box">
      <div class="game-header">
        <div class="game-matchup"><span class="team-name">{h(g['away_name'])}</span><span class="team-score{aw_cls}">{h(g['away_score'])}</span></div>
        <div class="game-matchup"><span class="team-name">{h(g['home_name'])}</span><span class="team-score{hw_cls}">{h(g['home_score'])}</span></div>
        {venue}
      </div>
      {ls}
      {batting_html}
      {pitching_html}
    </div>"""


def render_nhl_game(g):
    pl = g["period_labels"]
    al = g["away_line"]
    hl = g["home_line"]
    aw_score = int(g["away_score"]) if str(g["away_score"]).isdigit() else 0
    hw_score = int(g["home_score"]) if str(g["home_score"]).isdigit() else 0
    aw = aw_score > hw_score
    hw = not aw

    headers = "".join(f"<th>{h(x)}</th>" for x in pl)
    away_cells = "".join(f"<td>{h(x)}</td>" for x in al)
    home_cells = "".join(f"<td>{h(x)}</td>" for x in hl)
    ot = f" <small>({h(g['ot_note'])})</small>" if g.get("ot_note") else ""

    ls = f"""
    <div class="linescore-wrap">
    <table class="linescore">
      <thead><tr><th></th>{headers}<th class="rhe">F</th></tr></thead>
      <tbody>
        <tr><td class="{'total' if aw else ''}">{h(g['away_name'])}</td>{away_cells}<td class="rhe total">{h(g['away_score'])}</td></tr>
        <tr><td class="{'total' if hw else ''}">{h(g['home_name'])}</td>{home_cells}<td class="rhe total">{h(g['home_score'])}{ot}</td></tr>
      </tbody>
    </table></div>"""

    stats_html = render_team_stats_table(g.get("team_stats_rows", []), g["away_name"], g["home_name"])
    venue = f'<div class="game-meta">{h(g["venue"])}</div>' if g.get("venue") else ""
    aw_cls = " winner" if aw else ""
    hw_cls = " winner" if hw else ""

    return f"""
    <div class="game-box">
      <div class="game-header">
        <div class="game-matchup"><span class="team-name">{h(g['away_name'])}</span><span class="team-score{aw_cls}">{h(g['away_score'])}</span></div>
        <div class="game-matchup"><span class="team-name">{h(g['home_name'])}</span><span class="team-score{hw_cls}">{h(g['home_score'])}</span></div>
        {venue}
      </div>
      {ls}
      {stats_html}
    </div>"""


def render_nba_game(g):
    pl = g["period_labels"]
    al = g["away_line"]
    hl = g["home_line"]
    aw_score = int(g["away_score"]) if str(g["away_score"]).isdigit() else 0
    hw_score = int(g["home_score"]) if str(g["home_score"]).isdigit() else 0
    aw = aw_score > hw_score
    hw = not aw

    headers = "".join(f"<th>{h(x)}</th>" for x in pl)
    away_cells = "".join(f"<td>{h(x)}</td>" for x in al)
    home_cells = "".join(f"<td>{h(x)}</td>" for x in hl)

    ls = f"""
    <div class="linescore-wrap">
    <table class="linescore">
      <thead><tr><th></th>{headers}<th class="rhe">F</th></tr></thead>
      <tbody>
        <tr><td class="{'total' if aw else ''}">{h(g['away_name'])}</td>{away_cells}<td class="rhe total">{h(g['away_score'])}</td></tr>
        <tr><td class="{'total' if hw else ''}">{h(g['home_name'])}</td>{home_cells}<td class="rhe total">{h(g['home_score'])}</td></tr>
      </tbody>
    </table></div>"""

    players_html = ""
    if g.get("away_players") or g.get("home_players"):
        def p_rows(players):
            rows = ""
            for p in players[:12]:
                rows += f'<tr><td>{h(p["name"])} <em>{h(p["pos"])}</em></td><td>{h(p["pts"])}</td><td>{h(p["reb"])}</td><td>{h(p["ast"])}</td><td>{h(p["fg"])}</td><td>{h(p["3p"])}</td><td>{h(p["ft"])}</td></tr>'
            return rows

        players_html = f"""
        <div class="subsection-title">{h(g['away_name'])}</div>
        <table class="stats"><thead><tr><th>Player</th><th>PTS</th><th>REB</th><th>AST</th><th>FG</th><th>3P</th><th>FT</th></tr></thead>
        <tbody>{p_rows(g.get('away_players', []))}</tbody></table>
        <div class="subsection-title">{h(g['home_name'])}</div>
        <table class="stats"><thead><tr><th>Player</th><th>PTS</th><th>REB</th><th>AST</th><th>FG</th><th>3P</th><th>FT</th></tr></thead>
        <tbody>{p_rows(g.get('home_players', []))}</tbody></table>"""

    aw_cls = " winner" if aw else ""
    hw_cls = " winner" if hw else ""

    return f"""
    <div class="game-box">
      <div class="game-header">
        <div class="game-matchup"><span class="team-name">{h(g['away_name'])}</span><span class="team-score{aw_cls}">{h(g['away_score'])}</span></div>
        <div class="game-matchup"><span class="team-name">{h(g['home_name'])}</span><span class="team-score{hw_cls}">{h(g['home_score'])}</span></div>
      </div>
      {ls}
      {players_html}
    </div>"""


def render_nfl_game(g):
    pl = g["period_labels"]
    al = g["away_line"]
    hl = g["home_line"]
    aw_score = int(g["away_score"]) if str(g["away_score"]).isdigit() else 0
    hw_score = int(g["home_score"]) if str(g["home_score"]).isdigit() else 0
    aw = aw_score > hw_score
    hw = not aw

    headers = "".join(f"<th>{h(x)}</th>" for x in pl)
    away_cells = "".join(f"<td>{h(x)}</td>" for x in al)
    home_cells = "".join(f"<td>{h(x)}</td>" for x in hl)
    ot = f" <small>({h(g['ot_note'])})</small>" if g.get("ot_note") else ""

    ls = f"""
    <div class="linescore-wrap">
    <table class="linescore">
      <thead><tr><th></th>{headers}<th class="rhe">F</th></tr></thead>
      <tbody>
        <tr><td class="{'total' if aw else ''}">{h(g['away_name'])}</td>{away_cells}<td class="rhe total">{h(g['away_score'])}</td></tr>
        <tr><td class="{'total' if hw else ''}">{h(g['home_name'])}</td>{home_cells}<td class="rhe total">{h(g['home_score'])}{ot}</td></tr>
      </tbody>
    </table></div>"""

    stats_html = render_team_stats_table(g.get("team_stats_rows", []), g["away_name"], g["home_name"])
    venue = f'<div class="game-meta">{h(g["venue"])}</div>' if g.get("venue") else ""
    aw_cls = " winner" if aw else ""
    hw_cls = " winner" if hw else ""

    return f"""
    <div class="game-box">
      <div class="game-header">
        <div class="game-matchup"><span class="team-name">{h(g['away_name'])}</span><span class="team-score{aw_cls}">{h(g['away_score'])}</span></div>
        <div class="game-matchup"><span class="team-name">{h(g['home_name'])}</span><span class="team-score{hw_cls}">{h(g['home_score'])}{ot}</span></div>
        {venue}
      </div>
      {ls}
      {stats_html}
    </div>"""


def render_team_stats_table(rows, away_name, home_name):
    """Shared renderer for NHL/NFL side-by-side team stat comparison."""
    if not rows:
        return ""
    tbody = "".join(
        f'<tr><td>{h(r["label"])}</td><td>{h(r["away"])}</td><td>{h(r["home"])}</td></tr>'
        for r in rows
    )
    return f"""
    <div class="subsection-title">Team Stats</div>
    <table class="stats">
      <thead><tr><th>Stat</th><th>{h(away_name)}</th><th>{h(home_name)}</th></tr></thead>
      <tbody>{tbody}</tbody>
    </table>"""


def render_mlb_standings(standings):
    if not standings:
        return ""
    out = '<div class="subsection-title">MLB Standings</div>'
    for div_name, teams in standings.items():
        out += f'<div class="div-title">{h(div_name)}</div>'
        out += '<table class="standings"><thead><tr><th>Team</th><th>W</th><th>L</th><th>PCT</th><th>GB</th><th>STK</th></tr></thead><tbody>'
        for t in teams:
            out += f'<tr><td>{h(t["name"])}</td><td>{h(t["w"])}</td><td>{h(t["l"])}</td><td>{h(t["pct"])}</td><td>{h(t["gb"])}</td><td>{h(t["strk"])}</td></tr>'
        out += "</tbody></table>"
    return out


def render_nhl_standings(standings):
    if not standings:
        return ""
    out = '<div class="subsection-title">NHL Standings</div>'
    for div_name, teams in standings.items():
        out += f'<div class="div-title">{h(div_name)}</div>'
        out += '<table class="standings"><thead><tr><th>Team</th><th>W</th><th>L</th><th>OTL</th><th>PTS</th><th>STK</th></tr></thead><tbody>'
        for t in teams:
            out += f'<tr><td>{h(t["name"])}</td><td>{h(t["w"])}</td><td>{h(t["l"])}</td><td>{h(t["otl"])}</td><td>{h(t["pts"])}</td><td>{h(t["strk"])}</td></tr>'
        out += "</tbody></table>"
    return out


def render_nba_standings(standings):
    if not standings:
        return ""
    out = '<div class="subsection-title">NBA Standings</div>'
    for div_name, teams in standings.items():
        out += f'<div class="div-title">{h(div_name)}</div>'
        out += '<table class="standings"><thead><tr><th>Team</th><th>W</th><th>L</th><th>PCT</th><th>GB</th><th>STK</th></tr></thead><tbody>'
        for t in teams:
            out += f'<tr><td>{h(t["name"])}</td><td>{h(t["w"])}</td><td>{h(t["l"])}</td><td>{h(t["pct"])}</td><td>{h(t.get("gb",""))}</td><td>{h(t.get("strk",""))}</td></tr>'
        out += "</tbody></table>"
    return out


def render_nfl_standings(standings):
    if not standings:
        return ""
    out = '<div class="subsection-title">NFL Standings</div>'
    for div_name, teams in standings.items():
        out += f'<div class="div-title">{h(div_name)}</div>'
        out += '<table class="standings"><thead><tr><th>Team</th><th>W</th><th>L</th><th>T</th><th>PCT</th><th>PF</th><th>PA</th></tr></thead><tbody>'
        for t in teams:
            out += f'<tr><td>{h(t["name"])}</td><td>{h(t["w"])}</td><td>{h(t["l"])}</td><td>{h(t["t"])}</td><td>{h(t["pct"])}</td><td>{h(t["pf"])}</td><td>{h(t["pa"])}</td></tr>'
        out += "</tbody></table>"
    return out


def render_sport_section(sport_key, sport_label, games_html, standings_html):
    games_inner = games_html if games_html else '<p class="no-games">No completed games.</p>'
    return f"""
  <div class="sport-section" data-sport="{sport_key}">
    <div class="main">
      <div class="games-col">
        <div class="section-title">{sport_label} — Box Scores</div>
        <div class="games-grid">
          {games_inner}
        </div>
      </div>
      <div class="sidebar">
        <div class="section-title">Standings</div>
        {standings_html if standings_html else '<p class="no-games">No standings available.</p>'}
      </div>
    </div>
  </div>"""


def build_page(target_date: date, sports_data: dict):
    prev_date = target_date - timedelta(days=1)
    next_date = target_date + timedelta(days=1)

    tabs = ""
    sections = ""
    sport_configs = [
        ("mlb", "MLB ⚾"),
        ("nhl", "NHL 🏒"),
        ("nba", "NBA 🏀"),
        ("nfl", "NFL 🏈"),
    ]
    first = True
    for key, label in sport_configs:
        if key not in sports_data:
            continue
        active_cls = " active" if first else ""
        tabs += f'<button class="sport-tab{active_cls}" data-sport="{key}">{label}</button>'
        first = False
        sections += sports_data[key]

    date_str = target_date.strftime("%B %-d, %Y").upper()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Box Scores — {target_date.strftime("%B %-d, %Y")}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700;900&display=swap" rel="stylesheet">
  <style>{CSS}</style>
</head>
<body>
  <header class="page-header">
    <div class="site-title">Box Scores</div>
    <div class="page-date">{date_str}</div>
  </header>
  <nav class="nav-row">
    <a href="{prev_date.strftime('%Y%m%d')}.html">&larr; {prev_date.strftime('%b %-d')}</a>
    <span>MLB &bull; NHL &bull; NBA &bull; NFL</span>
    <div style="display:flex;gap:6px">
      <button id="dark-toggle">Dark Mode</button>
      <a href="{target_date.strftime('%Y%m%d')}.html">Today</a>
      <a href="{next_date.strftime('%Y%m%d')}.html">{next_date.strftime('%b %-d')} &rarr;</a>
    </div>
  </nav>
  <div class="sport-tabs">
    {tabs}
  </div>
  {sections}
  <script>{JS}</script>
</body>
</html>"""


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) > 1:
        target_date = date.fromisoformat(sys.argv[1])
    else:
        target_date = date.today() - timedelta(days=1)

    if not API_KEY:
        print("ERROR: set the API_SPORTS_KEY environment variable before running.", file=sys.stderr)
        sys.exit(1)

    print(f"Generating box scores for {target_date.isoformat()} ...")

    sports_data = {}

    print("  Fetching MLB...")
    mlb_g = mlb_games(target_date)
    mlb_s = mlb_standings(target_date)
    games_html = "".join(render_mlb_game(g) for g in mlb_g)
    sports_data["mlb"] = render_sport_section("mlb", "MLB ⚾", games_html, render_mlb_standings(mlb_s))
    print(f"    {len(mlb_g)} games  ({_requests_used('baseball')} requests used)")

    print("  Fetching NHL...")
    nhl_g = nhl_games(target_date)
    nhl_s = nhl_standings(target_date)
    games_html = "".join(render_nhl_game(g) for g in nhl_g)
    sports_data["nhl"] = render_sport_section("nhl", "NHL 🏒", games_html, render_nhl_standings(nhl_s))
    print(f"    {len(nhl_g)} games  ({_requests_used('hockey')} requests used)")

    print("  Fetching NBA...")
    nba_g = nba_games(target_date)
    nba_s = nba_standings(target_date)
    games_html = "".join(render_nba_game(g) for g in nba_g)
    sports_data["nba"] = render_sport_section("nba", "NBA 🏀", games_html, render_nba_standings(nba_s))
    print(f"    {len(nba_g)} games  ({_requests_used('nba')} requests used)")

    print("  Fetching NFL...")
    nfl_g = nfl_games(target_date)
    nfl_s = nfl_standings(target_date)
    games_html = "".join(render_nfl_game(g) for g in nfl_g)
    sports_data["nfl"] = render_sport_section("nfl", "NFL 🏈", games_html, render_nfl_standings(nfl_s))
    print(f"    {len(nfl_g)} games  ({_requests_used('football')} requests used)")

    html = build_page(target_date, sports_data)

    os.makedirs("boxscores", exist_ok=True)
    out_path = f"boxscores/{target_date.strftime('%Y%m%d')}.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  Written: {out_path}")


def _requests_used(sport):
    return _counts.get(_BASES[sport], 0)


if __name__ == "__main__":
    main()
