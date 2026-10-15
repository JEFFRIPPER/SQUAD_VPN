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

## Бесплатно на iOS 26: подписка в готовом клиенте

На iOS 26 без платной подписи VPN-приложение не поставить, поэтому проще
добавить подписку SQUAD VPN в готовый клиент: Happ, v2RayTun, Streisand, V2Box.
В российском App Store их удалили (март 2026), поэтому ставь из App Store
другой страны:

1. Создай бесплатный Apple ID другой страны (например, Казахстан или США) на
   [account.apple.com](https://account.apple.com), способ оплаты «Нет».
2. На iPhone: App Store → значок профиля → «Выйти» (только из App Store,
   iCloud не трогай) → войди новым Apple ID.
3. Скачай Happ или v2RayTun, потом можно вернуть свой Apple ID: приложение останется.
4. Скопируй ссылку подписки, в клиенте нажми «+» → вставить из буфера:

| Подписка | Ссылка |
| --- | --- |
| топ-10 | `https://raw.githubusercontent.com/JEFFRIPPER/SQUAD_VPN/subs/top.b64` |
| 300 лучших | `https://raw.githubusercontent.com/JEFFRIPPER/SQUAD_VPN/subs/best.b64` |
| белые списки (добавь заранее) | `https://raw.githubusercontent.com/JEFFRIPPER/SQUAD_VPN/subs/whitelist.b64` |

Если GitHub не открывается: `https://cdn.jsdelivr.net/gh/JEFFRIPPER/SQUAD_VPN@subs/top.b64`.

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
