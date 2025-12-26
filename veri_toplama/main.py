# veri_toplama/main.py

import json
from multiprocessing import Pool
import subprocess
import os
import sys
import time
import io
import shutil
from utils import initialize_driver, scrape_akakce_base_data
from pymongo import MongoClient

# ----------------- UTF-8 KORUMASI (Charmap Hatası Çözümü) -----------------
# Windows terminalinde Unicode karakterleri nedeniyle oluşan çökmeleri engeller.
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ----------------- YAPILANDIRMA -----------------

MONGO_DB_URL = "mongodb://localhost:27017/"
DB_NAME = "missha_price_data"

# Tüm desteklenen sitelerin listesi
ALL_SITES = ["hepsiburada", "trendyol", "n11", "pttavm", "pazarama"]

# ----------------- YARDIMCI FONKSİYONLAR -----------------

def load_existing_product_ids():
    """Mevcut targets.json'dan product_id'leri yükler."""
    try:
        with open("targets.json", "r", encoding="utf-8") as f:
            existing = json.load(f)
            return {item["product_id"] for item in existing if "product_id" in item}
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def get_mongodb_product_ids(collection_name="e_ticaret_offers"):
    """MongoDB'deki mevcut product_id'leri yükler."""
    try:
        client = MongoClient(MONGO_DB_URL, serverSelectionTimeoutMS=5000)
        db = client[DB_NAME]
        collection = db[collection_name]
        existing_ids = collection.distinct("product_id")
        client.close()
        return set(existing_ids)
    except Exception as e:
        print(f"WARNING MongoDB bağlantı hatası: {e}")
        return set()

