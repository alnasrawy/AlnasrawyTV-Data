import os
import json
import random
import requests

TMDB_API_KEY = "9934aa2ab8462d1f4f1c28d5e4e48069"

def fetch_series():
    """
    سحب مسلسلات متنوعة وعشوائية من TMDB باللغة العربية لتوسيع المكتبة باستمرار
    """
    existing_series = []
    
    if os.path.exists("series.json"):
        try:
            with open("series.json", "r", encoding="utf-8") as f:
                existing_series = json.load(f)
                if not isinstance(existing_series, list):
                    existing_series = []
        except Exception as e:
            print(f"⚠️ خطأ أثناء قراءة ملف series.json: {e}")
            existing_series = []

    existing_ids = {str(s.get("id")) for s in existing_series if isinstance(s, dict)}

    # اختيار رقم صفحة عشوائي من 1 إلى 100 لجلب مسلسلات مختلفة في كل تشغيل
    random_page = random.randint(1, 100)
    url = f"https://api.themoviedb.org/3/discover/tv?api_key={TMDB_API_KEY}&language=ar&sort_by=popularity.desc&page={random_page}"
    
    new_series = []

    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            results = response.json().get("results", [])

            for item in results:
                tmdb_id = str(item.get("id"))
                poster_path = item.get("poster_path")
                
                # تخطي المسلسلات التي بدون غلاف أو المضافة سابقاً
                if not poster_path or tmdb_id in existing_ids:
                    continue

                title = item.get("name") or item.get("original_name")
                backdrop_path = item.get("backdrop_path")
                
                poster = f"https://image.tmdb.org/t/p/w500{poster_path}"
                backdrop = f"https://image.tmdb.org/t/p/w780{backdrop_path}" if backdrop_path else poster
                overview = item.get("overview") or "لا يوجد وصف متاح لهذا المسلسل حالياً."
                rating = str(round(item.get("vote_average", 0), 1))
                release_year = (item.get("first_air_date") or "")[:4]

                series_obj = {
                    "id": tmdb_id,
                    "title": title,
                    "poster": poster,
                    "backdrop": backdrop,
                    "description": overview,
                    "rating": rating,
                    "year": release_year,
                    "servers": [
                        {"name": "سيرفر 1 (VidSrc)", "url": f"https://vidsrc.me/embed/tv?tmdb={tmdb_id}"},
                        {"name": "سيرفر 2 (2Embed)", "url": f"https://www.2embed.cc/embedtv/{tmdb_id}"},
                        {"name": "سيرفر 3 (VidSrc PRO)", "url": f"https://vidsrc.pro/embed/tv/{tmdb_id}"}
                    ]
                }
                new_series.append(series_obj)

    except Exception as e:
        print(f"⚠️ خطأ أثناء اتصال TMDB: {e}")

    final_series_list = new_series + existing_series

    with open("series.json", "w", encoding="utf-8") as f:
        json.dump(final_series_list, f, ensure_ascii=False, indent=2)

    print(f"✅ تم إضافة {len(new_series)} مسلسل جديد من الصفحة العشوائية ({random_page})! الإجمالي: {len(final_series_list)} مسلسل.")

if __name__ == "__main__":
    fetch_series()
