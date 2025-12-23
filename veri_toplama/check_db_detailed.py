#!/usr/bin/env python3
"""
Veritabanındaki ürünleri ve hangi sitelerden geldiğini detaylı kontrol eder
"""
from pymongo import MongoClient

MONGO_DB_URL = "mongodb://localhost:27017/"
DB_NAME = "missha_price_data"
COLLECTION = "e_ticaret_offers"

if __name__ == "__main__":
    client = MongoClient(MONGO_DB_URL)
    db = client[DB_NAME]
    collection = db[COLLECTION]
    
    # Ürün bazında grupla ve hangi sitelerden geldiğini göster
    pipeline = [
        {
            "$group": {
                "_id": "$product_id",
                "product_name": {"$first": "$product_name"},
                "category": {"$first": "$category"},
                "sites": {"$addToSet": "$site"},
                "vendors": {"$addToSet": "$vendor_name"},
                "count": {"$sum": 1}
            }
        },
        {"$sort": {"product_name": 1}}
    ]
    
    products = list(collection.aggregate(pipeline))
    print(f"📊 Toplam {len(products)} farklı ürün:\n")
    
    for i, p in enumerate(products, 1):
        print(f"{i}. {p['product_name'][:60]}...")
        print(f"   ID: {p['_id']}")
        print(f"   Kategori: {p.get('category', 'N/A')}")
        print(f"   Kayıt sayısı: {p['count']}")
        print(f"   Siteler: {', '.join(sorted(p.get('sites', [])))}")
        print(f"   Satıcılar: {', '.join(sorted(p.get('vendors', []))[:5])}")  # İlk 5 satıcı
        if len(p.get('vendors', [])) > 5:
            print(f"   ... ve {len(p.get('vendors', [])) - 5} satıcı daha")
        print()
    
    # Site bazında özet
    print("\n📈 Site bazında özet:")
    site_pipeline = [
        {
            "$group": {
                "_id": "$site",
                "count": {"$sum": 1},
                "products": {"$addToSet": "$product_id"}
            }
        },
        {"$sort": {"count": -1}}
    ]
    sites = list(collection.aggregate(site_pipeline))
    for s in sites:
        print(f"   {s['_id']}: {s['count']} kayıt, {len(s['products'])} ürün")
    
    client.close()

