import os
import sys
import json
import time
import logging
import argparse
import statistics
import urllib.request
import urllib.error
from pathlib import Path
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
from google import genai
from google.genai import types
import anthropic

CLAUDE_MODEL = "claude-sonnet-5"
GEMINI_MODEL = "gemini-2.5-flash"
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "llama3.1"
LOG_FILE_DEFAULT = "market_analyzer.log"
STATUS_FILE_DEFAULT = "status.json"

# Player names (e.g. Ibrahimović, Čech, Vidić) contain characters outside the
# default Windows console codepage (cp1252), which otherwise crashes print()
# mid-cycle and silently skips the rest of that run's analysis. Guarded because
# sys.stdout/stderr can be None if ever launched fully detached with no stdio
# at all (not how windows_manager.pyw launches it today, but cheap to guard).
if sys.stdout is not None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr is not None:
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Adjust sys.path to import renderz_api from scripts
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))
from scripts.renderz_api import search_players, get_player_market, MAX_PAGE_SIZE

logger = logging.getLogger("market_analyzer")


def setup_logging(log_path):
    """
    Writes to a rotating log file so the bot's activity is inspectable regardless
    of how it was launched — e.g. windows_manager.pyw redirects stdout to DEVNULL,
    so without a file handler there would be no way to see what a running instance
    is doing short of manually inspecting price_history.json.
    """
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    file_handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    if sys.stdout is not None:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(fmt)
        logger.addHandler(stream_handler)


def write_status(status_path, **fields):
    """Merge-update a small JSON status snapshot — read by `--status`."""
    status = {}
    if os.path.exists(status_path):
        try:
            with open(status_path, "r", encoding="utf-8") as f:
                status = json.load(f)
        except (json.JSONDecodeError, OSError):
            status = {}
    status.update(fields)
    status["updated_at"] = time.strftime('%Y-%m-%d %H:%M:%S')
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2)

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

def update_long_term_summary(pdata, price_point, max_days):
    """
    Roll the current poll into a daily summary entry (one row per calendar day), so
    long-term price context (up to ~1.5 months by default) survives the short-term
    rolling window's 10-point (~2.5 day) cap without storing every raw 6-hourly point
    forever. Mutates pdata in place.
    """
    value = price_point.get("current_value") or price_point.get("price", 0)
    if value <= 0:
        return

    day = price_point["date"][:10]  # "YYYY-MM-DD" prefix of "YYYY-MM-DD HH:MM:SS"
    summary = pdata.setdefault("long_term_summary", [])

    if summary and summary[-1]["date"] == day:
        entry = summary[-1]
        entry["min_value"] = min(entry["min_value"], value)
        entry["max_value"] = max(entry["max_value"], value)
        entry["samples"] += 1
        entry["avg_value"] += (value - entry["avg_value"]) / entry["samples"]  # running mean
    else:
        summary.append({"date": day, "min_value": value, "max_value": value, "avg_value": value, "samples": 1})

    if len(summary) > max_days:
        del summary[:-max_days]

def get_long_term_baseline(pdata, min_days=5):
    """
    Median of daily average values from long_term_summary — a genuine ~1-1.5 month
    typical-price reference, independent of the fine-grained ~2.5-day rolling window.
    Returns None until enough days have accumulated to trust it (min_days).
    """
    summary = pdata.get("long_term_summary", [])
    avg_values = [d["avg_value"] for d in summary if d.get("avg_value", 0) > 0]
    if len(avg_values) < min_days:
        return None
    baseline = statistics.median(avg_values)
    return baseline if baseline > 0 else None

def get_trend_series(prices):
    """
    Build the price series used for trend detection. current_value (RenderZ's per-player
    market detail) refreshes far more often than the bulk list endpoint's cached "price"
    snapshot — empirically observed cases where price stayed bit-for-bit identical across
    5+ polls while current_value moved every time. Using the stale field made the trend
    detector blind to real movement for most tracked cards.

    Deliberately does NOT mix the two fields within a single series (e.g. current_value
    for most points, price for one gap) — the two are on different scales (current_value
    is RenderZ's smoothed fair-value estimate; price is a cached cheapest-listing snapshot
    from a different endpoint), and empirically diverge 30-60% from each other. Switching
    scales mid-series can fabricate a "bounce" out of a data-source switch rather than a
    real move. Only fall back to "price" for ALL points when current_value coverage is
    too sparse to use at all (e.g. older entries recorded before enrichment existed).
    """
    value_points = [p.get("current_value") for p in prices if p.get("current_value", 0) > 0]
    if len(value_points) < 3:
        value_points = [p.get("price", 0) for p in prices if p.get("price", 0) > 0]
    return value_points

