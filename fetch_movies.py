import os
import json
import requests

# مفتاح TMDB API الخاص بحسابك
TMDB_API_KEY = "9934aa2ab8462d1f4f1c28d5e4e48069"

def fetch_movies():
    """
    سحب جديد الأفلام من TMDB باللغة العربية مع الحفاظ على الأفلام القديمة
    واستخراج 3 سيرفرات مشاهدة لكل فيلم.
    """
    existing_movies = []
    
    # 1. قراءة الأفلام المسجلة سابقاً لمنع مسحها
    if os.path.exists("movies.json"):
        try:
            with open("movies.json", "r", encoding="utf-8") as f:
                existing_movies = json.load(f)
                if not isinstance(existing_movies, list):
                    existing_movies = []
        except Exception as e:
            print(f"⚠️ خطأ أثناء قراءة ملف movies.json القديم: {e}")
            existing_movies = []

    # معرّفات الأفلام الموجودة حالياً لتفادي التكرار
    existing_ids = {str(m.get("id")) for m in existing_movies if isinstance(m, dict)}

    # 2. جلب قائمة الأفلام الأكثر شعبية اليوم من TMDB
    url = f"https://api.themoviedb.org/3/trending/movie/day?api_key={TMDB_API_KEY}&language=ar"
    new_movies = []

    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            results = data.get("results", [])

            for item in results:
                tmdb_id = str(item.get("id"))
                title = item.get("title") or item.get("original_title")
                poster_path = item.get("poster_path")
                backdrop_path = item.get("backdrop_path")
                
                poster = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else ""
                backdrop = f"https://image.tmdb.org/t/p/w780{backdrop_path}" if backdrop_path else ""
                overview = item.get("overview", "لا يوجد وصف متاح لهذا الفيلم حالياً.")
                rating = str(round(item.get("vote_average", 0), 1))
                release_year = (item.get("release_date") or "")[:4]

                # إضافة الفيلم فقط إذا لم يكن موجوداً سابقاً
                if tmdb_id not in existing_ids:
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

        else:
            print(f"⚠️ خطأ من سيرفر TMDB، رمز الاستجابة: {response.status_code}")

    except Exception as e:
        print(f"⚠️ خطأ أثناء اتصال TMDB: {e}")

    # 3. دمج الأفلام الجديدة في البداية مع الاحتفاظ بالقديمة
    final_movies_list = new_movies + existing_movies

    # 4. حفظ النتيجة داخل movies.json بصيغة قائمة صريحة [...]
    with open("movies.json", "w", encoding="utf-8") as f:
        json.dump(final_movies_list, f, ensure_ascii=False, indent=2)

    print(f"✅ تم إضافة {len(new_movies)} فيلم جديد! الإجمالي الحالي: {len(final_movies_list)} فيلم.")

if __name__ == "__main__":
    fetch_movies()
