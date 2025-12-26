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
# Windows konsolunda 'charmap' hatasını engellemek için çıktı kanalını UTF-8 yapar.
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ----------------- YAPILANDIRMA -----------------
MONGO_DB_URL = "mongodb://localhost:27017/"
DB_NAME = "missha_price_data"
SITE_NAME = "pttavm"

# PTTAVM XPATH'LERİ
RATING_XPATH = '//*[@id="tc-tab-comments"]/div[2]/div/div/div[1]/div[1]/div[2]'
REVIEW_XPATH = '//*[@id="tc-tab-comments"]/div[2]/div/div/div[1]/div[2]'

def scrape_ptt_reviews(driver, max_reviews=20):
    reviews_list = []
    try:
        wait = WebDriverWait(driver, 20)
        review_container_xpath = '//*[@id="tc-tab-comments"]/div[2]/div/div/div[2]/div/div/div/div[1]'
        
        # Sayfayı aşağı kaydır (Lazy load tetiklensin)
        driver.execute_script("window.scrollTo(0, 1000);")
        time.sleep(2)

        review_containers = driver.find_elements(By.XPATH, review_container_xpath)
        
        for i, container in enumerate(review_containers[:max_reviews]):
            try:
                review_data = {}
                # Yorum metni
                text_elem = container.find_element(By.XPATH, ".//div/div/div[2]/div")
                review_data["text"] = text_elem.text.strip()
                
                # Puan (Rating)
                rating_container = container.find_element(By.XPATH, ".//div/div/div[1]/div[1]/div[2]")
                rating_match = re.search(r'(\d+)', rating_container.text)
                review_data["rating"] = int(rating_match.group(1)) if rating_match else 5
                
                if review_data["text"] and len(review_data["text"]) > 5:
                    reviews_list.append(review_data)
            except:
                continue
    except Exception as e:
        print(f"DEBUG: PTT yorum çekme hatası: {e}")
    return reviews_list

def deep_scrape_ptt(driver, ptt_url):
    data = {"rating": None, "reviews": None, "reviews_list": []}
    try:
        driver.get(ptt_url)
        time.sleep(random.uniform(5, 7))
        wait = WebDriverWait(driver, 20)

        # Yorum sayısı
        try:
            review_el = wait.until(EC.presence_of_element_located((By.XPATH, REVIEW_XPATH)))
            num = re.sub(r"[^\d]", "", review_el.text)
            data["reviews"] = int(num) if num else 0
        except: pass

        # Genel Puan
        try:
            rating_el = driver.find_element(By.XPATH, RATING_XPATH)
            data["rating"] = float(rating_el.text.replace(",", "."))
        except: pass

        # Yorumları Çek
        data["reviews_list"] = scrape_ptt_reviews(driver)
            
    except Exception as e:
        print(f"DEBUG: PTT derin tarama hatası: {e}")
    return data

def resolve_ptt_url(akakce_link):
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
        time.sleep(4)
        WebDriverWait(driver, 25).until(lambda d: "pttavm.com" in d.current_url)
        return driver, driver.current_url
    except:
        if driver: driver.quit()
        return None, None

def scrape_ptt_product(product_config):
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
            v_name = item["vendor_name"].lower()
            if "ptt" not in v_name and "pttavm" not in v_name:
                continue

            ptt_driver, final_url = resolve_ptt_url(item["link"])
            if ptt_driver:
                details = deep_scrape_ptt(ptt_driver, final_url)
                
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
                ptt_driver.quit()
                return f"✅ PTT SCRAPER: {product_name} verisi kaydedildi."
        
        return "⚠️ PTT SCRAPER: PttAVM satıcısı bulunamadı."

    except Exception as e:
        return f"❌ PTT SCRAPER HATA: {str(e)}"
    finally:
        if DRIVER: DRIVER.quit()
        if client: client.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            config = json.loads(sys.argv[1])
            res = scrape_ptt_product(config)
            print(f"\n{'='*50}\n{res}\n{'='*50}", flush=True)
        except Exception as e:
            print(f"❌ PTT SCRAPER KRİTİK HATA: {str(e)}")