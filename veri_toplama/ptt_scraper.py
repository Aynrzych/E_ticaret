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
SITE_NAME = "pttavm"

# ----------------- PTTAVM XPATH'LERİ -----------------
# Burayı PttAVM ürün sayfasından güncel XPath/CSS ile doğrula.
RATING_XPATH = '//*[@id="tc-tab-comments"]/div[2]/div/div/div[1]/div[1]/div[2]'
REVIEW_XPATH = '//*[@id="tc-tab-comments"]/div[2]/div/div/div[1]/div[2]'


def scrape_ptt_reviews(driver, max_reviews=20):
    """
    PttAVM yorumlar sayfasından yorum metinlerini ve puanlarını çeker.
    XPath'ler: 
    - Yorum metni: //*[@id="tc-tab-comments"]/div[2]/div/div/div[2]/div/div/div/div[1]/div/div/div[2]/div
    - Yıldız (puan): //*[@id="tc-tab-comments"]/div[2]/div/div/div[2]/div/div/div/div[1]/div/div/div[1]/div[1]/div[2]
    """
    reviews_list = []
    
    try:
        wait = WebDriverWait(driver, 20)
        
        # Yorum container'larını bul - //*[@id="tc-tab-comments"]/div[2]/div/div/div[2]/div/div/div/div[1]
        # Her yorum için farklı index'ler var, bu yüzden genel bir yapı kullanıyoruz
        review_container_xpath = '//*[@id="tc-tab-comments"]/div[2]/div/div/div[2]/div/div/div/div[1]'
        review_containers = wait.until(
            EC.presence_of_all_elements_located((By.XPATH, review_container_xpath))
        )
        
        print(f"DEBUG: {len(review_containers)} yorum container bulundu")
        
        for i, container in enumerate(review_containers[:max_reviews]):
            try:
                review_data = {}
                
                # Yorum metnini çek
                # XPath: div/div/div[2]/div (container içinde)
                try:
                    # Önce spesifik yapıyı dene
                    text_elem = container.find_element(By.XPATH, ".//div/div/div[2]/div")
                    review_data["text"] = text_elem.text.strip()
                except:
                    try:
                        # Alternatif: Container içinde p, span veya div içinde yorum metni ara
                        text_elem = container.find_element(By.XPATH, ".//p | .//span | .//div[contains(@class, 'comment') or contains(@class, 'review')]")
                        review_data["text"] = text_elem.text.strip()
                    except:
                        try:
                            # Son çare: Container içindeki tüm metin elemanlarını ara
                            text_elements = container.find_elements(By.XPATH, ".//p | .//span | .//div")
                            if text_elements:
                                # En uzun metni al (genelde yorum metni en uzun olur)
                                text_elem = max(text_elements, key=lambda x: len(x.text.strip()))
                                review_data["text"] = text_elem.text.strip()
                            else:
                                review_data["text"] = None
                        except:
                            review_data["text"] = None
                
                # Yorum puanını çek - SADECE bu yorum container'ı içinde
                # XPath: div/div/div[1]/div[1]/div[2] (container içinde)
                try:
                    rating = None
                    # Container içinde, parent'a çıkmadan sadece bu container içinde ara
                    rating_container = container.find_element(By.XPATH, ".//div/div/div[1]/div[1]/div[2]")
                    
                    # Puan metnini çek
                    rating_text = rating_container.text.strip()
                    # Sadece sayıyı al (1-5 arası)
                    rating_match = re.search(r'(\d+(?:\.\d+)?)', rating_text)
                    if rating_match:
                        rating_float = float(rating_match.group(1))
                        if 1 <= rating_float <= 5:
                            rating = int(rating_float) if rating_float.is_integer() else rating_float
                    
                    # Eğer text'te bulamadıysak, yıldız iconlarını say
                    if not rating:
                        stars = rating_container.find_elements(By.XPATH, ".//i[contains(@class, 'star')] | .//span[contains(@class, 'star')] | .//svg[contains(@class, 'star')]")
                        if stars:
                            # Aktif/dolu yıldız sayısını say
                            active_stars = [s for s in stars if "fill" in (s.get_attribute("class") or "").lower() or "active" in (s.get_attribute("class") or "").lower()]
                            if active_stars:
                                rating = len(active_stars)
                            else:
                                # Eğer aktif class yoksa, tüm yıldızları say (hepsi dolu varsayımı)
                                rating = len(stars) if len(stars) <= 5 else 5
                    
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
                except Exception as e:
                    print(f"DEBUG: Yorum {i+1} puanı çekilemedi (opsiyonel): {e}")
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
                    
            except Exception as e:
                print(f"DEBUG: Yorum {i+1} işlenirken hata: {e}")
                continue
        
        print(f"DEBUG: {len(reviews_list)} yorum metni çekildi")
        
    except Exception as e:
        print(f"DEBUG HATA: Yorumlar çekilirken hata: {e}")
    
    return reviews_list


