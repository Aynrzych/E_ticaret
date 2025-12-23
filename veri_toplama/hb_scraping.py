# veri_toplama/hb_scraper.py

import sys
import json
import time
import re
from urllib.parse import urlparse, parse_qs, unquote
from pymongo import MongoClient
from selenium.webdriver.common.by import By 
import random
# UTILS dosyasından ortak fonksiyonları içeri aktar
from utils import initialize_driver, scrape_akakce_base_data 
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# ----------------- YAPILANDIRMA -----------------

MONGO_DB_URL = "mongodb://localhost:27017/"
DB_NAME = "missha_price_data"
SITE_NAME = "hepsiburada"

# ----------------- HEPSIBURADA ÖZEL FONKSİYONLAR -----------------

# Sizin belirlediğiniz KARARLI ve GÜNCEL olduğu varsayılan XPath'ler
RATING_XPATH = '//*[@id="container"]/main/div/div[2]/section[1]/div[2]/div[1]/div[2]/div/div/span'
REVIEW_XPATH = '//*[@id="container"]/main/div/div[2]/section[1]/div[2]/div[1]/div[2]/div/a'

def scrape_hepsiburada_reviews(driver, max_reviews=20):
    """
    Hepsiburada yorumlar sayfasından yorum metinlerini ve puanlarını çeker.
    
    Args:
        driver: Selenium WebDriver
        max_reviews: Maksimum kaç yorum çekilecek (varsayılan: 20, performans için)
    """
    reviews_list = []
    
    # Güvenlik: Maksimum limit kontrolü
    if max_reviews > 100:
        print(f"DEBUG: ⚠️ max_reviews {max_reviews} çok yüksek, 100'e sınırlandırılıyor (performans için)")
        max_reviews = 100
    
    try:
        wait = WebDriverWait(driver, 20)
        
        # Hepsiburada yorum container'larını bul - hermes-voltran-comments içinde
        # Kullanıcının verdiği XPath'leri kullan:
        # Yorum metni: //*[@id="hermes-voltran-comments"]/div[6]/div[3]/div/div[1]/div[2]/div[2]
        # Yorum puanı: //*[@id="hermes-voltran-comments"]/div[6]/div[3]/div/div[1]/div[2]/div[1]/div[2]/div/span/div/div[1]
        # Her yorum için: div[6]/div[3] = yorum container'ı (ama div[6] değişebilir, tüm div'leri kontrol et)
        
        # Önce hermes-voltran-comments container'ını bekle
        try:
            wait.until(EC.presence_of_element_located((By.XPATH, "//div[@id='hermes-voltran-comments']")))
            print("DEBUG: hermes-voltran-comments container bulundu")
        except Exception as e:
            print(f"DEBUG HATA: hermes-voltran-comments container bulunamadı! Hata: {e}")
            # Alternatif: Sayfada yorumlar farklı bir yerde olabilir
            try:
                # Yorumlar sayfasının URL'sini kontrol et
                current_url = driver.current_url
                print(f"DEBUG: Mevcut URL: {current_url}")
                
                # Sayfanın HTML'ini kontrol et
                page_source = driver.page_source[:5000]  # İlk 5000 karakter
                if "hermes-voltran-comments" in page_source:
                    print("DEBUG: hermes-voltran-comments sayfada var ama yüklenmemiş, bekleniyor...")
                    time.sleep(5)
                    try:
                        wait.until(EC.presence_of_element_located((By.XPATH, "//div[@id='hermes-voltran-comments']")))
                        print("DEBUG: hermes-voltran-comments şimdi bulundu")
                    except:
                        pass
                
                if "yorumlar" not in current_url.lower() and "review" not in current_url.lower():
                    print("DEBUG: Yorumlar sayfasında değiliz, yorumlar linkini arıyoruz...")
            except:
                pass
            
            # Eğer hala bulunamadıysa, alternatif container'ları dene
            try:
                alt_containers = driver.find_elements(By.XPATH, "//div[contains(@id, 'comment')] | //div[contains(@id, 'review')] | //div[contains(@class, 'review')] | //div[contains(@class, 'comment')]")
                if alt_containers:
                    print(f"DEBUG: Alternatif container bulundu: {len(alt_containers)} adet")
                else:
                    print("DEBUG: Hiç yorum container'ı bulunamadı, boş liste döndürülüyor")
                    return reviews_list
            except:
                return reviews_list
        
        # Sayfayı yavaşça kaydır (lazy loading için) - SADECE GEREKLI KADAR
        print(f"DEBUG: Sayfa kaydırılıyor (maksimum {max_reviews} yorum için)...")
        
        # Önce "Daha fazla yorum göster" butonunu kontrol et ve tıkla
        try:
            load_more_buttons = driver.find_elements(By.XPATH, "//button[contains(text(), 'Daha fazla')] | //button[contains(text(), 'daha fazla')] | //button[contains(@class, 'load-more')] | //a[contains(text(), 'Daha fazla')]")
            if load_more_buttons:
                print(f"DEBUG: 'Daha fazla yorum' butonu bulundu, tıklanıyor...")
                load_more_buttons[0].click()
                time.sleep(2)
        except:
            pass
        
        # İlk scroll'lar - sadece ilk birkaç yorumu yüklemek için
        scroll_positions = [300, 600, 900, 1200, 1500]
        if max_reviews > 10:
            scroll_positions.extend([1800, 2100])
        if max_reviews > 20:
            scroll_positions.extend([2400, 2700])
        
        for scroll_pos in scroll_positions:
            driver.execute_script(f"window.scrollTo(0, {scroll_pos});")
            time.sleep(1.5)
            # Her scroll'dan sonra yeterli container yüklendi mi kontrol et
            current_count = len(driver.find_elements(By.XPATH, "//div[@id='hermes-voltran-comments']/div/div[3]"))
            print(f"DEBUG: Scroll {scroll_pos}px sonrası {current_count} container")
            
            # Eğer yeterli yorum yüklendiyse dur
            if current_count >= max_reviews:
                print(f"DEBUG: ✅ Yeterli yorum yüklendi ({current_count} >= {max_reviews}), scroll durduruluyor")
                break
        
        # Eğer hala yeterli yorum yoksa, biraz daha scroll yap (ama çok fazla değil - timeout önleme)
        current_count = len(driver.find_elements(By.XPATH, "//div[@id='hermes-voltran-comments']/div/div[3]"))
        if current_count < max_reviews and max_reviews <= 30:
            print(f"DEBUG: Daha fazla yorum yüklemek için en alta scroll yapılıyor...")
            last_height = driver.execute_script("return document.body.scrollHeight")
            scroll_attempts = 0
            max_scrolls = 3  # Maksimum 3 kez scroll yap (timeout önleme - daha agresif)
            
            while scroll_attempts < max_scrolls and current_count < max_reviews:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    # Yükseklik değişmedi, "Daha fazla" butonunu tekrar dene
                    try:
                        load_more = driver.find_element(By.XPATH, "//button[contains(text(), 'Daha fazla')] | //button[contains(@class, 'load-more')]")
                        if load_more.is_displayed():
                            load_more.click()
                            time.sleep(2)
                    except:
                        pass
                last_height = new_height
                scroll_attempts += 1
                current_count = len(driver.find_elements(By.XPATH, "//div[@id='hermes-voltran-comments']/div/div[3]"))
                print(f"DEBUG: Scroll denemesi {scroll_attempts}: {current_count} container")
                if current_count >= max_reviews:
                    break
        
        time.sleep(2)  # Yorumların yüklenmesi için kısa bekleme
        
        # Tüm yorum container'larını bul - div[@id='hermes-voltran-comments']/div[X]/div[3] yapısı
        # Kullanıcının verdiği xpath: //*[@id="hermes-voltran-comments"]/div[6]/div[3]
        # Ama div[6] değişebilir, tüm div'leri al
        
        # Önce tüm div'leri say
        all_main_divs = driver.find_elements(By.XPATH, "//div[@id='hermes-voltran-comments']/div")
        print(f"DEBUG: hermes-voltran-comments içinde {len(all_main_divs)} ana div var")
        
        # Her ana div'in içinde div[3] var mı kontrol et
        review_containers = []
        for div_idx, main_div in enumerate(all_main_divs):
            try:
                div3 = main_div.find_element(By.XPATH, "./div[3]")
                review_containers.append(div3)
                if len(review_containers) <= 5:  # İlk 5'i göster
                    print(f"DEBUG: ✅ div[{div_idx+1}] içinde div[3] bulundu")
            except:
                pass
        
        print(f"DEBUG: İlk deneme ile {len(review_containers)} container bulundu")
        
        # Eğer hala bulunamadıysa, eski yöntemi kullan
        if not review_containers:
        review_containers = driver.find_elements(By.XPATH, "//div[@id='hermes-voltran-comments']/div/div[3]")
            print(f"DEBUG: Eski yöntem ile {len(review_containers)} container bulundu")
        
        # Eğer bulunamadıysa, daha geniş bir arama yap
        if not review_containers or len(review_containers) == 0:
            print("DEBUG: div[3] ile bulunamadı, tüm div yapılarını kontrol ediyoruz...")
            # Tüm div yapılarını kontrol et
            all_divs = driver.find_elements(By.XPATH, "//div[@id='hermes-voltran-comments']/div")
            print(f"DEBUG: hermes-voltran-comments içinde {len(all_divs)} div bulundu")
            
            # Her div'in içinde div[3] olup olmadığını kontrol et
            for div_idx, div in enumerate(all_divs[:20]):  # İlk 20 div'i kontrol et
                try:
                    sub_divs = div.find_elements(By.XPATH, "./div[3]")
                    if sub_divs:
                        review_containers.append(sub_divs[0])
                        print(f"DEBUG: div[{div_idx+1}] içinde div[3] bulundu")
                except:
                    pass
        
        # Alternatif: class ile ara
        if not review_containers or len(review_containers) == 0:
            print("DEBUG: Class ile arama yapılıyor...")
            review_containers = driver.find_elements(By.XPATH, "//div[@id='hermes-voltran-comments']//div[contains(@class, 'hermes-ReviewCard-module-KaU17BbDowCWcTZ9zzxw')]")
            print(f"DEBUG: Class ile {len(review_containers)} container bulundu")
        
        if not review_containers or len(review_containers) == 0:
            review_containers = driver.find_elements(By.XPATH, "//div[@id='hermes-voltran-comments']//div[contains(@class, 'hermes-ReviewCard-module')]")
            print(f"DEBUG: Genel class ile {len(review_containers)} container bulundu")
        
        # Son çare: Tüm yorum benzeri yapıları bul
        if not review_containers or len(review_containers) == 0:
            print("DEBUG: Son çare yöntemi - tüm yorum benzeri yapılar aranıyor...")
            review_containers = driver.find_elements(By.XPATH, "//div[@id='hermes-voltran-comments']//div[contains(@class, 'review') or contains(@class, 'comment') or contains(@class, 'Review')]")
            print(f"DEBUG: Son çare yöntemi ile {len(review_containers)} container bulundu")
        
        print(f"DEBUG: Toplam {len(review_containers)} yorum container bulundu")
        
        # Eğer container bulunamadıysa, sayfanın HTML yapısını kontrol et
        if not review_containers or len(review_containers) == 0:
            print("DEBUG: ⚠️ HİÇ CONTAINER BULUNAMADI!")
            print("DEBUG: Sayfanın HTML yapısını kontrol ediliyor...")
            try:
                # hermes-voltran-comments var mı?
                main_container = driver.find_element(By.XPATH, "//div[@id='hermes-voltran-comments']")
                print("DEBUG: ✅ hermes-voltran-comments container VAR")
                
                # İçindeki div'leri say
                all_divs = driver.find_elements(By.XPATH, "//div[@id='hermes-voltran-comments']/div")
                print(f"DEBUG: hermes-voltran-comments içinde {len(all_divs)} ana div var")
                
                # İlk birkaç div'in yapısını göster
                for idx, div in enumerate(all_divs[:5]):
                    try:
                        sub_divs = div.find_elements(By.XPATH, "./div")
                        print(f"DEBUG: div[{idx+1}] içinde {len(sub_divs)} alt div var")
                        if len(sub_divs) >= 3:
                            print(f"DEBUG: ✅ div[{idx+1}] içinde div[3] VAR - bu yorum container olabilir!")
                    except:
                        pass
            except Exception as debug_error:
                print(f"DEBUG: ❌ hermes-voltran-comments container BULUNAMADI: {debug_error}")
                print(f"DEBUG: Mevcut URL: {driver.current_url}")
                return reviews_list
        
        if len(review_containers) == 0:
            print("DEBUG: ❌ Container bulunamadı, yorumlar çekilemiyor!")
            return reviews_list
        
        print(f"DEBUG: ✅ {len(review_containers)} container bulundu, yorumlar çekiliyor...")
        
        for i, container in enumerate(review_containers[:max_reviews]):
            try:
                print(f"\nDEBUG: ===== YORUM {i+1} İŞLENİYOR =====")
                review_data = {}
                
                # Container'ın yapısını kontrol et
                try:
                    container_html = container.get_attribute('outerHTML')[:200]  # İlk 200 karakter
                    print(f"DEBUG: Container HTML başlangıcı: {container_html}...")
                except:
                    pass
                
                # Yorum metnini çek - KULLANICININ VERDİĞİ DOĞRU XPath'i kullan
                # Tam xpath: //*[@id="hermes-voltran-comments"]/div[6]/div[3]/div/div[2]/div[2]/div[2]
                # Container içinde: .//div[2]/div[2]/div[2]
                
                review_data["text"] = None
                
                # Önce container içindeki div yapısını kontrol et
                try:
                    container_divs = container.find_elements(By.XPATH, "./div")
                    print(f"DEBUG: Container içinde {len(container_divs)} ana div var")
                    if len(container_divs) >= 2:
                        print(f"DEBUG: ✅ div[2] VAR")
                        div2 = container_divs[1]  # div[2] (index 1)
                        div2_divs = div2.find_elements(By.XPATH, "./div")
                        print(f"DEBUG: div[2] içinde {len(div2_divs)} alt div var")
                        if len(div2_divs) >= 2:
                            print(f"DEBUG: ✅ div[2]/div[2] VAR")
                            div2_2 = div2_divs[1]  # div[2]/div[2]
                            div2_2_divs = div2_2.find_elements(By.XPATH, "./div")
                            print(f"DEBUG: div[2]/div[2] içinde {len(div2_2_divs)} alt div var")
                            if len(div2_2_divs) >= 2:
                                print(f"DEBUG: ✅ div[2]/div[2]/div[2] VAR - yorum metni burada olmalı!")
                except Exception as structure_error:
                    print(f"DEBUG: Container yapısı kontrol edilirken hata: {structure_error}")
                
                # Yöntem 1: Kullanıcının verdiği tam XPath - div[2]/div[2]/div[2]
                try:
                    text_container = container.find_element(By.XPATH, ".//div[2]/div[2]/div[2]")
                    review_data["text"] = text_container.text.strip()
                    if review_data["text"] and len(review_data["text"]) >= 10:
                        print(f"DEBUG: ✅ Yorum {i+1} metni (XPath: div[2]/div[2]/div[2]) çekildi: {len(review_data['text'])} karakter")
                        print(f"DEBUG: Yorum metni önizleme: {review_data['text'][:100]}...")
                    else:
                        print(f"DEBUG: ⚠️ Yorum {i+1} metni çok kısa veya boş: '{review_data['text']}'")
                except Exception as e1:
                    print(f"DEBUG: ❌ Yorum {i+1} için div[2]/div[2]/div[2] bulunamadı: {e1}")
                
                # Yöntem 2: İçindeki elemanları ara (eğer text_container boşsa)
                if not review_data["text"] or len(review_data.get("text", "") or "") < 10:
                    try:
                        text_container = container.find_element(By.XPATH, ".//div[2]/div[2]/div[2]")
                        inner_elems = text_container.find_elements(By.XPATH, ".//span | .//p | .//div")
                        if inner_elems:
                            text_elem = max(inner_elems, key=lambda x: len(x.text.strip()) if x.text else 0)
                            if text_elem.text and len(text_elem.text.strip()) >= 10:
                        review_data["text"] = text_elem.text.strip()
                                print(f"DEBUG: ✅ Yorum {i+1} metni (iç elemanlardan) çekildi: {len(review_data['text'])} karakter")
                    except:
                        pass
                
                # Yöntem 3: Alternatif yollar (eğer hala bulunamadıysa)
                if not review_data["text"] or len(review_data.get("text", "") or "") < 10:
                    try:
                        # div[2]/div[2] içinde herhangi bir uzun metin
                        text_elem = container.find_element(By.XPATH, ".//div[2]/div[2]//span | .//div[2]/div[2]//p | .//div[2]/div[2]//div")
                        if text_elem.text and len(text_elem.text.strip()) >= 10:
                            review_data["text"] = text_elem.text.strip()
                            print(f"DEBUG: ✅ Yorum {i+1} metni (alternatif) çekildi: {len(review_data['text'])} karakter")
                        except:
                        pass
                
                if not review_data["text"] or len(review_data.get("text", "") or "") < 10:
                    print(f"DEBUG: ❌ Yorum {i+1} için metin çekilemedi")
                            review_data["text"] = None
                
                # Yorum puanını çek - KULLANICININ VERDİĞİ DOĞRU XPath'i kullan
                # Tüm yıldızlar: //*[@id="hermes-voltran-comments"]/div[6]/div[3]/div/div[2]/div[2]/div[1]/div[2]/div/span/div
                # Tek yıldız: //*[@id="hermes-voltran-comments"]/div[6]/div[3]/div/div[2]/div[2]/div[1]/div[2]/div/span/div/div[1]
                # Container içinde: .//div[2]/div[2]/div[1]/div[2]/div/span/div
                try:
                    rating = None
                    
                    # Yöntem 1: Tüm yıldız container'ını bul ve dolu yıldızları say
                    try:
                        stars_container = container.find_element(By.XPATH, ".//div[2]/div[2]/div[1]/div[2]/div/span/div")
                        # Container içindeki tüm yıldız div'lerini bul
                        stars = stars_container.find_elements(By.XPATH, ".//div")
                        print(f"DEBUG: Yorum {i+1} için {len(stars)} yıldız div'i bulundu")
                        
                        # Dolu/aktif yıldızları say - DAHA DETAYLI KONTROL
                        active_count = 0
                        for star_idx, star in enumerate(stars):
                            # Yıldızın dolu olup olmadığını kontrol et
                            class_attr = star.get_attribute("class") or ""
                            style_attr = star.get_attribute("style") or ""
                            fill_attr = star.get_attribute("fill") or ""
                            aria_label = star.get_attribute("aria-label") or ""
                            
                            # SVG içindeki path'leri kontrol et (yıldızlar genelde SVG ile gösterilir)
                            svg_paths = star.find_elements(By.XPATH, ".//path | .//svg//path")
                            has_fill = False
                            for path in svg_paths:
                                path_fill = path.get_attribute("fill") or ""
                                path_style = path.get_attribute("style") or ""
                                if path_fill and path_fill.lower() not in ["none", "transparent", ""]:
                                    has_fill = True
                                    break
                                if "fill" in path_style.lower() and "none" not in path_style.lower():
                                    has_fill = True
                                    break
                            
                            # Yıldızın görünürlüğünü kontrol et (display: none olmamalı)
                            is_visible = True
                            if "display: none" in style_attr.lower() or "visibility: hidden" in style_attr.lower():
                                is_visible = False
                            
                            # Dolu yıldız işaretleri - daha kapsamlı kontrol
                            is_filled = (
                                any(keyword in class_attr.lower() for keyword in ["fill", "active", "selected", "checked", "on", "full", "filled", "star-filled"]) or
                                any(keyword in style_attr.lower() for keyword in ["color", "fill", "opacity: 1", "opacity:1", "rgb", "#", "yellow", "orange", "gold", "ffa500", "ffd700"]) or
                                (fill_attr and fill_attr.lower() not in ["none", "transparent", ""]) or
                                has_fill or
                                "dolu" in aria_label.lower() or "filled" in aria_label.lower() or "full" in aria_label.lower()
                            )
                            
                            # Eğer yukarıdaki kontroller başarısızsa, yıldızın içeriğini kontrol et
                            if not is_filled and is_visible:
                                star_html = star.get_attribute("outerHTML") or ""
                                star_text = star.text.strip()
                                # Eğer yıldız içinde "★" veya "⭐" gibi karakterler varsa ve görünürse dolu say
                                if ("★" in star_html or "⭐" in star_html or "★" in star_text or "⭐" in star_text) and len(star_html) > 10:
                                    is_filled = True
                            
                            if is_filled and is_visible:
                                active_count += 1
                                print(f"DEBUG: Yıldız {star_idx+1} dolu olarak işaretlendi (class: {class_attr[:30]}, fill: {fill_attr[:20]}, has_fill: {has_fill})")
                            else:
                                print(f"DEBUG: Yıldız {star_idx+1} boş (class: {class_attr[:30]}, style: {style_attr[:30]}, visible: {is_visible})")
                        
                        if active_count > 0 and active_count <= 5:
                            rating = active_count
                            print(f"DEBUG: ✅ Yorum {i+1} puanı (yıldız sayısı): {rating}")
                        else:
                            print(f"DEBUG: ⚠️ Yorum {i+1} için {active_count} dolu yıldız bulundu (geçersiz, 1-5 arası olmalı)")
                    except Exception as stars_error:
                        print(f"DEBUG: Yıldız container bulunamadı: {stars_error}")
                    
                    # Yöntem 2: Tek yıldız XPath'ini kullan (eğer yöntem 1 başarısızsa)
                    if not rating:
                        try:
                            # İlk yıldızı bul ve kaç tane dolu olduğunu say
                            first_star = container.find_element(By.XPATH, ".//div[2]/div[2]/div[1]/div[2]/div/span/div/div[1]")
                            stars_container = container.find_element(By.XPATH, ".//div[2]/div[2]/div[1]/div[2]/div/span/div")
                            all_stars = stars_container.find_elements(By.XPATH, ".//div")
                            
                            active_count = 0
                            for star in all_stars:
                                class_attr = star.get_attribute("class") or ""
                                style_attr = star.get_attribute("style") or ""
                                if (any(k in class_attr.lower() for k in ["fill", "active", "selected"]) or
                                    any(k in style_attr.lower() for k in ["color", "fill"])):
                                    active_count += 1
                            
                            if active_count > 0 and active_count <= 5:
                                rating = active_count
                                print(f"DEBUG: ✅ Yorum {i+1} puanı (tek yıldız yöntemi): {rating}")
                        except:
                            pass
                    
                    # Yöntem 3: Text veya aria-label'dan puan çek
                    if not rating:
                        try:
                            rating_elem = container.find_element(By.XPATH, ".//div[2]/div[2]/div[1]/div[2]/div/span/div")
                            rating_text = rating_elem.text.strip()
                            rating_match = re.search(r'(\d+)', rating_text)
                            if rating_match:
                                rating_val = int(rating_match.group(1))
                                if 1 <= rating_val <= 5:
                                    rating = rating_val
                                    print(f"DEBUG: ✅ Yorum {i+1} puanı (text'ten): {rating}")
                        except:
                            pass
                    
                    review_data["rating"] = rating
                    if not rating:
                        print(f"DEBUG: ❌ Yorum {i+1} puanı çekilemedi")
                        
                except Exception as e:
                    print(f"DEBUG: Yorum {i+1} puanı çekilirken hata: {e}")
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
                    print(f"DEBUG: ✅ Yorum {i+1} listeye eklendi (metin: {len(review_data['text'])} karakter, puan: {review_data.get('rating', 'yok')})")
                else:
                    print(f"DEBUG: ❌ Yorum {i+1} listeye EKLENMEDİ - metin yok veya çok kısa")
                    if review_data.get("text"):
                        print(f"DEBUG: Metin uzunluğu: {len(review_data['text'])} karakter")
                    else:
                        print(f"DEBUG: Metin: None")
                    
            except Exception as e:
                print(f"DEBUG: ❌ Yorum {i+1} işlenirken hata: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        print(f"\nDEBUG: ===== SONUÇ =====")
        print(f"DEBUG: Toplam {len(reviews_list)} yorum metni başarıyla çekildi")
        if len(reviews_list) == 0:
            print("DEBUG: ⚠️ HİÇ YORUM ÇEKİLEMEDİ!")
            print("DEBUG: Lütfen console çıktısındaki hata mesajlarını kontrol edin")
        
    except Exception as e:
        print(f"DEBUG HATA: Yorumlar çekilirken hata: {e}")
    
    return reviews_list


def deep_scrape_hepsiburada(driver, hb_url):
    """Hepsiburada sayfasındaki puan, yorum sayısı ve yorum metinlerini çeker."""
    data = {"rating": None, "reviews": None, "reviews_list": [], "high_rating_count": None, "low_rating_count": None}

    try:
        driver.get(hb_url)
        time.sleep(random.uniform(5, 8))  # bot görünmemek için kısa bekleme

        wait = WebDriverWait(driver, 30)

        review_element = wait.until(
            EC.presence_of_element_located((By.XPATH, REVIEW_XPATH))
        )
        reviews_text = review_element.text
        data["reviews"] = int(re.sub(r"[^\d]", "", reviews_text))

        rating_element = wait.until(
            EC.presence_of_element_located((By.XPATH, RATING_XPATH))
        )
        rating_text = rating_element.text.replace(",", ".")
        data["rating"] = float(rating_text)

        print(f"DEBUG: HB Puan/Yorum çekimi başarılı. Puan: {data['rating']}, Yorum sayısı: {data['reviews']}")
        
        # Yorumlar linkine tıkla ve yorum metinlerini çek
        try:
            review_link = review_element
            if review_link.tag_name == "a":
                review_href = review_link.get_attribute("href")
                if review_href:
                    print(f"DEBUG: Yorumlar sayfasına gidiliyor: {review_href}")
                    driver.get(review_href)
                    time.sleep(random.uniform(3, 5))
                    
                    # Yorum sayısına göre max_reviews ayarla (performans için - daha agresif limit)
                    total_reviews = data.get("reviews", 0)
                    if total_reviews > 1000:
                        max_reviews_to_scrape = 20  # Çok fazla yorum varsa sadece 20 çek (timeout önleme)
                        print(f"DEBUG: ⚠️ {total_reviews} yorum var, performans için sadece {max_reviews_to_scrape} yorum çekilecek")
                    elif total_reviews > 100:
                        max_reviews_to_scrape = 30  # Orta seviye için 30
                        print(f"DEBUG: {total_reviews} yorum var, {max_reviews_to_scrape} yorum çekilecek")
                    else:
                        max_reviews_to_scrape = 15  # Az yorum varsa 15
                        print(f"DEBUG: {total_reviews} yorum var, {max_reviews_to_scrape} yorum çekilecek")
                    
                    # Yüksek puanlı (4-5 yıldız) ve düşük puanlı (1-2 yıldız) yorum sayılarını çek
                    try:
                        wait_reviews = WebDriverWait(driver, 15)
                        
                        # Yıldız filtrelerini bul - XPath ile
                        # Hepsiburada'da genellikle yıldız filtreleri şu şekilde olur:
                        # //div[contains(@class, 'rating-filter')] veya benzeri
                        # Her yıldız için: //button[contains(@aria-label, '5 yıldız')] veya //div[contains(text(), '5 yıldız')]
                        
                        high_rating_count = 0  # 4-5 yıldız toplam
                        low_rating_count = 0   # 1-2 yıldız toplam
                        
                        # 5 yıldız yorum sayısı
                        try:
                            # XPath ile 5 yıldız butonu/div'i bul
                            star5_elem = driver.find_element(By.XPATH, "//button[contains(@aria-label, '5 yıldız')] | //div[contains(@aria-label, '5 yıldız')] | //span[contains(text(), '5 yıldız')]/following-sibling::span | //button[contains(text(), '5') and contains(@class, 'rating')]")
                            star5_text = star5_elem.text.strip()
                            star5_match = re.search(r'\((\d+)\)', star5_text)
                            if star5_match:
                                star5_count = int(star5_match.group(1))
                                high_rating_count += star5_count
                                print(f"DEBUG: 5 yıldız yorum sayısı: {star5_count}")
                        except:
                            # Class ile dene
                            try:
                                star5_elems = driver.find_elements(By.XPATH, "//div[contains(@class, 'rating')]//button[contains(@class, '5')] | //div[contains(@class, 'filter')]//button[contains(., '5')]")
                                for elem in star5_elems:
                                    text = elem.text.strip()
                                    match = re.search(r'\((\d+)\)', text)
                                    if match:
                                        high_rating_count += int(match.group(1))
                                        print(f"DEBUG: 5 yıldız yorum sayısı (class): {int(match.group(1))}")
                                        break
                            except:
                                pass
                        
                        # 4 yıldız yorum sayısı
                        try:
                            star4_elem = driver.find_element(By.XPATH, "//button[contains(@aria-label, '4 yıldız')] | //div[contains(@aria-label, '4 yıldız')] | //span[contains(text(), '4 yıldız')]/following-sibling::span | //button[contains(text(), '4') and contains(@class, 'rating')]")
                            star4_text = star4_elem.text.strip()
                            star4_match = re.search(r'\((\d+)\)', star4_text)
                            if star4_match:
                                star4_count = int(star4_match.group(1))
                                high_rating_count += star4_count
                                print(f"DEBUG: 4 yıldız yorum sayısı: {star4_count}")
                        except:
                            # Class ile dene
                            try:
                                star4_elems = driver.find_elements(By.XPATH, "//div[contains(@class, 'rating')]//button[contains(@class, '4')] | //div[contains(@class, 'filter')]//button[contains(., '4')]")
                                for elem in star4_elems:
                                    text = elem.text.strip()
                                    match = re.search(r'\((\d+)\)', text)
                                    if match:
                                        high_rating_count += int(match.group(1))
                                        print(f"DEBUG: 4 yıldız yorum sayısı (class): {int(match.group(1))}")
                                        break
                            except:
                                pass
                        
                        # 2 yıldız yorum sayısı
                        try:
                            star2_elem = driver.find_element(By.XPATH, "//button[contains(@aria-label, '2 yıldız')] | //div[contains(@aria-label, '2 yıldız')] | //span[contains(text(), '2 yıldız')]/following-sibling::span | //button[contains(text(), '2') and contains(@class, 'rating')]")
                            star2_text = star2_elem.text.strip()
                            star2_match = re.search(r'\((\d+)\)', star2_text)
                            if star2_match:
                                star2_count = int(star2_match.group(1))
                                low_rating_count += star2_count
                                print(f"DEBUG: 2 yıldız yorum sayısı: {star2_count}")
                        except:
                            # Class ile dene
                            try:
                                star2_elems = driver.find_elements(By.XPATH, "//div[contains(@class, 'rating')]//button[contains(@class, '2')] | //div[contains(@class, 'filter')]//button[contains(., '2')]")
                                for elem in star2_elems:
                                    text = elem.text.strip()
                                    match = re.search(r'\((\d+)\)', text)
                                    if match:
                                        low_rating_count += int(match.group(1))
                                        print(f"DEBUG: 2 yıldız yorum sayısı (class): {int(match.group(1))}")
                                        break
                            except:
                                pass
                        
                        # 1 yıldız yorum sayısı
                        try:
                            star1_elem = driver.find_element(By.XPATH, "//button[contains(@aria-label, '1 yıldız')] | //div[contains(@aria-label, '1 yıldız')] | //span[contains(text(), '1 yıldız')]/following-sibling::span | //button[contains(text(), '1') and contains(@class, 'rating')]")
                            star1_text = star1_elem.text.strip()
                            star1_match = re.search(r'\((\d+)\)', star1_text)
                            if star1_match:
                                star1_count = int(star1_match.group(1))
                                low_rating_count += star1_count
                                print(f"DEBUG: 1 yıldız yorum sayısı: {star1_count}")
                        except:
                            # Class ile dene
                            try:
                                star1_elems = driver.find_elements(By.XPATH, "//div[contains(@class, 'rating')]//button[contains(@class, '1')] | //div[contains(@class, 'filter')]//button[contains(., '1')]")
                                for elem in star1_elems:
                                    text = elem.text.strip()
                                    match = re.search(r'\((\d+)\)', text)
                                    if match:
                                        low_rating_count += int(match.group(1))
                                        print(f"DEBUG: 1 yıldız yorum sayısı (class): {int(match.group(1))}")
                                        break
                            except:
                                pass
                        
                        # Alternatif yöntem: Tüm rating filter butonlarını bul ve sayıları topla
                        if high_rating_count == 0 and low_rating_count == 0:
                            try:
                                # Tüm rating filter butonlarını bul
                                rating_filters = driver.find_elements(By.XPATH, "//button[contains(@class, 'rating')] | //div[contains(@class, 'rating-filter')]//button | //div[contains(@class, 'filter')]//button[contains(., 'yıldız')]")
                                
                                for filter_elem in rating_filters:
                                    text = filter_elem.text.strip()
                                    # Yıldız sayısını ve parantez içindeki sayıyı bul
                                    star_match = re.search(r'(\d+)\s*yıldız', text, re.IGNORECASE)
                                    count_match = re.search(r'\((\d+)\)', text)
                                    
                                    if star_match and count_match:
                                        star_num = int(star_match.group(1))
                                        count = int(count_match.group(1))
                                        
                                        if star_num >= 4:
                                            high_rating_count += count
                                        elif star_num <= 2:
                                            low_rating_count += count
                                        
                                        print(f"DEBUG: {star_num} yıldız: {count} yorum")
                            except Exception as e:
                                print(f"DEBUG: Alternatif yöntem ile yıldız sayıları çekilemedi: {e}")
                        
                        data["high_rating_count"] = high_rating_count if high_rating_count > 0 else None
                        data["low_rating_count"] = low_rating_count if low_rating_count > 0 else None
                        
                        print(f"DEBUG: Yüksek puanlı (4-5) yorum sayısı: {data['high_rating_count']}, Düşük puanlı (1-2) yorum sayısı: {data['low_rating_count']}")
                        
                    except Exception as e:
                        print(f"DEBUG: Yıldız bazlı yorum sayıları çekilemedi (opsiyonel): {e}")
                    
                    # Yorum metinlerini çek (performans için limitli)
                    data["reviews_list"] = scrape_hepsiburada_reviews(driver, max_reviews=max_reviews_to_scrape)
                    
                    # Ana sayfaya geri dön (gerekirse)
                    # driver.back()
            else:
                # Eğer link değilse, yorumlar zaten bu sayfada olabilir
                print("DEBUG: Yorumlar linki bulunamadı, mevcut sayfadan çekilmeye çalışılıyor")
                # Güvenli limit
                max_reviews_to_scrape = 20
                data["reviews_list"] = scrape_hepsiburada_reviews(driver, max_reviews=max_reviews_to_scrape)
        except Exception as e:
            print(f"DEBUG: Yorum metinleri çekilemedi (opsiyonel): {e}")
            # Yorum metinleri çekilemese bile devam et

    except TimeoutException:
        print("DEBUG HATA: Hepsiburada elementleri 30 saniyede yüklenmedi (Timeout).")
    except NoSuchElementException:
        print("DEBUG HATA: Hepsiburada XPath'leri bulunamadı.")
    except Exception as e:
        print(f"DEBUG KRİTİK HATA: Hepsiburada çekimi sırasında bilinmeyen hata: {e}")

    return data


def resolve_hepsiburada_url(akakce_link):
    """
    Akakçe takip linkini açıp gerçek Hepsiburada URL'sini döndürür.
    Akakçe bazen yeni sekmeye yönlendiriyor veya geç redirect yapıyor.
    """
    def _build_redirect_url(link: str) -> str:
        """Hash içindeki f= parametresini açıp gerçek /r/?... linkini kurar."""
        parsed = urlparse(link)
        # Parametreler fragmente gömülü olduğu için hem query hem fragment'e bak
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

        # 1) Akakçe bazen yeni sekme açıyor, bunu yakala
        WebDriverWait(driver, 15).until(lambda d: len(d.window_handles) >= 1)
        if len(driver.window_handles) > 1:
            driver.switch_to.window(driver.window_handles[-1])

        # 2) Redirect tamamlanana kadar bekle
        WebDriverWait(driver, 40).until(
            lambda d: ("hepsiburada.com" in d.current_url) or ("akakce.com" not in d.current_url)
        )
        time.sleep(random.uniform(2, 4))

        final_url = driver.current_url

        # Eğer hâlâ Akakçe içindeysek, sayfadaki HB linkini doğrudan yakalamayı dene
        if "hepsiburada.com" not in final_url and "akakce.com" in final_url:
            try:
                hb_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='hepsiburada.com']")
                if hb_links:
                    hb_href = hb_links[0].get_attribute("href")
                    print(f"DEBUG: Sayfada HB linki bulundu, direkt gidiliyor: {hb_href}")
                    driver.get(hb_href)
                    WebDriverWait(driver, 20).until(lambda d: "hepsiburada.com" in d.current_url)
                    final_url = driver.current_url
            except Exception as e:
                print(f"DEBUG HATA: Sayfadan HB linki çekilemedi: {e}")

        if "hepsiburada.com" not in final_url:
            print(f"DEBUG HATA: Yönlendirme HB'ye gitmedi. Nihai URL: {final_url}")
            driver.quit()
            return None, None

        print(f"DEBUG: Nihai HB URL'si yakalandı: {final_url}")
        return driver, final_url

    except Exception as e:
        print(f"DEBUG HATA: Yönlendirme yakalanamadı: {e}")
        driver.quit()
        return None, None

