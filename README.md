# AlnasrawyTV-Data

نظام آلي يجمع مباريات ysscores، يولّد كروت قبل المباراة/النتيجة، وينشرها على تيليجرام.

> ⚠️ **مرحلة اختبار** — قبل النشر النهائي على VPS. كل شيء يعمل محلياً أولاً.

## المكوّنات

| جزء | ملفات |
|---|---|
| 1. طبقة البيانات (سحب/تحليل) | `data_layer/` |
| 2. توليد الصور (كروت عربية) | `renderer/` |
| 3. مخزن الحالة (منع التكرار) | `state_store/` |
| 4. المجدول الذكي (خمول/نشط) | `scheduler.py` |
| 5. النشر على تيليجرام | `telegram_publisher.py`, `config.py` |
| نقطة التشغيل الموحدة | `main.py` |

## التشغيل محلياً

```bash
git clone https://github.com/alnasrawy/AlnasrawyTV-Data.git
cd AlnasrawyTV-Data
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # Linux
pip install -r requirements.txt

# 1) إعداد المتغيرات
cp .env.example .env              # ثم عبّئ القيم الحقيقية

# 2) فحص آمن بدون نشر (يطبع بيانات اليوم فقط)
python main.py --test-day today --max-details 3

# 3) التشغيل الفعلي (مجدول دائم: صحوة/نوم)
python main.py
```

## متغيرات البيئة (`.env`)

| متغير | مطلوب | الوصف |
|---|---|---|
| `TG_BOT_TOKEN` | نعم للنشر | توكن البوت من @BotFather |
| `TG_CHANNELS` | نعم للنشر | ids مفصولة بفواصل (قناة/مجموعة/خاص) |
| `TG_ADMIN_CHAT_ID` | نعم للتنبيهات | بوتY محادثة خاصة للتنبيهات التشغيلية |
| `IMAGE_DIR` | اختياري | مجلد الصور المولّدة (افتراضي `out_imgs/`) |

التوقيت مثبّت داخلياً على **Asia/Baghdad**.

## الاختبارات

```bash
python state_store\selftest.py      # مخزن الحالة: 16 فحص (منع التكرار + إعادة تشغيل)
python scheduler_selftest.py        # المجدول: 14 فحص (أوضاع + محاكاة يوم كامل وساعة)
```

## النشر على VPS (Linux + systemd)

1. نقل الكود أول مرة:
```bash
apt install python3-venv git
git clone https://github.com/alnasrawy/AlnasrawyTV-Data.git /opt/alnasrawy
cd /opt/alnasrawy
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env   # القيم الحقيقية
```

2. تفعيل الخدمة (إعادة تشغيل تلقائية عند الانهيار/إعادة تشغيل السيرفر):
```bash
cp deploy/alnasrawy-tv-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable alnasrawy-tv-bot   # تُقلع مع النظام
systemctl start alnasrawy-tv-bot
journalctl -u alnasrawy-tv-bot -f   # متابعة اللوج مباشرة
systemctl restart alnasrawy-tv-bot  # بعد أي تحديث
```

3. التحديث لاحقاً:
```bash
cd /opt/alnasrawy && git pull
systemctl restart alnasrawy-tv-bot
```

> أنشئ مستخدماً مخصصاً (`adduser deploy`) وعدّل `User=` في ملف الخدمة إن لم ترد التشغيل بصلاحيات أعلى.