import pytest

from stock_daily_research.api_server import DEFAULT_DB_PATH, normalize_research_state_payload


def test_normalize_research_state_payload_accepts_api_wrapper() -> None:
    payload = normalize_research_state_payload({
        "research_state": {
            "NVDA": {"thesis_state": "active"},
            "MSFT": {"tag": "core"},
        }
    })

    assert payload["version"] == 1
    assert payload["tickers"]["NVDA"]["thesis_state"] == "active"
    assert payload["tickers"]["MSFT"]["tag"] == "core"


def test_normalize_research_state_payload_accepts_export_shape() -> None:
    original = {"version": 1, "tickers": {"NVDA": {"tag": "ai"}}}

    assert normalize_research_state_payload(original) is original


def test_normalize_research_state_payload_rejects_non_object() -> None:
    with pytest.raises(ValueError, match="research_state must be a JSON object"):
        normalize_research_state_payload({"research_state": []})


def test_api_server_uses_project_default_db_path() -> None:
    assert DEFAULT_DB_PATH.as_posix() == "data/stock_daily.sqlite3"
