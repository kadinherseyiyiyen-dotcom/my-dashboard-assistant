# 📋 ADIM ADIM KULLANIM REHBERİ

## 🏠 EVDE YAPILACAKLAR (İLK KURULUM)

### 1. Hazırlık
- Bu klasörü USB'ye kopyala VEYA
- Bu klasörü OneDrive/Google Drive'a yükle VEYA  
- Bu klasörü dükkan bilgisayarına WhatsApp ile gönder

### 2. Test Et (Opsiyonel)
- Evde `baslat.bat`'a çift tıkla
- Sistem çalışıyor mu kontrol et
- Tarayıcıda `localhost:5000` aç
- Giriş yap: **kasa123**

---

## 🏪 DÜKKANDA YAPILACAKLAR (HER GÜN)

### SABAH (Sistem Başlatma)

#### 1. Klasörü Bilgisayara Koy
- USB'den kopyala VEYA
- OneDrive'dan indir VEYA
- WhatsApp'tan dosyaları kaydet

#### 2. Sistemi Başlat
- `baslat.bat` dosyasına **ÇİFT TIKLA**
- Siyah ekran açılacak ve şunu göreceksin:

```
==========================================
   KAHVALTI SALONU SIPARIS SISTEMI
==========================================

🚀 Sistem başlatılıyor...

📱 Erişim adresleri:
   Bilgisayar: http://localhost:5000
   Diğer cihazlar: http://192.168.1.45:5000
```

#### 3. IP Adresini Not Al
- Yukarıdaki örnekte: **192.168.1.45**
- Bu her dükkanada farklı olacak
- Bu IP'yi garsonlara söyle

#### 4. Kasa Bilgisayarında Giriş
- Tarayıcı aç
- `localhost:5000` yaz
- Kasa girişi: **kasa123**

---

## 📱 GARSONLAR İÇİN (HER GÜN)

### Telefon/Tablet Bağlantısı
1. **Dükkan Wi-Fi'sine bağlan**
2. **Tarayıcı aç**
3. **Kasa'nın söylediği IP'yi yaz**: `192.168.1.45:5000`
4. **Garson girişi**: **garson123**
5. **İsmini seç** (Ahmet, Ayşe, vs.)

---

## 🔄 GÜNLÜK KULLANIM

### Sabah
- `baslat.bat` çalıştır
- IP'yi garsonlara söyle
- Sistem hazır!

### Gün İçi
- **Garsonlar**: Telefonda sipariş alır
- **Kasa**: WhatsApp siparişlerini girer
- **Hesap**: Nakit/Kart ile kapatır

### Akşam
- **Ciroyu sıfırla** (isteğe bağlı)
- **Bilgisayarı kapat**

---

## 🆘 SORUN ÇÖZÜMLERI

### "Python bulunamadı" Hatası
1. Microsoft Store aç
2. "Python" ara ve indir
3. `baslat.bat` yeniden çalıştır

### Garsonlar Bağlanamıyor
1. Tüm cihazlar aynı Wi-Fi'de mi?
2. IP adresini doğru yazdılar mı?
3. `:5000` eklemeyi unutmadılar mı?

### Sistem Çalışmıyor
1. `baslat.bat` yeniden çalıştır
2. Bilgisayarı yeniden başlat
3. Antivirus'ü geçici kapat

---

## 💡 PRATIK İPUÇLARI

### Kolay Bağlantı
- IP'yi WhatsApp grubuna yaz
- Garsonlar kopyala-yapıştır yapsın
- Örnek: "Bugünkü adres: 192.168.1.45:5000"

### Yedekleme
- `orders.json` dosyasını her akşam yedekle
- `menu.json` dosyasını yedekle
- USB'ye kopyala

### Hızlı Başlatma
- `baslat.bat`'ı masaüstüne kopyala
- Çift tıkla, hazır!

---

## 📞 ÖZET

**EVDE**: Sistemi hazırla, test et
**DÜKKANDA**: `baslat.bat` çalıştır, IP'yi paylaş
**GARSONLAR**: Wi-Fi + IP + garson123
**KASA**: localhost:5000 + kasa123

Bu kadar basit! 🎉