# SQUAD VPN для iPhone

SQUAD-VPN.ipa лежит в релизах `ios-v<версия>` и в [последнем релизе](https://github.com/JEFFRIPPER/SQUAD_VPN/releases/latest).
Нужна iOS 16 или новее.

## Как установить

Apple даёт включать VPN только приложениям, подписанным платным аккаунтом
разработчика. Поэтому способ установки зависит от того, что у тебя есть:

| Способ | Цена | VPN работает |
| --- | --- | --- |
| [TrollStore](https://github.com/opa334/TrollStore) (iOS 14.0–16.6.1, 16.7 RC, 17.0) | бесплатно | да, навсегда, без переподписи |
| Sideloadly / AltStore с **платным** Apple ID (Apple Developer Program) | 99 $ в год | да, переподпись раз в год |
| Купленный сертификат разработчика (сервисы подписи) | от ~10 $ в год | да, если сертификат разрешает Network Extension |
| Sideloadly / AltStore с **бесплатным** Apple ID | бесплатно | **нет**: Apple вырезает разрешение VPN |

**TrollStore:** открой `SQUAD-VPN.ipa` в TrollStore → Install.

**Sideloadly:** подключи iPhone к ПК, перетащи `SQUAD-VPN.ipa` в Sideloadly, войди
Apple ID с платной подпиской разработчика, Start. На iPhone: Настройки → Основные →
VPN и управление устройством → доверять разработчику.

Если ни один способ не подходит, подписку SQUAD VPN можно добавить в бесплатные
приложения из App Store (Streisand, V2Box, Happ и т. п.):
`https://raw.githubusercontent.com/JEFFRIPPER/SQUAD_VPN/subs/top.b64`.

## Как устроено

- `App/`: SwiftUI-приложение (экран подключения, серверы, настройки), разбор ссылок
  и конфиги Xray по тем же правилам, что в `android/`.
- `Tunnel/`: Network Extension (Packet Tunnel). iOS отдаёт ему utun-интерфейс,
  ядро Xray читает пакеты прямо из него (tun-инбаунд с `xray.tun.fd`).
- `Shared/`: вызов ядра (libXray, `LibXrayInvoke`, API v3).
- `project.yml`: проект XcodeGen. Сборка в `.github/workflows/build-ios.yml` на
  macOS-машине GitHub: ядро собирается gomobile из XTLS/libXray (кэшируется),
  приложение без подписи, `ldid` вписывает разрешение VPN, результат —
  `SQUAD-VPN.ipa` в релизе `ios-v<версия>` (версия в `ios/version.properties`).
