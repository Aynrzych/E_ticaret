from pymongo import MongoClient
import pandas as pd

MONGO_DB_URL = "mongodb://localhost:27017/"
DB_NAME = "missha_price_data"
COLLECTION = "e_ticaret_offers"


def _get_collection():
    client = MongoClient(MONGO_DB_URL)
    db = client[DB_NAME]
    return db[COLLECTION]


def load_data(product_id: str) -> pd.DataFrame:
    """
    Belirli bir product_id için e_ticaret_offers koleksiyonundan tüm kayıtları DataFrame olarak döndürür.
    """
    col = _get_collection()
    docs = list(col.find({"product_id": product_id}))
    if not docs:
        return pd.DataFrame()
    df = pd.DataFrame(docs)
    if "scrape_ts" in df.columns:
        df["scrape_ts"] = pd.to_datetime(df["scrape_ts"], errors="coerce")
    return df


def fiyat_trendi(product_id: str) -> pd.DataFrame | None:
    """
    Zaman içinde min / max / ortalama fiyat trendini döndürür.
    """
    df = load_data(product_id)
    if df.empty or "scrape_ts" not in df.columns:
        return None

    trend = (
        df.groupby("scrape_ts")["price"]
        .agg(["min", "max", "mean"])
        .reset_index()
        .sort_values("scrape_ts")
    )
    return trend


def rakip_analizi(product_id: str) -> pd.DataFrame | None:
    """
    Her site + satıcı + seller_nickname için son (en güncel) fiyat / puan / yorum sayısını döndürür.
    seller_nickname'i de dahil ederek Pazarama gibi sitelerde farklı satıcıları ayırt eder.
    """
    df = load_data(product_id)
    if df.empty:
        return None

    # seller_nickname None ise boş string yap (gruplama için)
    df["seller_nickname"] = df["seller_nickname"].fillna("")

    # En son scrape edilen kayıtları al (site + vendor_name + seller_nickname bazında)
    latest = (
        df.sort_values("scrape_ts")
        .groupby(["site", "vendor_name", "seller_nickname"], as_index=False)
        .tail(1)
    )

    # seller_nickname boş string ise None yap
    latest["seller_nickname"] = latest["seller_nickname"].replace("", None)

    latest = latest.sort_values("price")
    cols = ["site", "vendor_name", "seller_nickname", "price", "rating", "review_count"]
    return latest[cols]


def dinamik_fiyat_oneri(product_id: str, marj_yuzde: float = 5.0) -> dict | None:
    """
    Basit dinamik fiyat modeli:
    - Tüm sitelerdeki en düşük güncel fiyatı bulur (seller_nickname'i de dikkate alarak).
    - Bu fiyata göre belirli bir marj ile önerilen fiyat döner.
    """
    df = load_data(product_id)
    if df.empty:
        return None

    # seller_nickname None ise boş string yap (gruplama için)
    df["seller_nickname"] = df["seller_nickname"].fillna("")

    # En son scrape edilen kayıtları al (site + vendor_name + seller_nickname bazında)
    latest = (
        df.sort_values("scrape_ts")
        .groupby(["site", "vendor_name", "seller_nickname"], as_index=False)
        .tail(1)
    )

    min_price = latest["price"].min()
    suggested = round(min_price * (1 + marj_yuzde / 100), 2)

    return {
        "product_id": product_id,
        "min_rakip_fiyati": float(min_price),
        "onerilen_fiyat": suggested,
        "marj_yuzde": marj_yuzde,
    }


def puan_ozellik_analizi(product_id: str) -> pd.DataFrame | None:
    """
    Basitleştirilmiş puan analizi:
    - Site bazında ortalama puan ve toplam yorum sayısını döndürür.
    - İleri seviye metin analizi (yorum içeriği) bu projede opsiyonel tutulmuştur.
    """
    df = load_data(product_id)
    if df.empty or "rating" not in df.columns:
        return None

    agg = (
        df.groupby("site")
        .agg(
            ort_puan=("rating", "mean"),
            toplam_yorum=("review_count", "sum"),
            teklif_sayisi=("price", "count"),
        )
        .reset_index()
        .sort_values("ort_puan", ascending=False)
    )
    return agg


