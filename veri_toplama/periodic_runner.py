import time
from main import main_scraper_runner

# Dakika cinsinden periyot (örn. 60 = saatte bir)
INTERVAL_MINUTES = 60


def run_periodic():
    """
    main_scraper_runner'ı belirli aralıklarla çalıştırır.

    Bu script'i:
    - Manuel olarak terminalde çalıştırabilir
    - Veya Windows Task Scheduler ile arka planda periyodik olarak tetikleyebilirsin.
    """
    while True:
        print(f"=== Yeni periyodik çekim başlıyor ===")
        main_scraper_runner()
        print(f"=== Çekim tamamlandı. {INTERVAL_MINUTES} dakika bekleniyor... ===")
        time.sleep(INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    run_periodic()


