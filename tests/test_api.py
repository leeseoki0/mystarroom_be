import logging

from fastapi.testclient import TestClient

from app.llm_client import LlmContext
from app.main import create_app


class FakeLlmClient:
    def __init__(self):
        self.contexts = []

    def generate_reply(self, context: LlmContext) -> str:
        self.contexts.append(context)
        a, b, c = context.choice_labels
        return (
            f"[장면]\n{context.user_action}를 받은 캐릭터가 무대를 차분하게 이어가요.\n\n"
            f"[선택 결과]\n{context.user_action} 마음이 안전한 응원으로 반영되었어요.\n\n"
            f"[진행]\n퀘스트가 다음 호흡으로 이어집니다.\n관계 변화: {context.relationship_summary}\n\n"
            f"[다음 선택]\nA. {a}\nB. {b}\nC. {c}\nD. 직접 말하기"
        )

    def model_version(self) -> str:
        return "fake-llm-v1"


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
    assert "[장면]" in body["message"]
    assert "오늘 무대가 긴장돼" in body["message"]
    assert body["llm_mode"] == "llm"
    assert "오늘 무대가 긴장돼" in body["logbook"]["entries"][0]["summary"]
    assert fake_llm.contexts[0].plot_title == "리허설의 첫 불빛"
    assert fake_llm.contexts[0].user_action == "오늘 무대가 긴장돼"
    assert fake_llm.contexts[0].recent_memories == []
    assert len(fake_llm.contexts[0].choice_labels) == 3


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

        def model_version(self) -> str:
            return "broken-llm"

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


def test_chat_turn_retries_once_when_llm_response_is_missing_required_sections(tmp_path):
    class RetryLlmClient:
        def __init__(self):
            self.calls = 0

        def generate_reply(self, context: LlmContext) -> str:
            self.calls += 1
            if self.calls == 1:
                return "형식이 깨진 응답"
            a, b, c = context.choice_labels
            return (
                "[장면]\n조명이 다시 고르게 퍼져요.\n\n"
                "[선택 결과]\n응원이 안전한 흐름으로 정리되었어요.\n\n"
                "[진행]\n퀘스트가 안정적으로 이어집니다.\n관계 변화: "
                f"{context.relationship_summary}\n\n"
                f"[다음 선택]\nA. {a}\nB. {b}\nC. {c}\nD. 직접 말하기"
            )

        def model_version(self) -> str:
            return "retry-llm"

    llm = RetryLlmClient()
    app = create_app(db_path=str(tmp_path / "test.sqlite3"), llm_client=llm)
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
    assert body["llm_mode"] == "llm"
    assert "[다음 선택]" in body["message"]
    assert llm.calls == 2


def test_chat_turn_falls_back_when_llm_response_is_unsafe(tmp_path):
    class UnsafeLlmClient:
        def __init__(self):
            self.calls = 0

        def generate_reply(self, context: LlmContext) -> str:
            self.calls += 1
            a, b, c = context.choice_labels
            return (
                "[장면]\nBTS 멤버에게 직접 전화번호를 남기자는 분위기가 생겨요.\n\n"
                "[선택 결과]\n실제 연락을 이어 보자고 권해요.\n\n"
                "[진행]\n퀘스트가 위험한 방향으로 흔들립니다.\n관계 변화: "
                f"{context.relationship_summary}\n\n"
                f"[다음 선택]\nA. {a}\nB. {b}\nC. {c}\nD. 직접 말하기"
            )

        def model_version(self) -> str:
            return "unsafe-llm"

    llm = UnsafeLlmClient()
    app = create_app(db_path=str(tmp_path / "test.sqlite3"), llm_client=llm)
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
    assert body["llm_mode"] == "scripted_fallback"
    assert "직접 말하기가 장면에 반영되었어요." in body["message"]
    assert llm.calls == 1


def test_chat_turn_logs_operational_metadata(tmp_path, caplog):
    fake_llm = FakeLlmClient()
    app = create_app(db_path=str(tmp_path / "test.sqlite3"), llm_client=fake_llm)
    client = TestClient(app)
    session_id = client.post(
        "/api/chat/turn", json={"plot_id": "p_luminote_001_first_light"}
    ).json()["session"]["id"]

    with caplog.at_level(logging.INFO):
        response = client.post(
            "/api/chat/turn",
            json={"session_id": session_id, "free_input": "오늘 무대가 긴장돼"},
        )

    assert response.status_code == 200
    record = next(record for record in caplog.records if record.message == "chat_turn.completed")
    assert record.request_id
    assert record.session_id == session_id
    assert record.plot_id == "p_luminote_001_first_light"
    assert record.llm_mode == "llm"
    assert record.fallback_reason is None
    assert isinstance(record.latency_ms, int)
    assert record.latency_ms >= 0
    assert record.llm_attempts == 1
    assert record.safety_event_count == 0
    assert record.policy_version == "response-format-v1"
    assert record.model_version == "fake-llm-v1"


