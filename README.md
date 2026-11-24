# גלריית הבית

## מה הפרויקט עושה

גלריית הבית מאפשרת לשמור תמונות בשרת ביתי, לצפות בהן מהדפדפן או מאפליקציית Android, ולשתף אלבומים עם משתמשים אחרים לפי שם משתמש. הגישה לשרת בפריסה הביתית עוברת דרך רשת Tailscale פרטית.

התמונות מוצפנות לפני שהן נשלחות לשרת. תמונות חדשות מוצפנות באמצעות מפתח האלבום. לקוחות מעודכנים יכולים לפתוח גם תמונות שנשמרו בפורמט הקודם, שבו לכל תמונה היה מפתח משלה. המשתמש נכנס עם סיסמה אחת באמצעות OPAQUE ופותח את מפתחות האלבומים בצד הלקוח. שמות אלבומים, הרשאות, פרטי חשבון ומכשירים גלויים לשרת.

לכל חשבון נוצרת אוטומטית גלריה קבועה. אפשר ליצור עד 48 אלבומים כולל הגלריה, ולשתף אלבומים לצפייה. הלקוח תומך בתמונות JPEG, PNG, WebP, GIF ו־AVIF בגודל של עד 25 MB לתמונה. שינוי סיסמה, איפוס סיסמה ושחזור מפתחות עדיין אינם זמינים.

## מה יש במאגר

| רכיב | תיקייה | אחריות |
| --- | --- | --- |
| שרת | [`server/`](server/) | Python ו־SQLite לניהול חשבונות, מכשירים, הרשאות, אלבומים ואחסון הקבצים המוצפנים. רכיב Node.js מקומי מבצע את חלק השרת באימות OPAQUE. |
| ממשק דפדפן | [`clients/browser/`](clients/browser/) | HTML, CSS ו־JavaScript למסכי הגלריה, העלאה, שיתוף והצפנה בדפדפן. |
| אפליקציית Android | [`clients/android/`](clients/android/) | Kotlin וממשק הגלריה המשותף לדפדפן, עם חיבור Tailscale מובנה באמצעות Go ו־`tsnet`. הוראות הבנייה נמצאות ב־[README של האפליקציה](clients/android/README.md). |

### ניווט בקוד השרת

`server/main.py` הוא נקודת הכניסה. ההרכבה וההגדרות נמצאות ב־`server/gallery/app.py` וב־`server/gallery/configuration.py`; אתחול Waitress ו־RoleForge/Tailscale ב־`server/gallery/server_runtime.py` וב־`server/gallery/tailscale.py`. מסלולי HTTP מקובצים תחת `server/gallery/routes/`: `authentication.py` לאימות ול־sessions, `account.py` למכשירים וליציאה, `albums.py` לאלבומים ולשיתוף, ו־`photos.py` לתמונות. שירותים משותפים נמצאים תחת `server/gallery/services/`: `username.py` לכללי שם המשתמש, `authorization.py` להרשאות אלבום, `photo_storage.py` ו־`storage.py` לנתיבי הקבצים ותיקיית הנתונים, `database.py` ל־SQLite, `opaque.py` לאימות OPAQUE דרך Node, ו־`request_utils.py` לבדיקת בקשות.

### בניית APK לכתובת השרת שלך

מתוך שורש המאגר, על Windows או Linux עם מעבד x86-64 ו־Python 3.10 ומעלה, הרץ:

```sh
python3 build-android.py
```

ב־Windows השתמש ב־`python build-android.py`. הסקריפט ישתמש בכתובת השמורה במחשב או ינסה לזהות את `home-server` דרך Tailscale. אם הכתובת חסרה, הוא יבקש אותה. אפשר להזין כתובת מראש באמצעות `--server https://home-server.example-tailnet.ts.net/`.

הסקריפט משתמש בכלי הבנייה הזמינים ומוריד את החסרים. בהתקנה ראשונה ייתכן שתתבקש לאשר את רישיונות Android SDK. ה־APK נוצר ב־`clients/android/app/build/outputs/apk/debug/app-debug.apk`. הכתובת נשמרת בקובץ הגדרות מקומי המוחרג מ־Git ומוטמעת ב־APK שנוצר.

### התקנה אוטומטית ב־Debian

מתוך עותקים של שני המאגרים באותה תיקיית אב במחשב השרת, כמנהל עם גישת `sudo`, הרץ את הסקריפט מתוך HomeServerDev:

```bash
bash install-server.sh
```

הסקריפט תומך ב־Debian עם AMD64 או ARM64. הוא מוריד ומתקין את Wheel המתאים מ־GitHub Release של RoleForge בגרסה 0.2.1: `manylinux_2_34_x86_64` ל־AMD64 ו־`manylinux_2_34_aarch64` ל־ARM64. אם Asset של הארכיטקטורה חסר, ההתקנה נעצרת עם הודעה מפורשת. הסקריפט אינו תלוי במאגר RoleForge מקומי או ב־PyPI. הוא בונה את ממשק הדפדפן ומגדיר שירות `systemd` שמפעיל את הצומת המוטמע. הוא מבקש כתובת HTTPS מלאה ומפתח Tailscale; המפתח נשמר בקובץ מקומי מוגן תחת `/etc/home-gallery/` ואינו נכתב ליומן או למאגר.

