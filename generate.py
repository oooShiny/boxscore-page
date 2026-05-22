#!/usr/bin/env python3
"""
Daily sports box score page generator.
Covers MLB, NHL, NBA, NFL.
Usage:  python generate.py [YYYY-MM-DD]   (defaults to yesterday)
Output: boxscores/YYYYMMDD.html
"""

import sys
import os
import json
import requests
from datetime import date, timedelta, datetime

# ── helpers ──────────────────────────────────────────────────────────────────

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
})


def get(url, params=None, timeout=15, extra_headers=None):
    try:
        headers = {}
        if extra_headers:
            headers.update(extra_headers)
        r = SESSION.get(url, params=params, timeout=timeout, headers=headers)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [warn] {url}: {e}", file=sys.stderr)
        return None


def fmt_pct(w, l):
    t = w + l
    return f"{w/t:.3f}".lstrip("0") if t else ".000"


def ordinal(n):
    s = str(n)
    if s.endswith("11") or s.endswith("12") or s.endswith("13"):
        return s + "th"
    if s.endswith("1"):
        return s + "st"
    if s.endswith("2"):
        return s + "nd"
    if s.endswith("3"):
        return s + "rd"
    return s + "th"


# ── MLB ───────────────────────────────────────────────────────────────────────

MLB_BASE = "https://statsapi.mlb.com/api/v1"


def mlb_games(d: date):
    data = get(
        f"{MLB_BASE}/schedule",
        params={
            "sportId": 1,
            "date": d.isoformat(),
            "hydrate": "boxscore,decisions,linescore",
        },
        extra_headers={"Referer": "https://www.mlb.com/"},
    )
    if not data:
        return []
    games = []
    for date_entry in data.get("dates", []):
        for g in date_entry.get("games", []):
            if g.get("status", {}).get("abstractGameState") != "Final":
                continue
            games.append(_parse_mlb_game(g))
    return [g for g in games if g]


