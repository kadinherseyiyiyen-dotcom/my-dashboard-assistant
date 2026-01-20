from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from datetime import datetime
import time
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
import json
import os

app = Flask(__name__)
@app.route("/health")
def health():
    return "ok", 200

app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-12345')
app.config['JSON_AS_ASCII'] = False

@app.after_request
def add_charset(response):
    if response.mimetype == 'text/html':
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
    return response

DATA_DIR = os.environ.get('DATA_DIR', '.')
DB_URL = os.environ.get('DATABASE_URL', '').strip()
USE_DB = bool(DB_URL)

def data_path(filename):
    return os.path.join(DATA_DIR, filename)

if DATA_DIR and DATA_DIR not in ['.', './']:
    os.makedirs(DATA_DIR, exist_ok=True)

_DB_READY = False
_CACHE = {}

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

def get_db_conn():
    try:
        import psycopg2
    except Exception as e:
        raise RuntimeError(f"psycopg2 import failed: {e}")

    db_url = os.getenv('DATABASE_URL', '')
    if not db_url:
        return None
    return psycopg2.connect(db_url, sslmode=os.environ.get('DB_SSLMODE', 'require'))

def ensure_kv_table():
    global _DB_READY
    if _DB_READY or not USE_DB:
        return
    conn = get_db_conn()
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
    conn.close()
    _DB_READY = True

