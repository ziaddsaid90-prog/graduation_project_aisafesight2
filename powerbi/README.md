# تقرير AI SafeSight على Power BI (داتا CHV)

| الملف | إيه ده |
|---|---|
| `data/CHV_PowerBI.xlsx` | الداتا كلها في ملف واحد (6 جداول): ده اللي بندخّله في Power BI |
| `data/*.csv` | نفس الجداول كملفات CSV منفصلة |
| `data/خطوات_Power_BI.md` | الخطوات بالعربي: الربط، والمقاييس، والرسوم، والأرقام اللي المفروض تظهر |
| `data/POWERBI_GUIDE.md` | الشرح الأصلي للداتا (إنجليزي) |
| `AI_SafeSight_CHV.pbix` | التقرير نفسه (افتحه بـ Power BI Desktop) |
| `AI_SafeSight_CHV.pdf` | التقرير متصدّر PDF: **ده اللي بيظهر في الموقع** |
| `safesight-theme.json` | ألوان المشروع (View ← Themes ← Browse for themes) |

## التقرير بيظهر في الموقع إزاي
الـ Dashboard بيعرض `AI_SafeSight_CHV.pdf` في قسم **Power BI report**، وده لـ Project Manager وHSE بس (صلاحية `view_reports`). والـ API بيقدّمه من `GET /bi-report`.

**بعد أي تعديل في التقرير:**
1. في Power BI Desktop: **File ← Export ← Export to PDF**.
2. احفظه **بنفس الاسم** هنا: `powerbi/AI_SafeSight_CHV.pdf`.
3. اعمل refresh للموقع، والنسخة الجديدة هتظهر.

## لو Power BI قال إنه مش لاقي الداتا
الداتا اتنقلت لـ `powerbi/data/`. فلو التقرير لسه بيدوّر عليها في مكانها القديم:
**Transform data ← Data source settings** ← اختار المصدر ← **Change Source** ← اختار `powerbi\data\CHV_PowerBI.xlsx` ← **OK** ← **Refresh**.

## خلي بالك
- الداتا دي **جداول بس، مافيهاش صور**، يعني تنفع للتقرير لكن ماتنفعش لتدريب النموذج.
- مافيهاش وقت ولا كاميرا، فالتقرير بيوضح **الالتزام** مش **إمتى** حصلت المخالفة.
- ربط الخوذة والسترة بالشخص اتعمل بالتقريب، ونجح مع حوالي 95% منهم (التفاصيل في `POWERBI_GUIDE.md`).
