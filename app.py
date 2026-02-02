from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import time
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
import json
import os
import urllib.parse
import urllib.request
from werkzeug.security import generate_password_hash, check_password_hash
try:
    import resource
except Exception:
    resource = None
import traceback

app = Flask(__name__)
@app.route("/health")
def health():
    return "ok", 200

app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-12345')
app.config['JSON_AS_ASCII'] = False

@app.before_request
def _t0():
    from flask import g
    g._start = time.time()
    if os.getenv("LOG_REQS", "0") == "1":
        print(f"REQ {request.method} {request.path}", flush=True)

@app.after_request
def _t1(resp):
    from flask import g, request
    dt = time.time() - getattr(g, "_start", time.time())
    if dt > 2.0:
        print(f"SLOW {dt:.2f}s {request.method} {request.path}", flush=True)
    return resp

@app.after_request
def add_charset(response):
    if response.mimetype == 'text/html':
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
    if response.mimetype == 'application/json':
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
    return response

def _mem_mb():
    if resource is None:
        return 0.0
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024

@app.after_request
def _log_mem(resp):
    if os.getenv("LOG_MEM", "0") == "1":
        print(f"MEM {_mem_mb():.1f} MB {resp.status_code} {resp.content_length or 0}B", flush=True)
    return resp

DATA_DIR = os.environ.get('DATA_DIR')
if not DATA_DIR:
    if os.path.isdir('/var/data'):
        DATA_DIR = '/var/data'
    else:
        DATA_DIR = '.'
DB_URL = os.environ.get('DATABASE_URL', '').strip()
USE_DB = bool(DB_URL)

def data_path(filename):
    return os.path.join(DATA_DIR, filename)

if DATA_DIR and DATA_DIR not in ['.', './']:
    os.makedirs(DATA_DIR, exist_ok=True)

_DB_READY = False
_DB_POOL = None
_CACHE = {}
_WEATHER_CACHE = {'ts': 0, 'data': None}
ORDERS_CACHE_TTL = int(os.environ.get('ORDERS_CACHE_TTL', '10'))
MENU_CACHE_TTL = int(os.environ.get('MENU_CACHE_TTL', '60'))
TABLES_CACHE_TTL = int(os.environ.get('TABLES_CACHE_TTL', '60'))
REHBER_CACHE_TTL = int(os.environ.get('REHBER_CACHE_TTL', '60'))
DB_CONNECT_TIMEOUT = int(os.environ.get('DB_CONNECT_TIMEOUT', '5'))
DB_STATEMENT_TIMEOUT_MS = int(os.environ.get('DB_STATEMENT_TIMEOUT_MS', '5000'))

def cached_load(key, loader, ttl_seconds):
    now = time.time()
    cached = _CACHE.get(key)
    if cached:
        ts, data = cached
        if now - ts < ttl_seconds:
            return data
    data = loader()
    _CACHE[key] = (now, data)
    return data

def invalidate_cache(key):
    _CACHE.pop(key, None)

def init_db_pool():
    global _DB_POOL
    if _DB_POOL is not None or not USE_DB:
        return
    try:
        import psycopg2  # noqa: F401
        from psycopg2.pool import ThreadedConnectionPool
    except Exception as e:
        raise RuntimeError(f"psycopg2 import failed: {e}")
    db_url = os.getenv('DATABASE_URL', '').strip()
    if not db_url:
        return
    minconn = int(os.environ.get('DB_POOL_MIN', '1'))
    maxconn = int(os.environ.get('DB_POOL_MAX', '5'))
    _DB_POOL = ThreadedConnectionPool(
        minconn=minconn,
        maxconn=maxconn,
        dsn=db_url,
        sslmode=os.environ.get('DB_SSLMODE', 'require'),
        connect_timeout=DB_CONNECT_TIMEOUT,
        options=f"-c statement_timeout={DB_STATEMENT_TIMEOUT_MS}"
    )

def get_db_conn():
    init_db_pool()
    if _DB_POOL is None:
        return None
    return _DB_POOL.getconn()

def release_db_conn(conn, close=False):
    if not _DB_POOL or not conn:
        return
    if close:
        try:
            _DB_POOL.putconn(conn, close=True)
        except TypeError:
            conn.close()
        return
    _DB_POOL.putconn(conn)

def ensure_kv_table():
    global _DB_READY
    if _DB_READY or not USE_DB:
        return
    conn = get_db_conn()
    if conn is None:
        return
    cur = conn.cursor()
    cur.execute("""
        create table if not exists kv_store (
            key text primary key,
            data text,
            updated_at timestamptz default now()
        )
    """)
    cur.execute("create index if not exists kv_store_key_idx on kv_store(key)")
    conn.commit()
    cur.close()
    release_db_conn(conn)
    _DB_READY = True

def storage_has_key(key):
    if USE_DB:
        ensure_kv_table()
        conn = get_db_conn()
        if conn is None:
            return False
        cur = conn.cursor()
        cur.execute("select 1 from kv_store where key = %s", (key,))
        row = cur.fetchone()
        cur.close()
        release_db_conn(conn)
        return row is not None
    return os.path.exists(data_path(key))

def load_json_storage(key, default):
    if USE_DB:
        ensure_kv_table()
        try:
            import psycopg2
        except Exception:
            psycopg2 = None
        for attempt in (1, 2):
            conn = None
            try:
                conn = get_db_conn()
                if conn is None:
                    return default
                cur = conn.cursor()
                cur.execute("select data from kv_store where key = %s", (key,))
                row = cur.fetchone()
                cur.close()
                release_db_conn(conn)
                if not row or row[0] is None:
                    return default
                try:
                    return json.loads(row[0])
                except Exception:
                    return default
            except Exception as e:
                if psycopg2 and isinstance(e, psycopg2.OperationalError):
                    if conn:
                        try:
                            release_db_conn(conn, close=True)
                        except Exception:
                            pass
                    if attempt == 2:
                        raise
                    continue
                raise
    try:
        with open(data_path(key), 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default

def save_json_storage(key, data):
    if USE_DB:
        ensure_kv_table()
        conn = get_db_conn()
        if conn is None:
            return
        cur = conn.cursor()
        payload = json.dumps(data, ensure_ascii=False)
        cur.execute("""
            insert into kv_store (key, data, updated_at)
            values (%s, %s, now())
            on conflict (key) do update set data = excluded.data, updated_at = now()
        """, (key, payload))
        conn.commit()
        cur.close()
        release_db_conn(conn)
        return
    with open(data_path(key), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

ORDERS_FILE = 'orders.json'
MENU_FILE = 'menu.json'
TABLES_FILE = 'tables.json'
REHBER_FILE = 'rehber_masalar.json'
TABLES_LAYOUT_FILE = 'tables_layout.json'
TABLE_SESSIONS_FILE = 'table_sessions.json'
TABLE_USAGE_FILE = 'table_usage.json'
TABLE_BILL_REQUEST_FILE = 'table_bill_requests.json'
ATTENDANCE_FILE = 'vardiya.json'
ATTENDANCE_CONFIG_FILE = 'vardiya_config.json'
EMPLOYEES_FILE = 'calisanlar.json'
STAFF_FILE = 'staff.json'
TIP_FILE = 'tip_havuzu.json'
EXPENSES_FILE = 'giderler.json'
CONFIG_FILE = 'config.json'
PAYMENTS_FILE = 'payments.json'
OTOPARK_CONFIG_FILE = 'otopark_config.json'
TABLE_DISCOUNTS_FILE = 'table_discounts.json'
CLOSED_CHECKS_FILE = 'closed_checks.json'
CLOSED_CHECK_ITEMS_FILE = 'closed_check_items.json'
ACTIVITY_LOG_FILE = 'activity_log.json'
STAFF_CACHE_TTL = int(os.environ.get('STAFF_CACHE_TTL', '60'))
PRINTER_NAME = os.environ.get('PRINTER_NAME')
KITCHEN_PRINTER_NAME = os.environ.get('KITCHEN_PRINTER_NAME')
KITCHEN_PRINTER_ENABLED = os.environ.get('KITCHEN_PRINTER_ENABLED', '0') == '1'
KITCHEN_PRINT_MODE = os.environ.get('KITCHEN_PRINT_MODE', 'printer')  # printer | console | queue
PRINT_AGENT_TOKEN = os.environ.get('PRINT_AGENT_TOKEN', '2024Family').strip()
PRINT_QUEUE_MAX = int(os.environ.get('PRINT_QUEUE_MAX', '500'))
WEATHER_API_KEY = os.environ.get('WEATHER_API_KEY', '55d81da9d6c54f39ae3222425262301')
WEATHER_LOCATION = os.environ.get('WEATHER_LOCATION', 'Istanbul Sisli')
WEATHER_TTL = int(os.environ.get('WEATHER_TTL', '600'))

def fetch_weather():
    now = time.time()
    cached = _WEATHER_CACHE.get('data')
    if cached and (now - _WEATHER_CACHE.get('ts', 0)) < WEATHER_TTL:
        return cached
    if not WEATHER_API_KEY:
        return None
    query = urllib.parse.urlencode({
        "key": WEATHER_API_KEY,
        "q": WEATHER_LOCATION,
        "lang": "tr",
    })
    url = f"https://api.weatherapi.com/v1/current.json?{query}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        current = payload.get("current", {}) if isinstance(payload, dict) else {}
        condition = current.get("condition", {}) if isinstance(current, dict) else {}
        icon = condition.get("icon") or ""
        if icon.startswith("//"):
            icon = "https:" + icon
        data = {
            "temp": current.get("temp_c"),
            "condition": condition.get("text") or "",
            "icon": icon,
        }
        _WEATHER_CACHE["ts"] = now
        _WEATHER_CACHE["data"] = data
        return data
    except Exception as e:
        print(f"WEATHER_ERROR: {e!r}", flush=True)
        return None

@app.route("/api/weather")
def api_weather():
    data = fetch_weather()
    if not data:
        return jsonify({"temp": None, "condition": "", "icon": ""})
    return jsonify(data)

# -----------------------------
# Print Queue (for "agent" mode)
# -----------------------------
#
# Render cannot print to a USB/LAN printer in your shop. In "queue" mode we enqueue
# printable jobs here, and a shop-PC agent pulls and prints them locally.
#
# Storage: kv_store rows with key prefix "print_job:" so we don't need a new table.

def _require_agent_token():
    if not PRINT_AGENT_TOKEN:
        return False
    token = request.headers.get('X-Agent-Token', '')
    return token and token == PRINT_AGENT_TOKEN

def _now_iso():
    return datetime.now(ZoneInfo("Europe/Istanbul")).isoformat()

def _list_print_jobs(limit=50):
    """Return list of job dicts (may include old/done). Ordered newest first."""
    limit = max(1, min(int(limit or 50), 200))
    prefix = "print_job:"
    if USE_DB:
        ensure_kv_table()
        conn = get_db_conn()
        if conn is None:
            return []
        cur = conn.cursor()
        # Key is indexed; fetch a bounded set and filter in python.
        cur.execute(
            "select key, data, updated_at from kv_store where key like %s order by updated_at desc limit %s",
            (prefix + "%", limit),
        )
        rows = cur.fetchall() or []
        cur.close()
        release_db_conn(conn)
        out = []
        for _key, data, _updated_at in rows:
            try:
                obj = json.loads(data) if isinstance(data, str) else (data or {})
            except Exception:
                continue
            if isinstance(obj, dict):
                out.append(obj)
        return out
    # File-mode: scan directory for print jobs.
    out = []
    try:
        for name in os.listdir(DATA_DIR):
            if not name.startswith(prefix):
                continue
            try:
                obj = load_json_storage(name, None)
            except Exception:
                obj = None
            if isinstance(obj, dict):
                out.append(obj)
    except Exception:
        return []
    out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return out[:limit]

def _save_print_job(job):
    save_json_storage(f"print_job:{job['id']}", job)

def enqueue_print_job(target, job_type, payload):
    """Create a print job and store it. Returns job dict."""
    import uuid
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "status": "pending",  # pending | claimed | done | error
        "target": target,     # kitchen | cashier | ...
        "type": job_type,     # kitchen_ticket | bill | ...
        "payload": payload or {},
        "created_at": _now_iso(),
        "claimed_at": None,
        "claimed_by": None,
        "done_at": None,
        "error": None,
    }
    _save_print_job(job)

    # Best-effort retention cap (delete oldest jobs if > PRINT_QUEUE_MAX).
    try:
        jobs = _list_print_jobs(limit=PRINT_QUEUE_MAX + 50)
        if len(jobs) > PRINT_QUEUE_MAX:
            # jobs are newest-first; drop tail
            to_drop = jobs[PRINT_QUEUE_MAX:]
            for j in to_drop:
                jid = j.get("id")
                if not jid:
                    continue
                key = f"print_job:{jid}"
                if USE_DB:
                    ensure_kv_table()
                    conn = get_db_conn()
                    if conn:
                        cur = conn.cursor()
                        cur.execute("delete from kv_store where key = %s", (key,))
                        conn.commit()
                        cur.close()
                        release_db_conn(conn)
                else:
                    try:
                        os.remove(data_path(key))
                    except Exception:
                        pass
    except Exception:
        pass
    return job

@app.route('/api/print-jobs', methods=['GET'])
def api_print_jobs_list():
    if not _require_agent_token():
        return jsonify({"success": False, "error": "FORBIDDEN"}), 403
    status = (request.args.get('status') or 'pending').strip()
    target = (request.args.get('target') or 'kitchen').strip()
    limit = request.args.get('limit') or 20
    jobs = _list_print_jobs(limit=200)
    out = []
    for j in jobs:
        if status and j.get("status") != status:
            continue
        if target and j.get("target") != target:
            continue
        out.append(j)
        if len(out) >= int(limit):
            break
    return jsonify({"success": True, "jobs": out})


@app.route('/api/print-jobs/mock', methods=['POST'])
def api_print_jobs_mock():
    """Create a mock print job for testing without a printer."""
    if not _require_agent_token():
        return jsonify({"success": False, "error": "FORBIDDEN"}), 403
    payload = request.json or {}
    target = (payload.get("target") or "kitchen").strip()
    text = payload.get("text") or "TEST MUTFAK FISI"
    job = enqueue_print_job(target, "kitchen_ticket", {
        "text": text,
        "lines": payload.get("lines") or [],
        "meta": {"mock": True}
    })
    return jsonify({"success": True, "job": job})

@app.route('/api/print-jobs/<job_id>/claim', methods=['POST'])
def api_print_jobs_claim(job_id):
    if not _require_agent_token():
        return jsonify({"success": False, "error": "FORBIDDEN"}), 403
    job = load_json_storage(f"print_job:{job_id}", None)
    if not isinstance(job, dict):
        return jsonify({"success": False, "error": "NOT_FOUND"}), 404
    if job.get("status") not in ("pending",):
        return jsonify({"success": False, "error": "NOT_PENDING", "status": job.get("status")}), 409
    agent_id = (request.json or {}).get("agent_id") or request.headers.get("X-Agent-Id") or "agent"
    job["status"] = "claimed"
    job["claimed_at"] = _now_iso()
    job["claimed_by"] = agent_id
    _save_print_job(job)
    return jsonify({"success": True, "job": job})

@app.route('/api/print-jobs/<job_id>/done', methods=['POST'])
def api_print_jobs_done(job_id):
    if not _require_agent_token():
        return jsonify({"success": False, "error": "FORBIDDEN"}), 403
    job = load_json_storage(f"print_job:{job_id}", None)
    if not isinstance(job, dict):
        return jsonify({"success": False, "error": "NOT_FOUND"}), 404
    job["status"] = "done"
    job["done_at"] = _now_iso()
    _save_print_job(job)
    return jsonify({"success": True})

@app.route('/api/print-jobs/<job_id>/error', methods=['POST'])
def api_print_jobs_error(job_id):
    if not _require_agent_token():
        return jsonify({"success": False, "error": "FORBIDDEN"}), 403
    job = load_json_storage(f"print_job:{job_id}", None)
    if not isinstance(job, dict):
        return jsonify({"success": False, "error": "NOT_FOUND"}), 404
    payload = request.json or {}
    job["status"] = "error"
    job["done_at"] = _now_iso()
    job["error"] = payload.get("error") or "unknown"
    _save_print_job(job)
    return jsonify({"success": True})

def get_order_date(order):
    return order.get('kapanma_tarih') or order.get('paid_at') or order.get('tarih')

def get_order_time(order):
    if order.get('kapanma_zamani'):
        return order.get('kapanma_zamani')
    paid_at = order.get('paid_at')
    if paid_at:
        try:
            return datetime.fromisoformat(paid_at).strftime('%H:%M')
        except Exception:
            return None
    return order.get('zaman')

def is_order_closed(order):
    return bool(
        order.get('durum') == 'kapali'
        or order.get('is_paid')
        or order.get('paid_at')
        or order.get('kapanma_tarih')
    )

def to_iso_date(date_str):
    if not date_str:
        return None
    if '-' in date_str:
        try:
            return datetime.fromisoformat(date_str).date().isoformat()
        except Exception:
            return None
    if '.' in date_str:
        parts = date_str.split('.')
        if len(parts) >= 3:
            day, month, year = parts[0], parts[1], parts[2]
            try:
                return datetime(int(year), int(month), int(day)).date().isoformat()
            except Exception:
                return None
    return None

def now_tr():
    try:
        return datetime.now(ZoneInfo("Europe/Istanbul"))
    except Exception:
        return datetime.now()

def parse_order_datetime(order):
    date_str = order.get('kapanma_tarih') or order.get('tarih') or ''
    time_str = order.get('kapanma_zamani') or order.get('zaman') or '00:00'
    try:
        if '.' in date_str:
            gun, ay, yil = date_str.split('.')
            dt = datetime(int(yil), int(ay), int(gun))
        else:
            yil, ay, gun = date_str.split('-')
            dt = datetime(int(yil), int(ay), int(gun))
        saat, dakika = time_str.split(':')
        dt = dt.replace(hour=int(saat), minute=int(dakika))
        return dt.replace(tzinfo=ZoneInfo("Europe/Istanbul"))
    except Exception:
        return now_tr()

def business_day_key(dt):
    cutoff = dt.replace(hour=19, minute=0, second=0, microsecond=0)
    if dt < cutoff:
        return (dt - timedelta(days=1)).date()
    return dt.date()

def parse_iso_datetime(value):
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("Europe/Istanbul"))
        return dt
    except Exception:
        return None

