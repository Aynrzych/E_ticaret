import sys
import json
import time
import re
import random
from urllib.parse import urlparse, parse_qs, unquote

from pymongo import MongoClient
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from utils import initialize_driver, scrape_akakce_base_data

# ----------------- YAPILANDIRMA -----------------

MONGO_DB_URL = "mongodb://localhost:27017/"
DB_NAME = "missha_price_data"
SITE_NAME = "n11"

# ----------------- N11 XPATH'LERİ -----------------
# Burayı gerçek N11 ürün sayfasından güncel XPath/CSS ile doğrula.
RATING_XPATH = '//*[@id="unf-p-id"]/div/div[2]/div[2]/div[1]/div/div[2]/div[1]/div[2]/div/strong'
REVIEW_XPATH = '//*[@id="readReviews"]/span'


def scrape_n11_reviews(driver, max_reviews=20):
    """
    N11 yorumlar sayfasından yorum metinlerini ve puanlarını çeker.
    Hepsiburada yaklaşımını kullanarak: scroll, container bulma, vs.
    """
    reviews_list = []
    
    try:
        wait = WebDriverWait(driver, 30)
        
        # Önce yorumlar container'ını bekle
        try:
            wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="app"]')))
            print("DEBUG: N11 app container bulundu")
        except:
            print("DEBUG: ⚠️ N11 app container bulunamadı")
        
        # Sayfayı scroll yap (lazy loading için)
        print(f"DEBUG: N11 sayfası kaydırılıyor (maksimum {max_reviews} yorum için)...")
        scroll_positions = [300, 600, 900, 1200, 1500]
        if max_reviews > 10:
            scroll_positions.extend([1800, 2100])
        for scroll_pos in scroll_positions:
            driver.execute_script(f"window.scrollTo(0, {scroll_pos});")
            time.sleep(1)
        
        # "Daha fazla yorum" butonunu kontrol et
        try:
            load_more = driver.find_elements(By.XPATH, "//button[contains(text(), 'Daha fazla')] | //button[contains(text(), 'daha fazla')] | //a[contains(text(), 'Daha fazla')]")
            if load_more:
                load_more[0].click()
                time.sleep(2)
        except:
            pass
        
        time.sleep(2)  # Yorumların yüklenmesi için bekle
        
        # Container'ları bul - Hepsiburada yaklaşımı gibi
        parent_xpath = '//*[@id="app"]/div/div[3]/div[2]'
        try:
            parent_element = wait.until(EC.presence_of_element_located((By.XPATH, parent_xpath)))
            print("DEBUG: N11 yorum parent elementi bulundu")
            
            # Tüm div'leri al ve container'ları filtrele
            all_divs = parent_element.find_elements(By.XPATH, "./div")
            print(f"DEBUG: N11'de {len(all_divs)} div bulundu")
            
            # Her div'in içinde yorum var mı kontrol et (div[2]/div[2]/span pattern'i)
            review_containers = []
            for div_idx, div in enumerate(all_divs):
                try:
                    # Bu div'in içinde yorum metni var mı kontrol et
                    test_elem = div.find_element(By.XPATH, ".//div[2]/div[2]/span")
                    if test_elem and test_elem.text and len(test_elem.text.strip()) > 10:
                        review_containers.append(div)
                        if len(review_containers) <= 3:
                            print(f"DEBUG: ✅ Container {div_idx+1} geçerli yorum içeriyor")
                except:
                    continue
            
            print(f"DEBUG: {len(review_containers)} yorum container bulundu")
            
            # Container'ları işle
            for i, container in enumerate(review_containers[:max_reviews]):
                try:
                    review_data = {}
                    
                    # Yorum metnini çek - container içinde relative XPath
                    try:
                        text_elem = container.find_element(By.XPATH, ".//div[2]/div[2]/span")
                        review_data["text"] = text_elem.text.strip()
                        print(f"DEBUG: N11 yorum {i+1} metni bulundu: {len(review_data['text'])} karakter")
                    except:
                        try:
                            # Alternatif yollar
                            text_elem = container.find_element(By.XPATH, ".//span | .//div[contains(@class, 'comment')] | .//div[contains(@class, 'review')]")
                            review_data["text"] = text_elem.text.strip()
                        except:
                            review_data["text"] = None
                    
                    # Yorum puanını çek - container içinde relative XPath
                    try:
                        rating_container = container.find_element(By.XPATH, ".//div[2]/div[1]/div")
                        
                        rating = None
                        # Yıldız sayısını bul - yıldız iconlarını say
                        stars = rating_container.find_elements(By.XPATH, ".//i[contains(@class, 'star')] | .//span[contains(@class, 'star')] | .//svg[contains(@class, 'star')] | .//div[contains(@class, 'star')]")
                        if stars:
                            # Aktif/dolu yıldız sayısını say
                            active_stars = [s for s in stars if "fill" in (s.get_attribute("class") or "").lower() or "active" in (s.get_attribute("class") or "").lower() or "text-orange" in (s.get_attribute("class") or "").lower()]
                            if active_stars:
                                rating = len(active_stars)
                            else:
                                # Eğer aktif class yoksa, tüm yıldızları say (hepsi dolu varsayımı)
                                rating = len(stars) if len(stars) <= 5 else 5
                        
                        # Eğer yıldız sayısından bulamadıysak, text içinde ara
                        if not rating:
                            rating_text = rating_container.text.strip()
                            rating_match = re.search(r'(\d+(?:\.\d+)?)', rating_text)
                            if rating_match:
                                rating_float = float(rating_match.group(1))
                                if 1 <= rating_float <= 5:
                                    rating = int(rating_float) if rating_float.is_integer() else rating_float
                        
                        # Eğer hala bulamadıysak, aria-label veya title'a bak
                        if not rating:
                            aria_label = rating_container.get_attribute("aria-label") or rating_container.get_attribute("title") or ""
                            if "yıldız" in aria_label.lower() or "star" in aria_label.lower():
                                rating_match = re.search(r'(\d+)', aria_label)
                                if rating_match:
                                    rating_val = int(rating_match.group(1))
                                    if 1 <= rating_val <= 5:
                                        rating = rating_val
                        
                        review_data["rating"] = rating
                        print(f"DEBUG: N11 yorum {i+1} puanı: {rating}")
                    except Exception as e:
                        print(f"DEBUG: N11 yorum {i+1} puanı çekilemedi (opsiyonel): {e}")
                        review_data["rating"] = None
                    
                    # Yorum tarihi (opsiyonel)
                    try:
                        date_elem = container.find_element(By.XPATH, ".//time | .//span[contains(@class, 'date')] | .//div[contains(@class, 'date')]")
                        review_data["date"] = date_elem.text.strip() or date_elem.get_attribute("datetime")
                    except:
                        review_data["date"] = None
                    
                    # Sadece metni olan yorumları ekle
                    if review_data.get("text") and len(review_data["text"]) > 10:  # En az 10 karakter
                        reviews_list.append(review_data)
                        print(f"DEBUG: ✅ N11 yorum {i+1} eklendi")
                    else:
                        print(f"DEBUG: ⚠️ N11 yorum {i+1} metni çok kısa veya yok, atlandı")
                        
                except Exception as e:
                    print(f"DEBUG: ❌ N11 yorum {i+1} işlenirken hata: {e}")
                    continue
            
        except Exception as e:
            print(f"DEBUG HATA: N11 container bulma hatası: {e}")
        
        print(f"DEBUG: N11'den toplam {len(reviews_list)} yorum metni çekildi")
        
    except Exception as e:
        print(f"DEBUG HATA: Yorumlar çekilirken hata: {e}")
    
    return reviews_list


