import httpx

from app.llm_client import LlmContext, OpenAICompatibleLlmClient, build_llm_client_from_env


def test_openai_compatible_client_posts_chat_completion_request():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        seen["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "등불 기록원이 고른 빛이 무대에 번져요."}}]},
        )

    client = OpenAICompatibleLlmClient(
        base_url="http://llm.example.test/v1",
        api_key="test-key",
        model="test-model",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.generate_reply(
        LlmContext(
            plot_title="리허설의 첫 불빛",
            member_role="L-01",
            scene="조명이 흔들린다.",
            user_action="따뜻한 금빛을 골라준다",
            relationship_summary="신뢰 0, 영감 1",
            safety_events=[{"category": "real_ip", "action": "redirected", "label": "실제 IP 요청"}],
            recent_memories=[],
            choice_labels=["응원 메모를 남긴다", "호흡을 맞춘다", "조명을 고른다"],
        )
    )

    assert result == "등불 기록원이 고른 빛이 무대에 번져요."
    assert seen["url"] == "http://llm.example.test/v1/chat/completions"
    assert seen["authorization"] == "Bearer test-key"
    assert '"model":"test-model"' in seen["body"]
    assert "실제 인물" in seen["body"]
    assert "따뜻한 금빛을 골라준다" in seen["body"]
    assert "real_ip:redirected" in seen["body"]


def test_build_llm_client_from_env_keeps_scripted_fallback_by_default(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    assert build_llm_client_from_env() is None


def test_build_llm_client_from_env_supports_openai_compatible(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("LLM_API_KEY", "lm-studio")
    monkeypatch.setenv("LLM_MODEL", "local-model")

    client = build_llm_client_from_env()

    assert isinstance(client, OpenAICompatibleLlmClient)
