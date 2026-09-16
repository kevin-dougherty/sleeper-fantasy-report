"""
Sleeper Weekly Fantasy Football Report Generator
--------------------------------------------------
Pulls data from the free, public Sleeper API (no auth needed) and builds a
weekly report:
  - Team of the Week (weekly high score) + its top contributors
  - Weekly MVP (single highest-scoring starter league-wide) + box score stats
  - Position Point Leaders — SEASON-LONG cumulative totals for QB/RB/WR/TE
  - Highlights: closest matchup, biggest blowout, bench regret
  - A short AI-generated recap via the Claude API (trash talk optional but encouraged)
Then optionally posts the whole thing to a GroupMe group.

CONFIG: everything is read from config.json in the repo root.
  copy config.example.json -> config.json and fill it in
  (config.json is gitignored — safe to keep real values there)

USAGE:
    python src/sleeper_weekly_report.py
    python src/sleeper_weekly_report.py --no-post

Requires: pip install -r requirements.txt
"""

import argparse
import json
import sys
from pathlib import Path

import requests

BASE = "https://api.sleeper.app/v1"
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"
ANTHROPIC_MODEL = "claude-sonnet-5"
POSITIONS = ["QB", "RB", "WR", "TE"]


# --------------------------------------------------------------------------
# Config loading
# --------------------------------------------------------------------------

def load_config():
    if not CONFIG_PATH.exists():
        sys.exit(
            f"No config.json found at {CONFIG_PATH}. "
            "Copy config.example.json to config.json and fill it in first."
        )

    with open(CONFIG_PATH) as f:
        cfg = json.load(f)

    league_id = cfg.get("league_id")
    week = cfg.get("week")
    groupme_bot_id = cfg.get("groupme_bot_id")
    anthropic_api_key = cfg.get("anthropic_api_key")

    if not league_id or str(league_id).startswith("YOUR_"):
        sys.exit("config.json is missing a real league_id. Fill it in and try again.")

    return {
        "league_id": str(league_id),
        "week": int(week) if week else None,
        "groupme_bot_id": groupme_bot_id if groupme_bot_id and not str(groupme_bot_id).startswith("YOUR_") else None,
        "anthropic_api_key": anthropic_api_key if anthropic_api_key and not str(anthropic_api_key).startswith("YOUR_") else None,
    }


# --------------------------------------------------------------------------
# Sleeper data
# --------------------------------------------------------------------------

def get_json(url):
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()


def get_current_week():
    state = get_json(f"{BASE}/state/nfl")
    return state["week"]


def get_league_season(league_id):
    info = get_json(f"{BASE}/league/{league_id}")
    return info["season"]


def get_week_stats(season, week):
    """Real box-score stats (yards, TDs, etc.) for every player in a given week."""
    try:
        return get_json(f"{BASE}/stats/nfl/regular/{season}/{week}")
    except Exception as e:
        print(f"Could not fetch box score stats (error: {e})", file=sys.stderr)
        return {}


def load_league_data(league_id, week):
    users = get_json(f"{BASE}/league/{league_id}/users")
    rosters = get_json(f"{BASE}/league/{league_id}/rosters")
    matchups = get_json(f"{BASE}/league/{league_id}/matchups/{week}")
    # ~5MB, rarely changes — fine to refetch weekly for a single scheduled run.
    players = get_json(f"{BASE}/players/nfl")
    return users, rosters, matchups, players


def build_team_name_map(users, rosters):
    user_by_id = {u["user_id"]: u for u in users}
    roster_to_name = {}
    for r in rosters:
        u = user_by_id.get(r["owner_id"], {})
        name = (u.get("metadata") or {}).get("team_name") or u.get("display_name") or f"Roster {r['roster_id']}"
        roster_to_name[r["roster_id"]] = name
    return roster_to_name


def player_display(players, player_id):
    p = players.get(player_id)
    if not p:
        return player_id, "UNK"
    name = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
    pos = p.get("position", "UNK")
    return name, pos