def storage_has_key(key):
    if USE_DB:
        ensure_kv_table()
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("select 1 from kv_store where key = %s", (key,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row is not None
    return os.path.exists(data_path(key))

def load_json_storage(key, default):
    if USE_DB:
        ensure_kv_table()
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("select data from kv_store where key = %s", (key,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row or row[0] is None:
            return default
        try:
            return json.loads(row[0])
        except Exception:
            return default
    try:
        with open(data_path(key), 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default

def save_json_storage(key, data):
    if USE_DB:
        ensure_kv_table()
        conn = get_db_conn()
        cur = conn.cursor()
        payload = json.dumps(data, ensure_ascii=False)
        cur.execute("""
            insert into kv_store (key, data, updated_at)
            values (%s, %s, now())
            on conflict (key) do update set data = excluded.data, updated_at = now()
        """, (key, payload))
        conn.commit()
        cur.close()
        conn.close()
        return
    with open(data_path(key), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

ORDERS_FILE = 'orders.json'
MENU_FILE = 'menu.json'
TABLES_FILE = 'tables.json'
REHBER_FILE = 'rehber_masalar.json'
ATTENDANCE_FILE = 'vardiya.json'
ATTENDANCE_CONFIG_FILE = 'vardiya_config.json'
EMPLOYEES_FILE = 'calisanlar.json'
TIP_FILE = 'tip_havuzu.json'
EXPENSES_FILE = 'giderler.json'
CONFIG_FILE = 'config.json'
OTOPARK_CONFIG_FILE = 'otopark_config.json'

def get_order_date(order):
    return order.get('kapanma_tarih') or order.get('tarih')

def load_config():
    return load_json_storage(CONFIG_FILE, {'kasa_sifre': 'kasa123'})

def init_data():
    if not storage_has_key(MENU_FILE):
        menu = {
            "ana_menu": [{"id": 1, "name": "Serpme Kahvaltı", "price": 85, "category": "ana_menu", "image": "🍳"}],
            "ekstralar": [
                {"id": 2, "name": "Patates Kızartması", "price": 25, "category": "ekstra", "image": "🍟"},
                {"id": 3, "name": "Hellim", "price": 30, "category": "ekstra", "image": "🧀"},
                {"id": 4, "name": "Full Falafel", "price": 35, "category": "ekstra", "image": "🥙"},
                {"id": 5, "name": "Mıhlama", "price": 40, "category": "ekstra", "image": "🫕"},
                {"id": 6, "name": "Göz Yumurta", "price": 20, "category": "ekstra", "image": "🍳"}
            ],
            "icecekler": [
                {"id": 7, "name": "Çay", "price": 8, "category": "icecek", "image": "🫖"},
                {"id": 8, "name": "Karak", "price": 15, "category": "icecek", "image": "☕"},
                {"id": 9, "name": "Sıcak Süt", "price": 12, "category": "icecek", "image": "🥛"},
                {"id": 10, "name": "Türk Kahvesi", "price": 25, "category": "icecek", "image": "☕"},
                {"id": 11, "name": "Portakal Suyu", "price": 20, "category": "icecek", "image": "🍊"},
                {"id": 12, "name": "Limonata", "price": 18, "category": "icecek", "image": "🍋"},
                {"id": 13, "name": "Su", "price": 5, "category": "icecek", "image": "💧"}
            ]
        }
        save_json_storage(MENU_FILE, menu)
    
    if not storage_has_key(ORDERS_FILE):
        save_json_storage(ORDERS_FILE, [])
    
    if not storage_has_key(TABLES_FILE):
        tables = {str(i): f"Masa {i}" for i in range(1, 21)}
        save_json_storage(TABLES_FILE, tables)

init_data()

def load_orders():
    return load_json_storage(ORDERS_FILE, [])

def save_orders(orders):
    save_json_storage(ORDERS_FILE, orders)

def load_menu():
    return load_json_storage(MENU_FILE, {})

def load_tables():
    return load_json_storage(TABLES_FILE, {str(i): f"Masa {i}" for i in range(1, 21)})

def save_tables(tables):
    save_json_storage(TABLES_FILE, tables)

def load_rehber_masalar():
    return load_json_storage(REHBER_FILE, {})

def save_rehber_masalar(rehber_masalar):
    save_json_storage(REHBER_FILE, rehber_masalar)

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
    return load_json_storage(EMPLOYEES_FILE, [])

def save_employees(names):
    save_json_storage(EMPLOYEES_FILE, names)

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
    data = request.json
    role = data.get('role')
    password = data.get('password')
    
    if role == 'garson' and password == 'garson123':
        session['role'] = 'garson'
        session['user'] = data.get('name', 'Garson')
        return jsonify({'success': True, 'redirect': '/garson'})
    elif role == 'kasa' and password == load_config().get('kasa_sifre', 'kasa123'):
        session['role'] = 'kasa'
        session['user'] = 'Kasiyer'
        return jsonify({'success': True, 'redirect': '/kasa'})
    else:
        return jsonify({'success': False, 'message': 'Hatalı şifre!'})

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
    menu = load_menu()
    tables = load_tables()
    return render_template('siparis_gir.html', menu=menu, tables=tables)

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
    bugun = datetime.now().strftime('%d.%m.%Y')
    dun = (datetime.now() - timedelta(days=1)).strftime('%d.%m.%Y')
    
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
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    
    orders = load_orders()
    from datetime import datetime, timedelta
    
    # Rehber masalarını yükle
    try:
        rehber_masalar = load_rehber_masalar()
    except:
        rehber_masalar = {}
    
    # Son 7 günün verilerini hazırla
    bugun = datetime.now()
    haftalik_data = []
    
    for i in range(6, -1, -1):
        tarih = bugun - timedelta(days=i)
        tarih_str = tarih.strftime('%d.%m.%Y')
        
        # Hem tarih hem de kapanma_tarih alanlarını kontrol et
        gunluk_orders = []
        for o in orders:
            if o['durum'] == 'kapali':
                # Önce kapanma_tarih'i kontrol et, yoksa tarih'i kullan
                order_tarih = o.get('kapanma_tarih')
                if not order_tarih:
                    order_tarih = o.get('tarih', '')
                
                # Tarih eşleştirmesi yap
                if order_tarih == tarih_str:
                    gunluk_orders.append(o)
        
        gunluk_ciro = sum(o.get('indirimli_tutar', o['toplam']) for o in gunluk_orders)
        
        # Komisyon hesapla
        gunluk_komisyon = 0
        for order in gunluk_orders:
            # Eğer rehber masa ise komisyon hesapla
            if order.get('rehber_masa') or rehber_masalar.get(str(order['masa'])):
                for item in order['items']:
                    if item['name'] == 'Serpme Kahvaltı':
                        gunluk_komisyon += item['adet'] * 100
        
        # Gider hesaplamalarını ekle
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

@app.route('/api/siparis', methods=['POST'])
def siparis_ekle():
    if session.get('role') not in ['garson', 'kasa']:
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
        
    data = request.json
    orders = load_orders()
    
    if session.get('role') == 'kasa':
        garson_name = data.get('garson', 'WhatsApp')
    else:
        garson_name = session.get('user', data['garson'])
    
    new_order = {
        'id': len(orders) + 1,
        'masa': data['masa'],
        'garson': garson_name,
        'items': data['items'],
        'toplam': data['toplam'],
        'zaman': datetime.now().strftime('%H:%M'),
        'tarih': datetime.now().strftime('%d.%m.%Y'),
        'durum': 'aktif',
        'kaynak': 'kasa' if session.get('role') == 'kasa' else 'garson'
    }
    
    orders.append(new_order)
    save_orders(orders)
    
    return jsonify({'success': True, 'order_id': new_order['id']})

@app.route('/api/siparisler')
def siparisler():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    orders = load_orders()
    return jsonify(orders)

@app.route('/api/kasa-init')
def kasa_init():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403
    orders = cached_load('orders', load_orders, 5)
    tables = cached_load('tables', load_tables, 30)
    rehber = cached_load('rehber', load_rehber_masalar, 30)
    return jsonify({'orders': orders, 'tables': tables, 'rehber': rehber})

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
        return jsonify({'success': True})

@app.route('/api/giderler', methods=['GET', 'POST'])
def giderler_api():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erisim!'}), 403

    if request.method == 'GET':
        date_val = request.args.get('date')
        records = load_expenses()
        if date_val:
            date_iso = normalize_date(date_val)
            records = [r for r in records if normalize_date(r.get('date')) == date_iso]
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
    if not date_val:
        return jsonify({'success': False, 'message': 'Tarih gerekli.'}), 400
    total = sum_expenses_for_date(date_val)
    return jsonify({'success': True, 'toplam_gider': total})

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
        'zaman': datetime.now().strftime('%H:%M'),
        'tarih': datetime.now().strftime('%d.%m.%Y'),
        'kapanma_tarih': datetime.now().strftime('%Y-%m-%d'),
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
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    orders = load_orders()
    masa_orders = [o for o in orders if o['masa'] == masa and o['durum'] == 'aktif']
    toplam = sum(o['toplam'] for o in masa_orders)
    return jsonify({
        'masa': masa,
        'siparisler': masa_orders,
        'toplam': toplam
    })

@app.route('/api/hesap_kapat/<int:masa>', methods=['POST'])
def hesap_kapat(masa):
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    
    data = request.json
    orders = load_orders()
    rehber_masalar = load_rehber_masalar()
    toplam_tutar = 0
    
    masa_rehber_durumu = rehber_masalar.get(str(masa), False)
    
    for order in orders:
        if order['masa'] == masa and order['durum'] == 'aktif':
            toplam_tutar += order['toplam']
            order['durum'] = 'kapali'
            order['kapanma_zamani'] = datetime.now().strftime('%H:%M')
            order['kapanma_tarih'] = datetime.now().strftime('%d.%m.%Y')
            order['odeme_turu'] = data.get('odeme_turu', 'nakit')
            order['rehber_masa'] = masa_rehber_durumu
            if data.get('odeme_turu') == 'nakit':
                order['indirim'] = order['toplam'] * 0.1
                order['indirimli_tutar'] = int(order['toplam'] * 0.9)
            else:
                order['indirim'] = 0
                order['indirimli_tutar'] = order['toplam']
    
    save_orders(orders)
    
    if str(masa) in rehber_masalar:
        rehber_masalar[str(masa)] = False
        save_rehber_masalar(rehber_masalar)
    
    response = {'success': True}
    if data.get('odeme_turu') == 'nakit':
        response['indirimli_tutar'] = int(toplam_tutar * 0.9)
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
    orders = load_orders()
    
    if not tarih:
        bugun_iso = datetime.now().strftime('%Y-%m-%d')
        bugun_tr = datetime.now().strftime('%d.%m.%Y')
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
        kapanma_tarih = order.get('kapanma_tarih', '')
        
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
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    
    tarih = request.args.get('tarih')
    orders = load_orders()
    
    if not tarih:
        bugun_iso = datetime.now().strftime('%Y-%m-%d')
        bugun_tr = datetime.now().strftime('%d.%m.%Y')
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
        kapanma_tarih = order.get('kapanma_tarih', '')
        
        tarih_match = (
            order_tarih == tarih or 
            order_tarih == tarih_iso or
            kapanma_tarih == tarih or 
            kapanma_tarih == tarih_iso
        )
        
        if tarih_match:
            tarih_orders.append(order)
    
    toplam_ciro = sum(o.get('indirimli_tutar', o.get('toplam', 0)) for o in tarih_orders)
    toplam_gider = sum_expenses_for_date(tarih_iso)
    net_ciro = toplam_ciro - toplam_gider
    nakit_satis = sum(o.get('indirimli_tutar', o.get('toplam', 0)) for o in tarih_orders if o.get('odeme_turu') == 'nakit')
    kart_satis = sum(o.get('indirimli_tutar', o.get('toplam', 0)) for o in tarih_orders if o.get('odeme_turu') == 'kart')
    
    toplam_komisyon = 0
    for order in tarih_orders:
        if order.get('rehber_masa', False):
            for item in order.get('items', []):
                if item.get('name') == 'Serpme Kahvaltı':
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
    
    return jsonify({
        'tarih': tarih,
        'toplam_ciro': net_ciro,
        'nakit_satis': nakit_satis,
        'kart_satis': kart_satis,
        'toplam_komisyon': toplam_komisyon,
        'toplam_gider': toplam_gider,
        'siparis_sayisi': len(tarih_orders),
        'urun_satislari': urun_satislari
    })

@app.route('/api/dashboard-data')
def dashboard_data():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    
    orders = load_orders()
    bugun_iso = datetime.now().strftime('%Y-%m-%d')
    bugun_tr = datetime.now().strftime('%d.%m.%Y')
    
    saatlik_satis = {}
    for i in range(7, 20):
        saatlik_satis[f"{i:02d}:00"] = 0
    
    urun_satis = {}
    masa_kullanim = {}
    for i in range(1, 21):
        masa_kullanim[i] = 0
    
    bugun_orders = [
        o for o in orders
        if (get_order_date(o) == bugun_iso or get_order_date(o) == bugun_tr)
        and o['durum'] == 'kapali'
    ]
    
    from datetime import timedelta
    son_7_gun = []
    for i in range(7):
        tarih = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        tarih_tr = (datetime.now() - timedelta(days=i)).strftime('%d.%m.%Y')
        gun_orders = [
            o for o in orders
            if (get_order_date(o) == tarih or get_order_date(o) == tarih_tr)
            and o['durum'] == 'kapali'
        ]
        son_7_gun.extend(gun_orders)
    
    for order in son_7_gun:
        masa_key = order.get('masa')
        if isinstance(masa_key, str) and masa_key.isdigit():
            masa_key = int(masa_key)
        if masa_key in masa_kullanim:
            masa_kullanim[masa_key] += 1
    
    for order in bugun_orders:
        saat_str = order.get('kapanma_zamani') or order.get('zaman', '00:00')
        try:
            saat = int(saat_str.split(':')[0])
        except ValueError:
            saat = None
        if saat is not None and 7 <= saat <= 19:
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
    populer_masalar = sorted(masa_kullanim.items(), key=lambda x: x[1], reverse=True)[:10]
    
    toplam_gider = sum_expenses_for_date(bugun_iso)
    toplam_ciro = sum(o.get('indirimli_tutar', o['toplam']) for o in bugun_orders)
    net_ciro = toplam_ciro - toplam_gider

    return jsonify({
        'saatlik_satis': saatlik_satis,
        'populer_urunler': populer_urunler,
        'toplam_siparis': len(bugun_orders),
        'toplam_ciro': net_ciro,
        'toplam_gider': toplam_gider,
        'karli_saatler': karli_saatler,
        'masa_kullanim': populer_masalar
    })

@app.route('/api/siparis-iptal/<int:masa>', methods=['POST'])
def siparis_iptal(masa):
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    
    orders = load_orders()
    iptal_count = 0
    
    for order in orders:
        if order['masa'] == masa and order['durum'] == 'aktif':
            iptal_count += 1
    
    orders = [o for o in orders if not (o['masa'] == masa and o['durum'] == 'aktif')]
    
    save_orders(orders)
    
    return jsonify({
        'success': True,
        'iptal_count': iptal_count,
        'message': f'{iptal_count} sipariş iptal edildi.'
    })

@app.route('/api/hesap-item-guncelle', methods=['POST'])
def hesap_item_guncelle():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    
    data = request.json
    orders = load_orders()
    
    for order in orders:
        if str(order['id']) == str(data['siparis_id']) and order['durum'] == 'aktif':
            for item in order['items']:
                if item['id'] == data['item_id']:
                    if data['action'] == 'arttir':
                        item['adet'] += 1
                    elif data['action'] == 'azalt' and item['adet'] > 1:
                        item['adet'] -= 1
                    
                    order['toplam'] = sum(i['price'] * i['adet'] for i in order['items'])
                    break
            break
    
    save_orders(orders)
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
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
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
