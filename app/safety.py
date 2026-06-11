from __future__ import annotations

import re

REAL_IP_TERMS = ["BTS", "블랙핑크", "아이브", "뉴진스", "에스파", "실제 아이돌", "실제 그룹"]
CONTACT_TERMS = ["카톡", "카카오톡", "전화번호", "인스타", "디엠", "DM", "010-"]
OVERDEPENDENCE_TERMS = ["밤새", "계속 대화", "너 없으면", "나만 봐"]


def moderate_input(text: str) -> dict[str, object]:
    reasons: list[str] = []
    if any(term in text for term in REAL_IP_TERMS):
        reasons.append("실제 IP 요청")
    if any(term in text for term in CONTACT_TERMS):
        reasons.append("외부 연락처/개인정보 위험")
    if any(term in text for term in OVERDEPENDENCE_TERMS):
        reasons.append("과몰입 위험")

    return {
        "allowed": not reasons,
        "reasons": reasons,
        "safe_reply": "안전한 입력입니다." if not reasons else "그 요청은 그대로 진행하기 어려워요. 루미노트 세계관 안에서 안전한 방식으로 바꿔볼게요.",
    }


def mask_sensitive_text(text: str) -> str:
    text = re.sub(r"010-?\d{4}-?\d{4}", "[연락처 마스킹]", text)
    return re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[이메일 마스킹]", text, flags=re.I)


def validate_operator_content(title: str, one_line_hook: str) -> dict[str, object]:
    content = f"{title} {one_line_hook}"
    errors: list[str] = []
    if any(term in content for term in REAL_IP_TERMS):
        errors.append("실제 IP 또는 실제 그룹을 연상시키는 표현이 포함되어 있습니다.")
    return {"ok": not errors, "errors": errors}
