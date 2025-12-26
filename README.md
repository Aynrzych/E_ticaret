# E-Ticaret Projesi

E-ticaret sitelerinden (Hepsiburada, Trendyol, N11, Pazarama, PTTAVM) ürün fiyat, puan ve yorum verilerini çeken ve analiz eden web scraping ve analiz sistemi.

## Özellikler

- 🔍 **Web Scraping**: Akakçe üzerinden çoklu e-ticaret sitelerinden veri çekme
- 📊 **Veri Analizi**: Rakip analizi, fiyat önerileri, yorum analizi
- 💬 **AI Chatbot**: Gemini AI ile entegre ürün danışmanlığı
- 🗄️ **MongoDB**: Verilerin MongoDB'de saklanması
- 🌐 **Web Arayüzü**: Flask tabanlı web uygulaması

## Kurulum

### Gereksinimler

- Python 3.8+
- MongoDB
- Chrome/Chromium (Selenium için)
- ChromeDriver

### Adımlar

1. Repository'yi klonlayın:
```bash
git clone https://github.com/kullanici-adi/E-Ticaret-Projesi.git
cd E-Ticaret-Projesi
```

2. Virtual environment oluşturun:
```bash
python -m venv venv
venv\Scripts\activate  # Windows
# veya
source venv/bin/activate  # Linux/Mac
```

3. Bağımlılıkları yükleyin:
```bash
pip install -r requirements.txt
```

4. MongoDB'yi başlatın (localhost:27017)

5. Environment variables ayarlayın:
```bash
# .env dosyası oluşturun (veya .env.example'ı kopyalayın)
cp .env.example .env

# .env dosyasını düzenleyin ve GEMINI_API_KEY'inizi ekleyin
# Google AI Studio'dan API key alın: https://aistudio.google.com/app/apikey
```

6. `veri_toplama/targets.json` dosyasını düzenleyin ve ürün URL'lerini ekleyin

7. Flask uygulamasını başlatın:
```bash
python app.py
```

## Kullanım

### Veri Toplama

Tüm ürünleri scrape etmek için:
```bash
cd veri_toplama
python main.py
```

Sadece bir ürün için:
```bash
python main.py product_id
```

### Web Arayüzü

Tarayıcıda `http://localhost:5001` adresine gidin.

## Proje Yapısı

```
E-Ticaret-Projesi/
├── veri_toplama/      # Web scraping modülleri
│   ├── hb_scraping.py      # Hepsiburada scraper
│   ├── ty_scraper.py       # Trendyol scraper
│   ├── n11_scraper.py      # N11 scraper
│   ├── pazarama_scraper.py # Pazarama scraper
│   ├── ptt_scraper.py      # PTTAVM scraper
│   ├── main.py             # Ana scraper runner
│   └── utils.py            # Yardımcı fonksiyonlar
├── analiz/             # Veri analizi modülleri
│   ├── analiz.py          # Analiz fonksiyonları
├── templates/          # HTML şablonları
│   ├── index.html         # Ana sayfa
│   └── product_detail.html # Ürün detay sayfası
├── app.py              # Flask uygulaması
└── README.md           # Bu dosya
```

## Desteklenen Siteler

- ✅ Hepsiburada
- ✅ Trendyol
- ✅ N11
- ✅ Pazarama
- ✅ PTTAVM

## Notlar

- Scraping işlemleri yavaş olabilir (sayfa yükleme süreleri)
- Bazı siteler bot koruması kullanabilir
- MongoDB bağlantısı gereklidir
- ChromeDriver'ın Chrome sürümü ile uyumlu olması gerekir

## Lisans

Bu proje eğitim amaçlıdır.
Mühendislikte bilgisayar uygulamaları dersi kapsamında gerçekleştirilmiştir.

