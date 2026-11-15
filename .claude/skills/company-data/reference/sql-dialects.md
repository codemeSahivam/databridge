# Snowflake vs Databricks SQL — the differences that bite

| Task | Snowflake | Databricks SQL |
|---|---|---|
| Table names | `DB.SCHEMA.TABLE` (unquoted = UPPERCASE) | `catalog.schema.table` (lowercase) |
| Add days | `DATEADD(day, -7, CURRENT_DATE)` | `date_add(current_date(), -7)` |
| Date diff | `DATEDIFF(day, a, b)` | `datediff(b, a)` (note argument order) |
| Truncate to week | `DATE_TRUNC('week', d)` (week start per `WEEK_START` param) | `date_trunc('WEEK', d)` (Monday) |
| String concat | `a \|\| b` or `CONCAT` | `concat(a, b)` |
| Safe divide | `DIV0(a, b)` | `try_divide(a, b)` |
| Conditional count | `COUNT_IF(x)` | `count_if(x)` |
| Approx distinct | `APPROX_COUNT_DISTINCT(x)` | `approx_count_distinct(x)` |
| Semi-structured | `col:field::string` | `col:field` / `get_json_object` |
| Timezone convert | `CONVERT_TIMEZONE('UTC','Asia/Kolkata', ts)` | `from_utc_timestamp(ts, 'Asia/Kolkata')` |

When cross-checking, make both queries return the **same column aliases in lowercase** and the same date grain.
Week boundaries are the most common cause of "mismatches" that aren't real — set them explicitly.
