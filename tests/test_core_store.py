"""Layer 1: SessionStore — id allocation, persistence round-trips, error surfaces."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from profiler_mcp.core.store import SessionStore


@pytest.fixture
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(tmp_path / "results", "vtune")


def _register(store: SessionStore, rid: str, rdir: Path, label: str = ""):
    rdir.mkdir(parents=True, exist_ok=True)
    return store.register(
        rid, rdir, analysis="hotspots", mode="mock", target="./hotspots --seconds 0.3", label=label
    )


def test_id_allocation_sequence(store: SessionStore) -> None:
    rid0, rdir0 = store.new_result_dir("hs")
    assert rid0 == "hs-0000"
    assert rdir0 == store.base_dir / "hs-0000"
    _register(store, rid0, rdir0)

    # new_result_dir claims the id atomically by creating its directory.
    assert rdir0.is_dir()

    rid1, rdir1 = store.new_result_dir("hs")
    assert rid1 == "hs-0001"
    assert rdir1.is_dir()

    # A bare directory on disk (never registered) also blocks its id.
    (store.base_dir / "hs-0002").mkdir(parents=True)
    rid3, _ = store.new_result_dir("hs")
    assert rid3 == "hs-0003"

    # Other analysis codes have their own sequence.
    assert store.new_result_dir("tbp")[0] == "tbp-0000"


def test_register_get_list_round_trip(store: SessionStore) -> None:
    rid, rdir = store.new_result_dir("hs")
    _register(store, rid, rdir)

    entry = store.get(rid)
    assert entry.result_id == rid
    assert entry.result_dir == str(rdir)
    assert entry.server == "vtune"
    assert entry.analysis == "hotspots"
    assert entry.mode == "mock"
    assert entry.target == "./hotspots --seconds 0.3"
    assert entry.created_at  # ISO timestamp, non-empty

    infos = store.list()
    assert [i["result_id"] for i in infos] == [rid]
    assert infos[0]["result_dir"] == str(rdir)
    assert infos[0]["mode"] == "mock"

    # A second store over the same dir sees the persisted registry.
    again = SessionStore(store.base_dir, "vtune")
    assert [i["result_id"] for i in again.list()] == [rid]


@pytest.mark.parametrize("bad_id", ["", "HS-0000", "hs 0000", "hs/../../etc", "-hs", "hs!"])
def test_invalid_result_id_rejected(store: SessionStore, bad_id: str) -> None:
    with pytest.raises(ToolError, match="Invalid result_id"):
        store.get(bad_id)


def test_unknown_id_error_lists_known_ids(store: SessionStore) -> None:
    rid, rdir = store.new_result_dir("hs")
    _register(store, rid, rdir)
    with pytest.raises(ToolError) as exc:
        store.get("hs-0042")
    message = str(exc.value)
    assert "Unknown result_id" in message
    assert "hs-0000" in message  # known ids are listed for recovery


def test_unknown_id_error_on_empty_store(store: SessionStore) -> None:
    with pytest.raises(ToolError, match="none stored yet"):
        store.get("hs-0000")


def test_registered_but_missing_dir_is_actionable(store: SessionStore) -> None:
    rid, rdir = store.new_result_dir("hs")
    _register(store, rid, rdir)
    rdir.rmdir()
    with pytest.raises(ToolError, match="directory is gone"):
        store.get(rid)


def test_corrupt_registry_json_tolerated(store: SessionStore, tmp_path: Path) -> None:
    registry = store.base_dir / "registry.json"
    registry.write_text("{ this is not json !!!")
    assert store.list() == []

    # The store recovers: registering afterwards works and persists.
    rid, rdir = store.new_result_dir("hs")
    _register(store, rid, rdir)
    assert [i["result_id"] for i in store.list()] == [rid]


def test_incompatible_registry_entries_skipped(store: SessionStore) -> None:
    registry = store.base_dir / "registry.json"
    registry.write_text(json.dumps({"hs-0000": {"written_by": "a future version"}}))
    assert store.list() == []
    with pytest.raises(ToolError, match="Unknown result_id"):
        store.get("hs-0000")


def test_label_survives_round_trip(store: SessionStore) -> None:
    rid, rdir = store.new_result_dir("hs")
    _register(store, rid, rdir, label="baseline")
    assert store.get(rid).label == "baseline"
    info = store.list()[0]
    assert info["label"] == "baseline"

    # Empty labels are omitted from the wire shape (NotRequired field).
    rid2, rdir2 = store.new_result_dir("hs")
    _register(store, rid2, rdir2)
    infos = {i["result_id"]: i for i in store.list()}
    assert "label" not in infos[rid2]
