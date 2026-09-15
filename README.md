# Sleeper Weekly Fantasy Football Report

A small Python script that pulls data from the free, public [Sleeper API](https://docs.sleeper.app/) and generates a weekly recap for a fantasy football league — built for leagues that pay out weekly prizes for the top-scoring team and top-scoring player at each position.

No API key or authentication required — Sleeper's read endpoints are open to anyone.

## What it does

Given a league ID and a week number, the script pulls that week's matchups and rosters and produces a text report with:

- **Team of the Week** — the highest-scoring team (weekly high-score payout)
- **Position point leaders** — the top scorer among starters at QB, RB, WR, and TE (position payouts)
- **Highlights** — closest matchup of the week, biggest blowout, and the highest-scoring player left on a bench ("bench regret")

The report prints to the console and is also saved to `weekly_report.txt` for easy copy-paste into a group chat.

## Setup

```bash
git clone https://github.com/<your-username>/sleeper-fantasy-report.git
cd sleeper-fantasy-report
pip install -r requirements.txt
```

## Usage

```bash
python src/sleeper_weekly_report.py <league_id> <week>
```

Example:

```bash
python src/sleeper_weekly_report.py 378845311639904256 3
```

### Finding your league ID

Open your league in the Sleeper app or on sleeper.com — the league ID is the numeric string in the URL, e.g. `sleeper.com/leagues/<league_id>/...`.

## Example output

```
🏈 WEEK 3 RECAP 🏈

💰 Team of the Week: Kevin's Krew (142.30 pts) — wins $15!

💰 Position Point Leaders (each wins $15):
   QB: Josh Allen (Team X) — 31.20 pts
   RB: Bijan Robinson (Team Y) — 28.40 pts
   WR: Justin Jefferson (Team Z) — 24.10 pts
   TE: Sam LaPorta (Team W) — 19.80 pts

📊 Highlights:
   Nail-biter: Team A (110.20) vs Team B (109.90) — decided by 0.30 pts
   Blowout: Team C (155.00) crushed Team D (85.00) by 70.00 pts
   Bench regret: Team E left Marvin Harrison Jr. (WR) on the bench — 26.40 pts wasted
```

## Notes

- Position leaders are calculated from **starters only** — bench players don't count toward position payouts unless you change the logic.
- The `players/nfl` endpoint returns Sleeper's full player dictionary (a few MB) and rarely changes week to week. If you run this often, consider caching it locally instead of re-fetching every run.
- Run it after Monday Night Football wraps up and stats finalize (typically Tuesday morning) to get final numbers.

## Roadmap ideas

- [ ] Cache the player dictionary locally
- [ ] Auto-post the report to Discord/GroupMe/Slack via webhook
- [ ] Layer in AI-generated commentary on top of the stats
- [ ] Season-long standings/leaderboard tracking

## License

MIT
