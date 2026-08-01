from datetime import datetime
import json
import re
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

def create_safe_session():
    """إنشاء جلسة اتصال محمية مع إعادة المحاولة التلقائية"""
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=2,  # الانتظار 2 ثانية ثم 4 ثواني بين المحاولات
        status_forcelist=[429, 500, 502, 503, 504]
    )
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session

def get_matches_from_yallakora():
    today_str = datetime.now().strftime("%m/%d/%Y")
    url = f"https://www.yallakora.com/match-center?date={today_str}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache'
    }

    print(f"🚀 بدء سحب المباريات آلياً لتاريخ: {today_str}")
    session = create_safe_session()

    try:
        response = session.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"❌ رمز استجابة غير متوقع: {response.status_code}")
            return []

        soup = BeautifulSoup(response.content, "html.parser")
        championships = soup.find_all('div', class_='matchCard')
        
        parsed_matches = []
        match_id = 1

        for champ in championships:
            league_title_elem = champ.find('div', class_='title') or champ.find('h2')
            league_name = league_title_elem.text.strip() if league_title_elem else "مباريات اليوم"
            league_name = re.sub(r'\s+', ' ', league_name).replace('\n', '')

            matches_ul = champ.find('div', class_='allMatches') or champ
            matches = matches_ul.find_all('div', class_='item') or matches_ul.find_all('li')

            for match in matches:
                try:
                    team_a_elem = match.find('div', class_='teamA')
                    home_team = team_a_elem.text.strip() if team_a_elem else ""
                    home_logo = team_a_elem.find('img').get('src', '') if team_a_elem and team_a_elem.find('img') else ""

                    team_b_elem = match.find('div', class_='teamB')
                    away_team = team_b_elem.text.strip() if team_b_elem else ""
                    away_logo = team_b_elem.find('img').get('src', '') if team_b_elem and team_b_elem.find('img') else ""

                    if not home_team or not away_team:
                        continue

                    scores = match.find_all('span', class_='score')
                    score_text = "0 - 0"
                    if len(scores) >= 2:
                        score_text = f"{scores[0].text.strip()} - {scores[1].text.strip()}"

                    time_elem = match.find('span', class_='time')
                    match_time = time_elem.text.strip() if time_elem else "--:--"

                    status_elem = match.find('div', class_='matchStatus') or match.find('span', class_='status')
                    raw_status = status_elem.text.strip() if status_elem else ""
                    
                    status = "UPCOMING"
                    if "جاري" in raw_status or "الشوط" in raw_status or "مباشر" in raw_status:
                        status = "LIVE"
                    elif "انتهت" in raw_status:
                        status = "ENDED"

                    channel_elem = match.find('div', class_='channel')
                    channel_name = channel_elem.text.strip() if channel_elem else "beIN Sports"

                    commentator_elem = match.find('div', class_='commentator')
                    commentator = commentator_elem.text.strip() if commentator_elem else "غير محدد"

                    home_team = re.sub(r'\s+', ' ', home_team)
                    away_team = re.sub(r'\s+', ' ', away_team)

                    parsed_matches.append({
                        "id": str(match_id),
                        "homeTeam": home_team,
                        "homeTeamLogo": home_logo,
                        "awayTeam": away_team,
                        "awayTeamLogo": away_logo,
                        "league": league_name,
                        "matchTime": match_time,
                        "channelName": channel_name,
                        "commentator": commentator,
                        "streamUrl": "",
                        "status": status,
                        "score": score_text
                    })
                    match_id += 1

                except Exception:
                    continue

        return parsed_matches

    except Exception as e:
        print(f"❌ خطأ أثناء الاتصال بالشبكة: {e}")
        return []

if __name__ == "__main__":
    matches_list = get_matches_from_yallakora()
    
    # 🔒 شرط الحماية: لا تقم بتحديث أو مسح الملف إلا إذا تم سحب مباريات فعلياً
    if len(matches_list) > 0:
        with open("matches.json", "w", encoding="utf-8") as f:
            json.dump(matches_list, f, ensure_ascii=False, indent=2)
        print(f"✅ تم تحديث ملف matches.json بنجاح! عدد المباريات: {len(matches_list)}")
    else:
        print("⚠️ لم يتم جلب مباريات جديدة (أو حدث انقطاع). تم الاحتفاظ بالبيانات السابقة لعدم تفريغ القائمة.")
