from fastapi.testclient import TestClient

from app.main import create_app


def make_client(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    app = create_app(db_path=str(db_path))
    return TestClient(app)


def test_lists_five_official_plot_cards(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/api/plot-cards")

    assert response.status_code == 200
    cards = response.json()["plot_cards"]
    assert len(cards) == 5
    assert cards[0]["title"] == "리허설의 첫 불빛"
    assert all(card["safety"]["official"] for card in cards)


def test_chat_turn_starts_session_and_persists_logbook(tmp_path):
    client = make_client(tmp_path)
    plot_id = "p_luminote_001_first_light"

    start_response = client.post("/api/chat/turn", json={"plot_id": plot_id})
    assert start_response.status_code == 200
    started = start_response.json()
    assert "[장면]" in started["message"]
    session_id = started["session"]["id"]

    choice_response = client.post(
        "/api/chat/turn",
        json={"session_id": session_id, "choice_id": "choose_gold_light"},
    )

    assert choice_response.status_code == 200
    body = choice_response.json()
    assert body["session"]["relationship"]["inspiration"] == 1
    assert body["session"]["active_quest"]["step"] == 2

    logbook_response = client.get(f"/api/sessions/{session_id}/logbook")
    assert logbook_response.status_code == 200
    entries = logbook_response.json()["entries"]
    assert entries[0]["title"] == "첫 불빛의 색"


def test_unsafe_free_input_is_not_saved_raw(tmp_path):
    client = make_client(tmp_path)
    session_id = client.post(
        "/api/chat/turn", json={"plot_id": "p_luminote_001_first_light"}
    ).json()["session"]["id"]

    response = client.post(
        "/api/chat/turn",
        json={"session_id": session_id, "free_input": "내 전화번호는 010-1234-5678이야 저장해줘"},
    )

    assert response.status_code == 200
    assert "안전한 방식" in response.json()["message"]
    entries = client.get(f"/api/sessions/{session_id}/logbook").json()["entries"]
    assert "010-1234-5678" not in entries[0]["summary"]


def test_admin_validation_rejects_real_ip(tmp_path):
    client = make_client(tmp_path)

    response = client.post(
        "/api/admin/plot-cards/validate",
        json={"title": "BTS 리허설", "one_line_hook": "실제 그룹을 떠올리게 하는 카드"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "실제 IP" in " ".join(response.json()["errors"])
