"""Windows autostart: start the agent silently at logon, plus a desktop shortcut.

Uses the per-user Startup folder (no administrator rights needed) and a tiny
VBScript that launches ``pythonw`` without a console window.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


STARTUP_NAME = "SQUAD VPN.vbs"
SHORTCUT_NAME = "SQUAD VPN.url"
CSIDL_STARTUP = 0x0007
CSIDL_DESKTOPDIRECTORY = 0x0010


def _known_folder(csidl: int) -> Path:
    """Real folder path (handles OneDrive-redirected Desktop, non-ASCII names)."""
    import ctypes
    from ctypes import wintypes

    buffer = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
    result = ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buffer)  # type: ignore[attr-defined]
    if result != 0:
        raise OSError(f"SHGetFolderPathW вернул {result}")
    return Path(buffer.value)


def pythonw_path() -> Path:
    executable = Path(sys.executable)
    candidate = executable.with_name("pythonw.exe")
    return candidate if candidate.exists() else executable


def startup_script(root: Path, pythonw: Path) -> str:
    def quote(value: Path) -> str:
        return str(value).replace('"', '""')

    return (
        "' SQUAD VPN: запуск агента без окна при входе в Windows\r\n"
        'Set shell = CreateObject("WScript.Shell")\r\n'
        f'shell.CurrentDirectory = "{quote(root)}"\r\n'
        f'shell.Run """{quote(pythonw)}"" -m squad_vpn agent", 0, False\r\n'
    )


def shortcut_body(port: int = 8080) -> str:
    return f"[InternetShortcut]\r\nURL=http://127.0.0.1:{port}/\r\n"


def enable(root: Path, *, port: int = 8080) -> list[Path]:
    if os.name != "nt":
        raise OSError("Автозапуск настраивается только в Windows")
    created = []
    startup = _known_folder(CSIDL_STARTUP) / STARTUP_NAME
    # UTF-16 with BOM: WSH reads it correctly for any path characters.
    startup.write_text(startup_script(root, pythonw_path()), encoding="utf-16")
    created.append(startup)
    shortcut = _known_folder(CSIDL_DESKTOPDIRECTORY) / SHORTCUT_NAME
    shortcut.write_text(shortcut_body(port), encoding="utf-8")
    created.append(shortcut)
    return created


def disable() -> list[Path]:
    if os.name != "nt":
        return []
    removed = []
    for csidl, name in ((CSIDL_STARTUP, STARTUP_NAME), (CSIDL_DESKTOPDIRECTORY, SHORTCUT_NAME)):
        path = _known_folder(csidl) / name
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed
