import json
import requests
from datetime import datetime, timezone, timedelta

def sanitize_league_name(name):
    junk = ["أخبار", "مالتيميديا", "نتائج المباريات", "المزيد", "نتائج", "جدول", "مباريات"]
    clean_name = name.split('-')[0].strip()
    for word in junk:
        clean_name = clean_name.replace(word, "").strip()
    return clean_name if clean_name else name

def get_matches():
    iraq_tz = timezone(timedelta(hours=3))
    today = datetime.now(iraq_tz).strftime("%Y-%m-%d")
    
    api_url = f"https://www.yallakora.com/wamp/api/v1/matches?date={today}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Referer': 'https://www.yallakora.com/match-center/'
    }

    print(f"Requesting API URL: {api_url}")

    try:
        response = requests.get(api_url, headers=headers, timeout=15)
        print(f"Response Status Code: {response.status_code}")
        
        if response.status_code != 200:
            print(f"Error: API returned status code {response.status_code}")
            return []
            
        try:
            data = response.json()
        except json.JSONDecodeError:
            print("Error: Response is not a valid JSON. Preview:")
            print(response.text[:300])
            return []
        
        parsed_matches = []
        championships = data.get('championships', [])
        print(f"Total championships found: {len(championships)}")
        
        for champ in championships:
            league = sanitize_league_name(champ.get('Title', 'مباريات متنوعة'))
            for m in champ.get('matches', []):
                h_score = str(m.get('TeamAScore', '0'))
                a_score = str(m.get('TeamBScore', '0'))
                
                status_code = m.get('MatchStatus')
                if status_code == 1:
                    match_status = "LIVE"
                elif status_code == 2:
                    match_status = "ENDED"
                else:
                    match_status = "UPCOMING"
                
                parsed_matches.append({
                    "id": str(m.get('MatchId', '0')),
                    "homeTeam": m.get('TeamA', {}).get('Name', '').strip(),
                    "homeTeamLogo": m.get('TeamA', {}).get('Logo', '').strip(),
                    "awayTeam": m.get('TeamB', {}).get('Name', '').strip(),
                    "awayTeamLogo": m.get('TeamB', {}).get('Logo', '').strip(),
                    "league": league,
                    "matchTime": m.get('Time', '--:--').strip(),
                    "status": match_status,
                    "score": f"{h_score} - {a_score}",
                    "homeScore": h_score,
                    "awayScore": a_score,
                    "channelName": m.get('Channel', 'غير متوفرة').strip(),
                    "commentator": m.get('Commentator', 'غير محدد').strip()
                })
                
        print(f"Total parsed matches: {len(parsed_matches)}")
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
