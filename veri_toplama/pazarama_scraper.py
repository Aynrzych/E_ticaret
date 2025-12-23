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
SITE_NAME = "pazarama"

# ----------------- PAZARAMA XPATH'LERİ -----------------
# Gerçek Pazarama ürün sayfasından doğrula/güncelle.
RATING_XPATH = '//*[@id="app"]/div[2]/div[1]/div[3]/div[2]/div[1]/div[2]/div/div/div[1]/span'
REVIEW_XPATH = '//*[@id="app"]/div[2]/div[1]/div[3]/div[2]/div[1]/div[2]/div/div/div[2]/a'
# Alternatif: Yıldız sayısından hesaplama için
STAR_CONTAINER_XPATH = '//div[@class="flex pointer-events-none"]'


def scrape_pazarama_reviews(driver, max_reviews=20):
    """
    Pazarama yorumlar sayfasından yorum metinlerini ve puanlarını çeker.
    XPath'ler: 
    - Yorum metni: //*[@id="product__comment__tab-header"]/div[1]/div[2]/div/div[1]/div[1]/div[2]/p
    - Yıldız (puan): //*[@id="product__comment__tab-header"]/div[1]/div[2]/div/div[1]/div[1]/div[1]
    """
    reviews_list = []
    
    try:
        wait = WebDriverWait(driver, 30)  # Timeout'u artırdık
        
        # Önce yorumlar sayfasının yüklendiğini kontrol et
        try:
            wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="product__comment__tab-header"]')))
            print("DEBUG: Pazarama yorumlar sayfası elementi bulundu")
        except:
            print("DEBUG: ⚠️ Pazarama yorumlar sayfası elementi bulunamadı, yine de deniyoruz...")
        
        # Sayfayı scroll yap (lazy loading için)
        print(f"DEBUG: Pazarama sayfası kaydırılıyor (maksimum {max_reviews} yorum için)...")
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
        parent_xpath = '//*[@id="product__comment__tab-header"]/div[1]/div[2]/div'
        try:
            parent_element = wait.until(EC.presence_of_element_located((By.XPATH, parent_xpath)))
            print("DEBUG: Pazarama yorum parent elementi bulundu")
            
            # Tüm div'leri al ve container'ları filtrele
            all_divs = parent_element.find_elements(By.XPATH, "./div")
            print(f"DEBUG: Pazarama'da {len(all_divs)} div bulundu")
            
            # Her div'in içinde yorum var mı kontrol et (div[1]/div[2]/p pattern'i)
            review_containers = []
            for div_idx, div in enumerate(all_divs):
                try:
                    # Bu div'in içinde yorum metni var mı kontrol et
                    test_elem = div.find_element(By.XPATH, ".//div[1]/div[2]/p")
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
                        text_elem = container.find_element(By.XPATH, ".//div[1]/div[2]/p")
                        review_data["text"] = text_elem.text.strip()
                        print(f"DEBUG: Pazarama yorum {i+1} metni bulundu: {len(review_data['text'])} karakter")
                    except:
                        try:
                            # Alternatif yollar
                            text_elem = container.find_element(By.XPATH, ".//p | .//span | .//div[contains(@class, 'comment')]")
                            review_data["text"] = text_elem.text.strip()
                        except:
                            review_data["text"] = None
                    
                    # Yorum puanını çek - container içinde relative XPath
                    try:
                        rating_container = container.find_element(By.XPATH, ".//div[1]/div[1]")
                        
                        rating = None
                        
                        # Yıldız sayısını bul - yıldız iconlarını say veya text içinde ara
                        # Pazarama'da yıldızlar genelde icon veya span ile gösterilir
                        stars = rating_container.find_elements(By.XPATH, ".//i[contains(@class, 'star')] | .//span[contains(@class, 'star')] | .//svg[contains(@class, 'star')]")
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
                        print(f"DEBUG: Pazarama yorum {i+1} puanı: {rating}")
                    except Exception as e:
                        print(f"DEBUG: Pazarama yorum {i+1} puanı çekilemedi (opsiyonel): {e}")
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
                        print(f"DEBUG: ✅ Pazarama yorum {i+1} eklendi")
                    else:
                        print(f"DEBUG: ⚠️ Pazarama yorum {i+1} metni çok kısa veya yok, atlandı")
                        
                except Exception as e:
                    print(f"DEBUG: ❌ Pazarama yorum {i+1} işlenirken hata: {e}")
                    continue
            
        except Exception as e:
            print(f"DEBUG HATA: Pazarama container bulma hatası: {e}")
        
        print(f"DEBUG: Pazarama'dan toplam {len(reviews_list)} yorum metni çekildi")
        
    except Exception as e:
        print(f"DEBUG HATA: Yorumlar çekilirken hata: {e}")
    
    return reviews_list


