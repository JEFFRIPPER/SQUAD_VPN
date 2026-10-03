# SQUAD VPN

SQUAD VPN — самостоятельный агрегатор публичных VPN/proxy-конфигураций.
Он собирает данные из нескольких независимых источников, нормализует и
дедуплицирует узлы, проверяет их через Mihomo, хранит историю качества и
генерирует smart-подписки только из актуальных результатов.

## Готовые подписки

GitHub Actions каждый час собирает, проверяет и публикует подписки в ветку
[`subs`](https://github.com/JEFFRIPPER/SQUAD_VPN/tree/subs). Компьютер для
этого не нужен. Вставь ссылку в VPN-клиент как подписку:

| Подписка | base64 (v2rayNG, Hiddify, INCY…) | Clash / Mihomo |
| --- | --- | --- |
| все живые | https://raw.githubusercontent.com/JEFFRIPPER/SQUAD_VPN/subs/all.b64 | https://raw.githubusercontent.com/JEFFRIPPER/SQUAD_VPN/subs/all.yaml |
| balanced | https://raw.githubusercontent.com/JEFFRIPPER/SQUAD_VPN/subs/balanced.b64 | https://raw.githubusercontent.com/JEFFRIPPER/SQUAD_VPN/subs/balanced.yaml |
| fast | https://raw.githubusercontent.com/JEFFRIPPER/SQUAD_VPN/subs/fast.b64 | https://raw.githubusercontent.com/JEFFRIPPER/SQUAD_VPN/subs/fast.yaml |
| stable | https://raw.githubusercontent.com/JEFFRIPPER/SQUAD_VPN/subs/stable.b64 | https://raw.githubusercontent.com/JEFFRIPPER/SQUAD_VPN/subs/stable.yaml |

Подписки по странам и протоколам перечислены в README ветки `subs`.
Если `raw.githubusercontent.com` не открывается, используй зеркало:
`https://cdn.jsdelivr.net/gh/JEFFRIPPER/SQUAD_VPN@subs/all.b64`.

Важно: в облаке узлы проверяются с серверов GitHub (США/Европа). Узел, живой
оттуда, может быть недоступен из твоей сети. Проверка из своей сети — это
`serve --watch` на своём компьютере (см. ниже), сеть пробников — план v0.7.

## Текущая версия

**0.5.0 — автообновление и публикация**

Уже работает:

- VLESS, VMess, Trojan, Shadowsocks, Hysteria2/HY2;
- Reality, TLS, TCP, WebSocket, gRPC, XHTTP;
- YAML-реестр независимых источников;
- приоритет, tags и лимит узлов для каждого источника;
- равномерная выборка из больших фидов;
- устойчивость к отдельным битым URI;
- fingerprint и дедупликация;
- SQLite с автоматической миграцией старых баз;
- активный health-check через Mihomo;
- latency, exit IP, country и ASN;
- история проверок;
- recent success rate;
- jitter по последним успешным проверкам;
- stability score и quality score;
- smart-подписки;
- периодический режим `watch`;
- HTTP API с динамическими подписками `/sub?...`;
- веб-панель: сводка, источники, узлы, история ping/jitter;
- фоновый цикл внутри сервера: `serve --watch`;
- автоочистка узлов, пропавших из источников, и редкая перепроверка мёртвых;
- публикация подписок в git-ветку с постоянными https-ссылками;
- ежечасное обновление через GitHub Actions;
- Mihomo для Windows, Linux и macOS (скачивается автоматически).

## Источники

Основной реестр: `config/sources.yaml`.

Каждая запись поддерживает:

```yaml
- name: example
  url: https://example.com/sub.txt
  enabled: true
  priority: 20
  max_nodes: 250
  tags: [github, aggregate]
```

По умолчанию проект использует несколько независимых публичных GitHub-фидов.
Akres оставлен в конфигурации только как выключенный контрольный источник и
не участвует в штатном сборе.

Статистика каждого источника сохраняется в SQLite: количество запросов,
успехи/ошибки, число найденных и выбранных узлов, длительность последней
загрузки и текст последней ошибки.

Посмотреть состояние:

```powershell
squad-vpn sources
```

## Установка

Требуется Python 3.11+.

```powershell
cd "D:\CODE PROECTS\SQUAD_VPN"
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
squad-vpn setup-mihomo
```

На старых x64 CPU установщик автоматически использует совместимую сборку
Mihomo (`windows-amd64-compatible`). Бинарник хранится локально в
`tools/mihomo/` и не коммитится в Git.

## Основной цикл

Один полный проход:

```powershell
squad-vpn run
```

Он выполняет:

```text
sources.yaml
    -> collect
    -> parse / normalize / deduplicate
    -> SQLite
    -> validation candidates
    -> Mihomo health-check
    -> Geo / ASN
    -> jitter / stability / quality
    -> export
    -> smart subscriptions
```

По умолчанию за один цикл проверяется до 200 узлов. Сначала выбираются
непроверенные узлы случайно по всему пулу, затем — самые давно проверенные.
Это позволяет постепенно покрывать большой каталог без полного перебора
каждый час.

## Периодический режим

Запуск цикла раз в час:

```powershell
squad-vpn watch --interval-minutes 60
```

Или просто:

```text
scripts\start-watch.cmd
```

`start-watch.cmd` проверяет наличие локального Mihomo и при необходимости
устанавливает его автоматически.

Для тестового одного цикла:

```powershell
squad-vpn watch --cycles 1 --limit 20 --geo-limit 0
```

## Smart-подписки

После `run` или `export` каталог `data/output/smart/` содержит:

```text
smart/
├── balanced
├── balanced.yaml
├── fast
├── fast.yaml
├── stable
├── stable.yaml
├── country/
│   ├── DE
│   ├── DE.yaml
│   └── ...
├── protocol/
│   ├── vless
│   ├── vless.yaml
│   └── ...
└── index.json
```

Профили:

- `balanced` — общий баланс доступности, скорости и стабильности;
- `fast` — свежие живые узлы с низкой задержкой;
- `stable` — узлы с высокой стабильностью по истории;
- `country/*` — подписки по реальному exit country;
- `protocol/*` — подписки по протоколу.

Собственная выборка по фильтрам:

```powershell
squad-vpn smart --country DE --protocol vless --max-latency 200 `
  --min-score 70 --min-stability 60 --limit 100
```

## Автообновление

Полный цикл — `collect → validate → cleanup → export → publish`. Если один
шаг падает (нет сети, нет Mihomo), остальные всё равно выполняются, и
подписки обновляются из уже накопленных данных. Mihomo, если его нет,
скачивается автоматически.

### Всё в одном окне

```powershell
squad-vpn serve --watch
```

Сервер отдаёт панель и API и сам раз в час (`--interval-minutes`) выполняет
полный цикл. В панели видно, когда был последний цикл и когда следующий;
кнопка «Обновить сейчас» запускает цикл сразу. Тот же режим запускает
`scripts\open-dashboard.cmd`.

### Очистка

Узлы, которых источники не отдают больше 3 дней (`--unseen-days`), удаляются
вместе с историей; мёртвые и пропавшие — уже через сутки. Мёртвые узлы, которые
источники ещё публикуют, не удаляются (иначе они вернулись бы «новыми»), а
перепроверяются реже — раз в 6 часов. Вручную: `squad-vpn cleanup`.

### Публикация

```powershell
squad-vpn publish                    # один раз
squad-vpn serve --watch --publish    # после каждого цикла
squad-vpn run --publish
```

Публикация собирает smart-подписки (plain, base64, Mihomo YAML, по профилям,
странам и протоколам), `stats.json` и README со ссылками и делает один
коммит в отдельную ветку (по умолчанию `subs-home`, параметр
`--publish-branch`). Ветка каждый раз перезаписывается целиком, поэтому её
история не растёт. В `main`/`master` публиковать нельзя. Репозиторий берётся
из `origin` проекта, `--publish-repo` или переменной `SQUAD_PUBLISH_REPO`;
для пуша используются твои обычные учётные данные git.

### GitHub Actions

Workflow `.github/workflows/update-subs.yml` раз в час на серверах GitHub
выполняет `run --publish --publish-branch subs`. База с историей узлов
переносится между запусками через кэш Actions. Запустить вручную:
вкладка **Actions → Update subscriptions → Run workflow**.

GitHub отключает расписание, если в репозитории 60 дней не было коммитов;
тогда его нужно включить заново на той же вкладке.

## API и веб-панель

Проще всего: дважды щёлкнуть `scripts\open-dashboard.cmd` — он обновит
зависимости, запустит сервер и сам откроет панель в браузере. Окно не
закрывать, пока панель нужна.

Вручную:

```powershell
squad-vpn serve
```

Панель откроется на <http://127.0.0.1:8080/>, документация API — на
<http://127.0.0.1:8080/api/docs>. API только читает базу, поэтому его можно
держать запущенным параллельно с `watch` (SQLite работает в режиме WAL).

По умолчанию сервер слушает только `127.0.0.1`. Чтобы открыть доступ из сети,
нужен токен:

```powershell
squad-vpn serve --host 0.0.0.0 --token "длинный-случайный-токен"
# или через переменную окружения SQUAD_VPN_TOKEN
```

Без токена запуск на внешнем адресе отклоняется (обойти можно только явным
`--insecure-no-token`). Токен передаётся как `?token=...` (так умеют все
VPN-клиенты) или заголовком `Authorization: Bearer ...`. Панель открывается
ссылкой `http://host:8080/?token=...`; `/` и `/health` данных узлов не отдают
и доступны без токена.

### Динамическая подписка `/sub`

| Параметр | Значение |
| --- | --- |
| `profile` | `balanced`, `fast`, `stable`, `all` — задают значения по умолчанию |
| `country` | код страны, например `DE` |
| `protocol` | `vless`, `vmess`, `trojan`, `ss`, `hysteria2` |
| `min_score`, `min_stability` | 0–100 |
| `max_latency` | максимальный ping, мс |
| `checked_within_hours`, `seen_within_hours` | свежесть проверки и появления в источниках (по умолчанию 12 и 48) |
| `limit` | до 2000 (по умолчанию из профиля, иначе 300) |
| `format` | `plain`, `base64` (v2rayN, Hiddify, v2rayNG), `mihomo` (Clash Meta YAML) |

Явные параметры перекрывают значения профиля. В подписку попадают только
живые узлы. Примеры:

```text
/sub?profile=fast&format=base64
/sub?profile=stable&country=DE&format=mihomo
/sub?protocol=vless&max_latency=300&limit=50
```

Ответ содержит заголовки `profile-update-interval: 1` (клиенты обновляют
подписку раз в час) и `x-squad-nodes` с количеством узлов.

### JSON API

| Метод | Описание |
| --- | --- |
| `GET /health` | статус и версия |
| `GET /api/stats` | количество узлов, средние ping/jitter/score, разбивка по странам и протоколам |
| `GET /api/nodes` | узлы с фильтрами (`alive_only`, `country`, `protocol`, `min_score`, `min_stability`, `max_latency`), сортировкой `sort=score|stability|latency|jitter|checked|seen` и пагинацией `limit`/`offset` |
| `GET /api/nodes/{fingerprint}` | узел и история проверок (`?history=50`) |
| `GET /api/sources` | здоровье источников |
| `GET /api/profiles` | параметры smart-профилей |
| `GET /api/cycle` | статус фонового цикла (`serve --watch`) |
| `POST /api/cycle/run` | запустить цикл сейчас |

`/api/nodes` не отдаёт учётные данные и исходные URI узлов — они есть только
в `/sub`. В истории каждой проверки есть поле `probe_id` (сейчас всегда
`local`) — задел под сеть пробников из v0.7.

## Выходные файлы

```text
data/output/
├── all
├── all.yaml
├── best
├── best.yaml
├── health.json
├── main.json
├── sources.json
├── protocols/
└── smart/
```

`health.json` содержит для каждого узла текущие метрики без изменения
исходного URI: alive, latency, jitter, recent success rate, stability,
quality score, exit IP, country, ASN и счётчики проверок.

## Скоринг

Quality Score учитывает:

- недавнюю долю успешных проверок;
- latency;
- jitter;
- количество накопленных проверок;
- текущий статус alive/dead.

Stability Score сильнее ориентирован на recent success rate и jitter.
Один удачный health-check не даёт узлу максимального доверия.

## Полезные команды

```powershell
squad-vpn collect
squad-vpn validate --limit 200
squad-vpn export
squad-vpn sources
squad-vpn run
squad-vpn watch --interval-minutes 60
```

Повторная проверка только после заданного интервала:

```powershell
squad-vpn validate --recheck-minutes 60
```

Как распределяется лимит `--limit`:

- половина бюджета уходит на новые (ещё не проверенные) узлы, половина —
  на повторную проверку уже известных, сначала ранее живых; неиспользованная
  часть одной половины отдаётся другой, поэтому поток новых узлов не
  «вытесняет» перепроверку живых;
- узлы, которых источники не отдают больше 72 часов, не проверяются;
- узел, который Mihomo не умеет конвертировать или из-за которого Mihomo
  отвергает конфиг, помечается мёртвым с понятной ошибкой (плохой узел
  изолируется делением пачки пополам), а не остаётся «непроверенным» навсегда;
- в `health_checks` хранится только 50 последних проверок на узел;
  накопленные счётчики успехов/ошибок живут в таблице `nodes`.

Экспорт удаляет устаревшие файлы в `protocols/`, `smart/country/` и
`smart/protocol/`, чтобы постоянные ссылки не отдавали мёртвые узлы.
Если Mihomo недоступен, `run`/`watch` пропускают проверку, но всё равно
обновляют подписки из уже накопленных данных.

## Тесты

```powershell
pytest -q
```

## Дальше

Дорога до 1.0:

1. ~~v0.4 — API + Dashboard~~;
2. ~~v0.5 — автообновление и публикация~~;
3. v0.6 — умный автоподбор: улучшенный ranking и failover;
4. v0.7 — сеть пробников: проверки с нескольких точек, региональный статус;
5. v0.8 — Windows-клиент поверх Mihomo с автопереключением;
6. v0.9 — продакшен-обвязка: конфиг, логирование, rate limit, API keys,
   кэш, backup базы, installer;
7. v1.0 — релиз.

SQUAD VPN не поднимает собственные VPN-серверы. Проект агрегирует и
проверяет публично доступные конфигурации; сами сетевые соединения выполняет
Mihomo. Доступность публичного узла может измениться в любой момент.

### Планировщик Windows

Для фонового запуска раз в час без открытого терминала:

```text
scripts\install-hourly-task.cmd
```

Задача запускает `scripts\run-once.cmd`, который сам переходит в корень
проекта, проверяет Mihomo и выполняет полный `squad-vpn run`.

Удалить задачу:

```text
scripts\remove-hourly-task.cmd
```
