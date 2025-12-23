#!/usr/bin/env python3
"""
MongoDB'deki e_ticaret_offers collection'ını temizler.
"""
from pymongo import MongoClient

MONGO_DB_URL = "mongodb://localhost:27017/"
DB_NAME = "missha_price_data"
COLLECTION = "e_ticaret_offers"

if __name__ == "__main__":
    client = MongoClient(MONGO_DB_URL)
    db = client[DB_NAME]
    collection = db[COLLECTION]
    
    # Mevcut kayıt sayısını göster
    count_before = collection.count_documents({})
    print(f"⚠️  Mevcut kayıt sayısı: {count_before}")
    
    if count_before > 0:
        # Kullanıcıdan onay al
        response = input(f"❓ '{COLLECTION}' collection'ındaki tüm {count_before} kayıt silinecek. Devam edilsin mi? (evet/hayır): ")
        
        if response.lower() in ['evet', 'e', 'yes', 'y']:
            # Collection'ı temizle
            collection.delete_many({})
            count_after = collection.count_documents({})
            print(f"✅ Collection temizlendi! Kalan kayıt: {count_after}")
        else:
            print("❌ İşlem iptal edildi.")
    else:
        print(f"ℹ️  Collection zaten boş ({COLLECTION})")
    
    client.close()

