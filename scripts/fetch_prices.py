"""
Fetches fuel prices from FuelWatch WA.
- data/prices.json  → Perth (6000) default area prices + history
- data/by_suburb.json → per-suburb prices for ALL Perth metro suburbs (for location lookup)
Run by GitHub Actions.
"""
import requests
import xml.etree.ElementTree as ET
import json
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ── Default area (Perth / 6000) ──────────────────────────────────────────────
DEFAULT_SUBURBS = ['PERTH']

# ── All Perth metro suburbs for location-based lookup ────────────────────────
ALL_METRO_SUBURBS = [
    # Inner Perth / CBD
    'PERTH', 'NORTHBRIDGE', 'EAST PERTH', 'WEST PERTH', 'HIGHGATE',
    'LEEDERVILLE', 'NORTH PERTH', 'MT LAWLEY', 'INGLEWOOD', 'MAYLANDS',
    'SUBIACO', 'SHENTON PARK', 'DAGLISH', 'JOLIMONT', 'WEMBLEY',
    'FLOREAT', 'CITY BEACH', 'NEDLANDS', 'CRAWLEY', 'CLAREMONT',
    'COTTESLOE', 'MOSMAN PARK', 'PEPPERMINT GROVE', 'DALKEITH',
    'MOUNT PLEASANT', 'ARDROSS', 'APPLECROSS', 'BOORAGOON',
    # North Inner
    'GLENDALOUGH', 'OSBORNE PARK', 'INNALOO', 'KARRINYUP', 'BALCATTA',
    'STIRLING', 'GWELUP', 'HAMERSLEY', 'DUNCRAIG', 'WARWICK',
    'GREENWOOD', 'KINGSLEY', 'WOODVALE', 'HILLARYS', 'PADBURY',
    'CRAIGIE', 'OCEAN REEF', 'HEATHRIDGE', 'EDGEWATER',
    # North
    'JOONDALUP', 'CURRAMBINE', 'CONNOLLY', 'BELDON', 'MULLALOO',
    'MARMION', 'NORTH BEACH', 'WATERMANS BAY', 'SORRENTO',
    'WANGARA', 'LANDSDALE', 'MADELEY', 'DARCH', 'MARANGAROO',
    'GIRRAWHEEN', 'KOONDOOLA', 'NOLLAMARA', 'WESTMINSTER', 'BALGA',
    'MIRRABOOKA', 'WANNEROO', 'PEARSALL', 'HOCKING', 'TAPPING',
    'SINAGRA', 'ASHBY', 'BUTLER', 'RIDGEWOOD', 'BANKSIA GROVE',
    'CLARKSON', 'MINDARIE', 'QUINNS ROCKS', 'MERRIWA',
    'TWO ROCKS', 'YANCHEP', 'ALKIMOS', 'EGLINTON',
    # Northeast
    'MORLEY', 'NORANDA', 'BEECHBORO', 'BALLAJURA', 'MALAGA',
    'BAYSWATER', 'BASSENDEAN', 'EDEN HILL', 'EMBLETON', 'BEDFORD',
    'DIANELLA', 'TUART HILL', 'YOKINE', 'COOLBINIA',
    'GUILDFORD', 'SOUTH GUILDFORD', 'WOODBRIDGE', 'CAVERSHAM',
    'HENLEY BROOK', 'UPPER SWAN', 'MIDDLE SWAN', 'SWAN VIEW',
    'MIDLAND', 'MIDVALE', 'BELLEVUE', 'HAZELMERE', 'REDCLIFFE',
    'ELLENBROOK', 'BRABHAM', 'DAYTON', 'AVELEY',
    # East
    'BELMONT', 'CLOVERDALE', 'RIVERVALE', 'ASCOT', 'REDCLIFFE',
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
    'THORNLIE', 'SOUTHERN RIVER', 'GOSNELLS', 'HUNTINGDALE',
    'CAMILLO', 'SEVILLE GROVE', 'KELMSCOTT', 'ARMADALE',
    'BYFORD', 'MUNDIJONG', 'OAKFORD', 'CARDUP', 'SERPENTINE',
    'PIARA WATERS', 'HARRISDALE', 'HILBERT',
    # South (Cockburn / Aubin Grove)
    'COCKBURN CENTRAL', 'SUCCESS', 'HAMMOND PARK', 'AUBIN GROVE',
    'TREEBY', 'ATWELL', 'BANJUP', 'MUNSTER', 'BEELIAR',
    'SPEARWOOD', 'HAMILTON HILL', 'COOLBELLUP',
    # Fremantle / Coast
    'FREMANTLE', 'EAST FREMANTLE', 'NORTH FREMANTLE', 'WHITE GUM VALLEY',
    'BEACONSFIELD', 'HILTON', 'PALMYRA', 'BICTON', 'ATTADALE',
    'MELVILLE', 'MYAREE', 'O CONNOR', 'SOLOMON', 'ALFRED COVE',
    'COOGEE', 'NORTH COOGEE', 'PORT KENNEDY',
    # Rockingham / Kwinana
    'ROCKINGHAM', 'SAFETY BAY', 'WAIKIKI', 'SHOALWATER',
    'NAVAL BASE', 'PARMELIA', 'LEDA', 'WANDI', 'MEDINA',
    'KWINANA', 'ORELIA', 'CALISTA', 'HILLMAN', 'BERTRAM',
    'SECRET HARBOUR', 'GOLDEN BAY', 'SINGLETON',
    'BALDIVIS', 'STAKEHILL', 'POSTANS',
    # Mandurah
    'MANDURAH', 'MEADOW SPRINGS', 'GREENFIELDS', 'HALLS HEAD',
    'MADORA BAY', 'ERSKINE', 'DUDLEY PARK', 'FALCON', 'DAWESVILLE',
]

FUEL_TYPES = {'1': 'Unleaded 91', '2': 'Premium 95'}
FUELWATCH_RSS = 'https://www.fuelwatch.wa.gov.au/fuelwatch/fuelWatchRSS'
DATA_DIR = Path(__file__).parent.parent / 'data'


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

    (DATA_DIR / 'by_suburb.json').write_text(json.dumps(by_suburb, indent=2))
    print(f'by_suburb.json saved — {len(by_suburb)} suburbs.')

    # Summary
    for name, data in result.items():
        td = data['today']
        if td:
            print(f"  {name}: {td['min']}c/L min, {td['count']} stations")


if __name__ == '__main__':
    main()
