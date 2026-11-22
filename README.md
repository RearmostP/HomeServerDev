# גלריית הבית

## מה הפרויקט עושה

גלריית הבית מאפשרת לשמור תמונות בשרת ביתי, לצפות בהן מהדפדפן או מאפליקציית Android, ולשתף אלבומים עם משתמשים אחרים לפי שם משתמש. הגישה לשרת בפריסה הביתית עוברת דרך רשת Tailscale פרטית.

התמונות מוצפנות לפני שהן נשלחות לשרת. לכל תמונה יש מפתח אקראי משלה, והוא מוגן במפתח האלבום. המשתמש נכנס עם סיסמה אחת באמצעות OPAQUE ופותח את מפתחות האלבומים בצד הלקוח. שמות אלבומים, הרשאות, פרטי חשבון ומכשירים גלויים לשרת.

לכל חשבון נוצרת אוטומטית גלריה קבועה. אפשר ליצור עד 48 אלבומים כולל הגלריה, ולשתף אלבומים לצפייה. הלקוח תומך בתמונות JPEG, PNG, WebP, GIF ו־AVIF בגודל של עד 25 MB לתמונה. שינוי סיסמה, איפוס סיסמה ושחזור מפתחות עדיין אינם זמינים.

## מה יש במאגר

| רכיב | תיקייה | אחריות |
| --- | --- | --- |
| שרת | [`server/`](server/) | Python ו־SQLite לניהול חשבונות, מכשירים, הרשאות, אלבומים ואחסון הקבצים המוצפנים. רכיב Node.js מקומי מבצע את חלק השרת באימות OPAQUE. |
| ממשק דפדפן | [`clients/browser/`](clients/browser/) | HTML, CSS ו־JavaScript למסכי הגלריה, העלאה, שיתוף והצפנה בדפדפן. |
| אפליקציית Android | [`clients/android/`](clients/android/) | Kotlin וממשק הגלריה המשותף לדפדפן, עם חיבור Tailscale מובנה באמצעות Go ו־`tsnet`. הוראות הבנייה נמצאות ב־[README של האפליקציה](clients/android/README.md). |

### התקנה אוטומטית ב־Debian

מתוך עותק של המאגר במחשב השרת, כמנהל עם גישת `sudo`, הרץ:

```bash
bash install-server.sh
```

הסקריפט תומך ב־Debian עם AMD64 או ARM64. הוא מתקין תלויות, בונה את ממשק הדפדפן, מגדיר שירות `systemd` ומפעיל Tailscale Serve. אם המחשב טרם התחבר ל־Tailscale, פתח את קישור ההתחברות שהפקודה תציג. כאשר נדרש אישור מכשיר, יש לאשר אותו ב־Tailscale. כתובת הגלריה נגזרת משם המחשב ב־Tailnet ומודפסת בסיום. כדי להשתמש בשם `home-server`, הגדר אותו כשם המחשב ב־Debian או כשם המכשיר ב־Tailscale.

קובצי ההגדרה המקומיים נשמרים ב־`/etc/home-gallery/`, והנתונים ב־`/server-storage/`. הרצה חוזרת משתמשת במפתח OPAQUE שכבר נשמר. אם יש נתונים מהתקנה ידנית, שחזר קודם את מפתח OPAQUE המקורי ב־`/etc/home-gallery/opaque.env`, בשורה `OPAQUE_SERVER_SETUP=...`.

### התקנה ידנית והגדרה של השרת ב־Debian

1. התקן Python 3.10 ומעלה, Node.js 22 ומעלה, npm ו־Tailscale. חבר את מחשב השרת ל־Tailnet הפרטי שלך.
2. משורש המאגר, בנה את ממשק הדפדפן, צור ערך הגדרה ראשוני ל־OPAQUE והתקן את תלויות Python.

   ```sh
   cd clients/browser
   npm ci
   npm run build
   npx @serenity-kit/opaque create-server-setup
   cd ../../server
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt
   ```

   שמור את ערך ההגדרה של OPAQUE בסוד ובגיבוי. צור אותו פעם אחת והשתמש בו גם אחרי הפעלה מחדש. החלפתו מבטלת את רישומי האימות הקיימים ועלולה למנוע גישה למפתחות התמונות.

3. צור את תיקיית האחסון ממנה השרת עובד. הפקודה הבאה מקצה אותה למשתמש הנוכחי. אם השרת ירוץ תחת משתמש שירות אחר, הגדר אותו כבעל התיקייה.

   ```sh
   sudo install -d -m 0700 -o "$(id -un)" -g "$(id -gn)" /server-storage
   ```

4. מתוך `server/`, הגדר את כתובת ה־HTTPS המלאה של השרת ב־Tailscale, ללא לוכסן בסוף. החלף את כתובת הדוגמה בכתובת שלך. הדבק את ערך OPAQUE כשהפקודה מבקשת אותו.

   ```bash
   export GALLERY_ORIGIN='https://home-server.example-tailnet.ts.net'
   read -rsp 'OPAQUE_SERVER_SETUP: ' OPAQUE_SERVER_SETUP
   printf '\n'
   export OPAQUE_SERVER_SETUP
   .venv/bin/python main.py
   ```

5. בחלון נפרד, הפעל Tailscale Serve.

   ```sh
   sudo tailscale serve http://127.0.0.1:8000
   ```

   פתח בדפדפן את הכתובת שהוגדרה ב־`GALLERY_ORIGIN` ובחר **יצירת חשבון**. שרת Python מאזין ב־`127.0.0.1:8000`, ו־Tailscale Serve מספק את הגישה דרך ה־Tailnet. כל משתמש שמדיניות הגישה של ה־Tailnet מאפשרת לו להגיע לשירות יכול להירשם.

לגיבוי בהעתקת קבצים, עצור את השרת והעתק יחד את מסד SQLite ואת עץ האחסון שב־`/server-storage/`. שמור בנפרד עותק של ערך ההגדרה של OPAQUE.

### הפעלה מקומית ב־Windows

בנה את ממשק הדפדפן באותן פקודות npm. מתוך `server/`, הגדר ב־PowerShell את `OPAQUE_SERVER_SETUP` לערך שכבר יצרת, ואז הרץ:

```powershell
$env:GALLERY_LOCAL_HTTP = '1'
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

פתח את [הגלריה המקומית](http://localhost:8000/). האחסון המקומי נוצר ב־`server/server-storage/`.
