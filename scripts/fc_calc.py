
# ============================================================
# FC MOBILE UPGRADE STRATEGY CALCULATOR
# Live data sourced from RenderZ.app (May 3, 2026)
# ============================================================

print("=" * 60)
print("FC MOBILE UPGRADE STRATEGY CALCULATOR")
print("Data sourced from RenderZ.app - Live as of May 3, 2026")
print("=" * 60)

# ── RAW MARKET DATA (from RenderZ screenshots) ───────────────
RIO_FERDINAND_117_BASE_PRICE  = 5_330_000_000   # 5.33B (base, unranked)
RIO_FERDINAND_122_RANKED_PRICE = 2_570_000_000  # 2.57B (rank 5 = 122 OVR)
RIO_LOW  = 2_440_000_000
RIO_HIGH = 2_690_000_000

GABRIEL_118_PRICE = 3_690_000_000               # 3.69B market buy price
GABRIEL_SHARD_COST = 13_000                     # shards needed for Star Signing

CURRENT_COINS = 450_000_000                     # 450M current balance

MARKET_TAX = 0.10                               # 10% EA market tax

# ── CHEAPEST 110-114 OVR FODDER (from RenderZ, auctionable) ──
CHEAPEST_FODDER_PRICE  = 32_700_000   # Anton 110 OVR base (unranked est.)
FODDER_113_PRICE       = 42_500_000   # Anton rank-1 confirmed on screen
FODDER_SHARDS_PER_CARD = 150          # 110-114 OVR yields 150 shards

print("\n📊 LIVE MARKET DATA (RenderZ, May 3 2026)")
print("-" * 60)
print(f"  Rio Ferdinand 117 OVR (base)   : {RIO_FERDINAND_117_BASE_PRICE/1e9:.3f}B coins")
print(f"  Rio Ferdinand 122 OVR (rank 5) : {RIO_FERDINAND_122_RANKED_PRICE/1e9:.3f}B coins")
print(f"  Rio market low / high          : {RIO_LOW/1e9:.3f}B - {RIO_HIGH/1e9:.3f}B")
print(f"  Gabriel TOTS 118 OVR (market)  : {GABRIEL_118_PRICE/1e9:.3f}B coins")
print(f"  Gabriel Star Signing cost      : {GABRIEL_SHARD_COST:,} shards")
print(f"  Cheapest 110 OVR fodder (Anton): {CHEAPEST_FODDER_PRICE/1e6:.1f}M coins")
print(f"  Shards per 110-114 OVR card    : {FODDER_SHARDS_PER_CARD} shards")

# ============================================================
# PHASE 1: What do you get from selling Rio Ferdinand?
# ============================================================
print("\n\n PHASE 1 - SELLING RIO FERDINAND (122 OVR)")
print("-" * 60)

after_tax_best   = RIO_HIGH * (1 - MARKET_TAX)
after_tax_mid    = RIO_FERDINAND_122_RANKED_PRICE * (1 - MARKET_TAX)
after_tax_worst  = RIO_LOW * (1 - MARKET_TAX)

total_budget_best   = CURRENT_COINS + after_tax_best
total_budget_mid    = CURRENT_COINS + after_tax_mid
total_budget_worst  = CURRENT_COINS + after_tax_worst

print(f"  Sell at HIGH  ({RIO_HIGH/1e9:.3f}B) -> after 10% tax: {after_tax_best/1e9:.3f}B")
print(f"  Sell at MID   ({RIO_FERDINAND_122_RANKED_PRICE/1e9:.3f}B) -> after 10% tax: {after_tax_mid/1e9:.3f}B")
print(f"  Sell at LOW   ({RIO_LOW/1e9:.3f}B) -> after 10% tax: {after_tax_worst/1e9:.3f}B")
print()
print(f"  TOTAL BUDGET (coins + sale) at midpoint:")
print(f"    Mid case  : {total_budget_mid/1e9:.3f}B coins")
print(f"    Best case : {total_budget_best/1e9:.3f}B coins")
print(f"    Worst case: {total_budget_worst/1e9:.3f}B coins")