def deep_scrape_pazarama(driver, paz_url):
    """Pazarama ürün sayfasından puan, yorum sayısı ve yorum metinlerini çeker."""
    data = {"rating": None, "reviews": None, "reviews_list": []}
    try:
        driver.get(paz_url)
        time.sleep(random.uniform(5, 8))

        wait = WebDriverWait(driver, 30)

        # Yorum sayısını çek
        try:
            review_el = wait.until(EC.presence_of_element_located((By.XPATH, REVIEW_XPATH)))
            review_text = review_el.text.strip()
            if review_text:
                review_num = re.sub(r"[^\d]", "", review_text)
                if review_num:
                    data["reviews"] = int(review_num)
        except Exception as e:
            print(f"DEBUG: Pazarama yorum sayısı çekilemedi: {e}")

        # Puanı çek - önce direkt metin, yoksa yıldız sayısından hesapla
        try:
            rating_el = wait.until(EC.presence_of_element_located((By.XPATH, RATING_XPATH)))
            rating_text = rating_el.text.strip().replace(",", ".")
            if rating_text:
                data["rating"] = float(rating_text)
        except (ValueError, TimeoutException, NoSuchElementException):
            # Fallback: Yıldız sayısından hesapla
            try:
                star_container = driver.find_element(By.XPATH, STAR_CONTAINER_XPATH)
                # Dolu yıldızları say (text-orange-500)
                filled_stars = star_container.find_elements(By.CSS_SELECTOR, 'span.text-orange-500')
                # Kısmi yıldız için rating div'inin width'ini oku
                partial_star = star_container.find_elements(By.CSS_SELECTOR, 'div.rating')
                if partial_star:
                    width_style = partial_star[0].get_attribute('style')
                    width_match = re.search(r'width:\s*(\d+(?:\.\d+)?)%', width_style)
                    if width_match:
                        partial_value = float(width_match.group(1)) / 100
                    else:
                        partial_value = 0
                else:
                    partial_value = 0
                
                # Toplam puan = dolu yıldız sayısı + kısmi değer
                total_rating = len(filled_stars) + partial_value
                if total_rating > 0:
                    data["rating"] = round(total_rating, 2)
                    print(f"DEBUG: Pazarama puanı yıldız sayısından hesaplandı: {data['rating']}")
            except Exception as e2:
                print(f"DEBUG: Pazarama puan çekilemedi (metin ve yıldız yöntemi): {e2}")
        except Exception as e:
            print(f"DEBUG: Pazarama puan çekilemedi: {e}")

        if data["rating"] or data["reviews"]:
            print(f"DEBUG: Pazarama Puan/Yorum çekimi başarılı. Puan: {data['rating']}, Yorum sayısı: {data['reviews']}")
        
        # Yorumlar linkine tıkla ve yorum metinlerini çek
        try:
            review_link = review_el
            if review_link.tag_name == "a":
                review_href = review_link.get_attribute("href")
                if review_href:
                    print(f"DEBUG: Pazarama yorumlar sayfasına gidiliyor: {review_href}")
                    driver.get(review_href)
                    time.sleep(random.uniform(5, 8))  # Sayfanın yüklenmesi için daha fazla bekle
                    
                    # Yorumlar sayfasının yüklendiğini kontrol et
                    try:
                        wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="product__comment__tab-header"]')))
                        print("DEBUG: Pazarama yorumlar sayfası yüklendi")
                    except:
                        print("DEBUG: ⚠️ Pazarama yorumlar sayfası yüklenemedi, yine de deniyoruz...")
                    
                    # Yorum metinlerini çek
                    data["reviews_list"] = scrape_pazarama_reviews(driver, max_reviews=20)
                    print(f"DEBUG: Pazarama'dan {len(data['reviews_list'])} yorum metni çekildi")
                    
                    # Ana sayfaya geri dön (gerekirse)
                    # driver.back()
            else:
                # Eğer link değilse, yorumlar zaten bu sayfada olabilir
                print("DEBUG: Pazarama yorumlar linki bulunamadı, mevcut sayfadan çekilmeye çalışılıyor")
                # Yorumlar tab'ına tıkla (eğer varsa)
                try:
                    comment_tab = driver.find_element(By.XPATH, '//*[@id="product__comment__tab-header"]')
                    if comment_tab:
                        print("DEBUG: Pazarama yorumlar tab'ı bulundu, tıklanıyor...")
                        comment_tab.click()
                        time.sleep(random.uniform(3, 5))
                except:
                    print("DEBUG: Pazarama yorumlar tab'ı bulunamadı")
                
                data["reviews_list"] = scrape_pazarama_reviews(driver, max_reviews=20)
                print(f"DEBUG: Pazarama'dan {len(data['reviews_list'])} yorum metni çekildi (mevcut sayfadan)")
        except Exception as e:
            print(f"DEBUG: Pazarama yorum metinleri çekilemedi (opsiyonel): {e}")
            import traceback
            traceback.print_exc()
            # Yorum metinleri çekilemese bile devam et
            
    except TimeoutException:
        print("DEBUG HATA: Pazarama elementleri 30 saniyede yüklenmedi (Timeout).")
    except NoSuchElementException:
        print("DEBUG HATA: Pazarama XPath'leri bulunamadı.")
    except Exception as e:
        print(f"DEBUG KRİTİK HATA: Pazarama çekimi sırasında hata: {e}")

    return data


