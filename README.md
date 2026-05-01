<!-- CHUCKY-BANNER:START -->
## Live performance — last cycle 2026-05-01T08:48Z

**Open positions:** 0

| Window | P&L | Return % | Trades |
|---|---|---|---|
| 24h | n/a | n/a | 0 |
| 7d | n/a | n/a | 0 |
| 30d | n/a | n/a | 0 |
| 12m | n/a | n/a | 0 |
| All-time | n/a | n/a | 0 |

### Last 10 trades
_No closed trades yet._
<!-- CHUCKY-BANNER:END -->

# etoro-chucky

> An aggressive, autonomous EUR/USD day-trading agent for **eToro agent-portfolios** — every decision made by an LLM, in real time. No algorithmic signals. No coded strategy. The model reads the tape every cycle and decides.

⚠ **Not financial advice.** This repo runs an experimental autonomous trading agent against a real eToro agent-portfolio (which mirrors at a configurable proportion into the user's real account). You can lose money. You accept that risk. The author accepts none.

---

## What this is

Most "AI trading bots" are an LLM-shaped wrapper around a hand-coded strategy: an algorithm decides, the LLM rationalises. This is the inverse: the **strategy doc** ([`strategy/chucky.md`](strategy/chucky.md)) and the **standing orders** ([`CLAUDE.md`](CLAUDE.md)) are read fresh by the model every cycle, and the model — not the code — decides what to open, close, size, or flip.

Code is allowed only as a tool layer:

- Fetch EUR/USD OHLC, ATR, DXY (`tools/eurusd_snapshot.py`)
- Fetch eToro portfolio state (`tools/portfolio_state.py`)
- Classify the current FX session (`tools/session_clock.py`)
- Compute returns over rolling windows (`tools/compute_returns.py`)
- Format the README banner (`tools/render_readme_banner.py`)
- Execute orders the model has chosen, against the eToro API per [`SKILL.md`](SKILL.md)

Calendar and sentiment? The model pulls those itself with `WebFetch` and `WebSearch` each cycle. No fragile scraper scripts.

---

## Architecture

```
                     ┌─────────────────────────────────────┐
                     │  Claude Code native routine (cron)  │
                     │   *​/30 6-21 * * 1-5  (every 30m)   │
                     └────────────────┬────────────────────┘
                                      │ fires
                                      ▼
                     ┌─────────────────────────────────────┐
                     │   routine/trade-cycle-prompt.md     │
                     │       (the cycle prompt)            │
                     └────────────────┬────────────────────┘
                                      │
                                      ▼
              ┌────────────── Chucky (the LLM) ───────────────┐
              │                                                │
              │  reads:  CLAUDE.md, strategy/chucky.md         │
              │          tools/*.py outputs (parallel)         │
              │          calendar via WebFetch (forexfactory)  │
              │          sentiment via WebSearch (last 6h)     │
              │                                                │
              │  decides: open/close/flip/stand-down           │
              │  red-teams: spawns a skeptic sub-agent         │
              │  executes: eToro API per SKILL.md              │
              │                                                │
              └────────────────────┬───────────────────────────┘
                                   │ writes
                                   ▼
            ┌──────────────────────┴──────────────────────┐
            │                                              │
   transactions.jsonl                          logs/cycle-<UTC>.md
   (per-trade record, public)                  (full reasoning audit, public)
            │                                              │
            └──────────────────────┬──────────────────────┘
                                   ▼
                    tools/render_readme_banner.py
                                   │
                                   ▼
                       README.md banner refreshed
                                   │
                                   ▼
                  git add -A → commit → push origin main
```

---

## Setup

1. **Clone, then install Python deps:**
   ```bash
   python -m venv tools/.venv
   tools/.venv/Scripts/activate    # or: source tools/.venv/bin/activate
   pip install -r tools/requirements.txt
   ```

2. **Create `.env`** from `.env.example` and paste your eToro agent-portfolio user token:
   ```
   ETORO_USER_TOKEN=<the-token-shown-once-at-portfolio-creation>
   ```
   `.env` is gitignored. Don't commit it. See `SKILL.md` for how to create the token.

3. **Verify git push works** (the cycle commits and pushes to `main` every tick):
   ```bash
   git push --dry-run origin main
   ```

4. **Smoke-test the tools:**
   ```bash
   python tools/session_clock.py
   python tools/eurusd_snapshot.py
   python tools/compute_returns.py
   python tools/render_readme_banner.py
   ```

5. **Register the Claude Code routine.** See [`routine/setup.md`](routine/setup.md) — the cadence, cron expression, and `/schedule` walkthrough live there.

---

## Dry-run a single cycle

To test without scheduling:

```bash
claude -p "$(cat routine/trade-cycle-prompt.md)"
```

Inspect afterward:
- a fresh `logs/cycle-*.md`
- any new lines in `transactions.jsonl`
- the refreshed banner at the top of this README
- the resulting commit on `main`

---

## Stop

- **Pause one cycle:** do nothing. The next cron tick re-runs.
- **Stop the routine:** in Claude Code, `/schedule` → list → delete the Chucky routine.
- **Emergency flatten:** in any CC session, paste:
  > *"Read CLAUDE.md and SKILL.md. Close every open position on the eToro agent-portfolio at market. Update transactions.jsonl. Commit and push. Output dollar P&L per position and total."*

---

## Where to look

| File | What it is |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Standing orders. Hard rules. Auto-loaded into every CC session in this repo. |
| [`strategy/chucky.md`](strategy/chucky.md) | The aggressive playbook. Five setups, position management ladder, fee model. |
| [`SKILL.md`](SKILL.md) | The eToro agent-portfolio API contract (auth, open/close, PnL, rate limits, forex specifics). |
| [`routine/trade-cycle-prompt.md`](routine/trade-cycle-prompt.md) | The exact prompt the routine fires each cycle. |
| [`routine/setup.md`](routine/setup.md) | How to register the CC routine. |
| `transactions.jsonl` | Append/update log of every trade. Machine-parseable. Public. |
| `logs/cycle-*.md` | Per-cycle reasoning audit. Public. |
| `tools/` | Analysis-only Python. **No decision logic anywhere.** |

---

## License

[MIT](LICENSE)
