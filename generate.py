#!/usr/bin/env python3
"""
Daily sports box score page generator.
Covers MLB, NHL, NBA, NFL using ESPN's public API (no key required).
Usage:  python generate.py [YYYY-MM-DD]   (defaults to yesterday)
Output: boxscores/YYYYMMDD.html
"""

import sys
import os
import requests
from datetime import date, timedelta

# ── ESPN API ──────────────────────────────────────────────────────────────────

_ESPN_SITE = "https://site.api.espn.com/apis/site/v2/sports"
_ESPN_V2   = "https://site.api.espn.com/apis/v2/sports"

_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; boxscore-generator/3.0)",
    "Accept": "application/json",
})


def _get(url, params=None):
    try:
        r = _session.get(url, params=params, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [warn] {url}: {e}", file=sys.stderr)
        return None


def _scoreboard(sport, league, d: date):
    return _get(f"{_ESPN_SITE}/{sport}/{league}/scoreboard",
                {"dates": d.strftime("%Y%m%d")})


def _summary(sport, league, event_id):
    return _get(f"{_ESPN_SITE}/{sport}/{league}/summary", {"event": event_id})


def _standings_data(sport, league):
    return _get(f"{_ESPN_V2}/{sport}/{league}/standings")


# ── helpers ───────────────────────────────────────────────────────────────────

def fmt_pct(w, l):
    w, l = (w or 0), (l or 0)
    return f"{w/(w+l):.3f}".lstrip("0") if (w + l) else ".000"


def _sv(stats, name):
    for s in (stats or []):
        if s.get("name") == name:
            return s.get("value")
    return None


def _sd(stats, name):
    for s in (stats or []):
        if s.get("name") == name:
            return s.get("displayValue", "")
    return ""


def _ls(linescores):
    return [
        str(int(x["value"])) if x.get("value") is not None else ""
        for x in (linescores or [])
    ]


def _comp_pair(comp):
    cs = comp.get("competitors", [])
    return (
        next((c for c in cs if c.get("homeAway") == "away"), {}),
        next((c for c in cs if c.get("homeAway") == "home"), {}),
    )


def _game_state(comp):
    """Returns 'pre', 'in', or 'post'."""
    return (comp.get("status") or {}).get("type", {}).get("state", "post")


def _status_detail(comp):
    st = (comp.get("status") or {}).get("type", {})
    return st.get("shortDetail") or st.get("description", "")


def _collect_divisions(node):
    """Walk ESPN's nested standings tree, return [(div_name, [entry, ...])]."""
    children = node.get("children", [])
    entries = (node.get("standings") or {}).get("entries", [])
    if children:
        result = []
        for child in children:
            result.extend(_collect_divisions(child))
        return result
    if entries:
        name = node.get("name") or node.get("shortName") or "Unknown"
        return [(name, entries)]
    return []


def _int_safe(v, default=0):
    try:
        return int(float(str(v or default)))
    except (ValueError, TypeError):
        return default


# ── MLB ───────────────────────────────────────────────────────────────────────

def mlb_games(d: date):
    data = _scoreboard("baseball", "mlb", d)
    if not data:
        return []
    games = []
    for event in data.get("events", []):
        comp = (event.get("competitions") or [{}])[0]
        if not comp.get("status", {}).get("type", {}).get("completed"):
            continue
        g = _parse_mlb_game(event["id"], comp)
        if g:
            games.append(g)
    return games


def _parse_mlb_game(event_id, comp):
    away_c, home_c = _comp_pair(comp)
    away_name  = away_c.get("team", {}).get("displayName", "Away")
    home_name  = home_c.get("team", {}).get("displayName", "Home")
    away_abbr  = away_c.get("team", {}).get("abbreviation", "")
    home_abbr  = home_c.get("team", {}).get("abbreviation", "")
    away_score = away_c.get("score", "")
    home_score = home_c.get("score", "")
    venue      = comp.get("venue", {}).get("fullName", "")

    # Fallback line score from scoreboard per-inning linescores
    a_ls = _ls(away_c.get("linescores"))
    h_ls = _ls(home_c.get("linescores"))
    n = max(len(a_ls), len(h_ls), 9)
    inning_labels = [str(i + 1) for i in range(n)]
    a_line = a_ls + [""] * (n - len(a_ls))
    h_line = h_ls + [""] * (n - len(h_ls))
    away_rhe = [away_score, "", ""]
    home_rhe = [home_score, "", ""]
    away_batters, home_batters = [], []
    away_pitchers, home_pitchers = [], []

    summary = _summary("baseball", "mlb", event_id)
    if summary:
        # H/E live in header.competitions[].competitors[].hits / .errors
        hcomp = summary.get("header", {}).get("competitions", [{}])[0]
        for c in hcomp.get("competitors", []):
            ha = c.get("homeAway", "")
            hits   = c.get("hits", "")
            errors = c.get("errors", "")
            if ha == "away":
                away_rhe[1] = str(hits) if hits != "" else ""
                away_rhe[2] = str(errors) if errors != "" else ""
            else:
                home_rhe[1] = str(hits) if hits != "" else ""
                home_rhe[2] = str(errors) if errors != "" else ""

        # Player stats — batting group has 'hits-atBats' as first key;
        # pitching group has 'fullInnings.partInnings' as first key.
        for team_block in summary.get("boxscore", {}).get("players", []):
            tname = team_block.get("team", {}).get("displayName", "")
            is_away = tname == away_name
            for sg in team_block.get("statistics", []):
                keys = sg.get("keys", [])
                athletes = sg.get("athletes", [])
                if not keys:
                    continue

                if keys[0] == "hits-atBats":
                    # Batting group
                    players = []
                    for a in athletes:
                        stats = a.get("stats", [])
                        km = {k: stats[i] if i < len(stats) else "" for i, k in enumerate(keys)}
                        if a.get("athlete"):
                            players.append({
                                "name": a["athlete"].get("displayName", ""),
                                "pos":  a["athlete"].get("position", {}).get("abbreviation", ""),
                                "ab":  km.get("atBats", ""),
                                "r":   km.get("runs", ""),
                                "h":   km.get("hits", ""),
                                "rbi": km.get("RBIs", ""),
                                "bb":  km.get("walks", ""),
                                "so":  km.get("strikeouts", ""),
                                "avg": km.get("avg", ""),
                            })
                    if is_away:
                        away_batters = players
                    else:
                        home_batters = players

                elif "fullInnings" in keys[0]:
                    # Pitching group
                    players = []
                    for a in athletes:
                        stats = a.get("stats", [])
                        km = {k: stats[i] if i < len(stats) else "" for i, k in enumerate(keys)}
                        if a.get("athlete"):
                            players.append({
                                "name": a["athlete"].get("displayName", ""),
                                "ip":  km.get("fullInnings.partInnings", ""),
                                "h":   km.get("hits", ""),
                                "r":   km.get("runs", ""),
                                "er":  km.get("earnedRuns", ""),
                                "bb":  km.get("walks", ""),
                                "so":  km.get("strikeouts", ""),
                                "era": km.get("ERA", ""),
                                "note": "",
                            })
                    if is_away:
                        away_pitchers = players
                    else:
                        home_pitchers = players

    return {
        "sport": "MLB",
        "away_name": away_name, "home_name": home_name,
        "away_score": away_score, "home_score": home_score,
        "inning_labels": inning_labels,
        "away_line": a_line, "home_line": h_line,
        "away_rhe": away_rhe, "home_rhe": home_rhe,
        "away_batters": away_batters, "home_batters": home_batters,
        "away_pitchers": away_pitchers, "home_pitchers": home_pitchers,
        "venue": venue,
    }


def mlb_standings(d: date):
    data = _standings_data("baseball", "mlb")
    if not data:
        return {}
    divisions = {}
    for div_name, entries in _collect_divisions(data):
        teams = []
        for e in entries:
            stats = e.get("stats", [])
            w = _int_safe(_sv(stats, "wins"))
            l = _int_safe(_sv(stats, "losses"))
            gb   = _sd(stats, "gamesBehind") or "-"
            strk = _sd(stats, "streak") or "-"
            teams.append({
                "name": e.get("team", {}).get("displayName", ""),
                "w": w, "l": l, "pct": fmt_pct(w, l), "gb": gb, "strk": strk,
            })
        teams.sort(key=lambda t: (-t["w"], t["l"]))
        divisions[div_name] = teams
    div_order = ["AL East", "AL Central", "AL West", "NL East", "NL Central", "NL West"]
    return {k: divisions[k] for k in div_order if k in divisions} | \
           {k: v for k, v in divisions.items() if k not in div_order}


# ── NHL ───────────────────────────────────────────────────────────────────────

def nhl_games(d: date):
    data = _scoreboard("hockey", "nhl", d)
    if not data:
        return []
    games = []
    for event in data.get("events", []):
        comp = (event.get("competitions") or [{}])[0]
        if not comp.get("status", {}).get("type", {}).get("completed"):
            continue
        g = _parse_nhl_game(event["id"], comp)
        if g:
            games.append(g)
    return games


def _parse_nhl_game(event_id, comp):
    away_c, home_c = _comp_pair(comp)
    away_name  = away_c.get("team", {}).get("displayName", "Away")
    home_name  = home_c.get("team", {}).get("displayName", "Home")
    away_score = away_c.get("score", "")
    home_score = home_c.get("score", "")
    venue      = comp.get("venue", {}).get("fullName", "")

    a_ls = _ls(away_c.get("linescores"))
    h_ls = _ls(home_c.get("linescores"))
    n = max(len(a_ls), len(h_ls), 3)

    status_desc = comp.get("status", {}).get("type", {}).get("shortDetail", "") or \
                  comp.get("status", {}).get("type", {}).get("description", "")
    ot_note = ""
    labels = ["1", "2", "3"]
    if n > 3:
        if "SO" in status_desc.upper() or "SHOOTOUT" in status_desc.upper():
            labels.append("SO")
            ot_note = "SO"
        else:
            labels.append("OT")
            ot_note = "OT"

    a_line = a_ls + [""] * (len(labels) - len(a_ls))
    h_line = h_ls + [""] * (len(labels) - len(h_ls))

    team_stats_rows = []
    summary = _summary("hockey", "nhl", event_id)
    if summary:
        away_stats, home_stats = {}, {}
        for tb in summary.get("boxscore", {}).get("teams", []):
            ha = tb.get("homeAway", "")
            sd = {s.get("label") or s.get("name", ""): s.get("displayValue", "")
                  for s in tb.get("statistics", [])}
            if ha == "away":
                away_stats = sd
            else:
                home_stats = sd
        nhl_priority = [
            "Shots on Goal", "Power Play Goals", "Power Play Opportunities",
            "Penalty Minutes", "Faceoffs Won", "Blocked Shots",
            "Giveaways", "Takeaways", "Hits",
        ]
        all_keys = set(away_stats) | set(home_stats)
        team_stats_rows = [
            {"label": k, "away": away_stats.get(k, "-"), "home": home_stats.get(k, "-")}
            for k in nhl_priority if k in all_keys
        ] + [
            {"label": k, "away": away_stats.get(k, "-"), "home": home_stats.get(k, "-")}
            for k in sorted(all_keys - set(nhl_priority))
        ]

    return {
        "sport": "NHL",
        "away_name": away_name, "home_name": home_name,
        "away_score": away_score, "home_score": home_score,
        "period_labels": labels,
        "away_line": a_line, "home_line": h_line,
        "ot_note": ot_note, "team_stats_rows": team_stats_rows, "venue": venue,
    }


def nhl_standings(d: date):
    data = _standings_data("hockey", "nhl")
    if not data:
        return {}
    divisions = {}
    for div_name, entries in _collect_divisions(data):
        teams = []
        for e in entries:
            stats = e.get("stats", [])
            w   = _int_safe(_sv(stats, "wins"))
            l   = _int_safe(_sv(stats, "losses"))
            otl = _int_safe(_sv(stats, "otLosses") or _sv(stats, "otl"))
            pts = _int_safe(_sv(stats, "points")) or (w * 2 + otl)
            strk = _sd(stats, "streak") or "-"
            teams.append({
                "name": e.get("team", {}).get("displayName", ""),
                "w": w, "l": l, "otl": otl, "pts": pts, "strk": strk,
            })
        divisions[div_name] = sorted(teams, key=lambda t: -t["pts"])
    div_order = ["Atlantic", "Metropolitan", "Central", "Pacific"]
    ordered = {}
    for d_name in div_order:
        for k in divisions:
            if d_name.lower() in k.lower():
                ordered[k] = divisions[k]
                break
    for k, v in divisions.items():
        if k not in ordered:
            ordered[k] = v
    return ordered


# ── NBA ───────────────────────────────────────────────────────────────────────

def nba_games(d: date):
    data = _scoreboard("basketball", "nba", d)
    if not data:
        return []
    games = []
    for event in data.get("events", []):
        comp = (event.get("competitions") or [{}])[0]
        if not comp.get("status", {}).get("type", {}).get("completed"):
            continue
        g = _parse_nba_game(event["id"], comp)
        if g:
            games.append(g)
    return games


def _parse_nba_game(event_id, comp):
    away_c, home_c = _comp_pair(comp)
    away_name  = away_c.get("team", {}).get("displayName", "Away")
    home_name  = home_c.get("team", {}).get("displayName", "Home")
    away_score = away_c.get("score", "")
    home_score = home_c.get("score", "")

    a_ls = _ls(away_c.get("linescores"))
    h_ls = _ls(home_c.get("linescores"))
    n = max(len(a_ls), len(h_ls), 4)

    if n == 5:
        labels = ["1", "2", "3", "4", "OT"]
    elif n > 5:
        labels = ["1", "2", "3", "4"] + [f"OT{i}" for i in range(1, n - 3)]
    else:
        labels = ["1", "2", "3", "4"]

    a_line = a_ls + [""] * (n - len(a_ls))
    h_line = h_ls + [""] * (n - len(h_ls))

    away_players, home_players = [], []
    summary = _summary("basketball", "nba", event_id)
    if summary:
        for team_block in summary.get("boxscore", {}).get("players", []):
            tname = team_block.get("team", {}).get("displayName", "")
            is_away = tname == away_name
            for sg in team_block.get("statistics", []):
                keys = sg.get("keys", [])
                athletes = sg.get("athletes", [])
                players = []
                for a in athletes:
                    stats = a.get("stats", [])
                    km = {k: stats[i] if i < len(stats) else "" for i, k in enumerate(keys)}
                    mins = km.get("minutes", km.get("min", ""))
                    if not mins or str(mins) in ("0", "0:00", "0.0", "DNP", "--"):
                        continue
                    if a.get("athlete"):
                        players.append({
                            "name": a["athlete"].get("displayName", ""),
                            "pos":  a["athlete"].get("position", {}).get("abbreviation", ""),
                            "pts":  km.get("points", "0") or "0",
                            "reb":  km.get("rebounds", "0") or "0",
                            "ast":  km.get("assists", "0") or "0",
                            "fg":   km.get("fieldGoalsMade-fieldGoalsAttempted", ""),
                            "3p":   km.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted", ""),
                            "ft":   km.get("freeThrowsMade-freeThrowsAttempted", ""),
                        })
                players.sort(key=lambda x: -_int_safe(x["pts"]))
                if is_away:
                    away_players = players
                else:
                    home_players = players

    return {
        "sport": "NBA",
        "away_name": away_name, "home_name": home_name,
        "away_score": away_score, "home_score": home_score,
        "period_labels": labels,
        "away_line": a_line, "home_line": h_line,
        "away_players": away_players, "home_players": home_players,
    }


def nba_standings(d: date):
    data = _standings_data("basketball", "nba")
    if not data:
        return {}
    divisions = {}
    for div_name, entries in _collect_divisions(data):
        teams = []
        for e in entries:
            stats = e.get("stats", [])
            w    = _int_safe(_sv(stats, "wins"))
            l    = _int_safe(_sv(stats, "losses"))
            gb   = _sd(stats, "gamesBehind") or "-"
            strk = _sd(stats, "streak") or "-"
            teams.append({
                "name": e.get("team", {}).get("displayName", ""),
                "w": w, "l": l, "pct": fmt_pct(w, l), "gb": gb, "strk": strk,
            })
        divisions[div_name] = sorted(teams, key=lambda t: (-t["w"], t["l"]))
    return divisions


# ── NFL ───────────────────────────────────────────────────────────────────────

def nfl_games(d: date):
    data = _scoreboard("football", "nfl", d)
    if not data:
        return []
    games = []
    for event in data.get("events", []):
        comp = (event.get("competitions") or [{}])[0]
        if not comp.get("status", {}).get("type", {}).get("completed"):
            continue
        g = _parse_nfl_game(event["id"], comp)
        if g:
            games.append(g)
    return games


def _parse_nfl_game(event_id, comp):
    away_c, home_c = _comp_pair(comp)
    away_name  = away_c.get("team", {}).get("displayName", "Away")
    home_name  = home_c.get("team", {}).get("displayName", "Home")
    away_score = away_c.get("score", "")
    home_score = home_c.get("score", "")
    venue      = comp.get("venue", {}).get("fullName", "")

    a_ls = _ls(away_c.get("linescores"))
    h_ls = _ls(home_c.get("linescores"))
    n = max(len(a_ls), len(h_ls), 4)

    ot_note = ""
    labels = ["1", "2", "3", "4"]
    if n > 4:
        labels.append("OT")
        ot_note = "OT"

    a_line = a_ls + [""] * (len(labels) - len(a_ls))
    h_line = h_ls + [""] * (len(labels) - len(h_ls))

    team_stats_rows = []
    summary = _summary("football", "nfl", event_id)
    if summary:
        away_stats, home_stats = {}, {}
        for tb in summary.get("boxscore", {}).get("teams", []):
            ha = tb.get("homeAway", "")
            sd = {s.get("label") or s.get("name", ""): s.get("displayValue", "")
                  for s in tb.get("statistics", [])}
            if ha == "away":
                away_stats = sd
            else:
                home_stats = sd
        nfl_priority = [
            "Total Yards", "Passing Yards", "Rushing Yards", "First Downs",
            "Third Down Efficiency", "Turnovers", "Sacks",
            "Penalties", "Possession", "Yards Per Play",
        ]
        all_keys = set(away_stats) | set(home_stats)
        team_stats_rows = [
            {"label": k, "away": away_stats.get(k, "-"), "home": home_stats.get(k, "-")}
            for k in nfl_priority if k in all_keys
        ] + [
            {"label": k, "away": away_stats.get(k, "-"), "home": home_stats.get(k, "-")}
            for k in sorted(all_keys - set(nfl_priority))
        ]

    return {
        "sport": "NFL",
        "away_name": away_name, "home_name": home_name,
        "away_score": away_score, "home_score": home_score,
        "period_labels": labels,
        "away_line": a_line, "home_line": h_line,
        "ot_note": ot_note, "team_stats_rows": team_stats_rows, "venue": venue,
    }


def nfl_standings(d: date):
    data = _standings_data("football", "nfl")
    if not data:
        return {}
    divisions = {}
    for div_name, entries in _collect_divisions(data):
        teams = []
        for e in entries:
            stats = e.get("stats", [])
            w   = _int_safe(_sv(stats, "wins"))
            l   = _int_safe(_sv(stats, "losses"))
            t   = _int_safe(_sv(stats, "ties"))
            pct = _sd(stats, "winPercent") or fmt_pct(w, l)
            pf  = _sd(stats, "pointsFor") or ""
            pa  = _sd(stats, "pointsAgainst") or ""
            strk = _sd(stats, "streak") or "-"
            teams.append({
                "name": e.get("team", {}).get("displayName", ""),
                "w": w, "l": l, "t": t, "pct": pct, "pf": pf, "pa": pa, "strk": strk,
            })
        divisions[div_name] = teams
    div_order = ["AFC East", "AFC North", "AFC South", "AFC West",
                 "NFC East", "NFC North", "NFC South", "NFC West"]
    ordered = {k: divisions[k] for k in div_order if k in divisions}
    for k, v in divisions.items():
        if k not in ordered:
            ordered[k] = v
    return ordered


def _preview_games(sport, league, d: date):
    """Return scheduled or in-progress (non-completed) games for any sport."""
    data = _scoreboard(sport, league, d)
    if not data:
        return []
    games = []
    for event in data.get("events", []):
        comp = (event.get("competitions") or [{}])[0]
        state = _game_state(comp)
        if state == "post":
            continue
        away_c, home_c = _comp_pair(comp)
        games.append({
            "away_name": away_c.get("team", {}).get("displayName", "Away"),
            "home_name": home_c.get("team", {}).get("displayName", "Home"),
            "away_score": away_c.get("score", "") if state == "in" else "",
            "home_score": home_c.get("score", "") if state == "in" else "",
            "state": state,
            "status_detail": _status_detail(comp),
            "venue": comp.get("venue", {}).get("fullName", ""),
        })
    return games


# ── HTML rendering ────────────────────────────────────────────────────────────

CSS = """
@font-face {
  font-family: "CloisterBlack";
  src: url("../fonts/CloisterBlack.ttf") format("truetype");
  font-weight: normal;
  font-style: normal;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #f9f7f1;
  --text: #111;
  --border: #111;
  --border-light: #bbb;
  --header-bg: #111111d6;
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
  font-family: "CloisterBlack", serif;
  font-size: 38px;
  font-weight: normal;
  letter-spacing: 0;
  text-transform: none;
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
  padding-bottom: 0.2em;
  justify-content: center;
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
  font-family: serif;   
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


def render_preview_game(g):
    state = g["state"]
    venue = f'<div class="game-meta">{h(g["venue"])}</div>' if g.get("venue") else ""
    status_lbl = g.get("status_detail") or ("In Progress" if state == "in" else "Scheduled")

    if state == "in":
        away_score = g.get("away_score") or "0"
        home_score = g.get("home_score") or "0"
        score_html = (
            f'<div class="game-matchup"><span class="team-name">{h(g["away_name"])}</span>'
            f'<span class="team-score">{h(away_score)}</span></div>'
            f'<div class="game-matchup"><span class="team-name">{h(g["home_name"])}</span>'
            f'<span class="team-score">{h(home_score)}</span></div>'
        )
    else:
        score_html = (
            f'<div class="game-matchup"><span class="team-name">{h(g["away_name"])}</span></div>'
            f'<div class="game-matchup"><span class="team-name">{h(g["home_name"])}</span></div>'
        )

    return (
        f'<div class="game-box">'
        f'<div class="game-header">{score_html}'
        f'<div class="game-meta">{h(status_lbl)}</div>{venue}</div>'
        f'</div>'
    )


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


def render_sport_section(sport_key, sport_label, games_html, standings_html, no_games_msg="No completed games."):
    games_inner = games_html if games_html else f'<p class="no-games">{no_games_msg}</p>'
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
    next_link = (
        f'<a href="{next_date.strftime("%Y%m%d")}.html">{next_date.strftime("%b %-d")} &rarr;</a>'
        if target_date < date.today() else ""
    )

    tabs = ""
    sections = ""
    sport_configs = [
        ("mlb", "MLB"),
        ("nhl", "NHL"),
        ("nba", "NBA"),
        ("nfl", "NFL"),
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
    <div style="display:flex;gap:6px">
      <button id="dark-toggle">Dark Mode</button>
      <a href="{date.today().strftime('%Y%m%d')}.html">Today</a>
      {next_link}
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

_SPORT_CONFIGS = [
    ("mlb", "baseball", "mlb", "MLB"),
    ("nhl", "hockey",   "nhl", "NHL"),
    ("nba", "basketball","nba","NBA"),
    ("nfl", "football", "nfl", "NFL"),
]

_GAME_FETCHERS = {
    "mlb": mlb_games, "nhl": nhl_games, "nba": nba_games, "nfl": nfl_games,
}
_GAME_RENDERERS = {
    "mlb": render_mlb_game, "nhl": render_nhl_game,
    "nba": render_nba_game, "nfl": render_nfl_game,
}
_STANDINGS_FETCHERS = {
    "mlb": mlb_standings, "nhl": nhl_standings,
    "nba": nba_standings, "nfl": nfl_standings,
}
_STANDINGS_RENDERERS = {
    "mlb": render_mlb_standings, "nhl": render_nhl_standings,
    "nba": render_nba_standings, "nfl": render_nfl_standings,
}


def _generate_page(target_date: date, preview: bool = False):
    label = "preview" if preview else "box scores"
    print(f"Generating {label} for {target_date.isoformat()} ...")
    sports_data = {}
    for key, sport, league, tab_label in _SPORT_CONFIGS:
        print(f"  Fetching {key.upper()}...")
        if preview:
            games = _preview_games(sport, league, target_date)
            games_html = "".join(render_preview_game(g) for g in games)
            no_games_msg = "No games scheduled."
        else:
            games = _GAME_FETCHERS[key](target_date)
            games_html = "".join(_GAME_RENDERERS[key](g) for g in games)
            no_games_msg = "No completed games."
        standings = _STANDINGS_FETCHERS[key](target_date)
        standings_html = _STANDINGS_RENDERERS[key](standings)
        sports_data[key] = render_sport_section(key, tab_label, games_html, standings_html, no_games_msg)
        print(f"    {len(games)} games")

    html = build_page(target_date, sports_data)
    os.makedirs("boxscores", exist_ok=True)
    out_path = f"boxscores/{target_date.strftime('%Y%m%d')}.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Written: {out_path}")


def main():
    if len(sys.argv) == 3:
        start = date.fromisoformat(sys.argv[1])
        end   = date.fromisoformat(sys.argv[2])
        if end < start:
            print("Error: end date must be >= start date", file=sys.stderr)
            sys.exit(1)
        d = start
        while d <= end:
            out_path = f"boxscores/{d.strftime('%Y%m%d')}.html"
            if os.path.exists(out_path):
                print(f"Skipping {d.isoformat()} (already exists)")
            else:
                _generate_page(d)
            d += timedelta(days=1)
    elif len(sys.argv) == 2:
        _generate_page(date.fromisoformat(sys.argv[1]))
    else:
        _generate_page(date.today() - timedelta(days=1))
        _generate_page(date.today(), preview=True)


if __name__ == "__main__":
    main()
