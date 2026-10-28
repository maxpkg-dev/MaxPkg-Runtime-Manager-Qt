# Оригинал MaxPkg Runtime Manager 1.2.0 — спецификация для Qt-версии

Источник: `C:\Projects\Scripts\runtime` (MaxScript + HTML в dotNet WebBrowser), установленная копия в
3ds Max 2027. Скриншоты сняты с живого Manager в `docs/original/`.

**Главное правило переноса: UI/UX повторяем как в оригинале** — те же экраны, тексты, порядок
элементов, поведение и адаптивность. Меняем только техническую основу (Qt + Python вместо
WebBrowser + dotNet). Улучшения допустимы только там, где они не меняют привычный сценарий
(в первую очередь — тулбар, см. раздел 9).

---

## 1. Назначение

Менеджер пакетов (скриптов) для 3ds Max, работающий с каталогом maxpkg.dev:
поиск, установка, запуск, обновление и удаление скриптов, собственный тулбар с кнопками
установленных скриптов, самообновление Runtime. Лицензия: только для официального сервиса MaxPkg.

## 2. Установка и раскладка файлов

**Источник установки:** `MaxPkg-Runtime-Manager.mzp` (`mzp.run` → `run/drop install.ms`), либо
автоматически при установке скрипта с сайта (блок перетаскивается во вьюпорт).