def get_table_open_ts(orders, masa):
    open_ts = None
    for order in orders:
        if order.get('durum') != 'aktif':
            continue
        if str(order.get('masa')) != str(masa):
            continue
        ts = order.get('masa_acilis_ts')
        if not ts:
            continue
        if open_ts is None or ts < open_ts:
            open_ts = ts
    return open_ts

def finalize_table_session(masa, orders):
    sessions = load_table_sessions()
    open_ts = sessions.get(str(masa))
    if not open_ts:
        open_ts = get_table_open_ts(orders, masa)
    start_dt = parse_iso_datetime(open_ts) if open_ts else None
    if not start_dt:
        return
    end_dt = now_tr()
    duration_seconds = max(0, int((end_dt - start_dt).total_seconds()))
    if duration_seconds <= 0:
        return
    day_key = business_day_key(end_dt).isoformat()
    usage = load_table_usage()
    day_usage = usage.get(day_key, {})
    day_usage[str(masa)] = int(day_usage.get(str(masa), 0)) + duration_seconds
    usage[day_key] = day_usage
    save_table_usage(usage)
    sessions.pop(str(masa), None)
    save_table_sessions(sessions)

def load_config():
    try:
        return load_json_storage(CONFIG_FILE, {'kasa_sifre': 'kasa123'})
    except Exception as e:
        print("CONFIG_LOAD_ERROR:", repr(e), flush=True)
        return {'kasa_sifre': 'kasa123'}


def default_menu_seed():
    return {
        "ana_menu": [
            {"id": 1, "name": "Serpme Kahvalt?", "price": 1290, "category": "ana_menu", "image": "??"}
        ],
        "ekstralar": [
            {"id": 2, "name": "Patates K?zartmas?", "price": 350, "category": "ekstra", "image": "??"},
            {"id": 3, "name": "Hellim", "price": 350, "category": "ekstra", "image": "??"},
            {"id": 4, "name": "Falafel", "price": 350, "category": "ekstra", "image": "??"},
            {"id": 5, "name": "M?hlama", "price": 350, "category": "ekstra", "image": "??"},
            {"id": 6, "name": "G?z Yumurta", "price": 350, "category": "ekstra", "image": "??"},
            {"id": 7, "name": "Sucuk", "price": 350, "category": "ekstra", "image": "??"},
            {"id": 8, "name": "Patatesli G?zleme", "price": 300, "category": "ekstra", "image": "??"},
            {"id": 9, "name": "Peynirli G?zleme", "price": 300, "category": "ekstra", "image": "??"},
            {"id": 10, "name": "Ispanakl? G?zleme", "price": 300, "category": "ekstra", "image": "??"}
        ],
        "icecekler": [
            {"id": 11, "name": "?ay", "price": 50, "category": "icecek", "image": "?"},
            {"id": 12, "name": "Karak", "price": 100, "category": "icecek", "image": "?"},
            {"id": 13, "name": "S?cak S?t", "price": 100, "category": "icecek", "image": "??"},
            {"id": 14, "name": "T?rk Kahvesi", "price": 150, "category": "icecek", "image": "?"},
            {"id": 15, "name": "Portakal Suyu", "price": 300, "category": "icecek", "image": "??"},
            {"id": 16, "name": "Limonata", "price": 300, "category": "icecek", "image": "??"},
            {"id": 17, "name": "Su", "price": 60, "category": "icecek", "image": "??"},
            {"id": 18, "name": "Nar Suyu", "price": 300, "category": "icecek", "image": "??"}
        ],
        "sarkuteri": [],
        "sicak_ucretsiz": []
    }

def init_data():
    if not storage_has_key(MENU_FILE):
        menu = default_menu_seed()
        save_json_storage(MENU_FILE, menu)
    
    if not storage_has_key(ORDERS_FILE):
        save_json_storage(ORDERS_FILE, [])

    if not storage_has_key(PAYMENTS_FILE):
        save_json_storage(PAYMENTS_FILE, [])
    
    if not storage_has_key(TABLES_FILE):
        tables = {str(i): f"Masa {i}" for i in range(1, 26)}
        save_json_storage(TABLES_FILE, tables)

    if not storage_has_key(TABLE_BILL_REQUEST_FILE):
        save_json_storage(TABLE_BILL_REQUEST_FILE, {})

    init_staff_storage()


def load_orders():
    return cached_load('orders', lambda: load_json_storage(ORDERS_FILE, []), ORDERS_CACHE_TTL)

def save_orders(orders):
    save_json_storage(ORDERS_FILE, orders)
    invalidate_cache('orders')

def load_activity_log():
    return load_json_storage(ACTIVITY_LOG_FILE, [])

def save_activity_log(entries):
    save_json_storage(ACTIVITY_LOG_FILE, entries)

def append_activity(action, payload):
    entries = load_activity_log()
    entry = {
        'id': len(entries) + 1,
        'action': action,
        'created_at': now_tr().isoformat(),
        'data': payload or {}
    }
    entries.append(entry)
    save_activity_log(entries)

def load_payments():
    return cached_load('payments', lambda: load_json_storage(PAYMENTS_FILE, []), ORDERS_CACHE_TTL)

def save_payments(payments):
    save_json_storage(PAYMENTS_FILE, payments)
    invalidate_cache('payments')

def load_closed_checks():
    return load_json_storage(CLOSED_CHECKS_FILE, [])

def save_closed_checks(records):
    save_json_storage(CLOSED_CHECKS_FILE, records)

def load_closed_check_items():
    return load_json_storage(CLOSED_CHECK_ITEMS_FILE, [])

def save_closed_check_items(items):
    save_json_storage(CLOSED_CHECK_ITEMS_FILE, items)

def archive_closed_order(order, staff_info=None):
    if not order:
        return
    checks = load_closed_checks()
    items_store = load_closed_check_items()
    check_id = max([c.get('id', 0) for c in checks] or [0]) + 1
    closed_at = now_tr().isoformat()
    table_id = order.get('masa')
    record = {
        'id': check_id,
        'order_id': order.get('id'),
        'table_id': table_id,
        'table_name': load_tables().get(str(table_id)) or f"Masa {table_id}",
        'opened_at': order.get('masa_acilis_ts') or order.get('tarih'),
        'closed_at': closed_at,
        'total': order.get('indirimli_tutar') or order.get('paid_total') or order.get('toplam') or 0,
        'payment_type': order.get('odeme_turu') or 'bilinmiyor',
        'payment_breakdown': order.get('odeme_breakdown') or {},
        'staff_id': (staff_info or {}).get('staff_id'),
        'staff_name': (staff_info or {}).get('staff_name') or order.get('garson') or 'Bilinmiyor'
    }
    checks.append(record)
    for item in order.get('items') or []:
        items_store.append({
            'check_id': check_id,
            'order_id': order.get('id'),
            'item_id': item.get('id'),
            'name': item.get('name'),
            'adet': item.get('adet'),
            'price': item.get('price'),
            'total': (item.get('price') or 0) * (item.get('adet') or 0)
        })
    save_closed_checks(checks)
    save_closed_check_items(items_store)

def parse_closed_datetime(order):
    date_str = order.get('kapanma_tarih') or order.get('tarih') or ''
    time_str = order.get('kapanma_zamani') or order.get('zaman') or '00:00'
    try:
        if '.' in date_str:
            gun, ay, yil = date_str.split('.')
            return datetime(int(yil), int(ay), int(gun), int(time_str.split(':')[0]), int(time_str.split(':')[1] or 0))
        if '-' in date_str:
            yil, ay, gun = date_str.split('-')
            return datetime(int(yil), int(ay), int(gun), int(time_str.split(':')[0]), int(time_str.split(':')[1] or 0))
    except Exception:
        return None
    return None

def load_table_discounts():
    return load_json_storage(TABLE_DISCOUNTS_FILE, {})

def save_table_discounts(discounts):
    save_json_storage(TABLE_DISCOUNTS_FILE, discounts)

def load_menu():
    menu = cached_load('menu', lambda: load_json_storage(MENU_FILE, {}), MENU_CACHE_TTL)
    if not menu:
        menu = default_menu_seed()
        save_json_storage(MENU_FILE, menu)
        invalidate_cache('menu')
    # ensure new groups exist
    if isinstance(menu, dict):
        menu.setdefault("sarkuteri", [])
        menu.setdefault("sicak_ucretsiz", [])
    return menu

def find_menu_item_by_name(menu, name):
    if not isinstance(menu, dict):
        return None
    for group_items in menu.values():
        if not isinstance(group_items, list):
            continue
        for item in group_items:
            if (item.get('name') or '').strip() == name:
                return item
    return None

def normalize_payment_type(value):
    val = (value or '').strip().lower()
    if val in ['cash', 'nakit']:
        return 'cash'
    if val in ['card', 'kart']:
        return 'card'
    if val in ['qr', 'qrpay', 'qrcode']:
        return 'qr'
    if val in ['other', 'diger', 'diğer']:
        return 'other'
    return val or 'other'

def payment_label_from_type(ptype):
    if ptype == 'cash':
        return 'nakit'
    if ptype == 'card':
        return 'kart'
    if ptype == 'qr':
        return 'qr'
    return 'diger'

def build_payment_breakdown(payments):
    breakdown = {'cash': 0.0, 'card': 0.0, 'qr': 0.0, 'other': 0.0}
    for payment in payments or []:
        ptype = normalize_payment_type(payment.get('type'))
        try:
            amount = float(payment.get('amount') or 0)
        except Exception:
            amount = 0.0
        if ptype not in breakdown:
            breakdown[ptype] = 0.0
        breakdown[ptype] += amount
    return breakdown

def get_payment_amount(order, pay_type):
    ptype = normalize_payment_type(pay_type)
    breakdown = order.get('odeme_breakdown')
    if isinstance(breakdown, dict) and ptype in breakdown:
        try:
            return float(breakdown.get(ptype) or 0)
        except Exception:
            return 0.0
    if order.get('odeme_turu') in ['nakit', 'kart'] and normalize_payment_type(order.get('odeme_turu')) == ptype:
        return float(order.get('indirimli_tutar', order.get('toplam', 0)) or 0)
    return 0.0

def apply_payments_to_orders(orders, payments, allow_discount=True, force_discount=False):
    if not payments or not isinstance(payments, list):
        raise ValueError('Odeme listesi gerekli.')
    allowed = {'cash', 'card', 'qr', 'other'}
    cleaned = []
    for item in payments:
        if not isinstance(item, dict):
            continue
        ptype = normalize_payment_type(item.get('type'))
        if ptype not in allowed:
            raise ValueError('Gecersiz odeme turu.')
        try:
            amount = float(item.get('amount') or 0)
        except Exception:
            amount = 0.0
        if amount <= 0:
            raise ValueError('Odeme tutari 0 olamaz.')
        cleaned.append({'type': ptype, 'amount': amount, 'meta': item.get('meta')})

    if not cleaned:
        raise ValueError('Odeme listesi gerekli.')

    total = sum(float(o.get('toplam', 0) or 0) for o in orders)
    if total <= 0:
        raise ValueError('Toplam tutar bulunamadi.')

    cash_only = allow_discount and all(p['type'] == 'cash' for p in cleaned)
    card_only = all(p['type'] == 'card' for p in cleaned)
    total_due = round(total * 0.9, 2) if cash_only else round(total, 2)
    if force_discount and not cash_only:
        raise ValueError('Nakit indirimi icin tek odeme nakit olmalidir.')
    paid_total = round(sum(p['amount'] for p in cleaned), 2)

    if abs(paid_total - total_due) > 0.01:
        raise ValueError('Odeme toplamı tutmuyor.')

    breakdowns = {}
    for order in orders:
        breakdowns[order['id']] = {'cash': 0.0, 'card': 0.0, 'qr': 0.0, 'other': 0.0}

    def order_share(order):
        try:
            return float(order.get('toplam', 0) or 0) / total
        except Exception:
            return 0.0

    for payment in cleaned:
        allocated = 0.0
        for idx, order in enumerate(orders):
            if idx == len(orders) - 1:
                part = round(payment['amount'] - allocated, 2)
            else:
                part = round(payment['amount'] * order_share(order), 2)
                allocated += part
            breakdowns[order['id']][payment['type']] += part

    due_map = {}
    allocated_due = 0.0
    for idx, order in enumerate(orders):
        if idx == len(orders) - 1:
            due = round(total_due - allocated_due, 2)
        else:
            ratio = order_share(order)
            due = round(total_due * ratio, 2)
            allocated_due += due
        due_map[order['id']] = due

    return {
        'payments': cleaned,
        'total_due': total_due,
        'cash_only': cash_only,
        'card_only': card_only,
        'breakdowns': breakdowns,
        'due_map': due_map
    }

def allocate_due_map(orders, total_due):
    total = sum(float(o.get('toplam', 0) or 0) for o in orders) or 0.0
    due_map = {}
    if total <= 0:
        for order in orders:
            due_map[order['id']] = 0.0
        return due_map
    allocated_due = 0.0
    for idx, order in enumerate(orders):
        if idx == len(orders) - 1:
            due = round(total_due - allocated_due, 2)
        else:
            ratio = float(order.get('toplam', 0) or 0) / total
            due = round(total_due * ratio, 2)
            allocated_due += due
        due_map[order['id']] = due
    return due_map

def compute_discount_amount(subtotal, discount):
    if not discount:
        return 0.0
    try:
        value = float(discount.get('value') or 0)
    except Exception:
        value = 0.0
    if value <= 0 or subtotal <= 0:
        return 0.0
    dtype = discount.get('type')
    if dtype == 'percent':
        amount = subtotal * value / 100.0
    elif dtype == 'amount':
        amount = value
    else:
        return 0.0
    return max(0.0, min(subtotal, round(amount, 2)))

def flatten_menu_items(menu):
    if not isinstance(menu, dict):
        return []
    items = []
    for group, entries in menu.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = entry.get('name') or entry.get('title')
            if not name:
                continue
            items.append({
                'name': str(name),
                'category': str(entry.get('category') or group or '')
            })
    seen = set()
    output = []
    for item in items:
        key = item['name'].lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output

def load_tables():
    return cached_load('tables', lambda: load_json_storage(TABLES_FILE, {str(i): f"Masa {i}" for i in range(1, 26)}), TABLES_CACHE_TTL)

def save_tables(tables):
    save_json_storage(TABLES_FILE, tables)
    invalidate_cache('tables')

def load_rehber_masalar():
    return cached_load('rehber', lambda: load_json_storage(REHBER_FILE, {}), REHBER_CACHE_TTL)

def save_rehber_masalar(rehber_masalar):
    save_json_storage(REHBER_FILE, rehber_masalar)
    invalidate_cache('rehber')

def load_bill_requests():
    return load_json_storage(TABLE_BILL_REQUEST_FILE, {})

def save_bill_requests(data):
    save_json_storage(TABLE_BILL_REQUEST_FILE, data)

def load_staff():
    staff = cached_load('staff', lambda: load_json_storage(STAFF_FILE, []), STAFF_CACHE_TTL)
    updated = False
    for item in staff:
        if not item.get('pin_hash'):
            item['pin_hash'] = generate_password_hash('1234')
            item['updated_at'] = now_tr().isoformat()
            updated = True
    if updated:
        save_staff(staff)
    return staff

def save_staff(staff):
    save_json_storage(STAFF_FILE, staff)
    invalidate_cache('staff')

def normalize_staff_name(name):
    return str(name or '').strip()

def find_staff_by_name(staff_list, name):
    key = normalize_staff_name(name).lower()
    if not key:
        return None
    for item in staff_list:
        if normalize_staff_name(item.get('name')).lower() == key:
            return item
    return None

def get_staff_defaults():
    employees = load_json_storage(EMPLOYEES_FILE, [])
    names = []
    if isinstance(employees, list) and employees:
        names = [normalize_staff_name(n) for n in employees if normalize_staff_name(n)]
    if not names:
        orders = load_json_storage(ORDERS_FILE, [])
        names = sorted({normalize_staff_name(o.get('garson')) for o in orders if normalize_staff_name(o.get('garson'))})
    if not names:
        names = ['Garson']
    return names

def init_staff_storage():
    if storage_has_key(STAFF_FILE):
        return
    now_iso = now_tr().isoformat()
    names = get_staff_defaults()
    staff = []
    next_id = 1
    for name in names:
        staff.append({
            'id': next_id,
            'name': name,
            'is_active': True,
            'pin_hash': generate_password_hash('1234'),
            'created_at': now_iso,
            'updated_at': now_iso
        })
        next_id += 1
    save_json_storage(STAFF_FILE, staff)

def find_staff_by_id(staff_list, staff_id):
    for item in staff_list:
        if str(item.get('id')) == str(staff_id):
            return item
    return None

def get_actor_info(staff_id=None, staff_name=None):
    sid = session.get('waiter_id')
    sname = session.get('user')
    if sid is None and staff_id is not None:
        sid = staff_id
    if (not sname) and staff_name:
        sname = staff_name
    if sid is not None:
        staff_list = load_staff()
        item = find_staff_by_id(staff_list, sid)
        if item and not sname:
            sname = item.get('name')
    return {
        'staff_id': sid,
        'staff_name': sname or 'Bilinmiyor'
    }