# ----------------- ANA SCRAPER FONKSİYONU -----------------

def scrape_hepsiburada_product(product_config):
    """Akakçe listesinden Hepsiburada satıcısını bulup puan/yorum çeker."""
    client, DRIVER, scraped_data = None, None, []

    try:
        client = MongoClient(MONGO_DB_URL, serverSelectionTimeoutMS=5000)
        db = client[DB_NAME]
        collection = db[product_config["collection"]]
        DRIVER = initialize_driver()
        print(f"DEBUG: Akakçe'den veri çekiliyor... Ürün: {product_config['product_name']}")
        product_name, base_data = scrape_akakce_base_data(DRIVER, product_config["url"])

        print(f"DEBUG: Akakçe'den toplam {len(base_data)} satıcı verisi çekildi.")
        
        # Hangi satıcılar geldiğini göster
        print("DEBUG: Bulunan satıcılar:")
        for idx, item in enumerate(base_data, 1):
            vendor_name = item['vendor_name']
            link = item.get('link', '')
            vendor_lower = vendor_name.lower()
            link_lower = link.lower()
            is_hb = ("hepsiburada" in vendor_lower or ("hepsi" in vendor_lower and "burada" in vendor_lower) or 
                    "hepsiburada" in link_lower or "hepsiburada.com" in link_lower)
            marker = "✅ HB" if is_hb else "❌"
            print(f"DEBUG:   {idx}. {marker} Vendor: '{vendor_name}' | Link: {link[:70]}...")
            if is_hb:
                print(f"DEBUG:      -> Bu satıcı Hepsiburada olarak algılandı!")
        
        DRIVER.quit()
        DRIVER = None
        print("DEBUG: Akakçe driver'ı kapatıldı.")

        hb_link_found = False

        for item in base_data:
            # Vendor name ve link kontrolü - daha esnek
            vendor_name = item["vendor_name"]
            vendor_name_lower = vendor_name.lower().strip()
            link = item.get("link", "").lower()
            
            # Hepsiburada kontrolü: vendor_name veya link'te "hepsiburada" olmalı
            is_hepsiburada = (
                "hepsiburada" in vendor_name_lower or
                ("hepsi" in vendor_name_lower and "burada" in vendor_name_lower) or
                "hepsiburada.com" in link or
                "hepsiburada" in link
            )
            
            if not is_hepsiburada:
                print(f"DEBUG: ⏭️  '{vendor_name}' Hepsiburada değil (vendor: '{vendor_name_lower}', link: '{link[:50]}...'), atlanıyor...")
                continue
            
            print(f"DEBUG: ✅ Hepsiburada satıcısı bulundu: '{vendor_name}' (link: '{item.get('link', '')[:80]}...')")

            hb_link_found = True
            full_akakce_link = item["link"]
            print(f"DEBUG: Hepsiburada satıcısı bulundu. Akakçe linki: {full_akakce_link}")

            hb_driver, final_hb_url = resolve_hepsiburada_url(full_akakce_link)
            if not hb_driver or not final_hb_url:
                print("DEBUG: HB yönlendirmesi alınamadı, satıcı atlandı.")
                continue

            vendor_details = deep_scrape_hepsiburada(hb_driver, final_hb_url)

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
                    "high_rating_count": vendor_details.get("high_rating_count"),
                    "low_rating_count": vendor_details.get("low_rating_count"),
                    "reviews_list": vendor_details.get("reviews_list", []),
                    "scrape_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
            )

            hb_driver.quit()
            print("DEBUG: HB driver kapatıldı.")

        if not hb_link_found and len(base_data) > 0:
            # Hangi satıcıların geldiğini göster (debug için)
            vendor_list = [item.get('vendor_name', 'Bilinmiyor') for item in base_data[:5]]
            return f"⚠️ HB SCRAPER: Hepsiburada satıcısı bulunamadı. Bulunan satıcılar: {', '.join(vendor_list)}"
        if not base_data:
            return "⚠️ HB SCRAPER: Akakçe'den satıcı verisi çekilemedi (satıcı listesi boş)."

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
                return f"✅ HB SCRAPER: {product_name} için {len(new_data)} yeni veri kaydedildi ({len(scraped_data) - len(new_data)} zaten kayıtlıydı)."
            else:
                return f"⚠️ HB SCRAPER: {product_name} için tüm veriler zaten kayıtlı, yeni kayıt eklenmedi."

        return f"⚠️ HB SCRAPER: {product_name} için Hepsiburada satıcı verisi çekilemedi."

    except Exception as e:
        return f"❌ KRİTİK HATA (HB Scraper): {e}"

    finally:
        if DRIVER:
            DRIVER.quit()
        if client:
            client.close()

