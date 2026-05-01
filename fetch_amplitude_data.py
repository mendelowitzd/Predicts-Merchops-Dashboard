#!/usr/bin/env python3
"""
fetch_amplitude_data.py
-----------------------
Pulls data from your existing Amplitude charts and writes data.json
for the Predicts Merch Ops Dashboard.

Chart sources (Futures FE Prod, project 712023):
  - Volume:  https://app.amplitude.com/analytics/fanduel/chart/4sx2glsm
  - Orders:  queries same event with totals metric (Futures FE Prod)

Credentials live in GitHub repo secrets — never in code.
Required secrets:
  AMPLITUDE_API_KEY    — Futures FE Prod API key
  AMPLITUDE_SECRET_KEY — Futures FE Prod secret key

Run manually:
  AMPLITUDE_API_KEY=xxx AMPLITUDE_SECRET_KEY=yyy python fetch_amplitude_data.py
"""

import os, sys, json, base64, urllib.request, urllib.parse, re
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# ── Credentials ──────────────────────────────────────────────────────────────
API_KEY    = os.environ.get("AMPLITUDE_API_KEY", "")
SECRET_KEY = os.environ.get("AMPLITUDE_SECRET_KEY", "")

if not API_KEY or not SECRET_KEY:
    print("ERROR: Set AMPLITUDE_API_KEY and AMPLITUDE_SECRET_KEY env vars.", file=sys.stderr)
    sys.exit(1)

CREDS = base64.b64encode(f"{API_KEY}:{SECRET_KEY}".encode()).decode()

# ── Chart IDs (your existing dashboards) ─────────────────────────────────────
CHART_VOLUME_ID = "4sx2glsm"   # Predicts Orders Placed By Trade Volume (CumSum)
# Orders chart (jkvikyux) is in the Roll-Up project — we replicate its query
# here against Futures FE Prod so we only need one set of credentials.

# ── Amplitude event / property names (Futures FE Prod) ───────────────────────
EVENT_NAME       = "Order Placed Success"
MARKET_NAME_PROP = "Market Name"
EVENT_NAME_PROP  = "Event Name"
SOURCE_PROP      = "Source"
MARKET_CAT_PROP  = "Market Category"

# ── Date helpers ──────────────────────────────────────────────────────────────
now       = datetime.now(timezone.utc)
today     = now.strftime("%Y%m%d")
yesterday = (now - timedelta(days=1)).strftime("%Y%m%d")
monday    = (now - timedelta(days=now.weekday())).strftime("%Y%m%d")


# ── HTTP helpers ──────────────────────────────────────────────────────────────
def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {CREDS}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  Request failed ({url[:80]}…): {e}", file=sys.stderr)
        return {}


def query_chart(chart_id: str) -> list[list]:
    """Query a saved Amplitude chart by ID. Returns CSV rows."""
    data = _get(f"https://amplitude.com/api/3/chart/{chart_id}/query")
    # Response: {"data": {"series": [...], "seriesLabels": [...], ...}}
    # The chart API returns different shapes; try both formats.
    if "data" in data:
        d = data["data"]
        if "seriesLabels" in d and "series" in d:
            return _parse_series(d)
    return []


def segmentation(event: str, group_props: list[str],
                 start: str, end: str, metric: str = "totals") -> dict:
    """Amplitude segmentation API → {label: value}."""
    params = {
        "e": json.dumps({"event_type": event}),
        "start": start, "end": end, "i": "1", "m": metric,
        "g": json.dumps([{"type": "event", "value": p} for p in group_props]),
    }
    qs  = urllib.parse.urlencode(params)
    url = f"https://amplitude.com/api/2/events/segmentation?{qs}"
    body = _get(url)
    d = body.get("data", {})
    result = {}
    for label, series in zip(d.get("seriesLabels", []), d.get("series", [])):
        if label and label != "(none)":
            result[str(label)] = sum(series or [])
    return result


def _parse_series(d: dict) -> dict:
    """Parse seriesLabels + series into {label: total}."""
    result = {}
    for label, series in zip(d.get("seriesLabels", []), d.get("series", [])):
        if label and label != "(none)":
            result[str(label)] = sum(series or [])
    return result


