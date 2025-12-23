#!/usr/bin/env python3
"""
L'Oreal Paris için tek bir scraper'ı test eder
"""
import json
import sys
from hb_scraping import scrape_hepsiburada_product

if __name__ == "__main__":
    # targets.json'dan L'Oreal Paris'i al
    with open('targets.json', 'r', encoding='utf-8') as f:
        products = json.load(f)
    
    loreal = None
    for p in products:
        if "loreal" in p["product_id"].lower() or "revitalift" in p["product_name"].lower():
            loreal = p
            break
    
    if not loreal:
        print("❌ L'Oreal Paris bulunamadı")
        print(f"   Mevcut ürünler: {[p['product_id'] for p in products]}")
        sys.exit(1)
    
    print(f"🧪 Test ediliyor: {loreal['product_name']}")
    print(f"   ID: {loreal['product_id']}")
    print("=" * 60)
    
    # Hepsiburada scraper'ını test et
    print("\n🔍 Hepsiburada scraper test ediliyor...\n")
    result = scrape_hepsiburada_product(loreal)
    print("\n" + "=" * 60)
    print("SONUÇ:")
    print(result)
    print("=" * 60)