def compute_staff_stats(date_param=None, start_param=None, end_param=None):
    target_date = to_iso_date(date_param) or None
    start_date = to_iso_date(start_param) or None
    end_date = to_iso_date(end_param) or None
    if start_date and not end_date:
        end_date = start_date
    if end_date and not start_date:
        start_date = end_date
    if not target_date and not start_date:
        target_date = now_tr().date().isoformat()

    orders = load_orders()
    closed_checks = load_closed_checks()
    closed_items = load_closed_check_items()
    staff_list = load_staff()
    staff_map = {str(s.get('id')): s for s in staff_list}
    stats = {}

    def ensure_stat(key, staff_id, name):
        if key in stats:
            return
        stats[key] = {
            'staff_id': staff_id,
            'name': name,
            'order_count': 0,
            'revenue': 0.0,
            'avg_basket': 0.0,
            'serpme_count': 0,
            'tables': [],
            'active_table_count': 0,
            'last_order_ts': None,
            '_tables': set(),
            '_active_tables': set(),
            '_last_dt': None
        }

    for s in staff_list:
        ensure_stat(str(s.get('id')), s.get('id'), s.get('name') or 'Garson')

    def order_total(order):
        val = order.get('indirimli_tutar')
        if val in [None, '']:
            val = order.get('toplam', 0)
        try:
            return float(val)
        except Exception:
            return 0.0

    def in_range(day_iso):
        if not day_iso:
            return False
        if start_date and end_date:
            return start_date <= day_iso <= end_date
        return day_iso == target_date

    selected_checks = []
    if closed_checks:
        for check in closed_checks:
            dt = parse_iso_datetime(check.get('closed_at') or check.get('opened_at') or '')
            if not dt:
                continue
            if in_range(dt.date().isoformat()):
                selected_checks.append(check)

    if selected_checks:
        items_by_check = {}
        for item in closed_items or []:
            cid = item.get('check_id')
            if cid is None:
                continue
            items_by_check.setdefault(cid, []).append(item)

        for check in selected_checks:
            staff_id = check.get('staff_id')
            if staff_id is None:
                key = 'unknown'
                name = normalize_staff_name(check.get('staff_name')) or 'Bilinmiyor'
            else:
                key = str(staff_id)
                staff_item = staff_map.get(key)
                name = (staff_item.get('name') if staff_item else None) or normalize_staff_name(check.get('staff_name')) or 'Bilinmiyor'

            ensure_stat(key, staff_id, name)
            stats[key]['order_count'] += 1
            try:
                stats[key]['revenue'] += float(check.get('total') or 0)
            except Exception:
                pass

            table_val = check.get('table_id')
            if table_val is not None:
                stats[key]['_tables'].add(table_val)

            for item in items_by_check.get(check.get('id'), []):
                item_name = str(item.get('name') or '').lower()
                if 'serpme' in item_name:
                    try:
                        stats[key]['serpme_count'] += int(item.get('adet') or 0)
                    except Exception:
                        pass

            dt = parse_iso_datetime(check.get('closed_at') or '')
            if dt:
                last_dt = stats[key]['_last_dt']
                if not last_dt or dt > last_dt:
                    stats[key]['_last_dt'] = dt
    else:
        for order in orders:
            order_date = to_iso_date(get_order_date(order))
            if not in_range(order_date):
                continue

            staff_id = order.get('staff_id')
            if staff_id is None:
                key = 'unknown'
                name = normalize_staff_name(order.get('garson')) or 'Bilinmiyor'
            else:
                key = str(staff_id)
                staff_item = staff_map.get(key)
                name = (staff_item.get('name') if staff_item else None) or normalize_staff_name(order.get('garson')) or 'Bilinmiyor'

            ensure_stat(key, staff_id, name)
            stats[key]['order_count'] += 1
            stats[key]['revenue'] += order_total(order)

            table_val = order.get('masa')
            if table_val is not None:
                stats[key]['_tables'].add(table_val)
                if order.get('durum') == 'aktif':
                    stats[key]['_active_tables'].add(table_val)

            for item in order.get('items') or []:
                item_name = str(item.get('name') or '').lower()
                if 'serpme' in item_name:
                    try:
                        stats[key]['serpme_count'] += int(item.get('adet') or 0)
                    except Exception:
                        pass

            dt = parse_order_datetime(order)
            if dt:
                last_dt = stats[key]['_last_dt']
                if not last_dt or dt > last_dt:
                    stats[key]['_last_dt'] = dt

    result = []
    for key, data in stats.items():
        tables = list(data.pop('_tables'))
        active_tables = data.pop('_active_tables')
        last_dt = data.pop('_last_dt')

        def table_sort_key(v):
            try:
                return (0, int(v))
            except Exception:
                return (1, str(v))

        tables = sorted(tables, key=table_sort_key)
        data['tables'] = tables
        data['active_table_count'] = len(active_tables)
        data['last_order_ts'] = last_dt.isoformat() if last_dt else None

        order_count = data.get('order_count') or 0
        revenue = round(float(data.get('revenue') or 0), 2)
        data['revenue'] = revenue
        data['avg_basket'] = round(revenue / order_count, 2) if order_count > 0 else 0.0
        result.append(data)

    result.sort(key=lambda x: (-(x.get('order_count') or 0), -(x.get('revenue') or 0), str(x.get('name') or '')))
    return (target_date or start_date or now_tr().date().isoformat()), result

def default_tables_layout(area):
    layout = {}
    cols = 5
    width = 120
    height = 90
    gap = 16
    start_x = 16
    start_y = 16
    for i in range(1, 26):
        idx = i - 1
        col = idx % cols
        row = idx // cols
        x = start_x + col * (width + gap)
        y = start_y + row * (height + gap)
        layout[str(i)] = {
            'pos_x': x,
            'pos_y': y,
            'width': width,
            'height': height,
            'rotation': 0,
            'area': area
        }
    return layout

def load_tables_layout(area='salon'):
    def loader():
        data = load_json_storage(TABLES_LAYOUT_FILE, {})
        if area not in data or not isinstance(data.get(area), dict):
            data[area] = default_tables_layout(area)
            save_json_storage(TABLES_LAYOUT_FILE, data)
        return data.get(area, {})
    return cached_load(f'tables_layout_{area}', loader, 60)

def save_tables_layout(area, layout):
    data = load_json_storage(TABLES_LAYOUT_FILE, {})
    data[area] = layout
    save_json_storage(TABLES_LAYOUT_FILE, data)
    invalidate_cache(f'tables_layout_{area}')

def load_table_sessions():
    return load_json_storage(TABLE_SESSIONS_FILE, {})

def save_table_sessions(sessions):
    save_json_storage(TABLE_SESSIONS_FILE, sessions)

def load_table_usage():
    return load_json_storage(TABLE_USAGE_FILE, {})

def save_table_usage(usage):
    save_json_storage(TABLE_USAGE_FILE, usage)

def load_tip_periods():
    return load_json_storage(TIP_FILE, [])

def save_tip_periods(periods):
    save_json_storage(TIP_FILE, periods)

def normalize_tip_total(value):
    return Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def calculate_tip_payouts(tip_total, workdays):
    # workdays: dict[name] = int
    tip_total_dec = normalize_tip_total(tip_total)
    total_cents = int(tip_total_dec * 100)
    total_days = sum(workdays.values())
    if total_days <= 0:
        return {}, 0

    payouts_cents = {}
    for name, days in workdays.items():
        if days <= 0:
            payouts_cents[name] = 0
            continue
        raw_cents = (Decimal(total_cents) * Decimal(days)) / Decimal(total_days)
        payouts_cents[name] = int(raw_cents.to_integral_value(rounding=ROUND_FLOOR))

    distributed = sum(payouts_cents.values())
    remaining = total_cents - distributed

    if remaining > 0:
        order = sorted(workdays.items(), key=lambda x: (-x[1], x[0]))
        idx = 0
        while remaining > 0 and order:
            name = order[idx % len(order)][0]
            payouts_cents[name] += 1
            remaining -= 1
            idx += 1

    payouts = {name: float(Decimal(cents) / Decimal(100)) for name, cents in payouts_cents.items()}
    return payouts, total_cents


def load_attendance():
    return load_json_storage(ATTENDANCE_FILE, [])

def save_attendance(records):
    save_json_storage(ATTENDANCE_FILE, records)

def load_attendance_config():
    return load_json_storage(ATTENDANCE_CONFIG_FILE, {'start_time': '09:00', 'end_time': '18:00'})

def save_attendance_config(cfg):
    save_json_storage(ATTENDANCE_CONFIG_FILE, cfg)

def parse_date(value):
    try:
        return datetime.strptime(value, '%Y-%m-%d')
    except:
        return None


def load_employees():
    staff = load_staff()
    names = []
    for item in staff:
        if item.get('is_active') is False:
            continue
        name = normalize_staff_name(item.get('name'))
        if name:
            names.append(name)
    return names

def save_employees(names):
    staff = load_staff()
    next_id = max([int(s.get('id', 0)) for s in staff] + [0]) + 1
    desired = {}
    for raw in names:
        name = normalize_staff_name(raw)
        if name:
            desired[name.lower()] = name

    for item in staff:
        key = normalize_staff_name(item.get('name')).lower()
        if key in desired:
            item['name'] = desired[key]
            item['is_active'] = True
        else:
            item['is_active'] = False

    existing_keys = {normalize_staff_name(s.get('name')).lower() for s in staff}
    for key, name in desired.items():
        if key in existing_keys:
            continue
        staff.append({
            'id': next_id,
            'name': name,
            'is_active': True,
            'created_at': now_tr().isoformat(timespec='seconds'),
            'updated_at': now_tr().isoformat(timespec='seconds')
        })
        next_id += 1

    save_staff(staff)

def get_printer_by_name(printer_name):
    try:
        from escpos.printer import Win32Raw
    except Exception as exc:
        raise RuntimeError('python-escpos yuklu degil.') from exc
    if not printer_name:
        raise RuntimeError('PRINTER_NAME ayari bulunamadi.')
    return Win32Raw(printer_name)

def get_printer():
    return get_printer_by_name(PRINTER_NAME)

def get_kitchen_printer():
    return get_printer_by_name(KITCHEN_PRINTER_NAME)

def build_bill_payload(table_id, orders):
    items_map = {}
    garson = ''
    last_time = ''
    for order in orders:
        if order.get('durum') != 'aktif':
            continue
        garson = order.get('garson') or garson
        last_time = order.get('zaman') or last_time
        for item in order.get('items', []):
            name = item.get('name') or 'Urun'
            price = float(item.get('price', 0))
            qty = int(item.get('adet', 0) or 0)
            is_complimentary = bool(item.get('is_complimentary'))
            is_free_hot = bool(item.get('is_free_hot'))
            key = (name, price, is_complimentary, is_free_hot)
            items_map[key] = items_map.get(key, 0) + qty
    items = []
    total = 0.0
    for (name, price, is_complimentary, is_free_hot), qty in items_map.items():
        line_total = 0.0 if (is_complimentary or is_free_hot) else (price * qty)
        total += line_total
        items.append({
            'name': name,
            'qty': qty,
            'price': price,
            'line_total': line_total,
            'is_complimentary': is_complimentary,
            'is_free_hot': is_free_hot
        })
    if total == 0:
        total = sum(float(o.get('toplam', 0)) for o in orders if o.get('durum') == 'aktif')
    items.sort(key=lambda i: i['name'])
    subtotal = sum(float(o.get('toplam', 0) or 0) for o in orders if o.get('durum') == 'aktif')
    discounts = load_table_discounts()
    discount = discounts.get(str(table_id))
    discount_amount = compute_discount_amount(subtotal, discount)
    total_due = round(subtotal - discount_amount, 2)
    return {
        'table_id': table_id,
        'garson': garson or 'Bilinmiyor',
        'time': now_tr().strftime('%d.%m.%Y %H:%M'),
        'items': items,
        'subtotal': round(subtotal, 2),
        'discount': discount or None,
        'discount_amount': discount_amount,
        'total_due': total_due,
        'total': round(total, 2)
    }

def build_bill_text(payload, width=32, lang='tr'):
    def translate_item(name):
        if lang != 'en':
            return name
        mapping = {
            'serpme kahvalti': 'Breakfast',
            'mihlama': 'M\u0131hlama (Turkish Cheese & Cornmeal Fondue)',
            'goz yumurta': 'Fried Eggs',
            'patates kizartmasi': 'French Fries',
            'hellim': 'Halloumi Cheese',
            'falafel': 'Falafel',
            'sucuk': 'Turkish Sausage (Sucuk)',
            'cay': 'Tea',
            'karak': 'Karak Tea',
            'sicak sut': 'Hot Milk',
            'turk kahvesi': 'Turkish Coffee',
            'portakal suyu': 'Orange Juice',
            'limonata': 'Lemonade',
            'su': 'Water',
            'nar suyu': 'Pomegranate Juice'
        }
        raw = (name or '').strip().lower()
        while raw and not raw[0].isalnum():
            raw = raw[1:]
        key = (raw.replace('\u0131', 'i')
                  .replace('\u011f', 'g')
                  .replace('\u015f', 's')
                  .replace('\u00f6', 'o')
                  .replace('\u00fc', 'u')
                  .replace('\u00e7', 'c'))
        return mapping.get(key, name)

    lines = []
    sep = '-' * width
    lines.append(sep)
    if lang == 'en':
        lines.append(f"Table: {payload['table_id']}")
        lines.append(f"Worker: {payload['garson']}")
        lines.append(f"Time: {payload['time']}")
    else:
        lines.append(f"Masa: {payload['table_id']}")
        lines.append(f"Garson: {payload['garson']}")
        lines.append(f"Tarih: {payload['time']}")
    lines.append(sep)
    for item in sorted(payload['items'], key=lambda i: (-i['line_total'], i['name'])):
        name = translate_item(item['name'])
        qty = item['qty']
        is_complimentary = bool(item.get('is_complimentary'))
        is_free_hot = bool(item.get('is_free_hot'))
        line_total = item['line_total']
        label = f"{name} x{qty}"
        amount = "IKRAM" if is_complimentary else ("UCRETSIZ" if is_free_hot else f"{line_total:.0f} TL")
        lines.append(label.ljust(width - len(amount)) + amount)
    lines.append(sep)
    subtotal_text = f"{payload.get('subtotal', payload['total']):.0f} TL"
    total_due = float(payload.get('total_due') or payload['total'])
    total_text = f"{total_due:.0f} TL"
    if lang == 'en':
        lines.append('Subtotal:'.ljust(width - len(subtotal_text)) + subtotal_text)
        lines.append('Total:'.ljust(width - len(total_text)) + total_text)
    else:
        lines.append('Ara Toplam:'.ljust(width - len(subtotal_text)) + subtotal_text)
        lines.append('Ödenecek:'.ljust(width - len(total_text)) + total_text)
    lines.append('')
    if lang == 'en':
        lines.append('You Are Happy We Are Happy')
    else:
        lines.append('Afiyet Olsun Yine Bekleriz')
    lines.append(sep)
    return '\n'.join(lines)

def print_bill(table_id, orders, lang='tr'):
    payload = build_bill_payload(table_id, orders)
    printer = get_printer()

    try:
        printer.charcode('CP857')
    except Exception:
        try:
            printer.charcode('CP1254')
        except Exception:
            pass
    printer.text(build_bill_text(payload, 32, lang) + '\n')
    try:
        printer.cut()
    except Exception:
        pass

def build_kitchen_text(order, width=32, is_additional=False):
    sep = '-' * width
    table_id = order.get('masa')
    table_name = load_tables().get(str(table_id)) or f"Masa {table_id}"
    header = 'EK SIPARIS' if is_additional else 'SIPARIS'
    lines = [sep, header, f"{table_name}", f"Garson: {order.get('garson') or 'Bilinmiyor'}"]
    if order.get('zaman'):
        lines.append(f"Saat: {order.get('zaman')}")
    lines.append(sep)
    items_map = {}
    for item in order.get('items') or []:
        name = item.get('name') or 'Urun'
        qty = int(item.get('adet') or 0)
        if qty <= 0:
            continue
        note = (item.get('note') or '').strip()
        is_complimentary = bool(item.get('is_complimentary'))
        is_free_hot = bool(item.get('is_free_hot'))
        key = (name, note, is_complimentary, is_free_hot)
        items_map[key] = items_map.get(key, 0) + qty
    for (name, note, is_complimentary, is_free_hot) in sorted(items_map.keys(), key=lambda k: (k[0], k[1], k[2], k[3])):
        qty = items_map[(name, note, is_complimentary, is_free_hot)]
        label = f"{name} x{qty}"
        if is_complimentary:
            label = f"{label} (IKRAM)"
        elif is_free_hot:
            label = f"{label} (UCRETSIZ SICAK)"
        lines.append(label[:width])
        if note:
            lines.append(("  * " + note)[:width])
    lines.append(sep)
    return '\n'.join(lines)



def build_kitchen_revision_text(order, changes, note='', width=32):
    sep = '-' * width
    table_id = order.get('masa')
    table_name = load_tables().get(str(table_id)) or f"Masa {table_id}"
    header = 'DUZELTME'
    garson_name = order.get('garson') or 'Bilinmiyor'
    lines = [sep, header, f"{table_name}", f"Garson: {garson_name}"]
    lines.append(f"Saat: {now_tr().strftime('%H:%M')}")
    lines.append(sep)
    for ch in changes or []:
        delta = int(ch.get('delta') or 0)
        if delta == 0:
            continue
        sign = '+' if delta > 0 else '-'
        qty = abs(delta)
        name = ch.get('name') or 'Urun'
        label = f"{sign} {name} x{qty}"
        if ch.get('is_complimentary'):
            label = f"{label} (IKRAM)"
        elif ch.get('is_free_hot'):
            label = f"{label} (UCRETSIZ SICAK)"
        lines.append(label[:width])
        ch_note = (ch.get('note') or '').strip()
        if ch_note:
            lines.append(("  * " + ch_note)[:width])
    if note:
        lines.append(("NOT: " + str(note))[:width])
    lines.append(sep)
    return '\n'.join(lines)


def print_kitchen_revision(order, changes, note=''):
    if not changes:
        return False
    text = build_kitchen_revision_text(order, changes, note, 32)
    if KITCHEN_PRINT_MODE == 'queue':
        enqueue_print_job('kitchen', 'kitchen_revision', {
            'text': text,
            'cut': True,
            'charcode': 'CP857',
        })
        return True
    if not KITCHEN_PRINTER_ENABLED:
        return False
    if KITCHEN_PRINT_MODE != 'printer':
        print("KITCHEN_REVISION:\n" + text, flush=True)
        return True
    if not KITCHEN_PRINTER_NAME:
        print("KITCHEN_PRINTER_NAME ayari bulunamadi.", flush=True)
        return False
    printer = get_kitchen_printer()
    try:
        printer.charcode('CP857')
    except Exception:
        try:
            printer.charcode('CP1254')
        except Exception:
            pass
    printer.text(text + '\n')
    try:
        printer.cut()
    except Exception:
        pass
    return True

def print_kitchen_order(order, is_additional=False):
    text = build_kitchen_text(order, 32, is_additional)
    if KITCHEN_PRINT_MODE == 'queue':
        enqueue_print_job("kitchen", "kitchen_ticket", {
            "text": text,
            "cut": True,
            "charcode": "CP857",
        })
        return True
    if not KITCHEN_PRINTER_ENABLED:
        return False
    if KITCHEN_PRINT_MODE != 'printer':
        print("KITCHEN_TICKET:\n" + text, flush=True)
        return True
    if not KITCHEN_PRINTER_NAME:
        print("KITCHEN_PRINTER_NAME ayari bulunamadi.", flush=True)
        return False
    printer = get_kitchen_printer()
    try:
        printer.charcode('CP857')
    except Exception:
        try:
            printer.charcode('CP1254')
        except Exception:
            pass
    printer.text(text + '\n')
    try:
        printer.cut()
    except Exception:
        pass
    return True

