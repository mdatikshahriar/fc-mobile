"""
=============================================================
RenderZ.app Unofficial API Client
Reverse-engineered from SvelteKit chunk: UVJLneNj.js
Discovered: May 3, 2026

RenderZ migrated their whole player-search architecture on/around 2026-09-03
(the old POST /api/players/filter started 404ing on every request). The new
search endpoint was reverse-engineered on 2026-09-04 via a Playwright-driven
browser session (network capture on the live /players page, not bulk crawling
of JS bundles), per explicit user instruction given the earlier decision not
to crawl RenderZ's site directly (their robots.txt disallows ClaudeBot and
/api/* for all crawlers).

WORKING ENDPOINTS:
  GET  /api/search/{seasonId}?v=1&q=<encoded>   → player search (see search_players)
  GET  /api/filter/filter-data/{name}?seasonId=  → filter options
  GET  /api/card-generator/search-images?year=23&query=  → player image search
  GET  /api/player/market/{id}   → per-player market detail (current value/trend,
                                    market low/high, real buy/sell prices) —
                                    confirmed via browser network capture,
                                    unaffected by the 2026-09 migration.

/api/search/{seasonId} query encoding: `q` is a raw Elasticsearch query DSL,
JSON-serialized, raw-deflate compressed (no zlib/gzip header, i.e.
`zlib.compressobj(9, zlib.DEFLATED, -15)`), then base64url-encoded with the
padding stripped (`+`/`/` -> `-`/`_`, trailing `=` removed). Field names
confirmed by testing against the live API (it validates sort/query fields
and returns a helpful `{"message": "..."}` on a bad one):
  - rating range:  {"range": {"rating": {"gte": X, "lte": Y}}}
  - auctionable:   {"match": {"auctionable": true}}
  - program(s):    {"terms": {"source.keyword": ["PROGRAM_ICONS", ...]}}
  - sort by price: {"priceData.0.basePrice": {"order": "asc"}} — same
                   priceData shape as before, just a different query mechanism.
Response shape: {"players": [...], "pagination": [...]}. No more page-count
metadata — paginate by incrementing `from` and stopping once a page returns
fewer than `size` results. Max `size` is 100 (200+ is rejected). The player
object's id field is now `assetId` (was `id`).

SEASON IDs:
  23  = FC 24/25 (current as of May 2026, still current as of Sep 2026)
  22  = FC 23/24 (legacy)
=============================================================
"""

import urllib.request
import urllib.error
import json
import time
import base64
import zlib
from typing import Optional

BASE = "https://renderz.app"
SEASON_ID = 23  # FC 24/25 (current)
MAX_PAGE_SIZE = 100  # confirmed max accepted by /api/search; 200 is rejected

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Referer": "https://renderz.app/24/players",
    "Origin": "https://renderz.app",
    "Accept-Encoding": "identity",
}


def _request_json(req, timeout=15, retries=3, backoff=1.5):
    """
    RenderZ's backend times out on roughly 1 in 5 requests at random (observed
    empirically, not tied to any specific endpoint). With ~140 sequential requests
    per pagination cycle and zero retries, a full cycle was virtually guaranteed to
    hit at least one timeout and abort entirely. Retry with backoff before giving up.
    """
    last_exc = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_exc = e
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
    raise last_exc


def _encode_search_query(query: dict) -> str:
    """base64url(raw_deflate(json)) with padding stripped — see module docstring."""
    raw = json.dumps(query, separators=(",", ":")).encode()
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    compressed = compressor.compress(raw) + compressor.flush()
    b64 = base64.b64encode(compressed).decode()
    return b64.replace("+", "-").replace("/", "_").rstrip("=")


# Only the one sort type this codebase actually uses (priceRank0) is mapped here —
# not a general legacyId -> field translator. Extend if a new sort type is needed.
_SORT_FIELD_MAP = {
    "priceRank0": "priceData.0.basePrice",
}


