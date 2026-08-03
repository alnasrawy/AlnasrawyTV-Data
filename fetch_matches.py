from datetime import datetime
import json
import requests

def get_matches_from_yallakora_api():
    # استخدام الصيغة القياسية للتاريخ التي تتوافق مع خوادم الـ API
    today_str = datetime.now().strftime("%m/%d/%Y")
    url = f"https://www.yallakora.com/api/v1/matches?date={today_str}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*'
    }

    print(f"🚀 بدء سحب مباريات اليوم لتاريخ: {today_str}")

    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"❌ رمز استجابة غير متوقع من الخادم: {response.status_code}")
            return []

        data = response.json()
        parsed_matches = []
        match_id = 1

        championships = data.get('championships', [])
        
        for champ in championships:
            league_name = champ.get('Title', 'مباريات اليوم').strip()
            matches = champ.get('matches', [])

            for match in matches:
                try:
                    # استخراج بيانات الفريق الأول (المستضيف)
                    team_a = match.get('TeamA', {})
                    home_team = team_a.get('Name', '').strip()
                    home_logo = team_a.get('Logo', '').strip()

                    # استخراج بيانات الفريق الثاني (الضيف)
                    team_b = match.get('TeamB', {})
                    away_team = team_b.get('Name', '').strip()
                    away_logo = team_b.get('Logo', '').strip()

                    if not home_team or not away_team:
                        continue

                    match_time = match.get('Time', '--:--').strip()
                    
                    # النتيجة
                    home_score = match.get('TeamAScore', 0)
                    away_score = match.get('TeamBScore', 0)
                    score_text = f"{home_score} - {away_score}"

                    # حالة المباراة (0 لم تبدأ، 1 جارية، 2 انتهت)
                    match_status = match.get('MatchStatus', 0)
                    status = "UPCOMING"
                    if match_status == 1:
                        status = "LIVE"
                    elif match_status == 2:
                        status = "ENDED"

                    # جلب اسم القناة الناقلة بدقة وتجنب القيم الفارغة
                    channel_name = match.get('Channel', '').strip()
                    if not channel_name:
                        channel_name = "غير متوفرة"
                        
                    # جلب اسم المعلق
                    commentator = match.get('Commentator', '').strip()
                    if not commentator:
                        commentator = "غير محدد"

                    parsed_matches.append({
                        "id": str(match_id),
                        "homeTeam": home_team,
                        "homeTeamLogo": home_logo,  # جلب رابط شعار الفريق الأول بوضوح
                        "awayTeam": away_team,
                        "awayTeamLogo": away_logo,  # جلب رابط شعار الفريق الثاني بوضوح
                        "league": league_name,
                        "matchTime": match_time,
                        "channelName": channel_name,
                        "commentator": commentator,
                        "streamUrl": "",  # يُترك فارغاً للربط اليدوي من لوحة التحكم
                        "status": status,
                        "score": score_text
                    })
                    match_id += 1

                except Exception as inner_e:
                    print(f"⚠️ خطأ أثناء معالجة مباراة واحدة: {inner_e}")
                    continue

        return parsed_matches

    except Exception as e:
        print(f"❌ خطأ أثناء الاتصال بالشبكة: {e}")
        return []

if __name__ == "__main__":
    matches_list = get_matches_from_yallakora_api()
    
    # شرط الحماية: الكتابة فقط إذا تم جلب مباريات جديدة، لمنع تفريغ الملف خطأً
    if len(matches_list) > 0:
        # الكتابة بنظام "w" لضمان تحديث مباريات اليوم فقط وإزالة مباريات الأيام القديمة المنتهية
        with open("matches.json", "w", encoding="utf-8") as f:
            json.dump(matches_list, f, ensure_ascii=False, indent=2)
        print(f"✅ تم تحديث ملف matches.json بمباريات اليوم بنجاح! إجمالي المباريات: {len(matches_list)}")
    else:
        print("⚠️ لم يتم جلب أي مباريات جديدة. تم الاحتفاظ بالملف القديم لحماية البيانات.")