# ── Sport detection ───────────────────────────────────────────────────────────
# Maps snake_case fragments (from Amplitude event names) to sport labels.
SPORT_FRAGMENTS = {
    # NBA teams
    "nuggets":"NBA","timberwolves":"NBA","celtics":"NBA","76_ers":"NBA",
    "knicks":"NBA","hawks":"NBA","rockets":"NBA","lakers":"NBA",
    "cavaliers":"NBA","raptors":"NBA","pistons":"NBA","magic":"NBA",
    "thunder":"NBA","suns":"NBA","spurs":"NBA","blazers":"NBA",
    "heat":"NBA","bucks":"NBA","hornets":"NBA","pelicans":"NBA",
    "kings":"NBA","jazz":"NBA","warriors":"NBA","bulls":"NBA",
    "pacers":"NBA","nets":"NBA","wizards":"NBA","grizzlies":"NBA",
    "mavericks":"NBA","clippers":"NBA","nba_champion":"NBA",
    # MLB teams
    "tigers":"MLB","braves":"MLB","royals":"MLB","athletics":"MLB",
    "blue_jays":"MLB","twins":"MLB","giants":"MLB","phillies":"MLB",
    "astros":"MLB","orioles":"MLB","rockies":"MLB","reds":"MLB",
    "cardinals":"MLB","pirates":"MLB","diamondbacks":"MLB","brewers":"MLB",
    "nationals":"MLB","mets":"MLB","dodgers":"MLB","padres":"MLB",
    "rangers":"MLB","yankees":"MLB","red_sox":"MLB","mariners":"MLB",
    "rays":"MLB","guardians":"MLB","cubs":"MLB","white_sox":"MLB",
    "angels":"MLB","marlins":"MLB","world_series":"MLB",
    # NHL teams
    "mammoth":"NHL","golden_knights":"NHL","stars":"NHL","wild":"NHL",
    "oilers":"NHL","ducks":"NHL","lightning":"NHL","canadiens":"NHL",
    "bruins":"NHL","sabres":"NHL","flyers":"NHL","penguins":"NHL",
    "hurricanes":"NHL","stanley_cup":"NHL",
    # PGA / Golf
    "cadillac_championship":"PGA","clover_crown":"PGA",
    "skys_the_limit":"PGA","moving_on":"PGA","i_will_survive":"PGA",
    "pga":"PGA",
    # Tennis
    "ruud":"Tennis","blockx":"Tennis","zverev":"Tennis","sinner":"Tennis",
    "fils":"Tennis","baptiste":"Tennis","andreeva":"Tennis",
    "kostyuk":"Tennis","potapova":"Tennis","madrid_open":"Tennis",
    # Futures / Predicts (non-sport)
    "bitcoin":"Futures","ether":"Futures","crude_oil":"Futures",
    "gold_futures":"Futures","nasdaq":"Futures","s_p_500":"Futures",
    "dow_jones":"Futures","silver":"Futures","copper":"Futures",
    "natural_gas":"Futures","russell":"Futures","eur_usd":"Futures",
    # Long-form futures
    "nba_champion":"Futures","stanley_cup":"Futures","world_series":"Futures",
    "super_bowl":"Futures","world_cup":"Futures","epl_champion":"Futures",
    "uefa":"Futures","college_football":"Futures","house_majority":"Futures",
    "senate_majority":"Futures","winning_party":"Futures",
    "unemployment_rate":"Futures","non_farm_payroll":"Futures",
    "gross_domestic_product":"Futures","consumer_price_index":"Futures",
}

def detect_sport(event_key: str) -> str:
    """Detect sport/category from a snake_case Amplitude event key."""
    k = event_key.lower()
    for fragment, sport in SPORT_FRAGMENTS.items():
        if fragment in k:
            return sport
    return "Other"


def snake_to_display(event_key: str) -> str:
    """Convert snake_case event key to a human-readable display name.
    e.g. 'den_nuggets_at_min_timberwolves' → 'DEN Nuggets at MIN Timberwolves'
    """
    # Replace ' at ' separator
    parts = event_key.replace("_at_", " @ ")
    # Title-case each segment
    segments = parts.split(" @ ")
    out = []
    for seg in segments:
        words = seg.split("_")
        # First word is typically a 2-4 char team code → uppercase
        titled = []
        for i, w in enumerate(words):
            if i == 0 and len(w) <= 4:
                titled.append(w.upper())
            else:
                titled.append(w.capitalize())
        out.append(" ".join(titled))
    return " @ ".join(out)


# ── Parse "market_name; event_name": value rows ───────────────────────────────
def parse_market_event_rows(raw: dict) -> tuple[dict, dict, dict]:
    """
    Input: {"moneyline; den_nuggets_at_min_timberwolves": 1497, ...}
    Returns:
      event_orders  = {"den_nuggets_at_min_timberwolves": total_orders}
      market_orders = {"Moneyline": total_orders, ...}
      event_key_map = {"den_nuggets_at_min_timberwolves": display_name}
    """
    event_orders  = defaultdict(float)
    market_orders = defaultdict(float)
    event_key_map = {}

    MARKET_LABELS = {
        "moneyline": "Moneyline", "spread": "Spread",
        "total_points": "Total Points", "combo": "Combo/Parlay",
        "player_props": "Player Props",
    }

    for key, val in raw.items():
        if "; " not in str(key):
            continue
        parts = str(key).split("; ", 1)
        market_raw = parts[0].strip()
        event_raw  = parts[1].strip() if len(parts) > 1 else ""

        market_label = MARKET_LABELS.get(market_raw, market_raw.replace("_", " ").title())
        if event_raw and event_raw != "null" and event_raw != "(none)":
            event_orders[event_raw]  += val
            event_key_map[event_raw]  = snake_to_display(event_raw)
        market_orders[market_label] += val

    return dict(event_orders), dict(market_orders), event_key_map


