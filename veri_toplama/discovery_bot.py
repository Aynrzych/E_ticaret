import json
import time
import random
from utils import initialize_driver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

CATEGORIES = [
    {"name": "Gunes Kremi", "url": "https://www.akakce.com/gunes-kremi.html"},
    {"name": "Kahve Makinesi", "url": "https://www.akakce.com/turk-kahve-makinesi.html"},
    {"name": "Deterjan", "url": "https://www.akakce.com/toz-deterjan.html"}
]

def load_existing_product_ids():
    """Mevcut targets.json'dan product_id'leri yükler."""
    try:
        with open("targets.json", "r", encoding="utf-8") as f:
            existing = json.load(f)
            return {item["product_id"] for item in existing if "product_id" in item}
    except FileNotFoundError:
        return set()
    except json.JSONDecodeError:
        return set()

def add_single_product(product_id, product_name, category, url):
    """
    Tek bir ürünü targets.json'a ekler (sadece product_id yoksa).
    
    Returns:
        bool - True if added, False if already exists
    """
    existing_ids = load_existing_product_ids()
    
    if product_id in existing_ids:
        print(f"⚠️  '{product_id}' zaten mevcut, eklenmedi.")
        return False
    
    # Mevcut ürünleri yükle
    try:
        with open("targets.json", "r", encoding="utf-8") as f:
            existing_products = json.load(f)
    except FileNotFoundError:
        existing_products = []
    except json.JSONDecodeError:
        existing_products = []
    
    # Yeni ürünü ekle
    new_product = {
        "product_id": product_id,
        "product_name": product_name,
        "category": category,
        "url": url,
        "collection": "e_ticaret_offers"
    }
    existing_products.append(new_product)
    
    # Dosyaya kaydet
    with open("targets.json", "w", encoding="utf-8") as f:
        json.dump(existing_products, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Yeni ürün eklendi: {product_name} ({product_id})")
    return True

def run_discovery(products_per_category=34):
    """
    Belirli kategorilerden ürün çeker ve targets.json'a yazar.
    Sadece yeni product_id'leri ekler, mevcut olanları korur.
    
    Args:
        products_per_category: Her kategoriden kaç ürün çekilecek (varsayılan: 34)
                              Toplam ~100 ürün için 3 kategori × 34 = 102 ürün
                              Daha az yük için 10-15 önerilir
    """
    # Mevcut product_id'leri yükle
    existing_ids = load_existing_product_ids()
    print(f"📋 Mevcut {len(existing_ids)} ürün bulundu. Sadece yeni ürünler eklenecek.")
    
    # HEADLESS = True olursa bilgisayarın hiç yorulmaz (utils.py'den ayarla)
    driver = initialize_driver() 
    new_targets = []
    skipped_count = 0
    
    try:
        for cat in CATEGORIES:
            print(f"🔎 {cat['name']} taranıyor...")
            driver.get(cat["url"])
            
            # Sayfanın yüklenmesi için bekleme - WebDriverWait ile
            wait = WebDriverWait(driver, 20)
            try:
                # Sayfa yüklenene kadar bekle
                wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            except:
                pass
            
            time.sleep(random.uniform(3, 5))
            
            # Sayfayı kademeli olarak kaydır (lazy loading için)
            print("   📜 Sayfa kaydırılıyor...")
            last_height = driver.execute_script("return document.body.scrollHeight")
            scroll_attempts = 0
            max_scrolls = 5
            
            while scroll_attempts < max_scrolls:
                # Kademeli scroll
                for scroll_pos in [500, 1000, 1500, 2000]:
                    driver.execute_script(f"window.scrollTo(0, {scroll_pos});")
                    time.sleep(0.5)
                
                # En alta scroll
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                
                # Yeni içerik yüklendi mi kontrol et
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height
                scroll_attempts += 1
            
            # Ürünlerin yüklenmesi için ek bekleme
            time.sleep(2)

            # Ürünleri topla
            items = driver.find_elements(By.XPATH, "//li[@class='pd_v8']")
            print(f"📦 Bu sayfada {len(items)} ürün bulundu.")
            
            if len(items) == 0:
                print(f"⚠️  Ürün bulunamadı. Sayfa yapısını kontrol ediliyor...")
                # Alternatif: Tüm li elementlerini say
                all_li = driver.find_elements(By.TAG_NAME, "li")
                print(f"   🔍 Sayfada toplam {len(all_li)} <li> elementi var.")
                continue
            
            # İstenen sayıda ürün al (mevcut ürün sayısını aşmamak için)
            products_to_take = min(products_per_category, len(items))
            print(f"   📌 İlk {products_to_take} ürün kontrol ediliyor...")

            for item in items[:products_to_take]:
                try:
                    name_el = item.find_element(By.TAG_NAME, "h3")
                    link_el = item.find_element(By.TAG_NAME, "a")
                    url = link_el.get_attribute("href")
                    name = name_el.text.strip()
                    
                    if name and url:
                        p_id = name.lower().replace(" ", "_")[:25].strip("_")
                        
                        # Eğer product_id zaten varsa atla
                        if p_id in existing_ids:
                            skipped_count += 1
                            continue
                        
                        new_targets.append({
                            "product_id": p_id,
                            "product_name": name,
                            "category": cat["name"],
                            "url": url,
                            "collection": "e_ticaret_offers"
                        })
                        existing_ids.add(p_id)  # Set'e ekle ki tekrar kontrol edilmesin
                except Exception as e:
                    print(f"   ⚠️  Ürün işlenirken hata: {e}")
                    continue
            
            # Kategoriler arası kısa mola
            time.sleep(random.uniform(3, 5))

        # Mevcut ürünleri yükle ve yeni ürünleri ekle
        if new_targets:
            try:
                with open("targets.json", "r", encoding="utf-8") as f:
                    existing_products = json.load(f)
            except FileNotFoundError:
                existing_products = []
            except json.JSONDecodeError:
                existing_products = []
            
            # Mevcut ürünlerle birleştir
            all_products = existing_products + new_targets
            
            # Dosyaya kaydet
            with open("targets.json", "w", encoding="utf-8") as f:
                json.dump(all_products, f, ensure_ascii=False, indent=2)
            
            print(f"✅ BİTTİ! {len(new_targets)} yeni ürün eklendi, {skipped_count} ürün atlandı (zaten mevcut).")
            print(f"📊 Toplam ürün sayısı: {len(all_products)}")
        else:
            print(f"⚠️  Yeni ürün bulunamadı. Tüm ürünler zaten mevcut olabilir.")

    finally:
        driver.quit() # Tarayıcıyı iş bitince bir kez kapatıyoruz

if __name__ == "__main__":
    # 100 ürün için her kategoriden 34 ürün al (toplam ~102 ürün)
    # Batch processing sayesinde bilgisayara yük binmeyecek
    run_discovery(products_per_category=34)
