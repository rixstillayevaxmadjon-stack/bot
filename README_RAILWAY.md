# Telegram xarajat botini Railwayga qo'yish

Bu papka Railway uchun tayyorlangan. Start command allaqachon `railway.json` ichida yozilgan:

```bash
python bot.py
```

## Railway Variables

Railway project ochilgandan keyin `Variables` bo'limiga shularni qo'shing:

| Variable | Qiymati |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | BotFather bergan token |
| `GEMINI_API_KEY` | Google AI Studio dan olingan Gemini API key |
| `GEMINI_MODEL` | `gemini-flash-latest` |
| `APP_TIMEZONE` | `Asia/Tashkent` |

## Deploy qilish

1. Fayllarni GitHub repositoryga yuklang yoki Railwayga project sifatida ulang.
2. Railway o'zi Python loyihani tanib, `requirements.txt` ichidagi kutubxonalarni o'rnatadi.
3. `Variables` bo'limiga tokenlarni kiriting.
4. Deploy tugagach `Logs` bo'limida `Bot ishga tushdi...` chiqsa, bot ishlayapti.

## Baza saqlanishi

Bot SQLite ishlatadi va `xarajatlar.db` faylini o'zi yaratadi. Railway redeploy paytida ma'lumotlar o'chmasligi uchun Railway Volume qo'shib, uni `/data` ga ulang va `Variables` bo'limiga quyidagini kiriting:

```bash
DB_PATH=/data/xarajatlar.db
```

Volume ulanmasa ham bot ishlaydi, lekin redeploy yoki restartlardan keyin eski xarajatlar saqlanmasligi mumkin.
