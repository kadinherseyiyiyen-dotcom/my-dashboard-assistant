# 🏪 DÜKKAN KURULUM REHBERİ

## 📋 Gereksinimler
- Windows bilgisayar
- Python yüklü (varsa)
- Wi-Fi bağlantısı

## 🚀 KOLAY KURULUM (Önerilen)

### 1️⃣ Telefon Hotspot Yöntemi
1. **Telefonunuzdan Wi-Fi hotspot açın**
2. **Bilgisayarı hotspot'a bağlayın**
3. **`baslat.bat` dosyasına çift tıklayın**
4. **Sistem otomatik IP adresini gösterecek**
5. **Diğer cihazlar için gösterilen IP'yi kullanın**

### 2️⃣ Dükkan Wi-Fi Yöntemi
1. **Tüm cihazları aynı Wi-Fi'ye bağlayın**
2. **`baslat.bat` dosyasına çift tıklayın**
3. **Sistem otomatik IP adresini gösterecek**
4. **Diğer cihazlar için gösterilen IP'yi kullanın**

## 📱 KULLANIM

### Kasa (Bilgisayar)
- `baslat.bat` çalıştır
- Tarayıcıda `http://localhost:5000` aç
- Kasa girişi: **kasa123**

### Garsonlar (Telefon/Tablet)
- Aynı Wi-Fi'ye bağlan
- Sistemin gösterdiği IP adresini kullan
- Örnek: `192.168.1.100:5000`
- Garson girişi: **garson123**

### WhatsApp Siparişleri
- Kasa panelinde **"📱 Sipariş Gir"**
- WhatsApp'tan gelen siparişleri gir

## 🎯 ÖNEMLİ
- **IP adresi her Wi-Fi'de farklıdır**
- **Sistem her başlatmada doğru IP'yi gösterir**
- **Evde farklı, dükkanada farklı IP olacak**
- **Bu normaldir ve otomatik çözülür**

## 🔧 SORUN GİDERME

### Python Yüklü Değilse
1. Microsoft Store'dan Python indir
2. Veya python.org'dan indir
3. Kurulum sırasında "Add to PATH" seç

### Bağlantı Sorunu
- Tüm cihazlar aynı Wi-Fi'de olmalı
- Windows Firewall'u geçici kapatın
- Antivirus'ü geçici devre dışı bırakın

## 📞 HIZLI DESTEK
- Sistem çalışmazsa: `baslat.bat` yeniden çalıştır
- Şifre unutulursa: Dosyalardaki `config.json` silin
- Veriler kaybolursa: `orders.json` ve `menu.json` yedekleyin

## 💡 İPUÇLARI
- Günlük kapanışta ciroyu sıfırlayın
- Masa isimlerini özelleştirin
- Menü fiyatlarını güncelleyin
- Düzenli yedek alın