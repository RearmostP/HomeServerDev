# גלריית הבית

שרת Python עם SQLite וממשק JavaScript. רכיב OPAQUE של Serenity Kit פועל בדפדפן ובתהליך Node מקומי שהשרת מפעיל רק לצורך האימות.

## התקנה והפעלה

יש להתקין Python 3.10 ומעלה, Node.js 22 ומעלה ו־npm. מתיקיית הפרויקט:

```sh
cd clients/browser
npm install
npm run build
npx @serenity-kit/opaque create-server-setup
cd ../../server
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

שמור את ערך ההתקנה של OPAQUE בסוד ובגיבוי קבוע. החלפתו מבטלת את רישומי הכניסה הקיימים ולכן עלולה למנוע פתיחה של המפתחות. הגדר אותו במשתנה הסביבה OPAQUE_SERVER_SETUP לפני הפעלה.

ב־Debian צור את /server-storage בבעלות משתמש השירות, עם הרשאות 0700, והריץ את השרת כאותו משתמש. גבה את מסד SQLite ואת עץ האחסון יחד. עצור את השירות בזמן גיבוי פשוט באמצעות העתקה. הפעל את השרת עם כתובת ה־HTTPS המדויקת של Tailscale, ללא לוכסן בסוף:

```sh
export GALLERY_ORIGIN=https://machine.example-tailnet.ts.net
.venv/bin/python main.py
```

בחלון נפרד בשירות Tailscale שמור על חשיפה לרשת הפרטית באמצעות:

```sh
tailscale serve http://127.0.0.1:8000
```

השרת מאזין ב־loopback בלבד. אין לחשוף את הפורט ישירות או להפעיל Funnel. כל מי שמורשה לגשת לשירות דרך מדיניות הגישה של ה־tailnet יכול להירשם.

## פיתוח מקומי ב־Windows

השתמש באותה התקנת npm והרצת build. בתיקייה server הרץ ב־PowerShell לאחר הגדרת סוד OPAQUE:

```powershell
$env:GALLERY_LOCAL_HTTP = '1'
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

פתח http://localhost:8000. מצב זה מיועד ל־loopback בלבד. האחסון נוצר ב־server/server-storage.

## שימוש

נרשמים עם שם משתמש, מייל וסיסמה. שם המשתמש קבוע ומכיל 3–24 אותיות אנגליות קטנות, ספרות וקווים תחתונים, ומתחיל באות. האלבום גלריה נוצר אוטומטית בתיקייה 001. מכסת 48 האלבומים כוללת את הגלריה. משתפים עם חשבון קיים לפי שם משתמש. משתתף מקבל הרשאת צפייה. קבצים מתקבלים עד 25MB לתמונה, והמערכת תומכת ב־JPEG, PNG, WebP, GIF ו־AVIF.

תוכן התמונה, השם שלה ומטא־דאטה של התצוגה מוצפנים בדפדפן. שמות אלבומים, הרשאות, פרטי חשבון ופרטי מכשיר גלויים לשרת. יש לסמוך על קוד הדפדפן שהשרת מגיש ועל התאמת מפתח השיתוף הציבורי לחשבון שלו. פתיחת דף מחדש דורשת כניסה כדי לטעון שוב את מפתח הפענוח לזיכרון.

שינוי או איפוס סיסמה ושחזור מפתחות אינם כלולים בגרסה זו.
