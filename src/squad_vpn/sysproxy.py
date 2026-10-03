"""Windows system proxy (WinINet, per user — no administrator rights needed).

Browsers and most Windows apps follow it. The previous settings are saved
before switching and restored exactly, so disconnecting gives back whatever
the user had (including another proxy).
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass


KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
BYPASS = "localhost;127.*;10.*;192.168.*;<local>"


@dataclass(slots=True)
class ProxyState:
    enabled: bool = False
    server: str = ""
    override: str = ""

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class ProxyBackend:
    """Reads and writes the proxy settings; replaced by a fake in tests."""

    supported = False

    def read(self) -> ProxyState:
        return ProxyState()

    def write(self, state: ProxyState) -> None:
        raise OSError("Системный прокси настраивается только в Windows")


class WindowsProxyBackend(ProxyBackend):
    supported = True

    def read(self) -> ProxyState:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as key:
            def value(name: str, default: object) -> object:
                try:
                    return winreg.QueryValueEx(key, name)[0]
                except FileNotFoundError:
                    return default

            return ProxyState(
                enabled=bool(value("ProxyEnable", 0)),
                server=str(value("ProxyServer", "")),
                override=str(value("ProxyOverride", "")),
            )

    def write(self, state: ProxyState) -> None:
        import ctypes
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, int(state.enabled))
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, state.server)
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, state.override)
        # Tell running apps the settings changed (39) and to reload them (37).
        internet_set_option = ctypes.windll.wininet.InternetSetOptionW  # type: ignore[attr-defined]
        internet_set_option(0, 39, 0, 0)
        internet_set_option(0, 37, 0, 0)


def default_backend() -> ProxyBackend:
    return WindowsProxyBackend() if os.name == "nt" else ProxyBackend()


def ours(state: ProxyState, port: int) -> bool:
    return state.enabled and state.server in (f"127.0.0.1:{port}", f"localhost:{port}")


def enable(backend: ProxyBackend, port: int) -> ProxyState:
    """Point the system proxy at the local core; return what was there before."""
    previous = backend.read()
    backend.write(ProxyState(True, f"127.0.0.1:{port}", BYPASS))
    return previous


def restore(backend: ProxyBackend, previous: ProxyState | None, port: int) -> bool:
    """Put the saved settings back, but only if the proxy is still ours."""
    current = backend.read()
    if not ours(current, port):
        return False  # the user (or another app) changed it meanwhile: leave it alone
    backend.write(previous if previous is not None and not ours(previous, port) else ProxyState())
    return True