def analyze_price_series(prices, tax_rate, long_term_baseline=None):
    """
    Compute mean-reversion stats for one player's price history.

    Deliberately does NOT flag on "latest price < previous price" — a single-listing
    snapshot always jitters a bit, and reacting to the first downtick risks buying into
    a still-falling price (catching a falling knife). Instead this looks for a
    confirmed trough: a low point that price has already started recovering FROM,
    which is the standard "buy the dip after confirmation" pattern in technical trading.

    long_term_baseline (from get_long_term_baseline, ~1-1.5 months of daily rollups) lets
    this see genuine longer-term discounts the ~2.5-day rolling window can't: if a card's
    true typical price over the past month is meaningfully higher than what our narrow
    window shows, that's real evidence of upside the short window would otherwise miss
    entirely — not just noise.

    Returns None if the series can't support a signal (too flat, no confirmed bounce,
    or so erratic that a "trend" isn't distinguishable from noise).
    """
    values = get_trend_series(prices)
    if len(values) < 3:
        return None

    # The "current" observation is evaluated AGAINST the historical window, not as part
    # of it — computing baseline/trough/volatility from all points INCLUDING the current
    # one is self-referential (the point you're testing contaminates its own reference).
    # Verified empirically: with baseline including the current point, remaining_discount_pct
    # was negative for 100% of confirmed bounces in the real dataset, since a rising
    # series' latest point is close to or above the median of that same series almost by
    # construction.
    current_price = values[-1]
    prior_values = values[:-1]
    if len(prior_values) < 2:
        return None

    mean = statistics.mean(prior_values)
    if mean <= 0:
        return None

    # Median baseline is robust to a single outlier spike/crash, unlike mean or max.
    short_term_baseline = statistics.median(prior_values)
    stdev = statistics.pstdev(prior_values)
    volatility_cv = stdev / mean

    # Use whichever baseline is more favorable (higher) as the reversion target. If the
    # card's true ~1-1.5 month typical price is higher than what our narrow ~2.5-day
    # window shows, that's real, statistically-grounded evidence of additional upside —
    # not something to ignore just because the short window can't see it. If the
    # long-term baseline is LOWER (card trending up over the longer run), the short-term
    # baseline already reflects the more relevant recent norm, so nothing changes.
    baseline = short_term_baseline
    used_long_term_baseline = False
    if long_term_baseline is not None and long_term_baseline > short_term_baseline:
        baseline = long_term_baseline
        used_long_term_baseline = True

    trough_price = min(prior_values)

    # Whether the current observation is a genuine recovery tick above the established
    # historical low, or still at/below it ("buy low" would just mean "buy while
    # falling"). This is a soft flag, not a hard reject here, so a fallback ranker can
    # still rank/compare cards even when none show a confirmed bounce this cycle —
    # find_reversion_candidates enforces it as a hard gate.
    has_confirmed_bounce = current_price > trough_price

    discount_pct = (baseline - trough_price) / baseline
    remaining_discount_pct = (baseline - current_price) / baseline

    # RenderZ's own per-player market detail (see get_player_market) gives the real
    # executable ask/bid and an independently-computed "current value" baseline,
    # refreshed on its own faster cadence than our own polling.
    latest = prices[-1]
    # buy_now_price == 0 is NOT "missing data" — it's RenderZ explicitly reporting no
    # active sell listing at all (observed in 57.5% of enriched points!). Treating that
    # as "fall back to current_price" would fabricate a buy price for a trade that isn't
    # actually executable right now. None (field truly absent/fetch failed) is the only
    # case that should fall back.
    buy_now_price = latest.get("buy_now_price")
    has_buy_price_data = buy_now_price is not None
    has_active_buy_listing = (buy_now_price or 0) > 0
    buy_price = buy_now_price if has_active_buy_listing else current_price
    # NOT latest current_value: empirically it sits below the actual executable buy
    # price about twice as often as above it (RenderZ's smoothed "fair value" lags or
    # discounts vs. the live ask) — using it as a sell target made expected profit
    # negative by construction most of the time. baseline (median of the short-term
    # window, or the long-term daily-rollup median if that's higher) is a genuine
    # reversion-to-typical-price target instead.
    sell_price_target = baseline
    expected_profit_after_tax = sell_price_target * (1 - tax_rate) - buy_price

    # Cross-validation #1: RenderZ's own latest computed delta (independent of our trend
    # detection above) shouldn't itself be a fresh downturn — if their most recent read
    # disagrees with the recovery we think we're seeing, don't trust a single source.
    value_change_pct = latest.get("value_change_pct")
    contradicts_recovery = value_change_pct is not None and value_change_pct < 0

    # Cross-validation #2: buy_now_price (the real ask) and current_value (RenderZ's fair-
    # value estimate) are two FRESH signals from the same per-player endpoint refresh, and
    # empirically agree closely (100% within 5% in real samples) — so a real gap between
    # them means something's off (stale enrichment, listing just changed, etc). The bulk
    # "price" field is deliberately NOT used for this check: it's a known-stale cache from
    # a different endpoint that diverges from current_value 30-60% typically, regardless
    # of data quality, so comparing it here would reject almost everything for no reason.
    latest_current_value = latest.get("current_value")
    price_value_divergence_pct = None
    if has_active_buy_listing and latest_current_value:
        price_value_divergence_pct = abs(buy_now_price - latest_current_value) / latest_current_value

    sell_now_price = latest.get("sell_now_price")
    # None = we don't have this data point (older entry / fetch failed) -> unknown,
    # don't penalize. 0 = RenderZ explicitly reports no instant-sell liquidity right now.
    has_liquidity_data = sell_now_price is not None
    has_instant_sell_liquidity = (sell_now_price or 0) > 0

    # range_low/range_high are NOT a historical trading range despite the name — measured
    # empirically at ~3-5% wide (avg ~4%) around current_value, moving in lockstep with
    # it. This is RenderZ's live "normal fluctuation" band for the current fair-value
    # estimate, refreshed alongside current_value itself — not a multi-day price history.
    # Used here as a sanity check against overpaying relative to current fair value, not
    # as a "cheap vs. its recent trading history" signal (discount_pct/remaining_discount_pct,
    # from our OWN multi-poll history, already cover that).
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
        "has_buy_price_data": has_buy_price_data,
        "has_active_buy_listing": has_active_buy_listing,
        "has_liquidity_data": has_liquidity_data,
        "has_instant_sell_liquidity": has_instant_sell_liquidity,
        "position_in_range": position_in_range,
        "value_change_pct": value_change_pct,
        "contradicts_recovery": contradicts_recovery,
        "price_value_divergence_pct": price_value_divergence_pct,
        "has_confirmed_bounce": has_confirmed_bounce,
        "short_term_baseline": short_term_baseline,
        "long_term_baseline": long_term_baseline,
        "used_long_term_baseline": used_long_term_baseline,
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
    require_value_change_confirmation = strategy_cfg.get("require_value_change_confirmation", True)
    max_price_value_divergence_pct = strategy_cfg.get("max_price_value_divergence_pct", 0.08)
    require_active_buy_listing = strategy_cfg.get("require_active_buy_listing", True)
    min_long_term_days = strategy_cfg.get("min_long_term_days_for_baseline", 5)
    # Must clear the market tax with real room to spare — NOT an arbitrary fraction of the
    # initial discount trigger. Verified empirically: with the old "half the trigger
    # discount" floor (4% against an 8% trigger), 100% of real confirmed bounces had
    # negative expected profit, because a candidate could pass with only 4% of edge left
    # while the tax alone takes 10%. Defaults to tax_rate + a 5% margin.
    min_remaining_discount_pct = strategy_cfg.get("min_remaining_discount_pct", tax_rate + 0.05)

    candidates = {}
    for pid, pdata in history.items():
        prices = pdata.get("prices", [])
        name = pdata.get("name", "Unknown")
        ovr = pdata.get("ovr", 0)

        if len(prices) < min_points:
            logger.debug(f"Skipping {name} ({ovr}) - gathering history ({len(prices)}/{min_points})...")
            continue

        long_term_baseline = get_long_term_baseline(pdata, min_days=min_long_term_days)
        stats = analyze_price_series(prices, tax_rate, long_term_baseline=long_term_baseline)
        if stats is None:
            continue

        # Not a falling knife: the current price must be a genuine recovery tick above
        # the established historical trough, not still at or below it.
        if not stats["has_confirmed_bounce"]:
            continue

        # buy_now_price == 0 means RenderZ explicitly reports no active sell listing at
        # all right now (observed in 57.5% of all polls) — there is literally nothing to
        # buy, so any "buy_price" computed for this candidate is fabricated, not
        # executable. Only enforced when we actually know (None = fetch failed/older
        # entry, don't penalize).
        if (
            require_active_buy_listing
            and stats["has_buy_price_data"]
            and not stats["has_active_buy_listing"]
        ):
            logger.info(f"Skipping {name} ({ovr}) - no active sell listing to buy from right now.")
            continue

        # Discount must be big enough to be a real signal, not single-listing noise.
        if stats["discount_pct"] < min_discount_pct:
            continue

        # Must still have meaningful room left before it's already priced back to
        # baseline — otherwise the edge is gone by the time we'd act on it, and
        # mathematically cannot survive the market tax.
        if stats["remaining_discount_pct"] < min_remaining_discount_pct:
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
            logger.info(f"Skipping {name} ({ovr}) - no instant-sell liquidity right now.")
            continue

        # range_low/range_high is RenderZ's live ~3-5%-wide "normal fluctuation" band
        # around current_value (empirically measured — NOT a historical trading range
        # despite the field names). This rejects paying meaningfully above the current
        # fair-value estimate, even if OUR OWN sparse history looked like a "recovery."
        if (
            stats["position_in_range"] is not None
            and stats["position_in_range"] > max_position_in_range
        ):
            logger.info(f"Skipping {name} ({ovr}) - price is above RenderZ's current fair-value band.")
            continue

        # Cross-validation: RenderZ's own latest computed delta shouldn't itself be a
        # fresh downturn contradicting the recovery we think we detected.
        if require_value_change_confirmation and stats["contradicts_recovery"]:
            logger.info(f"Skipping {name} ({ovr}) - RenderZ's own latest computed change contradicts the recovery.")
            continue

        # Cross-validation: the real ask (buy_now_price) and RenderZ's computed
        # current_value shouldn't diverge too much — a big gap between these two FRESH
        # signals means something's off (stale enrichment, listing just changed, etc).
        if (
            stats["price_value_divergence_pct"] is not None
            and stats["price_value_divergence_pct"] > max_price_value_divergence_pct
        ):
            logger.info(
                f"Skipping {name} ({ovr}) - buy price and current_value diverge "
                f"{stats['price_value_divergence_pct']*100:.1f}% (data may be stale/inconsistent)."
            )
            continue

        candidates[pid] = _format_candidate(name, ovr, prices, stats)

    return candidates

