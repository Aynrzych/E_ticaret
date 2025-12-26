# veri_toplama/hb_scraper.py

import sys
import json
import time
import re
import io
import random
from urllib.parse import urlparse, parse_qs, unquote
from pymongo import MongoClient
from selenium.webdriver.common.by import By 
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# UTILS dosyasından ortak fonksiyonları içeri aktar
from utils import initialize_driver, scrape_akakce_base_data 

# ----------------- UTF-8 KORUMASI (Kritik Hata Çözümü) -----------------
# Windows konsolunda Türkçe karakterler ve özel semboller (₺, stars vb.) 
# yüzünden alınan 'charmap' hatasını engellemek için stdout'u UTF-8'e zorlar.
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ----------------- YAPILANDIRMA -----------------
MONGO_DB_URL = "mongodb://localhost:27017/"
DB_NAME = "missha_price_data"
SITE_NAME = "hepsiburada"

# Sizin belirlediğiniz KARARLI ve GÜNCEL olduğu varsayılan XPath'ler
RATING_XPATH = '//*[@id="container"]/main/div/div[2]/section[1]/div[2]/div[1]/div[2]/div/div/span'
REVIEW_XPATH = '//*[@id="container"]/main/div/div[2]/section[1]/div[2]/div[1]/div[2]/div/a'

# ----------------- HEPSIBURADA ÖZEL FONKSİYONLAR -----------------

def scrape_hepsiburada_reviews(driver, max_reviews=20):
    reviews_list = []
    if max_reviews > 100:
        max_reviews = 100
    
    try:
        wait = WebDriverWait(driver, 20)
        try:
            wait.until(EC.presence_of_element_located((By.XPATH, "//div[@id='hermes-voltran-comments']")))
            print("DEBUG: hermes-voltran-comments container bulundu")
        except Exception as e:
            print(f"DEBUG HATA: hermes-voltran-comments container bulunamadı! Hata: {e}")
            return reviews_list

        # Sayfa Kaydırma Mantığı
        scroll_positions = [300, 600, 900, 1200, 1500]
        for scroll_pos in scroll_positions:
            driver.execute_script(f"window.scrollTo(0, {scroll_pos});")
            time.sleep(1.5)
            current_count = len(driver.find_elements(By.XPATH, "//div[@id='hermes-voltran-comments']/div/div[3]"))
            if current_count >= max_reviews:
                break
        
        # Container'ları İşleme (Senin mantığın: div[X]/div[3])
        all_main_divs = driver.find_elements(By.XPATH, "//div[@id='hermes-voltran-comments']/div")
        review_containers = []
        for main_div in all_main_divs:
            try:
                div3 = main_div.find_element(By.XPATH, "./div[3]")
                review_containers.append(div3)
            except: pass

        for i, container in enumerate(review_containers[:max_reviews]):
            try:
                review_data = {}
                # Metin çekme - div[2]/div[2]/div[2] yapısı
                try:
                    text_container = container.find_element(By.XPATH, ".//div[2]/div[2]/div[2]")
                    review_data["text"] = text_container.text.strip()
                except:
                    review_data["text"] = None

                # Puan çekme - Detaylı Yıldız Sayma Mantığın
                try:
                    rating = None
                    stars_container = container.find_element(By.XPATH, ".//div[2]/div[2]/div[1]/div[2]/div/span/div")
                    stars = stars_container.find_elements(By.XPATH, ".//div")
                    active_count = 0
                    for star in stars:
                        class_attr = star.get_attribute("class") or ""
                        if any(keyword in class_attr.lower() for keyword in ["fill", "active", "selected", "full"]):
                            active_count += 1
                    rating = active_count if 0 < active_count <= 5 else 5
                    review_data["rating"] = rating
                except:
                    review_data["rating"] = None
                
                if review_data.get("text") and len(review_data["text"]) > 10:
                    reviews_list.append(review_data)
            except: continue
            
    except Exception as e:
        print(f"DEBUG HATA: Yorumlar çekilirken hata: {e}")
    
    return reviews_list

