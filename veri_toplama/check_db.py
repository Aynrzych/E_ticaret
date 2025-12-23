#!/usr/bin/env python3
"""
Veritabanındaki ürünleri kontrol eder
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
    
    # Ürün bazında grupla
    pipeline = [
        {
            "$group": {
                "_id": "$product_id",
                "product_name": {"$first": "$product_name"},
                "category": {"$first": "$category"},
                "count": {"$sum": 1}
            }
        },
        {"$sort": {"product_name": 1}}
    ]
    
    products = list(collection.aggregate(pipeline))
    print(f"📦 Toplam {len(products)} farklı ürün:\n")
    
    for i, p in enumerate(products, 1):
        print(f"{i}. {p['product_name'][:60]}...")
        print(f"   ID: {p['_id']}")
        print(f"   Kategori: {p.get('category', 'N/A')}")
        print(f"   Kayıt sayısı: {p['count']}")
        print()
    
    # Son eklenen 5 kayıt
    print("\n📝 Son eklenen 5 kayıt:")
    recent = list(collection.find().sort("scrape_ts", -1).limit(5))
    for r in recent:
        print(f"   - {r.get('product_name', 'N/A')[:50]}... | {r.get('site')} | {r.get('scrape_ts')}")
    
    client.close()