def _format_candidate(name, ovr, prices, stats, extra_fields=None):
    """Shared candidate payload builder for both the strict filter and the fallback ranker."""
    candidate = {
        "name": name,
        "ovr": ovr,
        "buy_price": round(stats["buy_price"]),
        "sell_price_target": round(stats["sell_price_target"]),
        "expected_profit_after_tax": round(stats["expected_profit_after_tax"]),
        "discount_pct_vs_baseline": round(stats["discount_pct"] * 100, 1),
        "remaining_discount_pct_vs_baseline": round(stats["remaining_discount_pct"] * 100, 1),
        "volatility_cv": round(stats["volatility_cv"], 3),
        "has_instant_sell_liquidity": stats["has_instant_sell_liquidity"] if stats["has_liquidity_data"] else "unknown",
        "position_in_fair_value_band_pct": (
            round(stats["position_in_range"] * 100, 1) if stats["position_in_range"] is not None else "unknown"
        ),
        "renderz_own_recent_change_pct": stats["value_change_pct"],
        # True when the sell target/discount used the ~1-1.5 month long-term baseline
        # instead of the ~2.5-day short-term one, because it was higher (see
        # get_long_term_baseline) — i.e. this opportunity relies on longer-term context
        # the short window alone wouldn't have shown.
        "used_long_term_baseline": stats["used_long_term_baseline"],
        # Must be the SAME series the stats above were computed from (get_trend_series),
        # not the raw "price" field — otherwise the LLM's shape sanity-check is done
        # against numbers unrelated to the trough/discount/baseline it's reviewing.
        "recent_price_trend": get_trend_series(prices),
    }
    if extra_fields:
        candidate.update(extra_fields)
    return candidate

def rank_fallback_candidates(history, strategy_cfg, top_n=10):
    """
    Used when find_reversion_candidates finds zero candidates this cycle. Business
    requirement: the LLM should be called every 6-hour cycle regardless, so this ranks
    ALL players with enough history by expected_profit_after_tax (the single most
    decision-relevant number) and returns the top N — WITHOUT requiring any of the hard
    gates (confirmed bounce, active listing, liquidity, tax-aware edge, etc) to pass.

    These are explicitly NOT pre-vetted the way find_reversion_candidates' output is —
    build_fallback_analysis_prompt tells the LLM this and includes the gate-status flags
    so it can judge honestly rather than assuming these already cleared a bar they didn't.
    """
    min_points = strategy_cfg.get("min_history_points", 4)
    tax_rate = strategy_cfg.get("market_tax_rate", 0.10)
    min_long_term_days = strategy_cfg.get("min_long_term_days_for_baseline", 5)

    scored = []
    for pid, pdata in history.items():
        prices = pdata.get("prices", [])
        if len(prices) < min_points:
            continue
        long_term_baseline = get_long_term_baseline(pdata, min_days=min_long_term_days)
        stats = analyze_price_series(prices, tax_rate, long_term_baseline=long_term_baseline)
        if stats is None:
            continue
        scored.append((pid, pdata, prices, stats))

    scored.sort(key=lambda x: x[3]["expected_profit_after_tax"], reverse=True)

    fallback = {}
    for pid, pdata, prices, stats in scored[:top_n]:
        fallback[pid] = _format_candidate(
            pdata.get("name", "Unknown"),
            pdata.get("ovr", 0),
            prices,
            stats,
            extra_fields={
                "has_confirmed_bounce": stats["has_confirmed_bounce"],
                "has_active_buy_listing": stats["has_active_buy_listing"] if stats["has_buy_price_data"] else "unknown",
            },
        )
    return fallback

def build_analysis_prompt(candidates_data):
    return f"""
You are a risk-review analyst for an FC Mobile market-trading bot.

A separate statistical filter has ALREADY confirmed each candidate below as a
trough-and-recovery pattern (price bottomed out and has since ticked up) with a
computed edge exceeding the minimum profit threshold. buy_price, sell_price_target,
and expected_profit_after_tax were all computed deterministically from price
history — do NOT recalculate, adjust, or invent different numbers.

Every candidate here has ALREADY passed hard checks for profit floor, real instant-sell
liquidity, an active buy listing, RenderZ's own trend not contradicting the recovery, and
buy-vs-fair-value consistency — do not re-reject on those grounds; they're guaranteed true
for everything you're shown. Your ONLY job is to REJECT candidates whose PATTERN still
looks unreliable despite passing every numeric gate, for example:
- The "discount" traces back to a single anomalous low point surrounded by otherwise
  flat/stable data (looks like a data glitch or one rogue lowball listing, not a real
  market move).
- The recovery is a single fragile uptick that could just as easily be noise.
- The history looks manipulated (implausible round-number jumps, repeating identical
  values, patterns inconsistent with organic trading).

Field notes:
- position_in_fair_value_band_pct: where buy_price sits within RenderZ's current live
  fair-value band (0% = at the band's low end, 100% = at its high end). Lower is better.
  This is a narrow (~4% wide) live band around current value, NOT a historical range.
- has_instant_sell_liquidity / renderz_own_recent_change_pct: shown for context (both
  already passed their respective checks) — "unknown" liquidity means data wasn't
  available, not that liquidity is absent.

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

def build_fallback_analysis_prompt(candidates_data):
    return f"""
You are a risk-review analyst for an FC Mobile market-trading bot, reviewing a WEAK-SIGNAL
cycle.

No candidate this cycle cleared every strict deterministic check (confirmed bounce with
enough remaining discount to survive the 10% market tax, minimum profit floor, guaranteed
buy/sell liquidity, an active listing to buy from, etc). These are simply the players
ranked highest by computed expected_profit_after_tax this cycle — UNLIKE a normal batch,
NONE of them are pre-vetted, and expected_profit_after_tax may be negative.

