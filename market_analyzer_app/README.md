# FC Mobile Market Analyzer

An automated trading bot for EA FC Mobile. This tool fetches market data for high-rated players from RenderZ, tracks their price trends locally, and uses a deterministic mean-reversion filter — backed by an LLM for a final qualitative sanity check — to flag statistically-supported investment opportunities while accounting for the EA 10% market tax. See [Trading Strategy](#-trading-strategy) below for how a signal is actually decided; no automated signal from a price snapshot is ever "guaranteed."

## 🚀 Quick Start (For Ordinary Users)

### 1. Prerequisites
1. Install [Python 3](https://www.python.org/downloads/).
2. Open your terminal (or Command Prompt on Windows) and install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file in the main project folder (the one containing `requirements.txt`) and add an API key. The bot picks a provider in this order, using the first one available:
   1. **Claude (primary)** — set `ANTHROPIC_API_KEY=your_api_key_here`
   2. **Gemini (fallback)** — set `GEMINI_API_KEY=your_api_key_here` if no Claude key is present
   3. **Local Ollama (free fallback)** — if neither key is set, the bot calls a local Ollama server (`http://localhost:11434`, model `llama3.1` by default). Requires [Ollama](https://ollama.com) installed and the model pulled (`ollama pull llama3.1`) on the machine running the bot.

   You can set both `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` — Gemini is only used if the Claude call fails or the key is absent.

### 2. Configuration
You can customize the filters the bot uses by editing `market_analyzer_app/config.json`:
- `min_rating` / `max_rating`: The OVR range to search for (e.g., 106 to 114).
- `min_price` / `max_price`: The budget you want to search within (e.g., 100,000,000 to 1,000,000,000).
- `programs`: The specific event cards to target (e.g., Icons, Heroes).
- `interval_hours`: How long the bot waits between market scans (default: 6 hours).
- `log_file` / `status_file`: where the activity log and status snapshot are written (defaults: `market_analyzer.log`, `status.json`) — see [Command-Line Options](#5-command-line-options).
- `strategy`: tunable thresholds for the reversion filter — see [Trading Strategy](#-trading-strategy).

### 3. How to Run on Windows 11
Windows users can manage the bot with a single interactive file: `windows_manager.pyw`. This is a pure-Python manager (no VBS/PowerShell dependency), so it isn't affected by Windows Script Host being disabled — a common security setting on locked-down machines.
- **Start/Stop the Bot:** Inside the `market_analyzer_app` folder, simply double-click `windows_manager.pyw`. It will automatically detect if the bot is running. If it is running, it will ask if you want to stop it. If it isn't, it will ask if you want to start it silently in the background!
- **Auto-Start on Boot:** Press `Win + R`, type `shell:startup`, and create a shortcut there targeting `pythonw.exe` with the full path to `windows_manager.pyw` and the argument `autostart`. Set the shortcut's Target to your own `pythonw.exe` and repo paths, e.g. on this machine:
  ```
  "C:\Users\mdati\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe" "C:\Users\mdati\Projects\Personal\fc-mobile\market_analyzer_app\windows_manager.pyw" autostart
  ```
  It will now start silently every time you turn on your PC, with no popups.

### 4. How to Run on Linux
Linux users can run the bot interactively or as a background service:
- **Interactive Terminal:**
  ```bash
  python3 market_analyzer_app/market_analyzer.py
  ```
- **Run Permanently via Systemd (Survives Reboots):**
  To install the background service on a **new machine**, follow these steps:
  
  1. Open `fc-market-analyzer.service` and change `WorkingDirectory=/home/atik/Projects/Personal/fc-mobile` to the absolute path of this project on your new machine.
  2. Create the systemd user directory if it doesn't exist:
     ```bash
     mkdir -p ~/.config/systemd/user/
     ```
  3. Copy the service file into the systemd directory:
     ```bash
     cp market_analyzer_app/fc-market-analyzer.service ~/.config/systemd/user/
     ```
  4. Reload systemd and enable the service to start automatically on boot:
     ```bash
     systemctl --user daemon-reload
     systemctl --user enable fc-market-analyzer.service
     systemctl --user start fc-market-analyzer.service
     ```

  Once installed, you can manage the bot anytime using standard commands:
  - Start: `systemctl --user start fc-market-analyzer.service`
  - Stop: `systemctl --user stop fc-market-analyzer.service`
  - Logs: `journalctl --user -u fc-market-analyzer.service -f`
  - Check Status: `systemctl --user status fc-market-analyzer.service`

### 5. Command-Line Options
```bash
python market_analyzer_app/market_analyzer.py            # run continuously (the normal 24/7 mode)
python market_analyzer_app/market_analyzer.py --test-run  # run exactly one cycle then exit — useful after changing config.json
python market_analyzer_app/market_analyzer.py --status    # read-only: print current state and exit, safe alongside a live instance
```

The bot writes its own log file (`market_analyzer.log`, rotated automatically) and a small `status.json` snapshot on every cycle — useful since a silently-backgrounded instance (e.g. started via `windows_manager.pyw`) has no visible console output at all. `--status` reports the last/next cycle times, how many players are tracked, how many have enough history to be evaluated yet, which LLM provider actually served the last analysis, and the most recent error if any.

*(Note: The bot requires at least `min_history_points` (default 4) historical data points per card before it can evaluate a trend. It will skip newly-discovered cards until enough history accumulates — `--status` shows exactly how many are ready.)*

---

## ⚙️ Technical Details (For Advanced Users)

### RenderZ's 2026-09 Search API Migration
RenderZ replaced their whole player-search backend around 2026-09-03 — the old `POST /api/players/filter` started 404ing on every single request (confirmed via direct reproduction, and ruled out season-ID staleness, since all season IDs 404'd identically). The site now does full server-side rendering with an Elasticsearch-backed `GET /api/search/{seasonId}?v=1&q=<encoded>` endpoint, where `q` is a JSON Elasticsearch query DSL, raw-deflate compressed and base64url-encoded. This was reverse-engineered on 2026-09-04 via a Playwright-driven browser session capturing the live site's own network requests — not by crawling RenderZ's JS bundles in bulk, consistent with the earlier decision to respect their `robots.txt` (which disallows `ClaudeBot` and `/api/*` for all crawlers); this specific investigation was done on the user's explicit instruction.

Two genuine improvements came with the migration:
1. **Server-side filtering now actually works.** The old backend silently ignored OVR/price/auctionable filters and just dumped everything matching the program filter; the new one correctly honours rating range, `auctionable`, and program (`source.keyword`) filters server-side (verified empirically) — client-side re-filtering in `fetch_players` is now a defensive safety net, not a required workaround.
2. **Page size went from 20 to 100** (the confirmed max — 200 is rejected), cutting the number of paginated requests per cycle by 5x, which also reduces exposure to the flaky-timeout issue below.

The player object's id field is now `assetId` (was `id`) — same numbering scheme, just renamed; `priceData` (used for the rank-0 price) is unchanged.

### Pagination Strategy
No page-count metadata is returned anymore, so pagination stops when a page returns fewer than the requested page size (100) rather than checking a `pageCount` field. The script still introduces a `0.4s` polite sleep between paginated calls to avoid hammering the RenderZ API.

### Handling RenderZ's Flaky Backend
RenderZ's API times out on roughly 1 in 5 requests at random — not tied to any specific endpoint, just observed empirically. A full cycle makes ~140 pagination requests plus one `get_player_market` call per tracked player (~160+), so without retries a cycle was virtually guaranteed to hit at least one timeout and abort entirely partway through. Every request in `scripts/renderz_api.py` (`search_players`, `get_player_market`, `get_filter_options`) now goes through a shared retry-with-backoff helper (`_request_json`) before giving up — verified empirically to bring the effective failure rate to zero across dozens of consecutive requests.

### Historical Data Tracking
Player market data is persisted in `price_history.json`.
- To prevent JSON bloat for a script that runs 24/7, the `prices` array acts as a rolling buffer, keeping only the 10 most recent chronological data points.
- Each poll also fetches `GET /api/player/market/{id}` (RenderZ's own per-player market detail — the same data shown on that card's own page) and stores `current_value`, `range_low`/`range_high`, `buy_now_price`, and `sell_now_price` alongside the plain price snapshot (identified by a single human-readable `date` string). This gives real bid/ask prices and RenderZ's own independently-computed trend, refreshed on a faster cadence than our own polling.
- `range_low`/`range_high` are **not** a historical trading range despite the name — measured empirically across the real dataset at ~3-5% wide (avg ~4%) around `current_value`, moving in lockstep with it. It's RenderZ's live "normal fluctuation" band for the current fair-value estimate, not a multi-day price history.
- `buy_now_price` (and `sell_now_price`) can be explicitly `0`, which means something specific: RenderZ reports **no active listing at all** right now (measured at 57.5% of all polls for `buy_now_price`, 64.5% for `sell_now_price`) — not "no data." The strategy treats an explicit `0` differently from a missing/unavailable field (see [Trading Strategy](#-trading-strategy)).
- A separate `long_term_summary` array holds one daily rollup (`date`, `min_value`, `max_value`, `avg_value`, `samples`) per calendar day, capped at `long_term_summary_days` (default 45, ~1.5 months) — this survives the 10-point rolling window's ~2.5-day cap, so a genuine multi-week discount isn't invisible to the strategy just because the fine-grained window is short. Builds up from whenever this feature was added; takes `min_long_term_days_for_baseline` (default 5) days before it starts influencing decisions.

## 📈 Trading Strategy

All numeric trading decisions are made deterministically in Python (`find_reversion_candidates` / `analyze_price_series` in `market_analyzer.py`), not by the LLM — an LLM asked to eyeball a raw price array and invent buy/sell numbers has no real grounding in the data. The LLM's role is reduced to one final qualitative red-flag review of already-computed candidates, in exactly **one batched call per cycle** (never one call per candidate, and never skipped — see "Weak-signal fallback" below).

The trend itself is measured on RenderZ's per-player `current_value` (falling back to the coarser bulk-search `price` for ALL points only when there isn't enough `current_value` coverage to use at all — the two are never mixed within a single series, since they're on different scales and empirically diverge 30-60% from each other; mixing them mid-series can fabricate a "bounce" out of a data-source switch rather than a real move).

The "current" observation (the latest poll) is evaluated AGAINST the historical window, not as part of it — `baseline`/`trough`/`volatility` are computed from the prior points only, excluding the current one. Computing them from all points including the current one is self-referential: verified empirically that with the current point folded into `baseline`, **100% of real confirmed bounces had negative expected profit**, because a rising series' latest point sits close to or above the median of that same series almost by construction.

`baseline` uses whichever is more favorable (higher) of the ~2.5-day short-term median or the ~1-1.5 month `long_term_summary` median — the 10-point rolling window alone can't see a genuine multi-week discount that's already started a small recovery; if the long-term typical price is meaningfully higher than the short window shows, that's real evidence of additional upside, not noise. (If the long-term baseline is lower — a card trending up over the longer run — nothing changes, since the short-term baseline is already the more relevant recent reference.) Verified with a synthetic case: a series with only a 4.2% short-term discount and negative expected profit became a 34.3% discount with +160M profit once a higher long-term baseline was supplied. Candidates using it are flagged `used_long_term_baseline: true` for transparency.

A card only becomes a candidate if **all** of the following hold:
1. **Confirmed bounce, not a falling knife** — the current price must be above the established historical trough; reacting to the very latest downtick alone (the bot's original behavior) risks buying into a still-falling price.
2. **An active listing actually exists to buy from** (`require_active_buy_listing`, default true) — `buy_now_price == 0` means RenderZ reports no active sell listing at all right now (57.5% of polls!), not missing data. Without this check a "buy_price" would be fabricated for a trade that isn't executable.
3. **Statistically meaningful discount** (`min_discount_pct`, default 8%) — the trough must be a real deviation from the card's own historical median, not single-listing noise.
4. **Edge still remains after tax** (`min_remaining_discount_pct`, default `market_tax_rate + 5%` ≈ 15%) — NOT an arbitrary fraction of the discount trigger. Verified empirically: the old floor (half the trigger discount, i.e. 4%) let candidates pass that were mathematically guaranteed unprofitable, since the 10% tax alone exceeds a 4% remaining edge. This floor is tied directly to the tax rate so it can never be looser than breakeven.
5. **Not too erratic** (`max_volatility_cv`, default 0.35) — a wildly swinging single-listing snapshot is more likely an unreliable listing than a genuine trend.
6. **Clears the profit floor** (`min_profit_after_tax`, default 50M coins) — buy price is the real executable ask (`buy_now_price`); the sell target is our own median `baseline` of the *prior* window (not the latest `current_value`, which empirically sits *below* the executable buy price about twice as often as above it, and not a baseline contaminated by the current point either).
7. **Real instant-sell liquidity exists** (`require_instant_sell_liquidity`, default true) — if RenderZ reports `marketLowestSellPrice = 0`, there's no live buy-side interest right now, meaning you may not be able to exit on demand after buying.
8. **Not paying above current fair value** (`max_position_in_range`, default 0.6) — cross-checked against RenderZ's live `lowPrice`/`highPrice` fair-value band (a narrow ~4%-wide band around `current_value`, not a historical range), so a "recovery" our sparse history sees isn't actually a purchase at a premium over current fair value.
9. **RenderZ's own trend doesn't contradict the recovery** (`require_value_change_confirmation`, default true) — if RenderZ's latest computed `basePricePercentageChange` is itself negative, that's an independent signal disagreeing with our own detected bounce.
10. **`buy_now_price` and `current_value` roughly agree** (`max_price_value_divergence_pct`, default 8%) — these are two FRESH signals from the same per-player endpoint refresh, empirically found to agree within 5% in 100% of real samples, so a real gap means something's off. (Deliberately NOT compared against the stale bulk-search `price` field — that diverges 30-60% from `current_value` regardless of data quality, since it's cached on a much slower refresh cycle, which would make this gate reject almost everything for no real reason.)

Checks 2, 9, and 10 exist because no single data source or field value is trusted at face value in isolation — requiring independent signals to agree, and treating an explicit `0` as a real signal rather than "no data," is standard risk-management practice, not just a matter of picking "the best" field. Check 4 exists because a percentage-based "edge" threshold that isn't anchored to the actual tax rate can pass mathematically-guaranteed-unprofitable candidates.

This entire strategy was independently re-verified by a separate model (Claude Opus) reviewing the code against the real accumulated dataset, which caught the self-referential baseline issue (point 4 above) and the LLM-shown-wrong-series bug below — both fixed as a result.

Only cards passing every check are sent to the LLM, together with the pre-computed buy/sell/profit numbers and the risk flags above, using the **same price series the stats were computed from** (previously this accidentally sent the stale `price` field instead, so the LLM's shape sanity-check was being done against numbers unrelated to what it was reviewing) — asking it to reject anything that still looks unreliable (e.g. a discount traced to one anomalous data point) and to phrase results as favorable, asymmetric-risk opportunities rather than certainties.

### Weak-Signal Fallback
The LLM is called **every 6-hour cycle, never skipped** — a design requirement, not an incidental behavior. If zero candidates clear every check above (common when the market is quiet, especially early in a deployment), `rank_fallback_candidates` picks the `fallback_top_n` (default 10) players ranked purely by computed `expected_profit_after_tax`, with none of the hard gates enforced — these can have negative expected profit, no confirmed bounce, or no active listing at all.

This fallback batch uses a **different LLM prompt** (`build_fallback_analysis_prompt`) that explicitly tells the LLM these are NOT pre-vetted and includes the gate-pass/fail flags (`has_confirmed_bounce`, `has_active_buy_listing`, etc.) as things to actually check rather than guaranteed context — with instructions to default to rejecting, since this batch exists specifically because nothing cleared the normal bar. `--status` and the log both report whether a given cycle used the fallback (`used_fallback_candidates_last_cycle`), so a fallback approval is never confused with a fully-vetted one.

Only cards passing every check are sent to the LLM, together with the pre-computed buy/sell/profit numbers and the risk flags above — asking it to reject anything that still looks unreliable (e.g. a discount traced to one anomalous data point) and to phrase results as favorable, asymmetric-risk opportunities rather than certainties.
