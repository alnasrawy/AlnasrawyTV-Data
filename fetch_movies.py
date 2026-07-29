import json
import requests

# 1. مفتاح TMDB API ورابط جلب الأفلام الشائعة
TMDB_API_KEY = "ebda82be344d188aaec350fa63ccf401"  # مفتاح تجريبي
URL = f"https://api.themoviedb.org/3/trending/movie/day?api_key={TMDB_API_KEY}&language=ar-SA"

def fetch_movies():
    print("🔄 Fetching movies from TMDB...")
    response = requests.get(URL)
    
    if response.status_code != 200:
        print("❌ Failed to fetch data from TMDB")
        return []

    results = response.json().get('results', [])
    movies_list = []

    for item in results[:15]: # جلب أول 15 فيلم للتجربة
        tmdb_id = item.get('id')
        title = item.get('title')
        overview = item.get('overview', '')
        poster_path = item.get('poster_path', '')
        backdrop_path = item.get('backdrop_path', '')
        vote_average = item.get('vote_average', 0)
        release_date = item.get('release_date', '')[:4]

        # 2. بناء قائمة السيرفرات المتعددة لكل فيلم
        servers = [
            {
                "id": 1,
                "name": "سيرفر 1 (سريع)",
                "url": f"https://vidsrc.me/embed/movie?tmdb={tmdb_id}"
            },
            {
                "id": 2,
                "name": "سيرفر 2 (احتياطي)",
                "url": f"https://vidsrc.cc/v2/embed/movie/{tmdb_id}"
            },
            {
                "id": 3,
                "name": "سيرفر 3 (VIP)",
                "url": f"https://vidsrc.in/embed/movie?tmdb={tmdb_id}"
            }
        ]

        movie_data = {
            "id": tmdb_id,
            "title": title,
            "description": overview,
            "posterUrl": f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else "",
            "backdropUrl": f"https://image.tmdb.org/t/p/w780{backdrop_path}" if backdrop_path else "",
            "rating": round(vote_average, 1),
            "year": release_date,
            "sources": servers
        }
        movies_list.append(movie_data)

    return movies_list

def main():
    movies = fetch_movies()
    
    # 3. حفظ البيانات في ملف movies.json
    with open("movies.json", "w", encoding="utf-8") as f:
        json.dump(movies, f, ensure_ascii=False, indent=2)
        
    print(f"✅ Successfully generated movies.json with {len(movies)} movies!")

if __name__ == "__main__":
    main()