def load_expenses():
    return load_json_storage(EXPENSES_FILE, [])

def save_expenses(records):
    save_json_storage(EXPENSES_FILE, records)

def normalize_date(value):
    if not value:
        return None
    if '.' in value:
        parts = value.split('.')
        if len(parts) == 3:
            gun, ay, yil = parts
            return f"{yil}-{ay.zfill(2)}-{gun.zfill(2)}"
    return value

def sum_expenses_for_date(date_value):
    date_iso = normalize_date(date_value)
    if not date_iso:
        return 0
    total = 0
    for r in load_expenses():
        if normalize_date(r.get('date')) == date_iso:
            total += float(r.get('tutar', 0))
    return total



@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/auth', methods=['POST'])
def auth():
    try:
        data = request.get_json(silent=True) or {}
        role = data.get('role')
        password = data.get('password')

        if role == 'garson':
            staff_list = load_staff()
            staff_item = find_staff_by_name(staff_list, data.get('name'))
            if not staff_item or not staff_item.get('is_active'):
                return jsonify({'success': False, 'message': 'Garson bulunamadi.'}), 400
            pin_hash = staff_item.get('pin_hash')
            if not pin_hash or not password or not check_password_hash(pin_hash, password):
                return jsonify({'success': False, 'message': 'Hatali sifre!'}), 400
            session['role'] = 'garson'
            session['user'] = staff_item.get('name')
            session['waiter_id'] = staff_item.get('id')
            return jsonify({'success': True, 'redirect': '/garson'})
        if role == 'kasa':
            kasa_sifre = load_config().get('kasa_sifre', 'kasa123')
            if password == kasa_sifre:
                session['role'] = 'kasa'
                session['user'] = 'Kasiyer'
                session['waiter_id'] = None
                return jsonify({'success': True, 'redirect': '/dashboard'})
        return jsonify({'success': False, 'message': 'Hatali sifre!'})
    except Exception as exc:
        print('AUTH_ERROR:', repr(exc), flush=True)
        print(traceback.format_exc(), flush=True)
        return ('auth error', 500)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/garson')
def garson():
    if session.get('role') != 'garson':
        return redirect(url_for('login'))
    menu = load_menu()
    return render_template('garson.html', menu=menu, user=session.get('user'))

@app.route('/kasa')
def kasa():
    if session.get('role') != 'kasa':
        return redirect(url_for('login'))
    return render_template('kasa.html')

@app.route('/siparis-gir')
def siparis_gir():
    if session.get('role') != 'kasa':
        return redirect(url_for('login'))
    return render_template('siparis_gir.html')

@app.route('/menu-yonetim')
def menu_yonetim():
    if session.get('role') != 'kasa':
        return redirect(url_for('login'))
    menu = load_menu()
    return render_template('menu_yonetim.html', menu=menu)

@app.route('/giderler')
def giderler():
    if session.get('role') != 'kasa':
        return redirect(url_for('login'))
    return render_template('giderler.html')

@app.route('/komisyonlar')
def komisyonlar():
    if session.get('role') != 'kasa':
        return redirect(url_for('login'))
    return render_template('komisyonlar.html')

@app.route('/api/debug-orders')
def debug_orders():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    
    from datetime import timedelta
    orders = load_orders()
    bugun = now_tr().strftime('%d.%m.%Y')
    dun = (now_tr() - timedelta(days=1)).strftime('%d.%m.%Y')
    
    debug_info = {
        'bugun': bugun,
        'dun': dun,
        'toplam_siparis': len(orders),
        'kapali_siparisler': len([o for o in orders if o['durum'] == 'kapali']),
        'bugun_kapali': [],
        'dun_kapali': []
    }
    
    for o in orders:
        if o['durum'] == 'kapali':
            order_tarih = o.get('kapanma_tarih') or o.get('tarih', '')
            if order_tarih == bugun:
                debug_info['bugun_kapali'].append({
                    'id': o['id'],
                    'masa': o['masa'],
                    'toplam': o['toplam'],
                    'tarih': o.get('tarih'),
                    'kapanma_tarih': o.get('kapanma_tarih'),
                    'indirimli_tutar': o.get('indirimli_tutar')
                })
            elif order_tarih == dun:
                debug_info['dun_kapali'].append({
                    'id': o['id'],
                    'masa': o['masa'],
                    'toplam': o['toplam'],
                    'tarih': o.get('tarih'),
                    'kapanma_tarih': o.get('kapanma_tarih'),
                    'indirimli_tutar': o.get('indirimli_tutar')
                })
    
    return jsonify(debug_info)

@app.route('/api/satis-grafik')
def satis_grafik():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403

    from datetime import datetime, timedelta, date

    # Rehber masalari yukle
    try:
        rehber_masalar = load_rehber_masalar()
    except Exception:
        rehber_masalar = {}

    closed_checks = load_closed_checks()
    closed_items = load_closed_check_items()

    items_by_check = {}
    for item in closed_items or []:
        cid = item.get('check_id')
        if cid is None:
            continue
        items_by_check.setdefault(str(cid), []).append(item)

    def serpme_count_for_check(check_id):
        count = 0
        for item in items_by_check.get(str(check_id), []):
            name = str(item.get('name') or '').lower()
            if 'serpme' in name:
                count += int(item.get('adet') or 0)
        return count

    def is_rehber_check(check):
        if check.get('rehber_masa'):
            return True
        masa = check.get('table_id') or check.get('masa')
        return rehber_masalar.get(str(masa), False)

    def checks_for_date(target_date):
        selected = []
        for check in closed_checks or []:
            dt = parse_iso_datetime(check.get('closed_at') or '')
            if not dt:
                continue
            if dt.date() == target_date:
                selected.append(check)
        return selected

    def sum_expenses_for_month(year, month):
        start = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1)
        else:
            end = date(year, month + 1, 1)
        total = 0
        cursor = start
        while cursor < end:
            total += sum_expenses_for_date(cursor.strftime('%Y-%m-%d'))
            cursor += timedelta(days=1)
        return total

    bugun = now_tr().date()
    haftalik_data = []

    if closed_checks:
        for i in range(6, -1, -1):
            day = bugun - timedelta(days=i)
            daily_checks = checks_for_date(day)
            gunluk_ciro = sum((c.get('total') or 0) for c in daily_checks)
            gunluk_komisyon = 0
            for check in daily_checks:
                if is_rehber_check(check):
                    gunluk_komisyon += serpme_count_for_check(check.get('id')) * 100
            gunluk_gider = sum_expenses_for_date(day.isoformat())
            net_kar = gunluk_ciro - gunluk_komisyon - gunluk_gider
            haftalik_data.append({
                'tarih': day.strftime('%d.%m'),
                'ciro': gunluk_ciro,
                'komisyon': gunluk_komisyon,
                'net_kar': net_kar,
                'siparis_sayisi': len(daily_checks)
            })
    else:
        orders = load_orders()
        for i in range(6, -1, -1):
            tarih = bugun - timedelta(days=i)
            tarih_str = tarih.strftime('%d.%m.%Y')
            gunluk_orders = []
            for o in orders:
                if o['durum'] == 'kapali':
                    order_tarih = o.get('kapanma_tarih') or o.get('tarih', '')
                    if order_tarih == tarih_str:
                        gunluk_orders.append(o)
            gunluk_ciro = sum(o.get('indirimli_tutar', o['toplam']) for o in gunluk_orders)
            gunluk_komisyon = 0
            for order in gunluk_orders:
                if order.get('rehber_masa') or rehber_masalar.get(str(order['masa'])):
                    for item in order['items']:
                        if item['name'] == 'Serpme Kahvalt?':
                            gunluk_komisyon += item['adet'] * 100
            gunluk_gider = 0
            for order in gunluk_orders:
                if order.get('tip') == 'gider':
                    gunluk_gider += abs(order['toplam'])
            net_kar = gunluk_ciro - gunluk_komisyon - gunluk_gider
            haftalik_data.append({
                'tarih': tarih.strftime('%d.%m'),
                'ciro': gunluk_ciro,
                'komisyon': gunluk_komisyon,
                'net_kar': net_kar,
                'siparis_sayisi': len(gunluk_orders)
            })

    aylik_data = []
    for i in range(11, -1, -1):
        if i == 0:
            ay_tarih = bugun
        else:
            ay = bugun.month - i
            yil = bugun.year
            while ay <= 0:
                ay += 12
                yil -= 1
            ay_tarih = bugun.replace(year=yil, month=ay, day=1)

        ay_label = ay_tarih.strftime('%m/%Y')
        if closed_checks:
            aylik_checks = []
            for check in closed_checks or []:
                dt = parse_iso_datetime(check.get('closed_at') or '')
                if not dt:
                    continue
                if dt.year == ay_tarih.year and dt.month == ay_tarih.month:
                    aylik_checks.append(check)
            aylik_ciro = sum((c.get('total') or 0) for c in aylik_checks)
            aylik_komisyon = 0
            for check in aylik_checks:
                if is_rehber_check(check):
                    aylik_komisyon += serpme_count_for_check(check.get('id')) * 100
            aylik_gider = sum_expenses_for_month(ay_tarih.year, ay_tarih.month)
            aylik_net_kar = aylik_ciro - aylik_komisyon - aylik_gider
            aylik_data.append({
                'ay': ay_label,
                'ciro': aylik_ciro,
                'komisyon': aylik_komisyon,
                'net_kar': aylik_net_kar,
                'siparis_sayisi': len(aylik_checks)
            })
        else:
            orders = load_orders()
            ay_str = ay_tarih.strftime('%m.%Y')
            aylik_orders = []
            for o in orders:
                if o['durum'] == 'kapali':
                    order_tarih = o.get('kapanma_tarih') or o.get('tarih', '')
                    if order_tarih and order_tarih.endswith(ay_str):
                        aylik_orders.append(o)
            aylik_ciro = sum(o.get('indirimli_tutar', o['toplam']) for o in aylik_orders)
            aylik_komisyon = 0
            for order in aylik_orders:
                if order.get('rehber_masa') or rehber_masalar.get(str(order['masa'])):
                    for item in order['items']:
                        if item['name'] == 'Serpme Kahvalt?':
                            aylik_komisyon += item['adet'] * 100
            aylik_gider = 0
            for order in aylik_orders:
                if order.get('tip') == 'gider':
                    aylik_gider += abs(order['toplam'])
            aylik_net_kar = aylik_ciro - aylik_komisyon - aylik_gider
            aylik_data.append({
                'ay': ay_label,
                'ciro': aylik_ciro,
                'komisyon': aylik_komisyon,
                'net_kar': aylik_net_kar,
                'siparis_sayisi': len(aylik_orders)
            })

    return jsonify({
        'haftalik': haftalik_data,
        'aylik': aylik_data
    })
    
    # Son 12 ayın verilerini hazırla
    aylik_data = []
    for i in range(11, -1, -1):
        # Ay hesaplamasını düzelt
        if i == 0:
            ay_tarih = bugun
        else:
            # Önceki ayları hesapla
            ay = bugun.month - i
            yil = bugun.year
            while ay <= 0:
                ay += 12
                yil -= 1
            ay_tarih = bugun.replace(year=yil, month=ay, day=1)
        
        ay_str = ay_tarih.strftime('%m.%Y')
        
        # Bu aya ait tüm siparişleri bul
        aylik_orders = []
        for o in orders:
            if o['durum'] == 'kapali':
                # Önce kapanma_tarih'i kontrol et, yoksa tarih'i kullan
                order_tarih = o.get('kapanma_tarih')
                if not order_tarih:
                    order_tarih = o.get('tarih', '')
                
                # Ay eşleştirmesi yap
                if order_tarih and order_tarih.endswith(ay_str):
                    aylik_orders.append(o)
        
        aylik_ciro = sum(o.get('indirimli_tutar', o['toplam']) for o in aylik_orders)
        
        # Aylık komisyon hesapla
        aylik_komisyon = 0
        for order in aylik_orders:
            if order.get('rehber_masa') or rehber_masalar.get(str(order['masa'])):
                for item in order['items']:
                    if item['name'] == 'Serpme Kahvaltı':
                        aylik_komisyon += item['adet'] * 100
        
        # Aylık gider hesaplamalarını ekle
        aylik_gider = 0
        for order in aylik_orders:
            if order.get('tip') == 'gider':
                aylik_gider += abs(order['toplam'])
        
        aylik_net_kar = aylik_ciro - aylik_komisyon - aylik_gider
        
        aylik_data.append({
            'ay': ay_tarih.strftime('%m/%Y'),
            'ciro': aylik_ciro,
            'komisyon': aylik_komisyon,
            'net_kar': aylik_net_kar,
            'siparis_sayisi': len(aylik_orders)
        })
    
    return jsonify({
        'haftalik': haftalik_data,
        'aylik': aylik_data
    })

@app.route('/istatistik')
def istatistik():
    if session.get('role') != 'kasa':
        return redirect(url_for('login'))
    return render_template('istatistik.html')

@app.route('/dashboard')
def dashboard():
    if session.get('role') != 'kasa':
        return redirect(url_for('login'))
    return render_template('dashboard.html')

@app.route('/dashboard-analytics')
def dashboard_analytics():
    if session.get('role') != 'kasa':
        return redirect(url_for('login'))
    return render_template('dashboard_analytics.html', dashboard_seed=build_dashboard_data())

@app.route('/api/siparis', methods=['POST'])
def siparis_ekle():
    if session.get('role') not in ['garson', 'kasa']:
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
        
    data = request.json
    staff_id = data.get('staff_id')
    if staff_id is None:
        return jsonify({'success': False, 'message': 'Garson secilmelidir.'}), 400
    try:
        staff_id = int(staff_id)
    except Exception:
        return jsonify({'success': False, 'message': 'Garson secilmelidir.'}), 400
    staff_list = load_staff()
    staff_item = find_staff_by_id(staff_list, staff_id)
    if not staff_item or not staff_item.get('is_active'):
        return jsonify({'success': False, 'message': 'Garson aktif degil.'}), 400

    orders = load_orders()
    masa = data.get('masa')
    existing_active = [o for o in orders if o.get('durum') == 'aktif' and str(o.get('masa')) == str(masa)]
    open_ts = get_table_open_ts(orders, masa)
    if not open_ts:
        open_ts = now_tr().isoformat()
    for order in orders:
        if order.get('durum') == 'aktif' and str(order.get('masa')) == str(masa):
            if not order.get('masa_acilis_ts'):
                order['masa_acilis_ts'] = open_ts

    sessions = load_table_sessions()
    if str(masa) not in sessions:
        sessions[str(masa)] = open_ts
        save_table_sessions(sessions)
    
    garson_name = staff_item.get('name')
    menu = load_menu()
    items = list(data.get('items') or [])
    auto_water_added = False
    if not existing_active:
        water_item = find_menu_item_by_name(menu, 'Su')
        if water_item:
            has_water = any((i.get('name') or i.get('urun')) == 'Su' for i in items)
            if not has_water:
                items.append({
                    'id': water_item.get('id'),
                    'name': water_item.get('name'),
                    'price': water_item.get('price'),
                    'adet': 2,
                    'is_complimentary': False
                })
                auto_water_added = True
    toplam = 0
    for i in items:
        if i.get('is_complimentary') or i.get('is_free_hot'):
            continue
        toplam += (i.get('price') or 0) * (i.get('adet') or 0)

    if existing_active:
        target = existing_active[0]
        merged_items = list(target.get('items') or [])
        merged_items.extend(items)
        target['items'] = merged_items
        if not target.get('garson'):
            target['garson'] = garson_name
        if not target.get('staff_id'):
            target['staff_id'] = staff_id
        target_total = 0
        for it in merged_items:
            if it.get('is_complimentary') or it.get('is_free_hot'):
                continue
            target_total += (it.get('price') or 0) * (it.get('adet') or 0)
        target['toplam'] = target_total
        target['zaman'] = now_tr().strftime('%H:%M')
        save_orders(orders)

        try:
            add_order = {
                'id': target.get('id'),
                'masa': masa,
                'garson': garson_name,
                'items': items,
                'zaman': now_tr().strftime('%H:%M')
            }
            printed = print_kitchen_order(add_order, is_additional=True)
            if printed:
                append_activity('KITCHEN_PRINT', {
                    'order_id': target.get('id'),
                    'table_id': masa,
                    'staff_id': staff_id,
                    'staff_name': garson_name,
                    'is_additional': True
                })
        except Exception as exc:
            print(f"KITCHEN_PRINT_ERROR: {exc!r}", flush=True)

        return jsonify({'success': True, 'order_id': target.get('id'), 'merged': True})

    new_order = {
        'id': len(orders) + 1,
        'masa': masa,
        'garson': garson_name,
        'staff_id': staff_id,
        'items': items,
        'toplam': toplam,
        'zaman': now_tr().strftime('%H:%M'),
        'tarih': now_tr().strftime('%d.%m.%Y'),
        'durum': 'aktif',
        'kaynak': 'kasa' if session.get('role') == 'kasa' else 'garson',
        'masa_acilis_ts': open_ts,
        'auto_water_added': auto_water_added
    }
    
    orders.append(new_order)
    save_orders(orders)

    if auto_water_added:
        append_activity('AUTO_WATER', {
            'order_id': new_order['id'],
            'table_id': masa,
            'staff_id': staff_id,
            'staff_name': garson_name,
            'count': 2
        })

    try:
        printed = print_kitchen_order(new_order, is_additional=bool(existing_active))
        if printed:
            append_activity('KITCHEN_PRINT', {
                'order_id': new_order['id'],
                'table_id': masa,
                'staff_id': staff_id,
                'staff_name': garson_name,
                'is_additional': bool(existing_active)
            })
    except Exception as exc:
        print(f"KITCHEN_PRINT_ERROR: {exc!r}", flush=True)
    
    return jsonify({'success': True, 'order_id': new_order['id']})


