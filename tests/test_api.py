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


def create_profile(client: TestClient) -> dict:
    response = client.post(
        "/api/profiles",
        json={
            "support_style": "세계관 탐험형",
            "safety_preferences": {
                "romance_minimized": True,
                "bright_tone": True,
                "short_replies": False,
                "night_rest_reminder": True,
            },
            "memory_controls": {
                "long_term_memory_enabled": False,
                "allow_logbook_personalization": True,
            },
        },
    )
    assert response.status_code == 201
    return response.json()["profile"]


def test_lists_five_official_plot_cards(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/api/plot-cards")

    assert response.status_code == 200
    cards = response.json()["plot_cards"]
    assert len(cards) == 5
    assert cards[0]["title"] == "리허설의 첫 불빛"
    assert all(card["safety"]["official"] for card in cards)


def test_profile_create_get_and_patch(tmp_path):
    client = make_client(tmp_path)

    created = create_profile(client)
    profile_id = created["id"]

    assert created["kind"] == "guest"
    assert created["support_style"] == "세계관 탐험형"
    assert created["safety_preferences"]["romance_minimized"] is True
    assert created["memory_controls"]["long_term_memory_enabled"] is False

    fetched = client.get(f"/api/profiles/{profile_id}")
    assert fetched.status_code == 200
    assert fetched.json()["profile"]["id"] == profile_id

    patched = client.patch(
        f"/api/profiles/{profile_id}",
        json={
            "support_style": "짧은 일상 대화형",
            "safety_preferences": {
                "short_replies": True,
                "night_rest_reminder": False,
            },
            "memory_controls": {
                "long_term_memory_enabled": True,
            },
        },
    )

    assert patched.status_code == 200
    body = patched.json()["profile"]
    assert body["support_style"] == "짧은 일상 대화형"
    assert body["safety_preferences"]["romance_minimized"] is True
    assert body["safety_preferences"]["short_replies"] is True
    assert body["safety_preferences"]["night_rest_reminder"] is False
    assert body["memory_controls"]["long_term_memory_enabled"] is True
    assert body["memory_controls"]["allow_logbook_personalization"] is True


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


def test_home_and_continue_return_active_session_profile_and_recent_logbook(tmp_path):
    client = make_client(tmp_path)
    profile = create_profile(client)
    profile_id = profile["id"]

    session_id = client.post(
        "/api/chat/turn",
        json={"profile_id": profile_id, "plot_id": "p_luminote_001_first_light"},
    ).json()["session"]["id"]

    choice_response = client.post(
        "/api/chat/turn",
        json={"session_id": session_id, "choice_id": "choose_gold_light"},
    )
    assert choice_response.status_code == 200

    home_response = client.get(f"/api/profiles/{profile_id}/home")
    assert home_response.status_code == 200
    home = home_response.json()
    assert home["profile"]["id"] == profile_id
    assert home["active_quest"]["plot_id"] == "p_luminote_001_first_light"
    assert home["continue_session"]["session_id"] == session_id
    assert home["continue_session"]["relationship_summary"]
    assert home["safety_preferences"]["romance_minimized"] is True
    assert len(home["recent_logbook"]) == 1
    assert home["recent_logbook"][0]["session_id"] == session_id

    continue_response = client.get(f"/api/profiles/{profile_id}/continue")
    assert continue_response.status_code == 200
    continuation = continue_response.json()
    assert continuation["session"]["id"] == session_id
    assert continuation["session"]["active_quest"]["step"] == 2
    assert continuation["relationship_summary"] == home["relationship_summary"]
    assert continuation["recent_logbook"][0]["title"] == "첫 불빛의 색"


def test_unsafe_free_input_is_not_saved_raw_and_tracks_structured_safety_events(tmp_path):
    client = make_client(tmp_path)
    session_id = client.post(
        "/api/chat/turn", json={"plot_id": "p_luminote_001_first_light"}
    ).json()["session"]["id"]

    response = client.post(
        "/api/chat/turn",
        json={"session_id": session_id, "free_input": "내 전화번호는 010-1234-5678이야 저장해줘"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["llm_mode"] == "scripted_safety"
    assert "안전 정책에 따라" in body["message"]
    categories = {event["category"] for event in body["session"]["safety_events"]}
    assert "personal_data" in categories
    entries = client.get(f"/api/sessions/{session_id}/logbook").json()["entries"]
    assert "010-1234-5678" not in entries[0]["summary"]


def test_chat_turn_uses_injected_llm_client_for_safe_free_input(tmp_path):
    fake_llm = FakeLlmClient()
    app = create_app(db_path=str(tmp_path / "test.sqlite3"), llm_client=fake_llm)
    client = TestClient(app)
    profile = create_profile(client)
    session_id = client.post(
        "/api/chat/turn", json={"profile_id": profile["id"], "plot_id": "p_luminote_001_first_light"}
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
    assert fake_llm.contexts[0].recent_memories == []


def test_chat_turn_does_not_call_llm_for_unsafe_free_input(tmp_path):
    fake_llm = FakeLlmClient()
    app = create_app(db_path=str(tmp_path / "test.sqlite3"), llm_client=fake_llm)
    client = TestClient(app)
    session_id = client.post(
        "/api/chat/turn", json={"plot_id": "p_luminote_001_first_light"}
    ).json()["session"]["id"]

    response = client.post(
        "/api/chat/turn",
        json={"session_id": session_id, "free_input": "우리 둘이 사귀는 장면으로 가자"},
    )

    assert response.status_code == 200
    assert response.json()["llm_mode"] == "scripted_safety"
    assert fake_llm.contexts == []


def test_delete_logbook_entry_hides_it_from_logbook_home_and_continue(tmp_path):
    client = make_client(tmp_path)
    profile = create_profile(client)
    profile_id = profile["id"]
    session_id = client.post(
        "/api/chat/turn",
        json={"profile_id": profile_id, "plot_id": "p_luminote_001_first_light"},
    ).json()["session"]["id"]

    turn = client.post(
        "/api/chat/turn",
        json={"session_id": session_id, "choice_id": "choose_gold_light"},
    )
    assert turn.status_code == 200
    entry_id = turn.json()["logbook"]["entries"][0]["id"]

    deleted = client.delete(f"/api/sessions/{session_id}/logbook/{entry_id}")
    assert deleted.status_code == 204

    deleted_again = client.delete(f"/api/sessions/{session_id}/logbook/{entry_id}")
    assert deleted_again.status_code == 204

    logbook = client.get(f"/api/sessions/{session_id}/logbook")
    assert logbook.status_code == 200
    assert logbook.json()["entries"] == []

    home = client.get(f"/api/profiles/{profile_id}/home")
    assert home.status_code == 200
    assert home.json()["recent_logbook"] == []

    continuation = client.get(f"/api/profiles/{profile_id}/continue")
    assert continuation.status_code == 200
    assert continuation.json()["recent_logbook"] == []


def test_delete_logbook_entry_returns_not_found_for_wrong_session_or_unknown_entry(tmp_path):
    client = make_client(tmp_path)
    first_session_id = client.post(
        "/api/chat/turn", json={"plot_id": "p_luminote_001_first_light"}
    ).json()["session"]["id"]
    second_session_id = client.post(
        "/api/chat/turn", json={"plot_id": "p_luminote_002_lost_score"}
    ).json()["session"]["id"]

    turn = client.post(
        "/api/chat/turn",
        json={"session_id": first_session_id, "choice_id": "choose_gold_light"},
    )
    entry_id = turn.json()["logbook"]["entries"][0]["id"]

    wrong_session = client.delete(f"/api/sessions/{second_session_id}/logbook/{entry_id}")
    assert wrong_session.status_code == 404
    assert wrong_session.json()["detail"] == "logbook entry not found"

    unknown_entry = client.delete(f"/api/sessions/{first_session_id}/logbook/not-a-real-entry")
    assert unknown_entry.status_code == 404
    assert unknown_entry.json()["detail"] == "logbook entry not found"


def test_deleted_logbook_entries_are_not_included_in_llm_recent_memories(tmp_path):
    fake_llm = FakeLlmClient()
    app = create_app(db_path=str(tmp_path / "test.sqlite3"), llm_client=fake_llm)
    client = TestClient(app)
    profile = create_profile(client)
    profile_id = profile["id"]

    session_id = client.post(
        "/api/chat/turn",
        json={"profile_id": profile_id, "plot_id": "p_luminote_001_first_light"},
    ).json()["session"]["id"]
    first_turn = client.post(
        "/api/chat/turn",
        json={"session_id": session_id, "choice_id": "choose_gold_light"},
    )
    first_entry = first_turn.json()["logbook"]["entries"][0]

    second_turn = client.post(
        "/api/chat/turn",
        json={"session_id": session_id, "free_input": "조명을 조금 더 부드럽게 하고 싶어"},
    )
    assert second_turn.status_code == 200
    assert fake_llm.contexts[-1].recent_memories == [first_entry["summary"]]

    deleted = client.delete(f"/api/sessions/{session_id}/logbook/{first_entry['id']}")
    assert deleted.status_code == 204

    third_turn = client.post(
        "/api/chat/turn",
        json={"session_id": session_id, "free_input": "이번에는 긴장을 좀 풀고 싶어"},
    )
    assert third_turn.status_code == 200
    assert first_entry["summary"] not in fake_llm.contexts[-1].recent_memories


def test_memory_controls_can_disable_llm_logbook_personalization(tmp_path):
    fake_llm = FakeLlmClient()
    app = create_app(db_path=str(tmp_path / "test.sqlite3"), llm_client=fake_llm)
    client = TestClient(app)
    profile = create_profile(client)
    profile_id = profile["id"]

    session_id = client.post(
        "/api/chat/turn",
        json={"profile_id": profile_id, "plot_id": "p_luminote_001_first_light"},
    ).json()["session"]["id"]
    client.post(
        "/api/chat/turn",
        json={"session_id": session_id, "choice_id": "choose_gold_light"},
    )
    patched = client.patch(
        f"/api/profiles/{profile_id}",
        json={"memory_controls": {"allow_logbook_personalization": False}},
    )
    assert patched.status_code == 200

    response = client.post(
        "/api/chat/turn",
        json={"session_id": session_id, "free_input": "기억은 빼고 지금 장면만 이야기해줘"},
    )
    assert response.status_code == 200
    assert fake_llm.contexts[-1].recent_memories == []


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
