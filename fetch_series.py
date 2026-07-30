import json
import os
import time
import requests

TMDB_API_KEY = "855850b0048962918368d2652c1e67cd"
SERIES_FILE = "series.json"
PAGES_TO_FETCH = 3  # يجلب حوالي 60 مسلسلاً كبيراً في كل تشغيل

existing_series = []
existing_ids = set()

# 1. تحميل المسلسلات السابقة
if os.path.exists(SERIES_FILE):
    try:
        with open(SERIES_FILE, "r", encoding="utf-8") as f:
            existing_series = json.load(f)
            for s in existing_series:
                if "id" in s:
                    existing_ids.add(s["id"])
        print(f" تم تحميل {len(existing_series)} مسلسل سابق من الملف.")
    except Exception as e:
        print(f"⚠️ خطأ أثناء قراءة الملف القديم: {e}")

new_series_count = 0

# 2. جلب المسلسلات الجديدة
for page in range(1, PAGES_TO_FETCH + 1):
    url = f"https://api.themoviedb.org/3/tv/popular?api_key={TMDB_API_KEY}&language=ar-SA&page={page}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            results = response.json().get("results", [])
            for item in results:
                series_id = item.get("id")

                # تخطي المسلسل إذا كان موجوداً مسبقاً
                if series_id in existing_ids:
                    continue

                title = item.get("name") or item.get("original_name")
                overview = item.get("overview", "")
                poster_path = item.get("poster_path")
                backdrop_path = item.get("backdrop_path")
                rating = item.get("vote_average", 0)
                first_air_date = item.get("first_air_date", "")
                year = first_air_date.split("-")[0] if first_air_date else ""

                poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else ""
                backdrop_url = f"https://image.tmdb.org/t/p/w780{backdrop_path}" if backdrop_path else ""

                # جلب مواسم وحلقات المسلسل الجديد فقط
                seasons_data = []
                details_url = f"https://api.themoviedb.org/3/tv/{series_id}?api_key={TMDB_API_KEY}&language=ar-SA"
                det_resp = requests.get(details_url, timeout=10)
                if det_resp.status_code == 200:
                    details = det_resp.json()
                    for season in details.get("seasons", []):
                        season_num = season.get("season_number", 0)
                        if season_num == 0:
                            continue

                        ep_count = season.get("episode_count", 0)
                        episodes = []
                        for ep in range(1, min(ep_count + 1, 30)):
                            episodes.append({
                                "episodeNumber": ep,
                                "title": f"الحلقة {ep}",
                                "sources": [
                                    {"id": 1, "name": "سيرفر 1", "url": f"https://vidsrc.me/embed/tv?tmdb={series_id}&season={season_num}&episode={ep}"},
                                    {"id": 2, "name": "سيرفر 2", "url": f"https://vidsrc.cc/v2/embed/tv/{series_id}/{season_num}/{ep}"}
                                ]
                            })
                        seasons_data.append({
                            "seasonNumber": season_num,
                            "title": f"الموسم {season_num}",
                            "episodes": episodes
                        })

                series_obj = {
                    "id": series_id,
                    "title": title,
                    "description": overview,
                    "posterUrl": poster_url,
                    "backdropUrl": backdrop_url,
                    "rating": rating,
                    "year": year,
                    "seasons": seasons_data
                }

                existing_series.append(series_obj)
                existing_ids.add(series_id)
                new_series_count += 1
                time.sleep(0.3)

    except Exception as e:
        print(f"⚠️ خطأ أثناء جلب المسلسلات صفحة {page}: {e}")

# 3. حفظ القائمة
if existing_series:
    with open(SERIES_FILE, "w", encoding="utf-8") as f:
        json.dump(existing_series, f, ensure_ascii=False, indent=2)
    print(f" تم إضافة {new_series_count} مسلسل جديد! إجمالي المسلسلات الآن: {len(existing_series)}.")