@app.route('/api/siparis/<int:order_id>/revise', methods=['POST'])
def siparis_revise(order_id):
    if session.get('role') not in ['garson', 'kasa']:
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403
    data = request.get_json(silent=True) or {}
    new_items = list(data.get('items') or [])
    note = (data.get('note') or '').strip()
    orders = load_orders()
    order = next((o for o in orders if int(o.get('id', 0)) == int(order_id)), None)
    if not order or order.get('durum') != 'aktif':
        return jsonify({'success': False, 'message': 'Siparis bulunamadi.'}), 404
    if session.get('role') == 'garson':
        if normalize_staff_name(order.get('garson')) != normalize_staff_name(session.get('user')):
            return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403

    def _key(item):
        name = (item.get('name') or item.get('urun') or '').strip()
        note = (item.get('note') or '').strip()
        is_comp = bool(item.get('is_complimentary'))
        is_free = bool(item.get('is_free_hot'))
        return (name, note, is_comp, is_free)

    def _map(items):
        m = {}
        for it in items:
            qty = int(it.get('adet') or 0)
            if qty <= 0:
                continue
            key = _key(it)
            m[key] = m.get(key, 0) + qty
        return m

    old_items = order.get('items') or []
    old_map = _map(old_items)
    new_map = _map(new_items)
    changes = []
    for key in set(old_map.keys()) | set(new_map.keys()):
        old_qty = old_map.get(key, 0)
        new_qty = new_map.get(key, 0)
        delta = new_qty - old_qty
        if delta != 0:
            name, note_i, is_comp, is_free = key
            changes.append({
                'name': name,
                'note': note_i,
                'is_complimentary': is_comp,
                'is_free_hot': is_free,
                'delta': delta
            })

    total = 0
    for it in new_items:
        if it.get('is_complimentary') or it.get('is_free_hot'):
            continue
        total += (it.get('price') or 0) * (it.get('adet') or 0)

    order['items'] = new_items
    order['toplam'] = total
    order['revized_at'] = now_tr().isoformat()
    save_orders(orders)

    if changes:
        append_activity('ORDER_REVISION', {
            'order_id': order.get('id'),
            'table_id': order.get('masa'),
            'staff_id': order.get('staff_id') or session.get('waiter_id'),
            'staff_name': order.get('garson') or session.get('user'),
            'changes': changes,
            'note': note
        })
        try:
            print_kitchen_revision(order, changes, note)
        except Exception as exc:
            print(f"KITCHEN_REVISION_ERROR: {exc!r}", flush=True)

    return jsonify({'success': True, 'changes': changes})

@app.route('/api/siparisler')
def siparisler():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    orders = load_orders()
    return jsonify(orders)

@app.route('/api/garson/siparisler')
def garson_siparisler():
    if session.get('role') != 'garson':
        return jsonify([])
    orders = load_orders()
    user_name = normalize_staff_name(session.get('user'))
    if not user_name:
        return jsonify([])
    result = [
        o for o in orders
        if o.get('durum') == 'aktif' and normalize_staff_name(o.get('garson')) == user_name
    ]
    return jsonify(result)


@app.route('/api/staff', methods=['GET', 'POST'])
def staff_api():
    if session.get('role') not in ['kasa', 'garson']:
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403

    if request.method == 'GET':
        staff = load_staff()
        return jsonify({'success': True, 'staff': staff})

    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403

    data = request.json or {}
    name = normalize_staff_name(data.get('name'))
    if not name:
        return jsonify({'success': False, 'message': 'Garson adi gerekli.'}), 400

    staff = load_staff()
    next_id = max([int(s.get('id', 0)) for s in staff] + [0]) + 1
    now_iso = now_tr().isoformat()
    item = {
        'id': next_id,
        'name': name,
        'is_active': True,
        'pin_hash': generate_password_hash(str(data.get('pin') or '1234')),
        'created_at': now_iso,
        'updated_at': now_iso
    }
    staff.append(item)
    save_staff(staff)
    return jsonify({'success': True, 'staff': item})

@app.route('/api/staff/<int:staff_id>', methods=['PATCH', 'DELETE'])
def staff_item(staff_id):
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403

    staff = load_staff()
    item = find_staff_by_id(staff, staff_id)
    if not item:
        return jsonify({'success': False, 'message': 'Garson bulunamadi.'}), 404

    now_iso = now_tr().isoformat()
    if request.method == 'DELETE':
        item['is_active'] = False
        item['updated_at'] = now_iso
        save_staff(staff)
        return jsonify({'success': True})

    data = request.json or {}
    name = normalize_staff_name(data.get('name'))
    if name:
        item['name'] = name
    if data.get('pin'):
        item['pin_hash'] = generate_password_hash(str(data.get('pin')))
    if 'is_active' in data:
        item['is_active'] = bool(data.get('is_active'))
    item['updated_at'] = now_iso
    save_staff(staff)
    return jsonify({'success': True, 'staff': item})

@app.route('/api/public-staff')
def public_staff():
    staff = [s for s in load_staff() if s.get('is_active')]
    return jsonify({'success': True, 'staff': staff})

@app.route('/api/staff/stats')
def staff_stats_new():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403

    date_param = request.args.get('date')
    start_param = request.args.get('start')
    end_param = request.args.get('end')
    target_date, stats = compute_staff_stats(date_param, start_param, end_param)
    return jsonify(stats)

@app.route('/api/staff-stats')
def staff_stats_legacy():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403

    date_param = request.args.get('date')
    start_param = request.args.get('start')
    end_param = request.args.get('end')
    target_date, stats = compute_staff_stats(date_param, start_param, end_param)
    return jsonify({'success': True, 'date': target_date, 'stats': stats})

@app.route('/api/staff/<int:staff_id>/product-breakdown')
def staff_product_breakdown(staff_id):
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403

    date_param = request.args.get('date')
    start_param = request.args.get('start')
    end_param = request.args.get('end')
    target_date = to_iso_date(date_param) or None
    start_date = to_iso_date(start_param) or None
    end_date = to_iso_date(end_param) or None
    if start_date and not end_date:
        end_date = start_date
    if end_date and not start_date:
        start_date = end_date
    if not target_date and not start_date:
        target_date = now_tr().date().isoformat()
    orders = load_orders()
    product_counts = {}

    for order in orders:
        order_date = to_iso_date(get_order_date(order))
        if start_date and end_date:
            if not order_date:
                continue
            if order_date < start_date or order_date > end_date:
                continue
        else:
            if order_date != target_date:
                continue
        order_staff_id = order.get('staff_id')
        if staff_id == 0:
            if order_staff_id not in (None, '', 0):
                continue
        else:
            if str(order_staff_id) != str(staff_id):
                continue
        for item in order.get('items') or []:
            name = item.get('name') or item.get('urun')
            if not name:
                continue
            try:
                adet = int(item.get('adet') or 0)
            except Exception:
                adet = 0
            product_counts[name] = product_counts.get(name, 0) + adet

    return jsonify({
        'staff_id': staff_id,
        'date': target_date or start_date or now_tr().date().isoformat(),
        'product_counts': product_counts
    })

@app.route('/api/staff/<int:staff_id>/orders')
def staff_orders(staff_id):
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403

    date_param = request.args.get('date')
    start_param = request.args.get('start')
    end_param = request.args.get('end')
    target_date = to_iso_date(date_param) or None
    start_date = to_iso_date(start_param) or None
    end_date = to_iso_date(end_param) or None
    if start_date and not end_date:
        end_date = start_date
    if end_date and not start_date:
        start_date = end_date
    if not target_date and not start_date:
        target_date = now_tr().date().isoformat()
    orders = load_orders()
    output = []

    for order in orders:
        order_date = to_iso_date(get_order_date(order))
        if start_date and end_date:
            if not order_date:
                continue
            if order_date < start_date or order_date > end_date:
                continue
        else:
            if order_date != target_date:
                continue
        order_staff_id = order.get('staff_id')
        if staff_id == 0:
            if order_staff_id not in (None, '', 0):
                continue
        else:
            if str(order_staff_id) != str(staff_id):
                continue
        items = []
        for item in order.get('items') or []:
            name = item.get('name') or item.get('urun')
            if not name:
                continue
            try:
                adet = int(item.get('adet') or 0)
            except Exception:
                adet = 0
            items.append({'name': name, 'adet': adet})
        output.append({
            'id': order.get('id'),
            'masa': order.get('masa'),
            'zaman': order.get('kapanma_zamani') or order.get('zaman'),
            'tarih': order.get('kapanma_tarih') or order.get('tarih'),
            'toplam': order.get('indirimli_tutar', order.get('toplam', 0)),
            'items': items
        })

    def sort_key(item):
        dt = parse_order_datetime({'tarih': item.get('tarih', ''), 'zaman': item.get('zaman', '00:00')})
        return dt.timestamp() if dt else 0

    output.sort(key=sort_key, reverse=True)

    return jsonify({
        'staff_id': staff_id,
        'date': target_date or start_date or now_tr().date().isoformat(),
        'orders': output
    })


@app.route('/api/kasa-init')
def kasa_init():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403
    orders = cached_load('orders', load_orders, 10)
    tables = cached_load('tables', load_tables, 60)
    rehber = cached_load('rehber', load_rehber_masalar, 60)
    sessions = load_table_sessions()
    bill_requests = load_bill_requests()
    return jsonify({
        'orders': orders,
        'tables': tables,
        'rehber': rehber,
        'table_sessions': sessions,
        'bill_requests': bill_requests
    })

@app.route('/api/tables', methods=['GET', 'POST'])
def handle_tables():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    
    if request.method == 'GET':
        tables = load_tables()
        return jsonify(tables)
    else:
        data = request.json

        save_tables(data)
        return jsonify({'success': True})

@app.route('/api/tables-layout', methods=['GET', 'POST'])
def tables_layout():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403
    if request.method == 'GET':
        area = request.args.get('area', 'salon')
        layout = load_tables_layout(area)
        tables = []
        for table_id, pos in layout.items():
            tables.append({
                'table_id': int(table_id) if str(table_id).isdigit() else table_id,
                'pos_x': pos.get('pos_x', 0),
                'pos_y': pos.get('pos_y', 0),
                'width': pos.get('width', 120),
                'height': pos.get('height', 90),
                'rotation': pos.get('rotation', 0),
                'area': pos.get('area', area)
            })
        return jsonify(tables)
    data = request.get_json() or {}
    area = data.get('area', 'salon')
    tables = data.get('tables')
    if not isinstance(tables, list):
        return jsonify({'success': False, 'message': 'Layout gecersiz.'}), 400
    layout = {}
    for item in tables:
        table_id = item.get('table_id')
        if table_id is None:
            continue
        key = str(table_id)
        layout[key] = {
            'pos_x': int(item.get('pos_x', 0)),
            'pos_y': int(item.get('pos_y', 0)),
            'width': int(item.get('width', 120)),
            'height': int(item.get('height', 90)),
            'rotation': int(item.get('rotation', 0)),
            'area': area
        }
    save_tables_layout(area, layout)
    return jsonify({'success': True})

@app.route('/api/menu', methods=['GET', 'POST'])
def handle_menu():
    if request.method == 'GET':
        menu = load_menu()
        return jsonify(menu)
    else:
        if session.get('role') != 'kasa':
            return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
        data = request.json

        save_json_storage(MENU_FILE, data)
        invalidate_cache('menu')
        return jsonify({'success': True})

@app.route('/api/giderler', methods=['GET', 'POST'])
def giderler_api():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403

    if request.method == 'GET':
        date_val = request.args.get('date')
        start_val = request.args.get('start')
        end_val = request.args.get('end')
        kategori_val = request.args.get('kategori')
        records = load_expenses()
        if start_val or end_val:
            start_iso = normalize_date(start_val) if start_val else None
            end_iso = normalize_date(end_val) if end_val else None
            if start_iso and not end_iso:
                end_iso = start_iso
            if end_iso and not start_iso:
                start_iso = end_iso
            records = [
                r for r in records
                if start_iso <= normalize_date(r.get('date')) <= end_iso
            ]
        elif date_val:
            date_iso = normalize_date(date_val)
            records = [r for r in records if normalize_date(r.get('date')) == date_iso]
        if kategori_val:
            records = [r for r in records if (r.get('kategori') or '').strip() == kategori_val]
        return jsonify({'success': True, 'records': records})

    data = request.json or {}
    date_val = normalize_date(data.get('date'))
    kategori = (data.get('kategori') or '').strip()
    odeme_turu = data.get('odeme_turu')
    aciklama = (data.get('aciklama') or '').strip()

    miktar_val = data.get('miktar')
    birim_fiyat_val = data.get('birim_fiyat')
    miktar = None
    birim_fiyat = None
    if miktar_val not in [None, '']:
        try:
            miktar = float(miktar_val)
        except:
            return jsonify({'success': False, 'message': 'Miktar gecersiz.'}), 400
    if birim_fiyat_val not in [None, '']:
        try:
            birim_fiyat = float(birim_fiyat_val)
        except:
            return jsonify({'success': False, 'message': 'Birim fiyat gecersiz.'}), 400

    tutar_raw = data.get('tutar')
    if tutar_raw in [None, ''] and miktar is not None and birim_fiyat is not None:
        tutar = float(miktar) * float(birim_fiyat)
    else:
        try:
            tutar = float(tutar_raw or 0)
        except:
            return jsonify({'success': False, 'message': 'Tutar gecersiz.'}), 400

    if not date_val:
        return jsonify({'success': False, 'message': 'Tarih gerekli.'}), 400
    if not kategori:
        return jsonify({'success': False, 'message': 'Gider turu gerekli.'}), 400
    if odeme_turu not in ['nakit', 'kart']:
        return jsonify({'success': False, 'message': 'Odeme turu gerekli.'}), 400
    if tutar < 0:
        return jsonify({'success': False, 'message': 'Tutar 0 veya daha buyuk olmali.'}), 400
    if miktar is not None and miktar < 0:
        return jsonify({'success': False, 'message': 'Miktar 0 veya daha buyuk olmali.'}), 400
    if birim_fiyat is not None and birim_fiyat < 0:
        return jsonify({'success': False, 'message': 'Birim fiyat 0 veya daha buyuk olmali.'}), 400

    records = load_expenses()
    new_id = max([r.get('id', 0) for r in records] or [0]) + 1
    record = {
        'id': new_id,
        'date': date_val,
        'kategori': kategori,
        'odeme_turu': odeme_turu,
        'tutar': tutar,
        'aciklama': aciklama
    }
    if miktar is not None:
        record['miktar'] = miktar
    if birim_fiyat is not None:
        record['birim_fiyat'] = birim_fiyat
    records.append(record)
    save_expenses(records)
    return jsonify({'success': True, 'id': new_id})

@app.route('/api/giderler/<int:gid>', methods=['DELETE'])
def gider_sil(gid):
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403
    records = load_expenses()
    records = [r for r in records if r.get('id') != gid]
    save_expenses(records)
    return jsonify({'success': True})

@app.route('/api/giderler/summary')
def giderler_summary():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403
    date_val = request.args.get('date')
    start_val = request.args.get('start')
    end_val = request.args.get('end')
    if not date_val and not (start_val or end_val):
        return jsonify({'success': False, 'message': 'Tarih gerekli.'}), 400
    if start_val or end_val:
        start_iso = normalize_date(start_val) if start_val else None
        end_iso = normalize_date(end_val) if end_val else None
        if start_iso and not end_iso:
            end_iso = start_iso
        if end_iso and not start_iso:
            start_iso = end_iso
        total = sum(
            float(r.get('tutar', 0))
            for r in load_expenses()
            if start_iso <= normalize_date(r.get('date')) <= end_iso
        )
    else:
        total = sum_expenses_for_date(date_val)
    return jsonify({'success': True, 'toplam_gider': total})

@app.route('/api/closed-checks')
def closed_checks():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403
    date_val = request.args.get('date')
    start_val = request.args.get('start')
    end_val = request.args.get('end')
    target_date = normalize_date(date_val) if date_val else None
    start_iso = normalize_date(start_val) if start_val else None
    end_iso = normalize_date(end_val) if end_val else None
    if start_iso and not end_iso:
        end_iso = start_iso
    if end_iso and not start_iso:
        start_iso = end_iso
    records = []
    for check in load_closed_checks():
        dt = parse_iso_datetime(check.get('closed_at')) or parse_iso_datetime(check.get('opened_at') or '')
        if not dt:
            continue
        date_iso = dt.date().isoformat()
        if start_iso and end_iso:
            if date_iso < start_iso or date_iso > end_iso:
                continue
        elif target_date and date_iso != target_date:
            continue
        records.append(check)
    records.sort(key=lambda x: x.get('closed_at') or '', reverse=True)
    return jsonify({'success': True, 'records': records})

@app.route('/api/closed-checks/<int:check_id>')
def closed_check_items(check_id):
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403
    items = [i for i in load_closed_check_items() if str(i.get('check_id')) == str(check_id)]
    return jsonify({'success': True, 'items': items})

@app.route('/api/otopark-gider', methods=['POST'])
def otopark_gider():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    
    data = request.json

    tutar = data.get('tutar', 50)  # Varsayılan 50 TL
    
    orders = load_orders()
    
    gider_kaydi = {
        'id': len(orders) + 1,
        'masa': 'Otopark',
        'garson': 'Sistem',
        'items': [{'name': 'Otopark Gideri', 'adet': 1, 'fiyat': -tutar}],
        'toplam': -tutar,
        'zaman': now_tr().strftime('%H:%M'),
        'tarih': now_tr().strftime('%d.%m.%Y'),
        'kapanma_tarih': now_tr().strftime('%Y-%m-%d'),
        'durum': 'kapali',
        'tip': 'gider',
        'odeme_turu': 'nakit'
    }
    
    orders.append(gider_kaydi)
    save_orders(orders)
    
    return jsonify({'success': True, 'message': f'{tutar} TL otopark gideri kaydedildi'})

@app.route('/api/otopark-ayarlar', methods=['GET', 'POST'])
def otopark_ayarlar():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    
    if request.method == 'GET':
        try:
            config = load_json_storage(OTOPARK_CONFIG_FILE, {'otopark_fiyat': 50})
            return jsonify(config)
        except:
            return jsonify({'otopark_fiyat': 50})
    else:
        data = request.json

        save_json_storage(OTOPARK_CONFIG_FILE, data)
        return jsonify({'success': True})

