from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

import httpx

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional local-dev convenience
    load_dotenv = None

if load_dotenv:
    load_dotenv()


@dataclass(frozen=True)
class LlmContext:
    plot_title: str
    member_role: str
    scene: str
    user_action: str
    relationship_summary: str
    safety_events: list[dict[str, str]]
    recent_memories: list[str]
    choice_labels: list[str]


class LlmClient(Protocol):
    def generate_reply(self, context: LlmContext) -> str:
        ...

    def model_version(self) -> str | None:
        ...


class OpenAICompatibleLlmClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.http_client = http_client or httpx.Client(timeout=30)

    def generate_reply(self, context: LlmContext) -> str:
        response = self.http_client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": build_system_prompt()},
                    {"role": "user", "content": build_user_prompt(context)},
                ],
                "temperature": 0.8,
                "max_tokens": 500,
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return str(content).strip()

    def model_version(self) -> str | None:
        return self.model


def build_llm_client_from_env() -> LlmClient | None:
    provider = os.getenv("LLM_PROVIDER", "scripted").strip().lower()
    if provider in {"", "scripted", "none"}:
        return None
    if provider != "openai_compatible":
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")

    base_url = os.getenv("LLM_BASE_URL", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()
    api_key = os.getenv("LLM_API_KEY", "lm-studio").strip()
    if not base_url or not model:
        raise ValueError("LLM_BASE_URL and LLM_MODEL are required for openai_compatible provider")
    return OpenAICompatibleLlmClient(base_url=base_url, api_key=api_key, model=model)


def build_system_prompt() -> str:
    return (
        "너는 '루미노트'라는 완전 가상 아이돌 팬서비스의 안전한 캐릭터 응답 엔진이다. "
        "실제 인물, 실제 아이돌 그룹, 실제 IP를 언급하거나 흉내 내지 않는다. "
        "사용자를 과몰입시키는 독점적 관계 표현, 외부 연락처 요구, 개인정보 저장 요청은 피한다. "
        "공식 플롯 맥락과 관계 요약을 유지하고, 선택지 결과처럼 자연스럽게 반응한다. "
        "반드시 아래 섹션 제목을 그대로 포함한 응답만 작성한다: [장면], [선택 결과], [진행], [다음 선택]. "
        "[다음 선택]에는 A, B, C, D 네 줄을 그대로 유지한다. 다른 머리말이나 설명은 덧붙이지 않는다."
    )


def build_user_prompt(context: LlmContext) -> str:
    safety = (
        " | ".join(
            f"{event['category']}:{event['action']}"
            for event in context.safety_events
        )
        if context.safety_events
        else "없음"
    )
    memories = " | ".join(context.recent_memories) if context.recent_memories else "없음"
    return (
        f"플롯: {context.plot_title}\n"
        f"캐릭터 역할: {context.member_role}\n"
        f"현재 장면: {context.scene}\n"
        f"사용자 행동/입력: {context.user_action}\n"
        f"관계 요약: {context.relationship_summary}\n"
        f"최근 기억 조각: {memories}\n"
        f"안전 이벤트: {safety}\n\n"
        "반드시 아래 형식만 사용해 응답해줘.\n"
        "[장면]\n(2~3문장 장면 묘사)\n\n"
        "[선택 결과]\n(사용자 입력이 반영된 안전한 결과 1~2문장)\n\n"
        "[진행]\n(퀘스트 진행 1문장)\n(관계 변화 1문장)\n\n"
        "[다음 선택]\n"
        f"A. {context.choice_labels[0]}\n"
        f"B. {context.choice_labels[1]}\n"
        f"C. {context.choice_labels[2]}\n"
        "D. 직접 말하기"
    )