def deep_scrape_n11(driver, n11_url):
    """N11 ürün sayfasından puan, yorum sayısı ve yorum metinlerini çeker."""
    data = {"rating": None, "reviews": None, "reviews_list": []}
    try:
        driver.get(n11_url)
        time.sleep(random.uniform(5, 8))

        wait = WebDriverWait(driver, 30)

        review_el = wait.until(EC.presence_of_element_located((By.XPATH, REVIEW_XPATH)))
        review_text = review_el.text
        data["reviews"] = int(re.sub(r"[^\d]", "", review_text))

        rating_el = wait.until(EC.presence_of_element_located((By.XPATH, RATING_XPATH)))
        rating_text = rating_el.text.replace(",", ".")
        data["rating"] = float(rating_text)

        print(f"DEBUG: N11 Puan/Yorum çekimi başarılı. Puan: {data['rating']}, Yorum sayısı: {data['reviews']}")
        
        # Yorumlar linkine tıkla ve yorum metinlerini çek
        try:
            review_link = review_el
            if review_link.tag_name == "a" or review_link.find_element(By.XPATH, "./..").tag_name == "a":
                # Parent'a bak veya kendisi link olabilir
                parent_a = review_link.find_element(By.XPATH, "./..") if review_link.tag_name != "a" else review_link
                review_href = parent_a.get_attribute("href")
                if review_href:
                    print(f"DEBUG: Yorumlar sayfasına gidiliyor: {review_href}")
                    driver.get(review_href)
                    time.sleep(random.uniform(3, 5))
                    
                    # Yorum metinlerini çek
                    data["reviews_list"] = scrape_n11_reviews(driver, max_reviews=20)
                    
                    # Ana sayfaya geri dön (gerekirse)
                    # driver.back()
            else:
                # Eğer link değilse, yorumlar zaten bu sayfada olabilir
                print("DEBUG: Yorumlar linki bulunamadı, mevcut sayfadan çekilmeye çalışılıyor")
                data["reviews_list"] = scrape_n11_reviews(driver, max_reviews=20)
        except Exception as e:
            print(f"DEBUG: Yorum metinleri çekilemedi (opsiyonel): {e}")
            # Yorum metinleri çekilemese bile devam et
            
    except TimeoutException:
        print("DEBUG HATA: N11 elementleri 30 saniyede yüklenmedi (Timeout).")
    except NoSuchElementException:
        print("DEBUG HATA: N11 XPath'leri bulunamadı.")
    except Exception as e:
        print(f"DEBUG KRİTİK HATA: N11 çekimi sırasında hata: {e}")

    return data