@app.route('/api/hesap/<int:masa>')
def hesap_getir(masa):
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403
    t0 = time.time()
    orders = load_orders()
    t1 = time.time()
    masa_orders = [o for o in orders if o['masa'] == masa and o['durum'] == 'aktif']
    subtotal = sum(o['toplam'] for o in masa_orders)
    discounts = load_table_discounts()
    discount = discounts.get(str(masa))
    discount_amount = compute_discount_amount(subtotal, discount)
    toplam = round(subtotal - discount_amount, 2)
    t2 = time.time()
    print("hesap_getir timings:", "load_orders=", round(t1 - t0, 3), "compute=", round(t2 - t1, 3), "total=", round(t2 - t0, 3))
    return jsonify({
        'masa': masa,
        'siparisler': masa_orders,
        'subtotal': round(subtotal, 2),
        'discount': discount or None,
        'discount_amount': discount_amount,
        'total_due': toplam,
        'toplam': toplam,
        'discount_order_id': masa_orders[0].get('id') if masa_orders else None
    })

@app.route('/api/tables/<int:table_id>/print-bill', methods=['POST'])
def print_bill_api(table_id):
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403
    data = request.json or {}
    lang = data.get('lang')
    if not lang:
        return jsonify({'success': False, 'error': 'LANG_REQUIRED'}), 400
    if lang not in ('tr', 'en'):
        return jsonify({'success': False, 'error': 'LANG_INVALID'}), 400
    orders = load_orders()
    masa_orders = [o for o in orders if o.get('masa') == table_id and o.get('durum') == 'aktif']
    if not masa_orders:
        return jsonify({'success': False, 'message': 'Aktif siparis bulunamadi.'}), 400
    try:
        print_bill(table_id, masa_orders, lang)
    except Exception as exc:
        return jsonify({'success': False, 'message': str(exc)}), 500
    return jsonify({'success': True})

@app.route('/api/tables/<int:table_id>/bill-preview')
def bill_preview_api(table_id):
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403
    lang = request.args.get('lang')
    if lang and lang not in ('tr', 'en'):
        return jsonify({'success': False, 'error': 'LANG_INVALID'}), 400
    orders = load_orders()
    masa_orders = [o for o in orders if o.get('masa') == table_id and o.get('durum') == 'aktif']
    if not masa_orders:
        return jsonify({'success': False, 'message': 'Aktif siparis bulunamadi.'}), 400
    payload = build_bill_payload(table_id, masa_orders)
    text = build_bill_text(payload, 32, lang or 'tr')
    return jsonify({
        'table_id': table_id,
        'lang': lang or 'tr',
        'text': text,
        'total': payload['total'],
        'lines': payload['items']
    })

@app.route('/api/orders/<int:order_id>/payments', methods=['GET', 'POST'])
def order_payments(order_id):
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403

    orders = load_orders()
    order = next((o for o in orders if str(o.get('id')) == str(order_id)), None)
    if not order:
        return jsonify({'success': False, 'message': 'Siparis bulunamadi.'}), 404

    if request.method == 'GET':
        payments = load_payments()
        items = [p for p in payments if str(p.get('order_id')) == str(order_id)]
        return jsonify({'order_id': order_id, 'payments': items})

    data = request.json or {}

    manual = data.get('manual')
    if manual:
        pay_type = normalize_payment_type(manual.get('payment_type') or manual.get('type') or manual.get('odeme_turu'))
        if pay_type not in ['cash', 'card', 'qr', 'other']:
            return jsonify({'success': False, 'message': 'Odeme turu gecersiz.'}), 400
        override_total = manual.get('override_total')
        discount_enabled = bool(manual.get('discount_enabled'))
        discount_type = manual.get('discount_type')
        discount_value = manual.get('discount_value')
        note = (manual.get('note') or '').strip()
        base_total = float(order.get('toplam', 0) or 0)
        manual_due = base_total
        if override_total not in [None, '']:
            try:
                manual_due = float(override_total)
            except Exception:
                return jsonify({'success': False, 'message': 'Tahsil tutari gecersiz.'}), 400
        elif discount_enabled:
            try:
                dv = float(discount_value or 0)
            except Exception:
                return jsonify({'success': False, 'message': 'Indirim degeri gecersiz.'}), 400
            if dv <= 0:
                return jsonify({'success': False, 'message': 'Indirim degeri gerekli.'}), 400
            if discount_type == 'percent':
                manual_due = base_total * (1 - dv / 100)
            elif discount_type == 'amount':
                manual_due = base_total - dv
            else:
                return jsonify({'success': False, 'message': 'Indirim tipi gecersiz.'}), 400
        if manual_due < 0:
            return jsonify({'success': False, 'message': 'Tahsil tutari 0 olamaz.'}), 400
        manual_due = round(manual_due, 2)
        order['durum'] = 'kapali'
        order['kapanma_zamani'] = now_tr().strftime('%H:%M')
        order['kapanma_tarih'] = now_tr().strftime('%d.%m.%Y')
        order['odeme_breakdown'] = { pay_type: manual_due }
        order['paid_total'] = manual_due
        order['is_paid'] = True
        order['paid_at'] = now_tr().isoformat()
        actor = get_actor_info(order.get('staff_id'), order.get('garson'))
        order['odeme_turu'] = payment_label_from_type(pay_type)
        order['indirimli_tutar'] = manual_due
        order['indirim'] = round(max(0, order.get('toplam', 0) - manual_due), 2)
        order['manual_payment'] = {
            'payment_type': pay_type,
            'discount_enabled': discount_enabled,
            'discount_type': discount_type,
            'discount_value': discount_value,
            'override_total': override_total,
            'note': note
        }
        order['paid_by_staff_id'] = actor.get('staff_id')
        order['paid_by_staff_name'] = actor.get('staff_name')
        archive_closed_order(order, actor)

        payments_store = load_payments()
        payments_store.append({
            'id': len(payments_store) + 1,
            'order_id': order_id,
            'table_id': order.get('masa'),
            'type': pay_type,
            'amount': manual_due,
            'meta_json': {
                'manual': True,
                'discount_enabled': discount_enabled,
                'discount_type': discount_type,
                'discount_value': discount_value,
                'override_total': override_total,
                'note': note
            },
            'created_at': now_tr().isoformat(),
            'staff_id': actor.get('staff_id'),
            'staff_name': actor.get('staff_name')
        })
        save_payments(payments_store)
        save_orders(orders)
        append_activity('MANUAL_PAYMENT', {
            'order_id': order_id,
            'table_id': order.get('masa'),
            'total': manual_due,
            'payment_type': pay_type,
            'staff_id': actor.get('staff_id'),
            'staff_name': actor.get('staff_name')
        })
        return jsonify({'success': True})
    payments_input = data.get('payments')
    if not payments_input:
        return jsonify({'success': False, 'message': 'Odeme listesi gerekli.'}), 400

    if order.get('durum') == 'kapali' and order.get('is_paid'):
        return jsonify({'success': False, 'message': 'Siparis zaten odendi.'}), 409

    discount_flag = data.get('discount_applied')
    allow_discount = False if discount_flag is False else True
    force_discount = True if discount_flag is True else False
    try:
        result = apply_payments_to_orders([order], payments_input, allow_discount, force_discount)
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400

    actor = get_actor_info(order.get('staff_id'), order.get('garson'))
    breakdown = result['breakdowns'].get(order['id'], {})
    cash_only = result['cash_only']
    card_only = result['card_only']
    due = result['due_map'].get(order['id'], order.get('toplam', 0))

    order['durum'] = 'kapali'
    order['kapanma_zamani'] = now_tr().strftime('%H:%M')
    order['kapanma_tarih'] = now_tr().strftime('%d.%m.%Y')
    order['odeme_breakdown'] = breakdown
    order['paid_total'] = due
    order['is_paid'] = True
    order['paid_at'] = now_tr().isoformat()
    if cash_only:
        order['odeme_turu'] = 'nakit'
        order['indirim'] = order['toplam'] * 0.1
        order['indirimli_tutar'] = round(order['toplam'] * 0.9, 2)
    else:
        order['odeme_turu'] = 'kart' if card_only else 'split'
        order['indirim'] = 0
        order['indirimli_tutar'] = order.get('toplam', 0)

    order['paid_by_staff_id'] = actor.get('staff_id')
    order['paid_by_staff_name'] = actor.get('staff_name')
    archive_closed_order(order, actor)

    save_orders(orders)

    bill_requests = load_bill_requests()
    bill_requests.pop(str(order.get('masa')), None)
    save_bill_requests(bill_requests)

    payments_store = load_payments()
    for payment in result['payments']:
        payments_store.append({
            'id': len(payments_store) + 1,
            'order_id': order_id,
            'table_id': order.get('masa'),
            'type': payment['type'],
            'amount': round(payment['amount'], 2),
            'meta_json': payment.get('meta') or {},
            'created_at': now_tr().isoformat(),
            'staff_id': actor.get('staff_id'),
            'staff_name': actor.get('staff_name')
        })
    save_payments(payments_store)

    append_activity('PAYMENT', {
        'order_id': order_id,
        'table_id': order.get('masa'),
        'total': order.get('indirimli_tutar', order.get('toplam', 0)),
        'payment_type': order.get('odeme_turu'),
        'staff_id': actor.get('staff_id'),
        'staff_name': actor.get('staff_name')
    })

    return jsonify({'success': True})

@app.route('/api/orders/<int:order_id>/discount', methods=['POST', 'DELETE'])
def order_discount(order_id):
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403

    orders = load_orders()
    order = next((o for o in orders if str(o.get('id')) == str(order_id)), None)
    if not order:
        return jsonify({'success': False, 'message': 'Siparis bulunamadi.'}), 404
    if order.get('durum') != 'aktif':
        return jsonify({'success': False, 'message': 'Siparis kapali.'}), 400

    table_id = order.get('masa')
    if request.method == 'DELETE':
        discounts = load_table_discounts()
        if str(table_id) in discounts:
            del discounts[str(table_id)]
            save_table_discounts(discounts)
        for o in orders:
            if o.get('masa') == table_id and o.get('durum') == 'aktif':
                o['discount_type'] = None
                o['discount_value'] = None
                o['discount_reason'] = None
                o['discount_note'] = None
                o['discount_applied_by'] = None
                o['discount_applied_at'] = None
                o['discount_amount'] = 0
        save_orders(orders)
        actor = get_actor_info()
        append_activity('DISCOUNT_REMOVE', {
            'table_id': table_id,
            'staff_id': actor.get('staff_id'),
            'staff_name': actor.get('staff_name')
        })
        return jsonify({'success': True})

    data = request.json or {}
    dtype = data.get('type')
    reason = data.get('reason')
    note = (data.get('note') or '').strip()
    try:
        value = float(data.get('value') or 0)
    except Exception:
        value = 0.0

    if dtype not in ('percent', 'amount'):
        return jsonify({'success': False, 'message': 'Indirim tipi gecersiz.'}), 400
    if value <= 0:
        return jsonify({'success': False, 'message': 'Indirim degeri gerekli.'}), 400
    if dtype == 'percent' and (value < 1 or value > 100):
        return jsonify({'success': False, 'message': 'Indirim y\u00fczdesi 1-100 araliginda olmalidir.'}), 400
    if reason not in ('tanidik', 'personel', 'hata', 'diger'):
        return jsonify({'success': False, 'message': 'Indirim sebebi gecersiz.'}), 400
    if reason == 'diger' and not note:
        return jsonify({'success': False, 'message': 'Aciklama gerekli.'}), 400

    subtotal = sum(o.get('toplam', 0) for o in orders if o.get('masa') == table_id and o.get('durum') == 'aktif')
    if subtotal <= 0:
        return jsonify({'success': False, 'message': 'Indirim uygulanacak tutar yok.'}), 400
    if dtype == 'amount' and value > subtotal:
        return jsonify({'success': False, 'message': 'Indirim tutari toplamdan buyuk olamaz.'}), 400

    discount = {
        'type': dtype,
        'value': value,
        'reason': reason,
        'note': note,
        'applied_by': session.get('user') or 'Kasa',
        'applied_at': now_tr().isoformat(timespec='seconds')
    }
    discounts = load_table_discounts()
    discounts[str(table_id)] = discount
    save_table_discounts(discounts)

    for o in orders:
        if o.get('masa') == table_id and o.get('durum') == 'aktif':
            o['discount_type'] = dtype
            o['discount_value'] = value
            o['discount_reason'] = reason
            o['discount_note'] = note
            o['discount_applied_by'] = discount['applied_by']
            o['discount_applied_at'] = discount['applied_at']
    save_orders(orders)

    amount = compute_discount_amount(subtotal, discount)
    return jsonify({'success': True, 'discount': discount, 'discount_amount': amount})

@app.route('/api/orders/recent-closures')
def recent_closures():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403
    try:
        limit = int(request.args.get('limit') or 20)
    except Exception:
        limit = 20
    limit = max(1, min(50, limit))
    orders = load_orders()
    tables = load_tables()
    items = []
    for order in orders:
        if order.get('durum') != 'kapali':
            continue
        dt = parse_closed_datetime(order)
        if not dt:
            continue
        payment_label = ''
        ot = order.get('odeme_turu')
        if ot == 'nakit':
            payment_label = 'Nakit'
        elif ot == 'kart':
            payment_label = 'Kart'
        elif ot == 'split':
            payment_label = 'Parcali'
        items.append({
            'order_id': order.get('id'),
            'table_id': order.get('masa'),
            'table_name': tables.get(str(order.get('masa'))) or f"Masa {order.get('masa')}",
            'closed_at': dt.isoformat(),
            'closed_time': dt.strftime('%H:%M'),
            'total': order.get('indirimli_tutar') or order.get('paid_total') or order.get('toplam') or 0,
            'total_text': f"\u20ba{float(order.get('indirimli_tutar') or order.get('paid_total') or order.get('toplam') or 0):.2f}",
            'payment_label': payment_label or '-',
            'staff_name': order.get('garson') or 'Bilinmiyor'
        })
    items.sort(key=lambda x: x.get('closed_at') or '', reverse=True)
    return jsonify(items[:limit])

@app.route('/api/orders/<int:order_id>/reopen', methods=['POST'])
def reopen_order(order_id):
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403
    orders = load_orders()
    order = next((o for o in orders if str(o.get('id')) == str(order_id)), None)
    if not order:
        return jsonify({'success': False, 'message': 'Siparis bulunamadi.'}), 404
    if order.get('durum') != 'kapali':
        return jsonify({'success': False, 'message': 'Siparis zaten acik.'}), 409
    table_id = order.get('masa')
    if any(o.get('durum') == 'aktif' and str(o.get('masa')) == str(table_id) for o in orders):
        return jsonify({'success': False, 'message': 'Masa zaten acik.'}), 409

    order['durum'] = 'aktif'
    order['kapanma_zamani'] = None
    order['kapanma_tarih'] = None
    order['is_paid'] = False
    order['paid_total'] = 0
    order['paid_at'] = None
    order['odeme_turu'] = None
    order['odeme_breakdown'] = {}
    order['indirimli_tutar'] = order.get('toplam', 0)
    order['indirim'] = 0

    sessions = load_table_sessions()
    if str(table_id) not in sessions:
        sessions[str(table_id)] = order.get('masa_acilis_ts') or now_tr().isoformat()
        save_table_sessions(sessions)

    payments_store = load_payments()
    for payment in payments_store:
        if str(payment.get('order_id')) == str(order_id):
            payment['status'] = 'void'
            payment['voided_at'] = now_tr().isoformat()
            payment['void_reason'] = 'reopened'
    save_payments(payments_store)
    save_orders(orders)
    return jsonify({'success': True, 'order_id': order_id, 'table_id': table_id})

@app.route('/api/tables/<int:table_id>/bill-requested', methods=['POST'])
def set_bill_requested(table_id):
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403
    data = request.json or {}
    value = bool(data.get('value'))
    orders = load_orders()
    if value:
        if not any(o.get('durum') == 'aktif' and str(o.get('masa')) == str(table_id) for o in orders):
            return jsonify({'success': False, 'message': 'Aktif siparis yok.'}), 400
    bill_requests = load_bill_requests()
    if value:
        bill_requests[str(table_id)] = {
            'value': True,
            'at': now_tr().isoformat()
        }
    else:
        bill_requests.pop(str(table_id), None)
    save_bill_requests(bill_requests)
    return jsonify({
        'success': True,
        'table_id': table_id,
        'bill_requested': value,
        'bill_requested_at': bill_requests.get(str(table_id), {}).get('at')
    })

@app.route('/api/hesap_kapat/<int:masa>', methods=['POST'])

