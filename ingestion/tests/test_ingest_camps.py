import os

from lib.upsert import apply_upsert_in_memory, rows_from_geodataframe
from scripts import ingest_camps

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "sample_camps.geojson")


def _stub_upsert(captured):
    def fake_upsert_geodataframe(engine, gdf, table, layer, source, id_field, extra_fields=None):
        rows = rows_from_geodataframe(gdf, layer, source, id_field, extra_fields)
        store = {}
        apply_upsert_in_memory(store, rows)
        captured["store"] = store
        captured["table"] = table
        captured["layer"] = layer
        return len(rows)

    return fake_upsert_geodataframe


def test_ingest_camps_assigns_feature_ids_from_fixture(monkeypatch):
    captured = {}
    monkeypatch.setattr(ingest_camps, "upsert_geodataframe", _stub_upsert(captured))
    monkeypatch.setattr(ingest_camps, "get_engine", lambda: None)

    exit_code = ingest_camps.main(
        ["--input", FIXTURE_PATH, "--source", "fixture", "--id-field", "camp_id"]
    )

    assert exit_code == 0
    assert captured["table"] == "camps"
    assert captured["layer"] == "camp"

    store = captured["store"]
    assert set(store.keys()) == {
        "camp:fixture:camp-a",
        "camp:fixture:camp-b",
        "camp:fixture:camp-c",
    }
    for row in store.values():
        assert row["source"] == "fixture"


def test_ingest_camps_falls_back_to_row_index_without_id_field(monkeypatch):
    captured = {}
    monkeypatch.setattr(ingest_camps, "upsert_geodataframe", _stub_upsert(captured))
    monkeypatch.setattr(ingest_camps, "get_engine", lambda: None)

    exit_code = ingest_camps.main(["--input", FIXTURE_PATH])

    assert exit_code == 0
    # Default --source is "manual"; with no --id-field, source_id falls back
    # to the row index (0, 1, 2 for the three fixture features).
    assert set(captured["store"].keys()) == {
        "camp:manual:0",
        "camp:manual:1",
        "camp:manual:2",
    }
