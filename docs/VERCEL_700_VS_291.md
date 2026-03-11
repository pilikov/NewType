# Диагностика: 700+ vs 291 релизов MyFonts (2–8 марта) на Vercel vs localhost

## Симптом

- **Production** (https://new-type-livid.vercel.app/): неделя 2–8 марта — **700+** релизов MyFonts.
- **Localhost**: та же неделя — **291** релиз MyFonts (ожидаемо).

## Причина

На production задеплоена **старая версия кода** из git (ветка, с которой собирается Vercel, скорее всего `main`). В репозитории **не закоммичены** правки в `web/app/page.tsx`, которые дают 291 релиз.

### Что есть в репо (то, что видит Vercel)

- Загружается только **один** период — `findLatestPeriodDir` → один каталог периода.
- Для MyFonts **нет**:
  - загрузки **всех** периодов (`findAllPeriodDirs`);
  - объединения по семье (`mergeMyfontsByFamily`, `myfontsFamilyKey`);
  - фильтра «только с ссылкой на семью» (`hasMyfontsFamilyLink`).
- Итог: подмешивается **day + один period**, без дедупа по семье и без отсечения product-only/bundle без семьи. По неделе 2–8 марта остаётся 700+ записей.

### Что есть только локально (не в git)

- Загрузка **всех** периодов для MyFonts и слияние с day.
- Один релиз на семью (приоритет day, потом период).
- Фильтр: показываем только релизы с `hasMyfontsFamilyLink` (есть `collection_url` или страница коллекции).
- Итог: 291 релиз за 2–8 марта.

## Что сделать

Закоммитить и запушить текущие изменения в `web/app/page.tsx` (и при необходимости связанные файлы), затем задеплоить на Vercel ту же ветку (например, `main`), с которой идёт деплой. После деплоя production будет использовать ту же логику, что и localhost, и покажет ~291 релиз за 2–8 марта.

Проверка перед пушем:
```bash
git diff HEAD -- web/app/page.tsx   # должны быть findAllPeriodDirs, mergeMyfontsByFamily, hasMyfontsFamilyLink
git add web/app/page.tsx && git commit -m "fix(web): MyFonts merge by family + filter by family link (291 for week)"
git push
```