def hesap_kapat(masa):
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403

    data = request.json or {}
    payments = data.get('payments')
    odeme_turu = data.get('odeme_turu')

    orders = load_orders()
    payments_store = load_payments()
    rehber_masalar = load_rehber_masalar()
    toplam_tutar = 0.0

    masa_rehber_durumu = rehber_masalar.get(str(masa), False)
    masa_orders = [o for o in orders if o.get('masa') == masa and o.get('durum') == 'aktif']
    fallback_staff_id = masa_orders[0].get('staff_id') if masa_orders else None
    fallback_staff_name = masa_orders[0].get('garson') if masa_orders else None

    if not masa_orders:
        return jsonify({'success': False, 'message': 'Aktif siparis bulunamadi.'}), 400

    toplam_tutar = sum(o.get('toplam', 0) for o in masa_orders)
    discounts = load_table_discounts()
    table_discount = discounts.get(str(masa))
    discount_amount = compute_discount_amount(toplam_tutar, table_discount)
    discounted_subtotal = round(toplam_tutar - discount_amount, 2)

    adjusted_orders = []
    discount_shares = {}
    for order in masa_orders:
        share = (order.get('toplam', 0) / toplam_tutar) if toplam_tutar > 0 else 0
        share_amount = round(discount_amount * share, 2)
        adjusted_orders.append({**order, 'toplam': round(order.get('toplam', 0) - share_amount, 2)})
        discount_shares[order['id']] = share_amount

    manual = data.get('manual')
    if manual:
        pay_type = normalize_payment_type(manual.get('payment_type') or manual.get('type') or manual.get('odeme_turu'))
        if pay_type not in ['cash', 'card', 'qr', 'other']:
            return jsonify({'success': False, 'message': 'Odeme turu gecersiz.'}), 400
        override_total = manual.get('override_total')
        discount_enabled = bool(manual.get('discount_enabled'))
        discount_type = manual.get('discount_type')
        discount_value = manual.get('discount_value')
        note = (manual.get('note') or '').strip()

        base_total = discounted_subtotal
        manual_due = base_total
        if override_total not in [None, '']:
            try:
                manual_due = float(override_total)
            except Exception:
                return jsonify({'success': False, 'message': 'Tahsil tutari gecersiz.'}), 400
        elif discount_enabled:
            try:
                dv = float(discount_value or 0)
            except Exception:
                return jsonify({'success': False, 'message': 'Indirim degeri gecersiz.'}), 400
            if dv <= 0:
                return jsonify({'success': False, 'message': 'Indirim degeri gerekli.'}), 400
            if discount_type == 'percent':
                manual_due = base_total * (1 - dv / 100)
            elif discount_type == 'amount':
                manual_due = base_total - dv
            else:
                return jsonify({'success': False, 'message': 'Indirim tipi gecersiz.'}), 400

        if manual_due < 0:
            return jsonify({'success': False, 'message': 'Tahsil tutari 0 olamaz.'}), 400

        manual_due = round(manual_due, 2)
        actor = get_actor_info(fallback_staff_id, fallback_staff_name)
        for order in masa_orders:
            share = (order.get('toplam', 0) / toplam_tutar) if toplam_tutar > 0 else 0
            order_due = round(manual_due * share, 2)
            order['durum'] = 'kapali'
            order['kapanma_zamani'] = now_tr().strftime('%H:%M')
            order['kapanma_tarih'] = now_tr().strftime('%d.%m.%Y')
            order['rehber_masa'] = masa_rehber_durumu
            order['odeme_breakdown'] = { pay_type: order_due }
            order['paid_total'] = order_due
            order['is_paid'] = True
            order['paid_at'] = now_tr().isoformat()
            order['odeme_turu'] = payment_label_from_type(pay_type)
            order['indirimli_tutar'] = round(order_due, 2)
            order['indirim'] = round(max(0, order.get('toplam', 0) - order_due), 2)
            order['manual_payment'] = {
                'payment_type': pay_type,
                'discount_enabled': discount_enabled,
                'discount_type': discount_type,
                'discount_value': discount_value,
                'override_total': override_total,
                'note': note
            }
            order['paid_by_staff_id'] = actor.get('staff_id')
            order['paid_by_staff_name'] = actor.get('staff_name')
            archive_closed_order(order, actor)

            payments_store.append({
                'id': len(payments_store) + 1,
                'order_id': order.get('id'),
                'table_id': order.get('masa'),
                'type': pay_type,
                'amount': round(order_due, 2),
                'meta_json': {
                    'manual': True,
                    'discount_enabled': discount_enabled,
                    'discount_type': discount_type,
                    'discount_value': discount_value,
                    'override_total': override_total,
                    'note': note
                },
                'created_at': now_tr().isoformat(),
                'staff_id': actor.get('staff_id'),
                'staff_name': actor.get('staff_name')
            })

        bill_requests = load_bill_requests()
        bill_requests.pop(str(masa), None)
        save_bill_requests(bill_requests)
        save_orders(orders)
        save_payments(payments_store)
        finalize_table_session(masa, orders)
        append_activity('MANUAL_PAYMENT', {
            'table_id': masa,
            'total': manual_due,
            'payment_type': pay_type,
            'staff_id': actor.get('staff_id'),
            'staff_name': actor.get('staff_name')
        })
        return jsonify({'success': True, 'manual_total': manual_due})


    actor = get_actor_info(fallback_staff_id, fallback_staff_name)
    if payments:
        discount_flag = data.get('discount_applied')
        allow_discount = False if discount_flag is False else True
        force_discount = True if discount_flag is True else False
        try:
            result = apply_payments_to_orders(adjusted_orders, payments, allow_discount, force_discount)
        except ValueError as exc:
            return jsonify({'success': False, 'message': str(exc)}), 400

        breakdowns = result['breakdowns']
        due_map = result['due_map']
        cash_only = result['cash_only']
        card_only = result['card_only']

        for order in masa_orders:
            order['durum'] = 'kapali'
            order['kapanma_zamani'] = now_tr().strftime('%H:%M')
            order['kapanma_tarih'] = now_tr().strftime('%d.%m.%Y')
            order['rehber_masa'] = masa_rehber_durumu
            order['odeme_breakdown'] = breakdowns.get(order['id'], {})
            order['paid_total'] = due_map.get(order['id'], order.get('toplam', 0))
            order['is_paid'] = True
            order['paid_at'] = now_tr().isoformat()
            order['odeme_turu'] = 'nakit' if cash_only else ('kart' if card_only else 'split')
            order['indirimli_tutar'] = round(due_map.get(order['id'], order.get('toplam', 0)), 2)
            order['indirim'] = round(order.get('toplam', 0) - order['indirimli_tutar'], 2)
            if table_discount:
                order['discount_type'] = table_discount.get('type')
                order['discount_value'] = table_discount.get('value')
                order['discount_reason'] = table_discount.get('reason')
                order['discount_note'] = table_discount.get('note')
                order['discount_applied_by'] = table_discount.get('applied_by')
                order['discount_applied_at'] = table_discount.get('applied_at')
                order['discount_amount'] = discount_shares.get(order['id'], 0)
            order['paid_by_staff_id'] = actor.get('staff_id')
            order['paid_by_staff_name'] = actor.get('staff_name')
            archive_closed_order(order, actor)

        bill_requests = load_bill_requests()
        bill_requests.pop(str(masa), None)
        save_bill_requests(bill_requests)

        for payment in result['payments']:
            for order in masa_orders:
                payment_amount = breakdowns.get(order['id'], {}).get(payment['type'], 0)
                if payment_amount <= 0:
                    continue
                payments_store.append({
                    'id': len(payments_store) + 1,
                    'order_id': order.get('id'),
                    'table_id': masa,
                    'type': payment['type'],
                    'amount': round(payment_amount, 2),
                    'meta_json': payment.get('meta') or {},
                    'created_at': now_tr().isoformat(),
                    'staff_id': actor.get('staff_id'),
                    'staff_name': actor.get('staff_name')
                })

        save_payments(payments_store)
        append_activity('PAYMENT', {
            'table_id': masa,
            'payment_type': 'split' if not (cash_only or card_only) else ('cash' if cash_only else 'card'),
            'total': sum(o.get('indirimli_tutar', 0) for o in masa_orders),
            'staff_id': actor.get('staff_id'),
            'staff_name': actor.get('staff_name')
        })
    else:
        if odeme_turu not in ['nakit', 'kart']:
            return jsonify({'success': False, 'message': 'Odeme turu gerekli.'}), 400
        total_due = discounted_subtotal
        if odeme_turu == 'nakit':
            total_due = round(total_due * 0.9, 2)
        due_map = allocate_due_map(adjusted_orders, total_due)

        for order in masa_orders:
            order['durum'] = 'kapali'
            order['kapanma_zamani'] = now_tr().strftime('%H:%M')
            order['kapanma_tarih'] = now_tr().strftime('%d.%m.%Y')
            order['odeme_turu'] = odeme_turu
            order['rehber_masa'] = masa_rehber_durumu
            order['indirimli_tutar'] = round(due_map.get(order['id'], order.get('toplam', 0)), 2)
            order['indirim'] = round(order.get('toplam', 0) - order['indirimli_tutar'], 2)
            order['odeme_breakdown'] = { normalize_payment_type(odeme_turu): order['indirimli_tutar'] }
            order['paid_total'] = order['indirimli_tutar']
            order['is_paid'] = True
            order['paid_at'] = now_tr().isoformat()
            if table_discount:
                order['discount_type'] = table_discount.get('type')
                order['discount_value'] = table_discount.get('value')
                order['discount_reason'] = table_discount.get('reason')
                order['discount_note'] = table_discount.get('note')
                order['discount_applied_by'] = table_discount.get('applied_by')
                order['discount_applied_at'] = table_discount.get('applied_at')
                order['discount_amount'] = discount_shares.get(order['id'], 0)
            order['paid_by_staff_id'] = actor.get('staff_id')
            order['paid_by_staff_name'] = actor.get('staff_name')
            archive_closed_order(order, actor)
            payments_store.append({
                'id': len(payments_store) + 1,
                'order_id': order.get('id'),
                'table_id': masa,
                'type': normalize_payment_type(odeme_turu),
                'amount': round(order['indirimli_tutar'], 2),
                'meta_json': {},
                'created_at': now_tr().isoformat(),
                'staff_id': actor.get('staff_id'),
                'staff_name': actor.get('staff_name')
            })

        save_payments(payments_store)
        append_activity('PAYMENT', {
            'table_id': masa,
            'payment_type': normalize_payment_type(odeme_turu),
            'total': sum(o.get('indirimli_tutar', 0) for o in masa_orders),
            'staff_id': actor.get('staff_id'),
            'staff_name': actor.get('staff_name')
        })

    save_orders(orders)

    if str(masa) in rehber_masalar:
        rehber_masalar[str(masa)] = False
        save_rehber_masalar(rehber_masalar)

    finalize_table_session(masa, orders)
    if str(masa) in discounts:
        del discounts[str(masa)]
        save_table_discounts(discounts)

    response = {'success': True}
    if odeme_turu == 'nakit' and not payments:
        response['indirimli_tutar'] = int(discounted_subtotal * 0.9)
    return jsonify(response)

@app.route('/api/masa-transfer', methods=['POST'])
def masa_transfer():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    
    data = request.json

    kaynak_masa = data.get('kaynak_masa')
    hedef_masa = data.get('hedef_masa')
    
    if not kaynak_masa or not hedef_masa:
        return jsonify({'success': False, 'message': 'Kaynak ve hedef masa belirtilmeli!'})
    
    if kaynak_masa == hedef_masa:
        return jsonify({'success': False, 'message': 'Kaynak ve hedef masa aynı olamaz!'})
    
    orders = load_orders()
    transfer_count = 0
    
    for order in orders:
        if order['masa'] == kaynak_masa and order['durum'] == 'aktif':
            order['masa'] = hedef_masa
            transfer_count += 1
    
    save_orders(orders)
    
    return jsonify({
        'success': True,
        'transfer_count': transfer_count,
        'message': f'{transfer_count} sipariş {kaynak_masa} numaralı masadan {hedef_masa} numaralı masaya taşındı.'
    })

@app.route('/api/rehber-masa/<int:masa>', methods=['POST'])
def rehber_masa_toggle(masa):
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    
    rehber_masalar = load_rehber_masalar()
    masa_str = str(masa)
    
    rehber_masalar[masa_str] = not rehber_masalar.get(masa_str, False)
    save_rehber_masalar(rehber_masalar)
    
    return jsonify({'success': True, 'rehber': rehber_masalar[masa_str]})

@app.route('/api/rehber-masalar')
def get_rehber_masalar():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    
    return jsonify(load_rehber_masalar())

@app.route('/api/komisyonlar-tarih')
def get_komisyonlar_tarih():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    
    tarih = request.args.get('tarih')
    start_param = request.args.get('start')
    end_param = request.args.get('end')
    orders = load_orders()
    closed_checks = load_closed_checks()
    closed_items = load_closed_check_items()
    
    start_date = to_iso_date(start_param) if start_param else None
    end_date = to_iso_date(end_param) if end_param else None
    if start_date and not end_date:
        end_date = start_date
    if end_date and not start_date:
        start_date = end_date

    if not tarih:
        bugun_iso = now_tr().strftime('%Y-%m-%d')
        bugun_tr = now_tr().strftime('%d.%m.%Y')
        tarih = bugun_tr
        tarih_iso = bugun_iso
    else:
        if '.' in tarih:
            gun, ay, yil = tarih.split('.')
            tarih_iso = f"{yil}-{ay.zfill(2)}-{gun.zfill(2)}"
        else:
            tarih_iso = tarih
            parts = tarih.split('-')
            tarih = f"{parts[2]}.{parts[1]}.{parts[0]}"
    
    tarih_orders = []
    for order in orders:
        if order['durum'] != 'kapali':
            continue
        
        order_tarih = order.get('tarih', '')
        order_iso = to_iso_date(order_tarih)
        kapanma_tarih = order.get('kapanma_tarih', '')
        kapanma_iso = to_iso_date(kapanma_tarih)
        
        if start_date and end_date:
            for iso_val in (order_iso, kapanma_iso):
                if iso_val and start_date <= iso_val <= end_date:
                    tarih_orders.append(order)
                    break
            continue
        if (order_tarih == tarih or order_tarih == tarih_iso or
            kapanma_tarih == tarih or kapanma_tarih == tarih_iso):
            tarih_orders.append(order)
    
    komisyon_listesi = []
    
    for order in tarih_orders:
        if not order.get('rehber_masa', False):
            continue
            
        serpme_adet = 0
        for item in order['items']:
            if item['name'] == 'Serpme Kahvaltı':
                serpme_adet += item['adet']
        
        if serpme_adet > 0:
            komisyon_tutari = serpme_adet * 100
            komisyon_listesi.append({
                'masa': order['masa'],
                'serpme_adet': serpme_adet,
                'komisyon': komisyon_tutari,
                'zaman': order.get('kapanma_zamani', order['zaman']),
                'tarih': kapanma_tarih or order_tarih
            })
    
    toplam_komisyon = sum(k['komisyon'] for k in komisyon_listesi)
    
    return jsonify({
        'komisyonlar': komisyon_listesi,
        'toplam_komisyon': toplam_komisyon,
        'toplam_serpme': sum(k['serpme_adet'] for k in komisyon_listesi)
    })

@app.route('/api/istatistik-data')

def istatistik_data():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403

    tarih = request.args.get('tarih')
    start_param = request.args.get('start')
    end_param = request.args.get('end')
    orders = load_orders()
    closed_checks = load_closed_checks()
    closed_items = load_closed_check_items()

    start_date = to_iso_date(start_param) if start_param else None
    end_date = to_iso_date(end_param) if end_param else None
    if start_date and not end_date:
        end_date = start_date
    if end_date and not start_date:
        start_date = end_date

    tarih_iso = None
    if not start_date:
        if not tarih:
            bugun_iso = now_tr().strftime('%Y-%m-%d')
            bugun_tr = now_tr().strftime('%d.%m.%Y')
            tarih = bugun_tr
            tarih_iso = bugun_iso
        else:
            if '.' in tarih:
                gun, ay, yil = tarih.split('.')
                tarih_iso = f"{yil}-{ay.zfill(2)}-{gun.zfill(2)}"
            else:
                tarih_iso = tarih
                parts = tarih.split('-')
                if len(parts) >= 3:
                    tarih = f"{parts[2]}.{parts[1]}.{parts[0]}"

    def _filter_closed_checks(records, start_iso, end_iso, single_iso):
        selected = []
        for check in records or []:
            dt = parse_iso_datetime(check.get('closed_at') or check.get('opened_at') or '')
            if not dt:
                continue
            day = dt.date().isoformat()
            if start_iso and end_iso:
                if day < start_iso or day > end_iso:
                    continue
            else:
                if day != single_iso:
                    continue
            selected.append(check)
        return selected

    def _get_check_payment_amount(check, kind):
        pb = check.get('payment_breakdown') or {}
        if kind in pb:
            try:
                return float(pb.get(kind) or 0)
            except Exception:
                return 0
        ptype = (check.get('payment_type') or '').lower()
        total = check.get('total') or 0
        if kind == 'cash' and ptype in ['nakit', 'cash']:
            return total
        if kind == 'card' and ptype in ['kart', 'card']:
            return total
        if kind == 'qr' and ptype in ['qr']:
            return total
        if kind == 'other' and ptype in ['diger', 'other']:
            return total
        return 0

    tarih_orders = []
    tarih_checks = _filter_closed_checks(closed_checks, start_date, end_date, tarih_iso) if closed_checks else []

    if tarih_checks:
        toplam_ciro = sum((c.get('total') or 0) for c in tarih_checks)
    else:
        for order in orders:
            if order.get('durum') != 'kapali':
                continue

            order_date = to_iso_date(get_order_date(order))
            if start_date and end_date:
                if not order_date:
                    continue
                if order_date < start_date or order_date > end_date:
                    continue
            else:
                if order_date != tarih_iso:
                    continue

            tarih_orders.append(order)

        toplam_ciro = sum(o.get('indirimli_tutar', o.get('toplam', 0)) for o in tarih_orders)

    if start_date and end_date:
        toplam_gider = 0
        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date)
        cursor = start_dt
        while cursor <= end_dt:
            toplam_gider += sum_expenses_for_date(cursor.strftime('%Y-%m-%d'))
            cursor += timedelta(days=1)
        tarih_str = start_date if start_date == end_date else f"{start_date} - {end_date}"
    else:
        toplam_gider = sum_expenses_for_date(tarih_iso)
        tarih_str = tarih

    net_ciro = toplam_ciro - toplam_gider

    if tarih_checks:
        nakit_satis = sum(_get_check_payment_amount(c, 'cash') for c in tarih_checks)
        kart_satis = sum(_get_check_payment_amount(c, 'card') for c in tarih_checks)
        toplam_komisyon = 0
        urun_satislari = {}
        selected_ids = {c.get('id') for c in tarih_checks}
        for item in closed_items or []:
            if item.get('check_id') not in selected_ids:
                continue
            name = item.get('name')
            if not name:
                continue
            birim_fiyat = item.get('price', item.get('fiyat', 0))
            if name not in urun_satislari:
                urun_satislari[name] = {
                    'adet': 0,
                    'toplam_tutar': 0,
                    'birim_fiyat': birim_fiyat
                }
            urun_satislari[name]['adet'] += item.get('adet', 0)
            urun_satislari[name]['toplam_tutar'] += birim_fiyat * item.get('adet', 0)
            if 'serpme' in str(name).lower():
                toplam_komisyon += item.get('adet', 0) * 100
        siparis_sayisi = len(tarih_checks)
    else:
        nakit_satis = sum(get_payment_amount(o, 'cash') for o in tarih_orders)
        kart_satis = sum(get_payment_amount(o, 'card') for o in tarih_orders)

        toplam_komisyon = 0
        for order in tarih_orders:
            if order.get('rehber_masa', False):
                for item in order.get('items', []):
                    name = str(item.get('name') or '').lower()
                    if 'serpme' in name:
                        toplam_komisyon += item.get('adet', 0) * 100

        urun_satislari = {}
        for order in tarih_orders:
            for item in order.get('items', []):
                name = item.get('name')
                if not name:
                    continue
                birim_fiyat = item.get('price', item.get('fiyat', 0))
                if name not in urun_satislari:
                    urun_satislari[name] = {
                        'adet': 0,
                        'toplam_tutar': 0,
                        'birim_fiyat': birim_fiyat
                    }
                urun_satislari[name]['adet'] += item.get('adet', 0)
                urun_satislari[name]['toplam_tutar'] += birim_fiyat * item.get('adet', 0)
        siparis_sayisi = len(tarih_orders)

    return jsonify({
        'tarih': tarih_str,
        'toplam_ciro': net_ciro,
        'nakit_satis': nakit_satis,
        'kart_satis': kart_satis,
        'toplam_komisyon': toplam_komisyon,
        'toplam_gider': toplam_gider,
        'siparis_sayisi': siparis_sayisi,
        'urun_satislari': urun_satislari
    })