def format_stat_line(pid, pos, week_stats):
    """Turn a player's box-score stats into a short readable line, e.g.
    '312 pass yds, 3 pass TD, 41 rush yds'. Returns None if nothing usable."""
    s = week_stats.get(pid, {}) or {}
    parts = []

    def add(key, label, plural_ok=True):
        val = s.get(key)
        if val:
            val = int(val)
            suffix = "s" if plural_ok and val != 1 else ""
            parts.append(f"{val} {label}{suffix}")

    if pos == "QB":
        add("pass_yd", "pass yd", plural_ok=False)
        add("pass_td", "pass TD")
        add("pass_int", "INT")
        add("rush_yd", "rush yd", plural_ok=False)
        add("rush_td", "rush TD")
    elif pos == "RB":
        add("rush_yd", "rush yd", plural_ok=False)
        add("rush_td", "rush TD")
        add("rec", "rec")
        add("rec_yd", "rec yd", plural_ok=False)
        add("rec_td", "rec TD")
    elif pos in ("WR", "TE"):
        add("rec", "rec")
        add("rec_yd", "rec yd", plural_ok=False)
        add("rec_td", "rec TD")
        add("rush_yd", "rush yd", plural_ok=False)

    return ", ".join(parts) if parts else None


# --------------------------------------------------------------------------
# Report computation — this week
# --------------------------------------------------------------------------

def compute_report_data(users, rosters, matchups, players, week_stats):
    team_names = build_team_name_map(users, rosters)

    team_scores = []  # (team_name, points, roster_id)
    matchup_groups = {}
    for m in matchups:
        roster_id = m["roster_id"]
        points = m.get("points", 0) or 0
        team_name = team_names.get(roster_id, f"Roster {roster_id}")
        team_scores.append((team_name, points, roster_id))
        matchup_groups.setdefault(m.get("matchup_id"), []).append((team_name, points))

    team_scores.sort(key=lambda x: x[1], reverse=True)
    high_score_team, high_score_pts, high_score_roster_id = team_scores[0]
    low_score_team, low_score_pts, _ = team_scores[-1]

    # Top contributors on the winning team (its two highest-scoring starters)
    top_contributors = []
    winning_matchup = next((m for m in matchups if m["roster_id"] == high_score_roster_id), None)
    if winning_matchup:
        starters = winning_matchup.get("starters", []) or []
        player_points = winning_matchup.get("players_points", {}) or {}
        scored = sorted(((pid, player_points.get(pid, 0)) for pid in starters), key=lambda x: x[1], reverse=True)
        for pid, pts in scored[:2]:
            name, pos = player_display(players, pid)
            top_contributors.append((name, pos, pts))

    # Closest matchup / biggest blowout
    closest = None
    biggest_blowout = None
    for teams in matchup_groups.values():
        if len(teams) != 2:
            continue
        (t1, p1), (t2, p2) = teams
        diff = abs(p1 - p2)
        entry = (diff, t1, p1, t2, p2)
        if closest is None or diff < closest[0]:
            closest = entry
        if biggest_blowout is None or diff > biggest_blowout[0]:
            biggest_blowout = entry

    # Weekly MVP / biggest bust (highest & lowest scoring starters league-wide) + bench regret
    bench_waste = []
    mvp = None             # (name, pos, team_name, pts, stat_line)
    lowest_starter = None  # (name, pos, team_name, pts)

    for m in matchups:
        roster_id = m["roster_id"]
        team_name = team_names.get(roster_id, f"Roster {roster_id}")
        starters = set(m.get("starters", []) or [])
        player_points = m.get("players_points", {}) or {}

        for pid, pts in player_points.items():
            name, pos = player_display(players, pid)
            if pid in starters:
                if mvp is None or pts > mvp[3]:
                    stat_line = format_stat_line(pid, pos, week_stats)
                    mvp = (name, pos, team_name, pts, stat_line)
                if lowest_starter is None or pts < lowest_starter[3]:
                    lowest_starter = (name, pos, team_name, pts)
            else:
                bench_waste.append((team_name, name, pos, pts))

    bench_waste.sort(key=lambda x: x[3], reverse=True)
    top_bench = bench_waste[0] if bench_waste else None

    return {
        "high_score_team": high_score_team,
        "high_score_pts": high_score_pts,
        "low_score_team": low_score_team,
        "low_score_pts": low_score_pts,
        "top_contributors": top_contributors,
        "mvp": mvp,
        "lowest_starter": lowest_starter,
        "closest": closest,
        "biggest_blowout": biggest_blowout,
        "top_bench": top_bench,
    }


