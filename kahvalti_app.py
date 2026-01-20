from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from datetime import datetime
import json
import os
import secrets

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# Veri dosyaları
ORDERS_FILE = 'orders.json'
MENU_FILE = 'menu.json'
TABLES_FILE = 'tables.json'

def load_config():
    try:
        with open('config.json', 'r') as f:
            return json.load(f)
    except:
        return {'kasa_sifre': 'kasa123'}

# Başlangıç verileri
def init_data():
    # Menü oluştur
    if not os.path.exists(MENU_FILE):
        menu = {
            "ana_menu": [
                {"id": 1, "name": "Serpme Kahvaltı", "price": 85, "category": "ana_menu", "image": "🍳"}
            ],
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
        with open(MENU_FILE, 'w', encoding='utf-8') as f:
            json.dump(menu, f, ensure_ascii=False, indent=2)
    
    # Siparişler dosyası
    if not os.path.exists(ORDERS_FILE):
        with open(ORDERS_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False, indent=2)
    
    # Masa isimleri dosyası
    if not os.path.exists(TABLES_FILE):
        tables = {str(i): f"Masa {i}" for i in range(1, 16)}
        with open(TABLES_FILE, 'w', encoding='utf-8') as f:
            json.dump(tables, f, ensure_ascii=False, indent=2)

def load_orders():
    try:
        with open(ORDERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def save_orders(orders):
    with open(ORDERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(orders, f, ensure_ascii=False, indent=2)

def load_menu():
    with open(MENU_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_tables():
    try:
        with open(TABLES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {str(i): f"Masa {i}" for i in range(1, 16)}

def save_tables(tables):
    with open(TABLES_FILE, 'w', encoding='utf-8') as f:
        json.dump(tables, f, ensure_ascii=False, indent=2)

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
    
    # Basit şifre kontrolü (gerçek uygulamada hash kullanın)
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

@app.route('/api/siparis', methods=['POST'])
def siparis_ekle():
    if session.get('role') not in ['garson', 'kasa']:
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
        
    data = request.json
    orders = load_orders()
    
    # Kasa siparişi giriyorsa garson bilgisini al
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

@app.route('/api/garson/siparisler')
def garson_siparisler():
    if session.get('role') != 'garson':
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    orders = load_orders()
    # Garson sadece kendi siparişlerini görebilir
    garson_orders = [o for o in orders if o['garson'] == session.get('user') and o['durum'] == 'aktif']
    return jsonify(garson_orders)

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
    odeme_turu = data.get('odeme_turu', 'nakit')
    indirim = data.get('indirim', 0)
    
    orders = load_orders()
    toplam_tutar = 0
    
    for order in orders:
        if order['masa'] == masa and order['durum'] == 'aktif':
            toplam_tutar += order['toplam']
            order['durum'] = 'kapali'
            order['kapanma_zamani'] = datetime.now().strftime('%H:%M')
            order['odeme_turu'] = odeme_turu
            if indirim > 0:
                order['indirim'] = indirim
                order['indirimli_tutar'] = int(order['toplam'] * (1 - indirim))
    
    save_orders(orders)
    
    response = {'success': True}
    if indirim > 0:
        response['indirimli_tutar'] = int(toplam_tutar * (1 - indirim))
    
    return jsonify(response)

@app.route('/api/menu', methods=['GET', 'POST'])
def handle_menu():
    if request.method == 'GET':
        menu = load_menu()
        return jsonify(menu)
    else:  # POST
        if session.get('role') != 'kasa':
            return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
        
        data = request.json
        with open(MENU_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return jsonify({'success': True})

@app.route('/api/sifre-degistir', methods=['POST'])
def sifre_degistir():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    
    data = request.json
    eski_sifre = data.get('eski_sifre')
    yeni_sifre = data.get('yeni_sifre')
    
    if eski_sifre != load_config().get('kasa_sifre', 'kasa123'):
        return jsonify({'success': False, 'message': 'Mevcut şifre hatalı!'})
    
    config = load_config()
    config['kasa_sifre'] = yeni_sifre
    with open('config.json', 'w') as f:
        json.dump(config, f)
    
    return jsonify({'success': True})

@app.route('/istatistik')
def istatistik():
    if session.get('role') != 'kasa':
        return redirect(url_for('login'))
    return render_template('istatistik.html')

@app.route('/api/istatistik')
def get_istatistik():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    
    orders = load_orders()
    bugun = datetime.now().strftime('%d.%m.%Y')
    
    # Bugünün siparişleri
    bugun_orders = [o for o in orders if o.get('tarih') == bugun and o['durum'] == 'kapali']
    
    # Masa istatistikleri
    masa_stats = {}
    for order in bugun_orders:
        masa = order['masa']
        hesap_id = f"{masa}_{order.get('kapanma_zamani', order['zaman'])}"
        if hesap_id not in masa_stats:
            masa_stats[hesap_id] = {
                'masa': masa,
                'toplam': 0, 
                'siparisler': [], 
                'odeme_turu': {},
                'kapanma_zamani': order.get('kapanma_zamani', order['zaman'])
            }
        
        tutar = order.get('indirimli_tutar', order['toplam'])
        masa_stats[hesap_id]['toplam'] += tutar
        masa_stats[hesap_id]['siparisler'].append(order)
        
        odeme = order.get('odeme_turu', 'nakit')
        masa_stats[hesap_id]['odeme_turu'][odeme] = masa_stats[hesap_id]['odeme_turu'].get(odeme, 0) + tutar
    
    # Ürün istatistikleri
    urun_stats = {}
    for order in bugun_orders:
        for item in order['items']:
            name = item['name']
            if name not in urun_stats:
                urun_stats[name] = {'adet': 0, 'tutar': 0}
            urun_stats[name]['adet'] += item['adet']
            urun_stats[name]['tutar'] += item['price'] * item['adet']
    
    # Saatlik dağılım
    saatlik_stats = {}
    for order in bugun_orders:
        saat = order.get('kapanma_zamani', order['zaman'])[:2]
        if saat not in saatlik_stats:
            saatlik_stats[saat] = {'adet': 0, 'tutar': 0}
        saatlik_stats[saat]['adet'] += 1
        saatlik_stats[saat]['tutar'] += order.get('indirimli_tutar', order['toplam'])
    
    return jsonify({
        'masa_stats': masa_stats,
        'urun_stats': urun_stats,
        'saatlik_stats': saatlik_stats,
        'toplam_ciro': sum(order.get('indirimli_tutar', order['toplam']) for order in bugun_orders),
        'toplam_siparis': len(bugun_orders)
    })
@app.route('/api/hesap-item-guncelle', methods=['POST'])
def hesap_item_guncelle():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    
    data = request.json
    siparis_id = data.get('siparis_id')
    item_id = data.get('item_id')
    action = data.get('action')
    
    orders = load_orders()
    
    for order in orders:
        if order['id'] == int(siparis_id) and order['durum'] == 'aktif':
            for item in order['items']:
                if item['id'] == item_id:
                    if action == 'arttir':
                        item['adet'] += 1
                        order['toplam'] += item['price']
                    elif action == 'azalt':
                        if item['adet'] > 1:
                            item['adet'] -= 1
                            order['toplam'] -= item['price']
                        else:
                            # Ürünü tamamen kaldır
                            order['items'].remove(item)
                            order['toplam'] -= item['price']
                    break
            break
    
    save_orders(orders)
    return jsonify({'success': True})

@app.route('/api/tables', methods=['GET', 'POST'])
def handle_tables():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    
    if request.method == 'GET':
        tables = load_tables()
        return jsonify(tables)
    else:  # POST
        data = request.json
        save_tables(data)
        return jsonify({'success': True})

@app.route('/api/ciro-sifirla', methods=['POST'])
def ciro_sifirla():
    if session.get('role') != 'kasa':
        return jsonify({'success': False, 'message': 'Yetkisiz erişim!'}), 403
    
    orders = load_orders()
    bugun = datetime.now().strftime('%d.%m.%Y')
    
    # Bugünün kapalı siparişlerini sil (aktif olanları koru)
    orders = [o for o in orders if not (o.get('tarih') == bugun and o.get('durum') == 'kapali')]
    save_orders(orders)
    
    return jsonify({'success': True})

if __name__ == '__main__':
    import socket
    import os
    
    def get_local_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "IP bulunamadı"
    
    init_data()
    
    # Bulut ortamında çalışıyorsa farklı mesaj
    if os.environ.get('RENDER'):
        print("\n🌟 Sistem bulutta çalışıyor!")
        print("🌍 Her yerden erişim: https://[YOUR-APP].onrender.com")
    else:
        local_ip = get_local_ip()
        print("\n" + "="*50)
        print("    KAHVALTI SALONU SIPARIS SISTEMI")
        print("="*50)
        print("\n🚀 Sistem başlatılıyor...")
        print("\n📱 Erişim adresleri:")
        print(f"   Bilgisayar: http://localhost:5000")
        print(f"   Diğer cihazlar: http://{local_ip}:5000")
        print("\n🔑 Giriş şifreleri:")
        print("   Kasa: kasa123")
        print("   Garson: garson123")
        print("\n💡 Diğer cihazlardan erişim için:")
        print(f"   Tarayıcıda: {local_ip}:5000")
        print("\n" + "="*50)
        print("Sistem hazır! Tarayıcınızı açın...\n")
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)