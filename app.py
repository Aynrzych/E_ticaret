from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_pymongo import PyMongo
import os
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

from analiz.analiz import rakip_analizi, dinamik_fiyat_oneri, load_data, puan_ozellik_analizi, yuksek_puan_yorum_analizi

# Gemini API için
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
    print("✅ Gemini API paketi yüklü")
except ImportError:
    GEMINI_AVAILABLE = False
    genai = None
    print("⚠️ google-generativeai paketi yüklü değil. 'pip install google-generativeai' komutu ile yükleyin.")

# Gemini API Key - .env dosyasından oku
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Eğer API key boşsa uyarı ver
if not GEMINI_API_KEY:
    print("⚠️ UYARI: GEMINI_API_KEY bulunamadı. Chatbot özelliği çalışmayacak.")
    print("   💡 .env dosyası oluşturup GEMINI_API_KEY=your_api_key_here ekleyin.")

app = Flask(__name__)

app.config["MONGO_URI"] = "mongodb://localhost:27017/missha_price_data"
mongo = PyMongo(app)


@app.route("/")
def index():
    """
    Tüm ürünleri (product_id bazında) listeler.
    """
    pipeline = [
        {
            "$group": {
                "_id": "$product_id",
                "product_name": {"$first": "$product_name"},
                "category": {"$first": "$category"},
            }
        },
        {"$sort": {"product_name": 1}},
    ]
    products = list(mongo.db.e_ticaret_offers.aggregate(pipeline))
    # Flask tarafında erişimi kolaylaştırmak için _id yerine product_id kullan
    for p in products:
        p["product_id"] = p.pop("_id")
    return render_template("index.html", products=products)


@app.route("/product/<product_id>")
def product_detail(product_id):
    """
    Belirli bir ürün için son fiyatlar, rakip analizi ve basit dinamik fiyat önerisini gösterir.
    """
    # En güncel teklifler (site+vendor+seller_nickname bazında - Pazarama için tüm satıcıları göster)
    # seller_nickname None ise vendor_name kullanılır (gruplama için)
    pipeline = [
        {"$match": {"product_id": product_id}},
        {"$sort": {"scrape_ts": 1}},
        {
            "$group": {
                "_id": {
                    "site": "$site",
                    "vendor_name": "$vendor_name",
                    "seller_nickname": {"$ifNull": ["$seller_nickname", ""]}  # None ise boş string
                },
                "product_name": {"$last": "$product_name"},
                "category": {"$last": "$category"},
                "price": {"$last": "$price"},
                "rating": {"$last": "$rating"},
                "review_count": {"$last": "$review_count"},
                "scrape_ts": {"$last": "$scrape_ts"},
                "seller_nickname_original": {"$last": "$seller_nickname"},  # Orijinal değeri de sakla
            }
        },
        {"$sort": {"price": 1}},
    ]
    offers = list(mongo.db.e_ticaret_offers.aggregate(pipeline))
    
    # seller_nickname'i düzelt (boş string ise None yap)
    for offer in offers:
        if offer["_id"]["seller_nickname"] == "":
            offer["_id"]["seller_nickname"] = None
        else:
            # Orijinal değeri kullan
            offer["_id"]["seller_nickname"] = offer.get("seller_nickname_original")
    
    # En ucuz fiyatı hesapla (None olmayan fiyatlar arasından)
    valid_prices = [o["price"] for o in offers if o.get("price") is not None and isinstance(o["price"], (int, float))]
    min_price = min(valid_prices) if valid_prices else None
    
    if not offers:
        return render_template(
            "product_detail.html",
            product_id=product_id,
            product_name="Veri bulunamadı",
            offers=[],
            fiyat_oneri=None,
        )

    product_name = offers[0].get("product_name", product_id)

    # Analiz fonksiyonlarını çağır
    fiyat_oneri = dinamik_fiyat_oneri(product_id)
    # rakip_analizi pandas DataFrame döndürüyor; tabloya çevirmek istersen
    rakip_df = rakip_analizi(product_id)
    rakip_rows = (
        rakip_df.to_dict(orient="records") if rakip_df is not None else None
    )
    # Rakip analizi için en ucuz fiyatı hesapla
    rakip_min_price = None
    if rakip_rows:
        valid_rakip_prices = [r.get("price") for r in rakip_rows if r.get("price") is not None and isinstance(r.get("price"), (int, float))]
        rakip_min_price = min(valid_rakip_prices) if valid_rakip_prices else None
    # Yüksek puanlı yorum analizi
    yorum_analizi = yuksek_puan_yorum_analizi(product_id)

    return render_template(
        "product_detail.html",
        product_id=product_id,
        product_name=product_name,
        offers=offers,
        min_price=min_price,  # En ucuz fiyatı template'e gönder
        fiyat_oneri=fiyat_oneri,
        rakip_rows=rakip_rows,
        rakip_min_price=rakip_min_price,  # Rakip analizi için en ucuz fiyat
        yorum_analizi=yorum_analizi,
    )


