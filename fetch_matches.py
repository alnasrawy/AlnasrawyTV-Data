import json
import requests
from datetime import datetime, timezone, timedelta

# مفتاح الـ API الخاص بك المعتمد رسمياً
API_KEY = "08bb1fd877f108a186ef75e2b2b4cac6"

def get_matches():
    iraq_tz = timezone(timedelta(hours=3))
    today = datetime.now(iraq_tz).strftime("%Y-%m-%d")
    
    url = f"https://v3.football.api-sports.io/fixtures?date={today}"
    
    headers = {
        'x-rapidapi-host': 'v3.football.api-sports.io',
        'x-rapidapi-key': API_KEY
    }

    print(f"Requesting API-Football for date: {today}")

    try:
        response = requests.get(url, headers=headers, timeout=15)
        print(f"Response Status Code: {response.status_code}")
        
        if response.status_code != 200:
            print(f"Error: API returned status code {response.status_code}")
            return []
            
        data = response.json()
        fixtures = data.get('response', [])
        print(f"Total fixtures found: {len(fixtures)}")
        
        parsed_matches = []
        has_live_match = False
        
        for fixture in fixtures:
            match_info = fixture.get('fixture', {})
            teams = fixture.get('teams', {})
            goals = fixture.get('goals', {})
            league_info = fixture.get('league', {})
            status_short = match_info.get('status', {}).get('short', 'NS')
            
            # تحديد الحالة بدقة للتطبيق الرئيسي
            if status_short in ['1H', 'HT', '2H', 'ET', 'P', 'LIVE']:
                match_status = "LIVE"
                has_live_match = True
            elif status_short in ['FT', 'AET', 'PEN']:
                match_status = "ENDED"
            else:
                match_status = "UPCOMING"
                
            h_score = str(goals.get('home') if goals.get('home') is not None else 0)
            a_score = str(goals.get('away') if goals.get('away') is not None else 0)
            
            # استخراج وقت المباراة بتوقيت العراق المحلي
            match_date_utc = match_info.get('date')
            match_time = "--:--"
            if match_date_utc:
                dt_utc = datetime.fromisoformat(match_date_utc.replace('Z', '+00:00'))
                dt_iraq = dt_utc.astimezone(iraq_tz)
                match_time = dt_iraq.strftime("%H:%M")

            parsed_matches.append({
                "id": str(match_info.get('id', '0')),
                "homeTeam": teams.get('home', {}).get('name', '').strip(),
                "homeTeamLogo": teams.get('home', {}).get('logo', '').strip(),
                "awayTeam": teams.get('away', {}).get('name', '').strip(),
                "awayTeamLogo": teams.get('away', {}).get('logo', '').strip(),
                "league": league_info.get('name', 'مباريات متنوعة').strip(),
                "matchTime": match_time,
                "status": match_status,
                "score": f"{h_score} - {a_score}",
                "homeScore": h_score,
                "awayScore": a_score,
                "channelName": "غير متوفرة",
                "commentator": "غير محدد"
            })
            
        if has_live_match:
            print("Status: LIVE matches detected! Updating live scores.")
        else:
            print("Status: No live matches right now.")
            
        return parsed_matches
        
    except Exception as e:
        print(f"CRITICAL EXCEPTION: {str(e)}")
        return []

if __name__ == "__main__":
    matches = get_matches()
    if matches:
        with open("matches.json", "w", encoding="utf-8") as f:
            json.dump(matches, f, ensure_ascii=False, indent=2)
        print("matches.json updated successfully.")
    else:
        print("No matches to update or fetch failed.")
