import os
import sys
import json
import time
import argparse
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Adjust sys.path to import renderz_api from scripts
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))
from scripts.renderz_api import search_players

def load_config(config_path):
    with open(config_path, "r") as f:
        return json.load(f)

def load_history(history_path):
    if os.path.exists(history_path):
        with open(history_path, "r") as f:
            return json.load(f)
    return {}

def save_history(history_path, history):
    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)

def analyze_player_profitability(player_name, history_prices, api_key):
    """Query Gemini 2.5 Flash to evaluate if a player is a profitable market investment."""
    client = genai.Client(api_key=api_key)
    prompt = f"""
You are an expert FC Mobile market trader with a strict, no-loss business mindset.
Your ONLY job is to identify players that are GUARANTEED profitable to invest in.
If there is ANY doubt, risk, or insufficient trend data, you MUST output NO.

Player Name: {player_name}

Historical Price Data:
{json.dumps(history_prices, indent=2)}

Rules:
- EA FC Mobile charges a 10% market tax on ALL sales. Net received = sell_price * 0.90.
- A trade is ONLY profitable if: (sell_price * 0.90) > buy_price.
- Look for: clear upward price recovery trends, or structural buy-low/sell-high arbitrage.
- If prices are flat, declining, or too volatile — output NO.
- If there are fewer than 3 data points or no clear trend — output NO.

OUTPUT FORMAT (strict):
If profitable: first line must be exactly "YES", then:
---
Target Player: [Name] ([OVR] OVR)
Buy Price Target: [e.g. 35.0M]
Sell Price Target: [e.g. 45.0M]
Expected Profit After Tax: [e.g. +5.5M coins]
Confidence: [High | Very High]
Reasoning: [1-2 sentences on the trend/arbitrage rationale]
---

If NOT profitable: first line must be exactly "NO".
Output nothing else.
"""
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return response.text
    except Exception as e:
        print(f"Error querying LLM: {e}")
        return "NO\nError connecting to LLM."

def format_price(price_coins):
    if price_coins >= 1_000_000_000:
        return f"{price_coins/1e9:.3f}B"
    elif price_coins >= 1_000_000:
        return f"{price_coins/1e6:.1f}M"
    elif price_coins >= 1_000:
        return f"{price_coins/1e3:.1f}K"
    return str(price_coins)

