
# ============================================================
# FC MOBILE 26 - COST-PER-SHARD EFFICIENCY ANALYSIS
# Live market data from RenderZ.app (May 3, 2026)
# Shard rules from mrbelieverhub.com/game-guides/fc-mobile-star-shards-guide
# ============================================================

print("=" * 68)
print("FC MOBILE 26 - COST-PER-SHARD EFFICIENCY ANALYSIS")
print("Market data: RenderZ.app | Rules: mrbelieverhub.com")
print("=" * 68)

# ── SHARD RULES (from mrbelieverhub guide) ──────────────────
# TOTS-only (110+ OVR): any TOTS card 110+ gives shards
# Previous events (TOTY, Icons, etc.): ONLY 113+ OVR gives shards
#
# Shard yields:
#   110-114 OVR (TOTS only)     -> 150 shards
#   115 OVR (prev events only)  -> 300 shards  (from guide: token route = 750 via P2)
#   116 OVR (prev events 113+)  -> 750 shards  (50 Tokens x 15 = 750)
#   117 OVR (prev events 113+)  -> 2250 shards (150 Tokens x 15 = 2250)
#   118 OVR                     -> 3500 shards
#   119 OVR                     -> 5000 shards
#   120 OVR                     -> 10000 shards

# ── MARKET PRICES (confirmed from RenderZ screenshots) ───────
# Format: (player, ovr, price_per_card_coins, shards_yield, eligible)
# "eligible" = can be converted to shards? (TOTS = yes for 110+, prev events = 113+ only)

market_data = [
    # TIER: 110-114 OVR (TOTS cards ONLY eligible)
    # cheapest rank-1 confirmed: ~27.9M-30M
    # base (unranked) versions estimated ~10-20M cheaper (no rank bonus)
    # Using rank-1 prices since those are what's auctionable and confirmed
    {"player": "Lucas Beraldo (112 CB)", "ovr": 112, "price": 27_900_000,
     "shards": 150, "event": "TOTS", "eligible": True, "note": "Rank 1 confirmed RenderZ"},

    {"player": "Ndicka (110 CB)",        "ovr": 110, "price": 28_800_000,
     "shards": 150, "event": "TOTS", "eligible": True, "note": "Rank 1 confirmed RenderZ"},

    {"player": "Hincapie (111 CB)",      "ovr": 111, "price": 30_000_000,
     "shards": 150, "event": "TOTS", "eligible": True, "note": "Rank 1 confirmed RenderZ"},

    {"player": "Kompany (114 CB)",       "ovr": 114, "price": 416_000_000,
     "shards": 150, "event": "TOTS", "eligible": True, "note": "Rank 1 confirmed RenderZ"},

    # TIER: 115 OVR (prev events - eligible via token conversion)
    {"player": "Tillman (115 CAM)",      "ovr": 115, "price": 250_000_000,
     "shards": 300, "event": "PREV", "eligible": True, "note": "Rank 1 confirmed RenderZ"},

    {"player": "Luna (115 LM)",          "ovr": 115, "price": 250_000_000,
     "shards": 300, "event": "PREV", "eligible": True, "note": "Rank 1 confirmed RenderZ"},

    # TIER: 116 OVR (prev events - eligible, gives 750 shards via Phase 2 tokens)
    {"player": "Hackney (116 CDM)",      "ovr": 116, "price": 425_000_000,
     "shards": 750, "event": "PREV", "eligible": True, "note": "Rank 1 confirmed RenderZ"},

    {"player": "Joao Pedro (116 ST)",    "ovr": 116, "price": 425_000_000,
     "shards": 750, "event": "PREV", "eligible": True, "note": "Rank 1 confirmed RenderZ"},

    # TIER: 117 OVR (prev events - eligible, gives 2250 shards via Phase 2 tokens)
    {"player": "Berbatov (117 ST)",      "ovr": 117, "price": 875_000_000,
     "shards": 2250, "event": "PREV", "eligible": True, "note": "Rank 1 confirmed RenderZ"},

    {"player": "David Raya (117 GK)",    "ovr": 117, "price": 911_000_000,
     "shards": 2250, "event": "PREV", "eligible": True, "note": "Rank 1 confirmed RenderZ"},

    {"player": "Vlahovic (117 ST)",      "ovr": 117, "price": 1_150_000_000,
     "shards": 2250, "event": "PREV", "eligible": True, "note": "Rank 1 confirmed RenderZ"},
]

# ── COST-PER-SHARD ANALYSIS ──────────────────────────────────
print("\n📊 COST-PER-SHARD BREAKDOWN (all prices from RenderZ)")
print("-" * 68)
print(f"{'Player':<28} {'OVR':>4} {'Price':>10} {'Shards':>7} {'M/shard':>9} {'Event':<6}")
print("-" * 68)

for p in market_data:
    cost_per_shard = p["price"] / p["shards"]
    eligible_str = "TOTS" if p["event"] == "TOTS" else "PREV"
    print(f"  {p['player']:<26} {p['ovr']:>4}  {p['price']/1e6:>8.1f}M  {p['shards']:>6}  {cost_per_shard/1e6:>7.3f}M  {eligible_str}")

# ── FIND BEST EFFICIENCY ─────────────────────────────────────
print("\n\n🏆 RANKED BY EFFICIENCY (cheapest coins per shard, best first)")
print("-" * 68)

sorted_data = sorted(market_data, key=lambda x: x["price"] / x["shards"])

print(f"{'Rank':<5} {'Player':<28} {'M per Shard':>12} {'Event':>6}")
print("-" * 68)
for rank, p in enumerate(sorted_data, 1):
    cps = p["price"] / p["shards"]
    marker = " <<< BEST" if rank == 1 else (" <<< 2ND" if rank == 2 else "")
    print(f"  {rank:<4} {p['player']:<28} {cps/1e6:>10.3f}M  {p['event']:>6}{marker}")

# ── SCENARIO ANALYSIS FOR 13,000 SHARDS ─────────────────────
SHARDS_NEEDED = 13_000
BUDGET = 2_871_000_000  # best-case budget after selling Rio Ferdinand at high

print(f"\n\n🎯 SCENARIO COMPARISON: Reaching {SHARDS_NEEDED:,} Shards")
print(f"   Budget: {BUDGET/1e9:.3f}B coins (after selling Rio at high + 450M coins)")
print("-" * 68)

print(f"\n{'Strategy':<35} {'Cards':>6} {'Total Cost':>12} {'Budget Left':>13} {'OK?':>4}")
print("-" * 68)

scenarios = [
    {
        "label": "TOTS 110-114 only (Beraldo 27.9M)",
        "price": 27_900_000, "shards": 150
    },
    {
        "label": "TOTS 110-114 only (Ndicka 28.8M)",
        "price": 28_800_000, "shards": 150
    },
    {
        "label": "Mix: 116 OVR prev (Hackney 425M)",
        "price": 425_000_000, "shards": 750
    },
    {
        "label": "Mix: 117 OVR prev (Berbatov 875M)",
        "price": 875_000_000, "shards": 2250
    },
    {
        "label": "Mix: 117 OVR prev (Raya 911M)",
        "price": 911_000_000, "shards": 2250
    },
]

import math

for s in scenarios:
    cards = math.ceil(SHARDS_NEEDED / s["shards"])
    total_cost = cards * s["price"]
    leftover = BUDGET - total_cost
    ok = "YES" if leftover >= 0 else "NO"
    print(f"  {s['label']:<33} {cards:>6}  {total_cost/1e6:>10.0f}M  {leftover/1e6:>11.0f}M  {ok:>4}")

# ── MIXED STRATEGY OPTIMIZATION ─────────────────────────────
print("\n\n🔬 MIXED STRATEGY: Optimal blend of tiers")
print("-" * 68)

# Key insight: what if you use a FEW high-OVR cards + fill rest with cheap?
# E.g. 1x Berbatov (117) = 2250 shards, need 10750 more from 110-114 (TOTS)
print("  Strategy A: 1x Berbatov (117 OVR) + fill with Beraldo (110-114 TOTS)")
berbatov_price = 875_000_000
berbatov_shards = 2250
remaining_shards_A = SHARDS_NEEDED - berbatov_shards
beraldo_price = 27_900_000
beraldo_shards = 150
beraldo_cards_A = math.ceil(remaining_shards_A / beraldo_shards)
cost_A = berbatov_price + (beraldo_cards_A * beraldo_price)
leftover_A = BUDGET - cost_A
print(f"    Cost: {berbatov_price/1e6:.0f}M + {beraldo_cards_A} x {beraldo_price/1e6:.1f}M = {cost_A/1e6:.0f}M | Left: {leftover_A/1e6:.0f}M | {'OK' if leftover_A >= 0 else 'NO'}")

print("  Strategy B: 2x Berbatov (117 OVR) + fill with Beraldo")
berbatov_count_B = 2
remaining_shards_B = SHARDS_NEEDED - (berbatov_count_B * berbatov_shards)
beraldo_cards_B = math.ceil(remaining_shards_B / beraldo_shards)
cost_B = (berbatov_count_B * berbatov_price) + (beraldo_cards_B * beraldo_price)
leftover_B = BUDGET - cost_B
print(f"    Cost: 2x {berbatov_price/1e6:.0f}M + {beraldo_cards_B} x {beraldo_price/1e6:.1f}M = {cost_B/1e6:.0f}M | Left: {leftover_B/1e6:.0f}M | {'OK' if leftover_B >= 0 else 'NO'}")

print("  Strategy C: 1x Hackney (116, 750sh) + fill with Beraldo")
hackney_price = 425_000_000
hackney_shards = 750
remaining_shards_C = SHARDS_NEEDED - hackney_shards
beraldo_cards_C = math.ceil(remaining_shards_C / beraldo_shards)
cost_C = hackney_price + (beraldo_cards_C * beraldo_price)
leftover_C = BUDGET - cost_C
print(f"    Cost: {hackney_price/1e6:.0f}M + {beraldo_cards_C} x {beraldo_price/1e6:.1f}M = {cost_C/1e6:.0f}M | Left: {leftover_C/1e6:.0f}M | {'OK' if leftover_C >= 0 else 'NO'}")

