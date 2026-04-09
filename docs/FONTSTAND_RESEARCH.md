# Исследование: парсинг Fontstand (fontstand.com)

Отчёт по непубличным API и backend-методам для возможного парсинга каталога шрифтов.

## Стек и инфраструктура

- **CMS:** Silverstripe (по путям `/framework/`, `/themes/`, bootstrap, jQuery Entwine).
- **Фронт:** jQuery, Bootstrap, reCAPTCHA (логин, подписка).
- **Хостинг:** nginx, CloudFront (AWS).
- **Документации публичного API нет** — в поиске и на сайте не обнаружено.

## Обнаруженные backend-подобные эндпоинты

### 1. Подсказки при поиске семейств (JSON)

- **URL:** `GET/POST https://fontstand.com/home/suggestfamilies`
- **Назначение:** автодополнение для формы поиска семейств (атрибут `data-suggestlink="/home/suggestfamilies"` у `SearchFamilyForm`).
- **Ответ:** JSON вида `{"families":[]}`.
- **Поведение:** при запросах с `term=`, `q=`, `Family=` (GET и POST) в тестах всегда возвращался пустой массив `families`. Возможные причины: требование сессии/куки, другой параметр (например, имя поля формы) или минимальная длина ввода.

### 2. Форма поиска семейств

- **URL:** `POST /home/SearchFamilyForm`
- **Тип:** форма с `action="/home/SearchFamilyForm"`, `method="post"`.
- **Использование:** отправка поискового запроса; ответ, скорее всего, HTML (редирект или рендер страницы результатов). Отдельного JSON API для поиска по форме не видно.

### 3. Подписка на рассылку

- **URL:** `POST home/NewsletterForm` (относительный путь от base).
- **Класс:** `AjaxSubmit` — отправка через AJAX, ожидаемый ответ может быть JSON.
- **Защита:** reCAPTCHA (sitekey в HTML).

### 4. Скачивание приложений

- **URL:** `GET /apps/download/{id}` (например `/apps/download/82`).
- **Поведение:** в тесте возвращался 500; вероятно редирект на файл или проверка User-Agent/реферера.
- **Данные о версиях:** не API, а встроенный в HTML JSON в атрибуте `data-versionlist` у кнопки «Download»: список приложений по платформам (OSX, WINDOWS) с полями `AppVersion`, `Link`, `PlatformVersion`, `AppSpecify`. Уже пригоден для парсинга со страницы.

## Список шрифтов через /fonts/ — JSON API

Страница **https://fontstand.com/fonts/** подгружает список семейств через непубличный JSON-эндпоинт.

### Эндпоинт списка

- **URL:** `GET https://fontstand.com/fonts/filteredfonts?start={offset}`
- **Заголовки:** обязательны `Referer: https://fontstand.com/fonts/` и User-Agent браузера (иначе возвращается HTML).
- **Пагинация:** `start=0`, `64`, `128`, … (64 семейства на страницу в режиме «tiles», 20 в режиме «rows» — см. `data-perpagetiles="64"`, `data-perpagerows="20"` на странице).

### Формат ответа

```json
{
  "Good": true,
  "FamiliesCount": "2431 families",
  "FamiliesCountRaw": 2431,
  "AllFamiliesCount": 2895,
  "StartPagination": "0",
  "ShowRows": false,
  "Data": [
    {
      "Link": "fonts/gregory-text",
      "Title": "Gregory Text",
      "FoundryTitle": "14 styles<br>TypeMates",
      "Styles": "",
      "RegularRow": "",
      "Row": "",
      "Image": "<img ...>",
      "Pos": 0
    }
  ],
  "NoFamiliesText": "...",
  "Tags": []
}
```

В каждом элементе `Data`: **Link** (относительный путь к семейству), **Title** (название), **FoundryTitle** (текст вида «N styles<br>Foundry Name» — число стилей и фаундри). Поля **даты релиза в ответе нет**.

### Сортировка

На странице /fonts/ есть переключатель «Release Date» (`data-type="sorting" data-value="release-date"`). Параметры сортировки, скорее всего, передаются при AJAX-запросе (POST или GET). Даже при сортировке по дате релиза сам API в текущем формате **не отдаёт дату** — только порядок выдачи (сначала новые).