def run_analyzer(test_run=False):
    # Load environment variables from .env file
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    
    config_path = Path(__file__).parent / "config.json"
    config = load_config(config_path)
    filters = config.get("filters", {})
    history_file = Path(__file__).parent / config.get("history_file", "price_history.json")
    output_file = Path(__file__).parent / config.get("output_file", "profitable_investments.txt")
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not found in .env file or system. Exiting.")
        return
        
    MIN_HISTORY_POINTS = 3
    
    def get_rank0_price(player: dict) -> int:
        """Extract the rank-0 basePrice from a player's priceData."""
        pd = player.get("priceData", {})
        return pd.get("0", {}).get("basePrice", 0) if pd else 0

    def fetch_players(filters: dict) -> list:
        """
        Fetch players from RenderZ with smart pagination and server-side filtering.

        Key behaviours:
          - 'programs' list is sent as 'programFilters' in the POST body, which the
            server honours natively (discovered from the website URL). No need to loop
            per-program — one request covers all programs at once.
          - 'min_price' / 'max_price': applied client-side with early-stop pagination.
            When sorted ASC by price, pagination stops the moment all players on a page
            exceed max_price, avoiding scanning thousands of irrelevant pages.
          - 'position': stripped if null.
        """
        programs  = filters.pop("programs",  None)
        position  = filters.pop("position",  None)
        min_price = filters.pop("min_price", None)
        max_price = filters.pop("max_price", None)
        min_rating = filters.get("min_rating")
        max_rating = filters.get("max_rating")

        seen_ids: dict = {}
        page = 1

        while True:
            result = search_players(
                **filters,
                programs=programs,
                position=position,
                page=page,
            )
            players_page = result.get("players", [])
            page_data    = result.get("pageData", {})
            total_pages  = page_data.get("pageCount", 1)

            if not players_page:
                break

            auctionable_only = filters.get("auctionable_only", True)

            for p in players_page:
                price = get_rank0_price(p)
                ovr = p.get("rating", 0)
                is_auctionable = p.get("auctionable", False)

                # Client-side Auctionable filter
                if auctionable_only and not is_auctionable:
                    continue

                # Client-side OVR filter (RenderZ backend ignores the ratings payload)
                if min_rating is not None and ovr < min_rating:
                    continue
                if max_rating is not None and ovr > max_rating:
                    continue

                # Skip unlisted (price=0)
                if price == 0:
                    continue

                # Client-side Price filter
                if min_price is not None and price < min_price:
                    continue
                if max_price is not None and price > max_price:
                    continue

                pid = str(p.get("id"))
                if pid not in seen_ids:
                    seen_ids[pid] = p

            if page >= total_pages:
                break

            page += 1
            time.sleep(0.4)  # be polite between paginated calls

        return list(seen_ids.values())
        
    while True:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Starting market analysis...")
        try:
            # Fetch players - pass a copy so pop() doesn't mutate the original config
            players = fetch_players(dict(filters))
            print(f"Found {len(players)} players matching criteria.")
            
            history = load_history(history_file)
            current_time = time.time()
            
            # Update or create history entries for the fetched players
            for p in players:
                pid = str(p.get("id"))
                name = p.get("cardName", p.get("commonName", "Unknown"))
                ovr = p.get("rating", 0)
                position = p.get("position", "Unknown")
                total_stats = p.get("totalStats", 0)
                foot = p.get("footString", "")
                
                if pid not in history:
                    history[pid] = {
                        "name": name,
                        "ovr": ovr,
                        "position": position,
                        "total_stats": total_stats,
                        "foot": foot,
                        "prices": []
                    }
                
                # We save the basePrice for rank 0
                rank0_price = get_rank0_price(p)
                    
                history[pid]["prices"].append({
                    "timestamp": current_time,
                    "date": time.strftime('%Y-%m-%d %H:%M:%S'),
                    "price": rank0_price
                })
                
                # Keep only last 10 entries to avoid bloating
                history[pid]["prices"] = history[pid]["prices"][-10:]
                
                # We only analyze if we have enough historical data points
                if len(history[pid]["prices"]) < MIN_HISTORY_POINTS:
                    print(f"Skipping {name} ({ovr}) - gathering history ({len(history[pid]['prices'])}/{MIN_HISTORY_POINTS})...")
                    continue
                
                # Analyze using LLM
                print(f"Analyzing {name} ({ovr}) with {len(history[pid]['prices'])} historical data points...")
                analysis = analyze_player_profitability(name, history[pid]["prices"], api_key)
                
                if analysis.strip().upper().startswith("YES"):
                    print(f"*** PROFITABLE INVESTMENT FOUND: {name} ***")
                    
                    # Remove the "YES" line from the analysis text
                    analysis_text = "\n".join(analysis.split("\n")[1:]).strip()
                    
                    with open(output_file, "a") as f:
                        f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] MARKET OPPORTUNITY DETECTED\n")
                        f.write(analysis_text + "\n")
                        f.write("=" * 60 + "\n")
                        
            # Save history
            save_history(history_file, history)
            
        except Exception as e:
            print(f"Error during execution: {e}")
            
        if test_run:
            print("Test run completed.")
            break
            
        # Wait for the next interval
        interval_hours = config.get("interval_hours", 6)
        print(f"Sleeping for {interval_hours} hours...")
        time.sleep(interval_hours * 3600)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FC Mobile Market Analyzer")
    parser.add_argument("--test-run", action="store_true", help="Run once and exit")
    args = parser.parse_args()
    
    run_analyzer(test_run=args.test_run)

