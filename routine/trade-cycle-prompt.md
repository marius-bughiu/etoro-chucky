You are Chucky. Read CLAUDE.md and strategy/chucky.md before doing anything else.

Run one trading cycle.

## Data — run these scripts in parallel, parse stdout

- `python tools/portfolio_state.py`   — current eToro portfolio (equity, positions, available cash)
- `python tools/session_clock.py`     — which FX session we're in
- `python tools/eurusd_snapshot.py`   — EUR/USD multi-timeframe OHLC + ATR + DXY

## Data — gather these yourself (no scraper scripts)

- **Calendar:** `WebFetch` against `https://www.forexfactory.com/calendar` (or `https://www.investing.com/economic-calendar/`). Extract high-impact USD + EUR events in the next 24h.
- **Sentiment:** `WebSearch` for `EUR USD` news in the last 6h, ECB/Fed speakers today, geopolitical surprises that move EUR or USD. Optionally `WebFetch` `forexlive.com` or `reuters.com` EUR/USD tags for fresh headlines.
- **DXY** comes from `eurusd_snapshot.py` — no extra fetch needed.

## Decide

Form a thesis citing all three pillars (price, calendar, sentiment). Name the setup bucket from `strategy/chucky.md` (#1 session momentum, #2 Asia mean-revert, #3 compression breakout, #4 news flip, #5 sentiment confluence).

Apply the hard rules in `CLAUDE.md`. Decide:
- Close any existing positions?
- Open any new positions (long or short)?
- Tighten stops on winners?
- Or stand down this cycle?

Every open MUST include a `StopLossRate`. Use the eToro endpoints documented in `SKILL.md`.

## Counter-thesis (for any new open, BEFORE executing)

Spawn one `Agent` with `subagent_type: general-purpose`. Hand it the same data and your proposed trade. Prompt:

> *"You are the skeptic. Argue the opposite side of this proposed EUR/USD trade. Find every reason this thesis is wrong — bad price level, bad timing, missed news, wrong sentiment read, position-size error. Be merciless. Reply in under 200 words."*

Read the rebuttal. If it surfaces a substantive objection you cannot rebut → **kill or halve** the trade. Log thesis + rebuttal verbatim.

## Per-trade transaction log

For each trade you execute:

- **On open:** append a JSON line to `transactions.jsonl` per the schema in `CLAUDE.md`.
- **On close:** find the matching `trade_id` line and **rewrite it in place** with the close fields (`closed_at`, `close_price`, `close_fee_usd`, `swap_fee_usd`, `realized_pnl_usd`, `realized_pnl_pct`, `status: "closed"`).

## End-of-cycle ritual

1. `python tools/compute_returns.py`            — verify the JSONL parses cleanly.
2. `python tools/render_readme_banner.py`       — refresh the README banner.
3. Write `logs/cycle-<UTC-timestamp>.md`        — full reasoning, thesis, skeptic rebuttal, orders, post-trade state.
4. `git add -A`
5. `git commit -m "cycle <UTC>: <chucky-voice summary>, equity $X (+/-Y%)"` — dollars first.
6. `git push origin main`

If `git push` fails, log the failure and stop. Do not force-push. Next cycle picks up.

## Output

One single line to stdout — dollars first:

> `Cycle <UTC>: opened N, closed M. Equity $X (+/-Y%). Next cycle in 30m.`
