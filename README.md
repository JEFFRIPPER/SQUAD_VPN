# SQUAD VPN

Отбирает живые и быстрые публичные VPN-серверы (VLESS, VMess, Trojan,
Shadowsocks, Hysteria2) из открытых источников, проверяет их и раздаёт
в программе для ПК, в приложениях для Android и iPhone или подпиской.

**Версия 2.1.1.** Что нового — в [CHANGELOG.md](CHANGELOG.md).

**Скачать:** [SQUAD-VPN.exe для Windows](https://github.com/JEFFRIPPER/SQUAD_VPN/releases/latest/download/SQUAD-VPN.exe)
и [SQUAD-VPN.apk для Android](https://github.com/JEFFRIPPER/SQUAD_VPN/releases/latest/download/SQUAD-VPN.apk),
файлы лежат в [последнем релизе](https://github.com/JEFFRIPPER/SQUAD_VPN/releases/latest).

## Клиенты

| [🖥️ ПК клиент (Windows)](app/README.md) | [📱 Android клиент](android/README.md) | [🍏 iPhone клиент](ios/README.md) |
| --- | --- | --- |
| SQUAD-VPN.exe: установка в один клик, проверка серверов из твоей сети, подключение одной кнопкой, обновления сами. | SQUAD-VPN.apk: встроенные подписки, ядро Xray, лучший сервер и смена сервера при обрыве, обход DPI, kill switch, тест скорости, виджет, обновления сами. | SQUAD-VPN.ipa: те же подписки и ядро Xray, самый быстрый сервер, смена сервера, если интернет не открылся, обход DPI. |
| [Подробнее →](app/README.md) | [Подробнее →](android/README.md) | [Подробнее →](ios/README.md) |

## Подписка без приложения

Добавь ссылку как подписку в v2rayNG, Hiddify, INCY, Happ и т. п.
Обновляется каждый час.

| Подписка | Ссылка |
| --- | --- |
| **топ-10**, начни с неё | `https://raw.githubusercontent.com/JEFFRIPPER/SQUAD_VPN/subs/top.b64` |
| **300 лучших** | `https://raw.githubusercontent.com/JEFFRIPPER/SQUAD_VPN/subs/best.b64` |
| **белые списки**, когда глушат мобильный интернет | `https://raw.githubusercontent.com/JEFFRIPPER/SQUAD_VPN/subs/whitelist.b64` |

Для Clash и Mihomo замени `.b64` на `.yaml`. Если GitHub не открывается,
работает зеркало: `https://cdn.jsdelivr.net/gh/JEFFRIPPER/SQUAD_VPN@subs/top.b64`.
Подписку «белые списки» добавь заранее, пока интернет работает.

Своих серверов у проекта нет: это чужие публичные серверы, любой может пропасть
в любой момент. Как они отбираются — в [docs/REFERENCE.md](docs/REFERENCE.md).

Лицензия: [MIT](LICENSE).
