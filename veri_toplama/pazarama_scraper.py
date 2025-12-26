import sys
import json
import time
import re
import random
import io
from urllib.parse import urlparse, parse_qs, unquote

from pymongo import MongoClient
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from utils import initialize_driver, scrape_akakce_base_data

# ----------------- UTF-8 KORUMASI (Kritik Hata Çözümü) -----------------
# Windows terminalinde 'charmap' hatasını önlemek için boru hattını UTF-8'e zorlar.
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ----------------- YAPILANDIRMA -----------------
MONGO_DB_URL = "mongodb://localhost:27017/"
DB_NAME = "missha_price_data"
SITE_NAME = "pazarama"

# Pazarama XPATH'leri (Dinamik yapılar için güncellendi)
RATING_XPATH = '//*[@id="app"]/div[2]/div[1]/div[3]/div[2]/div[1]/div[2]/div/div/div[1]/span'
REVIEW_XPATH = '//*[@id="app"]/div[2]/div[1]/div[3]/div[2]/div[1]/div[2]/div/div/div[2]/a'

def scrape_pazarama_reviews(driver, max_reviews=20):
    """Asenkron yüklenen yorumları scroll ve element kontrolü ile çeker."""
    reviews_list = []
    try:
        wait = WebDriverWait(driver, 15)
        
        # 1. Sayfayı yavaşça aşağı kaydır (Lazy load tetiklensin)
        for i in range(1, 5):
            driver.execute_script(f"window.scrollTo(0, {i * 800});")
            time.sleep(1.5)
        
        # 2. Yorum container'ını daha esnek bir şekilde bul
        # Pazarama'da yorumlar genelde tab-header altındaki div'lerde bulunur
        try:
            parent_xpath = "//*[contains(@id, 'product__comment__tab-header') or contains(@class, 'comment')]"
            parent_element = wait.until(EC.presence_of_element_located((By.XPATH, parent_xpath)))
            
            # Yorum metinlerini içeren p veya div etiketlerini ara
            comment_elements = parent_element.find_elements(By.XPATH, ".//p | .//div[contains(@class, 'text-gray-600')]")
            
            for elem in comment_elements[:max_reviews]:
                txt = elem.text.strip()
                if len(txt) > 10: # Çok kısa (reklam vb.) metinleri ele
                    reviews_list.append({
                        "text": txt,
                        "rating": 5, # Rating genelde yıldız ikon sayısıdır, opsiyonel olarak eklenebilir
                        "date": None
                    })
        except:
            print("DEBUG: Yorumlar asenkron olarak yüklenemedi.")
            
    except Exception as e:
        print(f"DEBUG: Yorum çekme aşamasında hata: {e}")
    return reviews_list

def deep_scrape_pazarama(driver, paz_url):
    """Pazarama sayfasında 'Değerlendirmeler' sekmesine tıklar ve verileri alır."""
    data = {"rating": None, "reviews": None, "reviews_list": []}
    try:
        driver.get(paz_url)
        time.sleep(random.uniform(5, 7))
        wait = WebDriverWait(driver, 20)

        # 1. Sayısal verileri (Rating/Review count) çek
        try:
            review_el = wait.until(EC.presence_of_element_located((By.XPATH, REVIEW_XPATH)))
            num = re.sub(r"[^\d]", "", review_el.text)
            data["reviews"] = int(num) if num else 0
            
            rating_el = driver.find_element(By.XPATH, RATING_XPATH)
            data["rating"] = float(rating_el.text.replace(",", "."))
        except:
            pass

        # 2. KRİTİK: 'Yorumlar/Değerlendirmeler' sekmesine tıkla
        try:
            # Metin üzerinden butonu bul ve JavaScript ile tıkla (daha güvenlidir)
            tab_button = driver.find_element(By.XPATH, "//*[contains(text(), 'Değerlendirmeler')] | //*[contains(text(), 'Yorumlar')]")
            driver.execute_script("arguments[0].click();", tab_button)
            print("DEBUG: Yorumlar sekmesine tıklandı.")
            time.sleep(3)
        except:
            print("DEBUG: Yorum sekmesi bulunamadı, mevcut sayfadan devam ediliyor.")

        # 3. Yorum listesini çek
        data["reviews_list"] = scrape_pazarama_reviews(driver)

    except Exception as e:
        print(f"DEBUG: Pazarama derin tarama hatası: {e}")
    return data

def resolve_pazarama_url(akakce_link):
    """Akakçe linkini nihai Pazarama URL'sine çözer."""
    def _extract_f(link):
        parsed = urlparse(link)
        queries = parse_qs(parsed.query)
        frag = parse_qs(parsed.fragment.replace("#", ""))
        return (frag.get("f") or queries.get("f") or [None])[0]

    f_param = _extract_f(akakce_link)
    target = f"https://www.akakce.com/{unquote(f_param)}" if f_param else akakce_link
    
    driver = initialize_driver()
    try:
        driver.get(target)
        time.sleep(5)
        WebDriverWait(driver, 30).until(lambda d: "pazarama.com" in d.current_url)
        return driver, driver.current_url
    except:
        if driver: driver.quit()
        return None, None

def scrape_pazarama_product(product_config):
    """Ana pazar yeri kazıma mantığı."""
    client, DRIVER = None, None
    try:
        client = MongoClient(MONGO_DB_URL)
        db = client[DB_NAME]
        collection = db[product_config.get("collection", "e_ticaret_offers")]
        
        DRIVER = initialize_driver()
        product_name, base_data = scrape_akakce_base_data(DRIVER, product_config["url"])
        DRIVER.quit()
        DRIVER = None

        for item in base_data:
            if "pazarama" not in item["vendor_name"].lower():
                continue

            paz_driver, final_url = resolve_pazarama_url(item["link"])
            if paz_driver:
                details = deep_scrape_pazarama(paz_driver, final_url)
                
                doc = {
                    "product_id": product_config["product_id"],
                    "product_name": product_name,
                    "site": SITE_NAME,
                    "vendor_name": item["vendor_name"],
                    "seller_nickname": item.get("seller_nickname") or item["vendor_name"],
                    "price": item["price"],
                    "rating": details["rating"],
                    "review_count": details["reviews"],
                    "reviews_list": details["reviews_list"],
                    "scrape_ts": time.strftime("%Y-%m-%dT%H:%M:%S")
                }
                
                # MongoDB'ye güvenli yazım (Mükerrer kaydı önler)
                collection.update_one(
                    {"product_id": doc["product_id"], "vendor_name": doc["vendor_name"]},
                    {"$set": doc},
                    upsert=True
                )
                paz_driver.quit()
                return f"✅ PAZARAMA: {product_name} verisi ve {len(details['reviews_list'])} yorum başarıyla çekildi."
        
        return "⚠️ PAZARAMA: Satıcı bulunamadı."

    except Exception as e:
        return f"❌ PAZARAMA HATA: {str(e)}"
    finally:
        if DRIVER: DRIVER.quit()
        if client: client.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            config = json.loads(sys.argv[1])
            res = scrape_pazarama_product(config)
            print(f"\n{'='*50}\n{res}\n{'='*50}", flush=True)
        except Exception as e:
            print(f"❌ KRİTİK HATA: {str(e)}")