"""Registry of stored profiling results.

Results live on disk under the server's results dir; the registry is a JSON
file mapping result_id -> metadata. IDs are short, human-readable, and stable
(`hs-0001` style) per the tool-design guidance to prefer natural identifiers
over UUIDs.
"""

from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from mcp.server.fastmcp.exceptions import ToolError

from .models import Mode, ResultInfo

try:
    import fcntl  # POSIX only; on Windows the lock degrades to a no-op
except ImportError:  # pragma: no cover - platform dependent
    fcntl = None  # type: ignore[assignment]

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


@dataclass
class StoredResult:
    result_id: str
    result_dir: str
    server: str
    analysis: str
    mode: Mode
    created_at: str
    target: str
    label: str = ""

    def to_info(self) -> ResultInfo:
        info: ResultInfo = {
            "result_id": self.result_id,
            "result_dir": self.result_dir,
            "server": self.server,
            "analysis": self.analysis,
            "mode": self.mode,
            "created_at": self.created_at,
            "target": self.target,
        }
        if self.label:
            info["label"] = self.label
        return info


class SessionStore:
    def __init__(self, base_dir: Path, server: str) -> None:
        self.base_dir = base_dir
        self.server = server
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._registry_path = self.base_dir / "registry.json"
        self._lock_path = self.base_dir / ".registry.lock"

    # -- persistence ---------------------------------------------------------

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        """Serialize registry read-modify-write across processes sharing the dir."""
        if fcntl is None:
            yield
            return
        with open(self._lock_path, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _load(self) -> dict[str, StoredResult]:
        if not self._registry_path.is_file():
            return {}
        try:
            raw = json.loads(self._registry_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        out: dict[str, StoredResult] = {}
        for rid, meta in raw.items():
            try:
                out[rid] = StoredResult(**meta)
            except TypeError:
                continue  # skip entries written by an incompatible version
        return out

    def _save(self, entries: dict[str, StoredResult]) -> None:
        tmp = self._registry_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({k: asdict(v) for k, v in entries.items()}, indent=1))
        tmp.replace(self._registry_path)

    # -- API -----------------------------------------------------------------

    def new_result_dir(self, analysis_code: str) -> tuple[str, Path]:
        """Atomically claim the next `<code>-NNNN` id by creating its result dir.

        The directory is created with exist_ok=False, so two concurrent callers
        (even in separate processes) can never be handed the same id — the loser
        of the mkdir race simply takes the next number.
        """
        with self._locked():
            entries = self._load()
            n = 0
            while True:
                rid = f"{analysis_code}-{n:04d}"
                rdir = self.base_dir / rid
                if rid not in entries:
                    try:
                        rdir.mkdir(parents=True, exist_ok=False)
                    except FileExistsError:
                        n += 1
                        continue
                    return rid, rdir
                n += 1

    def register(
        self,
        result_id: str,
        result_dir: Path,
        *,
        analysis: str,
        mode: Mode,
        target: str,
        label: str = "",
    ) -> StoredResult:
        entry = StoredResult(
            result_id=result_id,
            result_dir=str(result_dir),
            server=self.server,
            analysis=analysis,
            mode=mode,
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            target=target,
            label=label,
        )
        with self._locked():
            entries = self._load()
            entries[result_id] = entry
            self._save(entries)
        return entry

    def get(self, result_id: str) -> StoredResult:
        if not _ID_RE.match(result_id or ""):
            raise ToolError(f"Invalid result_id {result_id!r}.")
        entries = self._load()
        if result_id not in entries:
            known = ", ".join(sorted(entries)) or "none stored yet"
            raise ToolError(
                f"Unknown result_id {result_id!r}. Known results: {known}. "
                f"Use the list-results tool, or collect first."
            )
        entry = entries[result_id]
        if not Path(entry.result_dir).exists():
            raise ToolError(
                f"Result {result_id} is registered but its directory is gone "
                f"({entry.result_dir}). Re-run the collection."
            )
        return entry

    def list(self) -> list[ResultInfo]:
        entries = self._load()
        return [e.to_info() for e in sorted(entries.values(), key=lambda e: e.created_at)]