def resolve_n11_url(akakce_link):
    """
    Akakçe takip linkini N11'e yönlendirir. Hash içindeki f parametresini açar.
    """

    def _build_redirect_url(link: str) -> str:
        parsed = urlparse(link)
        queries = parse_qs(parsed.query)
        frag_queries = parse_qs(parsed.fragment.replace("#", ""))
        f_param = (frag_queries.get("f") or queries.get("f") or [None])[0]
        if f_param:
            decoded = unquote(f_param)
            if decoded.startswith("/"):
                return f"https://www.akakce.com{decoded}"
            return f"https://www.akakce.com/{decoded}"
        return link

    akakce_resolved = _build_redirect_url(akakce_link)

    driver = initialize_driver()
    try:
        driver.get(akakce_resolved)

        WebDriverWait(driver, 15).until(lambda d: len(d.window_handles) >= 1)
        if len(driver.window_handles) > 1:
            driver.switch_to.window(driver.window_handles[-1])

        WebDriverWait(driver, 40).until(
            lambda d: ("n11.com" in d.current_url) or ("akakce.com" not in d.current_url)
        )
        time.sleep(random.uniform(2, 4))

        final_url = driver.current_url

        if "n11.com" not in final_url and "akakce.com" in final_url:
            try:
                n11_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='n11.com']")
                if n11_links:
                    n11_href = n11_links[0].get_attribute("href")
                    print(f"DEBUG: Sayfada N11 linki bulundu, direkt gidiliyor: {n11_href}")
                    driver.get(n11_href)
                    WebDriverWait(driver, 20).until(lambda d: "n11.com" in d.current_url)
                    final_url = driver.current_url
            except Exception as e:
                print(f"DEBUG HATA: Sayfadan N11 linki çekilemedi: {e}")

        if "n11.com" not in final_url:
            print(f"DEBUG HATA: Yönlendirme N11'e gitmedi. Nihai URL: {final_url}")
            driver.quit()
            return None, None

        print(f"DEBUG: Nihai N11 URL'si yakalandı: {final_url}")
        return driver, final_url

    except Exception as e:
        print(f"DEBUG HATA: N11 yönlendirmesi yakalanamadı: {e}")
        driver.quit()
        return None, None