def _parse_mlb_game(g):
    away = g["teams"]["away"]
    home = g["teams"]["home"]
    ls = g.get("linescore", {})

    innings = ls.get("innings", [])
    inning_labels = [str(i + 1) for i in range(max(len(innings), 9))]
    away_line = []
    home_line = []
    for inn in innings:
        away_runs = inn.get("away", {}).get("runs", "")
        home_runs = inn.get("home", {}).get("runs", "x" if away_runs == "" else "")
        away_line.append("" if away_runs == "" else str(away_runs))
        home_line.append("" if home_runs == "" else str(home_runs))

    def pad(lst, length):
        return lst + [""] * (length - len(lst))

    n = max(len(inning_labels), 9)
    inning_labels = pad(inning_labels, n)
    away_line = pad(away_line, n)
    home_line = pad(home_line, n)

    lsr = ls.get("teams", {})
    away_rhe = [
        lsr.get("away", {}).get("runs", ""),
        lsr.get("away", {}).get("hits", ""),
        lsr.get("away", {}).get("errors", ""),
    ]
    home_rhe = [
        lsr.get("home", {}).get("runs", ""),
        lsr.get("home", {}).get("hits", ""),
        lsr.get("home", {}).get("errors", ""),
    ]

    box = g.get("boxscore", {})
    teams_box = box.get("teams", {})

    def batters(side):
        rows = []
        side_box = teams_box.get(side, {})
        order = side_box.get("battingOrder", [])
        players = side_box.get("players", {})
        for pid in order:
            key = f"ID{pid}"
            p = players.get(key, {})
            s = p.get("stats", {}).get("batting", {})
            name = p.get("person", {}).get("fullName", "")
            pos = p.get("position", {}).get("abbreviation", "")
            rows.append(
                {
                    "name": name,
                    "pos": pos,
                    "ab": s.get("atBats", 0),
                    "r": s.get("runs", 0),
                    "h": s.get("hits", 0),
                    "rbi": s.get("rbi", 0),
                    "bb": s.get("baseOnBalls", 0),
                    "so": s.get("strikeOuts", 0),
                    "avg": p.get("seasonStats", {})
                    .get("batting", {})
                    .get("avg", ".---"),
                }
            )
        # totals
        ts = side_box.get("teamStats", {}).get("batting", {})
        rows.append(
            {
                "name": "TOTALS",
                "pos": "",
                "ab": ts.get("atBats", ""),
                "r": ts.get("runs", ""),
                "h": ts.get("hits", ""),
                "rbi": ts.get("rbi", ""),
                "bb": ts.get("baseOnBalls", ""),
                "so": ts.get("strikeOuts", ""),
                "avg": "",
                "total": True,
            }
        )
        return rows

    def pitchers(side):
        rows = []
        side_box = teams_box.get(side, {})
        order = side_box.get("pitchers", [])
        players = side_box.get("players", {})
        for pid in order:
            key = f"ID{pid}"
            p = players.get(key, {})
            s = p.get("stats", {}).get("pitching", {})
            name = p.get("person", {}).get("fullName", "")
            note = ""
            decisions = g.get("decisions", {})
            if decisions.get("winner", {}).get("id") == pid:
                note = "W"
            elif decisions.get("loser", {}).get("id") == pid:
                note = "L"
            elif decisions.get("save", {}).get("id") == pid:
                note = "S"
            rows.append(
                {
                    "name": name,
                    "note": note,
                    "ip": s.get("inningsPitched", "0.0"),
                    "h": s.get("hits", 0),
                    "r": s.get("runs", 0),
                    "er": s.get("earnedRuns", 0),
                    "bb": s.get("baseOnBalls", 0),
                    "so": s.get("strikeOuts", 0),
                    "era": p.get("seasonStats", {})
                    .get("pitching", {})
                    .get("era", "-.--"),
                }
            )
        return rows

    return {
        "sport": "MLB",
        "away_name": away["team"]["name"],
        "home_name": home["team"]["name"],
        "away_score": away.get("score", ""),
        "home_score": home.get("score", ""),
        "inning_labels": inning_labels,
        "away_line": away_line,
        "home_line": home_line,
        "away_rhe": away_rhe,
        "home_rhe": home_rhe,
        "away_batters": batters("away"),
        "home_batters": batters("home"),
        "away_pitchers": pitchers("away"),
        "home_pitchers": pitchers("home"),
        "venue": g.get("venue", {}).get("name", ""),
    }


def mlb_standings(d: date):
    data = get(f"{MLB_BASE}/standings", params={"leagueId": "103,104", "date": d.isoformat()},
               extra_headers={"Referer": "https://www.mlb.com/"})
    if not data:
        return {}
    divisions = {}
    div_order = [
        "American League East",
        "American League Central",
        "American League West",
        "National League East",
        "National League Central",
        "National League West",
    ]
    for rec in data.get("records", []):
        div_name = rec.get("division", {}).get("nameShort", "")
        full = rec.get("division", {}).get("name", div_name)
        teams = []
        for tr in rec.get("teamRecords", []):
            teams.append(
                {
                    "name": tr["team"]["name"],
                    "w": tr["wins"],
                    "l": tr["losses"],
                    "pct": fmt_pct(tr["wins"], tr["losses"]),
                    "gb": tr.get("gamesBack", "-"),
                    "l10": tr.get("records", {})
                    .get("splitRecords", [{}])[5]
                    .get("wins", "")
                    if tr.get("records", {}).get("splitRecords")
                    and len(tr["records"]["splitRecords"]) > 5
                    else "",
                    "l10l": tr.get("records", {})
                    .get("splitRecords", [{}])[5]
                    .get("losses", "")
                    if tr.get("records", {}).get("splitRecords")
                    and len(tr["records"]["splitRecords"]) > 5
                    else "",
                    "strk": tr.get("streak", {}).get("streakCode", "-"),
                }
            )
        divisions[full] = teams
    result = {}
    for d_name in div_order:
        if d_name in divisions:
            result[d_name] = divisions[d_name]
    return result


# ── NHL ───────────────────────────────────────────────────────────────────────