def yuksek_puan_yorum_analizi(product_id: str, min_rating: int = 4, top_k: int = 20) -> dict | None:
    """
    Yüksek puanlı yorumlardaki ortak kelimeleri analiz eder.
    
    Args:
        product_id: Ürün ID'si
        min_rating: Minimum puan (varsayılan: 4, yani 4-5 yıldız)
        top_k: En çok geçen kaç kelime gösterilecek (varsayılan: 20)
    
    Returns:
        {
            "yuksek_puan_kelimeler": [{"kelime": "...", "frekans": X}, ...],
            "dusuk_puan_kelimeler": [{"kelime": "...", "frekans": Y}, ...],
            "yuksek_puan_yorum_sayisi": int,
            "dusuk_puan_yorum_sayisi": int,
            "ortalama_yuksek_puan": float,
            "ortalama_dusuk_puan": float
        }
    """
    import re
    from collections import Counter
    from pymongo import MongoClient
    
    client = MongoClient(MONGO_DB_URL)
    db = client[DB_NAME]
    collection = db[COLLECTION]
    
    # Ürün için tüm kayıtları çek (reviews_list olanları)
    products = list(collection.find({
        "product_id": product_id,
        "reviews_list": {"$exists": True, "$ne": []}
    }))
    
    if not products:
        client.close()
        return None
    
    # Türkçe stop words (gereksiz kelimeler) - genişletilmiş liste
    stop_words = {
        "bir", "bu", "şu", "o", "ve", "ile", "için", "de", "da", "ki", "mi", "mu", "mü",
        "çok", "az", "en", "gibi", "kadar", "daha", "var", "yok", "ama", "ancak",
        "fakat", "lakin", "şey", "her", "hiç", "kim", "ne", "nasıl", "niçin", "neden",
        "ben", "sen", "biz", "siz", "onlar", "bana", "sana", "bize", "size", "onlara",
        "ile", "gibi", "kadar", "için", "göre", "dolayı", "rağmen", "karşı", "doğru",
        "kadar", "sonra", "önce", "beri", "dışında", "içinde", "üzerinde", "altında",
        "ürün", "ürünü", "ürünün", "fiyat", "fiyatı", "fiyatın", "satıcı", "satıcıyı",
        "almış", "aldım", "alındı", "geldi", "geldim", "geldiği", "oldu", "olduğu",
        "iyi", "kötü", "güzel", "çirkin", "beğendim", "beğenmedim", "tavsiye", "tavsiye ederim"
    }
    
    def temizle_ve_ayir(text):
        """Metni temizler ve kelimelere ayırır."""
        if not text or not isinstance(text, str):
            return []
        # Küçük harfe çevir
        text = text.lower()
        # Özel karakterleri kaldır, sadece harfler ve Türkçe karakterler
        text = re.sub(r'[^a-zçğıöşü\s]', ' ', text)
        # Kelimelere ayır
        kelimeler = text.split()
        # Stop words'leri ve 2 karakterden kısa kelimeleri filtrele
        kelimeler = [k for k in kelimeler if len(k) > 2 and k not in stop_words]
        return kelimeler
    
    yuksek_puan_yorumlar = []
    dusuk_puan_yorumlar = []
    yuksek_puan_ratings = []
    dusuk_puan_ratings = []
    
    # Tüm ürünlerden yorumları topla
    for product in products:
        reviews = product.get("reviews_list", [])
        if not reviews or not isinstance(reviews, list):
            continue
        
        for review in reviews:
            if not isinstance(review, dict):
                continue
            
            review_text = review.get("text")
            review_rating = review.get("rating")
            
            # Text kontrolü - boş veya çok kısa yorumları atla
            if not review_text or not isinstance(review_text, str) or len(review_text.strip()) < 10:
                continue
            
            # Rating varsa kullan, yoksa None olarak işle
            if review_rating is not None:
                try:
                    # Rating'i float'a çevir
                    if isinstance(review_rating, str):
                        # String ise sayısal kısmını çıkar
                        rating_match = re.search(r'(\d+(?:\.\d+)?)', str(review_rating))
                        if rating_match:
                            rating_val = float(rating_match.group(1))
                        else:
                            continue
                    else:
                        rating_val = float(review_rating)
                    
                    # Rating değerini kontrol et (1-5 arası olmalı)
                    if not (1 <= rating_val <= 5):
                        continue
                    
                    if rating_val >= min_rating:
                        yuksek_puan_yorumlar.append(review_text.strip())
                        yuksek_puan_ratings.append(rating_val)
                    elif rating_val <= 2:  # Düşük puan (1-2 yıldız)
                        dusuk_puan_yorumlar.append(review_text.strip())
                        dusuk_puan_ratings.append(rating_val)
                except (ValueError, TypeError) as e:
                    # Rating geçersizse atla
                    continue
            else:
                # Rating yoksa, yorumu yüksek puanlı olarak kabul et (varsayılan)
                # Çünkü bazı sitelerde rating bilgisi yorum metninde olmayabilir
                yuksek_puan_yorumlar.append(review_text.strip())
    
    # Eğer hiç yorum yoksa None döndür
    if not yuksek_puan_yorumlar and not dusuk_puan_yorumlar:
        client.close()
        return None
    
    # Kelime frekanslarını hesapla
    def kelime_frekansi(yorumlar):
        tum_kelimeler = []
        for yorum in yorumlar:
            kelimeler = temizle_ve_ayir(yorum)
            tum_kelimeler.extend(kelimeler)
        return Counter(tum_kelimeler)
    
    yuksek_kelimeler = kelime_frekansi(yuksek_puan_yorumlar) if yuksek_puan_yorumlar else Counter()
    dusuk_kelimeler = kelime_frekansi(dusuk_puan_yorumlar) if dusuk_puan_yorumlar else Counter()
    
    # En çok geçen kelimeleri al
    yuksek_top = [{"kelime": kelime, "frekans": sayi} 
                  for kelime, sayi in yuksek_kelimeler.most_common(top_k)]
    dusuk_top = [{"kelime": kelime, "frekans": sayi} 
                 for kelime, sayi in dusuk_kelimeler.most_common(top_k)]
    
    # Ortalama puanları hesapla
    ortalama_yuksek = sum(yuksek_puan_ratings) / len(yuksek_puan_ratings) if yuksek_puan_ratings else None
    ortalama_dusuk = sum(dusuk_puan_ratings) / len(dusuk_puan_ratings) if dusuk_puan_ratings else None
    
    client.close()
    
    return {
        "yuksek_puan_kelimeler": yuksek_top,
        "dusuk_puan_kelimeler": dusuk_top,
        "yuksek_puan_yorum_sayisi": len(yuksek_puan_yorumlar),
        "dusuk_puan_yorum_sayisi": len(dusuk_puan_yorumlar),
        "ortalama_yuksek_puan": round(ortalama_yuksek, 2) if ortalama_yuksek else None,
        "ortalama_dusuk_puan": round(ortalama_dusuk, 2) if ortalama_dusuk else None
    }