def scrape_n11_product(product_config):
    """Akakçe listesinden N11 satıcısını bulup puan/yorum çeker."""
    client, DRIVER, scraped_data = None, None, []
    try:
        client = MongoClient(MONGO_DB_URL, serverSelectionTimeoutMS=5000)
        db = client[DB_NAME]
        collection = db[product_config["collection"]]
        DRIVER = initialize_driver()
        print(f"DEBUG: Akakçe'den veri çekiliyor... Ürün: {product_config['product_name']}")
        product_name, base_data = scrape_akakce_base_data(DRIVER, product_config["url"])
        print(f"DEBUG: Akakçe'den toplam {len(base_data)} satıcı verisi çekildi.")
        DRIVER.quit()
        DRIVER = None
        print("DEBUG: Akakçe driver'ı kapatıldı.")

        n11_link_found = False

        for item in base_data:
            vendor_name_lower = item["vendor_name"].lower().strip()
            # N11 kontrolü: "n11" içermeli (daha esnek)
            if "n11" not in vendor_name_lower:
                print(f"DEBUG: ⏭️  '{item['vendor_name']}' N11 değil, atlanıyor...")
                continue

            n11_link_found = True
            full_akakce_link = item["link"]
            print(f"DEBUG: N11 satıcısı bulundu. Akakçe linki: {full_akakce_link}")

            n11_driver, final_n11_url = resolve_n11_url(full_akakce_link)
            if not n11_driver or not final_n11_url:
                print("DEBUG: N11 yönlendirmesi alınamadı, satıcı atlandı.")
                continue

            vendor_details = deep_scrape_n11(n11_driver, final_n11_url)

            scraped_data.append(
                {
                    "product_id": product_config["product_id"],
                    "product_name": product_name,
                    "category": product_config.get("category"),
                    "site": SITE_NAME,
                    "vendor_name": item["vendor_name"],
                    "seller_nickname": item["seller_nickname"],
                    "price": item["price"],
                    "source_url": full_akakce_link,
                    "rating": vendor_details.get("rating"),
                    "review_count": vendor_details.get("reviews"),
                    "reviews_list": vendor_details.get("reviews_list", []),
                    "scrape_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
            )

            n11_driver.quit()
            print("DEBUG: N11 driver kapatıldı.")

        if not n11_link_found and len(base_data) > 0:
            # Hangi satıcıların geldiğini göster (debug için)
            vendor_list = [item.get('vendor_name', 'Bilinmiyor') for item in base_data[:5]]
            return f"⚠️ N11 SCRAPER: N11 satıcısı bulunamadı. Bulunan satıcılar: {', '.join(vendor_list)}"
        if not base_data:
            return "⚠️ N11 SCRAPER: Akakçe'den satıcı verisi çekilemedi (satıcı listesi boş)."

        if scraped_data:
            # Sadece yeni verileri kaydet - aynı kombinasyon varsa atla
            new_data = []
            for data in scraped_data:
                # Aynı product_id, site, vendor_name, seller_nickname kombinasyonu var mı kontrol et
                existing = collection.find_one({
                    "product_id": data["product_id"],
                    "site": data["site"],
                    "vendor_name": data["vendor_name"],
                    "seller_nickname": data.get("seller_nickname") or ""
                })
                if not existing:
                    new_data.append(data)
                else:
                    print(f"DEBUG: ⏭️  Zaten kayıtlı: {data['product_id']} - {data['site']} - {data['vendor_name']} - {data.get('seller_nickname', '')}")
            
            if new_data:
                collection.insert_many(new_data)
                return f"✅ N11 SCRAPER: {product_name} için {len(new_data)} yeni veri kaydedildi ({len(scraped_data) - len(new_data)} zaten kayıtlıydı)."
            else:
                return f"⚠️ N11 SCRAPER: {product_name} için tüm veriler zaten kayıtlı, yeni kayıt eklenmedi."

        return f"⚠️ N11 SCRAPER: {product_name} için N11 satıcı verisi çekilemedi."

    except Exception as e:
        return f"❌ KRİTİK HATA (N11 Scraper): {e}"

    finally:
        if DRIVER:
            DRIVER.quit()
        if client:
            client.close()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        result = None
        try:
            product_config = json.loads(sys.argv[1])
            result = scrape_n11_product(product_config)
            # Eğer result None ise, bir hata mesajı oluştur
            if result is None:
                result = "⚠️ N11 SCRAPER: Fonksiyon None döndü (beklenmeyen durum)"
        except Exception as e:
            # Hata varsa sonuç mesajı oluştur
            import traceback
            try:
                result = f"❌ KRİTİK HATA (N11 Scraper): {e}\n{traceback.format_exc()}"
            except UnicodeEncodeError:
                # Encoding hatası durumunda ASCII karakterler kullan
                result = f"KRITIK HATA (N11 Scraper): {str(e)}\n{traceback.format_exc()}"
        
        # Sonuç mesajını mutlaka yazdır (stdout'a, DEBUG mesajlarından sonra)
        # result None olsa bile yazdır
        try:
            print("\n" + "="*50, flush=True)  # Ayırıcı
            if result:
                print(result, flush=True)
            else:
                print("⚠️ N11 SCRAPER: Sonuç mesajı alınamadı (result=None)", flush=True)
            print("="*50 + "\n", flush=True)
        except UnicodeEncodeError:
            # Windows konsolu encoding hatası durumunda ASCII karakterler kullan
            safe_result = result.encode('ascii', 'ignore').decode('ascii') if result else "N11 SCRAPER: Sonuc mesaji alinamadi"
            print("\n" + "="*50, flush=True)
            print(safe_result, flush=True)
            print("="*50 + "\n", flush=True)
        sys.stdout.flush()  # Buffer'ı temizle
    else:
        error_msg = "❌ Hata: Bu script, main.py tarafından bir JSON argümanı ile çağrılmalıdır."
        try:
            print(error_msg, flush=True)
            print(error_msg, file=sys.stderr, flush=True)
        except UnicodeEncodeError:
            safe_msg = error_msg.encode('ascii', 'ignore').decode('ascii')
            print(safe_msg, flush=True)
            print(safe_msg, file=sys.stderr, flush=True)

