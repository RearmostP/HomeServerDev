# גלריית הבית | Android

אפליקציית Kotlin שמשתמשת באותם מסכים, CSS והצפנה כמו הדפדפן. היא אורזת את קוד הגלריה מקומית ומעבירה רק את בקשות ה־API לשרת `https://home-server.example-tailnet.ts.net` דרך צומת `tsnet` מובנה. אין רכיב VPN או פרוקסי ששאר האפליקציות יכולות להשתמש בו.

## חלוקת הפרויקט

- `app/` — מסך החיבור ל־Tailscale, WebView, מעברי מסך ובחירת תמונות.
- `server-api/` — הגישור בין בקשות JavaScript לתעבורת HTTP של הגלריה.
- `network/` — צומת Go, חיבורי HTTPS ב־Tailnet ועטיפת Kotlin.
- `crypto/` — תיעוד החיבור למימוש ההצפנה המשותף עם הדפדפן.
- `backup/` — מקום למודול גיבוי עתידי.

## בנייה ב־Windows

יעד הריצה הוא Android 8 ומעלה. בניית ברירת המחדל כוללת ARM64 למכשירים ו־x86_64 לאמולטור. נדרשים Go עם הורדת toolchain אוטומטית, JDK 17 ומעלה, Android SDK עם פלטפורמה 37, NDK r28c ו־Node.js עם npm. יש להגדיר `JAVA_HOME`, `ANDROID_HOME` ו־`ANDROID_NDK_HOME` לפי מיקומי ההתקנה. Go ו־npm צריכים להיות ב־PATH.

צור קובץ מקומי בשם `clients/android/server-host.local.txt` עם שם המארח בשורה אחת, למשל `home-server.example-tailnet.ts.net`. הזן רק את שם המארח. הקובץ מוחרג מ־Git והכתובת נארזת בתוך ה־APK.

מתיקיית `clients/android`:

```powershell
Push-Location ..\browser
npm ci
npm run build
Pop-Location
powershell -ExecutionPolicy Bypass -File .\network\build.ps1
.\gradlew.bat :app:assembleDebug
```

ה־APK נוצר ב־`app/build/outputs/apk/debug/app-debug.apk`. גרסת debug מיועדת להתקנה מקומית. אפשר להעביר `-Targets android/arm64` לסקריפט כדי לבנות רק למכשיר ARM64.

## חיבור ראשון

1. יש להפעיל את שרת הגלריה דרך Tailscale Serve, לוודא שכתובת ה־HTTPS בחיבור תואמת ל־`GALLERY_ORIGIN`, ולהפעיל Device Approval ב־Tailnet.
2. יש להזמין את המשתמש ל־Tailnet ולוודא שמדיניות הגישה מאפשרת לו להתחבר ל־HTTPS של שרת הגלריה.
3. המשתמש פותח את האפליקציה ולוחץ על **התחברות ל־Tailscale**. ההזדהות מתבצעת בדפדפן מול Tailscale.
4. המנהל מאשר בממשק Machines את הצומת בשם `home-gallery-…`. כשבדיקת ה־HTTPS מצליחה, האפליקציה פותחת את מסך הכניסה לגלריה.

האפליקציה משתמשת באותה זהות צומת בהפעלות הבאות. זהות Tailscale נשמרת באזור פרטי של האפליקציה שמוחרג מגיבויי Android. חיבור מחדש לחשבון מחליף את הזהות המקומית ויצריך אישור חדש. ניתן להסיר את הצומת הישן דרך Machines.

## דוגמה מתוך שכבת Kotlin

```kotlin
// לאחר התחברות ואישור. להריץ מחוץ ל־UI thread.
val connection = TailnetConnection(stateDirectory, "home-gallery-example", "home-server.example-tailnet.ts.net")
connection.use {
    if (it.status().state == "Running") {
        it.probe()
        val result = it.request("GET", "/api/albums", "", "")
        // 401 לפני כניסה לחשבון הגלריה. לאחר הכניסה, עוגיית החשבון נשמרת בלקוח.
        println(result.getInt("status"))
    }
}
```