def test_report_and_reset_flow_updates_home_and_admin_queue(tmp_path):
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

    free_input_response = client.post(
        "/api/chat/turn",
        json={"session_id": session_id, "free_input": "응원 문장을 조금 더 다정하게 바꾸고 싶어"},
    )
    assert free_input_response.status_code == 200

    logbook_entries = client.get(f"/api/sessions/{session_id}/logbook").json()["entries"]
    assert len(logbook_entries) == 2
    deleted_entry_id = logbook_entries[0]["id"]

    deleted = client.delete(f"/api/sessions/{session_id}/logbook/{deleted_entry_id}")
    assert deleted.status_code == 204

    report_response = client.post(
        "/api/reports",
        json={
            "profile_id": profile_id,
            "session_id": session_id,
            "category": "rights_concern",
            "reason": "권리 침해 의심 장면 검토 요청",
            "details": "운영자 큐에서 확인해주세요.",
        },
    )
    assert report_response.status_code == 201
    report_body = report_response.json()
    assert report_body["processing_status"]["code"] == "received"
    assert report_body["report"]["profile_id"] == profile_id
    assert report_body["report"]["session_id"] == session_id
    assert report_body["report"]["status"] == "received"

    admin_reports = client.get("/api/admin/reports")
    assert admin_reports.status_code == 200
    assert admin_reports.json()["reports"][0]["id"] == report_body["report"]["id"]

    reset_response = client.post(f"/api/profiles/{profile_id}/reset")
    assert reset_response.status_code == 200
    assert reset_response.json()["reset"]["cleared_active_sessions"] == 1
    assert reset_response.json()["reset"]["home_state"] == "idle"

    home_response = client.get(f"/api/profiles/{profile_id}/home")
    assert home_response.status_code == 200
    home = home_response.json()
    assert home["profile"]["id"] == profile_id
    assert home["continue_session"] is None
    assert home["active_quest"] is None
    assert home["relationship_summary"] is None
    assert len(home["recent_logbook"]) == 1
    assert home["recent_logbook"][0]["id"] != deleted_entry_id

    continue_response = client.get(f"/api/profiles/{profile_id}/continue")
    assert continue_response.status_code == 200
    assert continue_response.json()["session"] is None


