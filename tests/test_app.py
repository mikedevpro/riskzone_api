from fastapi.testclient import TestClient

from app import RATE, app


client = TestClient(app)


def setup_function():
    RATE.clear()


def test_submit_score_accepts_player_name_alias():
    response = client.post(
        "/score?limit=1",
        json={
            "playerName": "AliasUser",
            "score": 50000,
            "level": 999,
            "character": "Runner",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload
    assert payload[0]["name"] == "AliasUser"
    assert payload[0]["playerName"] == "AliasUser"


def test_submit_score_rejects_score_above_expected_range():
    response = client.post(
        "/score",
        json={
            "name": "TooHigh",
            "score": 50001,
            "level": 1,
            "character": "Runner",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Score exceeds expected range"
