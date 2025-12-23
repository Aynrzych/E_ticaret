#!/usr/bin/env python3
"""
MongoDB'deki verilerin reviews_list alanını kontrol eder.
"""
from pymongo import MongoClient

MONGO_DB_URL = "mongodb://localhost:27017/"
DB_NAME = "missha_price_data"
COLLECTION = "e_ticaret_offers"

if __name__ == "__main__":
    client = MongoClient(MONGO_DB_URL)
    db = client[DB_NAME]
    collection = db[COLLECTION]
    
    # Toplam kayıt sayısı
    total = collection.count_documents({})
    print(f"📊 Toplam kayıt sayısı: {total}\n")
    
    if total == 0:
        print("⚠️  Henüz veri yok!")
        client.close()
        exit()
    
    # reviews_list olan kayıtlar
    with_reviews = collection.count_documents({"reviews_list": {"$exists": True, "$ne": []}})
    with_reviews_but_empty = collection.count_documents({"reviews_list": []})
    without_reviews = collection.count_documents({"reviews_list": {"$exists": False}})
    
    print(f"✅ Yorum metinleri olan kayıt: {with_reviews}")
    print(f"⚠️  reviews_list boş olan kayıt: {with_reviews_but_empty}")
    print(f"❌ reviews_list olmayan kayıt: {without_reviews}\n")
    
    # Örnek kayıt göster
    sample = collection.find_one({"reviews_list": {"$exists": True, "$ne": []}})
    if sample:
        print("📝 Örnek kayıt:")
        print(f"   Site: {sample.get('site')}")
        print(f"   Ürün: {sample.get('product_name', 'N/A')[:50]}...")
        print(f"   Rating: {sample.get('rating')}")
        print(f"   Review Count: {sample.get('review_count')}")
        reviews_list = sample.get('reviews_list', [])
        print(f"   Yorum metni sayısı: {len(reviews_list)}")
        if reviews_list:
            first_review = reviews_list[0]
            print(f"   İlk yorum puanı: {first_review.get('rating')}")
            print(f"   İlk yorum metni (ilk 100 karakter): {first_review.get('text', '')[:100]}...")
    else:
        print("⚠️  Yorum metinleri olan kayıt bulunamadı!")
    
    client.close()