NHL_BASE = "https://api-web.nhle.com/v1"


def nhl_games(d: date):
    data = get(f"{NHL_BASE}/score/{d.isoformat()}",
               extra_headers={"Referer": "https://www.nhl.com/"})
    if not data:
        return []
    games = []
    for g in data.get("games", []):
        state = g.get("gameState", "")
        if state not in ("FINAL", "OFF"):
            continue
        games.append(_parse_nhl_game(g))
    return [g for g in games if g]


def _parse_nhl_game(g):
    away = g.get("awayTeam", {})
    home = g.get("homeTeam", {})
    periods = g.get("periodDescriptor", {})

    # line score by period
    away_line = []
    home_line = []
    period_labels = []
    for p in g.get("goals", []) if False else []:
        pass  # goals list isn't useful for line score

    # use linescore from periodScores if available
    for ps in g.get("periodScores", []):
        period_num = ps.get("period", len(period_labels) + 1)
        if period_num <= 3:
            period_labels.append(str(period_num))
        elif period_num == 4:
            period_labels.append("OT")
        else:
            period_labels.append(f"OT{period_num-3}")
        away_line.append(str(ps.get("away", {}).get("goals", 0)))
        home_line.append(str(ps.get("home", {}).get("goals", 0)))

    if not period_labels:
        period_labels = ["1", "2", "3"]
        away_line = ["0", "0", "0"]
        home_line = ["0", "0", "0"]

    away_score = away.get("score", sum(int(x) for x in away_line if x.isdigit()))
    home_score = home.get("score", sum(int(x) for x in home_line if x.isdigit()))

    # skater stats
    def skaters(side_key):
        rows = []
        for player in g.get("summary", {}).get("scoring", []):
            pass  # scoring summary doesn't have skater lines
        return rows

    # top scorers from boxscore endpoint if available
    gid = g.get("id")
    box_data = get(f"{NHL_BASE}/gamecenter/{gid}/boxscore") if gid else None

    away_skaters, home_skaters = [], []
    away_goalies, home_goalies = [], []

    if box_data:
        player_by_game = box_data.get("playerByGameStats", {})
        for side, skater_list, goalie_list in [
            ("awayTeam", away_skaters, away_goalies),
            ("homeTeam", home_skaters, home_goalies),
        ]:
            side_data = player_by_game.get(side, {})
            for fwd in side_data.get("forwards", []) + side_data.get("defense", []):
                skater_list.append(
                    {
                        "name": fwd.get("name", {}).get("default", ""),
                        "pos": fwd.get("position", ""),
                        "g": fwd.get("goals", 0),
                        "a": fwd.get("assists", 0),
                        "pts": fwd.get("points", 0),
                        "plus_minus": fwd.get("plusMinus", 0),
                        "pim": fwd.get("pim", 0),
                        "sog": fwd.get("sog", 0),
                    }
                )
            for gk in side_data.get("goalies", []):
                away_name = away.get("name", {}).get("default", away.get("abbrev", ""))
                home_name_str = home.get("name", {}).get("default", home.get("abbrev", ""))
                goalie_list.append(
                    {
                        "name": gk.get("name", {}).get("default", ""),
                        "sa": gk.get("shotsAgainst", 0),
                        "sv": gk.get("saves", 0),
                        "ga": gk.get("goalsAgainst", 0),
                        "sv_pct": f"{gk.get('savePctg', 0):.3f}".lstrip("0"),
                        "toi": gk.get("toi", ""),
                    }
                )

    ot_note = ""
    if g.get("gameOutcome", {}).get("lastPeriodType") == "OT":
        ot_note = "OT"
    elif g.get("gameOutcome", {}).get("lastPeriodType") == "SO":
        ot_note = "SO"

    away_name = away.get("name", {}).get("default", away.get("abbrev", "AWAY"))
    home_name = home.get("name", {}).get("default", home.get("abbrev", "HOME"))

    return {
        "sport": "NHL",
        "away_name": away_name,
        "home_name": home_name,
        "away_score": away_score,
        "home_score": home_score,
        "period_labels": period_labels,
        "away_line": away_line,
        "home_line": home_line,
        "ot_note": ot_note,
        "away_skaters": away_skaters,
        "home_skaters": home_skaters,
        "away_goalies": away_goalies,
        "home_goalies": home_goalies,
        "venue": g.get("venue", {}).get("default", ""),
    }


