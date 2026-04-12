"""
Fetches fuel prices from FuelWatch WA.
- data/prices.json  → Perth (6000) default area prices + history
- data/by_suburb.json → per-suburb prices for ALL Perth metro suburbs (for location lookup)
Run by GitHub Actions.
"""
import requests
import xml.etree.ElementTree as ET
import json
import math
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ── Default area (Perth / 6000) ──────────────────────────────────────────────
DEFAULT_SUBURBS = ['PERTH']

# ── All Perth metro suburbs for location-based lookup ────────────────────────
ALL_METRO_SUBURBS = [
    # Inner Perth / CBD
    'PERTH', 'NORTHBRIDGE', 'EAST PERTH', 'WEST PERTH', 'HIGHGATE',
    'LEEDERVILLE', 'NORTH PERTH', 'MOUNT LAWLEY', 'INGLEWOOD', 'MAYLANDS',
    'SUBIACO', 'SHENTON PARK', 'DAGLISH', 'JOLIMONT', 'WEMBLEY',
    'FLOREAT', 'CITY BEACH', 'NEDLANDS', 'CRAWLEY', 'CLAREMONT',
    'COTTESLOE', 'MOSMAN PARK', 'PEPPERMINT GROVE', 'DALKEITH',
    'MOUNT PLEASANT', 'ARDROSS', 'APPLECROSS', 'BOORAGOON',
    'SOUTH PERTH', 'BURSWOOD', 'KENSINGTON', 'QUEENS PARK',
    # North Inner
    'GLENDALOUGH', 'OSBORNE PARK', 'INNALOO', 'KARRINYUP', 'BALCATTA',
    'STIRLING', 'GWELUP', 'HAMERSLEY', 'DUNCRAIG', 'WARWICK',
    'GREENWOOD', 'KINGSLEY', 'WOODVALE', 'HILLARYS', 'PADBURY',
    'CRAIGIE', 'OCEAN REEF', 'HEATHRIDGE', 'EDGEWATER',
    'MOUNT HAWTHORN', 'SCARBOROUGH', 'DOUBLEVIEW', 'CHURCHLANDS',
    'WEMBLEY DOWNS', 'TRIGG', 'NORTH BEACH',
    # North
    'JOONDALUP', 'CURRAMBINE', 'CONNOLLY', 'BELDON', 'MULLALOO',
    'MARMION', 'WATERMANS BAY', 'SORRENTO',
    'WANGARA', 'LANDSDALE', 'MADELEY', 'DARCH', 'MARANGAROO',
    'GIRRAWHEEN', 'KOONDOOLA', 'NOLLAMARA', 'WESTMINSTER', 'BALGA',
    'MIRRABOOKA', 'WANNEROO', 'PEARSALL', 'HOCKING', 'TAPPING',
    'SINAGRA', 'ASHBY', 'BUTLER', 'RIDGEWOOD', 'BANKSIA GROVE',
    'CLARKSON', 'MINDARIE', 'QUINNS ROCKS', 'MERRIWA',
    'TWO ROCKS', 'YANCHEP', 'ALKIMOS', 'EGLINTON',
    'BURNS BEACH', 'ILUKA', 'JINDALEE',
    # Northeast
    'MORLEY', 'NORANDA', 'BEECHBORO', 'BALLAJURA', 'MALAGA',
    'BAYSWATER', 'BASSENDEAN', 'EDEN HILL', 'EMBLETON', 'BEDFORD',
    'DIANELLA', 'TUART HILL', 'YOKINE', 'COOLBINIA',
    'GUILDFORD', 'SOUTH GUILDFORD', 'WOODBRIDGE', 'CAVERSHAM',
    'HENLEY BROOK', 'UPPER SWAN', 'MIDDLE SWAN', 'SWAN VIEW',
    'MIDLAND', 'MIDVALE', 'BELLEVUE', 'HAZELMERE', 'REDCLIFFE',
    'ELLENBROOK', 'BRABHAM', 'DAYTON', 'AVELEY',
    'JANE BROOK', 'BULLSBROOK', 'GNANGARA',
    # Hills
    'KALAMUNDA', 'FORRESTFIELD', 'HIGH WYCOMBE', 'MAIDA VALE',
    'WATTLE GROVE', 'LESMURDIE', 'PICKERING BROOK', 'BICKLEY',
    'MUNDARING', 'GLEN FORREST', 'SAWYERS VALLEY', 'PARKERVILLE',
    'CHIDLOW', 'STONEVILLE', 'MOUNT HELENA', 'DARLINGTON',
    # East
    'BELMONT', 'CLOVERDALE', 'RIVERVALE', 'ASCOT',
    'WELSHPOOL', 'ST JAMES', 'VICTORIA PARK', 'EAST VICTORIA PARK',
    'CARLISLE', 'LATHLAIN', 'BENTLEY', 'COMO', 'KARAWARA',
    'MANNING', 'SALTER POINT', 'WATERFORD', 'SHELLEY', 'ROSSMOYNE',
    'BULL CREEK', 'LEEMING', 'MURDOCH', 'WINTHROP', 'KARDINYA',
    'SOUTH LAKE', 'NORTH LAKE', 'BIBRA LAKE', 'YANGEBUP',
    'FORRESTDALE', 'JANDAKOT',
    # Southeast
    'CANNINGTON', 'BECKENHAM', 'FERNDALE', 'KENWICK', 'MADDINGTON',
    'ORANGE GROVE', 'MARTIN', 'CANNING VALE', 'WILLETTON',
    'RIVERTON', 'PARKWOOD', 'LYNWOOD', 'LANGFORD', 'HUNTINGDALE',
    'THORNLIE', 'SOUTHERN RIVER', 'GOSNELLS',
    'CAMILLO', 'SEVILLE GROVE', 'KELMSCOTT', 'ARMADALE',
    'BYFORD', 'MUNDIJONG', 'OAKFORD', 'CARDUP', 'SERPENTINE',
    'PIARA WATERS', 'HARRISDALE', 'HILBERT',
    'BROOKDALE', 'CHAMPION LAKES', 'WUNGONG', 'BEDFORDALE', 'ROLEYSTONE',
    # South (Cockburn / Aubin Grove)
    'COCKBURN CENTRAL', 'SUCCESS', 'HAMMOND PARK', 'AUBIN GROVE',
    'TREEBY', 'ATWELL', 'BANJUP', 'MUNSTER', 'BEELIAR',
    'SPEARWOOD', 'HAMILTON HILL', 'COOLBELLUP',
    # Fremantle / Coast
    'FREMANTLE', 'EAST FREMANTLE', 'NORTH FREMANTLE', 'SOUTH FREMANTLE',
    'WHITE GUM VALLEY', 'BEACONSFIELD', 'HILTON', 'PALMYRA', 'BICTON',
    'ATTADALE', 'MELVILLE', 'MYAREE', "O'CONNOR", 'ALFRED COVE',
    'COOGEE', 'NORTH COOGEE',
    # Rockingham / Kwinana
    'ROCKINGHAM', 'SAFETY BAY', 'WAIKIKI', 'SHOALWATER', 'WARNBRO',
    'NAVAL BASE', 'PARMELIA', 'LEDA', 'WANDI', 'MEDINA',
    'KWINANA', 'ORELIA', 'CALISTA', 'HILLMAN', 'BERTRAM',
    'SECRET HARBOUR', 'GOLDEN BAY', 'SINGLETON', 'PORT KENNEDY',
    'BALDIVIS', 'STAKEHILL', 'POSTANS',
    # Mandurah
    'MANDURAH', 'MEADOW SPRINGS', 'GREENFIELDS', 'HALLS HEAD',
    'MADORA BAY', 'ERSKINE', 'DUDLEY PARK', 'FALCON', 'DAWESVILLE',
    'WANNANUP', 'BOUVARD', 'HERRON', 'NORTH DANDALUP',
]

