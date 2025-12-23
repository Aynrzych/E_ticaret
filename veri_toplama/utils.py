# veri_toplama/utils.py

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager 
import re
import random
import time
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

# Bloklanmaya karşı rastgele User-Agent listesi
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.3 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/100.0.1185.39 Safari/537.36"
]

HEADLESS = True  # Çoklu ürün (ör. 100+) için kaynak tüketimini azaltır


def initialize_driver():
    """Yeni bir tarayıcı oturumu başlatır."""
    OPTIONS = Options()

    if HEADLESS:
        OPTIONS.add_argument("--headless=new")
    OPTIONS.add_argument("--disable-blink-features=AutomationControlled")
    OPTIONS.add_argument("--no-sandbox")
    OPTIONS.add_argument("--disable-dev-shm-usage")
    OPTIONS.add_argument('--disable-gpu')
    OPTIONS.add_argument('--log-level=3')

    OPTIONS.add_experimental_option("excludeSwitches", ["enable-automation"])
    OPTIONS.add_experimental_option('useAutomationExtension', False)

    OPTIONS.add_argument(f'user-agent={random.choice(USER_AGENTS)}') 
    
    OPTIONS.add_argument("lang=tr-TR")
    
    prefs = {"profile.managed_default_content_settings.images": 2}
    OPTIONS.add_experimental_option("prefs", prefs)
    
    SERVICE = Service(ChromeDriverManager().install()) 
    driver= webdriver.Chrome(service=SERVICE, options=OPTIONS)
    

    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': '''
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['tr-TR', 'tr']
            });
            window.chrome = {
                runtime: {},
            };
        '''
    })
    
    driver.set_window_size(1200, 800) 
    return driver

def clean_and_parse_price(price_text):
    """Fiyat metnini temizler ve float'a çevirir."""
    price_text = re.sub(r'<[^>]+>', '', price_text).strip()
    price_text = price_text.replace('TL', '').replace(' ', '').replace('.', '').replace(',', '.')
    try:
        return float(price_text)
    except ValueError:
        return 0.0
        
def scrape_akakce_base_data(driver, akakce_url):
    """Akakçe'den ürünün adını ve satıcı listesinin temel verilerini çeker."""
    driver.get(akakce_url)
    
    wait = WebDriverWait(driver, 30)
    wait.until(EC.presence_of_element_located((By.ID, "PL")))
    time.sleep(random.uniform(3, 5)) 

    soup = BeautifulSoup(driver.page_source, 'html.parser')
    seller_list = soup.find('ul', id='PL')
    
    if not seller_list:
        return "Satıcı listesi bulunamadı", []
        
    product_name_element = soup.find('div', class_='pdt_v8').find('h1')
    product_name = product_name_element.text.strip() if product_name_element else "Başlık Bulunamadı"
    rows = seller_list.find_all('li')
    
    base_data = []
    for row in rows[:10]: # İlk 10 satıcıyı al
        try:
            price = clean_and_parse_price(str(row.find('span', class_='pt_v8')))
            vendor_element = row.find('span', class_='v_v8')
            if not vendor_element:
                continue
                
            # vendor_name'i img alt text'inden al
            img_element = vendor_element.find('img')
            vendor_name = img_element['alt'].replace("/","").strip() if img_element and img_element.get('alt') else "Bilinmiyor"
            
            # seller_nickname'i daha güvenilir şekilde çıkar
            # vendor_element içindeki tüm text'i al, img alt text'ini çıkar
            from bs4 import NavigableString
            
            vendor_nickname = ""
            
            if img_element:
                # vendor_element içindeki tüm child'ları iterate et
                nickname_parts = []
                for child in vendor_element.children:
                    # NavigableString (text node) ise
                    if isinstance(child, NavigableString):
                        text = str(child).strip()
                        if text:
                            nickname_parts.append(text)
                    # Tag ise ve img değilse
                    elif hasattr(child, 'name') and child.name != 'img':
                        text = child.get_text(separator=' ', strip=True)
                        if text:
                            nickname_parts.append(text)
                
                vendor_nickname = ' '.join(nickname_parts).strip()
                
                # Eğer hala boşsa veya sadece boşluk varsa, alternatif yöntem
                if not vendor_nickname:
                    # Tüm text'i al ve vendor_name'i baştan çıkar
                    full_text = vendor_element.get_text(separator=' ', strip=True)
                    # vendor_name'i full_text'ten çıkar
                    if full_text.startswith(vendor_name):
                        vendor_nickname = full_text[len(vendor_name):].strip()
                    elif vendor_name in full_text:
                        # vendor_name text içinde başka bir yerdeyse, onu çıkar
                        vendor_nickname = full_text.replace(vendor_name, "", 1).strip()
                    else:
                        # vendor_name text içinde değilse, tüm text'i al
                        vendor_nickname = full_text.strip()
            else:
                # img yoksa tüm text'i nickname olarak al
                vendor_nickname = vendor_element.get_text(separator=' ', strip=True)
            
            # Temizleme: Eğer nickname vendor_name ile aynıysa boşalt
            # "H" gibi kısa nickname'ler geçerli, sadece vendor_name ile aynıysa boşalt
            if vendor_nickname == vendor_name:
                vendor_nickname = ""
            
            link_element = row.find('a')
            link = link_element.get('href') if link_element else "#"
            if not link.startswith('https'):
                full_link = "https://www.akakce.com" + link
            else:
                full_link = link   

            if price > 0:
                base_data.append({
                    "price": price,
                    "vendor_name": vendor_name,
                    "seller_nickname": vendor_nickname,
                    "link": full_link
                })
        except Exception as e:
            print(f"DEBUG: Satıcı verisi çıkarılırken hata: {e}")
            import traceback
            traceback.print_exc()
            continue
      #  print("DEBUG BASE DATA:", base_data)
            
    return product_name, base_data