# ── Fetch all data ────────────────────────────────────────────────────────────
print("Fetching Amplitude data…")

# 1. Volume by market+event (from your existing chart)
print("  [1/5] Volume chart (4sx2glsm)")
volume_raw = segmentation(
    EVENT_NAME, [MARKET_NAME_PROP, EVENT_NAME_PROP],
    today, today, metric="sums"
)
# Note: if you want to pull directly from the saved chart (preserving its
# exact filters/segments), swap the line above for:
#   volume_raw = query_chart(CHART_VOLUME_ID)
# The segmentation query above uses the same logic but with today's date window.

# 2. Order counts by market+event (same grouping, totals metric)
print("  [2/5] Order counts by market + event name")
orders_raw = segmentation(
    EVENT_NAME, [MARKET_NAME_PROP, EVENT_NAME_PROP],
    today, today, metric="totals"
)

# 3. Sport share today
print("  [3/5] Sport share today")
sport_today = segmentation(EVENT_NAME, [MARKET_CAT_PROP], today, today)

# 4. Sport share yesterday
print("  [4/5] Sport share yesterday")
sport_yest = segmentation(EVENT_NAME, [MARKET_CAT_PROP], yesterday, yesterday)

# 5. Source of trade
print("  [5/5] Source of trade")
sources = segmentation(EVENT_NAME, [SOURCE_PROP], today, today)

# 6. Orders this week by event (for Top 10 Week)
print("  [6/6] Top events this week")
week_raw = segmentation(
    EVENT_NAME, [MARKET_NAME_PROP, EVENT_NAME_PROP],
    monday, today, metric="totals"
)

print("Done fetching.")

# ── Process data ──────────────────────────────────────────────────────────────
event_orders,  market_orders,  key_map_today = parse_market_event_rows(orders_raw)
event_volume,  _,              _             = parse_market_event_rows(volume_raw)
event_orders_w, _,             key_map_week  = parse_market_event_rows(week_raw)
key_map = {**key_map_today, **key_map_week}

# Build eventsByName for the priority matching section
events_by_name = {
    key_map.get(k, snake_to_display(k)): {
        "orders": int(v),
        "volume": round(event_volume.get(k, 0), 2),
    }
    for k, v in event_orders.items()
}

# Top 10 events today
top_events_today = sorted(
    [
        {
            "name":   key_map.get(k, snake_to_display(k)),
            "orders": int(v),
            "volume": round(event_volume.get(k, 0), 2),
            "sport":  detect_sport(k),
        }
        for k, v in event_orders.items()
    ],
    key=lambda x: x["orders"], reverse=True
)[:10]

# Top 10 events this week
top_events_week = sorted(
    [
        {
            "name":   key_map.get(k, snake_to_display(k)),
            "orders": int(v),
            "sport":  detect_sport(k),
        }
        for k, v in event_orders_w.items()
    ],
    key=lambda x: x["orders"], reverse=True
)[:10]

# Totals
total_orders = int(sum(event_orders.values()))
trade_volume = round(sum(event_volume.values()), 2)

# Clean up sport share (remove empty keys)
sport_today = {k: int(v) for k, v in sport_today.items() if k and k != "(none)"}
sport_yest  = {k: int(v) for k, v in sport_yest.items()  if k and k != "(none)"}
sources     = {k: int(v) for k, v in sources.items()     if k and k != "(none)"}
market_orders = {k: int(v) for k, v in market_orders.items()}

# ── Write output ──────────────────────────────────────────────────────────────
output = {
    "lastUpdated":    now.isoformat(),
    "totalOrders":    total_orders,
    "tradeVolume":    trade_volume,
    "sportShare":     sport_today,
    "sportShareYest": sport_yest,
    "marketTypes":    market_orders,
    "sources":        sources,
    "topEventsToday": top_events_today,
    "topEventsWeek":  top_events_week,
    "eventsByName":   events_by_name,
}

out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
with open(out_path, "w") as f:
    json.dump(output, f, indent=2)

print(f"✅  Wrote data.json  ({total_orders:,} orders  /  ${trade_volume:,.0f} volume)")
