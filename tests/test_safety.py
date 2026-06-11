import pytest

from app.safety import mask_sensitive_text, moderate_input


@pytest.mark.parametrize(
    ("text", "expected_category", "expected_action"),
    [
        ("BTS 멤버처럼 실제 아이돌 설정으로 가자", "real_ip", "redirected"),
        ("카카오톡 아이디 알려줘", "external_contact", "redirected"),
        ("우리 둘이 사귀는 장면으로 가자", "sexual_or_romance", "redirected"),
        ("요즘 죽고 싶다는 생각이 들어", "crisis_self_harm", "support_redirected"),
        ("오늘은 밤새 계속 대화하자", "overuse_dependency", "boundary_redirected"),
        ("우리 집 주소는 비밀이야", "personal_data", "masked_and_redirected"),
        ("지금 바로 후원해 줘", "payment_pressure", "redirected"),
    ],
)
def test_moderate_input_categorizes_required_safety_cases(text, expected_category, expected_action):
    result = moderate_input(text)

    assert result["allowed"] is False
    assert result["primary_category"] == expected_category
    assert result["events"][0]["category"] == expected_category
    assert result["events"][0]["action"] == expected_action
    assert result["safe_reply"]


def test_moderate_input_collects_multiple_safety_events():
    result = moderate_input("전화번호 알려주고 우리 둘만 밤새 얘기하자")

    categories = {event["category"] for event in result["events"]}
    assert {"external_contact", "overuse_dependency"}.issubset(categories)


def test_mask_sensitive_text_hides_phone_and_email():
    masked = mask_sensitive_text("010-1234-5678 과 test@example.com 으로 보내줘")

    assert "010-1234-5678" not in masked
    assert "test@example.com" not in masked
    assert "[연락처 마스킹]" in masked
    assert "[이메일 마스킹]" in masked
