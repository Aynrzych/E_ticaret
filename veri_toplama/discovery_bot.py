import json
import time
import random
from utils import initialize_driver
from selenium.webdriver.common.by import By

CATEGORIES = [
    {"name": "Gunes Kremi", "url": "https://www.akakce.com/gunes-kremi.html"},
    {"name": "Kahve Makinesi", "url": "https://www.akakce.com/turk-kahve-makinesi.html"},
    {"name": "Deterjan", "url": "https://www.akakce.com/toz-deterjan.html"}
]

def run_discovery(products_per_category=34):
    """
    Belirli kategorilerden ürün çeker ve targets.json'a yazar.
    
    Args:
        products_per_category: Her kategoriden kaç ürün çekilecek (varsayılan: 34)
                              Toplam ~100 ürün için 3 kategori × 34 = 102 ürün
                              Daha az yük için 10-15 önerilir
    """
    # HEADLESS = True olursa bilgisayarın hiç yorulmaz (utils.py'den ayarla)
    driver = initialize_driver() 
    new_targets = []
    
    try:
        for cat in CATEGORIES:
            print(f"🔎 {cat['name']} taranıyor...")
            driver.get(cat["url"])
            
            # Sayfanın yüklenmesi için tek seferlik bekleme
            time.sleep(random.uniform(5, 7))
            
            # Sayfayı bir kez aşağı kaydır ki tüm ürünler yüklensin
            driver.execute_script("window.scrollTo(0, 1000);")
            time.sleep(2)

            # Ürünleri topla
            items = driver.find_elements(By.XPATH, "//li[@class='pd_v8']")
            print(f"📦 Bu sayfada {len(items)} ürün bulundu.")
            
            # İstenen sayıda ürün al (mevcut ürün sayısını aşmamak için)
            products_to_take = min(products_per_category, len(items))
            print(f"   📌 İlk {products_to_take} ürün alınıyor...")

            for item in items[:products_to_take]:
                try:
                    name_el = item.find_element(By.TAG_NAME, "h3")
                    link_el = item.find_element(By.TAG_NAME, "a")
                    url = link_el.get_attribute("href")
                    name = name_el.text.strip()
                    
                    if name and url:
                        p_id = name.lower().replace(" ", "_")[:25].strip("_")
                        new_targets.append({
                            "product_id": p_id,
                            "product_name": name,
                            "category": cat["name"],
                            "url": url,
                            "collection": "e_ticaret_offers"
                        })
                except: continue
            
            # Kategoriler arası kısa mola
            time.sleep(random.uniform(3, 5))

        # Dosyayı tek seferde kaydet
        if new_targets:
            with open("targets.json", "w", encoding="utf-8") as f:
                json.dump(new_targets, f, ensure_ascii=False, indent=2)
            print(f"✅ BİTTİ! Toplam {len(new_targets)} ürün targets.json'a yazıldı.")

    finally:
        driver.quit() # Tarayıcıyı iş bitince bir kez kapatıyoruz

if __name__ == "__main__":
    # 100 ürün için her kategoriden 34 ürün al (toplam ~102 ürün)
    # Batch processing sayesinde bilgisayara yük binmeyecek
    run_discovery(products_per_category=34)