#!/usr/bin/env python3
"""
Belirli ürünlerin hangi sitelerde mevcut olduğunu kontrol eder
"""
import json
from utils import initialize_driver, scrape_akakce_base_data

if __name__ == "__main__":
    with open('targets.json', 'r', encoding='utf-8') as f:
        products = json.load(f)
    
    # Sebamed ve Solante'yi bul
    test_products = [p for p in products if "sebamed" in p["product_id"].lower() or "solante" in p["product_id"].lower()]
    
    if not test_products:
        print("❌ Sebamed veya Solante bulunamadı")
        exit(1)
    
    for product in test_products:
        print(f"\n{'='*60}")
        print(f"🔍 Kontrol ediliyor: {product['product_name']}")
        print(f"   ID: {product['product_id']}")
        print(f"   URL: {product['url']}")
        print(f"{'='*60}\n")
        
        driver = initialize_driver()
        try:
            _, base_data = scrape_akakce_base_data(driver, product['url'])
            
            print(f"📊 Akakçe'den {len(base_data)} satıcı bulundu:\n")
            
            # Site bazında grupla
            sites = {}
            for item in base_data:
                vendor_lower = item.get('vendor_name', '').lower()
                site = None
                
                if 'hepsiburada' in vendor_lower:
                    site = 'hepsiburada'
                elif 'trendyol' in vendor_lower:
                    site = 'trendyol'
                elif 'n11' in vendor_lower:
                    site = 'n11'
                elif 'pttavm' in vendor_lower or 'ptt' in vendor_lower:
                    site = 'pttavm'
                elif 'pazarama' in vendor_lower:
                    site = 'pazarama'
                
                if site:
                    if site not in sites:
                        sites[site] = []
                    sites[site].append(item)
            
            # Sonuçları göster
            print("📦 Site bazında özet:")
            for site in ['hepsiburada', 'trendyol', 'n11', 'pttavm', 'pazarama']:
                if site in sites:
                    print(f"   ✅ {site}: {len(sites[site])} satıcı")
                    for vendor in sites[site][:3]:  # İlk 3 satıcı
                        print(f"      - {vendor.get('vendor_name', 'N/A')}: {vendor.get('price', 'N/A')} TL")
                else:
                    print(f"   ❌ {site}: Bulunamadı")
            
            # Bulunamayan siteler
            missing_sites = [s for s in ['hepsiburada', 'trendyol', 'n11', 'pttavm', 'pazarama'] if s not in sites]
            if missing_sites:
                print(f"\n⚠️ Bu ürün şu sitelerde bulunamadı: {', '.join(missing_sites)}")
            
        except Exception as e:
            print(f"❌ Hata: {e}")
            import traceback
            traceback.print_exc()
        finally:
            driver.quit()
            print("\n" + "="*60)

