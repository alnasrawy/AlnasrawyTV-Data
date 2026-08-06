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
    # تعديل تنسيق التاريخ ليوافق المعيار القياسي الأكثر قبولاً لدى الـ APIs
    today = datetime.now(iraq_tz).strftime("%Y-%m-%d")
    
    url = f"https://www.yallakora.com/api/v1/matches?date={today}"
    headers = {'User-Agent': 'Mozilla/5.0'}

    print(f"Requesting URL: {url}")

    try:
        response = requests.get(url, headers=headers, timeout=10)
        print(f"Response Status Code: {response.status_code}")
        
        if response.status_code != 200:
            print(f"Error: API returned status code {response.status_code}")
            return []
            
        data = response.json()
        parsed_matches = []
        
        championships = data.get('championships', [])
        print(f"Total championships found: {len(championships)}")
        
        for champ in championships:
            league = sanitize_league_name(champ.get('Title', 'مباريات متنوعة'))
            for m in champ.get('matches', []):
                h_score = str(m.get('TeamAScore', '0'))
                a_score = str(m.get('TeamBScore', '0'))
                
                parsed_matches.append({
                    "id": str(m.get('MatchId', '0')),
                    "homeTeam": m.get('TeamA', {}).get('Name', '').strip(),
                    "homeTeamLogo": m.get('TeamA', {}).get('Logo', '').strip(),
                    "awayTeam": m.get('TeamB', {}).get('Name', '').strip(),
                    "awayTeamLogo": m.get('TeamB', {}).get('Logo', '').strip(),
                    "league": league,
                    "matchTime": m.get('Time', '--:--').strip(),
                    "status": "LIVE" if m.get('MatchStatus') == 1 else "ENDED" if m.get('MatchStatus') == 2 else "UPCOMING",
                    "score": f"{h_score} - {a_score}",
                    "homeScore": h_score,
                    "awayScore": a_score,
                    "channelName": m.get('Channel', 'غير متوفرة'),
                    "commentator": m.get('Commentator', 'غير محدد')
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
