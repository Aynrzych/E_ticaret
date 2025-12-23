#!/usr/bin/env python3
"""
Tek bir scraper'ı test eder
"""
import json
import sys
from hb_scraping import scrape_hepsiburada_product

if __name__ == "__main__":
    # targets.json'dan ilk yeni ürünü al
    with open('targets.json', 'r', encoding='utf-8') as f:
        products = json.load(f)
    
    # Yeni eklenen ürünlerden birini bul (Sebamed, Solante, La Roche-Posay Oil Control)
    test_product = None
    for p in products:
        if "sebamed" in p["product_id"].lower() or "solante" in p["product_id"].lower():
            test_product = p
            break
    
    if not test_product:
        print("❌ Test ürünü bulunamadı")
        sys.exit(1)
    
    print(f"🧪 Test ediliyor: {test_product['product_name']}")
    print(f"   ID: {test_product['product_id']}")
    print("=" * 60)
    
    result = scrape_hepsiburada_product(test_product)
    print("\n" + "=" * 60)
    print("SONUÇ:")
    print(result)
    print("=" * 60)

