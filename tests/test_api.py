from fastapi.testclient import TestClient

from app.llm_client import LlmContext
from app.main import create_app


class FakeLlmClient:
    def __init__(self):
        self.contexts = []

    def generate_reply(self, context: LlmContext) -> str:
        self.contexts.append(context)
        return f"LLM 응답: {context.user_action}"


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


def test_chat_turn_uses_injected_llm_client_for_safe_free_input(tmp_path):
    fake_llm = FakeLlmClient()
    app = create_app(db_path=str(tmp_path / "test.sqlite3"), llm_client=fake_llm)
    client = TestClient(app)
    session_id = client.post(
        "/api/chat/turn", json={"plot_id": "p_luminote_001_first_light"}
    ).json()["session"]["id"]

    response = client.post(
        "/api/chat/turn",
        json={"session_id": session_id, "free_input": "오늘 무대가 긴장돼"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "LLM 응답: 오늘 무대가 긴장돼"
    assert body["llm_mode"] == "llm"
    assert "오늘 무대가 긴장돼" in body["logbook"]["entries"][0]["summary"]
    assert fake_llm.contexts[0].plot_title == "리허설의 첫 불빛"
    assert fake_llm.contexts[0].user_action == "오늘 무대가 긴장돼"


def test_chat_turn_falls_back_when_llm_client_fails(tmp_path):
    class BrokenLlmClient:
        def generate_reply(self, context: LlmContext) -> str:
            raise RuntimeError("llm unavailable")

    app = create_app(db_path=str(tmp_path / "test.sqlite3"), llm_client=BrokenLlmClient())
    client = TestClient(app)
    session_id = client.post(
        "/api/chat/turn", json={"plot_id": "p_luminote_001_first_light"}
    ).json()["session"]["id"]

    response = client.post(
        "/api/chat/turn",
        json={"session_id": session_id, "free_input": "응원할게"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "직접 말하기가 장면에 반영되었어요." in body["message"]
    assert body["llm_mode"] == "scripted_fallback"


def test_admin_validation_rejects_real_ip(tmp_path):
    client = make_client(tmp_path)

    response = client.post(
        "/api/admin/plot-cards/validate",
        json={"title": "BTS 리허설", "one_line_hook": "실제 그룹을 떠올리게 하는 카드"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "실제 IP" in " ".join(response.json()["errors"])


def test_cors_allows_localhost_and_loopback_frontend_origins(tmp_path):
    client = make_client(tmp_path)

    for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
        response = client.options(
            "/api/chat/turn",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
