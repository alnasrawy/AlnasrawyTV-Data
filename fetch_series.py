import os
import json
import random
import requests

# مفتاح TMDB API الخاص بك
TMDB_API_KEY = "9934aa2ab8462d1f4f1c28d5e4e48069"

def is_link_alive(url, timeout=4):
    """
    فحص صحة الرابط والتأكد من أنه شغال ويستجيب قبل اعتماده في القائمة
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    try:
        # فحص رأس الرابط HEAD لسرعة الاستجابة
        res = requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
        if res.status_code in [200, 206, 301, 302]:
            return True
        # فحص احتياطي عبر طلب GET خفيف
        res = requests.get(url, headers=headers, timeout=timeout, stream=True)
        return res.status_code in [200, 206, 301, 302]
    except Exception:
        return False

def fetch_series():
    """
    سحب مسلسلات متنوعة، فحص صحة الروابط تلقائياً، وتصفية السيرفرات الميتة
    """
    existing_series = []
    
    # 1. قراءة الملف القديم
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

    # 2. سحب من صفحات عشوائية لزيادة التنوع
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
                
                if not poster_path or tmdb_id in existing_ids:
                    continue

                title = item.get("name") or item.get("original_name")
                backdrop_path = item.get("backdrop_path")
                
                poster = f"https://image.tmdb.org/t/p/w500{poster_path}"
                backdrop = f"https://image.tmdb.org/t/p/w780{backdrop_path}" if backdrop_path else poster
                overview = item.get("overview") or "لا يوجد وصف متاح لهذا المسلسل حالياً."
                rating = str(round(item.get("vote_average", 0), 1))
                release_year = (item.get("first_air_date") or "")[:4]

                # قائمة المصادر المرشحة من شبكات ومزودات مختلفة
                candidate_servers = [
                    {
                        "name": "سيرفر 1 (VidSrc HLS Direct)", 
                        "url": f"https://vidsrc.stream/open/tv/{tmdb_id}/master.m3u8",
                        "type": "hls"
                    },
                    {
                        "name": "سيرفر 2 (Fast Stream MP4)", 
                        "url": f"https://vidsrc.net/stream/tv/{tmdb_id}.mp4",
                        "type": "mp4"
                    },
                    {
                        "name": "سيرفر 3 (MPEG-TS Stream)", 
                        "url": f"https://vidsrc.xyz/ts/tv/{tmdb_id}.ts",
                        "type": "ts"
                    }
                ]

                # 3. محرك الفحص: إبقاء السيرفرات الشغالة فقط وحذف الميتة
                valid_servers = []
                for srv in candidate_servers:
                    print(f"🔍 جاري فحص سيرفر المسلسل ({title}) - {srv['name']}...")
                    if is_link_alive(srv["url"]):
                        valid_servers.append(srv)
                        print(f"✅ الرابط يعمل بنجاح!")
                    else:
                        print(f"❌ الرابط متوقف أو بطيء، تم استبعاده.")

                # إضافة المسلسل فقط إذا كان يحتوي على سيرفر واحد شغال على الأقل
                if valid_servers:
                    series_obj = {
                        "id": tmdb_id,
                        "title": title,
                        "poster": poster,
                        "backdrop": backdrop,
                        "description": overview,
                        "rating": rating,
                        "year": release_year,
                        "servers": valid_servers
                    }
                    new_series.append(series_obj)

    except Exception as e:
        print(f"⚠️ خطأ أثناء اتصال TMDB: {e}")

    # 4. دمج وحفظ النتائج النظيفة
    final_series_list = new_series + existing_series

    with open("series.json", "w", encoding="utf-8") as f:
        json.dump(final_series_list, f, ensure_ascii=False, indent=2)

    print(f"🚀 تم فحص واعتماد {len(new_series)} مسلسل بحالة ممتازة! الإجمالي الحالي: {len(final_series_list)} مسلسل.")

if __name__ == "__main__":
    fetch_series()
