# Hepsiburada scraper test scripti
import json
import sys
from hb_scraping import scrape_hepsiburada_product
from utils import initialize_driver, scrape_akakce_base_data

# targets.json'dan tüm ürünleri yükle
def find_hepsiburada_product():
    """targets.json'dan Hepsiburada satıcısı olan bir ürün bul"""
    try:
        with open('targets.json', 'r', encoding='utf-8') as f:
            products = json.load(f)
    except:
        print("❌ targets.json bulunamadı!")
        return None
    
    driver = initialize_driver()
    try:
        for product in products:
            print(f"\n🔍 Kontrol ediliyor: {product['product_name']}")
            _, base_data = scrape_akakce_base_data(driver, product['url'])
            
            # Hepsiburada satıcısı var mı?
            hb_found = any("hepsi" in item["vendor_name"].lower() and "burada" in item["vendor_name"].lower() 
                          for item in base_data)
            
            if hb_found:
                print(f"✅ Hepsiburada satıcısı bulundu!")
                return product
            else:
                print(f"❌ Hepsiburada yok. Mevcut satıcılar: {[item['vendor_name'] for item in base_data[:3]]}")
    finally:
        driver.quit()
    
    return None

if __name__ == "__main__":
    print("=" * 60)
    print("HEPSIBURADA SCRAPER TEST")
    print("=" * 60)
    
    # Hepsiburada satıcısı olan bir ürün bul
    print("\n1. Hepsiburada satıcısı olan ürün aranıyor...")
    test_config = find_hepsiburada_product()
    
    if not test_config:
        print("\n❌ targets.json'da Hepsiburada satıcısı olan hiçbir ürün bulunamadı!")
        print("Lütfen Hepsiburada'da satılan bir ürün URL'si ekleyin.")
        sys.exit(1)
    
    print(f"\n✅ Test ürünü bulundu:")
    print(f"   Ürün: {test_config['product_name']}")
    print(f"   URL: {test_config['url']}")
    print("=" * 60)
    
    print("\n2. Yorumlar çekiliyor... (Detaylı debug mesajları göreceksiniz)\n")
    print("=" * 60)
    
    result = scrape_hepsiburada_product(test_config)
    print("\n" + "=" * 60)
    print("SONUÇ:")
    print(result)
    print("=" * 60)

