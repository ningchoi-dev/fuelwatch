from flask import Flask, jsonify, render_template
import requests
import xml.etree.ElementTree as ET
import sqlite3
from datetime import datetime, date
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import socket
import time
import os

_root = Path(os.environ.get('APP_ROOT', str(Path(__file__).parent)))
app = Flask(__name__,
            template_folder=str(_root / 'templates'),
            static_folder=str(_root / 'static'))

DB_PATH = Path(os.environ.get('DB_PATH', str(_root / 'fuel_prices.db')))

# Cockburn Central + Surrounding=1 already covers most stations.
# Hammond Park catches the southern fringe near Aubin Grove.
SUBURBS = [
    'COCKBURN CENTRAL',
    'HAMMOND PARK',
    'JANDAKOT',
    'SUCCESS',
    'SOUTH LAKE',
    'MUNSTER',
    'SPEARWOOD',
    'HAMILTON HILL',
]

FUEL_TYPES = {
    '1': 'Unleaded 91',
    '2': 'Premium 95',
}

FUELWATCH_RSS = 'https://www.fuelwatch.wa.gov.au/fuelwatch/fuelWatchRSS'

# In-memory cache: stores result per calendar date
_cache: dict = {}
CACHE_TTL = 1800  # 30 minutes — refresh mid-day if needed


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                fuel_type TEXT NOT NULL,
                min_price REAL,
                avg_price REAL,
                cheapest_station TEXT,
                cheapest_suburb TEXT,
                UNIQUE(date, fuel_type)
            )
        ''')
        conn.commit()
        conn.close()
    except Exception:
        pass  # read-only filesystem (e.g. Vercel) — history disabled


def fetch_suburb_prices(suburb, product, day):
    params = {
        'Product': product,
        'Suburb': suburb,
        'Day': day,
        'Surrounding': '1',
    }
    try:
        resp = requests.get(
            FUELWATCH_RSS, params=params, timeout=10,
            headers={'User-Agent': 'FuelWatch-App/1.0'}
        )
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
                price = float(price_str)
            except ValueError:
                continue

            stations.append({
                'price': price,
                'name': get('trading-name'),
                'brand': get('brand'),
                'address': get('address'),
                'suburb': get('location'),
                'phone': get('phone'),
                'features': get('site-features'),
                'lat': get('latitude'),
                'lng': get('longitude'),
            })
        return stations
    except Exception:
        return []


def get_all_stations_parallel(product, day):
    seen = {}
    tasks = [(s, product, day) for s in SUBURBS]
    with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
        futures = {ex.submit(fetch_suburb_prices, s, p, d): (s, p, d)
                   for s, p, d in tasks}
        for future in as_completed(futures):
            for station in future.result():
                key = (station['name'], station['address'])
                if key not in seen:
                    seen[key] = station
    return sorted(seen.values(), key=lambda x: x['price'])


def fetch_all_parallel():
    """Fetch all 4 combinations (2 fuels × today/tomorrow) concurrently."""
    combos = [(code, name, day)
              for code, name in FUEL_TYPES.items()
              for day in ('today', 'tomorrow')]
    results = {}
    with ThreadPoolExecutor(max_workers=len(combos) * len(SUBURBS)) as ex:
        futures = {
            ex.submit(get_all_stations_parallel, code, day): (name, day)
            for code, name, day in combos
        }
        for future in as_completed(futures):
            name, day = futures[future]
            results[(name, day)] = future.result()
    return results


def store_today_prices(fuel_type_name, stations):
    if not stations:
        return
    today = date.today().isoformat()
    prices = [s['price'] for s in stations]
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute('''
            INSERT OR IGNORE INTO price_history
            (date, fuel_type, min_price, avg_price, cheapest_station, cheapest_suburb)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (today, fuel_type_name,
              min(prices),
              round(sum(prices) / len(prices), 1),
              stations[0]['name'],
              stations[0]['suburb']))
        conn.commit()
        conn.close()
    except Exception:
        pass  # read-only filesystem — silently skip


def get_history(fuel_type_name, limit=60):
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute('''
            SELECT date, min_price, avg_price, cheapest_station, cheapest_suburb
            FROM price_history
            WHERE fuel_type = ?
            ORDER BY date ASC
            LIMIT ?
        ''', (fuel_type_name, limit)).fetchall()
        conn.close()
        return [{'date': r[0], 'min': r[1], 'avg': r[2],
                 'station': r[3], 'suburb': r[4]} for r in rows]
    except Exception:
        return []


def summarise(stations):
    if not stations:
        return None
    prices = [s['price'] for s in stations]
    return {
        'min': min(prices),
        'avg': round(sum(prices) / len(prices), 1),
        'max': max(prices),
        'count': len(stations),
        'cheapest': stations[0],
        'stations': stations[:15],
    }


def recommendation(today_min, tomorrow_min):
    if today_min is None or tomorrow_min is None:
        return None
    diff = round(tomorrow_min - today_min, 1)
    if diff <= -3:
        return {'action': 'wait', 'diff': diff,
                'text': f'Wait until tomorrow — prices drop {abs(diff)}c/L',
                'icon': '⏳'}
    elif diff >= 3:
        return {'action': 'fill', 'diff': diff,
                'text': f'Fill up today — prices rise {diff}c/L tomorrow',
                'icon': '⛽'}
    return {'action': 'neutral', 'diff': diff,
            'text': 'Prices are similar — fill up whenever suits you',
            'icon': '✓'}


init_db()  # runs on every worker start (safe — CREATE IF NOT EXISTS)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/prices')
def prices():
    from flask import request as flask_request
    cache_key = date.today().isoformat()
    now = time.time()
    force = flask_request.args.get('force') == '1'

    if not force and cache_key in _cache:
        ts, cached = _cache[cache_key]
        if now - ts < CACHE_TTL:
            return jsonify(cached)

    fetched = fetch_all_parallel()

    result = {}
    for code, name in FUEL_TYPES.items():
        today_stations = fetched.get((name, 'today'), [])
        tomorrow_stations = fetched.get((name, 'tomorrow'), [])

        store_today_prices(name, today_stations)

        today_sum = summarise(today_stations)
        tomorrow_sum = summarise(tomorrow_stations)

        result[name] = {
            'today': today_sum,
            'tomorrow': tomorrow_sum,
            'recommendation': recommendation(
                today_sum['min'] if today_sum else None,
                tomorrow_sum['min'] if tomorrow_sum else None,
            ),
            'history': get_history(name),
            'fetched_at': datetime.now().strftime('%d %b %Y, %I:%M %p'),
        }

    _cache[cache_key] = (now, result)
    return jsonify(result)


if __name__ == '__main__':
    init_db()
    ip = get_local_ip()
    print(f'\n  Local:   http://127.0.0.1:5001')
    print(f'  iPhone:  http://{ip}:5001\n')
    app.run(host='0.0.0.0', debug=False, port=5001)