# --------------------------------------------------------------------------
# Report computation — season-long position leaders
# --------------------------------------------------------------------------

def compute_season_position_leaders(league_id, through_week, users, rosters, players):
    """Cumulative starter points per player, weeks 1..through_week, then the
    top total at each of QB/RB/WR/TE. Team shown is whoever currently rosters
    that player (handles trades/waivers over the season)."""
    team_names = build_team_name_map(users, rosters)
    owner_map = {}
    for r in rosters:
        team = team_names.get(r["roster_id"])
        for pid in (r.get("players") or []):
            owner_map[pid] = team

    season_totals = {}
    for wk in range(1, through_week + 1):
        try:
            wk_matchups = get_json(f"{BASE}/league/{league_id}/matchups/{wk}")
        except Exception as e:
            print(f"Skipping week {wk} in season totals (error: {e})", file=sys.stderr)
            continue
        for m in wk_matchups:
            starters = set(m.get("starters", []) or [])
            player_points = m.get("players_points", {}) or {}
            for pid, pts in player_points.items():
                if pid not in starters:
                    continue
                season_totals[pid] = season_totals.get(pid, 0) + (pts or 0)

    best = {pos: None for pos in POSITIONS}  # pos -> (player_id, total)
    for pid, total in season_totals.items():
        _, pos = player_display(players, pid)
        if pos not in best:
            continue
        if best[pos] is None or total > best[pos][1]:
            best[pos] = (pid, total)

    leaders = {}
    for pos, entry in best.items():
        if entry is None:
            leaders[pos] = None
            continue
        pid, total = entry
        name, _ = player_display(players, pid)
        team = owner_map.get(pid, "Free Agent")
        leaders[pos] = (name, total, team)
    return leaders


# --------------------------------------------------------------------------
# Report text assembly
# --------------------------------------------------------------------------

def build_report_text(week, data, season_leaders, ai_blurb=None):
    lines = [f"WEEK {week} RECAP", ""]

    if ai_blurb:
        lines.append(ai_blurb.strip())
        lines.append("")

    lines.append(f"💰 Team of the Week: {data['high_score_team']} ({data['high_score_pts']:.2f} pts) — wins $15!")
    if data["top_contributors"]:
        contrib_str = ", ".join(f"{name} ({pos}, {pts:.2f} pts)" for name, pos, pts in data["top_contributors"])
        lines.append(f"   Top contributors: {contrib_str}")
    lines.append("")

    if data["mvp"]:
        name, pos, team, pts, stat_line = data["mvp"]
        lines.append(f"💰 Weekly MVP: {name} ({pos}, {team}) — {pts:.2f} pts — wins $15!")
        if stat_line:
            lines.append(f"   {stat_line}")
        lines.append("")

    lines.append("📈 Position Point Leaders (season total — top scorer at each position wins $25):")
    for pos in POSITIONS:
        leader = season_leaders.get(pos)
        if leader:
            name, total, team = leader
            lines.append(f"   {pos}: {name} ({team}) — {total:.2f} pts")
        else:
            lines.append(f"   {pos}: no data yet")
    lines.append("")

    lines.append("📊 Highlights:")
    if data["closest"]:
        diff, t1, p1, t2, p2 = data["closest"]
        lines.append(f"   Nail-biter: {t1} ({p1:.2f}) vs {t2} ({p2:.2f}) — decided by {diff:.2f} pts")
    if data["biggest_blowout"]:
        diff, t1, p1, t2, p2 = data["biggest_blowout"]
        winner, wp = (t1, p1) if p1 > p2 else (t2, p2)
        loser, lp = (t2, p2) if p1 > p2 else (t1, p1)
        lines.append(f"   Blowout: {winner} ({wp:.2f}) crushed {loser} ({lp:.2f}) by {diff:.2f} pts")
    if data["top_bench"]:
        team, name, pos, pts = data["top_bench"]
        lines.append(f"   Bench regret: {team} left {name} ({pos}) on the bench — {pts:.2f} pts wasted")

    return "\n".join(lines)


