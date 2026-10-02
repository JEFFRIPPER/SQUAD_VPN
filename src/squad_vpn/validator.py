from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

from .mihomo import MihomoProxy, build_runtime_config, dump_yaml
from .models import ProxyNode, ValidationResult


DEFAULT_TEST_URL = "https://www.gstatic.com/generate_204"
DEFAULT_BINARY = Path("tools/mihomo/mihomo.exe")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class MihomoValidator:
    def __init__(
        self,
        binary: str | Path = DEFAULT_BINARY,
        *,
        test_url: str = DEFAULT_TEST_URL,
        timeout_ms: int = 5000,
    ) -> None:
        self.binary = Path(binary)
        self.test_url = test_url
        self.timeout_ms = timeout_ms

    def _start(
        self,
        nodes: list[ProxyNode],
        directory: Path,
        controller_port: int,
        mixed_port: int,
    ) -> tuple[subprocess.Popen[str], list[MihomoProxy]]:
        if not self.binary.exists():
            raise FileNotFoundError(
                f"Mihomo не найден: {self.binary}. Выполни squad-vpn setup-mihomo"
            )
        config, converted = build_runtime_config(
            nodes, controller_port=controller_port, mixed_port=mixed_port
        )
        config_path = directory / "config.yaml"
        config_path.write_text(dump_yaml(config), encoding="utf-8")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen(
            [str(self.binary.resolve()), "-f", str(config_path), "-d", str(directory)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=flags,
        )
        return process, converted

    @staticmethod
    def _stop(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    async def _wait_ready(
        self,
        process: subprocess.Popen[str],
        base_url: str,
        timeout: float = 12.0,
    ) -> None:
        deadline = time.monotonic() + timeout
        async with httpx.AsyncClient(timeout=1.0) as client:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    output = process.stdout.read() if process.stdout else ""
                    raise RuntimeError(f"Mihomo завершился при запуске:\n{output[-2000:]}")
                try:
                    response = await client.get(f"{base_url}/version")
                    if response.is_success:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.15)
        raise TimeoutError("Mihomo API не запустился за отведённое время")

    async def _probe_one(
        self,
        client: httpx.AsyncClient,
        item: MihomoProxy,
        semaphore: asyncio.Semaphore,
    ) -> ValidationResult:
        async with semaphore:
            try:
                response = await client.get(
                    f"/proxies/{item.name}/delay",
                    params={
                        "url": self.test_url,
                        "timeout": self.timeout_ms,
                        "expected": "204",
                    },
                    timeout=(self.timeout_ms / 1000.0) + 2.0,
                )
                response.raise_for_status()
                delay = float(response.json()["delay"])
                return ValidationResult(item.fingerprint, True, latency_ms=delay)
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                return ValidationResult(item.fingerprint, False, error=str(exc)[:500])

    async def _enrich_geo(
        self,
        controller: httpx.AsyncClient,
        mixed_port: int,
        item: MihomoProxy,
        result: ValidationResult,
    ) -> None:
        try:
            select = await controller.put(
                "/proxies/SQUAD-VALIDATOR",
                json={"name": item.name},
                timeout=3.0,
            )
            select.raise_for_status()
            async with httpx.AsyncClient(
                proxy=f"http://127.0.0.1:{mixed_port}", timeout=8.0
            ) as proxied:
                ip_response = await proxied.get("https://api.ipify.org?format=json")
                ip_response.raise_for_status()
                exit_ip = str(ip_response.json()["ip"])
            async with httpx.AsyncClient(timeout=6.0) as direct:
                geo_response = await direct.get(f"https://ipwho.is/{exit_ip}")
                geo_response.raise_for_status()
                data = geo_response.json()
            result.exit_ip = exit_ip
            if data.get("success", True):
                result.country = str(data.get("country_code") or data.get("country") or "")
                connection = data.get("connection") or {}
                asn = connection.get("asn")
                org = connection.get("org") or connection.get("isp")
                if asn:
                    result.asn = f"AS{asn}" + (f" {org}" if org else "")
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return

    async def validate(
        self,
        nodes: list[ProxyNode],
        *,
        concurrency: int = 16,
        geo_limit: int = 0,
    ) -> list[ValidationResult]:
        if not nodes:
            return []
        controller_port = _free_port()
        mixed_port = _free_port()
        with tempfile.TemporaryDirectory(prefix="squad-vpn-") as tmp:
            directory = Path(tmp)
            process, converted = self._start(
                nodes, directory, controller_port, mixed_port
            )
            base_url = f"http://127.0.0.1:{controller_port}"
            try:
                await self._wait_ready(process, base_url)
                semaphore = asyncio.Semaphore(max(1, concurrency))
                async with httpx.AsyncClient(base_url=base_url) as client:
                    results = await asyncio.gather(
                        *(self._probe_one(client, item, semaphore) for item in converted)
                    )
                    if geo_limit > 0:
                        result_by_fp = {result.fingerprint: result for result in results}
                        item_by_fp = {item.fingerprint: item for item in converted}
                        alive = sorted(
                            (r for r in results if r.alive),
                            key=lambda r: r.latency_ms or 999999,
                        )[:geo_limit]
                        for result in alive:
                            item = item_by_fp[result.fingerprint]
                            await self._enrich_geo(client, mixed_port, item, result)
                return results
            finally:
                self._stop(process)