print("  Strategy D: Pure Beraldo (110-114 TOTS only)")
beraldo_cards_D = math.ceil(SHARDS_NEEDED / beraldo_shards)
cost_D = beraldo_cards_D * beraldo_price
leftover_D = BUDGET - cost_D
print(f"    Cost: {beraldo_cards_D} x {beraldo_price/1e6:.1f}M = {cost_D/1e6:.0f}M | Left: {leftover_D/1e6:.0f}M | {'OK' if leftover_D >= 0 else 'NO'}")

# ── VISUAL COST PER SHARD RANKING ───────────────────────────
print("\n\n📈 COST PER SHARD — THE KEY NUMBER THAT DECIDES EVERYTHING")
print("-" * 68)
print("  Lower M/shard = more efficient = you should buy THESE")
print()

tiers = [
    ("110-114 TOTS (Beraldo 27.9M)",  27_900_000, 150),
    ("110-114 TOTS (Ndicka 28.8M)",   28_800_000, 150),
    ("110-114 TOTS (Hincapie 30M)",   30_000_000, 150),
    ("115 PREV (Tillman 250M)",       250_000_000, 300),
    ("116 PREV (Hackney 425M)",       425_000_000, 750),
    ("117 PREV (Berbatov 875M)",      875_000_000, 2250),
    ("117 PREV (Raya 911M)",          911_000_000, 2250),
    ("117 PREV (Vlahovic 1.15B)",     1_150_000_000, 2250),
]

best_cps = min(t[0][0:3] and t[1]/t[2] for t in tiers)  # just for reference
all_cps = [(label, price, shards, price/shards) for label, price, shards in tiers]
all_cps_sorted = sorted(all_cps, key=lambda x: x[3])

for label, price, shards, cps in all_cps_sorted:
    bar_len = int((cps / all_cps_sorted[-1][3]) * 30)
    bar = "█" * bar_len
    verdict = " ✅ MOST EFFICIENT" if cps == all_cps_sorted[0][3] else ""
    verdict = " ❌ AVOID" if cps == all_cps_sorted[-1][3] else verdict
    print(f"  {cps/1e6:>6.3f}M/shard  {bar:<30}  {label}{verdict}")

# ── FINAL VERDICT ────────────────────────────────────────────
print("\n\n" + "=" * 68)
print("🏆 DEFINITIVE VERDICT")
print("=" * 68)
print()
print("  Q: Is it ALWAYS best to buy the lowest OVR (110-114)?")
print()
print("  SHORT ANSWER: YES — for this specific scenario.")
print()
print("  REASONING:")
print("  • Beraldo 112 TOTS = 0.186M coins per shard  (CHEAPEST)")
print("  • Hackney 116 PREV = 0.567M coins per shard  (3x MORE expensive)")
print("  • Berbatov 117 PREV = 0.389M coins per shard (2x MORE expensive)")
print()
print("  The 116 and 117 OVR cards from PREVIOUS events look attractive")
print("  because they give MORE shards per card, but their market price")
print("  rises proportionally MORE than the shard bonus they provide.")
print()
print("  EXCEPTION RULE — When higher OVR IS better:")
print("  • If 110-114 OVR TOTS fodder dries up from market (supply crash)")
print("  • If a 117 OVR prev-event card is extremely undervalued (e.g. <300M)")
print("    -> At 300M for 2250 shards = 0.133M/shard (BETTER than Beraldo!)")
print("  • Always calculate: Price / Shards = M per shard. Pick lowest.")
print()
print("  YOUR OPTIMAL PLAN:")
print(f"  1. Sell Rio Ferdinand at 2.69B → War chest ~2.87B")
print(f"  2. Hunt the CHEAPEST TOTS 110-114 OVR cards on market")
print(f"     (Target: Lucas Beraldo type @ ~27.9M or lower)")
print(f"  3. If supply of cheap 110-114 runs out mid-shopping,")
print(f"     SWITCH to 117 OVR prev-event if price < ~500M")
print(f"     (500M / 2250 = 0.222M/shard — still beats Hackney 116)")
print(f"  4. Need {math.ceil(SHARDS_NEEDED/150)} cards minimum (pure 110-114 route)")
print(f"     Total cost: ~{math.ceil(SHARDS_NEEDED/150) * 27_900_000 / 1e6:.0f}M coins")
print(f"  5. Release all → {SHARDS_NEEDED:,} shards → Star Sign Gabriel 118 ✅")
print()
print("  BUDGET STATUS:")
print(f"  War chest (best):  {BUDGET/1e9:.3f}B")
print(f"  Fodder cost:       {math.ceil(SHARDS_NEEDED/150) * 27_900_000 / 1e6:.0f}M  (87 cards @ 27.9M)")
print(f"  Remaining:         {(BUDGET - math.ceil(SHARDS_NEEDED/150) * 27_900_000) / 1e6:.0f}M coins left over")
print("=" * 68)
