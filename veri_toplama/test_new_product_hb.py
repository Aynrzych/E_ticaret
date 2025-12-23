#!/usr/bin/env python3
"""
Yeni ürün için Hepsiburada scraper'ını test eder
"""
import json
import sys
from hb_scraping import scrape_hepsiburada_product

if __name__ == "__main__":
    with open('targets.json', 'r', encoding='utf-8') as f:
        products = json.load(f)
    
    # Son 2 ürünü al (yeni eklenenler)
    test_product = products[-2]  # Oil Control ürünü
    
    print(f"🧪 Test ediliyor: {test_product['product_name']}")
    print(f"   ID: {test_product['product_id']}")
    print("=" * 60)
    
    print("\n🔍 Hepsiburada scraper test ediliyor...\n")
    result = scrape_hepsiburada_product(test_product)
    print("\n" + "=" * 60)
    print("SONUÇ:")
    print(result)
    print("=" * 60)

