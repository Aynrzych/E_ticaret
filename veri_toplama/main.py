# veri_toplama/main.py

import json
from multiprocessing import Pool, cpu_count
import subprocess
import os
import sys
from utils import initialize_driver, scrape_akakce_base_data

# ----------------- YARDIMCI FONKSİYONLAR -----------------

# Tüm desteklenen sitelerin listesi
ALL_SITES = ["hepsiburada", "trendyol", "n11", "pttavm", "pazarama"]

def identify_site(url):
    """Akakçe linkinin yönlendirdiği pazar yerini belirler."""
    url = url.lower()
    if "hepsiburada.com" in url :
        return "hepsiburada"
    elif "trendyol.com" in url:
        return "trendyol"
    elif "n11.com" in url:
        return "n11"
    elif "pttavm.com" in url:
        return "pttavm"
    elif "pazarama.com" in url:
        return "pazarama"
    return "unknown"

def expand_product_tasks(product_config, check_availability=True):
    """
    Bir ürün config'ini tüm siteler için task'lara genişletir.
    Eğer 'target_sites' belirtilmişse sadece onları kullanır,
    yoksa tüm siteleri çeker.
    
    check_availability=True ise önce Akakçe'den hangi sitelerde ürün olduğunu kontrol eder.
    """
    target_sites = product_config.get('target_sites', ALL_SITES)
    # Eğer tek bir site belirtilmişse (eski format), onu kullan
    if 'target_site' in product_config:
        target_sites = [product_config['target_site']]
    
    # Eğer kontrol etmek istiyorsak, Akakçe'den hangi sitelerde ürün olduğunu bul
    if check_availability and not product_config.get('target_site'):
        try:
            driver = initialize_driver()
            _, base_data = scrape_akakce_base_data(driver, product_config['url'])
            driver.quit()
            
            # Akakçe'de bulunan siteleri bul
            available_vendors = set()
            vendor_name_mapping = {
                "hepsiburada": "hepsiburada",
                "trendyol": "trendyol", 
                "n11": "n11",
                "pttavm": "pttavm",
                "pazarama": "pazarama"
            }
            
            for item in base_data:
                vendor_lower = item.get('vendor_name', '').lower()
                for site_key, site_name in vendor_name_mapping.items():
                    if site_key in vendor_lower or site_name in vendor_lower:
                        available_vendors.add(site_name)
            
            # Sadece mevcut siteler için task oluştur
            if available_vendors:
                target_sites = [site for site in target_sites if site in available_vendors]
                print(f"✅ {product_config['product_name']}: {len(available_vendors)} sitede mevcut ({', '.join(available_vendors)})")
            else:
                print(f"⚠️ {product_config['product_name']}: Hiçbir sitede bulunamadı, tüm siteler deneniyor")
        except Exception as e:
            print(f"⚠️ {product_config['product_name']}: Akakçe kontrolü başarısız, tüm siteler deneniyor: {e}")
    
    tasks = []
    for site in target_sites:
        task = product_config.copy()
        task['target_site'] = site
        # target_sites'i kaldır, sadece target_site kalsın
        task.pop('target_sites', None)
        tasks.append(task)
    
    return tasks

def run_scraper_script(product_config):
    """
    targets.json'dan gelen ürüne göre uygun site script'ini 
    subprocess ile çalıştırır.
    """
    
    site_name = product_config.get('target_site', 'unknown')
    
    script_map = {
        "hepsiburada": "hb_scraping.py",
        "trendyol": "ty_scraper.py", 
        "n11": "n11_scraper.py",
        "pttavm": "ptt_scraper.py",
        "pazarama": "pazarama_scraper.py",
        # Diğer siteler buraya eklenecek
    }
    
    script_file = script_map.get(site_name)
    
    if not script_file:
        return f"⚠️ {product_config['product_name']} için uygun scraper ({site_name}) tanımlı değil."
    
    try:
        json_arg = json.dumps(product_config)
        
        print(f"🔄 Başlatılıyor: {product_config['product_name']} ({site_name} -> {script_file})")
        
        result = subprocess.run(
            [sys.executable, script_file, json_arg],
            capture_output=True,
            text=True,
            check=True 
        )
        
        return result.stdout.strip()
        
    except subprocess.CalledProcessError as e:
        error_output = e.stderr.strip() or e.stdout.strip()
        return f"❌ Hata ({product_config['product_name']}): Script çalıştırılırken sorun oluştu.\n{error_output}"
    except FileNotFoundError:
        return f"❌ Hata: {script_file} dosyası bulunamadı. Lütfen kontrol edin."
    except Exception as e:
        return f"❌ Kritik Hata: {e}"


# ----------------- ANA ÇALIŞTIRMA BLOĞU -----------------

def main_scraper_runner():
    """targets.json dosyasını yükler ve Multiprocessing havuzunu başlatır."""
    
    try:
        with open('targets.json', 'r', encoding='utf-8') as f:
            product_list = json.load(f)
    except FileNotFoundError:
        print("❌ Hata: targets.json bulunamadı. Lütfen 'veri_toplama' klasöründe olduğundan emin olun.")
        return
    except json.JSONDecodeError:
        print("❌ Hata: targets.json dosyası bozuk veya geçersiz JSON formatında.")
        return

    if not product_list:
        print("⚠️ targets.json dosyası boş. Lütfen en az bir ürün URL'si ekleyin.")
        return
    
    # Her ürün için tüm siteleri çekmek üzere task'ları genişlet
    all_tasks = []
    for product in product_list:
        tasks = expand_product_tasks(product)
        all_tasks.extend(tasks)
    
    # 500 entry için çok fazla süreç açmamak için maksimum sınır koy
    num_processes = min(len(all_tasks), 10)  # Maksimum 10 paralel işlem
    print(f"=========================================================")
    print(f"📦 {len(product_list)} ürün bulundu")
    print(f"🔄 Toplam {len(all_tasks)} task oluşturuldu (ürün × site)")
    print(f"🚀 {num_processes} paralel işlem başlatılıyor...")
    print(f"=========================================================")

    with Pool(processes=num_processes) as pool:
        results = pool.map(run_scraper_script, all_tasks)

    print("\n========================= SONUÇLAR =========================")
    for result in results:
        print(result)
    print("==========================================================")


if __name__ == "__main__":
    import sys
    
    # Komut satırı argümanı: Sadece belirli bir product_id'yi işle
    if len(sys.argv) > 1:
        target_product_id = sys.argv[1]
        print(f"🎯 Sadece '{target_product_id}' ürünü işlenecek...\n")
        
        try:
            with open('targets.json', 'r', encoding='utf-8') as f:
                all_products = json.load(f)
        except FileNotFoundError:
            print("❌ Hata: targets.json bulunamadı.")
            sys.exit(1)
        
        filtered_products = [p for p in all_products if p.get('product_id') == target_product_id]
        
        if not filtered_products:
            print(f"❌ Hata: '{target_product_id}' ürünü targets.json'da bulunamadı.")
            sys.exit(1)
        
        print(f"✅ {len(filtered_products)} ürün bulundu: {filtered_products[0].get('product_name', target_product_id)}\n")
        
        import shutil
        shutil.copy('targets.json', 'targets.json.backup')
        
        with open('targets.json', 'w', encoding='utf-8') as f:
            json.dump(filtered_products, f, ensure_ascii=False, indent=2)
        
        try:
            main_scraper_runner()
        finally:
            shutil.move('targets.json.backup', 'targets.json')
            print("\n✅ targets.json orijinal haline geri yüklendi.")
    else:
        main_scraper_runner()
    