# ----------------- SCRIPT GİRİŞ NOKTASI -----------------

if __name__ == "__main__":
    if len(sys.argv) > 1:
        result = None
        try:
            product_config = json.loads(sys.argv[1])
            result = scrape_hepsiburada_product(product_config)
            # Eğer result None ise, bir hata mesajı oluştur
            if result is None:
                result = "⚠️ HB SCRAPER: Fonksiyon None döndü (beklenmeyen durum)"
        except Exception as e:
            # Hata varsa sonuç mesajı oluştur
            import traceback
            try:
                result = f"❌ KRİTİK HATA (HB Scraper): {e}\n{traceback.format_exc()}"
            except UnicodeEncodeError:
                # Encoding hatası durumunda ASCII karakterler kullan
                result = f"KRITIK HATA (HB Scraper): {str(e)}\n{traceback.format_exc()}"
        
        # Sonuç mesajını mutlaka yazdır (stdout'a, DEBUG mesajlarından sonra)
        # result None olsa bile yazdır
        try:
            print("\n" + "="*50, flush=True)  # Ayırıcı
            if result:
                print(result, flush=True)
            else:
                print("⚠️ HB SCRAPER: Sonuç mesajı alınamadı (result=None)", flush=True)
            print("="*50 + "\n", flush=True)
        except UnicodeEncodeError:
            # Windows konsolu encoding hatası durumunda ASCII karakterler kullan
            safe_result = result.encode('ascii', 'ignore').decode('ascii') if result else "HB SCRAPER: Sonuc mesaji alinamadi"
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