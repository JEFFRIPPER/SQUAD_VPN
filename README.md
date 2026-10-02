# SQUAD VPN

SQUAD VPN — самостоятельный агрегатор публичных VPN/proxy-конфигураций.
Он собирает данные из нескольких независимых источников, нормализует и
дедуплицирует узлы, проверяет их через Mihomo, хранит историю качества и
генерирует smart-подписки только из актуальных результатов.

## Текущая версия

**0.3.0 — Multi-source + Smart Subscriptions**

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
- периодический режим `watch`.

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

## Тесты

```powershell
pytest -q
```

## Дальше

План после v0.3:

1. собственный HTTP API для динамических подписок;
2. удалённые probe-агенты для разных сетей/операторов;
3. реальный BWL-check вместо ASN-эвристики;
4. web dashboard с историей latency/stability;
5. Windows-клиент с auto-select и failover.

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