החיבור בצד השרת מסופק על ידי RoleForge וה־`tsnet` שלו בלבד: הסקריפט אינו מתקין את `tailscaled`, ואם שירות מערכת ישן קיים הוא עוצר ומבטל אותו. אין שימוש ב־Tailscale Serve. יש להפעיל HTTPS certificates ל־Tailnet בהגדרות Tailscale ולאשר את צומת `home-gallery` אם מופעל Device Approval. כתובת הגלריה היא `https://home-gallery.<tailnet>.ts.net/`; ה־proxy משתמש ב־HTTPS בפורט 443, ולכן ממשק הדפדפן נשאר ב־secure context הדרוש ל־Web Crypto. לקוחות הטלפון נשארים חלק מההגדרה ומשתמשים ב־Tailscale שלהם כדי להגיע לאותה כתובת HTTPS.

קובצי ההגדרה המקומיים נשמרים ב־`/etc/home-gallery/`, והנתונים ב־`/server-storage/`. הרצה חוזרת משתמשת במפתח OPAQUE שכבר נשמר. אם יש נתונים מהתקנה ידנית, שחזר קודם את מפתח OPAQUE המקורי ב־`/etc/home-gallery/opaque.env`, בשורה `OPAQUE_SERVER_SETUP=...`.

### התקנה ידנית והגדרה של השרת ב־Debian

1. התקן Python 3.10 ומעלה, Node.js 22 ומעלה ו־npm. אין להתקין Tailscale system-wide בשרת; אם `tailscaled` משירות התקנה ישן פעיל, עצור והשבת אותו לפני ההפעלה הידנית.
2. משורש HomeServerDev, בנה את ממשק הדפדפן, צור ערך הגדרה ראשוני ל־OPAQUE והתקן את תלויות Python ואת Wheel של RoleForge 0.2.1 מה־GitHub Release המתאים לארכיטקטורה.

   ```sh
   cd clients/browser
   npm ci
   npm run build
   npx @serenity-kit/opaque create-server-setup
   cd ../../server
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt
   # AMD64:
   .venv/bin/python -m pip install --no-deps https://github.com/RearmostP/RoleForge/releases/download/v0.2.1/roleforge-0.2.1-cp310-abi3-manylinux_2_34_x86_64.whl
   # ARM64 — החלף את הפקודה הקודמת ב:
   # .venv/bin/python -m pip install --no-deps https://github.com/RearmostP/RoleForge/releases/download/v0.2.1/roleforge-0.2.1-cp310-abi3-manylinux_2_34_aarch64.whl
   ```

   שמור את ערך ההגדרה של OPAQUE בסוד ובגיבוי. צור אותו פעם אחת והשתמש בו גם אחרי הפעלה מחדש. החלפתו מבטלת את רישומי האימות הקיימים ועלולה למנוע גישה למפתחות התמונות.

3. ודא שהמשתמש שמריץ את השרת יכול לקרוא את `/etc/home-gallery/tailscale.env`, עם מפתח `TAILSCALE_AUTH_KEY`, וכתוב אותו בהרשאות `0640` לקבוצה של המשתמש. אל תשמור מפתח ב־`.rfg`, בפקודת shell או במאגר. `server/home-gallery-host-settings.rfg` מגדיר את צומת `home-gallery`, יעד מקומי ב־`127.0.0.1:8000`, HTTPS בפורט 443 ומצב `tsnet` קבוע ב־`/server-storage/tailscale`.

   ```sh
   sudo install -d -m 0700 -o "$(id -un)" -g "$(id -gn)" /server-storage
   ```

4. מתוך `server/`, הגדר את ה־HTTPS origin המדויק של צומת ה־Tailscale, ללא לוכסן בסוף, ואת ערך OPAQUE שכבר יצרת. יש להפעיל HTTPS certificates ל־Tailnet בהגדרות Tailscale.

   ```bash
   export GALLERY_ORIGIN='https://home-gallery.example-tailnet.ts.net'
   read -rsp 'OPAQUE_SERVER_SETUP: ' OPAQUE_SERVER_SETUP
   printf '\n'
   export OPAQUE_SERVER_SETUP
   export GALLERY_TAILSCALE_ROLE=1
   .venv/bin/python main.py
   ```

5. פתח בדפדפן את `GALLERY_ORIGIN` ובחר **יצירת חשבון**. שרת Python מאזין מקומית; ה־Role של RoleForge מקבל בקשות HTTPS דרך ה־Tailnet ומעביר אותן אליו. יש לוודא ששם ה־DNS שה־Role קיבל תואם ל־`GALLERY_ORIGIN`.

לגיבוי בהעתקת קבצים, עצור את השרת והעתק יחד את מסד SQLite ואת עץ האחסון שב־`/server-storage/`, כולל מצב `tsnet` כדי לשמר את זהות הצומת. שמור בנפרד את ערך OPAQUE ואת קובץ מפתח Tailscale באופן מוצפן ומוגן.

### הפעלה מקומית ב־Windows

בנה את ממשק הדפדפן באותן פקודות npm. מתוך `server/`, הגדר ב־PowerShell את `OPAQUE_SERVER_SETUP` לערך שכבר יצרת, ואז הרץ בלי להגדיר `GALLERY_TAILSCALE_ROLE`. `localhost` נשאר נתיב פיתוח מקומי ואינו בודק Tailscale או את פריסת Debian:

```powershell
$env:GALLERY_LOCAL_HTTP = '1'
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

פתח את [הגלריה המקומית](http://localhost:8000/). האחסון המקומי נוצר ב־`server/server-storage/`.