# --------------------------------------------------------------------------
# Optional AI commentary (Claude API)
# --------------------------------------------------------------------------

def generate_ai_commentary(week, data, api_key):
    # Deliberately does NOT get closest/blowout/bench-regret — those are already
    # covered in the Highlights section, so keeping them out here avoids the
    # recap just repeating the stats block in prose.
    prompt = (
        f"Write a fun, 4-6 sentence recap for week {week} of a fantasy football league group chat. "
        f"Bring real trash talk — needling, mock disrespect, some chirping at the other teams — but keep it "
        f"good-natured and nothing mean-spirited or personal. Definitely call out teams that had the worst "
        f"overall score or low scoring started. This is a great group of friends, so have fun with it.\n\n"
        f"Base it on:\n"
        f"- Team of the week: {data['high_score_team']} with {data['high_score_pts']:.2f} points"
    )
    if data["top_contributors"]:
        contrib_str = ", ".join(f"{name} ({pts:.2f} pts)" for name, pos, pts in data["top_contributors"])
        prompt += f", carried by {contrib_str}"
    prompt += "\n"
    if data["mvp"]:
        name, pos, team, pts, _ = data["mvp"]
        prompt += f"- Overall weekly high scorer: {name} ({pos}, {team}) with {pts:.2f} points\n"
    if data["lowest_starter"]:
        name, pos, team, pts = data["lowest_starter"]
        prompt += (
            f"- Biggest bust: {team} started {name} ({pos}), who only put up {pts:.2f} points — "
            f"call this team out specifically for starting them\n"
        )
    prompt += f"- Lowest scoring team: {data['low_score_team']} with only {data['low_score_pts']:.2f} points\n"
    prompt += (
        "\nDon't mention the closest matchup, the biggest blowout, or anyone's bench — those are covered "
        "elsewhere in the report. Return ONLY the recap text, nothing else — no preamble, no headers, "
        "no quotation marks around it."
    )

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": 350,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        r.raise_for_status()
        content = r.json()["content"]
        text = "".join(block.get("text", "") for block in content if block.get("type") == "text")
        return text.strip() or None
    except Exception as e:
        print(f"AI commentary skipped (error: {e})", file=sys.stderr)
        return None


# --------------------------------------------------------------------------
# GroupMe posting
# --------------------------------------------------------------------------

def post_to_groupme(text, bot_id):
    # GroupMe truncates messages over ~1000 chars, so split on blank lines if needed.
    chunks = []
    if len(text) <= 1000:
        chunks = [text]
    else:
        current = ""
        for block in text.split("\n\n"):
            if len(current) + len(block) + 2 > 1000:
                chunks.append(current)
                current = block
            else:
                current = f"{current}\n\n{block}" if current else block
        if current:
            chunks.append(current)

    for chunk in chunks:
        r = requests.post(
            "https://api.groupme.com/v3/bots/post",
            json={"bot_id": bot_id, "text": chunk},
            timeout=15,
        )
        r.raise_for_status()


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate and (optionally) post a weekly Sleeper report.")
    parser.add_argument("--no-post", action="store_true", help="Print the report but skip posting to GroupMe.")
    args = parser.parse_args()

    cfg = load_config()
    week = cfg["week"] or get_current_week()

    users, rosters, matchups, players = load_league_data(cfg["league_id"], week)
    season = get_league_season(cfg["league_id"])
    week_stats = get_week_stats(season, week)

    data = compute_report_data(users, rosters, matchups, players, week_stats)
    season_leaders = compute_season_position_leaders(cfg["league_id"], week, users, rosters, players)

    ai_blurb = None
    if cfg["anthropic_api_key"]:
        ai_blurb = generate_ai_commentary(week, data, cfg["anthropic_api_key"])

    report = build_report_text(week, data, season_leaders, ai_blurb)
    print(report)

    with open("weekly_report.txt", "w") as f:
        f.write(report)

    if cfg["groupme_bot_id"] and not args.no_post:
        post_to_groupme(report, cfg["groupme_bot_id"])
        print("\nPosted to GroupMe.", file=sys.stderr)


if __name__ == "__main__":
    main()
