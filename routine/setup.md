# Routine setup

Chucky runs as a **native Claude Code routine** — Claude Code itself fires the trade cycle on a cron schedule. No Windows Task Scheduler, no external cron, no daemon.

## Prerequisites (one-time)

1. **Clone the repo and `cd` into it.**

2. **Install the analysis tools' Python deps.** From the repo root:
   ```bash
   python -m venv tools/.venv
   tools/.venv/Scripts/activate    # Windows; or  source tools/.venv/bin/activate on bash
   pip install -r tools/requirements.txt
   ```

3. **Create `.env` from the template.** Copy `.env.example` to `.env` and paste your eToro agent-portfolio user token:
   ```
   ETORO_USER_TOKEN=<paste-the-token-from-portfolio-creation>
   ```
   `.env` is gitignored. Never commit a real token.

4. **Verify git push works.** From the repo root:
   ```bash
   git remote get-url origin
   git push --dry-run origin main
   ```
   The routine commits and pushes every cycle. If push prompts for credentials, configure a credential helper (`git config --global credential.helper manager-core` on Windows, or set up a GitHub PAT) before the first cycle.

5. **Smoke-test each tool.** None of these need an eToro token except `portfolio_state.py`:
   ```bash
   python tools/session_clock.py
   python tools/eurusd_snapshot.py
   python tools/compute_returns.py
   python tools/render_readme_banner.py
   ```

## Register the routine

From a Claude Code session inside `C:\S\etoro-chucky`, invoke the schedule skill:

```
/schedule
```

When prompted, configure:

- **Title:** `Chucky EUR/USD trade cycle`
- **Cron:** `*/30 6-21 * * 1-5`
  *(every 30 min, 06:00–21:30 UTC, weekdays only)*
  Aggressive but sane. You can dial up to `*/15` for more reps, or down to `0,30 7-20 * * 1-5` for a tighter window.
- **Working directory:** `C:\S\etoro-chucky`
- **Prompt:** the full contents of `routine/trade-cycle-prompt.md`. Either paste it inline or instruct the routine to read it from the file each tick:
  > *"Read and execute `routine/trade-cycle-prompt.md`."*

The cron above means Chucky will:
- never fire on weekends (so no Friday-night → Monday-morning gap risk between cycles),
- start each weekday at 06:00 UTC (London open warmup),
- finish at 21:30 UTC (post-NY close, well before any Friday 21:00 flat-by deadline).

## Manual dry-run (before going live)

To test the prompt end-to-end without scheduling:

```bash
claude -p "$(cat routine/trade-cycle-prompt.md)"
```

This runs exactly one cycle. Inspect:
- `logs/cycle-*.md` (newly created)
- `transactions.jsonl` (any new lines if a trade was placed)
- `README.md` (banner refreshed)
- the commit on `main` and the push

If anything looks wrong, fix it before scheduling. The routine is unsupervised — anything broken at registration time stays broken until you intervene.

## Pause / stop

- **Pause one cycle:** nothing to do — just don't worry about it. The next cron tick re-runs.
- **Stop the routine:** in a Claude Code session, list scheduled routines and delete the Chucky one. (`/schedule` provides the UI.)
- **Emergency flatten:** to close every open position right now, run a one-shot prompt in any CC session:

  > *"Read CLAUDE.md and SKILL.md. Close every open position on the eToro agent-portfolio at market. Use the close-by-positionId endpoint per SKILL.md. Update transactions.jsonl for each close. Commit and push. Output dollar P&L per position and total."*

## Alternative: `/loop` for in-session live tests

If you want to babysit it for the first day before trusting the unattended routine, open a Claude Code session in this repo and run:

```
/loop 30m read and execute routine/trade-cycle-prompt.md
```

This ticks every 30 minutes for as long as the session stays open. Same prompt, same outputs. Stop with `Ctrl-C` or by closing the session.

## Cadence tuning

| Cron | Cadence | Use case |
|---|---|---|
| `*/15 6-21 * * 1-5` | every 15 min | maximum aggressiveness; more cycles, more API calls |
| `*/30 6-21 * * 1-5` | every 30 min | **default** — sane, captures most setups |
| `0 6-21 * * 1-5` | hourly | conservative; you'll miss faster session-momentum trades |
| `*/30 7-9,13-16 * * 1-5` | only during London-open + NY-overlap | only the sharpest hours |

Pick one. Default works.
