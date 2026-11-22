# CHV dataset – Power BI guide

## 1. Import
Get Data → **Excel workbook** → `CHV_PowerBI.xlsx` → select all 6 sheets → Load.
(Or Get Data → Text/CSV for each `.csv`. They are UTF-8, comma-separated.)

## 2. Relationships (Model view)
| From (many) | To (one) | Key |
|---|---|---|
| fact_objects | dim_images | image_id |
| fact_objects | dim_classes | class_id |
| fact_persons_ppe | dim_images | image_id |
| fact_persons_ppe | fact_objects | person_object_id → object_id (inactive is fine) |

Star schema: `dim_images` and `dim_classes` are dimensions; slicers on `split`, `crowd_level`, `orientation`, `category`, `helmet_color` filter everything.
`original_images` and `data_quality_log` are stand-alone tables.

## 3. Suggested DAX measures
```DAX
Total Images      = DISTINCTCOUNT(dim_images[image_id])
Total Objects     = COUNTROWS(fact_objects)
Total Persons     = COUNTROWS(fact_persons_ppe)
Compliance Rate   = DIVIDE(SUM(fact_persons_ppe[is_fully_compliant]), [Total Persons])
Helmet Rate       = DIVIDE(CALCULATE([Total Persons], fact_persons_ppe[has_helmet] = TRUE()), [Total Persons])
Vest Rate         = DIVIDE(CALCULATE([Total Persons], fact_persons_ppe[has_vest] = TRUE()), [Total Persons])
Avg Objects/Image = DIVIDE([Total Objects], [Total Images])
```

## 4. Suggested visuals
- Cards: Total Images, Total Objects, Total Persons, Compliance Rate
- Column chart: object count by `dim_classes[class_name]` (use `color_hex` for conditional colors)
- Stacked bar: class distribution per `split` (checks train/val/test balance)
- Donut: `fact_persons_ppe[ppe_status]`
- Pie/bar: helmet color distribution (`helmet_color`)
- Histogram: `fact_objects[size_bucket]` / `area_pct_of_image`
- Bar: images by `crowd_level`
- Scatter: `x_center_norm` vs `y_center_norm` (where objects appear in frames)
- Table: `data_quality_log`

## 5. Notes on the preprocessing
- YOLO normalized boxes were converted to pixel coordinates using each image's real size.
- 177 boxes extending slightly past the image edge were clipped; 1 exact duplicate box was removed.
- 2 images are CMYK (flagged only). `__MACOSX` / `.DS_Store` were ignored.
- **PPE matching is a heuristic** (the dataset doesn't link helmets/vests to people): a helmet is assigned to a
  person if its center lies in the person's horizontal range and top ~35% of the box; a vest if its center lies
  in the upper 75%. About 94% of helmets and 96% of vests get matched to a person.
- Regenerate everything with: `python preprocessing/preprocess_for_powerbi.py`