def deep_scrape_ptt(driver, ptt_url):
    """PttAVM ürün sayfasından puan, yorum sayısı ve yorum metinlerini çeker."""
    data = {"rating": None, "reviews": None, "reviews_list": []}
    try:
        driver.get(ptt_url)
        time.sleep(random.uniform(5, 8))

        wait = WebDriverWait(driver, 30)

        # Yorum sayısını çek - daha esnek yaklaşım
        try:
            review_el = wait.until(EC.presence_of_element_located((By.XPATH, REVIEW_XPATH)))
            review_text = review_el.text.strip()
            if review_text:
                review_num = re.sub(r"[^\d]", "", review_text)
                if review_num:
                    data["reviews"] = int(review_num)
        except TimeoutException:
            print("DEBUG: PttAVM yorum elementi bulunamadı (timeout)")
        except Exception as e:
            print(f"DEBUG: PttAVM yorum sayısı çekilemedi: {e}")

        # Puanı çek - daha esnek yaklaşım
        try:
            rating_el = wait.until(EC.presence_of_element_located((By.XPATH, RATING_XPATH)))
            rating_text = rating_el.text.strip().replace(",", ".")
            if rating_text:
                data["rating"] = float(rating_text)
        except TimeoutException:
            print("DEBUG: PttAVM puan elementi bulunamadı (timeout)")
        except ValueError:
            print(f"DEBUG: PttAVM puan metni boş veya geçersiz: '{rating_text}'")
        except Exception as e:
            print(f"DEBUG: PttAVM puan çekilemedi: {e}")

        if data["rating"] or data["reviews"]:
            print(f"DEBUG: PttAVM Puan/Yorum çekimi başarılı. Puan: {data['rating']}, Yorum sayısı: {data['reviews']}")
        else:
            print("DEBUG: PttAVM'de puan/yorum bulunamadı (sayfa yapısı değişmiş olabilir)")
        
        # Yorumlar sayfasına git ve yorum metinlerini çek
        try:
            # Yorumlar tab'ına tıkla veya direkt yorumlar sayfasına git
            # PttAVM'de yorumlar genelde aynı sayfada tab içinde olabilir
            # Önce mevcut sayfadan çekmeyi dene
            print("DEBUG: Mevcut sayfadan yorumlar çekilmeye çalışılıyor")
            data["reviews_list"] = scrape_ptt_reviews(driver, max_reviews=20)
            
            # Eğer yorumlar bulunamadıysa, yorumlar tab'ına tıkla
            if not data["reviews_list"]:
                try:
                    comment_tab = driver.find_element(By.XPATH, "//a[contains(@href, 'comment') or contains(text(), 'Yorum')] | //button[contains(text(), 'Yorum')]")
                    comment_tab.click()
                    time.sleep(random.uniform(2, 4))
                    data["reviews_list"] = scrape_ptt_reviews(driver, max_reviews=20)
                except:
                    print("DEBUG: Yorumlar tab'ı bulunamadı")
        except Exception as e:
            print(f"DEBUG: Yorum metinleri çekilemedi (opsiyonel): {e}")
            # Yorum metinleri çekilemese bile devam et
            
    except Exception as e:
        print(f"DEBUG KRİTİK HATA: PttAVM çekimi sırasında hata: {e}")

    return data


