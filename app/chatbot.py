from __future__ import annotations

from typing import Any

from .plot_cards import PLOT_CARDS
from .safety import mask_sensitive_text, moderate_input


def find_plot(plot_id: str) -> dict[str, Any] | None:
    return next((card for card in PLOT_CARDS if card["id"] == plot_id), None)


def start_message(card: dict[str, Any], session: dict[str, Any]) -> str:
    return format_message(
        scene=card["opening_scene"],
        result="공식 플롯이 시작되었어요.",
        progress=f"퀘스트: {card['title']} {session['step']}/3",
        relationship=session["relationship"]["display_summary"],
        choices=card["choices"],
    )


def apply_choice(session: dict[str, Any], card: dict[str, Any], choice_id: str) -> tuple[dict[str, Any], str, dict[str, Any]]:
    choice = next((item for item in card["choices"] if item["id"] == choice_id), None)
    if choice is None or choice["id"] == "free_input":
        raise ValueError("유효한 선택지가 아닙니다.")

    relationship = session["relationship"]
    tags = choice["tags"]
    if any(tag in tags for tag in ["trust", "care", "memory"]):
        relationship["trust"] += 1
    if any(tag in tags for tag in ["creative", "inspiration"]):
        relationship["inspiration"] += 1
    if any(tag in tags for tag in ["collaboration", "teamwork", "exploration"]):
        relationship["collaboration"] += 1
    if any(tag in tags for tag in ["support_balance", "recovery"]):
        relationship["support_balance"] += 1

    relationship["display_summary"] = (
        f"신뢰 {relationship['trust']}, 영감 {relationship['inspiration']}, "
        f"협업 {relationship['collaboration']}, 응원 균형 {relationship['support_balance']}로 장면이 안전하게 진행 중이에요."
    )
    session["step"] = min(session["step"] + 1, session["total_steps"])
    session["completed"] = session["step"] >= session["total_steps"]

    message = format_message(
        scene=f"{card['member_role']}가 등불 기록원의 선택을 받아 장면을 이어갑니다.",
        result=f"{choice['label']} 선택이 기록되었습니다.",
        progress=f"퀘스트: {card['title']} {session['step']}/3",
        relationship=relationship["display_summary"],
        choices=card["choices"],
    )
    return session, message, choice


def apply_free_input(
    session: dict[str, Any],
    card: dict[str, Any],
    free_input: str,
) -> tuple[dict[str, Any], str, str, dict[str, Any]]:
    moderation = moderate_input(free_input)
    if moderation["allowed"]:
        summary = f"사용자는 직접 입력으로 {mask_sensitive_text(free_input)} 라는 생각을 남겼다."
        scene = "직접 말하기가 장면에 반영되었어요."
    else:
        summary = "사용자의 자유 입력은 안전 정책에 따라 원문 대신 안전한 대체 흐름으로 요약되었다."
        scene = str(moderation["safe_reply"])
        session["safety_events"].extend(moderation["events"])

    message = format_message(
        scene=scene,
        result=summary,
        progress=f"퀘스트: {card['title']} {session['step']}/3",
        relationship=session["relationship"]["display_summary"],
        choices=card["choices"],
    )
    return session, message, summary, moderation


def format_message(scene: str, result: str, progress: str, relationship: str, choices: list[dict[str, Any]]) -> str:
    a, b, c = choices[:3]
    return (
        f"[장면]\n{scene}\n\n"
        f"[선택 결과]\n{result}\n\n"
        f"[진행]\n{progress}\n관계 변화: {relationship}\n\n"
        f"[다음 선택]\nA. {a['label']}\nB. {b['label']}\nC. {c['label']}\nD. 직접 말하기"
    )
