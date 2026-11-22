# خطوات تقرير Power BI على داتا CHV (بالعربي)

> الأرقام اللي بين قوسين **(✓ ...)** هي اللي المفروض تظهرلك، فلو طلعلك نفسها يبقى الخطوة صح.

---

## 1. دخّل الداتا

1. افتح **Power BI Desktop** ← **Home ← Get data ← Excel workbook**.
2. اختار `CHV_PowerBI.xlsx` من الفولدر ده.
3. علّم على **كل الجداول** (6 جداول) ← **Load**.

**مهم، اتأكد من نوع عمودين:**
1. **Home ← Transform data** (هيفتح Power Query).
2. من الشمال اختار جدول `fact_persons_ppe`.
3. شوف أيقونة النوع جنب اسم عمود `has_helmet` وعمود `has_vest`. لازم تبقى أيقونة **True/False** (شكلها ✓✗). لو مكتوب جنبها **ABC** يبقى Power BI فاكرها نص: دوس على الأيقونة واختار **True/False**.
4. **Close & Apply**.

---

## 2. الربط بين الجداول (Model view)

1. اضغط الأيقونة **التالتة** على الشمال (**Model view**).
2. Power BI غالبًا ربط شوية جداول لوحده. **امسح أي خط مش موجود في الجدول اللي تحت**: دوس على الخط، وبعدين **Delete**.
3. اعمل الخطوط دي بالسحب، من العمود في الجدول الأول للعمود في الجدول التاني:

| من (الكتير) | لـ (الواحد) | العمود | الحالة |
|---|---|---|---|
| `fact_objects` | `dim_images` | `image_id` | نشط |
| `fact_objects` | `dim_classes` | `class_id` | نشط |
| `fact_persons_ppe` | `dim_images` | `image_id` | نشط |
| `fact_persons_ppe` | `fact_objects` | `person_object_id` ← `object_id` | **غير نشط** |

**ليه آخر واحد غير نشط؟** لأن `fact_persons_ppe` مربوط بـ `dim_images` بطريقتين: على طول، وكمان عن طريق `fact_objects`. والطريقين مع بعض بيلخبطوا Power BI. لو ظهر الخط ده متقطع (- - -) يبقى غير نشط، وده الصح. ولو طلع خط متصل: دوس عليه دبل كليك، وشيل العلامة من **Make this relationship active**.

`original_images` و `data_quality_log` يفضلوا **من غير ربط**، وده طبيعي.

---

## 3. المقاييس (Measures)

اعمل جدول فاضي يجمّع كل المقاييس عشان يبقوا في مكان واحد:
**Home ← Enter data** ← سمّيه `Measures` ← **Load**.

وبعدين: **كليك يمين على `Measures` ← New measure**، والصق كل مقياس من دول لوحده، وبعد كل واحد اضغط **Enter**:

```DAX
Total Images = DISTINCTCOUNT(dim_images[image_id])
```
```DAX
Total Objects = COUNTROWS(fact_objects)
```
```DAX
Total Persons = COUNTROWS(fact_persons_ppe)
```
```DAX
Compliance Rate = DIVIDE(SUM(fact_persons_ppe[is_fully_compliant]), [Total Persons])
```
```DAX
Helmet Rate = DIVIDE(CALCULATE([Total Persons], fact_persons_ppe[has_helmet] = TRUE()), [Total Persons])
```
```DAX
Vest Rate = DIVIDE(CALCULATE([Total Persons], fact_persons_ppe[has_vest] = TRUE()), [Total Persons])
```
```DAX
No Helmet = CALCULATE([Total Persons], fact_persons_ppe[has_helmet] = FALSE())
```
```DAX
No Vest = CALCULATE([Total Persons], fact_persons_ppe[has_vest] = FALSE())
```
```DAX
Avg Objects per Image = DIVIDE([Total Objects], [Total Images])
```

**التنسيق:** اختار `Compliance Rate` و `Helmet Rate` و `Vest Rate`، وواحد واحد روح **Measure tools ← Format ← Percentage**، وخلي عدد الأرقام العشرية **1**.