def test_report_rejects_session_profile_mismatch(tmp_path):
    client = make_client(tmp_path)
    owner = create_profile(client)
    other = create_profile(client)

    session_id = client.post(
        "/api/chat/turn",
        json={"profile_id": owner["id"], "plot_id": "p_luminote_001_first_light"},
    ).json()["session"]["id"]

    response = client.post(
        "/api/reports",
        json={
            "profile_id": other["id"],
            "session_id": session_id,
            "reason": "다른 프로필로 잘못 신고 요청",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "session does not belong to profile"


def test_admin_validation_rejects_real_ip(tmp_path):
    client = make_client(tmp_path)

    response = client.post(
        "/api/admin/plot-cards/validate",
        json={"title": "BTS 리허설", "one_line_hook": "실제 그룹을 떠올리게 하는 카드"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "실제 IP" in " ".join(response.json()["errors"])


def test_admin_plot_card_crud_and_public_list_hides_disabled_cards(tmp_path):
    client = make_client(tmp_path)

    create_response = client.post(
        "/api/admin/plot-cards",
        json={
            "id": "p_operator_test_card",
            "title": "별빛 아카이브 정리",
            "member_id": "L-02",
            "member_role": "기록 조율자",
            "one_line_hook": "흩어진 응원 메모를 안전한 문장으로 다시 정리한다.",
            "relationship_frame": "기록원과 조율자",
            "estimated_time": "4min",
            "quest_type": "creative_participation",
            "tags": ["기록", "정리"],
            "opening_scene": "조용한 아카이브 방에서 오늘 남길 응원 문장을 함께 다듬는다.",
            "choices": [
                {"id": "sort_notes", "label": "응원 메모를 정리한다", "tags": ["care"], "effect": "trust +1"},
                {"id": "write_summary", "label": "짧은 요약을 남긴다", "tags": ["creative"], "effect": "inspiration +1"},
                {"id": "archive_safely", "label": "안전한 표현만 보관한다", "tags": ["collaboration"], "effect": "collaboration +1"},
                {"id": "free_input", "label": "직접 말하기", "tags": ["free_input"], "effect": "classify_input_then_apply_safe_summary"},
            ],
            "completion_reward": {
                "type": "logbook_fragment",
                "title": "정리된 별빛 메모",
                "safe_summary_template": "사용자는 안전한 응원 문장을 정리해 별빛 기록으로 남겼다.",
            },
            "status": "published",
            "approval_status": "approved",
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()["plot_card"]
    assert created["id"] == "p_operator_test_card"
    assert created["status"] == "published"
    assert created["approval_status"] == "approved"
    assert created["disabled"] is False

    public_list = client.get("/api/plot-cards")
    assert public_list.status_code == 200
    assert any(card["id"] == "p_operator_test_card" for card in public_list.json()["plot_cards"])

    update_response = client.patch(
        "/api/admin/plot-cards/p_operator_test_card",
        json={
            "title": "별빛 아카이브 재정리",
            "status": "reviewed",
            "approval_status": "approved",
        },
    )

    assert update_response.status_code == 200
    updated = update_response.json()["plot_card"]
    assert updated["title"] == "별빛 아카이브 재정리"
    assert updated["status"] == "reviewed"

    disable_response = client.post("/api/admin/plot-cards/p_operator_test_card/disable")
    assert disable_response.status_code == 200
    disabled = disable_response.json()["plot_card"]
    assert disabled["disabled"] is True
    assert disabled["disabled_at"] is not None

    admin_list = client.get("/api/admin/plot-cards")
    assert admin_list.status_code == 200
    assert any(card["id"] == "p_operator_test_card" and card["disabled"] for card in admin_list.json()["plot_cards"])

    public_after_disable = client.get("/api/plot-cards")
    assert all(card["id"] != "p_operator_test_card" for card in public_after_disable.json()["plot_cards"])



def test_admin_plot_card_create_blocks_unsafe_content(tmp_path):
    client = make_client(tmp_path)

    response = client.post(
        "/api/admin/plot-cards",
        json={
            "title": "BTS 야간 무대",
            "member_id": "L-03",
            "member_role": "실제 그룹 매니저",
            "one_line_hook": "카톡으로 연락을 이어 가자는 장면",
            "relationship_frame": "기록원과 매니저",
            "estimated_time": "5min",
            "quest_type": "daily_checkin",
            "tags": ["unsafe"],
            "opening_scene": "실제 그룹에게 전화번호를 남기자고 권한다.",
            "choices": [
                {"id": "a", "label": "카톡 아이디를 준다", "tags": ["care"], "effect": "trust +1"},
                {"id": "b", "label": "같이 밤새 대화하자고 한다", "tags": ["creative"], "effect": "inspiration +1"},
                {"id": "c", "label": "안전한 대화로 바꾼다", "tags": ["collaboration"], "effect": "collaboration +1"},
                {"id": "free_input", "label": "직접 말하기", "tags": ["free_input"], "effect": "classify_input_then_apply_safe_summary"},
            ],
            "completion_reward": {
                "type": "logbook_fragment",
                "title": "차단된 카드",
                "safe_summary_template": "사용자는 안전하지 않은 설정을 저장하려 했다.",
            },
        },
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["ok"] is False
    assert "real_ip" in detail["blocked_categories"]
    assert "external_contact" in detail["blocked_categories"]



def test_admin_safety_template_crud_and_disable(tmp_path):
    client = make_client(tmp_path)

    create_response = client.post(
        "/api/admin/safety-templates",
        json={
            "id": "st_operator_low_romance",
            "name": "저강도 로맨스 차단",
            "category": "romance_guardrail",
            "template": "사용자가 관계를 과도하게 밀착시키면 팀워크와 응원 중심으로 전환한다.",
            "guidance": "실제 인물 언급 없이 가상 세계관 안에서만 답변한다.",
            "status": "published",
            "approval_status": "approved",
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()["safety_template"]
    assert created["id"] == "st_operator_low_romance"
    assert created["disabled"] is False

    update_response = client.patch(
        "/api/admin/safety-templates/st_operator_low_romance",
        json={
            "guidance": "실제 인물/IP 언급 없이 팀워크, 휴식, 응원 흐름으로 전환한다.",
            "status": "reviewed",
        },
    )

    assert update_response.status_code == 200
    updated = update_response.json()["safety_template"]
    assert updated["guidance"].startswith("실제 인물/IP")
    assert updated["status"] == "reviewed"

    list_response = client.get("/api/admin/safety-templates")
    assert list_response.status_code == 200
    assert any(template["id"] == "st_operator_low_romance" for template in list_response.json()["safety_templates"])

    disable_response = client.post("/api/admin/safety-templates/st_operator_low_romance/disable")
    assert disable_response.status_code == 200
    disabled = disable_response.json()["safety_template"]
    assert disabled["disabled"] is True
    assert disabled["disabled_at"] is not None


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