def build_dashboard_data():
    orders = load_orders()
    closed_checks = load_closed_checks()
    closed_items = load_closed_check_items()
    bugun_iso = now_tr().date().isoformat()

    saatlik_satis = {}
    for i in range(0, 24):
        saatlik_satis[f"{i:02d}:00"] = 0

    urun_satis = {}
    items_by_check = {}
    for item in closed_items:
        check_id = item.get('check_id')
        if check_id is None:
            continue
        items_by_check.setdefault(str(check_id), []).append(item)

    bugun_checks = []
    for check in closed_checks:
        dt = parse_iso_datetime(check.get('closed_at') or '')
        if dt and dt.date().isoformat() == bugun_iso:
            bugun_checks.append(check)

    for check in bugun_checks:
        dt = parse_iso_datetime(check.get('closed_at') or '')
        saat = dt.hour if dt else None
        if saat is not None and 0 <= saat <= 23:
            saatlik_satis[f"{saat:02d}:00"] += check.get('total', 0) or 0
        for item in items_by_check.get(str(check.get('id')), []):
            name = item.get('name')
            if not name:
                continue
            if name not in urun_satis:
                urun_satis[name] = {'adet': 0, 'tutar': 0}
            adet = item.get('adet', 0) or 0
            tutar = item.get('total')
            if tutar is None:
                fiyat = item.get('price', 0) or 0
                tutar = fiyat * adet
            urun_satis[name]['adet'] += adet
            urun_satis[name]['tutar'] += tutar

    bugun_orders = []
    if not bugun_checks:
        for o in orders:
            if not is_order_closed(o):
                continue
            order_date = to_iso_date(get_order_date(o))
            if order_date == bugun_iso:
                bugun_orders.append(o)

        for order in bugun_orders:
            saat_str = get_order_time(order) or '00:00'
            try:
                saat = int(saat_str.split(':')[0])
            except ValueError:
                saat = None
            if saat is not None and 0 <= saat <= 23:
                saatlik_satis[f"{saat:02d}:00"] += order.get('indirimli_tutar', order.get('toplam', 0))

            for item in order.get('items', []):
                name = item.get('name')
                if not name:
                    continue
                if name not in urun_satis:
                    urun_satis[name] = {'adet': 0, 'tutar': 0}
                adet = item.get('adet', 0)
                fiyat = item.get('price', item.get('fiyat', 0))
                urun_satis[name]['adet'] += adet
                urun_satis[name]['tutar'] += fiyat * adet

    populer_urunler = sorted(urun_satis.items(), key=lambda x: x[1]['adet'], reverse=True)[:5]
    karli_saatler = sorted(saatlik_satis.items(), key=lambda x: x[1], reverse=True)[:5]
    toplam_gider = sum_expenses_for_date(bugun_iso)
    if bugun_checks:
        toplam_ciro = sum(c.get('total', 0) or 0 for c in bugun_checks)
        toplam_siparis = len(bugun_checks)
    else:
        toplam_ciro = sum(o.get('indirimli_tutar', o['toplam']) for o in bugun_orders)
        toplam_siparis = len(bugun_orders)
    net_ciro = toplam_ciro - toplam_gider

    return {
        'saatlik_satis': saatlik_satis,
        'populer_urunler': populer_urunler,
        'toplam_siparis': toplam_siparis,
        'toplam_ciro': net_ciro,
        'toplam_gider': toplam_gider,
        'karli_saatler': karli_saatler
    }

@app.route('/api/dashboard-data')
def dashboard_data():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz eri?im!'}), 403
    return jsonify(build_dashboard_data())
    closed_checks = load_closed_checks()
    closed_items = load_closed_check_items()
    bugun_iso = now_tr().date().isoformat()
    
    saatlik_satis = {}
    for i in range(0, 24):
        saatlik_satis[f"{i:02d}:00"] = 0
    
    urun_satis = {}
    items_by_check = {}
    for item in closed_items:
        check_id = item.get('check_id')
        if check_id is None:
            continue
        items_by_check.setdefault(str(check_id), []).append(item)

    bugun_checks = []
    for check in closed_checks:
        dt = parse_iso_datetime(check.get('closed_at') or '')
        if dt and dt.date().isoformat() == bugun_iso:
            bugun_checks.append(check)

    for check in bugun_checks:
        dt = parse_iso_datetime(check.get('closed_at') or '')
        saat = dt.hour if dt else None
        if saat is not None and 0 <= saat <= 23:
            saatlik_satis[f"{saat:02d}:00"] += check.get('total', 0) or 0
        for item in items_by_check.get(str(check.get('id')), []):
            name = item.get('name')
            if not name:
                continue
            if name not in urun_satis:
                urun_satis[name] = {'adet': 0, 'tutar': 0}
            adet = item.get('adet', 0) or 0
            tutar = item.get('total')
            if tutar is None:
                fiyat = item.get('price', 0) or 0
                tutar = fiyat * adet
            urun_satis[name]['adet'] += adet
            urun_satis[name]['tutar'] += tutar

    bugun_orders = []
    if not bugun_checks:
        for o in orders:
            if not is_order_closed(o):
                continue
            order_date = to_iso_date(get_order_date(o))
            if order_date == bugun_iso:
                bugun_orders.append(o)
        
        for order in bugun_orders:
            saat_str = get_order_time(order) or '00:00'
            try:
                saat = int(saat_str.split(':')[0])
            except ValueError:
                saat = None
            if saat is not None and 0 <= saat <= 23:
                saatlik_satis[f"{saat:02d}:00"] += order.get('indirimli_tutar', order.get('toplam', 0))
            
            for item in order.get('items', []):
                name = item.get('name')
                if not name:
                    continue
                if name not in urun_satis:
                    urun_satis[name] = {'adet': 0, 'tutar': 0}
                adet = item.get('adet', 0)
                fiyat = item.get('price', item.get('fiyat', 0))
                urun_satis[name]['adet'] += adet
                urun_satis[name]['tutar'] += fiyat * adet

    populer_urunler = sorted(urun_satis.items(), key=lambda x: x[1]['adet'], reverse=True)[:5]
    karli_saatler = sorted(saatlik_satis.items(), key=lambda x: x[1], reverse=True)[:5]
    toplam_gider = sum_expenses_for_date(bugun_iso)
    if bugun_checks:
        toplam_ciro = sum(c.get('total', 0) or 0 for c in bugun_checks)
        toplam_siparis = len(bugun_checks)
    else:
        toplam_ciro = sum(o.get('indirimli_tutar', o['toplam']) for o in bugun_orders)
        toplam_siparis = len(bugun_orders)
    net_ciro = toplam_ciro - toplam_gider

    return jsonify({
        'saatlik_satis': saatlik_satis,
        'populer_urunler': populer_urunler,
        'toplam_siparis': toplam_siparis,
        'toplam_ciro': net_ciro,
        'toplam_gider': toplam_gider,
        'karli_saatler': karli_saatler
    })

@app.route('/api/siparis-iptal/<int:masa>', methods=['POST'])
def siparis_iptal(masa):
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    
    orders = load_orders()
    iptal_count = 0
    first_staff_id = None
    first_staff_name = None
    
    for order in orders:
        if order['masa'] == masa and order['durum'] == 'aktif':
            iptal_count += 1
            if first_staff_id is None:
                first_staff_id = order.get('staff_id')
                first_staff_name = order.get('garson')
    
    finalize_table_session(masa, orders)
    orders = [o for o in orders if not (o['masa'] == masa and o['durum'] == 'aktif')]
    
    save_orders(orders)
    actor = get_actor_info(first_staff_id, first_staff_name)
    append_activity('ORDER_CANCEL', {
        'table_id': masa,
        'count': iptal_count,
        'staff_id': actor.get('staff_id'),
        'staff_name': actor.get('staff_name')
    })
    
    return jsonify({
        'success': True,
        'iptal_count': iptal_count,
        'message': f'{iptal_count} sipariş iptal edildi.'
    })

@app.route('/api/hesap-item-guncelle', methods=['POST'])
def hesap_item_guncelle():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403
    
    data = request.json or {}
    orders = load_orders()
    removed_item = None
    target_order = None

    for order in orders:
        if str(order.get('id')) == str(data.get('siparis_id')) and order.get('durum') == 'aktif':
            target_order = order
            for idx, item in enumerate(order.get('items', [])):
                if str(item.get('id')) == str(data.get('item_id')):
                    action = data.get('action')
                    if action == 'arttir':
                        item['adet'] += 1
                    elif action == 'azalt' and item.get('adet', 1) > 1:
                        item['adet'] -= 1
                    elif action == 'sil':
                        removed_item = order['items'].pop(idx)
                    order['toplam'] = sum(i.get('price', 0) * i.get('adet', 0) for i in order.get('items', []))
                    break
            break

    save_orders(orders)
    if removed_item and target_order:
        actor = get_actor_info(target_order.get('staff_id'), target_order.get('garson'))
        append_activity('VOID_ITEM', {
            'order_id': target_order.get('id'),
            'table_id': target_order.get('masa'),
            'staff_id': actor.get('staff_id'),
            'staff_name': actor.get('staff_name'),
            'item': {
                'id': removed_item.get('id'),
                'name': removed_item.get('name'),
                'adet': removed_item.get('adet'),
                'price': removed_item.get('price')
            }
        })
    return jsonify({'success': True})

@app.route('/tip-havuzu')
def tip_havuzu_page():
    if session.get('role') != 'kasa':
        return redirect(url_for('login'))
    return render_template('tip_havuzu.html')

@app.route('/api/tip-havuzu', methods=['GET', 'POST'])
def tip_havuzu_api():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403

    periods = load_tip_periods()

    if request.method == 'GET':
        start = request.args.get('start')
        end = request.args.get('end')
        if not start or not end:
            return jsonify({'success': False, 'message': 'Baslangic ve bitis tarihi gerekli.'}), 400
        for p in periods:
            if p.get('period_start') == start and p.get('period_end') == end:
                return jsonify({'success': True, 'period': p})
        return jsonify({'success': True, 'period': None})

    data = request.json or {}
    start = data.get('period_start')
    end = data.get('period_end')
    tip_total = data.get('tip_total', 0)
    workdays = data.get('workdays', {})

    if not start or not end:
        return jsonify({'success': False, 'message': 'Baslangic ve bitis tarihi gerekli.'}), 400

    try:
        tip_total_val = float(tip_total)
    except:
        return jsonify({'success': False, 'message': 'Tip tutari gecersiz.'}), 400

    if tip_total_val < 0:
        return jsonify({'success': False, 'message': 'Tip tutari 0 veya daha buyuk olmali.'}), 400

    cleaned_workdays = {}
    for name, days in workdays.items():
        try:
            days_int = int(days)
        except:
            return jsonify({'success': False, 'message': f'Calisma gunu gecersiz: {name}'}), 400
        if days_int < 0:
            return jsonify({'success': False, 'message': f'Calisma gunu 0 veya daha buyuk olmali: {name}'}), 400
        if name.strip():
            cleaned_workdays[name.strip()] = days_int

    if sum(cleaned_workdays.values()) <= 0:
        return jsonify({'success': False, 'message': 'Toplam calisma gunu 0 olamaz.'}), 400

    payouts, _ = calculate_tip_payouts(tip_total_val, cleaned_workdays)

    record = {
        'period_start': start,
        'period_end': end,
        'tip_total': float(normalize_tip_total(tip_total_val)),
        'workdays': cleaned_workdays,
        'payouts': payouts,
        'updated_at': now_tr().strftime('%Y-%m-%d %H:%M:%S')
    }

    updated = False
    for idx, p in enumerate(periods):
        if p.get('period_start') == start and p.get('period_end') == end:
            periods[idx] = record
            updated = True
            break
    if not updated:
        periods.append(record)

    save_tip_periods(periods)

    return jsonify({'success': True, 'period': record})

@app.route('/api/tip-havuzu/hesapla', methods=['POST'])
def tip_havuzu_hesapla():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403

    data = request.json or {}
    tip_total = data.get('tip_total', 0)
    workdays = data.get('workdays', {})

    try:
        tip_total_val = float(tip_total)
    except:
        return jsonify({'success': False, 'message': 'Tip tutari gecersiz.'}), 400

    if tip_total_val < 0:
        return jsonify({'success': False, 'message': 'Tip tutari 0 veya daha buyuk olmali.'}), 400

    cleaned_workdays = {}
    for name, days in workdays.items():
        try:
            days_int = int(days)
        except:
            return jsonify({'success': False, 'message': f'Calisma gunu gecersiz: {name}'}), 400
        if days_int < 0:
            return jsonify({'success': False, 'message': f'Calisma gunu 0 veya daha buyuk olmali: {name}'}), 400
        if name.strip():
            cleaned_workdays[name.strip()] = days_int

    if sum(cleaned_workdays.values()) <= 0:
        return jsonify({'success': False, 'message': 'Toplam calisma gunu 0 olamaz.'}), 400

    payouts, _ = calculate_tip_payouts(tip_total_val, cleaned_workdays)
    return jsonify({'success': True, 'payouts': payouts})



@app.route('/vardiya')
def vardiya_page():
    if session.get('role') != 'kasa':
        return redirect(url_for('login'))
    return render_template('vardiya.html')


@app.route('/api/vardiya', methods=['GET', 'POST'])
def vardiya_api():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403

    records = load_attendance()

    if request.method == 'GET':
        start = request.args.get('start')
        end = request.args.get('end')
        month = request.args.get('month')

        if month and (not start and not end):
            try:
                start = f"{month}-01"
                start_dt = parse_date(start)
                if not start_dt:
                    return jsonify({'success': False, 'message': 'Gecersiz ay.'}), 400
                if start_dt.month == 12:
                    end_dt = datetime(start_dt.year + 1, 1, 1)
                else:
                    end_dt = datetime(start_dt.year, start_dt.month + 1, 1)
                end_dt = end_dt.replace(day=1) - datetime.resolution
                end = end_dt.strftime('%Y-%m-%d')
            except:
                return jsonify({'success': False, 'message': 'Gecersiz ay.'}), 400

        if not start or not end:
            return jsonify({'success': False, 'message': 'Baslangic ve bitis gerekli.'}), 400

        start_dt = parse_date(start)
        end_dt = parse_date(end)
        if not start_dt or not end_dt:
            return jsonify({'success': False, 'message': 'Tarih formati hatali.'}), 400

        filtered = []
        for r in records:
            r_date = parse_date(r.get('date', ''))
            if r_date and start_dt <= r_date <= end_dt:
                filtered.append(r)
        return jsonify({'success': True, 'records': filtered})

    data = request.json or {}
    date_val = data.get('date')
    waiter = (data.get('waiter') or '').strip()
    clear = data.get('clear') is True
    status = data.get('status')
    late_time = data.get('late_time')
    start_time = data.get('start_time')
    end_time = data.get('end_time')
    note = data.get('note', '')

    if not date_val or not parse_date(date_val):
        return jsonify({'success': False, 'message': 'Tarih gerekli.'}), 400
    if not waiter:
        return jsonify({'success': False, 'message': 'Garson adi gerekli.'}), 400
    if not clear and status not in ['calisti', 'izinli', 'mazeretli', 'gelmedi', 'gec_geldi']:
        return jsonify({'success': False, 'message': 'Gecersiz durum.'}), 400

    if clear:
        records = [r for r in records if not (r.get('date') == date_val and r.get('waiter') == waiter)]
        save_attendance(records)
        return jsonify({'success': True})

    updated = False
    for r in records:
        if r.get('date') == date_val and r.get('waiter') == waiter:
            r.update({
                'status': status,
                'late_time': late_time,
                'start_time': start_time,
                'end_time': end_time,
                'note': note
            })
            updated = True
            break

    if not updated:
        records.append({
            'date': date_val,
            'waiter': waiter,
            'status': status,
            'late_time': late_time,
            'start_time': start_time,
            'end_time': end_time,
            'note': note
        })

    save_attendance(records)
    return jsonify({'success': True})

@app.route('/api/vardiya/summary')
def vardiya_summary():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403

    start = request.args.get('start')
    end = request.args.get('end')
    if not start or not end:
        return jsonify({'success': False, 'message': 'Baslangic ve bitis gerekli.'}), 400

    start_dt = parse_date(start)
    end_dt = parse_date(end)
    if not start_dt or not end_dt:
        return jsonify({'success': False, 'message': 'Tarih formati hatali.'}), 400

    records = load_attendance()
    summary = {}
    for r in records:
        r_date = parse_date(r.get('date', ''))
        if not r_date or r_date < start_dt or r_date > end_dt:
            continue
        if r.get('status') == 'calisti':
            name = r.get('waiter', '').strip()
            if not name:
                continue
            summary[name] = summary.get(name, 0) + 1

    return jsonify({'success': True, 'workdays': summary})

@app.route('/api/vardiya/config', methods=['GET', 'POST'])
def vardiya_config():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403

    if request.method == 'GET':
        return jsonify({'success': True, 'config': load_attendance_config()})

    data = request.json or {}
    start_time = data.get('start_time')
    end_time = data.get('end_time')
    if not start_time or not end_time:
        return jsonify({'success': False, 'message': 'Calisma saatleri gerekli.'}), 400

    save_attendance_config({'start_time': start_time, 'end_time': end_time})
    return jsonify({'success': True})



@app.route('/api/calisanlar', methods=['GET', 'POST'])
def calisanlar_api():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403

    if request.method == 'GET':
        return jsonify({'success': True, 'names': load_employees()})

    data = request.json or {}
    names = data.get('names', [])
    cleaned = []
    for n in names:
        n = (n or '').strip()
        if n and n not in cleaned:
            cleaned.append(n)
    save_employees(cleaned)
    return jsonify({'success': True, 'names': cleaned})









@app.route('/api/deneme-sifirla', methods=['POST'])
def deneme_sifirla():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403

    save_orders([])
    return jsonify({'success': True})

if __name__ == '__main__':
    init_data()
    app.run(debug=True, host='0.0.0.0', port=5000)