def deep_scrape_hepsiburada(driver, hb_url):
    data = {"rating": None, "reviews": None, "reviews_list": [], "high_rating_count": None, "low_rating_count": None}
    try:
        driver.get(hb_url)
        time.sleep(random.uniform(5, 8))
        wait = WebDriverWait(driver, 30)

        # Yorum Sayısı ve Genel Puan
        review_element = wait.until(EC.presence_of_element_located((By.XPATH, REVIEW_XPATH)))
        data["reviews"] = int(re.sub(r"[^\d]", "", review_element.text))
        rating_element = wait.until(EC.presence_of_element_located((By.XPATH, RATING_XPATH)))
        data["rating"] = float(rating_element.text.replace(",", "."))

        # Yorumlar Sayfasına Git
        review_href = review_element.get_attribute("href")
        if review_href:
            driver.get(review_href)
            time.sleep(5)
            data["reviews_list"] = scrape_hepsiburada_reviews(driver, max_reviews=20)

    except Exception as e:
        print(f"DEBUG KRİTİK HATA: HB çekimi sırasında hata: {e}")
    return data

def resolve_hepsiburada_url(akakce_link):
    def _build_redirect_url(link: str) -> str:
        parsed = urlparse(link)
        queries = parse_qs(parsed.query)
        frag_queries = parse_qs(parsed.fragment.replace("#", ""))
        f_param = (frag_queries.get("f") or queries.get("f") or [None])[0]
        if f_param:
            decoded = unquote(f_param)
            return f"https://www.akakce.com{decoded}" if decoded.startswith("/") else f"https://www.akakce.com/{decoded}"
        return link

    akakce_resolved = _build_redirect_url(akakce_link)
    driver = initialize_driver()
    try:
        driver.get(akakce_resolved)
        WebDriverWait(driver, 15).until(lambda d: len(d.window_handles) >= 1)
        if len(driver.window_handles) > 1:
            driver.switch_to.window(driver.window_handles[-1])
        WebDriverWait(driver, 40).until(lambda d: "hepsiburada.com" in d.current_url or "akakce.com" not in d.current_url)
        return driver, driver.current_url
    except:
        driver.quit()
        return None, None

def scrape_hepsiburada_product(product_config):
    client, DRIVER = None, None
    try:
        client = MongoClient(MONGO_DB_URL, serverSelectionTimeoutMS=5000)
        db = client[DB_NAME]
        collection = db[product_config["collection"]]
        DRIVER = initialize_driver()
        product_name, base_data = scrape_akakce_base_data(DRIVER, product_config["url"])
        DRIVER.quit()
        DRIVER = None

        for item in base_data:
            v_name = item["vendor_name"].lower()
            link = item.get("link", "").lower()
            if "hepsiburada" in v_name or "hepsiburada" in link:
                hb_driver, final_url = resolve_hepsiburada_url(item["link"])
                if hb_driver:
                    details = deep_scrape_hepsiburada(hb_driver, final_url)
                    doc = {
                        "product_id": product_config["product_id"],
                        "product_name": product_name,
                        "site": SITE_NAME,
                        "vendor_name": item["vendor_name"],
                        "seller_nickname": item.get("seller_nickname") or None,
                        "price": item["price"],
                        "rating": details.get("rating"),
                        "review_count": details.get("reviews"),
                        "reviews_list": details.get("reviews_list", []),
                        "scrape_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    }
                    collection.update_one(
                        {"product_id": doc["product_id"], "vendor_name": doc["vendor_name"]},
                        {"$set": doc},
                        upsert=True
                    )
                    hb_driver.quit()
                    return f"✅ HB SCRAPER: {product_name} verisi kaydedildi."
        
        return "⚠️ HB SCRAPER: Hepsiburada satıcısı bulunamadı."
    except Exception as e:
        return f"❌ KRİTİK HATA (HB Scraper): {e}"
    finally:
        if DRIVER: DRIVER.quit()
        if client: client.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            config = json.loads(sys.argv[1])
            result = scrape_hepsiburada_product(config)
            print(f"\n{'='*50}\n{result}\n{'='*50}", flush=True)
        except Exception as e:
            print(f"❌ KRİTİK HATA: {str(e)}")