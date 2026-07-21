import os
import sys
import json
import time
import argparse
import statistics
import urllib.request
import urllib.error
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types
import anthropic

CLAUDE_MODEL = "claude-sonnet-5"
GEMINI_MODEL = "gemini-2.5-flash"
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "llama3.1"

# Player names (e.g. Ibrahimović, Čech, Vidić) contain characters outside the
# default Windows console codepage (cp1252), which otherwise crashes print()
# mid-cycle and silently skips the rest of that run's analysis.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Adjust sys.path to import renderz_api from scripts
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))
from scripts.renderz_api import search_players, get_player_market

def load_config(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_history(history_path):
    if os.path.exists(history_path) and os.path.getsize(history_path) > 0:
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {}

def save_history(history_path, history):
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

def analyze_price_series(prices, tax_rate):
    """
    Compute mean-reversion stats for one player's price history.

    Deliberately does NOT flag on "latest price < previous price" — a single-listing
    snapshot always jitters a bit, and reacting to the first downtick risks buying into
    a still-falling price (catching a falling knife). Instead this looks for a
    confirmed trough: a low point that price has already started recovering FROM,
    which is the standard "buy the dip after confirmation" pattern in technical trading.

    Returns None if the series can't support a signal (too flat, no confirmed bounce,
    or so erratic that a "trend" isn't distinguishable from noise).
    """
    values = [p["price"] for p in prices if p.get("price", 0) > 0]
    if len(values) < 3:
        return None

    mean = statistics.mean(values)
    if mean <= 0:
        return None

    # Median baseline is robust to a single outlier spike/crash, unlike mean or max.
    baseline = statistics.median(values)
    stdev = statistics.pstdev(values)
    volatility_cv = stdev / mean

    trough_price = min(values)
    trough_idx = values.index(trough_price)
    current_price = values[-1]

    # Require at least one recovery tick since the trough — i.e. the dip has already
    # bottomed out and turned up. Without this, "buy low" just means "buy while falling."
    if trough_idx >= len(values) - 1:
        return None
    if current_price <= trough_price:
        return None

    discount_pct = (baseline - trough_price) / baseline
    remaining_discount_pct = (baseline - current_price) / baseline

    # RenderZ's own per-player market detail (see get_player_market) is richer than our
    # own rolling "cheapest listing" snapshot: it gives the real executable ask/bid and
    # an independently-computed "current value" baseline, refreshed on its own faster
    # cadence. Prefer these when available; fall back to our own history-derived numbers
    # for older entries recorded before this data was captured.
    latest = prices[-1]
    buy_price = latest.get("buy_now_price") or current_price
    sell_price_target = latest.get("current_value") or baseline
    expected_profit_after_tax = sell_price_target * (1 - tax_rate) - buy_price

    sell_now_price = latest.get("sell_now_price")
    # None = we don't have this data point (older entry / fetch failed) -> unknown,
    # don't penalize. 0 = RenderZ explicitly reports no instant-sell liquidity right now.
    has_liquidity_data = sell_now_price is not None
    has_instant_sell_liquidity = (sell_now_price or 0) > 0

    range_low = latest.get("range_low")
    range_high = latest.get("range_high")
    position_in_range = None
    if range_low is not None and range_high is not None and range_high > range_low:
        position_in_range = (buy_price - range_low) / (range_high - range_low)

    return {
        "baseline": baseline,
        "trough_price": trough_price,
        "buy_price": buy_price,
        "sell_price_target": sell_price_target,
        "expected_profit_after_tax": expected_profit_after_tax,
        "discount_pct": discount_pct,
        "remaining_discount_pct": remaining_discount_pct,
        "volatility_cv": volatility_cv,
        "has_liquidity_data": has_liquidity_data,
        "has_instant_sell_liquidity": has_instant_sell_liquidity,
        "position_in_range": position_in_range,
        "value_change_pct": latest.get("value_change_pct"),
    }

def find_reversion_candidates(history, strategy_cfg):
    """
    Deterministically filter history for statistically-supported mean-reversion
    candidates. All numeric decisions (discount size, confirmed bounce, volatility,
    profit) happen here in code — not in the LLM prompt — because an LLM asked to
    eyeball a JSON price array and invent "Buy Price Target: 35.0M" has no grounding
    in the actual numbers. The LLM's job (see build_analysis_prompt) is reduced to a
    qualitative red-flag review of these already-computed candidates.
    """
    min_points = strategy_cfg.get("min_history_points", 4)
    min_discount_pct = strategy_cfg.get("min_discount_pct", 0.08)
    max_volatility_cv = strategy_cfg.get("max_volatility_cv", 0.35)
    min_profit_after_tax = strategy_cfg.get("min_profit_after_tax", 50_000_000)
    tax_rate = strategy_cfg.get("market_tax_rate", 0.10)
    require_instant_sell_liquidity = strategy_cfg.get("require_instant_sell_liquidity", True)
    max_position_in_range = strategy_cfg.get("max_position_in_range", 0.6)

    candidates = {}
    for pid, pdata in history.items():
        prices = pdata.get("prices", [])
        name = pdata.get("name", "Unknown")
        ovr = pdata.get("ovr", 0)

        if len(prices) < min_points:
            print(f"Skipping {name} ({ovr}) - gathering history ({len(prices)}/{min_points})...")
            continue

        stats = analyze_price_series(prices, tax_rate)
        if stats is None:
            continue

        # Discount must be big enough to be a real signal, not single-listing noise.
        if stats["discount_pct"] < min_discount_pct:
            continue

        # Must still have meaningful room left before it's already priced back to
        # baseline — otherwise the edge is gone by the time we'd act on it.
        if stats["remaining_discount_pct"] < min_discount_pct * 0.5:
            continue

        # A single "current price" snapshot that swings wildly between polls is more
        # likely an unreliable/thin listing than a genuine trend — real trend signals
        # get rejected here far less than one-off spikes do.
        if stats["volatility_cv"] > max_volatility_cv:
            continue

        if stats["expected_profit_after_tax"] < min_profit_after_tax:
            continue

        # Don't enter a position you may not be able to exit. RenderZ's per-player
        # market detail reports whether there's currently ANY instant-sell liquidity
        # (marketLowestSellPrice > 0) — if it explicitly reports none, buying now risks
        # having to list-and-wait rather than sell on demand. Only enforced when we
        # actually have this data; unknown (fetch failed / older entry) isn't penalized.
        if (
            require_instant_sell_liquidity
            and stats["has_liquidity_data"]
            and not stats["has_instant_sell_liquidity"]
        ):
            print(f"Skipping {name} ({ovr}) - no instant-sell liquidity right now.")
            continue

        # Cross-check against RenderZ's own recent market range (independent of our own
        # 6-hourly polling): reject if the buy price isn't actually in the cheaper part
        # of its recent range, even if OUR OWN sparse history looked like a "recovery."
        if (
            stats["position_in_range"] is not None
            and stats["position_in_range"] > max_position_in_range
        ):
            print(f"Skipping {name} ({ovr}) - price is in the upper part of its recent market range.")
            continue

        candidates[pid] = {
            "name": name,
            "ovr": ovr,
            "buy_price": round(stats["buy_price"]),
            "sell_price_target": round(stats["sell_price_target"]),
            "expected_profit_after_tax": round(stats["expected_profit_after_tax"]),
            "discount_pct_vs_baseline": round(stats["discount_pct"] * 100, 1),
            "remaining_discount_pct_vs_baseline": round(stats["remaining_discount_pct"] * 100, 1),
            "volatility_cv": round(stats["volatility_cv"], 3),
            "has_instant_sell_liquidity": stats["has_instant_sell_liquidity"] if stats["has_liquidity_data"] else "unknown",
            "position_in_recent_range_pct": (
                round(stats["position_in_range"] * 100, 1) if stats["position_in_range"] is not None else "unknown"
            ),
            "renderz_own_recent_change_pct": stats["value_change_pct"],
            # Bare chronological price trend only (no timestamps/nulls) — the LLM's job
            # is a shape sanity-check against the computed stats above, not re-deriving
            # them, so it doesn't need the full raw records.
            "recent_price_trend": [p["price"] for p in prices if p.get("price", 0) > 0],
        }

    return candidates

def build_analysis_prompt(candidates_data):
    return f"""
You are a risk-review analyst for an FC Mobile market-trading bot.

A separate statistical filter has ALREADY confirmed each candidate below as a
trough-and-recovery pattern (price bottomed out and has since ticked up) with a
computed edge exceeding the minimum profit threshold. buy_price, sell_price_target,
and expected_profit_after_tax were all computed deterministically from price
history — do NOT recalculate, adjust, or invent different numbers.

Your ONLY job is to REJECT candidates whose pattern looks unreliable despite passing
the numeric filter, for example:
- The "discount" traces back to a single anomalous low point surrounded by otherwise
  flat/stable data (looks like a data glitch or one rogue lowball listing, not a real
  market move).
- The recovery is a single fragile uptick that could just as easily be noise.
- The history looks manipulated (implausible round-number jumps, repeating identical
  values, patterns inconsistent with organic trading).
- has_instant_sell_liquidity is false — there is currently no live buy-side interest,
  meaning after buying you may not be able to exit the position on demand.
- renderz_own_recent_change_pct (an independent trend signal from RenderZ's own price
  index, separate from our own history) contradicts the recovery story.

Field notes:
- position_in_recent_range_pct: where buy_price sits within the recent market
  low-high range (0% = at the recent low, 100% = at the recent high). Lower is better.
- has_instant_sell_liquidity: "unknown" means data wasn't available, not that liquidity
  is absent — don't penalize "unknown" the way you would penalize an explicit false.

Candidates (all prices in coins, already net of the required checks):
{json.dumps(candidates_data, indent=2)}

IMPORTANT: No signal derived from a single-listing price snapshot is ever "guaranteed."
Treat approved candidates as statistically favorable, asymmetric-risk opportunities —
not certainties. Do not use the word "guaranteed" in your output.

OUTPUT FORMAT:
For each candidate you approve (do not alter the given numbers), output exactly in
this format separated by "---":
---
Target Player: [Name] ([OVR] OVR)
Buy Price Target: [format the given buy_price, e.g. 35.0M]
Sell Price Target: [format the given sell_price_target, e.g. 45.0M]
Expected Profit After Tax: [format the given expected_profit_after_tax, e.g. +5.5M coins]
Conviction: [Moderate | High] (based on discount size, volatility, and recovery strength)
Reasoning: [1-2 sentences referencing the actual discount_pct_vs_baseline / volatility_cv
given, explaining why this looks like a genuine reversion rather than noise]
---

If none of the candidates hold up to scrutiny, output EXACTLY "NO PROFITABLE INVESTMENTS FOUND".
"""

def query_claude(prompt, api_key):
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text")

def query_gemini(prompt, api_key):
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
    )
    return response.text

