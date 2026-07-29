import json
import requests

TMDB_API_KEY = "9934aa2ab8462d1f4f1c28d5e4e48069"
URL = f"https://api.themoviedb.org/3/trending/movie/day?api_key={TMDB_API_KEY}&language=ar-SA"

# إضافة هيدر متصفح لتفادي حظر TMDB لسكربتات البايثون
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def fetch_movies():
    print("🔄 Fetching movies from TMDB...")
    try:
        response = requests.get(URL, headers=HEADERS, timeout=10)
        
        if response.status_code != 200:
            print(f"❌ Failed to fetch data from TMDB. Status Code: {response.status_code}")
            print(f"Response: {response.text}")
            return get_fallback_data()

        results = response.json().get('results', [])
        if not results:
            return get_fallback_data()

        movies_list = []
        for item in results[:10]:
            tmdb_id = item.get('id')
            title = item.get('title')
            overview = item.get('overview', '')
            poster_path = item.get('poster_path', '')
            backdrop_path = item.get('backdrop_path', '')
            vote_average = item.get('vote_average', 0)
            release_date = item.get('release_date', '')[:4] if item.get('release_date') else "2026"

            sources = [
                {"id": 1, "name": "سيرفر 1", "url": f"https://vidsrc.me/embed/movie?tmdb={tmdb_id}"},
                {"id": 2, "name": "سيرفر 2", "url": f"https://vidsrc.cc/v2/embed/movie/{tmdb_id}"}
            ]

            movie_data = {
                "id": tmdb_id,
                "title": title,
                "description": overview,
                "posterUrl": f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else "",
                "backdropUrl": f"https://image.tmdb.org/t/p/w780{backdrop_path}" if backdrop_path else "",
                "rating": round(vote_average, 1),
                "year": release_date,
                "sources": sources
            }
            movies_list.append(movie_data)

        return movies_list

    except Exception as e:
        print(f"⚠️ Exception occurred: {e}")
        return get_fallback_data()

def get_fallback_data():
    """ بيانات احتياطية لضمان عدم إرجاع ملف فارغ إطلاقاً """
    print("⚠️ Generating fallback data for movies...")
    return [
        {
            "id": 550,
            "title": "فيلم تجريبي - Alnasrawy TV",
            "description": "هذا فيلم تجريبي للتأكد من ربط السيرفرات والتطبيق بنجاح.",
            "posterUrl": "https://image.tmdb.org/t/p/w500/pB8BM7pdSp6B6Ih7QZ4DrQ3PmJK.jpg",
            "backdropUrl": "https://image.tmdb.org/t/p/w780/hZk2G17Z9539D889a8117a78a63.jpg",
            "rating": 8.8,
            "year": "2026",
            "sources": [
                {"id": 1, "name": "سيرفر 1 (تجريبي)", "url": "https://vidsrc.me/embed/movie?tmdb=550"},
                {"id": 2, "name": "سيرفر 2 (تجريبي)", "url": "https://vidsrc.cc/v2/embed/movie/550"}
            ]
        }
    ]

def main():
    movies = fetch_movies()
    with open("movies.json", "w", encoding="utf-8") as f:
        json.dump(movies, f, ensure_ascii=False, indent=2)
    print(f"✅ Successfully generated movies.json with {len(movies)} movies!")

if __name__ == "__main__":
    main()
