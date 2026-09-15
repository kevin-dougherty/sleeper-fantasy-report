"""
Sleeper Weekly Fantasy Football Report Generator
--------------------------------------------------
Pulls data from the free, public Sleeper API (no auth needed), builds a report
showing the weekly high-score team, position point leaders (QB/RB/WR/TE), and
a few highlights — optionally adds a short AI-generated recap via the Claude
API, then posts the whole thing to a GroupMe group.

CONFIG (in priority order — highest wins):
  1. CLI args:      --league-id, --week
  2. Environment:   LEAGUE_ID, WEEK, GROUPME_BOT_ID, ANTHROPIC_API_KEY
  3. config.json:   copy config.example.json -> config.json and fill it in
                     (config.json is gitignored — safe to keep real values there)

USAGE:
    python src/sleeper_weekly_report.py
    python src/sleeper_weekly_report.py --league-id 378845311639904256 --week 3

Requires: pip install -r requirements.txt
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests

BASE = "https://api.sleeper.app/v1"
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"
ANTHROPIC_MODEL = "claude-sonnet-5"


# --------------------------------------------------------------------------
# Config loading
# --------------------------------------------------------------------------

def load_config(cli_league_id=None, cli_week=None):
    cfg = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)

    league_id = cli_league_id or os.environ.get("LEAGUE_ID") or cfg.get("league_id")
    week_raw = cli_week or os.environ.get("WEEK") or cfg.get("week")
    week = int(week_raw) if week_raw else None
    groupme_bot_id = os.environ.get("GROUPME_BOT_ID") or cfg.get("groupme_bot_id")
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY") or cfg.get("anthropic_api_key")

    if not league_id or league_id.startswith("YOUR_"):
        sys.exit(
            "No league_id found. Set it via --league-id, the LEAGUE_ID env var, "
            "or config.json (copy config.example.json to config.json first)."
        )

    return {
        "league_id": league_id,
        "week": week,
        "groupme_bot_id": groupme_bot_id if groupme_bot_id and not groupme_bot_id.startswith("YOUR_") else None,
        "anthropic_api_key": anthropic_api_key if anthropic_api_key and not anthropic_api_key.startswith("YOUR_") else None,
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


# --------------------------------------------------------------------------
# Report computation
# --------------------------------------------------------------------------

def compute_report_data(users, rosters, matchups, players):
    team_names = build_team_name_map(users, rosters)

    team_scores = []
    matchup_groups = {}
    for m in matchups:
        roster_id = m["roster_id"]
        points = m.get("points", 0) or 0
        team_name = team_names.get(roster_id, f"Roster {roster_id}")
        team_scores.append((team_name, points))
        matchup_groups.setdefault(m.get("matchup_id"), []).append((team_name, points))

    team_scores.sort(key=lambda x: x[1], reverse=True)
    high_score_team, high_score_pts = team_scores[0]

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

    pos_leaders = {"QB": None, "RB": None, "WR": None, "TE": None}
    bench_waste = []

    for m in matchups:
        roster_id = m["roster_id"]
        team_name = team_names.get(roster_id, f"Roster {roster_id}")
        starters = set(m.get("starters", []) or [])
        player_points = m.get("players_points", {}) or {}

        for pid, pts in player_points.items():
            name, pos = player_display(players, pid)
            is_starter = pid in starters
            if is_starter and pos in pos_leaders:
                current = pos_leaders[pos]
                if current is None or pts > current[1]:
                    pos_leaders[pos] = (name, pts, team_name)
            if not is_starter:
                bench_waste.append((team_name, name, pos, pts))

    bench_waste.sort(key=lambda x: x[3], reverse=True)
    top_bench = bench_waste[0] if bench_waste else None

    return {
        "high_score_team": high_score_team,
        "high_score_pts": high_score_pts,
        "pos_leaders": pos_leaders,
        "closest": closest,
        "biggest_blowout": biggest_blowout,
        "top_bench": top_bench,
    }


def build_report_text(week, data, ai_blurb=None):
    lines = [f"🏈 WEEK {week} RECAP 🏈", ""]

    if ai_blurb:
        lines.append(ai_blurb.strip())
        lines.append("")

    lines.append(f"💰 Team of the Week: {data['high_score_team']} ({data['high_score_pts']:.2f} pts) — wins $15!")
    lines.append("")
    lines.append("💰 Position Point Leaders (each wins $15):")
    for pos in ["QB", "RB", "WR", "TE"]:
        leader = data["pos_leaders"][pos]
        if leader:
            name, pts, team = leader
            lines.append(f"   {pos}: {name} ({team}) — {pts:.2f} pts")
        else:
            lines.append(f"   {pos}: no starters found")
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
    prompt = (
        f"Write a fun, 2-3 sentence recap for week {week} of a fantasy football league group chat. "
        f"Be playful and a little bit of a trash-talker, but keep it good-natured.\n\n"
        f"Data:\n"
        f"- Highest scoring team: {data['high_score_team']} with {data['high_score_pts']:.2f} points\n"
    )
    if data["biggest_blowout"]:
        diff, t1, p1, t2, p2 = data["biggest_blowout"]
        winner = t1 if p1 > p2 else t2
        loser = t2 if p1 > p2 else t1
        prompt += f"- Biggest blowout: {winner} beat {loser} by {diff:.2f} points\n"
    if data["closest"]:
        diff, t1, t2 = data["closest"][0], data["closest"][1], data["closest"][3]
        prompt += f"- Closest matchup: {t1} vs {t2}, decided by {diff:.2f} points\n"
    if data["top_bench"]:
        team, name, pos, pts = data["top_bench"]
        prompt += f"- Bench regret: {team} left {name} ({pos}) on the bench for {pts:.2f} points\n"
    prompt += "\nJust return the 2-3 sentences, nothing else."

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
                "max_tokens": 200,
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
    parser.add_argument("--league-id", dest="league_id", default=None)
    parser.add_argument("--week", dest="week", default=None)
    parser.add_argument("--no-post", action="store_true", help="Print the report but skip posting to GroupMe.")
    args = parser.parse_args()

    cfg = load_config(cli_league_id=args.league_id, cli_week=args.week)
    week = cfg["week"] or get_current_week()

    users, rosters, matchups, players = load_league_data(cfg["league_id"], week)
    data = compute_report_data(users, rosters, matchups, players)

    ai_blurb = None
    if cfg["anthropic_api_key"]:
        ai_blurb = generate_ai_commentary(week, data, cfg["anthropic_api_key"])

    report = build_report_text(week, data, ai_blurb)
    print(report)

    with open("weekly_report.txt", "w") as f:
        f.write(report)

    if cfg["groupme_bot_id"] and not args.no_post:
        post_to_groupme(report, cfg["groupme_bot_id"])
        print("\nPosted to GroupMe.", file=sys.stderr)


if __name__ == "__main__":
    main()
