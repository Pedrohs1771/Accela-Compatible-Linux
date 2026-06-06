import json
import logging
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)


class RyuuClientError(RuntimeError):
    pass


class RyuuClient:
    BASE_URL = "https://generator.ryuu.lol"

    def __init__(self, auth_key: Optional[str] = None):
        self.auth_key = (auth_key or load_ryuu_auth_key() or "").strip()

    def _headers(self) -> dict[str, str]:
        if not self.auth_key:
            raise RyuuClientError("Configure sua auth_key do Ryuu antes de baixar fixes.")
        return {
            "X-Auth-Key": self.auth_key,
            "User-Agent": "LumaTools",
        }

    def _get(self, path: str, params: Optional[dict[str, str]] = None, *, stream: bool = False):
        url = f"{self.BASE_URL}{path}"
        try:
            response = requests.get(
                url,
                params=params or {},
                headers=self._headers(),
                timeout=60,
                stream=stream,
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            raise RyuuClientError(str(exc)) from exc

    def download(
        self,
        appid: str,
        output_dir: Path,
        *,
        file_type: str = "",
        branch: str = "public",
    ) -> Path:
        appid = str(appid).strip()
        if not appid.isdigit():
            raise RyuuClientError("AppID inválido.")

        params: dict[str, str] = {}
        if file_type:
            params["file_type"] = file_type
        if branch and branch != "public":
            params["branch"] = branch

        extension = {"lua": "lua", "manifest": "zip"}.get(file_type, "zip")
        suffix = f"-{file_type}" if file_type else "-full"
        branch_suffix = "" if branch == "public" else f"-{branch}"
        output_dir = Path(output_dir).expanduser()
        app_dir = output_dir if output_dir.name == appid else output_dir / appid
        target = app_dir / f"ryuu-{appid}{branch_suffix}{suffix}.{extension}"
        target.parent.mkdir(parents=True, exist_ok=True)

        response = self._get(f"/api/download/{appid}", params=params, stream=True)
        with open(target, "wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    handle.write(chunk)

        if target.stat().st_size <= 0:
            target.unlink(missing_ok=True)
            raise RyuuClientError("Ryuu retornou um arquivo vazio.")

        write_ryuu_info(target.parent, appid, branch, file_type or "zip", target.name)
        return target

    def request_game(self, appid: str) -> str:
        response = self._get("/request", params={"appid": str(appid)})
        return response.text.strip() or "Pedido enviado."

    def request_update(self, appid: str, branch: str = "public") -> str:
        response = self._get(
            "/requestupdate",
            params={"appid": str(appid), "branch": branch or "public"},
        )
        return response.text.strip() or "Pedido de update enviado."

    def request_branch(self, appid: str, branch: str) -> str:
        if not branch:
            raise RyuuClientError("Informe a branch.")
        response = self._get("/requestbranch", params={"appid": str(appid), "branch": branch})
        return response.text.strip() or "Pedido de branch enviado."

    def test_key(self) -> bool:
        # Passive validation only. Do not call request/update endpoints just to
        # test credentials, because those endpoints can create server-side work.
        if not self.auth_key:
            raise RyuuClientError("Configure sua auth_key do Ryuu primeiro.")
        if len(self.auth_key) < 12:
            raise RyuuClientError("Auth key Ryuu curta demais.")
        if any(ch.isspace() for ch in self.auth_key):
            raise RyuuClientError("Auth key Ryuu não pode conter espaços.")
        return True


def secrets_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "LumaTools" / "secrets.json"


def mask_key(value: str) -> str:
    value = (value or "").strip()
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * max(4, len(value) - 8)}{value[-4:]}"


def load_ryuu_auth_key() -> str:
    path = secrets_path()
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data.get("ryuu_auth_key", "")).strip()
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Falha ao ler secrets do LumaTools: %s", exc)
        return ""


def save_ryuu_auth_key(auth_key: str) -> None:
    path = secrets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    data["ryuu_auth_key"] = auth_key.strip()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)


def write_ryuu_info(directory: Path, appid: str, branch: str, file_type: str, filename: str) -> None:
    info = directory / "LUMA_RYUU_FIX_INFO.txt"
    info.write_text(
        "\n".join(
            [
                "Fonte: Ryuu Fixes",
                f"AppID: {appid}",
                f"Branch: {branch or 'public'}",
                f"Tipo: {file_type}",
                f"Arquivo: {filename}",
                "Status: baixado; aplicação manual/confirmada pelo usuário",
                "",
            ]
        ),
        encoding="utf-8",
    )
