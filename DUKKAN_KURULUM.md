# 🏪 Dükkan Kurulum Rehberi

## 📱 Seçenek 1: Telefon Hotspot (Önerilen)
1. **Telefon Hotspot Aç**: Telefonunuzdan Wi-Fi hotspot açın
2. **Bilgisayar Bağla**: Bilgisayarı hotspot'a bağlayın
3. **Sistemi Başlat**: `python kahvalti_app.py` komutu ile başlatın
4. **IP Adresini Öğren**: Cmd'de `ipconfig` yazın, "Wireless LAN adapter Wi-Fi" altındaki IPv4 adresini not alın
5. **Diğer Cihazlar**: Tabletler/telefonlar aynı hotspot'a bağlanıp `http://IP_ADRESI:5000` adresine gitsin

**Örnek**: IP adresiniz 192.168.43.1 ise, diğer cihazlar `http://192.168.43.1:5000` adresine gidecek

## 🌐 Seçenek 2: Dükkan Wi-Fi
1. **Tüm Cihazlar**: Aynı Wi-Fi ağına bağlanın
2. **Bilgisayar IP**: `ipconfig` ile IP adresini öğrenin
3. **Erişim**: Diğer cihazlar `http://IP_ADRESI:5000` adresine gitsin

## 📋 Kullanım Senaryosu
- **Kasa**: Bilgisayarda sistem çalışır
- **Garsonlar**: Telefonlarından WhatsApp ile sipariş iletir
- **Kasa**: Telefon/tablet ile sipariş girer (`/siparis-gir`)
- **Hesap**: Nakit/Kart butonları ile direkt kapatır

## 🔧 Sistem Gereksinimleri
- Python 3.x yüklü bilgisayar
- Wi-Fi bağlantısı
- Tarayıcı olan cihazlar (telefon/tablet)

## 🚀 Hızlı Başlangıç
```bash
cd kahvalti-sistemi
python kahvalti_app.py
```

Sistem `http://localhost:5000` adresinde çalışmaya başlar.

## 📞 Destek
Sorun yaşarsanız sistem yöneticisine başvurun.