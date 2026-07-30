import json
import os
import time
import requests

TMDB_API_KEY = "855850b0048962918368d2652c1e67cd"
MOVIES_FILE = "movies.json"
PAGES_TO_FETCH = 5  # يجلب 100 فيلم جديد في كل مرة

# 1. قراءة الأفلام المحفوظة سابقاً لمنع التكرار والحفاظ على المكتبة
existing_movies = []
existing_ids = set()

if os.path.exists(MOVIES_FILE):
    try:
        with open(MOVIES_FILE, "r", encoding="utf-8") as f:
            existing_movies = json.load(f)
            for movie in existing_movies:
                if "id" in movie:
                    existing_ids.add(movie["id"])
        print(f" تم تحميل {len(existing_movies)} فيلم سابق من الملف.")
    except Exception as e:
        print(f"⚠️ خطأ أثناء قراءة الملف القديم: {e}")

new_movies_count = 0

# 2. جلب الأفلام من TMDB (الأكثر شعبية والأعلى تقييماً)
endpoints = [
    "https://api.themoviedb.org/3/movie/popular",
    "https://api.themoviedb.org/3/movie/top_rated"
]

for endpoint in endpoints:
    for page in range(1, PAGES_TO_FETCH + 1):
        url = f"{endpoint}?api_key={TMDB_API_KEY}&language=ar-SA&page={page}"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                results = response.json().get("results", [])
                for item in results:
                    movie_id = item.get("id")

                    # إذا كان الفيلم موجوداً في مكتبتنا من قبل، نتخطاه فوراً
                    if movie_id in existing_ids:
                        continue

                    title = item.get("title") or item.get("original_title")
                    overview = item.get("overview", "")
                    poster_path = item.get("poster_path")
                    backdrop_path = item.get("backdrop_path")
                    rating = item.get("vote_average", 0)
                    release_date = item.get("release_date", "")
                    year = release_date.split("-")[0] if release_date else ""

                    poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else ""
                    backdrop_url = f"https://image.tmdb.org/t/p/w780{backdrop_path}" if backdrop_path else ""

                    # إنشاء روابط السيرفرات الهجينة
                    sources = [
                        {"id": 1, "name": "سيرفر 1 (VidSrc)", "url": f"https://vidsrc.me/embed/movie?tmdb={movie_id}"},
                        {"id": 2, "name": "سيرفر 2 (VidSrc CC)", "url": f"https://vidsrc.cc/v2/embed/movie/{movie_id}"},
                        {"id": 3, "name": "سيرفر 3 (2Embed)", "url": f"https://www.2embed.cc/embed/{movie_id}"}
                    ]

                    movie_obj = {
                        "id": movie_id,
                        "title": title,
                        "description": overview,
                        "posterUrl": poster_url,
                        "backdropUrl": backdrop_url,
                        "rating": rating,
                        "year": year,
                        "sources": sources
                    }

                    existing_movies.append(movie_obj)
                    existing_ids.add(movie_id)
                    new_movies_count += 1

            time.sleep(0.2)  # فاصل زمني لحماية الـ API
        except Exception as e:
            print(f"⚠️ خطأ أثناء جلب الصفحة {page}: {e}")

# 3. حفظ القائمة المدمجة الجديدة
if existing_movies:
    with open(MOVIES_FILE, "w", encoding="utf-8") as f:
        json.dump(existing_movies, f, ensure_ascii=False, indent=2)
    print(f" تم إضافة {new_movies_count} فيلم جديد! إجمالي المكتبة الآن: {len(existing_movies)} فيلم.")