FUEL_TYPES = {'1': 'Unleaded 91', '2': 'Premium 95'}
FUELWATCH_RSS = 'https://www.fuelwatch.wa.gov.au/fuelwatch/fuelWatchRSS'
DATA_DIR = Path(__file__).parent.parent / 'data'

# Fallback centroids for suburbs FuelWatch doesn't recognise (returns 0 stations)
# These ensure the distance gate still works for location/search
FALLBACK_CENTROIDS = {
    'Aubin Grove':    {'lat': -32.1480, 'lng': 115.8830},
    'Hammond Park':   {'lat': -32.1530, 'lng': 115.8610},
    'Treeby':         {'lat': -32.1400, 'lng': 115.8750},
    'Atwell':         {'lat': -32.1270, 'lng': 115.8490},
    'Banjup':         {'lat': -32.1700, 'lng': 115.8700},
    'Piara Waters':   {'lat': -32.1340, 'lng': 115.9140},
    'Harrisdale':     {'lat': -32.1256, 'lng': 115.9260},
    'Hilbert':        {'lat': -32.1500, 'lng': 115.9400},
    'Brookdale':      {'lat': -32.1750, 'lng': 115.9900},
    'Champion Lakes': {'lat': -32.1600, 'lng': 115.9600},
    'Wungong':        {'lat': -32.1850, 'lng': 115.9700},
    'Caversham':      {'lat': -31.8400, 'lng': 115.9700},
    'Brabham':        {'lat': -31.7700, 'lng': 115.9400},
    'Dayton':         {'lat': -31.7900, 'lng': 115.9500},
    'Aveley':         {'lat': -31.7800, 'lng': 116.0100},
    'Sinagra':        {'lat': -31.6900, 'lng': 115.7800},
    'Ashby':          {'lat': -31.6700, 'lng': 115.7700},
    'Ridgewood':      {'lat': -31.6600, 'lng': 115.7600},
    'Banksia Grove':  {'lat': -31.6800, 'lng': 115.8100},
    'Eglinton':       {'lat': -31.5300, 'lng': 115.7400},
    'Burns Beach':    {'lat': -31.6900, 'lng': 115.7300},
    'Iluka':          {'lat': -31.7100, 'lng': 115.7300},
    'Jindalee':       {'lat': -31.7300, 'lng': 115.7200},
    'Bedfordale':     {'lat': -32.2000, 'lng': 116.0200},
    'Roleystone':     {'lat': -32.1200, 'lng': 116.0700},
    'Warnbro':        {'lat': -32.3300, 'lng': 115.7600},
    'Wannanup':       {'lat': -32.6000, 'lng': 115.6800},
    'Bouvard':        {'lat': -32.6200, 'lng': 115.6600},
    'Herron':         {'lat': -32.5800, 'lng': 115.6700},
    'Lesmurdie':      {'lat': -32.0100, 'lng': 116.0400},
    'Mundaring':      {'lat': -31.9000, 'lng': 116.1700},
    'Glen Forrest':   {'lat': -31.9300, 'lng': 116.1200},
    'Sawyers Valley': {'lat': -31.9200, 'lng': 116.2100},
    'Parkerville':    {'lat': -31.8700, 'lng': 116.1400},
    'Chidlow':        {'lat': -31.8600, 'lng': 116.2700},
    'Stoneville':     {'lat': -31.8600, 'lng': 116.1700},
    'Churchlands':    {'lat': -31.9200, 'lng': 115.8100},
    'Wembley Downs':  {'lat': -31.9000, 'lng': 115.7900},
    'Doubleview':     {'lat': -31.9100, 'lng': 115.7900},
    'South Fremantle':{'lat': -32.0800, 'lng': 115.7500},
    'Kensington':     {'lat': -31.9900, 'lng': 115.8800},
    'Queens Park':    {'lat': -32.0000, 'lng': 115.9200},
    'Burswood':       {'lat': -31.9600, 'lng': 115.9000},
    'South Perth':    {'lat': -31.9800, 'lng': 115.8600},
    # Additional suburbs that may have 0 stations on high-price cycle days
    'Ardross':          {'lat': -32.0270, 'lng': 115.8570},
    'Beaconsfield':     {'lat': -32.0690, 'lng': 115.7550},
    'Bickley':          {'lat': -32.0200, 'lng': 116.0530},
    'Cardup':           {'lat': -32.2770, 'lng': 116.0470},
    'City Beach':       {'lat': -31.9310, 'lng': 115.7590},
    'Connolly':         {'lat': -31.7410, 'lng': 115.7500},
    'Coogee':           {'lat': -32.1160, 'lng': 115.7500},
    'Coolbellup':       {'lat': -32.0700, 'lng': 115.8060},
    'Coolbinia':        {'lat': -31.9270, 'lng': 115.8470},
    'Cottesloe':        {'lat': -31.9900, 'lng': 115.7550},
    'Craigie':          {'lat': -31.7750, 'lng': 115.7600},
    'Crawley':          {'lat': -31.9810, 'lng': 115.8200},
    'Daglish':          {'lat': -31.9430, 'lng': 115.8290},
    'Dalkeith':         {'lat': -31.9930, 'lng': 115.8120},
    'Darch':            {'lat': -31.7840, 'lng': 115.8050},
    'Darlington':       {'lat': -31.9130, 'lng': 116.0970},
    'Dudley Park':      {'lat': -32.5070, 'lng': 115.7260},
    'Eden Hill':        {'lat': -31.8820, 'lng': 116.0020},
    'Ferndale':         {'lat': -32.0240, 'lng': 115.9550},
    'Gnangara':         {'lat': -31.7910, 'lng': 115.8800},
    'Hamersley':        {'lat': -31.8480, 'lng': 115.8150},
    'Hazelmere':        {'lat': -31.8900, 'lng': 116.0370},
    'Heathridge':       {'lat': -31.7580, 'lng': 115.7600},
    'Highgate':         {'lat': -31.9360, 'lng': 115.8630},
    'Hillman':          {'lat': -32.2920, 'lng': 115.7450},
    'Hilton':           {'lat': -32.0410, 'lng': 115.7830},
    'Hocking':          {'lat': -31.7330, 'lng': 115.8180},
    'Inglewood':        {'lat': -31.9200, 'lng': 115.8720},
    'Jane Brook':       {'lat': -31.8300, 'lng': 116.0850},
    'Karrinyup':        {'lat': -31.8650, 'lng': 115.7750},
    'Kenwick':          {'lat': -32.0200, 'lng': 115.9870},
    'Kwinana':          {'lat': -32.2400, 'lng': 115.7700},
    'Lathlain':         {'lat': -31.9750, 'lng': 115.9070},
    'Madora Bay':       {'lat': -32.5760, 'lng': 115.7130},
    'Manning':          {'lat': -32.0140, 'lng': 115.8870},
    'Marangaroo':       {'lat': -31.8270, 'lng': 115.8450},
    'Marmion':          {'lat': -31.8360, 'lng': 115.7570},
    'Martin':           {'lat': -32.1150, 'lng': 116.0110},
    'Maylands':         {'lat': -31.9270, 'lng': 115.8880},
    'Medina':           {'lat': -32.2590, 'lng': 115.7600},
    'Melville':         {'lat': -32.0400, 'lng': 115.8000},
    'Mount Hawthorn':   {'lat': -31.9210, 'lng': 115.8420},
    'Mount Helena':     {'lat': -31.8790, 'lng': 116.1880},
    'Mount Lawley':     {'lat': -31.9280, 'lng': 115.8770},
    'North Beach':      {'lat': -31.8720, 'lng': 115.7540},
    'North Coogee':     {'lat': -32.1020, 'lng': 115.7500},
    'North Lake':       {'lat': -32.0680, 'lng': 115.8280},
    "O'Connor":         {'lat': -32.0640, 'lng': 115.7930},
    'Orange Grove':     {'lat': -32.0340, 'lng': 116.0110},
    'Orelia':           {'lat': -32.2580, 'lng': 115.7690},
    'Parkwood':         {'lat': -32.0270, 'lng': 115.9130},
    'Parmelia':         {'lat': -32.2490, 'lng': 115.7840},
    'Peppermint Grove': {'lat': -32.0010, 'lng': 115.7820},
    'Pickering Brook':  {'lat': -32.0300, 'lng': 116.0970},
    'Postans':          {'lat': -32.2180, 'lng': 115.7870},
    'Rossmoyne':        {'lat': -32.0430, 'lng': 115.8700},
    'Salter Point':     {'lat': -32.0120, 'lng': 115.8840},
    'Shelley':          {'lat': -32.0380, 'lng': 115.8930},
    'Shenton Park':     {'lat': -31.9560, 'lng': 115.8090},
    'South Guildford':  {'lat': -31.8930, 'lng': 115.9780},
    'St James':         {'lat': -31.9860, 'lng': 115.9010},
    'Stakehill':        {'lat': -32.1880, 'lng': 115.7700},
    'Stirling':         {'lat': -31.8630, 'lng': 115.8030},
    'Tapping':          {'lat': -31.7240, 'lng': 115.8090},
    'Trigg':            {'lat': -31.8870, 'lng': 115.7560},
    'Victoria Park':    {'lat': -31.9760, 'lng': 115.9060},
    'Wandi':            {'lat': -32.2090, 'lng': 115.8390},
    'Waterford':        {'lat': -32.0300, 'lng': 115.8970},
    'Watermans Bay':    {'lat': -31.8490, 'lng': 115.7550},
    'White Gum Valley': {'lat': -32.0480, 'lng': 115.7690},
    'Winthrop':         {'lat': -32.0660, 'lng': 115.8450},
}