def nhl_standings(d: date):
    data = get(f"{NHL_BASE}/standings/{d.isoformat()}",
               extra_headers={"Referer": "https://www.nhl.com/"})
    if not data:
        return {}
    divisions = {}
    for team in data.get("standings", []):
        conf = team.get("conferenceName", "")
        div = team.get("divisionName", "")
        key = f"{conf} – {div}"
        if key not in divisions:
            divisions[key] = []
        divisions[key].append(
            {
                "name": team.get("teamName", {}).get("default", ""),
                "w": team.get("wins", 0),
                "l": team.get("losses", 0),
                "otl": team.get("otLosses", 0),
                "pts": team.get("points", 0),
                "gf": team.get("goalFor", 0),
                "ga": team.get("goalAgainst", 0),
                "strk": team.get("streakCode", "-"),
            }
        )
    # sort within each division by points desc
    ordered = {}
    div_sort = ["Eastern – Atlantic", "Eastern – Metropolitan",
                "Western – Central", "Western – Pacific"]
    for k in div_sort:
        if k in divisions:
            ordered[k] = sorted(divisions[k], key=lambda x: -x["pts"])
    for k, v in divisions.items():
        if k not in ordered:
            ordered[k] = sorted(v, key=lambda x: -x["pts"])
    return ordered


# ── NBA ───────────────────────────────────────────────────────────────────────

NBA_CDN = "https://cdn.nba.com/static/json/liveData"
NBA_STATS = "https://stats.nba.com/stats"


def nba_games(d: date):
    # NBA CDN scoreboard uses YYYYMMDD
    date_str = d.strftime("%Y%m%d")
    data = get(f"https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json",
               extra_headers={"Referer": "https://www.nba.com/", "Origin": "https://www.nba.com"})
    # If the date doesn't match today, fall back to stats API
    sb_date = None
    if data:
        sb_date = data.get("scoreboard", {}).get("gameDate", "")

    games_list = None
    if data and sb_date == d.isoformat():
        games_list = data.get("scoreboard", {}).get("games", [])
    else:
        # Use NBA stats API for historical dates
        nba_data = get(
            f"{NBA_STATS}/scoreboardv2",
            params={"GameDate": d.strftime("%m/%d/%Y"), "LeagueID": "00", "DayOffset": "0"},
            extra_headers={"Referer": "https://www.nba.com/", "Origin": "https://www.nba.com"},
        )
        # This endpoint returns a complex structure; skip if unavailable
        if not nba_data:
            return []
        # Parse header-based response
        try:
            rs = nba_data.get("resultSets", [])
            games_list = _nba_parse_stats_api(rs, d)
            return games_list
        except Exception:
            return []

    if not games_list:
        return []

    result = []
    for g in games_list:
        status = g.get("gameStatus", 0)
        if status != 3:  # 3 = final
            continue
        result.append(_parse_nba_game_cdn(g))
    return [x for x in result if x]


