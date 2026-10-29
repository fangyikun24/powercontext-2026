"""Configuration for the SDD context module.

Everything is driven by environment variables so that the module can be pointed at a
different project, database or model provider without code changes. A ``.env`` file in
the module directory (or the current working directory) is read first; real environment
variables win over it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader: ``KEY=VALUE`` lines, ``#`` comments, optional quotes."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_path(name: str, default: Path) -> Path:
    raw = _env(name)
    return Path(raw).expanduser().resolve() if raw else default


@dataclass(frozen=True)
class Settings:
    """Resolved runtime configuration."""

    home: Path
    project_dir: Path

    materials_backend: str
    materials_seekdb_path: Path
    oceanbase_url: str | None

    state_backend: str
    state_seekdb_path: Path
    state_sqlite_url: str

    llm_provider: str
    minimax_api_key: str
    minimax_base_url: str
    minimax_model: str
    minimax_reasoning_effort: str
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    request_timeout: float

    artifacts_dir: Path = field(default_factory=Path)

    @property
    def materials_db_label(self) -> str:
        if self.materials_backend == "oceanbase":
            return "OceanBase"
        return "seekdb"

    @classmethod
    def from_env(cls, project_dir: Path | None = None) -> Settings:
        _load_dotenv(MODULE_ROOT / ".env")
        _load_dotenv(Path.cwd() / ".env")

        home = _env_path("SDDCTX_HOME", MODULE_ROOT / "state")
        resolved_project = (
            project_dir.resolve()
            if project_dir is not None
            else _env_path("SDDCTX_PROJECT", MODULE_ROOT / "sample-project")
        )

        materials_backend = _env("SDDCTX_MATERIALS_BACKEND", "seekdb").lower()
        state_backend = _env("SDDCTX_STATE_BACKEND", "seekdb").lower()
        oceanbase_url = _env("SDDCTX_OCEANBASE_URL") or None

        return cls(
            home=home,
            project_dir=resolved_project,
            materials_backend=materials_backend,
            materials_seekdb_path=_env_path("SDDCTX_MATERIALS_SEEKDB_PATH", home / "materials"),
            oceanbase_url=oceanbase_url,
            state_backend=state_backend,
            state_seekdb_path=_env_path("SDDCTX_STATE_SEEKDB_PATH", home / "state-seekdb"),
            state_sqlite_url=_env(
                "SDDCTX_STATE_SQLITE_URL", f"sqlite+aiosqlite:///{(home / 'powercontext.db').as_posix()}"
            ),
            llm_provider=_env("SDDCTX_LLM_PROVIDER", "minimax").lower(),
            minimax_api_key=_env("MINIMAX_API_KEY"),
            minimax_base_url=_env("MINIMAX_BASE_URL", "https://api.minimaxi.com"),
            minimax_model=_env("MINIMAX_MODEL", "MiniMax-M3"),
            # MiniMax-M3 is an adaptive-thinking model: it cannot run with thinking
            # disabled, and with a large prompt it will otherwise spend the whole token
            # budget reasoning and return no text. "low" keeps enough room for the answer.
            minimax_reasoning_effort=_env("MINIMAX_REASONING_EFFORT", "low").lower(),
            deepseek_api_key=_env("DEEPSEEK_API_KEY"),
            deepseek_base_url=_env("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            deepseek_model=_env("DEEPSEEK_MODEL", "deepseek-chat"),
            request_timeout=float(_env("SDDCTX_REQUEST_TIMEOUT", "600")),
            artifacts_dir=_env_path("SDDCTX_ARTIFACTS", MODULE_ROOT / "artifacts"),
        )

    def validate(self, *, require_llm: bool = False) -> list[str]:
        """Return a list of human-readable configuration problems."""
        problems: list[str] = []
        if self.materials_backend not in {"seekdb", "oceanbase"}:
            problems.append(f"SDDCTX_MATERIALS_BACKEND must be seekdb|oceanbase, got {self.materials_backend!r}")
        if self.materials_backend == "oceanbase" and not self.oceanbase_url:
            problems.append("SDDCTX_OCEANBASE_URL is required when SDDCTX_MATERIALS_BACKEND=oceanbase")
        if self.state_backend not in {"seekdb", "sqlite"}:
            problems.append(f"SDDCTX_STATE_BACKEND must be seekdb|sqlite, got {self.state_backend!r}")
        if not self.project_dir.is_dir():
            problems.append(f"project directory not found: {self.project_dir}")
        if require_llm:
            problems.extend(self.llm_problems())
        return problems

    def llm_problems(self) -> list[str]:
        if self.llm_provider == "minimax" and not self.minimax_api_key:
            return ["MINIMAX_API_KEY is not set"]
        if self.llm_provider == "deepseek" and not self.deepseek_api_key:
            return ["DEEPSEEK_API_KEY is not set"]
        if self.llm_provider not in {"minimax", "deepseek"}:
            return [f"SDDCTX_LLM_PROVIDER must be minimax|deepseek, got {self.llm_provider!r}"]
        return []
