# SQUAD VPN

Отбирает живые и быстрые публичные VPN-узлы (VLESS, VMess, Trojan,
Shadowsocks, Hysteria2) из открытых источников, проверяет их через ядро
Mihomo и раздаёт подпиской для телефона или в программе для Windows.

**Версия 1.5.2.** Что нового — в [CHANGELOG.md](CHANGELOG.md).

Своих серверов у проекта нет: это чужие публичные узлы, любой может пропасть
в любой момент. Поэтому проверка идёт постоянно, а программа сама
переключается на рабочий узел.

## Подписка для телефона

Добавь ссылку как подписку в v2rayNG, Hiddify, INCY, Happ и т. п.
Обновляется каждый час.

| Подписка | Ссылка |
| --- | --- |
| **топ-10**, начни с неё | `https://raw.githubusercontent.com/JEFFRIPPER/SQUAD_VPN/subs/top.b64` |
| **100 лучших** | `https://raw.githubusercontent.com/JEFFRIPPER/SQUAD_VPN/subs/best.b64` |
| **белые списки**, когда глушат мобильный интернет | `https://raw.githubusercontent.com/JEFFRIPPER/SQUAD_VPN/subs/whitelist.b64` |

Для Clash и Mihomo замени `.b64` на `.yaml`. Если GitHub не открывается,
работает зеркало: `https://cdn.jsdelivr.net/gh/JEFFRIPPER/SQUAD_VPN@subs/top.b64`.
Подписку «белые списки» добавь заранее, пока интернет работает.

## Программа для Windows

1. Скачай **SQUAD-VPN.exe** из
   [последнего релиза](https://github.com/JEFFRIPPER/SQUAD_VPN/releases/latest).
2. Запусти и нажми **«Установить»**.

Дальше всё само: установка, автозапуск, проверка узлов из твоей сети,
подключение в один клик и обновления. Exe без цифровой подписи, поэтому
антивирус может спросить о нём при первом запуске.

## Приложение для Android

Скачай [SQUAD-VPN.apk](https://github.com/JEFFRIPPER/SQUAD_VPN/releases/download/android-latest/SQUAD-VPN.apk)
на телефон и установи (Android 8 и новее; разреши установку из браузера).
Внутри те же подписки SQUAD, ядро Xray, выбор лучшего узла и смена узла,
если текущий перестал отвечать. Приложение обновляется само.

## Подробности

Как отбираются узлы, профили, API, команды, обновления по воздуху и
безопасность описаны в [docs/REFERENCE.md](docs/REFERENCE.md).

Разработка: `pip install -e ".[dev]"`, затем `pytest -q` и `ruff check .`.

Лицензия: [MIT](LICENSE).
