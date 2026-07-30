import os
import json
import random
import requests

TMDB_API_KEY = "9934aa2ab8462d1f4f1c28d5e4e48069"

def fetch_movies():
    """
    سحب أفلام متنوعة وعشوائية من TMDB باللغة العربية وتطعيم المكتبة دائماً بجديد
    """
    existing_movies = []
    
    if os.path.exists("movies.json"):
        try:
            with open("movies.json", "r", encoding="utf-8") as f:
                existing_movies = json.load(f)
                if not isinstance(existing_movies, list):
                    existing_movies = []
        except Exception as e:
            print(f"⚠️ خطأ أثناء قراءة ملف movies.json: {e}")
            existing_movies = []

    existing_ids = {str(m.get("id")) for m in existing_movies if isinstance(m, dict)}

    # اختيار رقم صفحة عشوائي من 1 إلى 100 لجلب أفلام مختلفة في كل تشغيل
    random_page = random.randint(1, 100)
    url = f"https://api.themoviedb.org/3/discover/movie?api_key={TMDB_API_KEY}&language=ar&sort_by=popularity.desc&page={random_page}"
    
    new_movies = []

    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            results = response.json().get("results", [])

            for item in results:
                tmdb_id = str(item.get("id"))
                poster_path = item.get("poster_path")
                
                # تخطي الأفلام التي بدون غلاف أو المضافة سابقاً
                if not poster_path or tmdb_id in existing_ids:
                    continue

                title = item.get("title") or item.get("original_title")
                backdrop_path = item.get("backdrop_path")
                
                poster = f"https://image.tmdb.org/t/p/w500{poster_path}"
                backdrop = f"https://image.tmdb.org/t/p/w780{backdrop_path}" if backdrop_path else poster
                overview = item.get("overview") or "لا يوجد وصف متاح لهذا الفيلم حالياً."
                rating = str(round(item.get("vote_average", 0), 1))
                release_year = (item.get("release_date") or "")[:4]

                movie_obj = {
                    "id": tmdb_id,
                    "title": title,
                    "poster": poster,
                    "backdrop": backdrop,
                    "description": overview,
                    "rating": rating,
                    "year": release_year,
                    "servers": [
                        {"name": "سيرفر 1 (VidSrc)", "url": f"https://vidsrc.me/embed/movie?tmdb={tmdb_id}"},
                        {"name": "سيرفر 2 (2Embed)", "url": f"https://www.2embed.cc/embed/{tmdb_id}"},
                        {"name": "سيرفر 3 (VidSrc PRO)", "url": f"https://vidsrc.pro/embed/movie/{tmdb_id}"}
                    ]
                }
                new_movies.append(movie_obj)

    except Exception as e:
        print(f"⚠️ خطأ أثناء اتصال TMDB: {e}")

    final_movies_list = new_movies + existing_movies

    with open("movies.json", "w", encoding="utf-8") as f:
        json.dump(final_movies_list, f, ensure_ascii=False, indent=2)

    print(f"✅ تم إضافة {len(new_movies)} فيلم جديد من الصفحة العشوائية ({random_page})! الإجمالي: {len(final_movies_list)} فيلم.")

if __name__ == "__main__":
    fetch_movies()
