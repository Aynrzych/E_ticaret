#!/usr/bin/env python3
"""
L'Oreal Paris ürününü kontrol eder
"""
from pymongo import MongoClient

MONGO_DB_URL = "mongodb://localhost:27017/"
DB_NAME = "missha_price_data"
COLLECTION = "e_ticaret_offers"

if __name__ == "__main__":
    client = MongoClient(MONGO_DB_URL)
    db = client[DB_NAME]
    collection = db[COLLECTION]
    
    # L'Oreal Paris ürününü bul
    product_id = "l_oreal_paris_revitalif_728839"
    
    pipeline = [
        {"$match": {"product_id": product_id}},
        {
            "$group": {
                "_id": {"site": "$site", "vendor_name": "$vendor_name"},
                "count": {"$sum": 1},
                "price": {"$last": "$price"},
                "scrape_ts": {"$last": "$scrape_ts"}
            }
        },
        {"$sort": {"_id.site": 1}}
    ]
    
    results = list(collection.aggregate(pipeline))
    
    print(f"📊 L'Oreal Paris ürünü için {len(results)} farklı site+vendor kaydı:\n")
    
    for r in results:
        print(f"   {r['_id']['site']:15} | {r['_id']['vendor_name']:30} | {r['price']} TL | {r['scrape_ts']}")
    
    # Hangi sitelerden veri var?
    sites = set(r['_id']['site'] for r in results)
    all_sites = ['hepsiburada', 'trendyol', 'n11', 'pttavm', 'pazarama']
    missing_sites = [s for s in all_sites if s not in sites]
    
    print(f"\n✅ Veri olan siteler: {', '.join(sorted(sites))}")
    if missing_sites:
        print(f"❌ Veri olmayan siteler: {', '.join(missing_sites)}")
    
    client.close()

