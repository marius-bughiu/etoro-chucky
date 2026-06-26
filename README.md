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
## Live performance — last cycle 2026-06-26T10:49Z

**Open positions:** 0

| Window | P&L | Return % | Trades |
|---|---|---|---|
| 24h | n/a | n/a | 0 |
| 7d | +$0.53 | +0.01% | 1 |
| 30d | -$100.43 | -0.62% | 4 |
| 12m | -$105.56 | -0.63% | 5 |
| All-time | -$105.56 | -0.63% | 5 |

### Last 10 trades
| # | opened (UTC) | side | size | entry | closed (UTC) | exit | fees | P&L $ | P&L % |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-06-24 00:36:44 | short | $6,000.00 | 1.13762 | 2026-06-24 00:40:53 | 1.13757 | $0.00 | +$0.53 | +0.01% |
| 2 | 2026-06-08 13:36:34 | long | $4,000.00 | 1.15503 | 2026-06-08 14:28:00 | 1.1534 | $0.00 | -$56.45 | -1.41% |
| 3 | 2026-06-08 09:05:38 | short | $3,750.00 | 1.15081 | 2026-06-08 10:19:16 | 1.15172 | $0.00 | -$29.65 | -0.79% |
| 4 | 2026-06-03 08:52:28 | short | $2,500.00 | 1.1608 | 2026-06-03 09:50:53 | 1.16149 | $0.00 | -$14.86 | -0.59% |
| 5 | 2026-05-01 14:20:36 | long | $500.00 | 1.17829 | 2026-05-01 14:49:32 | 1.17726 | $0.00 | -$5.13 | -1.03% |
<!-- CHUCKY-BANNER:END -->
