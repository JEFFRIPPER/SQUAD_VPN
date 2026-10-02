# SQUAD VPN

SQUAD VPN — агрегатор публичных VPN/proxy-конфигураций с нормализацией,
дедупликацией, историей и последующей активной проверкой качества узлов.

Проект создаётся как более умная альтернатива простым каталогам подписок:
цель — выдавать не максимальное количество конфигов, а наиболее живые и
стабильные узлы с понятной статистикой.

## Статус

Текущая версия: **0.1.0 / Core MVP**.

Уже работает:

- загрузка нескольких URL-источников параллельно;
- чтение plain и base64 подписок;
- VLESS;
- VMess;
- Trojan;
- Shadowsocks;
- Hysteria2 / HY2;
- канонический fingerprint узла;
- дедупликация одинаковых конфигов;
- SQLite-хранилище с `first_seen` и `last_seen`;
- генерация общего файла подписки;
- генерация файлов по протоколам;
- генерация `main.json` со статистикой.

## Установка

Требуется Python 3.11+.

```powershell
cd "D:\CODE PROECTS\SQUAD_VPN"
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
```

Добавьте URL источников в `config/sources.txt`, по одному на строку.

## Использование

Собрать конфиги:

```powershell
squad-vpn collect
```

Импортировать локальный файл подписки:

```powershell
squad-vpn import-file .\subscription.txt
```

Сгенерировать каталог:

```powershell
squad-vpn export
```

Результаты создаются в `data/output/`, база — `data/squad_vpn.sqlite3`.

## Архитектура

```text
Sources -> Collector -> Parser -> Normalizer/Fingerprint
       -> SQLite -> Validator -> Scoring -> Export/API
```

## Следующие этапы

1. Mihomo/sing-box validator для реального подключения через каждый узел.
2. Измерение latency, jitter, success-rate и истории отказов.
3. Определение реального exit IP, страны и ASN.
4. Quality Score вместо бинарного `жив/мёртв`.
5. Clash/Mihomo YAML export.
6. Динамические smart-subscriptions по стране, ping и протоколу.
7. Отдельные probe-агенты для проверки доступности из разных сетей.
8. Web UI и JSON API.
9. Windows-клиент с автоматическим выбором и переключением сервера.

## Принцип проекта

SQUAD VPN не поднимает собственные VPN-серверы и не является сетевым
туннельным движком. Ядро проекта агрегирует, проверяет, ранжирует и публикует
конфигурации. Туннелирование планируется выполнять проверенными движками
Mihomo/sing-box.

## Тесты

```powershell
pytest
```