def resolve_ptt_url(akakce_link):
    """
    Akakçe takip linkini PttAVM'ye yönlendirir. Hash içindeki f parametresini açar.
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
            lambda d: ("pttavm.com" in d.current_url) or ("akakce.com" not in d.current_url)
        )
        time.sleep(random.uniform(2, 4))

        final_url = driver.current_url

        if "pttavm.com" not in final_url and "akakce.com" in final_url:
            try:
                ptt_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='pttavm.com']")
                if ptt_links:
                    ptt_href = ptt_links[0].get_attribute("href")
                    print(f"DEBUG: Sayfada PttAVM linki bulundu, direkt gidiliyor: {ptt_href}")
                    driver.get(ptt_href)
                    WebDriverWait(driver, 20).until(lambda d: "pttavm.com" in d.current_url)
                    final_url = driver.current_url
            except Exception as e:
                print(f"DEBUG HATA: Sayfadan PttAVM linki çekilemedi: {e}")

        if "pttavm.com" not in final_url:
            print(f"DEBUG HATA: Yönlendirme PttAVM'ye gitmedi. Nihai URL: {final_url}")
            driver.quit()
            return None, None

        print(f"DEBUG: Nihai PttAVM URL'si yakalandı: {final_url}")
        return driver, final_url

    except Exception as e:
        print(f"DEBUG HATA: PttAVM yönlendirmesi yakalanamadı: {e}")
        driver.quit()
        return None, None


def scrape_ptt_product(product_config):
    """Akakçe listesinden PttAVM satıcısını bulup puan/yorum çeker."""
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

        ptt_link_found = False

        for item in base_data:
            vendor_name_lower = item["vendor_name"].lower().strip()
            # PTT kontrolü: "ptt" veya "pttavm" içermeli (daha esnek)
            if "ptt" not in vendor_name_lower and "pttavm" not in vendor_name_lower:
                print(f"DEBUG: ⏭️  '{item['vendor_name']}' PTT değil, atlanıyor...")
                continue

            ptt_link_found = True
            full_akakce_link = item["link"]
            print(f"DEBUG: PttAVM satıcısı bulundu. Akakçe linki: {full_akakce_link}")

            ptt_driver, final_ptt_url = resolve_ptt_url(full_akakce_link)
            if not ptt_driver or not final_ptt_url:
                print("DEBUG: PttAVM yönlendirmesi alınamadı, satıcı atlandı.")
                continue

            vendor_details = deep_scrape_ptt(ptt_driver, final_ptt_url)

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

            ptt_driver.quit()
            print("DEBUG: PttAVM driver kapatıldı.")

        if not ptt_link_found and len(base_data) > 0:
            # Hangi satıcıların geldiğini göster (debug için)
            vendor_list = [item.get('vendor_name', 'Bilinmiyor') for item in base_data[:5]]
            return f"⚠️ PTT SCRAPER: PttAVM satıcısı bulunamadı. Bulunan satıcılar: {', '.join(vendor_list)}"
        if not base_data:
            return "⚠️ PTT SCRAPER: Akakçe'den satıcı verisi çekilemedi (satıcı listesi boş)."

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
                return f"✅ PTT SCRAPER: {product_name} için {len(new_data)} yeni veri kaydedildi ({len(scraped_data) - len(new_data)} zaten kayıtlıydı)."
            else:
                return f"⚠️ PTT SCRAPER: {product_name} için tüm veriler zaten kayıtlı, yeni kayıt eklenmedi."

        return f"⚠️ PTT SCRAPER: {product_name} için PttAVM satıcı verisi çekilemedi."

    except Exception as e:
        return f"❌ KRİTİK HATA (PTT Scraper): {e}"

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
            result = scrape_ptt_product(product_config)
            # Eğer result None ise, bir hata mesajı oluştur
            if result is None:
                result = "⚠️ PTT SCRAPER: Fonksiyon None döndü (beklenmeyen durum)"
        except Exception as e:
            # Hata varsa sonuç mesajı oluştur
            import traceback
            try:
                result = f"❌ KRİTİK HATA (PTT Scraper): {e}\n{traceback.format_exc()}"
            except UnicodeEncodeError:
                # Encoding hatası durumunda ASCII karakterler kullan
                result = f"KRITIK HATA (PTT Scraper): {str(e)}\n{traceback.format_exc()}"
        
        # Sonuç mesajını mutlaka yazdır (stdout'a, DEBUG mesajlarından sonra)
        # result None olsa bile yazdır
        try:
            print("\n" + "="*50, flush=True)  # Ayırıcı
            if result:
                print(result, flush=True)
            else:
                print("⚠️ PTT SCRAPER: Sonuç mesajı alınamadı (result=None)", flush=True)
            print("="*50 + "\n", flush=True)
        except UnicodeEncodeError:
            # Windows konsolu encoding hatası durumunda ASCII karakterler kullan
            safe_result = result.encode('ascii', 'ignore').decode('ascii') if result else "PTT SCRAPER: Sonuc mesaji alinamadi"
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