# ============================================================
# ROUTE 1: Direct Market Buy of Gabriel 118
# ============================================================
print("\n\n ROUTE 1 - DIRECT MARKET BUY (Gabriel 118 OVR)")
print("-" * 60)

route1_cost     = GABRIEL_118_PRICE
route1_leftover_mid  = total_budget_mid - route1_cost
route1_leftover_best = total_budget_best - route1_cost
route1_feasible_mid  = total_budget_mid >= route1_cost
route1_feasible_best = total_budget_best >= route1_cost

print(f"  Gabriel 118 market price       : {route1_cost/1e9:.3f}B coins")
print(f"  Your total budget (mid)        : {total_budget_mid/1e9:.3f}B coins")
print(f"  Remaining after purchase (mid) : {route1_leftover_mid/1e9:.3f}B coins")
print(f"  Feasible at mid price?         : {'YES' if route1_feasible_mid else 'NO'}")

if not route1_feasible_mid:
    shortfall_mid = abs(route1_leftover_mid)
    print(f"  SHORTFALL at mid price         : {shortfall_mid/1e6:.0f}M coins")
if not route1_feasible_best:
    shortfall_best = abs(route1_leftover_best)
    print(f"  SHORTFALL even at best case    : {shortfall_best/1e6:.0f}M coins")
elif route1_feasible_best:
    print(f"  At BEST case: surplus          : {route1_leftover_best/1e6:.0f}M coins")

# ============================================================
# ROUTE 2: Star Shard Arbitrage
# ============================================================
print("\n\n ROUTE 2 - STAR SHARD ARBITRAGE (Star Signing Gabriel)")
print("-" * 60)

shards_needed = GABRIEL_SHARD_COST
shards_per_card = FODDER_SHARDS_PER_CARD
fodder_price = CHEAPEST_FODDER_PRICE

import math
cards_needed = math.ceil(shards_needed / shards_per_card)
fodder_total_cost = cards_needed * fodder_price

route2_leftover_mid  = total_budget_mid - fodder_total_cost
route2_leftover_best = total_budget_best - fodder_total_cost
route2_feasible = total_budget_mid >= fodder_total_cost

print(f"  Shards needed for Gabriel      : {shards_needed:,}")
print(f"  Shards per 110 OVR fodder card : {shards_per_card}")
print(f"  Cards required (ceiling div)   : {cards_needed}")
print(f"  Cheapest fodder price each     : {fodder_price/1e6:.1f}M coins")
print(f"  Total fodder cost              : {fodder_total_cost/1e9:.3f}B coins ({fodder_total_cost/1e6:.0f}M)")
print(f"  Your total budget (mid)        : {total_budget_mid/1e9:.3f}B coins")
print(f"  Remaining after all moves(mid) : {route2_leftover_mid/1e9:.3f}B coins")
print(f"  Feasible?                      : {'YES' if route2_feasible else 'NO'}")

# Ranked fodder variant
cards_needed_r1 = cards_needed
fodder_total_cost_r1 = cards_needed_r1 * FODDER_113_PRICE
leftover_r1 = total_budget_mid - fodder_total_cost_r1
print(f"\n  -- If using rank-1 110 OVR (Anton @ {FODDER_113_PRICE/1e6:.1f}M):")
print(f"     Total cost: {fodder_total_cost_r1/1e9:.3f}B | Budget left: {leftover_r1/1e9:.3f}B")

