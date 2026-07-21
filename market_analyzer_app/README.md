# FC Mobile Market Analyzer

An automated, AI-powered trading bot for EA FC Mobile. This tool fetches market data for high-rated players from RenderZ, tracks their price trends locally, and uses Google's Gemini LLM to identify guaranteed profitable investment opportunities (arbitrage) while accounting for the EA 10% market tax.

## 🚀 Quick Start (For Ordinary Users)

### 1. Prerequisites
1. Install [Python 3](https://www.python.org/downloads/).
2. Open your terminal (or Command Prompt on Windows) and install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file in the main project folder (the one containing `requirements.txt`) and add your Google Gemini API key:
   ```env
   GEMINI_API_KEY=your_api_key_here
   ```

### 2. Configuration
You can customize the filters the bot uses by editing `market_analyzer_app/config.json`:
- `min_rating` / `max_rating`: The OVR range to search for (e.g., 106 to 114).
- `min_price` / `max_price`: The budget you want to search within (e.g., 100,000,000 to 1,000,000,000).
- `programs`: The specific event cards to target (e.g., Icons, Heroes).
- `interval_hours`: How long the bot waits between market scans (default: 6 hours).

### 3. How to Run on Windows 11
Windows users can manage the bot with a single interactive file:
- **Start/Stop the Bot:** Inside the `market_analyzer_app` folder, simply double-click `windows_manager.vbs`. It will automatically detect if the bot is running. If it is running, it will ask if you want to stop it. If it isn't, it will ask if you want to start it silently in the background!
- **Auto-Start on Boot:** Press `Win + R`, type `shell:startup`, and drag a shortcut of `windows_manager.vbs` into that folder. Next, right-click the shortcut, go to Properties, and add `"autostart"` to the very end of the Target field (after the quotes). It will now run silently every time you turn on your PC without any popups.

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

*(Note: The bot requires at least 3 historical data points to make an investment decision. It will skip analysis for the first two runs while it gathers history!)*

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
- The bot extracts structural metadata (`position`, `foot`, `totalStats`) into the JSON purely for the user's manual analytical reference.
- To prevent JSON bloat for a script that runs 24/7, the `prices` array acts as a rolling buffer, keeping only the 10 most recent chronological data points.

### LLM Prompt Engineering
When handing off data to the Gemini 2.5 Flash model, the prompt is highly constrained to prevent hallucination:
- The LLM receives **only** the `player_name` and the `prices` array.
- It is blinded to the player's OVR, stats, and position during the analysis phase. This forces the LLM to make decisions strictly based on mathematical arbitrage and price momentum, eliminating the risk of it recommending a card simply because it has "good stats." 
- The 10% EA tax rule is hardcoded into the prompt context.