**الأرقام اللي المفروض تظهر:**
| المقياس | القيمة |
|---|---|
| Total Images | ✓ 1,330 |
| Total Objects | ✓ 9,208 |
| Total Persons | ✓ 3,886 |
| Compliance Rate | ✓ 40.6% |
| Helmet Rate | ✓ 85.8% |
| Vest Rate | ✓ 44.1% |
| No Helmet | ✓ 552 |
| No Vest | ✓ 2,172 |
| Avg Objects per Image | ✓ 6.92 |

لو `Helmet Rate` أو `No Helmet` طلّعوا error أو صفر، ارجع لخطوة نوع العمود في الجزء 1.

---

## 4. أعمدة بالعربي للرسوم

الداتا بالإنجليزي، فهنعمل أعمدة جديدة بالعربي عشان الرسوم تطلع عربي.

**على جدول `fact_persons_ppe`:** كليك يمين على الجدول ← **New column**، والصق كل عمود لوحده:

```DAX
حالة المعدات = SWITCH(fact_persons_ppe[ppe_status],
    "Fully compliant", "ملتزم بالكامل",
    "Helmet only", "خوذة فقط",
    "Vest only", "سترة فقط",
    "No PPE", "بدون معدات",
    fact_persons_ppe[ppe_status])
```
```DAX
ترتيب الحالة = SWITCH(fact_persons_ppe[ppe_status],
    "Fully compliant", 1, "Helmet only", 2, "Vest only", 3, "No PPE", 4, 5)
```
```DAX
لون الخوذة = SWITCH(fact_persons_ppe[helmet_color],
    "Yellow", "أصفر", "White", "أبيض", "Red", "أحمر", "Blue", "أزرق",
    "None", "بدون خوذة", "", "بدون خوذة",
    fact_persons_ppe[helmet_color])
```

**على جدول `dim_images`:**
```DAX
عدد العمال في الصورة = SWITCH(dim_images[crowd_level],
    "No person", "لا يوجد", "1 person", "شخص واحد", "2-3 persons", "2 - 3",
    "4-6 persons", "4 - 6", "7+ persons", "7 أو أكثر", dim_images[crowd_level])
```
```DAX
ترتيب الزحمة = SWITCH(dim_images[crowd_level],
    "No person", 0, "1 person", 1, "2-3 persons", 2, "4-6 persons", 3, "7+ persons", 4, 5)
```

**خلي الترتيب صح** (عشان "ملتزم بالكامل" تيجي الأول، و"شخص واحد" قبل "7 أو أكثر"):
1. روح **Data view**، الأيقونة التانية على الشمال.
2. اختار عمود `حالة المعدات` ← **Column tools ← Sort by column** ← اختار `ترتيب الحالة`.
3. اختار عمود `عدد العمال في الصورة` ← **Sort by column** ← اختار `ترتيب الزحمة`.

---

## 5. الألوان

**View ← Themes** ← السهم الصغير ← **Browse for themes** ← اختار:
```
C:\Users\yousef\graduation_project_aisafesight\powerbi\safesight-theme.json
```

---

## 6. الصفحة الأولى: الالتزام بمعدات السلامة (لـ HSE وProject Manager)

سمّي الصفحة: دوس دبل كليك على **Page 1** تحت، واكتب **الالتزام بالمعدات**.