Field notes (treat these as things to actually check, not guaranteed-true context):
- has_confirmed_bounce: false means there's no real recovery signal at all yet — price is
  still flat or falling. Reject these unless something else makes a compelling case.
- has_active_buy_listing: false means there is currently nothing to actually buy — reject.
  "unknown" means data wasn't available.
- has_instant_sell_liquidity: false means no live buy-side interest right now (may not be
  able to exit after buying) — a real risk factor here, not pre-cleared.
- position_in_fair_value_band_pct: where buy_price sits within RenderZ's live ~4%-wide
  fair-value band (0% = low end, 100% = high end, NOT a historical range). Lower is better.

Your job: identify if ANY of these represent a genuine, worthwhile opportunity despite not
clearing the full bar, or conclude that none do. Default to rejecting — this batch exists
specifically because nothing looked strong enough to pass the normal filter, so the bar for
approval should be at least as high as normal, not lower just because something has to be
picked.

Candidates (all prices in coins — NOT pre-filtered by profitability or liquidity):
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
Conviction: [Low | Moderate] (this is a weak-signal cycle — "High" conviction should not
be used here; if a candidate looks that strong, note the discrepancy in your reasoning)
Reasoning: [1-2 sentences explaining why this specific candidate is worth surfacing despite
not clearing the normal bar, referencing the actual numbers given]
---

If none of the candidates represent a genuine opportunity — which is expected most cycles
in a weak-signal batch — output EXACTLY "NO PROFITABLE INVESTMENTS FOUND".
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