### Итог по «всем релизам» с /fonts/

| Задача | Возможно? |
|--------|-----------|
| Получить **полный список семейств** (название, слаг, фаундри, кол-во стилей) | **Да** — обход `filteredfonts?start=0,64,128,...` до исчерпания (≈2431 записей, ~39 страниц по 64). |
| Получить **дату релиза** по каждому шрифту | **Нет** — в JSON нет поля с датой. Варианты: парсить отдельную страницу каждого шрифта (например `/fonts/{slug}`), если там есть дата, либо использовать только порядок «по дате» без самой даты. |

Для «релизов с датой» нужно либо проверять наличие даты на странице семейства (`/fonts/{slug}`), либо ограничиться списком «все семейства» без дат.

### Обогащение датой релиза через New Releases

**Да, дату релиза можно обогатить** по разделу [New Releases](https://fontstand.com/news/new-releases/).

#### RSS (предпочтительно)

- **URL:** `https://fontstand.com/news/new-releases/rss`
- **Формат:** RSS 2.0, в каждом `<item>`:
  - `<title>` — название шрифта/семейства (иногда несколько: «Fit Tamil and Fit Devanagari», «Borges Open and Borges Titling»);
  - `<link>` — ссылка на статью;
  - `<description>` — фаундри, например `by R-Typography`;
  - `<pubDate>` — дата в RFC 2822, например `Mon, 08 Dec 2025 12:00:00 +0100`.

Парсинг RSS даёт готовые пары (название, фаундри, дата) для сопоставления со списком из `filteredfonts` (по `Title` и, при необходимости, по фаундри из `FoundryTitle`).

#### Load more — пагинация (все записи New Releases)

Кнопка «Load more» внизу страницы подгружает следующие записи через AJAX.

- **URL:** `GET https://fontstand.com/news/new-releases/loadMore?url=news%2Fnew-releases%2F&start={offset}`
- **Заголовки:** обязательны `Referer: https://fontstand.com/news/new-releases/` и `X-Requested-With: XMLHttpRequest` (иначе возвращается HTML главной).
- **Шаг пагинации:** по 9 статей: первая страница — первые 9 на самой странице, затем `start=9`, `start=18`, `start=27`, … пока в ответе `last !== true`.

**Формат ответа (JSON):**
```json
{
  "nextUrl": "https://fontstand.com/news/new-releases/loadMore?url=...&start=18",
  "last": false,
  "data": ["<article class=\"article-post\">...Otta...26 Sep 2025 • 1 min read...</article>", ...],
  "css": { ... }
}
```

В каждом элементе `data` — HTML одного `<article>`: заголовок (название шрифта), ссылка, блок «by {Foundry}», в `<footer class=\"article-post__meta\">` — дата в виде «26 Sep 2025 • 1 min read». Парсинг этого HTML даёт (title, foundry, date) для обогащения. Цикл: запрашивать `loadMore?start=0,9,18,...` до `last: true` — получаем **полный список записей New Releases с датами**, не только последние из RSS.

#### Ограничения

- В разделе New Releases — только те релизы, которым посвящена новостная запись; это не полный каталог всех семейств с датами.
- Итог: дату релиза можно обогатить **для всех записей из New Releases** (RSS + loadMore до конца), а для остальных семейств — только если дата есть на странице `/fonts/{slug}`.

---

## Структура URL для парсинга (HTML)

Данные каталога также отдаются через обычные страницы (foundries и т.д.).

| Сущность        | Пример URL |
|-----------------|------------|
| Список фаундри  | `/foundries/`, `/apps/` (на apps — блок Participating Type Foundries) |
| Фаундри (слаг)  | `/foundries/typotheque`, `/foundries/xyz-type` |
| Пагинация       | `/foundries/foundries/typotheque?start=20` |
| Семейство шрифта| `/foundries/fonts/amalia-std` (в списке фаундри; отдельная страница по такому URL в тесте отдала 404 — возможно иной маршрут или только через список) |
| Внутренняя ссылка на фаундри | `/foundries/foundries/{slug}` (тот же контент, что и `/foundries/{slug}`) |

На странице фаундри (например `/foundries/typotheque`) в HTML есть:

- название и описание фаундри;
- таблица/список семейств с ссылками вида `/foundries/fonts/{family-slug}` и подписи «N styles»;
- блок «Participating Type Foundries» со ссылками на другие фаундри.

Имеет смысл парсить список фаундри с главной/apps, затем для каждой — страницу `/foundries/{slug}` и при необходимости пагинацию `?start=20,40,...`, извлекая ссылки на семейства и метаданные из разметки.

## robots.txt

- **Разрешено:** `/` (с задержкой 15 с для общего User-agent).
- **Закрыто от краулинга:** `/framework/`, `/themes/`, `/admin/`.
- **Sitemap:** `https://www.fontstand.com/sitemap.xml` (при обращении по этому URL в тесте возвращалась ошибка 500).

## Защита и ограничения

- reCAPTCHA на логине и формах подписки.
- Разные правила в robots.txt для ботов (в т.ч. AI/краулеры).
- Возможная проверка Referer/User-Agent на `/apps/download/` и, гипотетически, на `suggestfamilies`.

## Соответствие полей продукта (FontRelease)

Продукт сохраняет для каждого релиза поля: `name`, `styles`, `authors`, `scripts`, `release_date`, `image_url`, `woff_url`, `specimen_pdf_url`, а также `source_id`, `source_url`, `discovered_at`, `release_id`, `raw`.

| Поле продукта   | Откуда взять в Fontstand | Доступно? |
|-----------------|--------------------------|-----------|
| **name**        | `filteredfonts` → `Title`; New Releases → `title` | ✅ Да |
| **source_url**  | `https://fontstand.com/fonts/{slug}` из `filteredfonts.Link` или из статьи | ✅ Да |
| **release_date**| New Releases (RSS или loadMore); для остальных — только при парсинге страницы семейства | ⚠️ Только для записей в New Releases |
| **image_url**   | В `filteredfonts` в поле `Image` — HTML с `<img src="...">`; можно вытащить `src` | ✅ Да |
| **authors**     | Фаундри: `FoundryTitle` («N styles<br>TypeMates») или New Releases «by X»; персон-авторов в API нет | ⚠️ Только фаундри как строка/список |
| **styles**      | В API только число начертаний («14 styles»), не список названий (Regular, Bold и т.д.) | ❌ Списка нет; возможен парсинг со страницы семейства |
| **scripts**     | В каталоге и New Releases не отдаётся | ❌ Нет; возможен парсинг со страницы семейства |
| **woff_url**    | В каталоге и New Releases не отдаётся | ❌ Нет; возможен парсинг со страницы семейства |
| **specimen_pdf_url** | В каталоге и New Releases не отдаётся | ❌ Нет; возможен парсинг со страницы семейства |

### Фильтры на /fonts/ — откуда данные (Category, Languages, Features)

На странице [https://fontstand.com/fonts](https://fontstand.com/fonts) есть фильтры **Category**, **Proportions**, **Intended Use**, **Features**, **Languages**. Значения для них подгружаются через тот же бэкенд — по ним видно, что **у каждого шрифта на стороне Fontstand есть привязка к категориям, письменностям/языкам и фичам**; иначе фильтрация по ним не работала бы.

#### Получение списков опций фильтров

Эндпоинт **`GET https://fontstand.com/fonts/FilterV2?type={type}`** с заголовками `Referer: https://fontstand.com/fonts/` и `X-Requested-With: XMLHttpRequest` возвращает JSON с полем **`items`** — HTML фрагмент с чекбоксами/списками опций. Параметр **`type`**:

| type | Содержимое |
|------|------------|
| **languages** | Письменности (Latin, Arabic, Cyrillic, Greek, Armenian, Indic, Hebrew, Chinese, Hangul, Japanese, Thai, Georgian) и большой список языков/encoding’ов (Western European, English, French, German, Russian, Hindi, Tamil и т.д.). |
| **catparams** | Категории: Serif (подкатегории Oldstyle, Slab…), Sans, Slab, Script, Display/Decorative и др. У каждого варианта есть `data-value` / `value` (числовой id). |
| **features** | Advanced Typography: Small Caps, Ligatures и другие фичи с числовыми id (например 166, 184). |
| **proportions** | Ширина: Compressed, Condensed и т.д. |
| **intended-use** | Назначение: Small, Body Copy и т.д. |

Из этого HTML можно вытащить **полный справочник**: id и названия для письменностей/языков, категорий и фич — то, что нужно для полей продукта **scripts** (письменности), **languages** (языки), а также для **Category** и **Features**.

#### Привязка к конкретному шрифту

В ответах **filteredfonts** / **FilterV2** (список шрифтов) в каждом элементе **Data** полей category / languages / features **нет** — только Link, Title, FoundryTitle, Image и т.д. То есть «какой шрифт к каким фильтрам относится» в списковом API не отдаётся.

Теоретически можно было бы восстанавливать это **обратным проходом**: для каждого значения фильтра (например, «Latin», «Serif») делать запрос с этим фильтром и считать, что все вернувшиеся шрифты обладают этим атрибутом. Для этого нужно знать **точный формат параметров** запроса (имена полей и формат значений), с которыми бэкенд реально фильтрует список. **Важно:** фильтр по языкам/письменностям срабатывает только при **GET**-запросе к `FilterV2` с параметрами в query string. При POST с телом запроса возвращается полный каталог (2431). Пример: `GET /fonts/FilterV2?start=0&languages[393]=393` (English) → 2163 семейств; `languages[511]=511` (Russian) → 295 семейств.

**Реализованная схема «языки → письменности»:** из `FilterV2?type=languages` парсится (1) список **encodings** (id письменности: Latin, Cyrillic, Arabic и т.д.) и (2) список **языков** с привязкой к письменности: каждый чекбокс `languages[id]` лежит внутри блока `ul-holder` с `data-pos`, по которому определяется письменность. Для каждого encoding и каждого языка делается запрос к FilterV2 с соответствующим параметром (`encodings[id]` или `languages[id]`); если ответ содержит меньше 90% каталога, считаем фильтр сработавшим и присваиваем указанную письменность всем шрифтам из ответа. В краулере запросы к FilterV2 для фильтрации выполняются через **GET** с параметрами в query (например `languages[393]=393`), тогда фильтр применяется и поля **scripts** заполняются по языкам и encodings. Для каждого скрипта используется один **маркерный язык** (один запрос на скрипт): Latin→English (393), Cyrillic→Russian (511), Arabic→Arabic (626), Greek→Greek (512), Armenian→Armenian (612), Indic→Hindi (610), Hebrew→Hebrew (594), Chinese→Chinese Simplified (698), Hangul→Korean (689), Japanese→Japanese (732), Thai→Thai (734), Georgian→Georgian (756).

**Итог:** данные для **Languages** (письменности и языки), **Category** и **Features** на бэкенде есть; списки всех опций можно получить через **FilterV2?type=languages|catparams|features|...**. Чтобы получить эти атрибуты **по каждому релизу**, нужно либо добиться работы фильтра в запросе и строить обратный индекс по ответам, либо искать другой источник (например, страница семейства или неочевидный detail-API).

**Итог:** без парсинга страницы семейства (`/fonts/{slug}`) можно уверенно заполнить только **name**, **source_url**, **image_url**, для части записей — **release_date** (из New Releases) и **authors** в виде фаундри. Поля **styles** (список), **scripts**, **woff_url**, **specimen_pdf_url** из текущих API не получить; их можно попытаться извлечь при обогащении со страницы семейства (если там есть соответствующие блоки и ссылки).

---

## Сводка: что можем получить и что критично для сервиса

Поля модели **FontRelease** и что по ним даёт Fontstand. Критичность — с точки зрения «что сохраняется» в краулере и что важно для отображения/фильтрации релизов.

| Поле продукта | Критично для сервиса? | Можем получить из Fontstand? | Источник |
|---------------|------------------------|------------------------------|----------|
| **name** | ✅ Да | ✅ Да | `filteredfonts` → `Title`; New Releases (RSS/loadMore) → title; страница семейства `/fonts/{slug}` |
| **source_url** | ✅ Да | ✅ Да | `https://fontstand.com/fonts/{slug}` из `filteredfonts.Link` |
| **image_url** | ✅ Да | ✅ Да | `filteredfonts` → поле `Image` (HTML), вытащить `src` из `<img>`; или страница семейства |
| **release_date** | ✅ Да | ⚠️ Частично | Только для записей в New Releases: RSS или loadMore (парсинг даты из HTML). Остальные семейства — даты в API нет |
| **authors** | ✅ Да | ⚠️ Частично | Фаундри: `FoundryTitle` в filteredfonts или «by X» в New Releases. Персон-дизайнеров — только со страницы семейства (блок Designers) |
| **scripts** | ✅ Да | ⚠️ Справочник есть, по шрифту — нет | Список опций: `FilterV2?type=languages` (письменности + языки). Привязка «шрифт → scripts» в списковом API не отдаётся; возможен обратный проход по фильтрам (если разобрать формат запроса) или парсинг страницы семейства |
| **styles** | ✅ Да | ❌ Нет списка названий | В API только число («14 styles»). Список начертаний (Regular, Bold…) — только с страницы семейства `/fonts/{slug}` |
| **woff_url** | Желательно | ❌ Нет | В каталоге и New Releases нет; только при парсинге страницы семейства (если есть ссылка на .woff/.woff2) |
| **specimen_pdf_url** | Желательно | ❌ Нет | В каталоге и New Releases нет; только при парсинге страницы семейства (если есть ссылка на PDF) |
| **source_id** / **source_name** | ✅ Да | ✅ Да | Задаём сами: например `fontstand`, `Fontstand` |
| **discovered_at** / **release_id** / **raw** | ✅ Да | ✅ Да | Формируем при сохранении |

Дополнительно (не в FontRelease, но полезно для продукта):

| Данные | Критично? | Можем получить? | Источник |
|--------|-----------|------------------|----------|
| **Category** (Serif, Sans, Script…) | Желательно | ⚠️ Справочник да, по шрифту — нет | Список: `FilterV2?type=catparams`. По шрифту — обратный проход по фильтрам или страница семейства |
| **Features** (Small Caps, Ligatures…) | Желательно | ⚠️ Справочник да, по шрифту — нет | Список: `FilterV2?type=features`. По шрифту — обратный проход или страница семейства |
| **Languages** (детальный список языков) | Желательно | ⚠️ Справочник да, по шрифту — нет | Список: `FilterV2?type=languages`. По шрифту — так же, что и для scripts |

### Итог по критичным полям

- **Полностью из API/лент без парсинга страниц:** `name`, `source_url`, `image_url`, `authors` (фаундри), для части записей — `release_date` (New Releases).
- **Критично, но только частично или со страницы:** `release_date` (не у всех), `authors` (персоны — только со страницы), `scripts` (справочник есть, привязка к шрифту — через фильтры или страницу).
- **Критично, но только со страницы семейства:** `styles` (список названий).
- **Желательно, только со страницы или через фильтры:** `woff_url`, `specimen_pdf_url`, Category, Features, Languages по шрифту.

Чтобы закрыть все критичные поля по максимуму, нужен обход страницы семейства `/fonts/{slug}` (как в `html_list` с detail enrichment): там есть Designers, описание, число стилей; наличие там scripts/category/features/woff/specimen нужно проверить по разметке.

---

## Выводы и рекомендации для парсинга

1. **Публичного API каталога нет** — каталог доступен только через HTML.
2. **Непубличные backend-методы:**
   - ` /home/suggestfamilies` — JSON, но в тестах возвращал пустой массив; для парсинга каталога не обязателен, если достаточно обхода страниц.
   - ` /home/SearchFamilyForm` — форма поиска, ответ HTML.
   - ` home/NewsletterForm` — подписка, с reCAPTCHA.
3. **Практичный подход:** парсинг HTML-страниц:
   - список фаундри: с главной и/или `/apps/`;
   - для каждой фаундри: `GET /foundries/{slug}` и при необходимости `?start=20,40,...`;
   - из каждой страницы извлекать ссылки на `/foundries/fonts/{slug}` и метаданные (название, количество стилей, фаундри).
4. **Дополнительные данные:** на главной (и, при наличии, на apps) в атрибуте `data-versionlist` у кнопки загрузки приложения уже есть готовый JSON со списком приложений по платформам — можно парсить без вызова `/apps/download/`.

Для следующего шага можно добавить в проект источник `fontstand` с краулером, который ходит по `/foundries/` и `/foundries/{slug}` и сохраняет структуру «фаундри → семейства» в том же формате, что и остальные источники (см. `docs/ADDING_NEW_SOURCE.md` и существующие краулеры).
