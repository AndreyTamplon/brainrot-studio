import pytest

from brainrot import assets, config, media, store


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    for directory in ("jobs", "media", "cache"):
        (tmp_path / directory).mkdir()
    for module in (assets, config, media, store):
        monkeypatch.setattr(module, "DATA", tmp_path)
    monkeypatch.setattr(assets, "CATALOG", tmp_path / "catalog.json")
    store.init()
    return tmp_path
