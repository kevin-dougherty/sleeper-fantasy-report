"""
Sleeper Weekly Fantasy Football Report Generator
--------------------------------------------------
Pulls data from the free, public Sleeper API (no auth needed) and builds a
copy-paste-ready text report showing:
  - Weekly high score (team) -> wins the $15 team payout
  - Weekly point leader by position: QB, RB, WR, TE -> each wins the $15 player payout
  - A few extra highlights (closest matchup, biggest blowout, best bench point left on table)

USAGE:
    python sleeper_weekly_report.py <league_id> <week>

Example:
    python sleeper_weekly_report.py 378845311639904256 3

Requires: pip install requests
"""

import sys
import requests

BASE = "https://api.sleeper.app/v1"


def get_json(url):
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()


def load_league_data(league_id, week):
    users = get_json(f"{BASE}/league/{league_id}/users")
    rosters = get_json(f"{BASE}/league/{league_id}/rosters")
    matchups = get_json(f"{BASE}/league/{league_id}/matchups/{week}")

    # Sleeper's global player dictionary is large (~5MB) but only needs to be
    # fetched once; cache it locally after first run if you call this often.
    players = get_json(f"{BASE}/players/nfl")

    return users, rosters, matchups, players


def build_team_name_map(users, rosters):
    """roster_id -> display/team name"""
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
    name = p.get("full_name") or f"{p.get('first_name','')} {p.get('last_name','')}".strip()
    pos = p.get("position", "UNK")
    return name, pos


def main():
    if len(sys.argv) != 3:
        print("Usage: python sleeper_weekly_report.py <league_id> <week>")
        sys.exit(1)

    league_id = sys.argv[1]
    week = int(sys.argv[2])

    users, rosters, matchups, players = load_league_data(league_id, week)
    team_names = build_team_name_map(users, rosters)

    # ---- Team scores & matchup pairing ----
    team_scores = []          # (team_name, points, matchup_id, roster_id)
    matchup_groups = {}       # matchup_id -> list of (team_name, points)

    for m in matchups:
        roster_id = m["roster_id"]
        points = m.get("points", 0) or 0
        team_name = team_names.get(roster_id, f"Roster {roster_id}")
        team_scores.append((team_name, points, m.get("matchup_id"), roster_id))
        matchup_groups.setdefault(m.get("matchup_id"), []).append((team_name, points))

    team_scores.sort(key=lambda x: x[1], reverse=True)
    high_score_team, high_score_pts = team_scores[0][0], team_scores[0][1]

    # ---- Closest matchup & biggest blowout ----
    closest = None
    biggest_blowout = None
    for mid, teams in matchup_groups.items():
        if len(teams) != 2:
            continue
        (t1, p1), (t2, p2) = teams
        diff = abs(p1 - p2)
        entry = (diff, t1, p1, t2, p2)
        if closest is None or diff < closest[0]:
            closest = entry
        if biggest_blowout is None or diff > biggest_blowout[0]:
            biggest_blowout = entry

    # ---- Position point leaders (starters only) ----
    # position -> (player_name, points, team_name)
    pos_leaders = {"QB": None, "RB": None, "WR": None, "TE": None}
    bench_waste = []  # (team_name, player_name, pos, points) for players left on bench

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

    # ---- Build the report ----
    lines = []
    lines.append(f"🏈 WEEK {week} RECAP 🏈")
    lines.append("")
    lines.append(f"💰 Team of the Week: {high_score_team} ({high_score_pts:.2f} pts) — wins $15!")
    lines.append("")
    lines.append("💰 Position Point Leaders (each wins $15):")
    for pos in ["QB", "RB", "WR", "TE"]:
        leader = pos_leaders[pos]
        if leader:
            name, pts, team = leader
            lines.append(f"   {pos}: {name} ({team}) — {pts:.2f} pts")
        else:
            lines.append(f"   {pos}: no starters found")
    lines.append("")
    lines.append("📊 Highlights:")
    if closest:
        diff, t1, p1, t2, p2 = closest
        lines.append(f"   Nail-biter: {t1} ({p1:.2f}) vs {t2} ({p2:.2f}) — decided by {diff:.2f} pts")
    if biggest_blowout:
        diff, t1, p1, t2, p2 = biggest_blowout
        winner, wp = (t1, p1) if p1 > p2 else (t2, p2)
        loser, lp = (t2, p2) if p1 > p2 else (t1, p1)
        lines.append(f"   Blowout: {winner} ({wp:.2f}) crushed {loser} ({lp:.2f}) by {diff:.2f} pts")
    if top_bench:
        team, name, pos, pts = top_bench
        lines.append(f"   Bench regret: {team} left {name} ({pos}) on the bench — {pts:.2f} pts wasted")

    report = "\n".join(lines)
    print(report)

    with open("weekly_report.txt", "w") as f:
        f.write(report)


if __name__ == "__main__":
    main()