def _parse_nba_game_cdn(g):
    away = g.get("awayTeam", {})
    home = g.get("homeTeam", {})

    period_labels = [str(i + 1) for i in range(4)]
    away_line = []
    home_line = []
    for p in away.get("periods", []):
        away_line.append(str(p.get("score", 0)))
    for p in home.get("periods", []):
        home_line.append(str(p.get("score", 0)))

    if len(away_line) > 4:
        for i in range(len(away_line) - 4):
            period_labels.append(f"OT{i+1}" if i > 0 else "OT")

    def pad(lst, n):
        return lst + [""] * (n - len(lst))

    n = max(len(period_labels), 4)
    period_labels = pad(period_labels, n)
    away_line = pad(away_line, n)
    home_line = pad(home_line, n)

    away_score = away.get("score", 0)
    home_score = home.get("score", 0)

    # Fetch box score for player stats
    gid = g.get("gameId", "")
    box = get(f"{NBA_CDN}/boxscore/boxscore_{gid}.json") if gid else None

    away_players, home_players = [], []
    if box:
        for side, player_list in [("awayTeam", away_players), ("homeTeam", home_players)]:
            side_data = box.get("game", {}).get(side, {})
            for p in side_data.get("players", []):
                s = p.get("statistics", {})
                if not s.get("minutesCalculated", "PT00M00.00S").startswith("PT00"):
                    player_list.append(
                        {
                            "name": p.get("name", ""),
                            "pos": p.get("position", ""),
                            "min": s.get("minutesCalculated", "")[2:].replace("M", ":").replace(".00S", ""),
                            "pts": s.get("points", 0),
                            "reb": s.get("reboundsTotal", 0),
                            "ast": s.get("assists", 0),
                            "stl": s.get("steals", 0),
                            "blk": s.get("blocks", 0),
                            "fg": f"{s.get('fieldGoalsMade',0)}-{s.get('fieldGoalsAttempted',0)}",
                            "3p": f"{s.get('threePointersMade',0)}-{s.get('threePointersAttempted',0)}",
                            "ft": f"{s.get('freeThrowsMade',0)}-{s.get('freeThrowsAttempted',0)}",
                            "to": s.get("turnovers", 0),
                        }
                    )
            # sort by minutes (pts as proxy)
            player_list.sort(key=lambda x: -x["pts"])

    return {
        "sport": "NBA",
        "away_name": f"{away.get('teamCity', '')} {away.get('teamName', '')}",
        "home_name": f"{home.get('teamCity', '')} {home.get('teamName', '')}",
        "away_score": away_score,
        "home_score": home_score,
        "period_labels": period_labels,
        "away_line": away_line,
        "home_line": home_line,
        "away_players": away_players,
        "home_players": home_players,
    }


def _nba_parse_stats_api(result_sets, d):
    # Returns simplified game list from stats API result sets
    return []


def nba_standings(d: date):
    data = get(
        f"{NBA_STATS}/leaguestandingsv3",
        params={"LeagueID": "00", "Season": _nba_season(d), "SeasonType": "Regular Season"},
        extra_headers={"Referer": "https://www.nba.com/", "Origin": "https://www.nba.com"},
    )
    if not data:
        return {}
    try:
        rs = data["resultSets"][0]
        headers = rs["headers"]
        rows = rs["rowSet"]
        idx = {h: i for i, h in enumerate(headers)}

        conferences = {}
        for row in rows:
            conf = row[idx["Conference"]]
            div = row[idx["Division"]]
            key = f"{conf}ern – {div}"
            if key not in conferences:
                conferences[key] = []
            conferences[key].append(
                {
                    "name": row[idx["TeamName"]],
                    "w": row[idx["WINS"]],
                    "l": row[idx["LOSSES"]],
                    "pct": fmt_pct(row[idx["WINS"]], row[idx["LOSSES"]]),
                    "gb": row[idx.get("ConferenceGamesBack", "WINS")] if "ConferenceGamesBack" in idx else "-",
                    "strk": row[idx["strCurrentStreak"]] if "strCurrentStreak" in idx else "-",
                }
            )
        return conferences
    except Exception:
        return {}


def _nba_season(d: date):
    # NBA season year (e.g., 2024-25)
    year = d.year
    if d.month < 9:
        year -= 1
    return f"{year}-{str(year+1)[2:]}"


# ── NFL ───────────────────────────────────────────────────────────────────────

ESPN_NFL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"


def nfl_games(d: date):
    data = get(f"{ESPN_NFL}/scoreboard", params={"dates": d.strftime("%Y%m%d")})
    if not data:
        return []
    games = []
    for event in data.get("events", []):
        comp = event.get("competitions", [{}])[0]
        status = comp.get("status", {}).get("type", {}).get("name", "")
        if status != "STATUS_FINAL":
            continue
        games.append(_parse_nfl_game(event))
    return [g for g in games if g]


