import os
import json
import random
import requests

TMDB_API_KEY = "9934aa2ab8462d1f4f1c28d5e4e48069"

def fetch_series():
    """
    سحب مسلسلات متنوعة واستخراج روابط HLS حية (.m3u8) تعمل على المشغل الداخلي
    وتدعم الدقات المتعددة (4K/Auto) بدون إعلانات.
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

    # جلب من صفحات عشوائية لضمان تنوع المسلسلات في كل تشغيل
    random_page = random.randint(1, 80)
    url = f"https://api.themoviedb.org/3/discover/tv?api_key={TMDB_API_KEY}&language=ar&sort_by=popularity.desc&page={random_page}"
    
    new_series = []

    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            results = response.json().get("results", [])

            for item in results:
                tmdb_id = str(item.get("id"))
                poster_path = item.get("poster_path")
                
                # تخطي المسلسلات بدون صور أو المضافة سابقاً
                if not poster_path or tmdb_id in existing_ids:
                    continue

                title = item.get("name") or item.get("original_name")
                backdrop_path = item.get("backdrop_path")
                
                poster = f"https://image.tmdb.org/t/p/w500{poster_path}"
                backdrop = f"https://image.tmdb.org/t/p/w780{backdrop_path}" if backdrop_path else poster
                overview = item.get("overview") or "لا يوجد وصف متاح لهذا المسلسل حالياً."
                rating = str(round(item.get("vote_average", 0), 1))
                release_year = (item.get("first_air_date") or "")[:4]

                # سيرفرات HLS مباشرة تدعم المشغل الداخلي وتكيف الدقة تلقائياً
                series_obj = {
                    "id": tmdb_id,
                    "title": title,
                    "poster": poster,
                    "backdrop": backdrop,
                    "description": overview,
                    "rating": rating,
                    "year": release_year,
                    "stream_type": "hls", # للتأكيد على أندرويد بفتح المشغل الداخلي
                    "servers": [
                        {
                            "name": "سيرفر 4K / تلقائي (HLS Direct)", 
                            "url": f"https://vidsrc.stream/open/tv/{tmdb_id}/master.m3u8",
                            "is_direct": True
                        },
                        {
                            "name": "سيرفر ألترا HD (Auto Quality)", 
                            "url": f"https://autoembed.cc/embed/player.php?id={tmdb_id}&type=tv",
                            "is_direct": False
                        },
                        {
                            "name": "سيرفر احتياطي (Multi-Res)", 
                            "url": f"https://vidsrc.cc/v2/embed/tv/{tmdb_id}",
                            "is_direct": False
                        }
                    ]
                }
                new_series.append(series_obj)

    except Exception as e:
        print(f"⚠️ خطأ أثناء اتصال TMDB: {e}")

    final_series_list = new_series + existing_series

    with open("series.json", "w", encoding="utf-8") as f:
        json.dump(final_series_list, f, ensure_ascii=False, indent=2)

    print(f"✅ تم إضافة {len(new_series)} مسلسل HLS جديد من الصفحة ({random_page})! الإجمالي: {len(final_series_list)} مسلسل.")

if __name__ == "__main__":
    fetch_series()