def analyze_players_bulk(players_data, fallback=False):
    """
    Evaluate a batch of players for profitable market investments.
    Provider priority: Claude (ANTHROPIC_API_KEY) -> Gemini (GEMINI_API_KEY) -> local Ollama (no key needed).
    Each tier is only attempted if the previous one is unavailable or fails.

    fallback=True uses build_fallback_analysis_prompt (players_data is the output of
    rank_fallback_candidates, i.e. NOT pre-vetted) instead of build_analysis_prompt.

    Returns (analysis_text, provider_used) so the caller/status file can report
    which provider actually served the request, not just which was preferred.
    """
    if not players_data:
        return "", None

    prompt = build_fallback_analysis_prompt(players_data) if fallback else build_analysis_prompt(players_data)

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")

    if anthropic_key:
        try:
            logger.info(f"Querying Claude ({CLAUDE_MODEL}) for analysis...")
            return query_claude(prompt, anthropic_key), "claude"
        except Exception as e:
            logger.warning(f"Claude query failed ({e}), falling back to Gemini...")

    if gemini_key:
        try:
            logger.info(f"Querying Gemini ({GEMINI_MODEL}) for analysis...")
            return query_gemini(prompt, gemini_key), "gemini"
        except Exception as e:
            logger.warning(f"Gemini query failed ({e}), falling back to local Ollama...")

    try:
        logger.info(f"No cloud API key available - querying local Ollama ({OLLAMA_MODEL})...")
        return query_ollama(prompt), "ollama"
    except Exception as e:
        logger.warning(f"Ollama query failed ({e}). No LLM provider available - skipping analysis.")
        return "", None

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
    log_file = Path(__file__).parent / config.get("log_file", LOG_FILE_DEFAULT)
    status_file = Path(__file__).parent / config.get("status_file", STATUS_FILE_DEFAULT)
    long_term_summary_days = strategy_cfg.get("long_term_summary_days", 45)

    setup_logging(log_file)

    if os.environ.get("ANTHROPIC_API_KEY"):
        logger.info(f"LLM provider: Claude ({CLAUDE_MODEL}).")
    elif os.environ.get("GEMINI_API_KEY"):
        logger.info(f"LLM provider: Gemini ({GEMINI_MODEL}) — no ANTHROPIC_API_KEY set.")
    else:
        logger.info(f"LLM provider: local Ollama ({OLLAMA_MODEL}) — no ANTHROPIC_API_KEY or GEMINI_API_KEY set.")

    def get_rank0_price(player: dict) -> int:
        """Extract the rank-0 basePrice from a player's priceData."""
        pd = player.get("priceData", {})
        return pd.get("0", {}).get("basePrice", 0) if pd else 0

    def fetch_players(filters: dict) -> list:
        """
        Fetch players from RenderZ with pagination and server-side filtering.

        Key behaviours:
          - 'programs' list is sent as a "terms" query on "source.keyword" — the
            correct server-side filter key for the current /api/search endpoint
            (RenderZ migrated from POST /api/players/filter around 2026-09-03).
          - Server-side rating/auctionable filtering is honoured correctly by the
            current endpoint (verified empirically) — unlike the old endpoint, which
            silently ignored these and required full client-side re-filtering. The
            client-side checks below are now a defensive safety net, not a workaround.
          - 'min_price' / 'max_price': still applied client-side — price range isn't
            passed to the query at all, so this remains a filter over every fetched page.
          - 'position': stripped if null.
          - Pagination: no page-count metadata is returned anymore, so a page returning
            fewer than MAX_PAGE_SIZE players signals the last page.
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

            if not players_page:
                break

            auctionable_only = filters.get("auctionable_only", True)

            for p in players_page:
                price = get_rank0_price(p)
                ovr = p.get("rating", 0)
                is_auctionable = p.get("auctionable", False)

                # Defensive client-side Auctionable filter (belt-and-suspenders; the
                # server now honours this correctly, verified empirically).
                if auctionable_only and not is_auctionable:
                    continue

                # Defensive client-side OVR filter (same — server now honours this too).
                if min_rating is not None and ovr < min_rating:
                    continue
                if max_rating is not None and ovr > max_rating:
                    continue

                # Skip unlisted (price=0)
                if price == 0:
                    continue

                # Client-side Price filter (not supported server-side)
                if min_price is not None and price < min_price:
                    continue
                if max_price is not None and price > max_price:
                    continue

                pid = str(p.get("assetId"))
                if pid not in seen_ids:
                    seen_ids[pid] = p

            if len(players_page) < MAX_PAGE_SIZE:
                break

            page += 1
            time.sleep(0.4)  # be polite between paginated calls

        return list(seen_ids.values())
        
    while True:
        cycle_started_at = time.strftime('%Y-%m-%d %H:%M:%S')
        logger.info(f"Starting market analysis...")
        write_status(status_file, state="running", cycle_started_at=cycle_started_at)
        try:
            # Fetch players - pass a copy so pop() doesn't mutate the original config
            players = fetch_players(dict(filters))
            logger.info(f"Found {len(players)} players matching criteria.")

            history = load_history(history_file)

            # Update or create history entries for the fetched players
            for p in players:
                pid = str(p.get("assetId"))
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
                market_detail = get_player_market(p.get("assetId"))
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

                # Daily-rollup long-term summary (~1-1.5 months by default) — survives
                # the short-term window's 10-point cap so genuine multi-week discounts
                # aren't invisible to the strategy just because the raw window is short.
                update_long_term_summary(history[pid], price_point, long_term_summary_days)

            # Save history right after updating it
            save_history(history_file, history)

            # Deterministic mean-reversion filter (see find_reversion_candidates) —
            # replaces the old "did the last price tick down" precheck.
            candidates = find_reversion_candidates(history, strategy_cfg)
            used_fallback = False

            if not candidates:
                # Business requirement: call the LLM every cycle, not only when something
                # fully qualifies. Rank the closest-to-viable players instead — these are
                # explicitly NOT pre-vetted (see build_fallback_analysis_prompt).
                fallback_top_n = strategy_cfg.get("fallback_top_n", 10)
                candidates = rank_fallback_candidates(history, strategy_cfg, top_n=fallback_top_n)
                used_fallback = bool(candidates)
                if used_fallback:
                    logger.info(
                        f"No candidates cleared the strict filter — falling back to the "
                        f"top {len(candidates)} ranked-by-edge players (not pre-vetted)."
                    )

            provider_used = None
            if candidates:
                if not used_fallback:
                    logger.info(f"Found {len(candidates)} statistically-supported reversion candidates.")
                logger.info(f"Sending batch to LLM for qualitative red-flag review...")

                # Exactly one LLM call per cycle, no matter how many candidates —
                # all pre-computed numbers already exist, so this is a single batched
                # review call, never a per-candidate loop.
                analysis, provider_used = analyze_players_bulk(list(candidates.values()), fallback=used_fallback)

                if analysis and "NO PROFITABLE INVESTMENTS FOUND" not in analysis.upper():
                    logger.info(f"*** PROFITABLE INVESTMENTS FOUND! ***")
                    with open(output_file, "a", encoding="utf-8") as f:
                        f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] BULK MARKET OPPORTUNITY DETECTED"
                                f"{' (weak-signal fallback batch)' if used_fallback else ''}\n")
                        f.write(analysis.strip() + "\n")
                        f.write("=" * 60 + "\n")
                else:
                    logger.info("LLM rejected all candidates in this batch.")
            else:
                logger.info("No players with enough history yet this cycle. Skipping LLM analysis.")

            interval_hours = config.get("interval_hours", 6)
            next_cycle_at = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() + interval_hours * 3600))
            write_status(
                status_file,
                state="sleeping",
                cycle_completed_at=time.strftime('%Y-%m-%d %H:%M:%S'),
                next_cycle_at=next_cycle_at,
                players_tracked=len(history),
                players_found_last_cycle=len(players),
                candidates_found_last_cycle=len(candidates),
                used_fallback_candidates_last_cycle=used_fallback,
                llm_provider_used_last_cycle=provider_used,
                last_error=None,
            )

        except Exception as e:
            logger.error(f"Error during execution: {e}", exc_info=True)
            write_status(status_file, state="error", last_error=str(e), error_at=time.strftime('%Y-%m-%d %H:%M:%S'))

        if test_run:
            logger.info("Test run completed.")
            break

        # Wait for the next interval
        interval_hours = config.get("interval_hours", 6)
        logger.info(f"Sleeping for {interval_hours} hours...")
        time.sleep(interval_hours * 3600)

def print_status(config):
    """
    Pure file-read summary of the bot's current state — works identically on
    Windows and Linux, and regardless of whether the bot's own stdout is visible
    (e.g. when launched via windows_manager.pyw, which discards it).
    """
    status_file = Path(__file__).parent / config.get("status_file", STATUS_FILE_DEFAULT)
    history_file = Path(__file__).parent / config.get("history_file", "price_history.json")
    log_file = Path(__file__).parent / config.get("log_file", LOG_FILE_DEFAULT)
    min_points = config.get("strategy", {}).get("min_history_points", 4)

    print("=== Market Analyzer Status ===")

    if status_file.exists():
        with open(status_file, "r", encoding="utf-8") as f:
            status = json.load(f)
        print(f"State: {status.get('state', 'unknown')}")
        print(f"Status last updated: {status.get('updated_at', 'unknown')}")
        for label, key in [
            ("Last cycle started", "cycle_started_at"),
            ("Last cycle completed", "cycle_completed_at"),
            ("Next cycle expected", "next_cycle_at"),
            ("Players found last cycle", "players_found_last_cycle"),
            ("Reversion candidates last cycle", "candidates_found_last_cycle"),
            ("Used weak-signal fallback last cycle", "used_fallback_candidates_last_cycle"),
            ("LLM provider used last cycle", "llm_provider_used_last_cycle"),
        ]:
            if status.get(key) is not None:
                print(f"{label}: {status[key]}")
        if status.get("last_error"):
            print(f"Last error (at {status.get('error_at', '?')}): {status['last_error']}")
    else:
        print("No status file yet — the bot hasn't completed a cycle since this feature was added.")

    history = load_history(history_file)
    print()
    print(f"Players tracked in history: {len(history)}")
    depth_counts = {}
    for p in history.values():
        n = len(p.get("prices", []))
        depth_counts[n] = depth_counts.get(n, 0) + 1
    ready = sum(count for n, count in depth_counts.items() if n >= min_points)
    print(f"History-depth distribution (points -> #players): {dict(sorted(depth_counts.items()))}")
    print(f"Players with enough history to evaluate ({min_points}+ points): {ready}")
    print()
    print(f"Log file: {log_file} (tail this for full activity detail)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FC Mobile Market Analyzer")
    parser.add_argument("--test-run", action="store_true", help="Run once and exit")
    parser.add_argument("--status", action="store_true", help="Print current bot status and exit (safe to run alongside a live instance)")
    args = parser.parse_args()

    if args.status:
        print_status(load_config(Path(__file__).parent / "config.json"))
        sys.exit(0)

    run_analyzer(test_run=args.test_run)