def add_new_products_to_mongodb():
    """targets.json'daki yeni ürünleri MongoDB'ye ekler (Senkronizasyon)."""
    try:
        with open("targets.json", "r", encoding="utf-8") as f:
            target_products = json.load(f)
    except Exception as e:
        print(f"HATA: targets.json okunamadı: {e}")
        return False
    
    mongodb_ids = get_mongodb_product_ids()
    new_products = [p for p in target_products if p.get("product_id") not in mongodb_ids]
    
    if not new_products:
        print("Tüm ürünler zaten MongoDB'de mevcut.")
        return True
    
    try:
        client = MongoClient(MONGO_DB_URL)
        db = client[DB_NAME]
        added_count = 0
        for product in new_products:
            collection_name = product.get("collection", "e_ticaret_offers")
            collection = db[collection_name]
            if not collection.find_one({"product_id": product["product_id"]}):
                product["added_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                collection.insert_one(product)
                added_count += 1
        client.close()
        print(f"Toplam {added_count} yeni ürün MongoDB'ye eklendi.")
        return True
    except Exception as e:
        print(f"HATA MongoDB senkronizasyon hatası: {e}")
        return False

def add_single_product(product_id, product_name, category, url):
    """Tek bir ürünü targets.json'a güvenli şekilde ekler."""
    existing_ids = load_existing_product_ids()
    if product_id in existing_ids:
        print(f"⚠️ '{product_id}' zaten mevcut.")
        return False
    
    try:
        with open("targets.json", "r", encoding="utf-8") as f:
            products = json.load(f)
    except: products = []

    products.append({
        "product_id": product_id, "product_name": product_name,
        "category": category, "url": url, "collection": "e_ticaret_offers"
    })
    
    with open("targets.json", "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)
    return True

def expand_product_tasks(product_config):
    """Bir ürünü tüm pazar yerleri için ayrı görevlere (task) böler."""
    tasks = []
    for site in ALL_SITES:
        task = product_config.copy()
        task['target_site'] = site
        tasks.append(task)
    return tasks

def run_scraper_script(product_config):
    """Scraper scriptlerini subprocess ile asenkron ve UTF-8 güvenli çalıştırır."""
    site_name = product_config.get('target_site', 'unknown')
    script_map = {
        "hepsiburada": "hb_scraper.py", "trendyol": "ty_scraper.py", 
        "n11": "n11_scraper.py", "pttavm": "ptt_scraper.py", "pazarama": "pazarama_scraper.py"
    }
    
    script_file = script_map.get(site_name)
    if not script_file: return f"SKIP: {site_name} için script yok."
    
    try:
        json_arg = json.dumps(product_config)
        print(f"STARTING: {product_config['product_name']} -> {site_name}")
        
        # Subprocess UTF-8 yönetimi burada gerçekleşir
        result = subprocess.run(
            [sys.executable, script_file, json_arg],
            capture_output=True, text=True, 
            encoding="utf-8", errors="replace", check=True 
        )
        return result.stdout.strip()
    except Exception as e:
        return f"ERROR ({site_name}): {str(e)}"

def get_products_with_scraped_data():
    """MongoDB'de veri çekilmiş (scrape_ts veya price olan) product_id'leri döndürür."""
    try:
        client = MongoClient(MONGO_DB_URL, serverSelectionTimeoutMS=5000)
        db = client[DB_NAME]
        collection = db["e_ticaret_offers"]
        
        # Veri çekilmiş ürünleri bul (scrape_ts veya price alanı olanlar)
        scraped_products = collection.distinct("product_id", {
            "$or": [
                {"scrape_ts": {"$exists": True}},
                {"price": {"$exists": True, "$ne": None}}
            ]
        })
        client.close()
        return set(scraped_products)
    except Exception as e:
        print(f"WARNING MongoDB kontrol hatası: {e}")
        return set()

# ----------------- ANA ÇALIŞTIRMA -----------------

def main_scraper_runner():
    try:
        with open('targets.json', 'r', encoding='utf-8') as f:
            product_list = json.load(f)
    except:
        print("HATA: targets.json bulunamadı veya bozuk."); return

    all_tasks = []
    for product in product_list:
        all_tasks.extend(expand_product_tasks(product))
    
    num_processes = min(len(all_tasks), 10) # Maksimum 10 paralel işlem
    print(f"Başlatılıyor: {len(product_list)} ürün | {len(all_tasks)} görev | {num_processes} slot")

    with Pool(processes=num_processes) as pool:
        results = pool.map(run_scraper_script, all_tasks)

    print("\n" + "="*20 + " SONUÇLAR " + "="*20)
    for res in results: print(res)

def main_scraper_runner_new_only():
    """Sadece yeni eklenen (henüz veri çekilmemiş) ürünler için scraper çalıştırır."""
    try:
        with open('targets.json', 'r', encoding='utf-8') as f:
            all_products = json.load(f)
    except:
        print("HATA: targets.json bulunamadı veya bozuk.")
        return
    
    # MongoDB'de veri çekilmiş ürünleri bul
    scraped_product_ids = get_products_with_scraped_data()
    print(f"MongoDB'de {len(scraped_product_ids)} urun icin veri cekilmis.")
    
    # Yeni ürünleri bul (henüz veri çekilmemiş olanlar)
    new_products = [p for p in all_products if p.get("product_id") not in scraped_product_ids]
    
    if not new_products:
        print("Yeni urun bulunamadi. Tum urunler icin veri cekilmis.")
        return
    
    print(f"{len(new_products)} yeni urun icin scraper calistiriliyor...")
    for p in new_products:
        print(f"  - {p.get('product_name', p.get('product_id'))}")
    
    # Sadece yeni ürünler için task oluştur
    all_tasks = []
    for product in new_products:
        all_tasks.extend(expand_product_tasks(product))
    
    num_processes = min(len(all_tasks), 10)
    print(f"\nBaslatiliyor: {len(new_products)} yeni urun | {len(all_tasks)} gorev | {num_processes} slot")
    
    with Pool(processes=num_processes) as pool:
        results = pool.map(run_scraper_script, all_tasks)
    
    print("\n" + "="*20 + " SONUCLAR " + "="*20)
    for res in results:
        print(res)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "sync":
            add_new_products_to_mongodb()
        elif cmd == "new-only" or cmd == "new":
            # Sadece yeni eklenen ürünler için scraper çalıştır
            add_new_products_to_mongodb()
            main_scraper_runner_new_only()
        elif cmd == "add" and len(sys.argv) >= 6:
            if add_single_product(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]):
                add_new_products_to_mongodb()
        else:
            # Belirli bir ID'yi çalıştırma modu
            target_id = sys.argv[1]
            try:
                with open('targets.json', 'r', encoding='utf-8') as f:
                    all_p = json.load(f)
                filtered = [p for p in all_p if p.get('product_id') == target_id]
                if filtered:
                    shutil.copy('targets.json', 'targets.json.bak')
                    with open('targets.json', 'w', encoding='utf-8') as f:
                        json.dump(filtered, f, ensure_ascii=False, indent=2)
                    main_scraper_runner()
                    shutil.move('targets.json.bak', 'targets.json')
            except Exception as e: print(f"Hata: {e}")
    else:
        add_new_products_to_mongodb()
        main_scraper_runner()