# ============================================================
# COMPARISON
# ============================================================
print("\n\n ROUTE COMPARISON (at mid-budget scenario)")
print("=" * 60)
print(f"{'Metric':<38} {'Route 1':>10} {'Route 2':>10}")
print("-" * 60)
print(f"{'Strategy':<38} {'Market Buy':>10} {'Star Sign':>10}")
print(f"{'True Coin Cost':<38} {route1_cost/1e9:>9.3f}B {fodder_total_cost/1e6:>8.0f}M")
print(f"{'Budget (mid)':<38} {total_budget_mid/1e9:>9.3f}B {total_budget_mid/1e9:>9.3f}B")
print(f"{'Leftover coins':<38} {route1_leftover_mid/1e9:>9.3f}B {route2_leftover_mid/1e9:>9.3f}B")
print(f"{'Feasible at mid?':<38} {'YES' if route1_feasible_mid else 'NO':>10} {'YES' if route2_feasible else 'NO':>10}")
print(f"{'RNG / Pack luck?':<38} {'None':>10} {'None':>10}")
print(f"{'Market price risk':<38} {'HIGH':>10} {'LOW':>10}")
print(f"{'Execution time':<38} {'Instant':>10} {'2-3 days':>10}")

savings = route1_cost - fodder_total_cost
print()
print(f"  SAVINGS by choosing Route 2: {savings/1e6:.0f}M coins ({savings/1e9:.3f}B)")
saving_pct = (savings / route1_cost) * 100
print(f"  That is {saving_pct:.1f}% cheaper than the direct market buy!")

# ============================================================
# VERDICT
# ============================================================
print("\n\n FINAL VERDICT & ACTION PLAN")
print("=" * 60)

if not route1_feasible_mid and route2_feasible:
    print("  RECOMMENDED: ROUTE 2 - STAR SHARD ARBITRAGE")
    print("  Reason: You cannot afford Gabriel directly on market.")
    print("          Shard route is your ONLY viable path AND saves")
    print(f"          {savings/1e6:.0f}M coins over the market price.")
elif route2_feasible and savings > 0:
    print("  RECOMMENDED: ROUTE 2 - STAR SHARD ARBITRAGE")
    print(f"  Reason: Saves {savings/1e6:.0f}M coins vs. direct market buy.")
else:
    print("  RECOMMENDED: ROUTE 1 - DIRECT MARKET BUY")

print()
print("  STEP-BY-STEP ACTION PLAN:")
print(f"     Step 1: List Rio Ferdinand 122 at {RIO_HIGH/1e9:.3f}B (market high)")
print(f"             --> Time listing 1h49m before 05:55 PM refresh")
print(f"             --> Gets you to front of the sell queue")
print(f"     Step 2: After sale, war chest = ~{total_budget_best/1e9:.3f}B coins (best case)")
print(f"     Step 3: Buy {cards_needed} x Anton 110 OVR @ ~{fodder_price/1e6:.0f}M each")
print(f"             --> Total spend: {fodder_total_cost/1e6:.0f}M coins ({fodder_total_cost/1e9:.3f}B)")
print(f"     Step 4: Release all {cards_needed} Anton cards -> earn {cards_needed * shards_per_card:,} shards")
print(f"             (This covers your {shards_needed:,} shard target with {cards_needed * shards_per_card - shards_needed} spare)")
print(f"     Step 5: Go to Star Signing, select Gabriel 118 OVR")
print(f"             Spend {shards_needed:,} shards -> Gabriel is YOURS. Done.")
print(f"     Step 6: Leftover coins after everything:")
print(f"             Best case : {(total_budget_best - fodder_total_cost)/1e9:.3f}B coins")
print(f"             Mid case  : {route2_leftover_mid/1e9:.3f}B coins")

print()
print("  MARKET TIMING TIPS:")
print("     - RIO best sell window: right before weekend events")
print("     - Market refresh at 05:55 PM (per RenderZ) -> list 1h49m before")
print("     - Buy fodder right AFTER a weekly reset (supply spikes, prices dip)")
print("     - Anton 110 OVR is the most cost-efficient at 150 shards per card")

print()
print("  CAVEATS:")
print("     - RenderZ prices are community estimates, not live order books")
print("     - Always verify IN-GAME before executing any large trade")
print("     - 10% tax already factored into all calculations above")
print("     - If you already have saved shards, your fodder cost is lower!")
print("=" * 60)
