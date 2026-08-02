from datetime import datetime
import json
import requests

def get_matches_from_yallakora_api():
    today_str = datetime.now().strftime("%m/%d/%Y")
    # رابط الـ API المباشر الذي يعتمد عليه موقع يلاكورة لجلب المباريات
    url = f"https://www.yallakora.com/api/v1/matches?date={today_str}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*'
    }

    print(f"🚀 بدء سحب المباريات عبر API لتاريخ: {today_str}")

    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"❌ رمز استجابة غير متوقع: {response.status_code}")
            return []

        data = response.json()
        parsed_matches = []
        match_id = 1

        # استخراج البطولات والمباريات من هيكل الـ JSON القادم
        championships = data.get('championships', [])
        
        for champ in championships:
            league_name = champ.get('Title', 'مباريات اليوم')
            matches = champ.get('matches', [])

            for match in matches:
                try:
                    home_team = match.get('TeamA', {}).get('Name', '')
                    home_logo = match.get('TeamA', {}).get('Logo', '')

                    away_team = match.get('TeamB', {}).get('Name', '')
                    away_logo = match.get('TeamB', {}).get('Logo', '')

                    if not home_team or not away_team:
                        continue

                    match_time = match.get('Time', '--:--')
                    
                    # النتيجة
                    home_score = match.get('TeamAScore', 0)
                    away_score = match.get('TeamBScore', 0)
                    score_text = f"{home_score} - {away_score}"

                    # حالة المباراة (0 لم تبدأ، 1 جارية، 2 انتهت - حسب نظامهم)
                    match_status = match.get('MatchStatus', 0)
                    status = "UPCOMING"
                    if match_status == 1:
                        status = "LIVE"
                    elif match_status == 2:
                        status = "ENDED"

                    channel_name = match.get('Channel', 'beIN Sports')
                    commentator = match.get('Commentator', 'غير محدد')

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
    matches_list = get_matches_from_yallakora_api()
    
    if len(matches_list) > 0:
        with open("matches.json", "w", encoding="utf-8") as f:
            json.dump(matches_list, f, ensure_ascii=False, indent=2)
        print(f"✅ تم تحديث ملف matches.json بنجاح! عدد المباريات: {len(matches_list)}")
    else:
        print("⚠️ لم يتم جلب مباريات جديدة. تم الاحتفاظ بالبيانات السابقة.")