def query_ollama(prompt):
    """Local, keyless fallback. Requires Ollama running with OLLAMA_MODEL already pulled."""
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        result = json.loads(r.read().decode("utf-8"))
    return result.get("response", "")

def analyze_players_bulk(players_data):
    """
    Evaluate a batch of players for profitable market investments.
    Provider priority: Claude (ANTHROPIC_API_KEY) -> Gemini (GEMINI_API_KEY) -> local Ollama (no key needed).
    Each tier is only attempted if the previous one is unavailable or fails.
    """
    if not players_data:
        return ""

    prompt = build_analysis_prompt(players_data)

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")

    if anthropic_key:
        try:
            print(f"Querying Claude ({CLAUDE_MODEL}) for analysis...")
            return query_claude(prompt, anthropic_key)
        except Exception as e:
            print(f"Claude query failed ({e}), falling back to Gemini...")

    if gemini_key:
        try:
            print(f"Querying Gemini ({GEMINI_MODEL}) for analysis...")
            return query_gemini(prompt, gemini_key)
        except Exception as e:
            print(f"Gemini query failed ({e}), falling back to local Ollama...")

    try:
        print(f"No cloud API key available - querying local Ollama ({OLLAMA_MODEL})...")
        return query_ollama(prompt)
    except Exception as e:
        print(f"Ollama query failed ({e}). No LLM provider available - skipping analysis.")
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
    strategy_cfg = config.get("strategy", {})
    history_file = Path(__file__).parent / config.get("history_file", "price_history.json")
    output_file = Path(__file__).parent / config.get("output_file", "profitable_investments.txt")

    if os.environ.get("ANTHROPIC_API_KEY"):
        print(f"LLM provider: Claude ({CLAUDE_MODEL}).")
    elif os.environ.get("GEMINI_API_KEY"):
        print(f"LLM provider: Gemini ({GEMINI_MODEL}) — no ANTHROPIC_API_KEY set.")
    else:
        print(f"LLM provider: local Ollama ({OLLAMA_MODEL}) — no ANTHROPIC_API_KEY or GEMINI_API_KEY set.")

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

            # Update or create history entries for the fetched players
            for p in players:
                pid = str(p.get("id"))
                name = p.get("cardName", p.get("commonName", "Unknown"))
                ovr = p.get("rating", 0)
                position = p.get("position", "Unknown")

                if pid not in history:
                    history[pid] = {
                        "name": name,
                        "ovr": ovr,
                        "position": position,
                        "prices": []
                    }

                # We save the basePrice for rank 0
                rank0_price = get_rank0_price(p)

                price_point = {
                    "date": time.strftime('%Y-%m-%d %H:%M:%S'),
                    "price": rank0_price
                }

                # Enrich with RenderZ's per-player market detail (current value/trend,
                # market range, real buy/sell prices) — see get_player_market docstring.
                # A failure here just means this poll's entry lacks the richer fields;
                # it must never abort the whole cycle over one flaky request.
                market_detail = get_player_market(p.get("id"))
                if market_detail:
                    price_point.update({
                        "current_value": market_detail.get("basePrice"),
                        "value_change_pct": market_detail.get("basePricePercentageChange"),
                        "range_low": market_detail.get("lowPrice"),
                        "range_high": market_detail.get("highPrice"),
                        "buy_now_price": market_detail.get("marketLowestBuyPrice"),
                        "sell_now_price": market_detail.get("marketLowestSellPrice"),
                    })
                time.sleep(0.4)  # be polite between per-player calls, same cadence as pagination

                history[pid]["prices"].append(price_point)

                # Keep only last 10 entries to avoid bloating
                history[pid]["prices"] = history[pid]["prices"][-10:]

            # Save history right after updating it
            save_history(history_file, history)

            # Deterministic mean-reversion filter (see find_reversion_candidates) —
            # replaces the old "did the last price tick down" precheck.
            candidates = find_reversion_candidates(history, strategy_cfg)

            if candidates:
                print(f"Found {len(candidates)} statistically-supported reversion candidates.")
                print(f"Sending batch to LLM for qualitative red-flag review...")

                # Exactly one LLM call per cycle, no matter how many candidates —
                # all pre-computed numbers already exist, so this is a single batched
                # review call, never a per-candidate loop.
                analysis = analyze_players_bulk(list(candidates.values()))

                if analysis and "NO PROFITABLE INVESTMENTS FOUND" not in analysis.upper():
                    print(f"*** PROFITABLE INVESTMENTS FOUND! ***")
                    with open(output_file, "a", encoding="utf-8") as f:
                        f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] BULK MARKET OPPORTUNITY DETECTED\n")
                        f.write(analysis.strip() + "\n")
                        f.write("=" * 60 + "\n")
                else:
                    print("LLM rejected all candidates in this batch.")
            else:
                print("No statistically-supported reversion candidates this cycle. Skipping LLM analysis.")
            
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

