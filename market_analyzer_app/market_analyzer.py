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
    if os.path.exists(history_path) and os.path.getsize(history_path) > 0:
        try:
            with open(history_path, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {}

def save_history(history_path, history):
    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)

def analyze_players_bulk(players_data, api_key):
    """Query Gemini 2.5 Flash to evaluate multiple players at once for profitable market investments."""
    if not players_data:
        return ""
        
    client = genai.Client(api_key=api_key)
    prompt = f"""
You are an expert FC Mobile market trader with a strict, no-loss business mindset.
Your ONLY job is to identify players that are GUARANTEED profitable to invest in from the provided list.
If there is ANY doubt, risk, or insufficient trend data for a player, DO NOT recommend them.

List of players with dropped prices and their historical data:
{json.dumps(players_data, indent=2)}

Rules:
- EA FC Mobile charges a 10% market tax on ALL sales. Net received = sell_price * 0.90.
- A trade is ONLY profitable if: (sell_price * 0.90) > buy_price.
- IMPORTANT: A trade MUST yield an EXPECTED PROFIT of at least 50,000,000 (50M) coins after tax to be considered profitable. If the profit is less than 50M coins, DO NOT recommend the player.
- Look for: clear upward price recovery trends, or structural buy-low/sell-high arbitrage.
- If prices are flat, declining continuously with no bottom, or too volatile — ignore them.
- If there are fewer than 3 data points or no clear trend — ignore them.

OUTPUT FORMAT:
For EACH profitable player you identify, output exactly in this format separated by "---":
---
Target Player: [Name] ([OVR] OVR)
Buy Price Target: [e.g. 35.0M]
Sell Price Target: [e.g. 45.0M]
Expected Profit After Tax: [e.g. +5.5M coins]
Confidence: [High | Very High]
Reasoning: [1-2 sentences on the trend/arbitrage rationale]
---

If NO players are profitable, output EXACTLY "NO PROFITABLE INVESTMENTS FOUND".
"""
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return response.text
    except Exception as e:
        print(f"Error querying LLM: {e}")
        return ""

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
                
            # Save history right after updating it
            save_history(history_file, history)
            
            # Precheck: Find players whose price just dropped
            dropped_players = {}
            for pid, pdata in history.items():
                prices = pdata.get("prices", [])
                name = pdata.get("name", "Unknown")
                ovr = pdata.get("ovr", 0)
                
                if len(prices) < MIN_HISTORY_POINTS:
                    print(f"Skipping {name} ({ovr}) - gathering history ({len(prices)}/{MIN_HISTORY_POINTS})...")
                    continue
                    
                current_price = prices[-1]["price"]
                previous_price = prices[-2]["price"]
                
                if current_price < previous_price:
                    # Price dropped, add to analysis batch
                    dropped_players[pid] = {
                        "name": name,
                        "ovr": ovr,
                        "history_prices": prices
                    }
                    
            if dropped_players:
                print(f"Precheck found {len(dropped_players)} players with recently dropped prices.")
                print(f"Analyzing batch with LLM in a single request...")
                
                analysis = analyze_players_bulk(list(dropped_players.values()), api_key)
                
                if analysis and "NO PROFITABLE INVESTMENTS FOUND" not in analysis.upper():
                    print(f"*** PROFITABLE INVESTMENTS FOUND! ***")
                    with open(output_file, "a") as f:
                        f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] BULK MARKET OPPORTUNITY DETECTED\n")
                        f.write(analysis.strip() + "\n")
                        f.write("=" * 60 + "\n")
                else:
                    print("LLM found no guaranteed profitable investments in this batch.")
            else:
                print("No players had price drops in this cycle. Skipping LLM analysis.")
            
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