def search_players(
    name: Optional[str] = None,
    min_rating: Optional[int] = None,
    max_rating: Optional[int] = None,
    position: Optional[str] = None,
    programs: Optional[list] = None,
    auctionable_only: bool = True,
    sort_type: str = "priceRank0",
    sort_direction: str = "ASC",
    page: int = 1,
    season_id: int = SEASON_ID,
) -> dict:
    """
    Search FC Mobile players via RenderZ's Elasticsearch-backed /api/search endpoint
    (migrated from the old POST /api/players/filter around 2026-09-03 — see module
    docstring for the query encoding and how each filter below was confirmed).

    Args:
        name: Player name to search (e.g. "gabriel") — best-effort multi-field match,
              not empirically confirmed against the live API (unused by market_analyzer.py).
        min_rating: Minimum OVR rating
        max_rating: Maximum OVR rating
        position: Position filter (e.g. "CB", "ST", "GK") — best-effort match query,
                  not empirically confirmed (config.json currently leaves this null).
        programs: List of program IDs (e.g. ["PROGRAM_ICONS", "PROGRAM_HEROS8"]).
        auctionable_only: Only return market-tradeable cards
        sort_type: Sort field — only "priceRank0" (cheapest first) is translated;
                   anything else falls back to sorting by rating.
        sort_direction: ASC or DESC
        page: Page number (MAX_PAGE_SIZE players per page — offset-based: page N
              fetches from=(N-1)*MAX_PAGE_SIZE)
        season_id: Season database ID (23 = FC 24/25)

    Returns:
        dict with keys: players, pagination (no page-count metadata — see
        MAX_PAGE_SIZE and the calling loop's stopping condition in market_analyzer.py)
    """
    must = []
    if min_rating is not None or max_rating is not None:
        rating_range = {}
        if min_rating is not None:
            rating_range["gte"] = min_rating
        if max_rating is not None:
            rating_range["lte"] = max_rating
        must.append({"range": {"rating": rating_range}})
    if position:
        must.append({"match": {"position": position}})
    if programs:
        must.append({"terms": {"source.keyword": programs}})
    if auctionable_only:
        must.append({"match": {"auctionable": True}})
    if name:
        must.append({"multi_match": {"query": name, "fields": ["cardName", "commonName", "firstName", "lastName"]}})

    sort_field = _SORT_FIELD_MAP.get(sort_type, "rating")
    order = "asc" if sort_direction.upper() == "ASC" else "desc"

    query = {
        "query": {"bool": {"must": must, "should": [], "must_not": []}},
        "sort": [{sort_field: {"order": order}}, {"assetId": {"order": order}}],
        "_source": [],
        "from": (page - 1) * MAX_PAGE_SIZE,
        "size": MAX_PAGE_SIZE,
    }

    q = _encode_search_query(query)
    url = f"{BASE}/api/search/{season_id}?v=1&q={q}"
    req = urllib.request.Request(url, headers=HEADERS)
    return _request_json(req)


def get_player_market(player_id, rank: int = 0) -> Optional[dict]:
    """
    Fetch the per-player market detail panel (the one shown on a player's own
    renderz.app page): current value + trend, market low/high range, and real
    executable buy/sell prices.

    Endpoint confirmed via a browser network capture (GET /api/player/market/{id}),
    not discovered through bulk crawling of the site's JS bundles.

    Returns the entry for `rank` (default 0, matching the unupgraded card the
    bulk /api/players/filter search already targets), or None if unavailable.
    Fields of note:
      - basePrice / previousBasePrice / basePricePercentageChange:
            RenderZ's own smoothed "current value" and short-term trend,
            refreshed independently of our own polling (see nextRefreshTime).
      - lowPrice / highPrice: the recent market range for this card.
      - marketLowestBuyPrice: the real price to buy right now (ask).
      - marketLowestSellPrice: the real price to sell right now (bid). A value
            of 0 means there is currently NO instant-sell liquidity at all —
            i.e. after buying, you may have to list and wait for a buyer
            rather than exit immediately.
    """
    # This endpoint 404s unless Referer matches the specific player's own page
    # (not the generic /24/players list page used elsewhere in this module).
    headers = {**HEADERS, "Referer": f"{BASE}/24/player/{player_id}"}
    url = f"{BASE}/api/player/market/{player_id}"
    req = urllib.request.Request(url, headers=headers)
    try:
        data = _request_json(req)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    return data.get(str(rank))