def resolve_pazarama_url(akakce_link):
    """
    Akakçe takip linkini Pazarama'ya yönlendirir. Hash içindeki f parametresini açar.
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
            lambda d: ("pazarama.com" in d.current_url) or ("akakce.com" not in d.current_url)
        )
        time.sleep(random.uniform(2, 4))

        final_url = driver.current_url

        if "pazarama.com" not in final_url and "akakce.com" in final_url:
            try:
                paz_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='pazarama.com']")
                if paz_links:
                    paz_href = paz_links[0].get_attribute("href")
                    print(f"DEBUG: Sayfada Pazarama linki bulundu, direkt gidiliyor: {paz_href}")
                    driver.get(paz_href)
                    WebDriverWait(driver, 20).until(lambda d: "pazarama.com" in d.current_url)
                    final_url = driver.current_url
            except Exception as e:
                print(f"DEBUG HATA: Sayfadan Pazarama linki çekilemedi: {e}")

        if "pazarama.com" not in final_url:
            print(f"DEBUG HATA: Yönlendirme Pazarama'ya gitmedi. Nihai URL: {final_url}")
            driver.quit()
            return None, None

        print(f"DEBUG: Nihai Pazarama URL'si yakalandı: {final_url}")
        return driver, final_url

    except Exception as e:
        print(f"DEBUG HATA: Pazarama yönlendirmesi yakalanamadı: {e}")
        driver.quit()
        return None, None


def scrape_pazarama_product(product_config):
    """Akakçe listesinden Pazarama satıcısını bulup puan/yorum çeker."""
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

        paz_link_found = False

        for item in base_data:
            vendor_name_lower = item["vendor_name"].lower().strip()
            # Pazarama kontrolü: "pazarama" içermeli (daha esnek)
            if "pazarama" not in vendor_name_lower:
                print(f"DEBUG: ⏭️  '{item['vendor_name']}' Pazarama değil, atlanıyor...")
                continue

            paz_link_found = True
            full_akakce_link = item["link"]
            print(f"DEBUG: Pazarama satıcısı bulundu. Akakçe linki: {full_akakce_link}")

            paz_driver, final_paz_url = resolve_pazarama_url(full_akakce_link)
            if not paz_driver or not final_paz_url:
                print("DEBUG: Pazarama yönlendirmesi alınamadı, satıcı atlandı.")
                continue

            vendor_details = deep_scrape_pazarama(paz_driver, final_paz_url)

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

            paz_driver.quit()
            print("DEBUG: Pazarama driver kapatıldı.")

        if not paz_link_found and len(base_data) > 0:
            # Hangi satıcıların geldiğini göster (debug için)
            vendor_list = [item.get('vendor_name', 'Bilinmiyor') for item in base_data[:5]]
            return f"⚠️ PAZ SCRAPER: Pazarama satıcısı bulunamadı. Bulunan satıcılar: {', '.join(vendor_list)}"
        if not base_data:
            return "⚠️ PAZ SCRAPER: Akakçe'den satıcı verisi çekilemedi (satıcı listesi boş)."

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
                return f"✅ PAZ SCRAPER: {product_name} için {len(new_data)} yeni veri kaydedildi ({len(scraped_data) - len(new_data)} zaten kayıtlıydı)."
            else:
                return f"⚠️ PAZ SCRAPER: {product_name} için tüm veriler zaten kayıtlı, yeni kayıt eklenmedi."

        return f"⚠️ PAZ SCRAPER: {product_name} için Pazarama satıcı verisi çekilemedi."

    except Exception as e:
        return f"❌ KRİTİK HATA (Pazarama Scraper): {e}"

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
            result = scrape_pazarama_product(product_config)
            # Eğer result None ise, bir hata mesajı oluştur
            if result is None:
                result = "⚠️ PAZ SCRAPER: Fonksiyon None döndü (beklenmeyen durum)"
        except Exception as e:
            # Hata varsa sonuç mesajı oluştur
            import traceback
            try:
                result = f"❌ KRİTİK HATA (Pazarama Scraper): {e}\n{traceback.format_exc()}"
            except UnicodeEncodeError:
                # Encoding hatası durumunda ASCII karakterler kullan
                result = f"KRITIK HATA (Pazarama Scraper): {str(e)}\n{traceback.format_exc()}"
        
        # Sonuç mesajını mutlaka yazdır (stdout'a, DEBUG mesajlarından sonra)
        # result None olsa bile yazdır
        try:
            print("\n" + "="*50, flush=True)  # Ayırıcı
            if result:
                print(result, flush=True)
            else:
                print("⚠️ PAZ SCRAPER: Sonuç mesajı alınamadı (result=None)", flush=True)
            print("="*50 + "\n", flush=True)
        except UnicodeEncodeError:
            # Windows konsolu encoding hatası durumunda ASCII karakterler kullan
            safe_result = result.encode('ascii', 'ignore').decode('ascii') if result else "PAZ SCRAPER: Sonuc mesaji alinamadi"
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

