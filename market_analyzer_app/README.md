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

*(Note: The bot requires at least `min_history_points` (default 4) historical data points per card before it can evaluate a trend. It will skip newly-discovered cards until enough history accumulates.)*

---

## ⚙️ Technical Details (For Advanced Users)

### Overcoming RenderZ API Limitations
The RenderZ backend (`/api/players/filter`) is remarkably limited. It completely ignores payload filters for OVR (`ratings`), `price`, and `auctionable`. If requested, it simply dumps the entire database of players matching the `programFilters` (e.g., all 2,800+ Icons/Heroes). 

To solve this, `market_analyzer.py` utilizes a **hybrid filtering approach**:
1. **Server-Side Program Filtering:** Reduces the payload from 58,000 total players down to ~2,800.
2. **Client-Side Enforced Strict Filtering:** The script aggressively filters out non-auctionable cards, out-of-bounds OVRs, and price mismatches in memory, narrowing the 2,800 results down to the ~130 exact matches instantly.

### Pagination Strategy
Because the server ignores our price/OVR bounds, early-stop pagination is impossible (the API returns players in random/unsorted order regarding price). The script purposefully introduces a `0.4s` polite sleep between paginated API calls to avoid rate-limiting or DDoS-ing the RenderZ API while it fetches all 142 pages of the subset.

### Historical Data Tracking
Player market data is persisted in `price_history.json`.
- To prevent JSON bloat for a script that runs 24/7, the `prices` array acts as a rolling buffer, keeping only the 10 most recent chronological data points.
- Each poll also fetches `GET /api/player/market/{id}` (RenderZ's own per-player market detail — the same data shown on that card's own page) and stores `current_value`, `range_low`/`range_high`, `buy_now_price`, and `sell_now_price` alongside the plain price snapshot (identified by a single human-readable `date` string). This gives real bid/ask prices and RenderZ's own independently-computed trend, refreshed on a faster cadence than our own polling.

## 📈 Trading Strategy

All numeric trading decisions are made deterministically in Python (`find_reversion_candidates` / `analyze_price_series` in `market_analyzer.py`), not by the LLM — an LLM asked to eyeball a raw price array and invent buy/sell numbers has no real grounding in the data. The LLM's role is reduced to one final qualitative red-flag review of already-computed candidates, in exactly **one batched call per cycle** (never one call per candidate).

A card only becomes a candidate if **all** of the following hold:
1. **Confirmed bounce, not a falling knife** — the price must have hit a trough and already ticked up since; reacting to the very latest downtick alone (the bot's original behavior) risks buying into a still-falling price.
2. **Statistically meaningful discount** (`min_discount_pct`, default 8%) — the trough must be a real deviation from the card's own median price, not single-listing noise.
3. **Edge still remains** (`remaining_discount_pct` >= half the discount threshold) — reject cards that have already reverted most of the way back to baseline by the time we'd act.
4. **Not too erratic** (`max_volatility_cv`, default 0.35) — a wildly swinging single-listing snapshot is more likely an unreliable listing than a genuine trend.
5. **Clears the profit floor** (`min_profit_after_tax`, default 50M coins) — computed from the real executable buy price and RenderZ's own current-value sell target, net of the 10% market tax.
6. **Real instant-sell liquidity exists** (`require_instant_sell_liquidity`, default true) — if RenderZ reports `marketLowestSellPrice = 0`, there's no live buy-side interest right now, meaning you may not be able to exit on demand after buying.
7. **Buying in the cheap part of the recent range** (`max_position_in_range`, default 0.6) — cross-checked against RenderZ's own `lowPrice`/`highPrice` range, independent of our own 6-hourly polling, so a "recovery" our sparse history sees isn't actually a purchase near the top of the card's normal range.

Only cards passing every check are sent to the LLM, together with the pre-computed buy/sell/profit numbers and the risk flags above — asking it to reject anything that still looks unreliable (e.g. a discount traced to one anomalous data point) and to phrase results as favorable, asymmetric-risk opportunities rather than certainties.