def fetch_suburb(suburb, product, day):
    params = {'Product': product, 'Suburb': suburb, 'Day': day, 'Surrounding': '1'}
    try:
        resp = requests.get(FUELWATCH_RSS, params=params, timeout=15,
                            headers={'User-Agent': 'FuelWatch-GHPages/1.0'})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        stations = []
        for item in root.findall('.//item'):
            def get(tag, _item=item):
                el = _item.find(tag)
                return el.text.strip() if el is not None and el.text else ''
            price_str = get('price')
            if not price_str:
                continue
            try:
                stations.append({
                    'price': float(price_str),
                    'name':  get('trading-name'),
                    'brand': get('brand'),
                    'address': get('address'),
                    'suburb': get('location'),
                    'lat': get('latitude'),
                    'lng': get('longitude'),
                })
            except ValueError:
                pass
        return stations
    except Exception as e:
        return []


def dedup_sort(stations):
    seen = {}
    for s in stations:
        key = (s['name'], s['address'])
        if key not in seen:
            seen[key] = s
    return sorted(seen.values(), key=lambda x: x['price'])


def get_stations(suburbs, product, day):
    all_stations = []
    with ThreadPoolExecutor(max_workers=min(len(suburbs), 20)) as ex:
        futures = {ex.submit(fetch_suburb, s, product, day): s for s in suburbs}
        for f in as_completed(futures):
            all_stations.extend(f.result())
    return dedup_sort(all_stations)


