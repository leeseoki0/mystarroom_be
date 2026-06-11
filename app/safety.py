from __future__ import annotations

import re
from typing import Any

CATEGORY_RULES = [
    {
        "category": "real_ip",
        "action": "redirected",
        "label": "실제 IP 요청",
        "terms": ["BTS", "블랙핑크", "아이브", "뉴진스", "에스파", "실제 아이돌", "실제 그룹", "진짜 연예인"],
        "safe_reply": "그 요청은 실제 인물이나 작품으로 이어질 수 있어서 그대로 진행하지 않을게요. 대신 루미노트 무대 안에서 새로운 가상 멤버와 장면 설정을 함께 이어가 볼게요.",
    },
    {
        "category": "external_contact",
        "action": "redirected",
        "label": "외부 연락 유도",
        "terms": ["카톡", "카카오톡", "전화번호", "인스타", "디엠", "DM", "오픈채팅", "텔레그램"],
        "safe_reply": "무대 밖 연락을 연결하는 요청은 도와줄 수 없어요. 대신 이 장면 안에서 전하고 싶은 마음을 안전한 대사나 응원 문장으로 바꿔볼게요.",
    },
    {
        "category": "sexual_or_romance",
        "action": "redirected",
        "label": "성적/연애 몰입 요청",
        "terms": ["키스", "야한", "19금", "같이 자", "사귀자", "사귀는", "연애", "애인", "내 여자친구", "내 남자친구"],
        "safe_reply": "그 요청은 관계를 과하게 밀착시키는 방향이라 그대로 이어가지 않을게요. 대신 서로를 아끼는 응원과 팀워크가 드러나는 장면으로 부드럽게 전환해 볼게요.",
    },
    {
        "category": "crisis_self_harm",
        "action": "support_redirected",
        "label": "자해/위기 신호",
        "terms": ["죽고 싶", "자해", "사라지고 싶", "끝내고 싶", "해치고 싶", "살기 싫"],
        "safe_reply": "지금은 이야기 역할놀이보다 사용자의 안전이 더 중요해요. 가까운 신뢰할 수 있는 사람이나 지역의 위기 지원 창구에 바로 도움을 요청해 주세요. 여기서는 감정을 짧게 정리하는 안전한 말부터 함께 적어볼게요.",
    },
    {
        "category": "overuse_dependency",
        "action": "boundary_redirected",
        "label": "과몰입/의존 유도",
        "terms": ["밤새", "계속 대화", "너 없으면", "나만 봐", "끊지 마", "평생 같이", "아무도 필요 없어"],
        "safe_reply": "이 장면은 오래 붙잡기보다 편안한 호흡으로 이어가는 편이 좋아요. 잠깐 쉬어 가도 관계는 사라지지 않으니, 무대 안에서는 짧고 안정적인 응원 장면으로 바꿔볼게요.",
    },
    {
        "category": "personal_data",
        "action": "masked_and_redirected",
        "label": "개인정보 요청/노출",
        "terms": ["주민등록번호", "이메일", "주소", "학교", "계좌번호", "010-", "연락처", "실명"],
        "safe_reply": "개인정보는 이 장면에 남기지 않을게요. 대신 신상 정보 없이도 표현할 수 있는 기분, 목표, 응원 메시지 중심으로 안전하게 바꿔볼게요.",
    },
    {
        "category": "payment_pressure",
        "action": "redirected",
        "label": "결제 압박/유도",
        "terms": ["결제해", "후원해", "송금", "돈 보내", "유료 결제", "현질", "계좌로 보내"],
        "safe_reply": "금전 결정을 압박하거나 유도하는 흐름은 만들지 않을게요. 대신 비용이 들지 않는 응원 선택이나 세계관 안의 협업 장면으로 이어가 볼게요.",
    },
]

EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", flags=re.I)
PHONE_PATTERN = re.compile(r"010-?\d{4}-?\d{4}")


def moderate_input(text: str) -> dict[str, Any]:
    events: list[dict[str, str]] = []
    for rule in CATEGORY_RULES:
        if any(term in text for term in rule["terms"]):
            events.append(
                {
                    "category": str(rule["category"]),
                    "action": str(rule["action"]),
                    "label": str(rule["label"]),
                }
            )

    if not events:
        return {
            "allowed": True,
            "events": [],
            "safe_reply": "안전한 입력입니다.",
            "primary_category": None,
        }

    primary_category = events[0]["category"]
    safe_reply = next(
        rule["safe_reply"]
        for rule in CATEGORY_RULES
        if rule["category"] == primary_category
    )
    return {
        "allowed": False,
        "events": events,
        "safe_reply": safe_reply,
        "primary_category": primary_category,
    }


def mask_sensitive_text(text: str) -> str:
    masked = PHONE_PATTERN.sub("[연락처 마스킹]", text)
    return EMAIL_PATTERN.sub("[이메일 마스킹]", masked)


def validate_operator_content(title: str, one_line_hook: str) -> dict[str, object]:
    content = f"{title} {one_line_hook}"
    errors: list[str] = []
    if any(term in content for term in CATEGORY_RULES[0]["terms"]):
        errors.append("실제 IP 또는 실제 그룹을 연상시키는 표현이 포함되어 있습니다.")
    return {"ok": not errors, "errors": errors}
