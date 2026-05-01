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
- Format the performance banner below (`tools/render_readme_banner.py`)
- Execute orders the model has chosen, against the eToro API per [`SKILL.md`](SKILL.md)

Calendar and sentiment? The model pulls those itself with `WebFetch` and `WebSearch` each cycle. No fragile scraper scripts.

---

<!-- CHUCKY-BANNER:START -->
## Live performance — last cycle 2026-05-01T12:18Z

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