def summarise(stations):
    if not stations:
        return None
    prices = [s['price'] for s in stations]
    return {
        'min':      min(prices),
        'avg':      round(sum(prices) / len(prices), 1),
        'max':      max(prices),
        'count':    len(stations),
        'cheapest': stations[0],
        'stations': stations[:15],
    }


def recommendation(today_min, tomorrow_min):
    if today_min is None or tomorrow_min is None:
        return None
    diff = round(tomorrow_min - today_min, 1)
    if diff <= -3:
        return {'action': 'wait', 'diff': diff, 'icon': '⏳',
                'text': f'Wait until tomorrow — prices drop {abs(diff)}c/L'}
    if diff >= 3:
        return {'action': 'fill', 'diff': diff, 'icon': '⛽',
                'text': f'Fill up today — prices rise {diff}c/L tomorrow'}
    return {'action': 'neutral', 'diff': diff, 'icon': '✓',
            'text': 'Prices are similar — fill up whenever suits you'}


def update_history(history, fuel_name, today_summary):
    if fuel_name not in history:
        history[fuel_name] = []
    today = date.today().isoformat()
    if not any(h['date'] == today for h in history[fuel_name]):
        history[fuel_name].append({
            'date':    today,
            'min':     today_summary['min'],
            'avg':     today_summary['avg'],
            'station': today_summary['cheapest']['name'],
            'suburb':  today_summary['cheapest']['suburb'],
        })
    history[fuel_name] = sorted(history[fuel_name], key=lambda h: h['date'])[-90:]


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    DATA_DIR.mkdir(exist_ok=True)
    history_path = DATA_DIR / 'history.json'
    history = json.loads(history_path.read_text()) if history_path.exists() else {}

    from datetime import timezone, timedelta
    AWST = timezone(timedelta(hours=8))
    fetched_at = datetime.now(AWST).strftime('%d %b %Y %H:%M AWST')

    # 1. Default area prices (today + tomorrow for both fuels)
    print('Fetching default area prices…')
    combos = [(code, name, day)
              for code, name in FUEL_TYPES.items()
              for day in ('today', 'tomorrow')]

    default_fetched = {}
    with ThreadPoolExecutor(max_workers=len(combos) * len(DEFAULT_SUBURBS)) as ex:
        futures = {ex.submit(get_stations, DEFAULT_SUBURBS, code, day): (name, day)
                   for code, name, day in combos}
        for f in as_completed(futures):
            name, day = futures[f]
            default_fetched[(name, day)] = f.result()

    result = {}
    for code, name in FUEL_TYPES.items():
        today_s    = summarise(default_fetched.get((name, 'today'), []))
        tomorrow_s = summarise(default_fetched.get((name, 'tomorrow'), []))
        if today_s:
            update_history(history, name, today_s)
        result[name] = {
            'today':          today_s,
            'tomorrow':       tomorrow_s,
            'recommendation': recommendation(today_s['min'] if today_s else None,
                                             tomorrow_s['min'] if tomorrow_s else None),
            'fetched_at':     fetched_at,
        }
    for name in result:
        result[name]['history'] = history.get(name, [])

    (DATA_DIR / 'prices.json').write_text(json.dumps(result, indent=2))
    history_path.write_text(json.dumps(history, indent=2))
    print('prices.json saved.')

    # 2. Per-suburb lookup (today only, both fuels) for location feature
    print(f'Fetching per-suburb data for {len(ALL_METRO_SUBURBS)} suburbs…')
    by_suburb = {}

    suburb_combos = [(suburb, code, name)
                     for suburb in ALL_METRO_SUBURBS
                     for code, name in FUEL_TYPES.items()]

    with ThreadPoolExecutor(max_workers=30) as ex:
        futures = {ex.submit(fetch_suburb, suburb, code, 'today'): (suburb, name)
                   for suburb, code, name in suburb_combos}
        for f in as_completed(futures):
            suburb, fuel_name = futures[f]
            stations = f.result()
            key = suburb.title()  # normalise: "COCKBURN CENTRAL" → "Cockburn Central"
            if key not in by_suburb:
                by_suburb[key] = {}
            s = summarise(stations)
            if s:
                by_suburb[key][fuel_name] = {
                    'min':      s['min'],
                    'avg':      s['avg'],
                    'max':      s['max'],
                    'count':    s['count'],
                    'stations': s['stations'],
                }
                # Compute centroid from this suburb's own stations (not surrounding)
                if '_centroid' not in by_suburb[key]:
                    own = [st for st in s['stations']
                           if st.get('suburb', '').upper() == suburb.upper()]
                    ref = own if own else s['stations']
                    clats = [float(st['lat']) for st in ref if st.get('lat')]
                    clngs = [float(st['lng']) for st in ref if st.get('lng')]
                    if clats:
                        by_suburb[key]['_centroid'] = {
                            'lat': round(sum(clats) / len(clats), 5),
                            'lng': round(sum(clngs) / len(clngs), 5),
                        }

    # Also fetch tomorrow for the by_suburb data
    with ThreadPoolExecutor(max_workers=30) as ex:
        futures = {ex.submit(fetch_suburb, suburb, code, 'tomorrow'): (suburb, name)
                   for suburb, code, name in suburb_combos}
        for f in as_completed(futures):
            suburb, fuel_name = futures[f]
            stations = f.result()
            key = suburb.title()
            if key not in by_suburb:
                by_suburb[key] = {}
            s = summarise(stations)
            if s:
                fuel_key = fuel_name + '_tomorrow'
                by_suburb[key][fuel_key] = {
                    'min':      s['min'],
                    'avg':      s['avg'],
                    'max':      s['max'],
                    'count':    s['count'],
                    'stations': s['stations'],
                }

    # Apply fallback centroids for suburbs FuelWatch doesn't recognise (0 stations returned)
    # Without a centroid, the 20 km distance gate in the front-end can't filter correctly
    for suburb_title, centroid in FALLBACK_CENTROIDS.items():
        if suburb_title in by_suburb and '_centroid' not in by_suburb[suburb_title]:
            by_suburb[suburb_title]['_centroid'] = centroid

    # 3. Per-suburb price history — mirrors the frontend fill logic so that
    #    suburbs with no direct data (Aubin Grove etc.) track the min price
    #    from their actual catchment area (15 km radius for fill-only suburbs,
    #    5 km for recognised suburbs), not just the global Perth average.
    def haversine_km(lat1, lng1, lat2, lng2):
        R = 6371
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
             * math.sin(dlng / 2) ** 2)
        return R * 2 * math.asin(math.sqrt(a))

    def effective_fuel_data(key, entry, fuel_name):
        """Return {min, avg} for a suburb using the same fill logic as the frontend."""
        direct = entry.get(fuel_name)
        if direct:
            return direct
        # Fill-only suburb: aggregate stations from surrounding suburbs
        centroid = entry.get('_centroid')
        if not centroid:
            return None
        has_own_data = any(entry.get(fn) for fn in FUEL_TYPES.values())
        fill_km = 5 if has_own_data else 15
        seen, prices = set(), []
        for other_key, other_entry in by_suburb.items():
            if other_key == key:
                continue
            other_c = other_entry.get('_centroid')
            if not other_c:
                continue
            if haversine_km(centroid['lat'], centroid['lng'],
                            other_c['lat'], other_c['lng']) > fill_km:
                continue
            for st in other_entry.get(fuel_name, {}).get('stations', []):
                uid = (st['name'], st.get('address', ''))
                if uid not in seen:
                    seen.add(uid)
                    prices.append(st['price'])
        if not prices:
            return None
        return {'min': min(prices), 'avg': round(sum(prices) / len(prices), 1)}

    suburb_history_path = DATA_DIR / 'suburb_history.json'
    suburb_history = (json.loads(suburb_history_path.read_text())
                      if suburb_history_path.exists() else {})
    today_str = date.today().isoformat()

    for key, entry in by_suburb.items():
        for fuel_name in FUEL_TYPES.values():
            fuel_data = effective_fuel_data(key, entry, fuel_name)
            if not fuel_data:
                continue
            suburb_history.setdefault(key, {}).setdefault(fuel_name, [])
            hist = suburb_history[key][fuel_name]
            if not any(h['date'] == today_str for h in hist):
                hist.append({'date': today_str, 'min': fuel_data['min'], 'avg': fuel_data['avg']})
            suburb_history[key][fuel_name] = sorted(hist, key=lambda h: h['date'])[-90:]
        if key in suburb_history:
            by_suburb[key]['_history'] = suburb_history[key]

    suburb_history_path.write_text(json.dumps(suburb_history, indent=2))
    (DATA_DIR / 'by_suburb.json').write_text(json.dumps(by_suburb, indent=2))
    print(f'by_suburb.json saved — {len(by_suburb)} suburbs.')

    # Summary
    for name, data in result.items():
        td = data['today']
        if td:
            print(f"  {name}: {td['min']}c/L min, {td['count']} stations")


if __name__ == '__main__':
    main()
