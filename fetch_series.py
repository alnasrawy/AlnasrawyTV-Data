import os
import json
import requests

# مفتاح TMDB API الخاص بحسابك
TMDB_API_KEY = "9934aa2ab8462d1f4f1c28d5e4e48069"

def fetch_series():
    """
    سحب جديد المسلسلات من TMDB باللغة العربية مع الحفاظ على المسلسلات القديمة
    واستخراج سيرفرات المشاهدة المباشرة لكل مسلسل.
    """
    existing_series = []
    
    # 1. قراءة المسلسلات المسجلة سابقاً لمنع مسحها
    if os.path.exists("series.json"):
        try:
            with open("series.json", "r", encoding="utf-8") as f:
                existing_series = json.load(f)
                if not isinstance(existing_series, list):
                    existing_series = []
        except Exception as e:
            print(f"⚠️ خطأ أثناء قراءة ملف series.json القديم: {e}")
            existing_series = []

    # معرّفات المسلسلات الموجودة حالياً لتفادي التكرار
    existing_ids = {str(s.get("id")) for s in existing_series if isinstance(s, dict)}

    # 2. جلب قائمة المسلسلات الأكثر شعبية اليوم من TMDB
    url = f"https://api.themoviedb.org/3/trending/tv/day?api_key={TMDB_API_KEY}&language=ar"
    new_series = []

    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            results = data.get("results", [])

            for item in results:
                tmdb_id = str(item.get("id"))
                title = item.get("name") or item.get("original_name")
                poster_path = item.get("poster_path")
                backdrop_path = item.get("backdrop_path")
                
                poster = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else ""
                backdrop = f"https://image.tmdb.org/t/p/w780{backdrop_path}" if backdrop_path else ""
                overview = item.get("overview", "لا يوجد وصف متاح لهذا المسلسل حالياً.")
                rating = str(round(item.get("vote_average", 0), 1))
                release_year = (item.get("first_air_date") or "")[:4]

                # إضافة المسلسل فقط إذا لم يكن موجوداً سابقاً
                if tmdb_id not in existing_ids:
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

        else:
            print(f"⚠️ خطأ من سيرفر TMDB، رمز الاستجابة: {response.status_code}")

    except Exception as e:
        print(f"⚠️ خطأ أثناء اتصال TMDB: {e}")

    # 3. دمج المسلسلات الجديدة في البداية مع الاحتفاظ بالقديمة
    final_series_list = new_series + existing_series

    # 4. حفظ النتيجة داخل series.json بصيغة قائمة صريحة [...]
    with open("series.json", "w", encoding="utf-8") as f:
        json.dump(final_series_list, f, ensure_ascii=False, indent=2)

    print(f"✅ تم إضافة {len(new_series)} مسلسل جديد! الإجمالي الحالي: {len(final_series_list)} مسلسل.")

if __name__ == "__main__":
    fetch_series()
