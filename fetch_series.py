import json
import requests

TMDB_API_KEY = "9934aa2ab8462d1f4f1c28d5e4e48069"
URL = f"https://api.themoviedb.org/3/trending/tv/day?api_key={TMDB_API_KEY}&language=ar-SA"

# إضافة هيدر متصفح لتفادي حظر TMDB لسكربتات البايثون
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def fetch_series():
    print("🔄 Fetching TV series from TMDB...")
    try:
        response = requests.get(URL, headers=HEADERS, timeout=10)
        
        if response.status_code != 200:
            print(f"❌ Failed to fetch data from TMDB. Status Code: {response.status_code}")
            print(f"Response: {response.text}")
            return get_fallback_data()

        results = response.json().get('results', [])
        if not results:
            return get_fallback_data()

        series_list = []
        for item in results[:10]:
            tmdb_id = item.get('id')
            title = item.get('name')
            overview = item.get('overview', '')
            poster_path = item.get('poster_path', '')
            backdrop_path = item.get('backdrop_path', '')
            vote_average = item.get('vote_average', 0)
            first_air_date = item.get('first_air_date', '')[:4] if item.get('first_air_date') else "2026"

            seasons = [
                {
                    "season_number": 1,
                    "episodes": [
                        {
                            "episode_number": 1,
                            "title": "الحلقة 1",
                            "sources": [
                                {"id": 1, "name": "سيرفر 1", "url": f"https://vidsrc.me/embed/tv?tmdb={tmdb_id}&season=1&episode=1"},
                                {"id": 2, "name": "سيرفر 2", "url": f"https://vidsrc.cc/v2/embed/tv/{tmdb_id}/1/1"}
                            ]
                        }
                    ]
                }
            ]

            series_data = {
                "id": tmdb_id,
                "title": title,
                "description": overview,
                "posterUrl": f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else "",
                "backdropUrl": f"https://image.tmdb.org/t/p/w780{backdrop_path}" if backdrop_path else "",
                "rating": round(vote_average, 1),
                "year": first_air_date,
                "seasons": seasons
            }
            series_list.append(series_data)

        return series_list

    except Exception as e:
        print(f"⚠️ Exception occurred: {e}")
        return get_fallback_data()

def get_fallback_data():
    """ بيانات احتياطية لضمان عدم إرجاع ملف فارغ إطلاقاً """
    print("⚠️ Generating fallback data to ensure JSON is never empty...")
    return [
        {
            "id": 999901,
            "title": "مسلسل تجريبي - Alnasrawy TV",
            "description": "هذا مسلسل تجريبي للتأكد من ربط السيرفرات والتطبيق بنجاح.",
            "posterUrl": "https://image.tmdb.org/t/p/w500/1E5baAaEse26feLBvuX3yA98pTo.jpg",
            "backdropUrl": "https://image.tmdb.org/t/p/w780/1E5baAaEse26feLBvuX3yA98pTo.jpg",
            "rating": 9.5,
            "year": "2026",
            "seasons": [
                {
                    "season_number": 1,
                    "episodes": [
                        {
                            "episode_number": 1,
                            "title": "الحلقة 1",
                            "sources": [
                                {"id": 1, "name": "سيرفر 1 (تجريبي)", "url": "https://vidsrc.me/embed/tv?tmdb=1396&season=1&episode=1"},
                                {"id": 2, "name": "سيرفر 2 (تجريبي)", "url": "https://vidsrc.cc/v2/embed/tv/1396/1/1"}
                            ]
                        }
                    ]
                }
            ]
        }
    ]

def main():
    series = fetch_series()
    with open("series.json", "w", encoding="utf-8") as f:
        json.dump(series, f, ensure_ascii=False, indent=2)
    print(f"✅ Successfully generated series.json with {len(series)} series!")

if __name__ == "__main__":
    main()