| الرسمة | إزاي تعملها | المفروض يظهر |
|---|---|---|
| **عنوان** | Insert ← Text box: **AI SafeSight — الالتزام بمعدات السلامة**. ومن Insert ← Image حط `Frontend\logo.svg` جنبه | |
| **4 كروت** | Card لكل واحد من دول: `Total Persons`، `Compliance Rate`، `No Helmet`، `No Vest` | ✓ 3,886 / 40.6% / 552 / 2,172 |
| **Donut: حالة العمال** | Legend: `حالة المعدات`، Values: `Total Persons` | ✓ خوذة فقط 1,757، وملتزم بالكامل 1,577، وبدون معدات 415، وسترة فقط 137 |
| **Bar: ألوان الخوذات** | Y-axis: `لون الخوذة`، X-axis: `Total Persons` | ✓ أصفر 1,205، وأبيض 1,136، وبدون خوذة 552، وأحمر 501، وأزرق 492 |
| **Column: الالتزام حسب الزحمة** | X-axis: `dim_images[عدد العمال في الصورة]`، Y-axis: `Compliance Rate` | ✓ شخص واحد 37.7%، و2-3 49.0%، و4-6 33.0%، و7+ 39.5% |
| **Gauge: نسبة الخوذة والسترة** | Gauge لـ `Helmet Rate` وGauge تاني لـ `Vest Rate`. وفي Format ← Gauge axis خلي **Max = 1** | ✓ 85.8% / 44.1% |
| **Slicers** | `dim_images[split]`، و`dim_images[عدد العمال في الصورة]` | |

**ألوان الدونات:** اضغط على الدونات ← **Format ← Slices**، وخلي: ملتزم بالكامل **أخضر `#16A34A`**، وخوذة فقط **برتقالي `#F59E0B`**، وسترة فقط **أصفر غامق `#D97706`**، وبدون معدات **أحمر `#DC2626`**.

**ألوان الخوذات:** ممكن تخلي كل عمود بلون الخوذة نفسها: اضغط على البار ← **Format ← Bars ← Show all**، ولوّن كل لون بلونه (والأبيض خليه رمادي فاتح `#D9D9D9` عشان يبان على الخلفية).

**العناوين:** لكل رسمة: **Format ← General ← Title**، واكتب عنوان عربي. مثلًا: "حالة العمال"، و"ألوان الخوذات"، و"الالتزام حسب عدد العمال".

---

## 7. الصفحة التانية: جودة الداتا (للمناقشة)

دي بتوضح للجنة إنكم فاهمين الداتا اللي دربتوا عليها.

اعمل صفحة جديدة بالـ **+** اللي تحت، وسمّيها **جودة الداتا**:

| الرسمة | إزاي تعملها |
|---|---|
| **كروت** | `Total Images` (✓ 1,330)، و`Total Objects` (✓ 9,208)، و`Avg Objects per Image` (✓ 6.92) |
| **Stacked column: الكلاسات في كل split** | X-axis: `dim_classes[class_name]`، Y-axis: `Total Objects`، Legend: `dim_images[split]` |
| **Column: حجم الحاجات** | X-axis: `fact_objects[size_bucket]`، Y-axis: `Total Objects` (✓ Large 5,040، وMedium 2,919، وSmall 1,249) |
| **Scatter: الحاجات بتظهر فين في الصورة** | X-axis: `fact_objects[x_center_norm]`، Y-axis: `fact_objects[y_center_norm]`، Legend: `dim_classes[category]`. واقلب محور Y من **Format ← Y-axis ← Invert range = On** عشان فوق يبقى فوق زي الصورة |
| **Table: المشاكل اللي اتصلحت** | من `data_quality_log`: `issue`، و`action`، و`image_id` |

**خلي بالك من الـ Scatter:** لو النقط ظهرت نقطة واحدة بس، دوس على السهم جنب `x_center_norm` في خانة X-axis، واختار **Don't summarize**، واعمل نفس الحاجة مع Y.

---

## 8. حاجات تقولها في المناقشة

- الداتا مافيهاش **وقت ولا كاميرا**، فالتقرير بيوضح **الالتزام** مش **إمتى** حصلت المخالفة. ولما الكاميرا تتربط بالنظام، الـ API هيسجّل الوقت.
- ربط الخوذة والسترة بالشخص اتعمل **بالتقريب** حسب مكانهم جوه مربع الشخص، ونجح مع حوالي 95% منهم.
- أكبر مشكلة في الداتا هي **السترة**: 56% من العمال مش لابسينها، قصاد 14% بس من غير خوذة.
