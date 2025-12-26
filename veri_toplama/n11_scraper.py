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
SITE_NAME = "n11"

# N11 XPATH'LERİ (Güncel yapıyla uyumlu)
RATING_XPATH = '//strong[@class="ratingScore"]'
REVIEW_XPATH = '//*[@id="readReviews"]/span'

def scrape_n11_reviews(driver, max_reviews=20):
    reviews_list = []
    try:
        wait = WebDriverWait(driver, 20)
        # N11'de yorumlar genelde #app içindeki dinamik div'lerde bulunur
        parent_xpath = '//*[@id="app"]/div/div[3]/div[2]'
        
        # Sayfayı kaydırarak yorumların yüklenmesini sağla
        for i in range(1, 4):
            driver.execute_script(f"window.scrollTo(0, {i * 800});")
            time.sleep(1)

        try:
            parent_element = wait.until(EC.presence_of_element_located((By.XPATH, parent_xpath)))
            all_divs = parent_element.find_elements(By.XPATH, "./div")
            
            for div in all_divs[:max_reviews]:
                try:
                    review_data = {}
                    # Metin çekme (N11 spesifik span)
                    text_elem = div.find_element(By.XPATH, ".//div[2]/div[2]/span")
                    review_data["text"] = text_elem.text.strip()
                    
                    # Puan çekme (Dolu yıldızları say)
                    stars = div.find_elements(By.XPATH, ".//span[contains(@class, 'active')]")
                    review_data["rating"] = len(stars) if stars else 5
                    
                    if len(review_data["text"]) > 5:
                        reviews_list.append(review_data)
                except:
                    continue
        except:
            print("DEBUG: N11 yorum containerları bulunamadı.")
            
    except Exception as e:
        print(f"DEBUG: N11 yorum çekme hatası: {e}")
    return reviews_list

def deep_scrape_n11(driver, n11_url):
    data = {"rating": None, "reviews": None, "reviews_list": []}
    try:
        driver.get(n11_url)
        time.sleep(random.uniform(4, 6))
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

        # Yorumlar
        if data["reviews"] and data["reviews"] > 0:
            data["reviews_list"] = scrape_n11_reviews(driver)

    except Exception as e:
        print(f"DEBUG: N11 derin tarama hatası: {e}")
    return data

def resolve_n11_url(akakce_link):
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
        WebDriverWait(driver, 25).until(lambda d: "n11.com" in d.current_url)
        return driver, driver.current_url
    except:
        if driver: driver.quit()
        return None, None

def scrape_n11_product(product_config):
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
            if "n11" not in item["vendor_name"].lower():
                continue

            n11_driver, final_url = resolve_n11_url(item["link"])
            if n11_driver:
                details = deep_scrape_n11(n11_driver, final_url)
                
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
                
                collection.update_one(
                    {"product_id": doc["product_id"], "vendor_name": doc["vendor_name"]},
                    {"$set": doc},
                    upsert=True
                )
                n11_driver.quit()
                return f"✅ N11 SCRAPER: {product_name} verisi kaydedildi."
        
        return "⚠️ N11 SCRAPER: Satıcı bulunamadı."

    except Exception as e:
        return f"❌ N11 SCRAPER HATA: {str(e)}"
    finally:
        if DRIVER: DRIVER.quit()
        if client: client.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            config = json.loads(sys.argv[1])
            res = scrape_n11_product(config)
            print(f"\n{'='*50}\n{res}\n{'='*50}", flush=True)
        except Exception as e:
            print(f"❌ N11 SCRAPER KRİTİK HATA: {str(e)}")