`install.ms` делает:
1. Останавливает текущий `MaxPkg` (`MaxPkg.shutdown()`).
2. Копирует `core/`, `ui/`, `themes/`, `startup.ms`, `version.ini`, `uninstall.ms` в
   **`(getDir #temp)\MaxPkg-Runtime-Manager\`** (например,
   `%LOCALAPPDATA%\Autodesk\3dsMax\2027 - 64bit\ENU\temp\MaxPkg-Runtime-Manager\`).
   Папки `core/` и `ui/` перед этим удаляются целиком; пользовательские темы, `settings.ini`, `data/` сохраняются.
3. Создаёт `data\packages\` и `logs\`.
4. Пишет startup-шим `(getDir #userStartupScripts)\maxpkg-runtime-startup.ms` = `fileIn @"<root>/startup.ms"`.
5. Пишет MacroScript `(getDir #userMacros)\maxpkg-runtime-manager.mcr`:
   `macroScript MaxPkg_Manager category:"MaxPkg" buttonText:"MaxPkg Manager"`, иконка `ui/common/icons/maxpkg-logo.svg`;
   при выполнении поднимает Runtime при необходимости и зовёт `MaxPkg.openManager()`.
6. Запускает `startup.ms` и показывает **онбординг**.
7. При ошибке — тематический «Result dialog» (`ui/common/result-dialog.*`) с заголовком
   «Installation incomplete» и тремя шагами помощи.

Удаление Runtime: `Settings > Uninstall` → `uninstall.ms` (убирает шим, макрос, тулбар, папку Runtime,
показывает Result dialog).

### Пакеты
- Пакет = папка с `manifest.ini` (единственный источник правды). Корни поиска:
  `getDir #temp`, `<runtime>\data\packages`, плюс `[Packages] Roots` из настроек. Ищется `manifest.ini`
  в самом корне и в каждой подпапке первого уровня.
- Установка пакета: скачать `.mzp` во временный файл `maxpkg-download-<guid>.mzp` и **`fileIn` его**
  (установщик пакета генерирует MaxPkg Packager), затем пересканировать и проверить, что GUID появился.
  Имя файла `slug@version@guid.mzp` → ожидаемый GUID.
- Пакеты сами создают: макросы `maxpkg-<guid>*.mcr` / `MaxPkg-MaxPkg_<guidбезДефисов>.mcr`,
  иконку `(getDir #userIcons)\<guid>.svg`, quad-menu (`maxpkg-quad.ms` +
  `userStartupScripts\maxpkg-<guid>-quad-startup.ms`), uninstall-хук (`uninstallScript`, по умолчанию `uninstall.ms`).
- Удаление: проверка безопасности пути (не корни temp/userScripts/startup, не внутри Runtime) →
  хук → quad-menu cleanup → удалить макросы и иконку → удалить папку → пересканировать.
- Запуск: `Runtime=Python` или `.py` → `python.ExecuteFile`, иначе `fileIn` (`.ms`/`.mse`).

Ключи `manifest.ini` секции `[package]` (с алиасами): `packageGuid|Guid`, `name`, `slug`, `buttonName`,
`version`, `developerName|Developer`, `description`, `documentation|help`, `homepage`, `support`,
`purchase`, `purchaseButtonLabel` (по умолчанию «Buy»), `license`, `licenseUrl`, `releaseChannel`,
`releaseDate`, `min3dsMax`, `max3dsMax`, `manifestVersion`, `packager`, `packagerVersion`, `entry`,
`runtime`, `icon`, `showInToolbar|ToolbarVisible`, `toolbarOrder`, `uninstallScript|Uninstall`.
`[changelog]`: `N_text`, `N_type`. Обязательные: Guid, Name, Version, Runtime (выводится из Entry), Entry.
Дубликаты GUID пропускаются, битый манифест логируется и пропускается.

## 3. Публичный MaxScript API — сохранить обязательно

Его используют README, установщики пакетов, блок установки с сайта и пользователи из Listener.
В Qt-версии нужен **MaxScript-фасад `MaxPkg` с теми же методами**, проксирующий в Python.

`isStarted()`, `start()`, `shutdown()`, `scan()`, `openManager tab: settingsPage:`, `showOnboarding()`,
`getPackages()`, `getPackage ref`, `getSettings()`, `saveSettings()`, `getStatus()`,
`run ref`, `install ref showNotification:`, `uninstall ref showNotification:`, `checkUpdates()`,
`updateAll()`, `updatePackage ref`, `selfUpdate()`, `rebuildToolbar()`, `resetToolbarPosition()`,
`setToolbarVisible ref bool`, `resetToolbarOrder()`, `setToolbarOrder guids`, `openPackageFolder ref`,
`openPackageLink ref kind`, `openPackageHelp ref`, `packageInstalled guid`, `packageRemoved guid`,
`isBusy()`, `browsePackages/browseCollections/browseCategories/getRemotePackageDetails/resolveRemotePackage`;
свойства `version`, `runtimeChannel`, `packages`, `settings`.

`MaxPkg.install "prune scene"` принимает GUID, slug, URL, локальный путь или свободное имя
(регистр и порядок слов не важны: нормализация → `packages/resolve` → поиск по каталогу).
`install` возвращает `{success, errorCode, errorMessage, packageGuid}` (коды `RUNTIME_BUSY`,
`PACKAGE_NOT_FOUND`, `ARTIFACT_NOT_FOUND`, `INSTALL_FAILED`, `INCOMPATIBLE_3DS_MAX`, …) и показывает
системное уведомление Windows (tray balloon), если `showNotification: true`.

> Не найдено в репозитории: что именно вызывает блок установки с сайта. Перед релизом проверить в
> `maxpkg-dev/max-dev-tool` / на сайте, какие методы `MaxPkg` он использует.

## 4. Сетевой API

- База: `https://maxpkg.dev/api/runtime/v1/` (переопределение `[Endpoint] apiEndpoint`, видно только в Developer mode).
- Все запросы — `POST application/x-www-form-urlencoded`, общие поля `max3dsMax=<год>`, `runtimeVersion`, `channel`.
- Ответы — **INI-текст** (секции `[error] Code/Message/RequestId`, `[catalog]|[meta] Page/PageSize/Total/TotalPages/TotalPackages`,
  пакеты — секция на пакет с ключами `Guid, Slug, Name, ButtonName, Version, Developer, Description, FullDescription,
  Category, Documentation, Homepage, Support, PurchaseUrl, PurchaseButtonLabel, License, LicenseUrl, Channel,
  ReleaseDate, Min3dsMax, Max3dsMax, Runtime, Entry, IconUrl, PackageIconUrl, CoverImageUrl, DownloadUrl,
  Rating, ReviewCount, DownloadCount`; `<section>.changelog` или `[changelog] Count` + `changelog_N`/`changelog_N_item_M`;
  `[screenshots] Count` + `screenshot_N Url/ThumbnailUrl/Title/Caption/SortOrder`).

| Действие | Поля | Назначение |
|---|---|---|
| `catalog` | query, category, sort (popular/newest/rating/downloads/name), page, pageSize=24, featured=true \| collection | Discover |
| `collections` | — | чипы коллекций (`[meta] FeaturedCount, Count`, `collection_N Slug/Name/Description/Icon/AccentColor/Count`) |
| `categories` | — | категории (`category_* Slug/Name/Description/Count`, показываются только с Count>0) |
| `packages/details` | package | детали |
| `packages/resolve` | package | установка по ссылке |
| `updates` | packages=`guid@version,…` | одна пакетная проверка обновлений |

Клиент дополнительно отбрасывает пакеты с `Min3dsMax` выше текущей версии Max.
HTTP: dotNet WebClient с TLS 1.2 и автоматический фолбэк на `curl.exe` на сессию.

**Самообновление Runtime:** сравнивает `version.ini` из
`raw.githubusercontent.com/maxpkg-dev/MaxPkg-Runtime-Manager/main/version.ini` и при новой версии того же
канала качает `archive/refs/heads/main.zip`, копирует поверх (кроме `settings.ini`, `data/`, `logs/`, `.git/`)
и перезапускает `startup.ms`. Если открыт онбординг, перезапуск откладывается до его закрытия.

**Обновления пакетов:** автопроверка при старте по интервалу (1/6/12/24/48/168 ч), кэш результата
`[Updates] PackageCache=guid@version|…` (бейдж на тулбаре виден без сети), опционально автоустановка.

## 5. Настройки (`<runtime>\settings.ini`, UTF-16)

`[General]` Language=English, Environment, AutoStart, OpenManagerOnStartup, ManagerTheme ·
`[Toolbar]` Visible, Hidden=`guid|…`, Order=`guid|…`, TitleMode (packageName/buttonName), SubtitleMode
(version/developer/none), ButtonSize (icon/small/medium/large), IconSize (small/medium/large), Density
(regular/compact), DockPosition (top/bottom/left/right/floatinghorizontal/floatingvertical), Theme,
FloatingHorizontalX/Y, FloatingVerticalX/Y (−1 = по центру) ·
`[Updates]` FrequencyHours, Notifications, AutoCheckPackages, AutoCheckRuntime, DownloadAutomatically,
LastPackageCheckUtc, PackageCache · `[Manager]` LastTab, LastSelection, Sort, Filter, PositionX/Y, Width,
Height (900×650 по умолчанию), FirstOpenCompleted, FullCards, SortVersion · `[Developer]` Enabled,
DebugLogging · `[Packages]` Roots · `[Endpoint]` apiEndpoint.
Все настройки сохраняются сразу при изменении (без Save/Cancel). Qt-версия должна читать этот файл
(миграция без потерь).

## 6. Manager — экраны

Окно 900×650 (min ширина контента 680), позиция и размер запоминаются. Фон — тёмный градиент темы.

### Общая рамка (все вкладки) — `installed.png`, `discover-1000.jpg`
- **Шапка 68 px:** слева логотип в скруглённой плашке 40×40 + «maxpkg» / «Runtime 1.2.0».
  Справа: `Toolbar Configurator` (иконка panel-top), `Check Updates` (refresh-cw, при работе — «Checking updates...»),
  `Update All` (primary, только когда есть обновления), квадратная кнопка Settings (шестерёнка).
- **Вкладки 43 px:** `Discover [21]`, `Installed [6]`, `Updates [0]` — счётчик в пилюле, активная вкладка
  с подчёркиванием цветом accent.
- **Панель фильтров:** поиск с иконкой (placeholder «Search Discover»), справа выпадающие списки;
  у активного фильтра/сортировки появляется кнопка «×» сброса.
- **Статус-бар 28 px:** «6 packages», «0 updates», по центру ссылка `maxpkg.dev ↗`, справа «Runtime 1.2.0»
  и статус соединения (`Online` зелёным / `Endpoint configured` / Offline / curl — жёлтым).
- **Оверлеи:** полупрозрачная «busy shade» с текстом операции; тосты уведомлений внутри окна;
  выпадающие меню собственного вида.

### Discover — `discover-1000.jpg`, `discover-1300-sidebar.jpg`
- Чипы: `All packages`, `Featured N`, коллекции с цветом `AccentColor` и счётчиком.
- Категории: **≥1200 px — левая панель «CATEGORIES»** (чекбокс-список с количеством);
  **<1200 px — выпадающий список «All Categories» рядом с поиском**.
- Сортировка: Popular, Newest, Rating, Downloads, Name.
- Строка «21 packages [in <фильтр>]», сетка карточек (3 колонки), пагинация по 24 (`Previous`, «Page X of Y», `Next`).
- **Полная карточка** (высота 248): иконка 40 в плашке, название, «v1.5.3 · 3DGROUND», описание с обрезкой «...»,
  статистика `↓ 10.7K  ☆ 5.0 (2)`, бейдж покупки справа (`Donate` зелёный / цена), кнопка `Install`
  или неактивная `✓ Installed`. Клик по шапке карточки → детали.
- Состояния: «Catalog unavailable» + Retry (иконка cloud-off), «No packages found».

### Installed / Updates — `installed.png`
- Фильтр: All / In toolbar / Hidden. Сортировка: Toolbar order / Name / Developer / Version.
- **Компактная карточка** (по умолчанию): иконка, название, «v · автор», кнопка `▷ Run`, кнопка `⋯`,
  в режиме сортировки «Toolbar order» — ручка `⠿` для перетаскивания (меняет порядок на тулбаре).
  Скрытые с тулбара помечаются индикатором.
- Полные карточки (Settings → «Show full package cards»): + описание и бейджи (Runtime, Toolbar,
  «vX available», покупка).
- Вкладка Updates: зелёная `Update to X.Y.Z` вместо Run.
- Меню `⋯`: Run · [Update to X] · Details · [Open Folder — dev] · [Help] · Hide from Toolbar / Show in Toolbar ·
  [Copy GUID, Copy Path — dev] · — · Uninstall (красным).
- Пусто: «No packages installed» / «No packages match» + Refresh.

### Details — `details.jpg`
- Хлебные крошки: `← Back / Installed|Discover / <Name>`.
- Слева: hero (иконка 48, имя, «Version X by Y», бейджи Runtime · channel · License · Toolbar ·
  Online info / Offline info), кнопки `Run` + `Uninstall` (или `Install`, или `Update to X`).
- Блок покупки/доната с текстом и кнопкой (`Donate` / метка из `purchaseButtonLabel`).
- Вкладки: **Description** (Markdown: заголовки, списки, цитаты, код; ниже секция Links:
  Copy link, MaxPkg page, Homepage, Documentation, Support, License, Open Folder),
  **Screenshots N** (большой просмотрщик со стрелками, подпись, лента миниатюр, полноэкранный просмотр),
  **Changelog N** (группы по версиям с датой; бейджи типов Added/Fixed/Changed/Improved/Removed своим цветом).
- Справа «PACKAGE INFORMATION»: Package ID (с кнопкой копирования), Version, Release date,
  3ds Max («2022 and newer» / «Any version»), Author, Type, Channel, License, Integration, Packager — моноширинные значения.

### Settings — модальное окно поверх Manager (`settings-*.jpg`)
Левая навигация: General, Updates, Toolbar, Themes, Developer, [Endpoint — dev], About, Uninstall (красным). Переключатели — зелёные switch.
- **General:** Language (English); Start Runtime with 3ds Max; Open Manager on startup; Show notifications; Show full package cards in Installed views.
- **Updates:** Check package updates automatically; Check Runtime updates automatically; Download updates automatically; Check interval (Every hour … Every week).
- **Toolbar (= Toolbar Configurator):** заголовок + «Show toolbar»; **Live preview** с текстовым резюме
  «Top · Regular · Large icons · Medium · Version»; сегментированные кнопки:
  Position (Top, Bottom, Left, Right, Floating Horizontal, Floating Vertical — с мини-глифами),
  Spacing (Regular/Compact), Icon size (S/M/L), Button style (Icons only/Narrow/Medium/Wide),
  Second line (None/Version/Developer); примечание для компактных позиций; кнопки
  Reset package order, Reset toolbar position (только floating), Reset toolbar defaults.
- **Themes:** Manager theme, Toolbar theme (независимо).
- **Developer:** Enable developer mode, Enable debug logging.
- **Endpoint (dev):** Base endpoint.
- **About:** версия, два абзаца о MaxPkg, `Copy Runtime info`.
- **Uninstall:** описание, блок «Your scenes are safe.», 3 шага, `Uninstall MaxPkg` → подтверждение «Uninstall MaxPkg now?» Cancel / Yes, uninstall.

### Онбординг (отдельное окно, тема Manager)
«Your next steps» — три карточки: `01 / DISCOVER` Find your next script → Browse scripts;
`02 / PERSONALIZE` Set up your toolbar → Customize toolbar; `03 / UPDATES` How should scripts update? —
радио Automatically / Manually (сохраняется сразу). Футер: «This window stays open while you explore.» + Close.

### Result dialog (установка/удаление Runtime)
Заголовок, резюме, версия, состояние автозапуска, «Quick help» с тремя шагами, статус success/error.

## 7. Адаптивность (повторить те же пороги)

| Ширина | Поведение |
|---|---|
| ≥ 1200 | Discover: боковая панель категорий слева (330 px) |
| < 1200 | Категории — выпадающий список рядом с поиском |
| < 900 | Details: одна колонка, Package information под основным блоком |
| < 760 | Toolbar Configurator: подписи над группами кнопок |
| < 720 | Кнопки шапки — только иконки (с tooltip) |
| < 540 | Блок покупки: вертикальная раскладка |
| 680 | Минимальная ширина контента |

Улучшение без смены UX: в оригинале сетка всегда 3 колонки по 32% (min 230 px). В Qt — та же
карточка, но число колонок вычисляется по ширине (1–4), чтобы карточки не сжимались и не обрезались.
Масштаб DPI: оригинал вручную масштабирует WebBrowser; в Qt — логические пиксели и шрифты в pt.

## 8. Темы

- 6 наборов: Default, 3ds Max Dark, Midnight Blue, Forest Green, Light Studio, Violet Night
  (`themes/manager/*.ini`, ~65 семантических токенов: background*, surface*, border*, selectionBlue*,
  text*, accent*, success*, switch*, warning*, danger*, changed*, shadow*, overlay, icon*, brandIcon;
  `themes/toolbar/*.ini`, 14 токенов). Дополнительные INI-файлы подхватываются автоматически,
  неполные — с фолбэком на Default.
- Иконки — Lucide SVG, перекрашиваются под тему (`ui/common/icons/*.svg`).
- В Qt: те же INI-токены → QSS/палитра, тот же Default по умолчанию (пожелание пользователя
  «как в оригинале» приоритетнее дефолта Warm Graphite из навыка), выбор применяется ко всем окнам сразу.

## 9. Тулбар

### Как сейчас
- Docked: `rollout` с WebBrowser, зарегистрированный как CUI dialog bar
  (`cui.RegisterDialogBar` + `cui.DockDialogBar` top/bottom/left/right).
  Floating: отдельная WinForms-форма без рамки + WebBrowser + панель-ручка для перетаскивания
  (6 точек), владелец — окно Max, позиция сохраняется и ограничивается рабочей областью монитора.
- **Любое изменение (видимость, порядок, тема, обновления) полностью уничтожает и создаёт тулбар заново.**
- Состав: кнопка бренда `maxpkg` (всегда первая, открывает Manager, красный бейдж с числом обновлений),
  затем кнопки пакетов по сохранённому порядку (иконка + имя/кнопочное имя + вторая строка версия/автор),
  стрелки `‹ ›` прокрутки при переполнении.
- Left/Right/Floating — всегда только иконки; размеры: иконка S/M/L = 22/26/30 (compact 18/22/26),
  текстовые кнопки 30/34/38 высотой, ширины Narrow/Medium/Wide (Wide = 150 px).
- Alt + перетаскивание переупорядочивает кнопки прямо на тулбаре (с автопрокруткой и «призраком»),
  порядок сразу отражается в Installed.

### Что плохо в оригинале
- Любое изменение (порядок, видимость, тема, счётчик обновлений) уничтожает и создаёт заново окно с WebBrowser:
  мигание, утечки, риск GC-ошибки.
- Два разных механизма: docked = CUI dialog bar, floating = отдельная WinForms-форма со своей ручкой.
- Перетаскивание тулбара мышью не синхронизируется с Settings.
- WebBrowser перехватывает фокус клавиатуры (постоянные `enableAccelerators = true`).
- Размеры зашиты вручную, DPI 150–200% подгоняется хаками.

### Qt-версия — переписываем толково (согласовано с пользователем)
**1. Одна модель, точечные обновления.** `ToolbarController` держит список элементов
(guid, иконка, заголовок, вторая строка, флаг обновления, состояние «занят»), вычисляет diff
(добавить / удалить / переставить / обновить одну кнопку). **Тулбар никогда не пересоздаётся.**

**2. Нативный `QToolBar` в главном окне Max** (`qtmax.GetQMaxMainWindow()` — `QMainWindow`), уникальный `objectName`:
- стыковка ко всем 4 краям и отрыв в плавающий режим средствами Qt, как у родных тулбаров Max;
- ориентация переключается автоматически: вертикально — только иконки, горизонтально — текстовые кнопки;
- сигналы `topLevelChanged` / `orientationChanged` / смена области сразу пишут положение в настройки,
  Settings всегда показывает фактическое положение;
- шесть позиций настроек (top, bottom, left, right, floatinghorizontal, floatingvertical) сохраняются
  и реализованы одним механизмом; плавающая геометрия хранится отдельно для каждой ориентации
  (ключи `FloatingHorizontalX/Y`, `FloatingVerticalX/Y`), с ограничением по рабочей области монитора;
- восстановление положения — после того как Max восстановил свою раскладку окна.

**3. Кнопка `ToolbarButton`** (наследник `QToolButton`), вид как в оригинале:
- иконка S/M/L, имя пакета или buttonName, вторая строка Version/Developer/None,
  стили Icons only / Narrow / Medium / Wide, плотность Regular/Compact (размеры — раздел «Как сейчас»);
- SVG рендерится под текущий devicePixelRatio, чётко на 150–200% и при переносе между мониторами;
- кнопка `maxpkg` всегда первая, бейдж числа обновлений; во время проверки обновлений — индикатор;
- на кнопке пакета — точка «есть обновление»; при установке/обновлении — индикатор занятости и блокировка;
- `setFocusPolicy(Qt.NoFocus)` — тулбар не перехватывает горячие клавиши Max;
- tooltip: имя, версия, автор, «Hold Alt and drag to reorder».

**4. Поведение (дополнения, привычное не ломаем):**
- правый клик по пакету: Run, Details, Update to X, Hide from Toolbar, Move Left, Move Right, Toolbar settings…;
- правый клик по `maxpkg`: Open Manager, Check Updates, Toolbar settings…, Hide toolbar;
- Alt + перетаскивание сохраняется, плюс линия-индикатор места вставки и автопрокрутка; порядок сразу отражается в Installed;
- переполнение: встроенный шеврон `»` QToolBar с меню скрытых кнопок (как у родных тулбаров Max) вместо стрелок `‹ ›`
  (пользователь не возражал против рекомендации; при желании можно вернуть стрелки);
- новая тема тулбара «3ds Max (native)» — цвета из палитры Max (`QApplication.palette()`),
  выглядит родным в светлой и тёмной теме Max; остальные 6 тем остаются;
- живой предпросмотр в Settings → Toolbar рисуется теми же `ToolbarButton`, поэтому всегда совпадает с реальным тулбаром.

**5. Надёжность.** Тулбар принадлежит владельцу сессии (lifecycle из навыка): при перезапуске Runtime
снимается с главного окна (`removeToolBar` + `deleteLater`), повторный запуск не плодит дубликаты.
Если главное окно не `QMainWindow`, фолбэк — плавающее окно `Qt.Tool` с той же ручкой из точек.

## 10. Технические проблемы оригинала (причины перехода)

1. **MaxScript выполняется в фоновом потоке.** `updater.ms` и `self-updater.ms` используют
   `CSharpUtilities.SynchronizingBackgroundWorker`, и обработчик `DoWork` — это MaxScript-функция
   (HTTP, разбор INI, логирование, а при самообновлении — копирование файлов). `DoWork` идёт вне главного
   потока; MaxScript не потокобезопасен → **наиболее вероятная причина «MAXScript Garbage Collection Error»**.
   Qt-версия: в воркерах только чистый Python без `pymxs`, результат — сигналом в главный поток.
2. Синхронные HTTP-запросы в главном потоке: открытие деталей пакета подвешивает Max (замер: ~22 с).
3. Полное пересоздание WebBrowser-тулбара на каждое изменение.
4. Все ответы API пишутся в один файл `data/api-response.ini` и читаются `getINISetting` — гонки при параллельных запросах.
5. Самообновление берёт ветку `main`, а не опубликованный релиз.
6. WebBrowser = движок IE (режим IE9) — ограничения вёрстки и нестабильная отрисовка.

## 11. Соответствие компонентов

| Оригинал | Qt/Python |
|---|---|
| `startup.ms`, макрос, шим | тонкий `.ms`-лаунчер → `python.ExecuteFile bootstrap.py`; MaxScript-фасад `MaxPkg` |
| `core/scanner, settings, ini, utils` | `domain/` — чистый Python (configparser с UTF-16) |
| `http, repository, updater, image-cache` | `workers.py` + `urllib`/`QNetworkAccessManager`, без `pymxs` в потоках |
| `launcher, installer, uninstaller, self-updater` | `max_api.py` (главный поток) + операции через один lock |
| `ui/manager/*` | `ui/manager/` — QWidget-экраны, общая библиотека контролов |
| `ui/toolbar/*`, `core/toolbar.ms` | `ui/toolbar/` — `QToolBar` + floating-окно |
| `themes/*.ini` | те же INI → QSS |
| `notifier.ms` (tray balloon) | `QSystemTrayIcon.showMessage` или тост в окне Max |
