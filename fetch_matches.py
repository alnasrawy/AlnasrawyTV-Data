import json
import requests
from datetime import datetime, timezone, timedelta

def sanitize_league_name(name):
    # تنظيف الأسماء من الكلمات العشوائية التي تشوه التصميم
    junk = ["أخبار", "مالتيميديا", "نتائج المباريات", "المزيد", "نتائج", "جدول", "مباريات"]
    clean_name = name.split('-')[0].strip() # نأخذ الاسم الأساسي قبل الشرطة
    for word in junk:
        clean_name = clean_name.replace(word, "").strip()
    return clean_name if clean_name else name

def get_matches():
    # ضبط التوقيت لضمان دقة جلب البيانات
    iraq_tz = timezone(timedelta(hours=3))
    today = datetime.now(iraq_tz).strftime("%m/%d/%Y")
    
    url = f"https://www.yallakora.com/api/v1/matches?date={today}"
    headers = {'User-Agent': 'Mozilla/5.0'}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()
        parsed_matches = []
        
        for champ in data.get('championships', []):
            league = sanitize_league_name(champ.get('Title', 'مباريات متنوعة'))
            for m in champ.get('matches', []):
                h_score = str(m.get('TeamAScore', '0'))
                a_score = str(m.get('TeamBScore', '0'))
                
                # بناء هيكل البيانات المطور المتوافق مع التطبيق
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
                    "homeScore": h_score, # 🚀 إرسال النتيجة كحقل منفصل
                    "awayScore": a_score, # 🚀 إرسال النتيجة كحقل منفصل
                    "channelName": m.get('Channel', 'غير متوفرة'),
                    "commentator": m.get('Commentator', 'غير محدد')
                })
        return parsed_matches
    except: return []

if __name__ == "__main__":
    matches = get_matches()
    if matches:
        with open("matches.json", "w", encoding="utf-8") as f:
            json.dump(matches, f, ensure_ascii=False, indent=2)