@app.route("/api/chat", methods=["POST"])
def chat_api():
    """
    Gemini AI ile güçlendirilmiş ürün sohbet API'si.
    Gönderim örneği (JSON):
    {
      "product_id": "missha_sunscreen_50ml",
      "question": "Bu üründe en ucuz fiyat ve en yüksek puanlı satıcı kim?"
    }
    """
    data = request.get_json(silent=True) or {}
    product_id = data.get("product_id")
    question = data.get("question", "")
    conversation_history = data.get("history", [])  # Önceki konuşma geçmişi

    if not product_id:
        return jsonify({"error": "product_id alanı gerekli."}), 400

    df = load_data(product_id)
    if df.empty:
        return jsonify({"answer": "Bu ürün için henüz veri bulunamadı."})

    # seller_nickname None ise boş string yap (gruplama için)
    df["seller_nickname"] = df["seller_nickname"].fillna("")
    
    # En güncel kayıtlar (seller_nickname'i de dahil et)
    latest = (
        df.sort_values("scrape_ts")
        .groupby(["site", "vendor_name", "seller_nickname"], as_index=False)
        .tail(1)
    )
    
    # seller_nickname boş string ise None yap
    latest["seller_nickname"] = latest["seller_nickname"].replace("", None)

    # En ucuz teklif
    cheapest = latest.sort_values("price").iloc[0]

    # En yüksek puanlı (puanı olanlar arasından)
    rated = latest.dropna(subset=["rating"])
    best_rated = rated.sort_values(["rating", "review_count"], ascending=[False, False]).iloc[0] if not rated.empty else None

    fiyat_oneri = dinamik_fiyat_oneri(product_id)
    oz_analiz = puan_ozellik_analizi(product_id)
    yorum_analizi = yuksek_puan_yorum_analizi(product_id)

    # Ürün verilerini hazırla (Gemini için context)
    product_context = {
        "product_id": product_id,
        "product_name": latest.iloc[0]["product_name"] if not latest.empty else product_id,
        "category": latest.iloc[0].get("category", ""),
        "cheapest": {
            "site": cheapest["site"],
            "vendor_name": cheapest["vendor_name"],
            "seller_nickname": cheapest.get("seller_nickname") or None,
            "price": float(cheapest["price"]),
        },
        "best_rated": {
            "site": best_rated["site"],
            "vendor_name": best_rated["vendor_name"],
            "seller_nickname": best_rated.get("seller_nickname") or None,
            "rating": float(best_rated["rating"]),
            "review_count": int(best_rated["review_count"] or 0),
        } if best_rated is not None else None,
        "fiyat_oneri": fiyat_oneri,
        "teklifler": latest[["site", "vendor_name", "seller_nickname", "price", "rating", "review_count"]].to_dict("records"),
    }
    
    if yorum_analizi:
        product_context["yorum_analizi"] = yorum_analizi

    # Gemini API kullan (eğer mevcut ve key varsa)
    if GEMINI_AVAILABLE and GEMINI_API_KEY and GEMINI_API_KEY.strip():
        try:
            api_key = GEMINI_API_KEY.strip()
            print(f"DEBUG: Gemini API key uzunluğu: {len(api_key)}")
            print(f"DEBUG: Gemini API key başlangıcı: {api_key[:10]}...")
            
            # API key'i yapılandır
            genai.configure(api_key=api_key)
            print("DEBUG: Gemini API yapılandırıldı")
            
            # API key'in geçerli olup olmadığını test et
            try:
                test_models = list(genai.list_models())
                print(f"DEBUG: ✅ API key geçerli! {len(test_models)} model bulundu")
            except Exception as key_test_error:
                print(f"DEBUG: ❌ API key geçersiz veya hatalı: {key_test_error}")
                raise Exception(f"API key geçersiz. Lütfen Google AI Studio'dan yeni bir API key alın. Hata: {key_test_error}")
            
            # Önce mevcut modelleri listele ve uygun olanı seç
            model = None
            try:
                print("DEBUG: Mevcut modeller listeleniyor...")
                available_models = list(genai.list_models())
                print(f"DEBUG: Toplam {len(available_models)} model bulundu")
                
                # Uygun modeli bul (generateContent destekleyen)
                for m in available_models:
                    model_name = m.name
                    # Model adını temizle (models/ prefix'i varsa kaldır)
                    clean_name = model_name.split('/')[-1] if '/' in model_name else model_name
                    
                    # generateContent destekleyen modelleri kontrol et
                    if 'generateContent' in str(m.supported_generation_methods):
                        try:
                            model = genai.GenerativeModel(clean_name)
                            print(f"DEBUG: ✅ Model seçildi: {clean_name} (tam ad: {model_name})")
                            break
                        except Exception as e:
                            print(f"DEBUG: {clean_name} modeli oluşturulamadı: {e}")
                            continue
                
                # Eğer hala model bulunamadıysa, ilk modeli dene
                if model is None:
                    print("DEBUG: Uygun model bulunamadı, ilk model deneniyor...")
                    if available_models:
                        first_model = available_models[0]
                        clean_name = first_model.name.split('/')[-1] if '/' in first_model.name else first_model.name
                        model = genai.GenerativeModel(clean_name)
                        print(f"DEBUG: İlk model seçildi: {clean_name}")
                    else:
                        raise Exception("Hiç model bulunamadı. API key geçersiz olabilir.")
                        
            except Exception as list_error:
                print(f"DEBUG: Model listesi alınamadı: {list_error}")
                # Fallback: Yaygın model isimlerini dene
                fallback_models = ['gemini-pro', 'gemini-1.5-pro', 'gemini-1.5-flash', 'models/gemini-pro']
                for fallback_name in fallback_models:
                    try:
                        model = genai.GenerativeModel(fallback_name)
                        print(f"DEBUG: Fallback model seçildi: {fallback_name}")
                        break
                    except:
                        continue
                
                if model is None:
                    raise Exception(f"Hiçbir model çalışmıyor. API key kontrol edilmeli. Hata: {list_error}")
            
            # Context'i prompt'a çevir
            cheapest_seller = product_context['cheapest']['vendor_name']
            if product_context['cheapest'].get('seller_nickname'):
                cheapest_seller += f" ({product_context['cheapest']['seller_nickname']})"
            
            best_rated_seller = product_context['best_rated']['vendor_name'] if product_context['best_rated'] else 'Yok'
            if product_context['best_rated'] and product_context['best_rated'].get('seller_nickname'):
                best_rated_seller += f" ({product_context['best_rated']['seller_nickname']})"
            
            context_str = f"""
Ürün Bilgileri:
- Ürün ID: {product_context['product_id']}
- Ürün Adı: {product_context['product_name']}
- Kategori: {product_context['category']}

Fiyat Bilgileri:
- En ucuz teklif: {product_context['cheapest']['site']} / {cheapest_seller} - {product_context['cheapest']['price']} TL
- En yüksek puanlı: {product_context['best_rated']['site'] if product_context['best_rated'] else 'Yok'} / {best_rated_seller} - {product_context['best_rated']['rating'] if product_context['best_rated'] else 'N/A'} puan

"""
            
            if fiyat_oneri:
                context_str += f"Fiyat Önerisi: Önerilen fiyat {fiyat_oneri['onerilen_fiyat']} TL (en düşük rakip: {fiyat_oneri['min_rakip_fiyati']} TL)\n"
            
            if yorum_analizi:
                context_str += f"""
Yorum Analizi:
- Yüksek puanlı yorum sayısı: {yorum_analizi.get('yuksek_puan_yorum_sayisi', 0)}
- Düşük puanlı yorum sayısı: {yorum_analizi.get('dusuk_puan_yorum_sayisi', 0)}
- En sık geçen kelimeler (yüksek puan): {', '.join([k['kelime'] for k in yorum_analizi.get('yuksek_puan_kelimeler', [])[:5]])}
"""
            
            # Conversation history'yi ekle (son 10 mesajı al - çok uzun olmasın)
            history_text = ""
            if conversation_history:
                history_text = "\n\nÖnceki Konuşma Geçmişi:\n"
                for msg in conversation_history[-10:]:  # Son 10 mesajı al
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if role == "user":
                        history_text += f"Kullanıcı: {content}\n"
                    elif role == "assistant":
                        history_text += f"Danışman: {content}\n"
            
            # System prompt + context + history + current question
            system_prompt = """Sen bir e-ticaret ürün danışmanısın. Kullanıcıya ürün bilgilerine göre yardımcı oluyorsun. 
Önceki konuşmayı dikkate al, bağlamı koru ve doğal bir sohbet akışı sağla. Türkçe, samimi ve yardımcı ol."""
            
            full_prompt = f"""{system_prompt}

ÜRÜN BİLGİLERİ:
{context_str}
{history_text}

ŞİMDİKİ SORU: {question}

Lütfen kullanıcının sorusunu, önceki konuşmayı dikkate alarak Türkçe, doğal ve samimi bir dille cevapla. 
Sadece verilen ürün bilgilerine dayanarak cevap ver, varsayım yapma."""
            
            print("DEBUG: Gemini API'ye istek gönderiliyor...")
            # Gemini API ile içerik üret
            response = model.generate_content(full_prompt)
            answer = response.text.strip()
            print("DEBUG: Gemini API'den cevap alındı")
            
        except Exception as e:
            print(f"❌ Gemini API hatası: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            if "API_KEY" in str(e) or "api key" in str(e).lower() or "authentication" in str(e).lower() or "403" in str(e) or "401" in str(e):
                print("   ⚠️ API key geçersiz veya eksik. Lütfen GEMINI_API_KEY'i kontrol edin.")
                answer = "Üzgünüm, API anahtarınız geçersiz veya eksik. Lütfen API anahtarınızı kontrol edin."
            elif "quota" in str(e).lower() or "429" in str(e) or "ResourceExhausted" in str(type(e).__name__):
                print("   ⚠️ API quota aşıldı veya rate limit.")
                print("   📌 Açıklama: Gemini API'nin ücretsiz planında günlük 20 istek limiti var.")
                print("   💡 Çözüm: 24 saat sonra limit sıfırlanır veya ücretli plana geçebilirsiniz.")
                print("   🔗 Detaylar: https://ai.google.dev/gemini-api/docs/rate-limits")
                answer = "Üzgünüm, günlük API istek limitiniz dolmuş. Ücretsiz plan günde 20 istek ile sınırlıdır. 24 saat sonra limit sıfırlanacak veya ücretli plana geçebilirsiniz. Şimdilik basit cevaplar alabilirsiniz."
            else:
                # Fallback: Basit cevap
                answer = fallback_answer(question.lower(), product_context)
    else:
        # Gemini yoksa basit cevap
        if not GEMINI_AVAILABLE:
            print("⚠️ Gemini API paketi yüklü değil. 'pip install google-generativeai' komutu ile yükleyin.")
        elif not GEMINI_API_KEY or not GEMINI_API_KEY.strip():
            print("⚠️ Gemini API key bulunamadı. Chatbot özelliği devre dışı.")
        answer = fallback_answer(question.lower(), product_context)

    return jsonify(
        {
            "answer": answer,
            "cheapest": product_context["cheapest"],
            "best_rated": product_context["best_rated"],
            "fiyat_oneri": fiyat_oneri,
        }
    )


def fallback_answer(question_lower: str, context: dict) -> str:
    """Gemini kullanılamazsa basit cevap üretir."""
    # Fiyat soruları
    if any(k in question_lower for k in ["en ucuz", "fiyat", "ucuz", "ne kadar", "kaç para", "fiyatı"]):
        cheapest_seller = context['cheapest']['vendor_name']
        if context['cheapest'].get('seller_nickname'):
            cheapest_seller += f" ({context['cheapest']['seller_nickname']})"
        
        answer = (
            f"Şu anda en ucuz teklif {context['cheapest']['site']} / {cheapest_seller} "
            f"tarafından {context['cheapest']['price']} TL fiyatla sunuluyor."
        )
        if context.get("fiyat_oneri"):
            answer += (
                f" Dinamik fiyat modeline göre önerilen satış fiyatı ise "
                f"{context['fiyat_oneri']['onerilen_fiyat']} TL (en düşük rakip {context['fiyat_oneri']['min_rakip_fiyati']} TL)."
            )
        # Tüm teklifleri listele
        if context.get("teklifler") and len(context["teklifler"]) > 1:
            answer += "\n\nDiğer teklifler: "
            other_offers = [t for t in context["teklifler"][:5] 
                          if t["site"] != context['cheapest']['site'] or 
                             t["vendor_name"] != context['cheapest']['vendor_name'] or
                             t.get("seller_nickname") != context['cheapest'].get('seller_nickname')]
            for offer in other_offers[:3]:
                seller_display = offer['vendor_name']
                if offer.get('seller_nickname'):
                    seller_display += f" ({offer['seller_nickname']})"
                answer += f"{offer['site']} / {seller_display}: {offer['price']} TL, "
            answer = answer.rstrip(", ")
    
    # Puan ve yorum soruları
    elif any(k in question_lower for k in ["puan", "yorum", "memnun", "değerlendirme", "rating", "yıldız"]):
        if context.get("best_rated"):
            best_rated_seller = context['best_rated']['vendor_name']
            if context['best_rated'].get('seller_nickname'):
                best_rated_seller += f" ({context['best_rated']['seller_nickname']})"
            
            answer = (
                f"En yüksek puanlı teklif {context['best_rated']['site']} / {best_rated_seller}."
                f" Ortalama puan {context['best_rated']['rating']} ve toplam yorum sayısı {context['best_rated']['review_count']}."
            )
            # Yorum analizi varsa ekle
            if context.get("yorum_analizi"):
                yorum = context["yorum_analizi"]
                if yorum.get("yuksek_puan_yorum_sayisi"):
                    answer += f" Yüksek puanlı (4-5 yıldız) yorum sayısı: {yorum['yuksek_puan_yorum_sayisi']}."
                if yorum.get("dusuk_puan_yorum_sayisi"):
                    answer += f" Düşük puanlı (1-2 yıldız) yorum sayısı: {yorum['dusuk_puan_yorum_sayisi']}."
        else:
            answer = "Bu ürün için henüz puan verisi bulunmuyor."
    
    # Satıcı soruları
    elif any(k in question_lower for k in ["satıcı", "vendor", "nerede", "nereden", "hangi site"]):
        answer = f"{context['product_name']} için mevcut satıcılar:\n"
        if context.get("teklifler"):
            for offer in context["teklifler"][:5]:
                seller_display = offer['vendor_name']
                if offer.get('seller_nickname'):
                    seller_display += f" ({offer['seller_nickname']})"
                answer += f"- {offer['site']} / {seller_display}: {offer['price']} TL"
                if offer.get("rating"):
                    answer += f" (Puan: {offer['rating']}, Yorum: {offer.get('review_count', 0)})"
                answer += "\n"
        else:
            cheapest_seller = context['cheapest']['vendor_name']
            if context['cheapest'].get('seller_nickname'):
                cheapest_seller += f" ({context['cheapest']['seller_nickname']})"
            answer += f"En ucuz: {context['cheapest']['site']} / {cheapest_seller} - {context['cheapest']['price']} TL"
    
    # Karşılaştırma soruları
    elif any(k in question_lower for k in ["karşılaştır", "fark", "hangi", "hangisi", "öner"]):
        cheapest_seller = context['cheapest']['vendor_name']
        if context['cheapest'].get('seller_nickname'):
            cheapest_seller += f" ({context['cheapest']['seller_nickname']})"
        
        answer = f"{context['product_name']} için:\n"
        answer += f"✅ En ucuz: {context['cheapest']['site']} / {cheapest_seller} - {context['cheapest']['price']} TL\n"
        if context.get("best_rated"):
            best_rated_seller = context['best_rated']['vendor_name']
            if context['best_rated'].get('seller_nickname'):
                best_rated_seller += f" ({context['best_rated']['seller_nickname']})"
            answer += f"⭐ En yüksek puanlı: {context['best_rated']['site']} / {best_rated_seller} - {context['best_rated']['rating']} puan ({context['best_rated']['review_count']} yorum)\n"
        if context.get("fiyat_oneri"):
            answer += f"💡 Önerilen fiyat: {context['fiyat_oneri']['onerilen_fiyat']} TL"
    
    # Genel bilgi
    else:
        cheapest_seller = context['cheapest']['vendor_name']
        if context['cheapest'].get('seller_nickname'):
            cheapest_seller += f" ({context['cheapest']['seller_nickname']})"
        
        answer = (
            f"{context['product_name']} için şu an en ucuz teklif {context['cheapest']['site']} / {cheapest_seller} "
            f"ile {context['cheapest']['price']} TL."
        )
        if context.get("best_rated"):
            best_rated_seller = context['best_rated']['vendor_name']
            if context['best_rated'].get('seller_nickname'):
                best_rated_seller += f" ({context['best_rated']['seller_nickname']})"
            answer += (
                f" En yüksek puanlı satıcı ise {context['best_rated']['site']} / {best_rated_seller} "
                f"({context['best_rated']['rating']} puan, {context['best_rated']['review_count']} yorum)."
            )
        if context.get("fiyat_oneri"):
            answer += f" Önerilen satış fiyatı: {context['fiyat_oneri']['onerilen_fiyat']} TL."
    
    return answer


if __name__ == "__main__":
    # Bu proje için farklı port kullan (diğer proje muhtemelen 5000'de)
    # Eğer diğer projede farklı port kullanıyorsanız, burayı 5000 yapabilirsiniz
    app.run(debug=True, port=5001)
