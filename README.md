# Valorant AI Analyst
Passion project to make professional analysis of Valorant matches accessible to anyone.

Give it one match; it computes the stats in code (ACS, ADR, KAST, first bloods, trades, clutches, economy,
post-plant and retakes), then Claude explains what decided the match and what to fix. Every AI claim must cite
the computed facts it is based on, and a validator drops any claim that doesn't check out.

> **Prototype data source:** the unofficial [HenrikDev API](https://docs.henrikdev.xyz), which Riot does not
> endorse. Use it locally on your own matches only. The plan is to move to Riot's official API.

## Setup

Requires Python 3.11+.

```powershell
pip install -e .
setx HENRIK_API_KEY "your-henrik-key"        # free Basic key: https://api.henrikdev.xyz/dashboard
setx ANTHROPIC_API_KEY "sk-ant-api03-..."    # https://console.anthropic.com/settings/keys
```

`setx` saves the keys permanently but only for **new** terminals, so open a new one afterwards.
(For the current terminal only: `$env:HENRIK_API_KEY = "..."`; in Git Bash: `export HENRIK_API_KEY=...`.)

## Find a match ID

List your last 5 matches (replace region, name and tag):

```powershell
$r = Invoke-RestMethod -Headers @{Authorization = $env:HENRIK_API_KEY} `
  "https://api.henrikdev.xyz/valorant/v4/matches/na/pc/$([uri]::EscapeDataString('YourName'))/TAG?size=5"
$r.data | ForEach-Object { "{0}  {1,-10} {2,-12} {3}" -f $_.metadata.match_id, $_.metadata.map.name, $_.metadata.queue.id, $_.metadata.started_at }
```

Supported modes: competitive, unrated, premier, swiftplay, custom (5v5).

## Run

```powershell
python -m valoanalyst <match_id> --region na --player "YourName#TAG"                # team review
python -m valoanalyst <match_id> --region na --player "YourName#TAG" --mode player  # focus on you
python -m valoanalyst <match_id> --region na --player "YourName#TAG" --no-llm       # stats only, free
python -m unittest                                                                  # tests
```

| Option | Meaning |
|---|---|
| `--region` | `na`, `eu`, `ap`, `kr`, `latam`, `br` (default `na`) |
| `--player` | your Riot ID; the report is written from your team's side |
| `--mode` | `team` (default) or `player` |
| `--file` | analyze a saved HenrikDev v4 JSON file instead of fetching |
| `--no-llm` | skip Claude; stats tables only |
| `--out` | output folder (default `reports/`) |

- Reports: `reports/<match_id>-<mode>.md`. Claims the validator dropped are printed to the terminal.
- Raw API responses are cached in `cache/henrik/`, so re-running a match doesn't call HenrikDev again.
- Other players appear as Ally2–5 / Enemy1–5; Riot IDs are never sent to Claude.
- One AI report costs roughly $0.10–0.20 (Claude Opus 5.5).

## What it can't see

The data has kills, timings, weapons, economy, plants/defuses, damage totals and ability-cast counts. It has
no utility placement, positioning outside kill moments, crosshair placement or comms, so the feedback never
comments on those.

## Troubleshooting

- **`AI feedback unavailable (AuthenticationError ... 401 invalid x-api-key)`**: the Anthropic key in that terminal
  is wrong or stale. Open a new terminal after `setx`, check nothing (e.g. `$PROFILE`) sets an old value, then test
  with `python -c "import anthropic; anthropic.Anthropic().models.list(); print('key ok')"`.
- **`HenrikDev: API key rejected`**: `HENRIK_API_KEY` isn't set in this terminal, or the key is wrong.
- **`HenrikDev: match not found`**: check the match ID and `--region`.
- **`... is not in this match`**: `--player` must match your Riot ID exactly (case doesn't matter); the error lists the players.
- **`rate limited`**: the free Basic key allows 30 requests per minute; wait a minute.

## Project layout

```
valoanalyst/
  henrik.py    fetch + cache + convert HenrikDev v4 JSON to the internal model
  models.py    normalized match data (source-independent)
  metrics.py   all stats, round cards and citable facts
  llm.py       Claude call with structured output
  validate.py  drops AI claims not grounded in the facts
  render.py    Markdown report
tests/         synthetic-match tests (python -m unittest)
```