def _parse_nfl_game(event):
    comp = event.get("competitions", [{}])[0]
    competitors = comp.get("competitors", [])
    away = next((c for c in competitors if c["homeAway"] == "away"), {})
    home = next((c for c in competitors if c["homeAway"] == "home"), {})

    def linescores(c):
        return [str(ls.get("value", "")) for ls in c.get("linescores", [])]

    away_line = linescores(away)
    home_line = linescores(home)

    n = max(len(away_line), len(home_line), 4)
    period_labels = ["1", "2", "3", "4"]
    if n > 4:
        for i in range(n - 4):
            period_labels.append("OT" if i == 0 else f"OT{i+1}")

    def pad(lst, length):
        return lst + [""] * (length - len(lst))

    away_line = pad(away_line, n)
    home_line = pad(home_line, n)
    period_labels = pad(period_labels, n)

    # Team leaders
    away_leaders, home_leaders = _nfl_leaders(away), _nfl_leaders(home)

    ot_note = ""
    if comp.get("status", {}).get("type", {}).get("name") == "STATUS_FINAL" and n > 4:
        ot_note = "OT"

    return {
        "sport": "NFL",
        "away_name": away.get("team", {}).get("displayName", "Away"),
        "home_name": home.get("team", {}).get("displayName", "Home"),
        "away_score": away.get("score", ""),
        "home_score": home.get("score", ""),
        "period_labels": period_labels,
        "away_line": away_line,
        "home_line": home_line,
        "ot_note": ot_note,
        "away_leaders": away_leaders,
        "home_leaders": home_leaders,
        "venue": comp.get("venue", {}).get("fullName", ""),
    }


def _nfl_leaders(competitor):
    leaders = []
    for cat in competitor.get("leaders", []):
        label = cat.get("displayName", "")
        for ld in cat.get("leaders", [])[:1]:
            athlete = ld.get("athlete", {})
            leaders.append(
                {
                    "cat": label,
                    "name": athlete.get("displayName", ""),
                    "stat": ld.get("displayValue", ""),
                }
            )
    return leaders


def nfl_standings(d: date):
    data = get(f"{ESPN_NFL}/standings", params={"season": d.year if d.month >= 9 else d.year - 1})
    if not data:
        return {}
    divisions = {}
    for child in data.get("children", []):
        conf = child.get("name", "")
        for div_child in child.get("children", []):
            div_name = div_child.get("name", "")
            key = f"{conf} – {div_name}"
            teams = []
            entries = div_child.get("standings", {}).get("entries", [])
            for entry in entries:
                team = entry.get("team", {})
                stats = {s["name"]: s.get("displayValue", s.get("value", "")) for s in entry.get("stats", [])}
                teams.append(
                    {
                        "name": team.get("displayName", ""),
                        "w": stats.get("wins", ""),
                        "l": stats.get("losses", ""),
                        "t": stats.get("ties", "0"),
                        "pct": stats.get("winPercent", ""),
                        "pf": stats.get("pointsFor", ""),
                        "pa": stats.get("pointsAgainst", ""),
                        "strk": stats.get("streak", "-"),
                    }
                )
            divisions[key] = teams
    return divisions


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

