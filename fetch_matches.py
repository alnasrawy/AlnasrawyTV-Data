from datetime import datetime
import json
import re
import requests
from bs4 import BeautifulSoup


def get_matches_from_yallakora():
  today_str = datetime.now().strftime("%m/%d/%Y")  # صيغة التاريخ لموقع يلا كورة
  url = f"https://www.yallakora.com/match-center?date={today_str}"

  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
          " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
      ),
      "Accept-Language": "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
  }

  print(f"🚀 جاري سحب المباريات من يلا كورة لتاريخ: {today_str}")

  try:
    response = requests.get(url, headers=headers, timeout=15)
    if response.status_code != 200:
      print(f"❌ رمز استجابة غير متوقع: {response.status_code}")
      return []

    soup = BeautifulSoup(response.content, "html.parser")
    championships = soup.find_all("div", class_="matchCard")

    parsed_matches = []
    match_id = 1

    for champ in championships:
      # اسم البطولة
      league_title_elem = champ.find("div", class_="title") or champ.find("h2")
      league_name = (
          league_title_elem.text.strip() if league_title_elem else "مباريات اليوم"
      )
      league_name = re.sub(r"\s+", " ", league_name).replace("\n", "")

      # المباريات داخل البطولة
      matches_ul = champ.find("div", class_="allMatches") or champ
      matches = matches_ul.find_all("div", class_="item") or matches_ul.find_all(
          "li"
      )

      for match in matches:
        try:
          # الفريق الأول
          team_a_elem = match.find("div", class_="teamA")
          home_team = team_a_elem.text.strip() if team_a_elem else ""
          home_logo = ""
          if team_a_elem and team_a_elem.find("img"):
            home_logo = team_a_elem.find("img").get("src", "")

          # الفريق الثاني
          team_b_elem = match.find("div", class_="teamB")
          away_team = team_b_elem.text.strip() if team_b_elem else ""
          away_logo = ""
          if team_b_elem and team_b_elem.find("img"):
            away_logo = team_b_elem.find("img").get("src", "")

          if not home_team or not away_team:
            continue

          # النتيجة
          scores = match.find_all("span", class_="score")
          score_text = "0 - 0"
          if len(scores) >= 2:
            score_text = f"{scores[0].text.strip()} - {scores[1].text.strip()}"

          # الوقت
          time_elem = match.find("span", class_="time")
          match_time = time_elem.text.strip() if time_elem else "--:--"

          # الحالة
          status_elem = match.find("div", class_="matchStatus") or match.find(
              "span", class_="status"
          )
          raw_status = status_elem.text.strip() if status_elem else ""

          status = "UPCOMING"
          if (
              "جاري" in raw_status
              or "الشوط" in raw_status
              or "مباشر" in raw_status
          ):
            status = "LIVE"
          elif "انتهت" in raw_status:
            status = "ENDED"

          # القناة والمعلق
          channel_elem = match.find("div", class_="channel")
          channel_name = (
              channel_elem.text.strip() if channel_elem else "beIN Sports"
          )

          commentator_elem = match.find("div", class_="commentator")
          commentator = (
              commentator_elem.text.strip() if commentator_elem else "غير محدد"
          )

          # تنظيف أسماء الفرق
          home_team = re.sub(r"\s+", " ", home_team)
          away_team = re.sub(r"\s+", " ", away_team)

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
              "score": score_text,
          })
          match_id += 1

        except Exception as e:
          continue

    return parsed_matches

  except Exception as e:
    print(f"❌ خطأ أثناء السحب: {e}")
    return []


if __name__ == "__main__":
  matches_list = get_matches_from_yallakora()

  # حفظ النتيجة في ملف matches.json
  with open("matches.json", "w", encoding="utf-8") as f:
    json.dump(matches_list, f, ensure_ascii=False, indent=2)

  print(
      f"✅ تم سحب وتحديث {len(matches_list)} مباراة بنجاح في ملف matches.json!"
  )
