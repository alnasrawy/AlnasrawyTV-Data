from datetime import datetime
import json
import re
import requests
from bs4 import BeautifulSoup


def clean_text(text):
  """تنظيف النصوص من الفراغات والسطور الزائدة"""
  return re.sub(r"\s+", " ", text).strip() if text else ""


def get_match_status(status_text):
  """تحويل حالة المباراة إلى الصيغة الموحدة للتطبيق"""
  if not status_text:
    return "UPCOMING"
  status_text = status_text.strip()
  if "جاري" in status_text or "الشوط" in status_text or "مباشر" in status_text:
    return "LIVE"
  elif "انتهت" in status_text or "خارج" in status_text:
    return "ENDED"
  return "UPCOMING"


def fetch_todays_matches():
  today_str = datetime.now().strftime("%Y-%m-%d")
  url = f"https://www.filgoal.com/sections/matches/?date={today_str}"

  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
          " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
      )
  }

  print(f"🚀 بدء سحب المباريات ليوم: {today_str}")

  try:
    response = requests.get(url, headers=headers, timeout=15)
    if response.status_code != 200:
      print(f"❌ فشل الاتصال بالموقع. رمز الاستجابة: {response.status_code}")
      return []

    soup = BeautifulSoup(response.content, "html.parser")
    match_blocks = soup.find_all("div", class_="mc-block")

    parsed_matches = []
    match_counter = 1

    for block in match_blocks:
      # اسم البطولة
      league_elem = block.find("h3") or block.find("div", class_="title")
      league_name = (
          clean_text(league_elem.text) if league_elem else "مباريات اليوم"
      )

      # عناصر المباريات داخل البطولة
      match_items = block.find_all("div", class_="match-aux")

      for match in match_items:
        try:
          # أسماء الفريقين
          teams = match.find_all("div", class_="team")
          if len(teams) < 2:
            continue

          home_team = clean_text(teams[0].find("strong").text)
          away_team = clean_text(teams[1].find("strong").text)

          # شعارات الفريقين
          home_logo_img = teams[0].find("img")
          away_logo_img = teams[1].find("img")
          home_logo = (
              home_logo_img.get("src", "")
              if home_logo_img
              else "https://via.placeholder.com/60"
          )
          away_logo = (
              away_logo_img.get("src", "")
              if away_logo_img
              else "https://via.placeholder.com/60"
          )

          # النتيجة وحالة المباراة
          scores = match.find_all("b", class_="score")
          score_text = "0 - 0"
          if len(scores) >= 2:
            score_text = (
                f"{clean_text(scores[0].text)} - {clean_text(scores[1].text)}"
            )

          status_elem = match.find("span", class_="status")
          raw_status = clean_text(status_elem.text) if status_elem else ""
          status = get_match_status(raw_status)

          # توقيت المباراة
          time_elem = match.find("span", class_="time")
          match_time = clean_text(time_elem.text) if time_elem else "--:--"

          # القناة والمعلق
          details_elem = match.find("div", class_="match-details")
          channel_name = "غير محدد"
          commentator = "غير محدد"

          if details_elem:
            channel_elem = details_elem.find("span", class_="channel")
            comm_elem = details_elem.find("span", class_="commentator")
            if channel_elem:
              channel_name = clean_text(channel_elem.text)
            if comm_elem:
              commentator = clean_text(comm_elem.text)

          parsed_matches.append({
              "id": str(match_counter),
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
          match_counter += 1

        except Exception as e:
          print(f"⚠️ خطأ أثناء قراءة مباراة: {e}")
          continue

    return parsed_matches

  except Exception as e:
    print(f"❌ خطأ عام أثناء السحب: {e}")
    return []


if __name__ == "__main__":
  matches_list = fetch_todays_matches()

  # حفظ النتيجة بداخل ملف matches.json
  with open("matches.json", "w", encoding="utf-8") as f:
    json.dump(matches_list, f, ensure_ascii=False, indent=2)

  print(
      f"✅ تم تحديث ملف matches.json بنجاح! عدد المباريات:"
      f" {len(matches_list)}"
  )
