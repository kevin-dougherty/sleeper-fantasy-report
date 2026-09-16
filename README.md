# Sleeper Weekly Fantasy Football Report

A Python script that pulls data from the free, public [Sleeper API](https://docs.sleeper.app/), builds a weekly recap for a fantasy football league, adds a short trash-talking AI recap via the Claude API, and posts the whole thing to a GroupMe group — automatically, every Tuesday, via GitHub Actions.

Built for leagues that pay out weekly prizes for the top-scoring team and the top individual scorer, plus a season-long prize for the top scorer at each position.

## What it does

The script auto-detects the current NFL week (or reads a specific one from config) and produces a report with:

- **Team of the Week** — the highest-scoring team, plus a shoutout to its top two contributing starters
- **Weekly MVP** — the single highest-scoring starter league-wide, any position, with real box-score stats (yards, TDs, etc. pulled from Sleeper's stats endpoint)
- **Position Point Leaders** — a running, **season-long** cumulative leaderboard of total starter points at QB/RB/WR/TE, updated every run
- **Highlights** — closest matchup, biggest blowout, and the highest-scoring player left on a bench ("bench regret")
- **A short AI-generated recap** (optional) — a few sentences of good-natured trash talk from Claude, calling out the week's biggest bust and lowest-scoring team by name, layered on top of the stats

The report prints to the console, saves to `weekly_report.txt`, and (if configured) posts to a GroupMe group via a bot.

## Setup

```bash
git clone https://github.com/<your-username>/sleeper-fantasy-report.git
cd sleeper-fantasy-report

# optional but recommended: keep this project's one dependency isolated
python3 -m venv .venv
source .venv/bin/activate   # on Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

The repo pins `3.11` in `.python-version` — if you use [pyenv](https://github.com/pyenv/pyenv) it'll pick that up automatically. Neither `.venv/` nor pyenv itself ever gets committed (see `.gitignore`); the only things that make this reproducible for anyone else are `requirements.txt` and `.python-version`, and GitHub Actions installs `3.11` fresh on every run regardless of what's on your machine.

### Config

Real league/API values are kept out of the repo. Copy the template and fill in your own:

```bash
cp config.example.json config.json
```

```json
{
  "league_id": "your Sleeper league ID",
  "week": null,
  "groupme_bot_id": "your GroupMe bot ID",
  "anthropic_api_key": "your Anthropic API key"
}
```

`config.json` is gitignored, so it stays local to your machine and never gets pushed. Leave `week` as `null` to auto-detect the current NFL week, and leave `groupme_bot_id` / `anthropic_api_key` as the placeholder values if you don't want posting or AI commentary. This is the only place the script reads settings from — there's no CLI override for league ID or week, just `config.json`.

**Finding your league ID:** open your league in the Sleeper app or on sleeper.com — it's the numeric string in the URL (`sleeper.com/leagues/<league_id>/...`).

**Getting a GroupMe bot ID:** go to [dev.groupme.com/bots](https://dev.groupme.com/bots), create a bot for your group, and copy its Bot ID.

**Getting an Anthropic API key:** create one at [console.anthropic.com](https://console.anthropic.com) (this step is optional — the report works fine without AI commentary, just with no recap paragraph at the top).

## Usage

```bash
python src/sleeper_weekly_report.py
```

Options:

```bash
python src/sleeper_weekly_report.py --no-post     # print/save the report but skip GroupMe
```

Useful for testing changes to the recap tone without spamming the group — see `weekly_report.txt` or the console output instead.

## Automating it with GitHub Actions

`.github/workflows/weekly-report.yml` runs the script every Tuesday at 12:00 UTC and posts straight to GroupMe. Since the script only reads `config.json` (which isn't committed), the workflow generates a `config.json` on the runner from **GitHub Secrets** right before running the script — it never touches your repo, just the ephemeral Actions environment for that run:

1. In your repo: **Settings → Secrets and variables → Actions → New repository secret**
2. Add:
   - `LEAGUE_ID`
   - `GROUPME_BOT_ID`
   - `ANTHROPIC_API_KEY` (optional — omit to skip AI commentary)
3. That's it — the workflow will run automatically every Tuesday, or you can trigger it manually from the **Actions** tab (`Run workflow`).

Adjust the cron schedule in the workflow file if you want a different day/time — GitHub Actions cron is always in UTC.

## Example output

```
WEEK 3 RECAP

Burrow McConk In Her put up an obscene 177 points this week while half this league was still trying to figure out their flex spot. Meanwhile All the Glory to Garrett got run out of the building, and someone's really out here starting a guy for 4 points like it's a dare.

💰 Team of the Week: Burrow McConk In Her (177.36 pts) — wins $15!
   Top contributors: Caleb Williams (QB, 37.26 pts), Ja'Marr Chase (WR, 24.10 pts)

💰 Weekly MVP: Caleb Williams (QB, Cam Shaft) — 37.26 pts — wins $15!
   312 pass yds, 3 pass TDs, 41 rush yds

📈 Position Point Leaders (season total — top scorer at each position wins $25):
   QB: Caleb Williams (Cam Shaft) — 37.26 pts
   RB: Derrick Henry (Gay Retards) — 35.30 pts
   WR: Jalen Coker (Mo RBs Mo Problems) — 33.80 pts
   TE: Isaiah Likely (CMC Lifetime Keeper) — 27.80 pts

📊 Highlights:
   Nail-biter: Mayebe I Should Call Her (147.52) vs CMC Lifetime Keeper (156.56) — decided by 9.04 pts
   Blowout: Reese's Pieces (173.60) crushed All the Glory to Garrett (73.16) by 100.44 pts
   Bench regret: Canceled My 830 For This left Patrick Mahomes (QB) on the bench — 21.66 pts wasted
```

## Notes

- The Weekly MVP and Position Point Leaders are calculated from **starters only** — bench points don't count toward either.
- Position Point Leaders accumulates from Week 1 through whatever week you're on, refetching each past week's matchups every run — fast and free, just worth knowing it's a handful of extra API calls rather than a cached running total.
- The `players/nfl` endpoint returns Sleeper's full player dictionary (a few MB); fine to refetch on a weekly cron, but worth caching locally if you run this more often than weekly.
- GitHub Actions cron jobs can run a few minutes late during high-traffic periods (like Tuesday mornings across all of GitHub) — that's normal.
- If you added a temporary debug step to the workflow while troubleshooting secrets, remember to remove it once things are confirmed working — it echoes filenames/directory contents to the logs, which is fine short-term but not something to leave in permanently.

## Roadmap ideas

- [ ] Cache the player dictionary locally
- [ ] Support for Discord/Slack webhooks as alternatives to GroupMe

## License

MIT