def get_filter_options(filter_name: str, season_id: int = SEASON_ID) -> list:
    """
    Get valid filter options for a given filter type.

    filter_name options: programs, positions, leagues, clubs, nations
    """
    url = f"{BASE}/api/filter/filter-data/{filter_name}?seasonId={season_id}"
    req = urllib.request.Request(url, headers=HEADERS)
    return _request_json(req)


def format_price(price_coins: int) -> str:
    if price_coins >= 1_000_000_000:
        return f"{price_coins/1e9:.3f}B"
    elif price_coins >= 1_000_000:
        return f"{price_coins/1e6:.1f}M"
    elif price_coins >= 1_000:
        return f"{price_coins/1e3:.1f}K"
    return str(price_coins)


def print_players(result: dict, title: str = ""):
    players = result.get("players", [])
    print(f"\n{'='*70}")
    if title:
        print(f"  {title}")
    print(f"  Results: {len(players)} players")
    print(f"{'='*70}")
    print(f"  {'Name':<25} {'OVR':>4} {'POS':>4} {'Price':>12} {'Auc':>5}")
    print(f"  {'-'*55}")
    for p in players:
        price_raw = 0
        price_data = p.get("priceData", {})
        if price_data:
            rank0 = price_data.get("0", {})
            price_raw = rank0.get("basePrice", 0) if rank0 else 0
        name = p.get("cardName", p.get("commonName", "?"))
        ovr = p.get("rating", "?")
        pos = p.get("position", "?")
        auc = "✅" if p.get("auctionable") else "❌"
        pid = p.get("assetId", "?")
        price_str = format_price(price_raw) if price_raw else "—"
        print(f"  {name:<25} {ovr:>4} {pos:>4} {price_str:>12} {auc:>5}  [id={pid}]")
    print()


# ============================================================
# LIVE DEMO — Run directly to query real data
# ============================================================
if __name__ == "__main__":

    print("=" * 70)
    print("RENDERZ API LIVE QUERY — FC Mobile 26 Player Data")
    print("=" * 70)

    # 1. Search for Gabriel 118 TOTS
    print("\n[1] Searching for Gabriel 118 OVR...")
    result = search_players(name="gabriel", min_rating=118, max_rating=118, auctionable_only=False)
    print_players(result, "Gabriel 118 OVR — All cards")

    time.sleep(0.5)

    # 2. Cheapest auctionable 110-114 TOTS 26 players
    print("\n[2] Cheapest auctionable 110-114 OVR players (fodder)...")
    result2 = search_players(
        min_rating=110,
        max_rating=114,
        auctionable_only=True,
        sort_type="priceRank0",
        sort_direction="ASC",
        program="PROGRAM_TOTS26",
    )
    print_players(result2, "110-114 OVR TOTS 26 — Sorted by Price (cheapest first)")

    time.sleep(0.5)

    # 3. Rio Ferdinand market price
    print("\n[3] Searching for Rio Ferdinand...")
    result3 = search_players(name="rio ferdinand", auctionable_only=True)
    print_players(result3, "Rio Ferdinand — Market listings")

    time.sleep(0.5)

    # 4. Summary: cheapest price per shard
    print("\n[4] Cost-per-shard analysis (110-114 OVR TOTS 26 fodder)...")
    players = result2.get("players", [])
    print(f"  {'Name':<25} {'OVR':>4} {'Price':>10} {'M/shard':>10}")
    print(f"  {'-'*55}")
    for p in players[:10]:
        price_raw = 0
        pd = p.get("priceData", {})
        if pd and pd.get("0"):
            price_raw = pd["0"].get("basePrice", 0)
        if price_raw > 0:
            cost_per_shard = price_raw / 150  # 110-114 gives 150 shards
            name = p.get("cardName", "?")
            ovr = p.get("rating", "?")
            print(f"  {name:<25} {ovr:>4} {format_price(price_raw):>10} {format_price(int(cost_per_shard)):>10}")
