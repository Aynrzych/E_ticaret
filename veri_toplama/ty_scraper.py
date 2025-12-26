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

# ----------------- UTF-8 KORUMASI (Charmap Hatası Çözümü) -----------------
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ----------------- YAPILANDIRMA -----------------
MONGO_DB_URL = "mongodb://localhost:27017/"
DB_NAME = "missha_price_data"
SITE_NAME = "trendyol"

# TRENDYOL XPATH'LERİ
RATING_XPATH = '//*[@id="envoy-mobile"]/div/div[2]/div/a/div[1]/span'
REVIEW_XPATH = '//*[@id="envoy-mobile"]/div/div[2]/div/a/div[2]'

def scrape_trendyol_reviews(driver, max_reviews=20):
    reviews_list = []
    try:
        wait = WebDriverWait(driver, 20)
        # Trendyol yorum container'ı
        parent_xpath = '//*[@id="review-detail"]/div/div[3]'
        
        # Sayfayı kaydır (Lazy load tetiklensin)
        for i in range(1, 5):
            driver.execute_script(f"window.scrollTo(0, {i * 700});")
            time.sleep(1)

        try:
            parent_element = wait.until(EC.presence_of_element_located((By.XPATH, parent_xpath)))
            all_divs = parent_element.find_elements(By.XPATH, "./div")
            
            for div in all_divs[:max_reviews]:
                try:
                    review_data = {}
                    # Metin çekme
                    text_elem = div.find_element(By.XPATH, ".//div[1]/div[2]/div/span")
                    review_data["text"] = text_elem.text.strip()
                    
                    # Puan çekme (Yıldız ikonlarını say)
                    stars = div.find_elements(By.XPATH, ".//div[contains(@class, 'full')]")
                    review_data["rating"] = len(stars) if stars else 5
                    
                    if len(review_data["text"]) > 10:
                        reviews_list.append(review_data)
                except:
                    continue
        except:
            print("DEBUG: Trendyol yorumları bulunamadı.")
            
    except Exception as e:
        print(f"DEBUG: TY yorum çekme hatası: {e}")
    return reviews_list

def deep_scrape_trendyol(driver, ty_url):
    data = {"rating": None, "reviews": None, "reviews_list": []}
    try:
        driver.get(ty_url)
        time.sleep(random.uniform(5, 7))
        wait = WebDriverWait(driver, 15)

        # Yorum sayısı
        try:
            review_el = wait.until(EC.presence_of_element_located((By.XPATH, REVIEW_XPATH)))
            num = re.sub(r"[^\d]", "", review_el.text)
            data["reviews"] = int(num) if num else 0
        except: pass

        # Rating
        try:
            rating_el = driver.find_element(By.XPATH, RATING_XPATH)
            data["rating"] = float(rating_el.text.replace(",", "."))
        except: pass

        # Yorum sayfasını bul ve git
        if data["reviews"] and data["reviews"] > 0:
            review_url = ty_url + "/yorumlar" if "/yorumlar" not in ty_url else ty_url
            driver.get(review_url)
            time.sleep(3)
            data["reviews_list"] = scrape_trendyol_reviews(driver)

    except Exception as e:
        print(f"DEBUG: TY derin tarama hatası: {e}")
    return data

def resolve_trendyol_url(akakce_link):
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
        # Trendyol'a geçene kadar bekle
        WebDriverWait(driver, 30).until(lambda d: "trendyol.com" in d.current_url)
        return driver, driver.current_url
    except:
        if driver: driver.quit()
        return None, None

def scrape_trendyol_product(product_config):
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
            if "trendyol" not in item["vendor_name"].lower():
                continue

            ty_driver, final_url = resolve_trendyol_url(item["link"])
            if ty_driver:
                details = deep_scrape_trendyol(ty_driver, final_url)
                
                doc = {
                    "product_id": product_config["product_id"],
                    "product_name": product_name,
                    "site": SITE_NAME,
                    "vendor_name": item["vendor_name"],
                    "seller_nickname": item.get("seller_nickname") or None,
                    "price": item["price"],
                    "rating": details["rating"],
                    "review_count": details["reviews"],
                    "reviews_list": details["reviews_list"],
                    "scrape_ts": time.strftime("%Y-%m-%dT%H:%M:%S")
                }
                
                # MongoDB'ye kaydet (Aynı ürün+satıcı varsa güncelle)
                collection.update_one(
                    {"product_id": doc["product_id"], "vendor_name": doc["vendor_name"]},
                    {"$set": doc},
                    upsert=True
                )
                ty_driver.quit()
                return f"✅ TY SCRAPER: {product_name} başarıyla güncellendi."
        
        return "⚠️ TY SCRAPER: Trendyol satıcısı bulunamadı."

    except Exception as e:
        return f"❌ TY SCRAPER HATA: {str(e)}"
    finally:
        if DRIVER: DRIVER.quit()
        if client: client.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            config = json.loads(sys.argv[1])
            res = scrape_trendyol_product(config)
            print(f"\n{'='*50}\n{res}\n{'='*50}", flush=True)
        except Exception as e:
            print(f"❌ TY SCRAPER KRİTİK HATA: {str(e)}")