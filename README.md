# SQUAD VPN

SQUAD VPN — агрегатор и активный валидатор публичных VPN/proxy-конфигураций.
Проект собирает узлы, нормализует их, удаляет дубли, реально проверяет через
Mihomo, хранит историю и выдаёт лучшие конфиги по измеренному качеству.

## Статус

Текущая версия: **0.2.0 / Active Validation MVP**.

Работает:

- параллельный сбор URL-источников;
- plain и base64 подписки;
- VLESS, VMess, Trojan, Shadowsocks, Hysteria2/HY2;
- канонический fingerprint и дедупликация;
- SQLite с `first_seen` / `last_seen`;
- автоматическая миграция базы v0.1 -> v0.2;
- официальный Mihomo как внешний validator engine;
- Reality, TLS, WS, gRPC, XHTTP и базовые transport-параметры;
- реальный HTTP health-check каждого узла;
- latency и состояние alive/dead;
- история всех проверок в `health_checks`;
- success/failure counters и Quality Score;
- определение exit IP, страны и ASN для живых узлов;
- plain и Clash/Mihomo YAML подписки.

## Установка

Требуется Windows 10/11 x64 и Python 3.11+.

```powershell
cd "D:\CODE PROECTS\SQUAD_VPN"
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
```

Установить актуальный официальный Mihomo:

```powershell
squad-vpn setup-mihomo
```

Команда скачивает latest stable `windows-amd64-compatible` из официального
репозитория MetaCubeX. Бинарник хранится локально в `tools/mihomo/` и не
коммитится в Git.

## Основной цикл

Добавьте URL подписок в `config/sources.txt`, по одному на строку.

```powershell
squad-vpn collect
squad-vpn validate
squad-vpn export
```

Или одним запуском:

```powershell
squad-vpn run
```

### Проверка

По умолчанию используется HTTP 204 endpoint и до 16 параллельных проверок:

```powershell
squad-vpn validate --timeout-ms 5000 --concurrency 16 --geo-limit 10
```

`--geo-limit` определяет, для скольких самых быстрых живых узлов за проход
нужно дополнительно получить реальный exit IP, страну и ASN.

### Экспорт

```powershell
squad-vpn export
```

В `data/output/` создаются:

```text
all               все известные URI
all.yaml          все узлы в формате Mihomo/Clash
best              только узлы с последним alive=true
best.yaml         только живые узлы для Mihomo/Clash
protocols/        разрез всех узлов по протоколам
health.json       измерения без секретов конфигов
main.json         агрегированная статистика + top-20
```

Можно ограничить экспорт:

```powershell
squad-vpn export --alive-only --min-score 70 --limit 100
```

## Quality Score

Текущий score 0..100 учитывает:

- 65% — исторический success rate;
- 30% — последнюю измеренную latency;
- 5% — confidence по количеству накопленных проверок;
- последний `alive=false` дополнительно штрафует рейтинг.

Формула намеренно консервативная: один успешный тест не делает новый узел
автоматически «идеальным».

## Архитектура

```text
Sources -> Collector -> Parser -> Fingerprint/Dedup -> SQLite
                                                   -> Mihomo Validator
                                                   -> Health History
                                                   -> Exit IP / Geo / ASN
                                                   -> Quality Score
                                                   -> best / YAML / JSON
```

Mihomo используется как внешний сетевой движок. SQUAD VPN отвечает за сбор,
данные, историю, анализ, ranking и публикацию подписок.

## Следующие этапы

1. Jitter, packet-loss и bandwidth probes.
2. Smart subscriptions по стране, ping, протоколу и score.
3. Несколько probe-агентов для проверки из разных сетей/регионов.
4. BWL status по реальным probe-результатам, а не только ASN-эвристике.
5. Web UI + JSON API.
6. Windows-клиент с автоматическим выбором и failover.

## Тесты

```powershell
pytest
```