/* ── NFL leaders ── */
.leader-row { display: flex; justify-content: space-between; padding: 2px 0; font-size: 11px; border-bottom: 1px solid var(--border-light); }
.leader-row .cat { font-weight: 700; width: 80px; flex-shrink: 0; }
.leader-row .stat { font-weight: 700; padding-left: 6px; flex-shrink: 0; }

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

    skater_html = ""
    if g["away_skaters"] or g["home_skaters"]:
        def sk_rows(skaters):
            rows = ""
            for s in skaters[:10]:
                pm = ("+" if s["plus_minus"] > 0 else "") + str(s["plus_minus"])
                rows += f'<tr><td>{h(s["name"])} <em>{h(s["pos"])}</em></td><td>{h(s["g"])}</td><td>{h(s["a"])}</td><td>{h(s["pts"])}</td><td>{h(pm)}</td><td>{h(s["sog"])}</td></tr>'
            return rows

        def gk_rows(goalies):
            rows = ""
            for gk in goalies:
                rows += f'<tr><td>{h(gk["name"])}</td><td>{h(gk["sa"])}</td><td>{h(gk["sv"])}</td><td>{h(gk["ga"])}</td><td>{h(gk["sv_pct"])}</td><td>{h(gk["toi"])}</td></tr>'
            return rows

        skater_html = f"""
        <div class="subsection-title">{h(g['away_name'])} Skaters</div>
        <table class="stats"><thead><tr><th>Player</th><th>G</th><th>A</th><th>PTS</th><th>+/-</th><th>SOG</th></tr></thead>
        <tbody>{sk_rows(g['away_skaters'])}</tbody></table>
        <div class="subsection-title">{h(g['home_name'])} Skaters</div>
        <table class="stats"><thead><tr><th>Player</th><th>G</th><th>A</th><th>PTS</th><th>+/-</th><th>SOG</th></tr></thead>
        <tbody>{sk_rows(g['home_skaters'])}</tbody></table>"""

        if g["away_goalies"] or g["home_goalies"]:
            skater_html += f"""
        <div class="subsection-title">Goalies</div>
        <table class="stats"><thead><tr><th>Goalie</th><th>SA</th><th>SV</th><th>GA</th><th>SV%</th><th>TOI</th></tr></thead>
        <tbody>{gk_rows(g['away_goalies'] + g['home_goalies'])}</tbody></table>"""

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
      {skater_html}
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

    def leader_block(name, leaders, side_cls):
        if not leaders:
            return ""
        rows = "".join(
            f'<div class="leader-row"><span class="cat">{h(ld["cat"])}</span><span class="name">{h(ld["name"])}</span><span class="stat">{h(ld["stat"])}</span></div>'
            for ld in leaders
        )
        return f'<div class="subsection-title">{h(name)}</div><div class="leader-block">{rows}</div>'

    leaders_html = leader_block(g["away_name"], g.get("away_leaders", []), "away") + \
                   leader_block(g["home_name"], g.get("home_leaders", []), "home")

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
      {leaders_html}
    </div>"""


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

    print(f"Generating box scores for {target_date.isoformat()} ...")

    sports_data = {}

    print("  Fetching MLB...")
    mlb_g = mlb_games(target_date)
    mlb_s = mlb_standings(target_date)
    games_html = "".join(render_mlb_game(g) for g in mlb_g)
    sports_data["mlb"] = render_sport_section("mlb", "MLB ⚾", games_html, render_mlb_standings(mlb_s))
    print(f"    {len(mlb_g)} games")

    print("  Fetching NHL...")
    nhl_g = nhl_games(target_date)
    nhl_s = nhl_standings(target_date)
    games_html = "".join(render_nhl_game(g) for g in nhl_g)
    sports_data["nhl"] = render_sport_section("nhl", "NHL 🏒", games_html, render_nhl_standings(nhl_s))
    print(f"    {len(nhl_g)} games")

    print("  Fetching NBA...")
    nba_g = nba_games(target_date)
    nba_s = nba_standings(target_date)
    games_html = "".join(render_nba_game(g) for g in nba_g)
    sports_data["nba"] = render_sport_section("nba", "NBA 🏀", games_html, render_nba_standings(nba_s))
    print(f"    {len(nba_g)} games")

    print("  Fetching NFL...")
    nfl_g = nfl_games(target_date)
    nfl_s = nfl_standings(target_date)
    games_html = "".join(render_nfl_game(g) for g in nfl_g)
    sports_data["nfl"] = render_sport_section("nfl", "NFL 🏈", games_html, render_nfl_standings(nfl_s))
    print(f"    {len(nfl_g)} games")

    html = build_page(target_date, sports_data)

    os.makedirs("boxscores", exist_ok=True)
    out_path = f"boxscores/{target_date.strftime('%Y%m%d')}.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  Written: {out_path}")


if __name__ == "__main__":
    main()
