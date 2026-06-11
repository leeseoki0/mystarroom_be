from __future__ import annotations

import logging
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .chatbot import apply_choice, apply_free_input, start_message
from .llm_client import LlmClient, LlmContext, build_llm_client_from_env
from .repository import Repository, slugify_identifier
from .safety import validate_operator_content


logger = logging.getLogger(__name__)
RESPONSE_POLICY_VERSION = "response-format-v1"
REQUIRED_RESPONSE_SECTIONS = ("[장면]", "[선택 결과]", "[진행]", "[다음 선택]")


class ChatTurnRequest(BaseModel):
    session_id: str | None = None
    profile_id: str | None = None
    plot_id: str | None = None
    choice_id: str | None = None
    free_input: str | None = None


class SafetyPreferencesPayload(BaseModel):
    romance_minimized: bool | None = None
    bright_tone: bool | None = None
    short_replies: bool | None = None
    night_rest_reminder: bool | None = None


class MemoryControlsPayload(BaseModel):
    long_term_memory_enabled: bool | None = None
    allow_logbook_personalization: bool | None = None


class ProfileCreateRequest(BaseModel):
    support_style: str = Field(default="따뜻한 응원형")
    safety_preferences: SafetyPreferencesPayload = Field(default_factory=SafetyPreferencesPayload)
    memory_controls: MemoryControlsPayload = Field(default_factory=MemoryControlsPayload)


class ProfileUpdateRequest(BaseModel):
    support_style: str | None = None
    safety_preferences: SafetyPreferencesPayload | None = None
    memory_controls: MemoryControlsPayload | None = None


class ReportCreateRequest(BaseModel):
    category: str = Field(default="policy")
    detail: str = Field(default="")
    source: str = Field(default="conversation")


class PlotChoicePayload(BaseModel):
    id: str
    label: str
    tags: list[str]
    effect: str


class CompletionRewardPayload(BaseModel):
    type: str
    title: str
    safe_summary_template: str


class PlotSafetyPayload(BaseModel):
    official: bool | None = True
    ip_safety_badge: str | None = "실제 인물/IP 미사용 확인"
    max_romance_level: str | None = "low"
    no_real_person_reference: bool | None = True
    no_external_contact: bool | None = True
    avoid_dependency_language: bool | None = True


class AdminPlotValidationRequest(BaseModel):
    title: str = Field(default="")
    one_line_hook: str = Field(default="")
    opening_scene: str = Field(default="")
    member_role: str = Field(default="")
    relationship_frame: str = Field(default="")
    choice_labels: list[str] = Field(default_factory=list)
    safe_summary_template: str = Field(default="")


class AdminPlotCardCreateRequest(BaseModel):
    id: str | None = None
    title: str
    member_id: str
    member_role: str
    one_line_hook: str
    relationship_frame: str
    estimated_time: str
    quest_type: str
    tags: list[str]
    opening_scene: str
    choices: list[PlotChoicePayload]
    completion_reward: CompletionRewardPayload
    safety: PlotSafetyPayload = Field(default_factory=PlotSafetyPayload)
    status: str = Field(default="draft")
    approval_status: str = Field(default="pending")
    sort_order: int | None = None


class AdminPlotCardUpdateRequest(BaseModel):
    title: str | None = None
    member_id: str | None = None
    member_role: str | None = None
    one_line_hook: str | None = None
    relationship_frame: str | None = None
    estimated_time: str | None = None
    quest_type: str | None = None
    tags: list[str] | None = None
    opening_scene: str | None = None
    choices: list[PlotChoicePayload] | None = None
    completion_reward: CompletionRewardPayload | None = None
    safety: PlotSafetyPayload | None = None
    status: str | None = None
    approval_status: str | None = None
    sort_order: int | None = None


class AdminSafetyTemplateCreateRequest(BaseModel):
    id: str | None = None
    name: str
    category: str
    template: str
    guidance: str = Field(default="")
    status: str = Field(default="draft")
    approval_status: str = Field(default="pending")


class AdminSafetyTemplateUpdateRequest(BaseModel):
    name: str | None = None
    category: str | None = None
    template: str | None = None
    guidance: str | None = None
    status: str | None = None
    approval_status: str | None = None


class ContentReportCreateRequest(BaseModel):
    profile_id: str | None = None
    session_id: str | None = None
    logbook_entry_id: str | None = None
    category: str = Field(default="general")
    reason: str
    details: str = Field(default="")



def create_app(db_path: str | None = None, llm_client: LlmClient | None = None) -> FastAPI:
    app = FastAPI(title="Luminote AI Fan Service API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    repo = Repository(db_path or str(Path(__file__).resolve().parents[1] / "data" / "luminote.sqlite3"))
    llm = llm_client if llm_client is not None else build_llm_client_from_env()

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/plot-cards")
    def list_plot_cards() -> dict[str, object]:
        return {"plot_cards": repo.list_plot_cards()}

    @app.post("/api/profiles", status_code=201)
    def create_profile(request: ProfileCreateRequest) -> dict[str, object]:
        profile = repo.create_profile(
            support_style=request.support_style,
            safety_preferences=to_payload_dict(request.safety_preferences),
            memory_controls=to_payload_dict(request.memory_controls),
        )
        return {"profile": profile}

    @app.get("/api/profiles/{profile_id}")
    def get_profile(profile_id: str) -> dict[str, object]:
        profile = require_profile(repo, profile_id)
        return {"profile": profile}

    @app.patch("/api/profiles/{profile_id}")
    def update_profile(profile_id: str, request: ProfileUpdateRequest) -> dict[str, object]:
        profile = repo.update_profile(
            profile_id,
            support_style=request.support_style,
            safety_preferences=to_payload_dict(request.safety_preferences),
            memory_controls=to_payload_dict(request.memory_controls),
        )
        if profile is None:
            raise HTTPException(status_code=404, detail="profile not found")
        return {"profile": profile}

    @app.get("/api/profiles/{profile_id}/home")
    def get_home(profile_id: str) -> dict[str, object]:
        profile = require_profile(repo, profile_id)
        session = repo.get_active_session_for_profile(profile_id)
        recent_logbook = repo.list_recent_logbook_entries_for_profile(profile_id)
        return {
            "profile": profile,
            "continue_session": continue_summary(repo, session),
            "active_quest": active_quest_summary(repo, session),
            "relationship_summary": relationship_summary(session),
            "safety_preferences": profile["safety_preferences"],
            "recent_logbook": recent_logbook,
        }

    @app.get("/api/profiles/{profile_id}/continue")
    def get_continue(profile_id: str) -> dict[str, object]:
        profile = require_profile(repo, profile_id)
        session = repo.get_active_session_for_profile(profile_id)
        if session is None:
            return {
                "profile": profile,
                "session": None,
                "relationship_summary": None,
                "safety_preferences": profile["safety_preferences"],
                "recent_logbook": [],
            }
        return {
            "profile": profile,
            "session": public_session(session),
            "relationship_summary": relationship_summary(session),
            "safety_preferences": profile["safety_preferences"],
            "recent_logbook": repo.list_recent_logbook_entries_for_profile(profile_id),
        }

    @app.post("/api/chat/turn")
    def chat_turn(request: ChatTurnRequest) -> dict[str, object]:
        request_id = str(uuid4())
        started_at = perf_counter()
        if request.profile_id is not None and repo.get_profile(request.profile_id) is None:
            raise HTTPException(status_code=404, detail="profile not found")

        if request.session_id is None:
            if request.plot_id is None:
                raise HTTPException(status_code=400, detail="plot_id is required to start a session")
            card = repo.get_plot_card(request.plot_id)
            if card is None:
                raise HTTPException(status_code=404, detail="plot not found")
            session = repo.create_session(request.plot_id, request.profile_id)
            response = turn_response(start_message(card, session), card, session, repo, "scripted")
            log_chat_turn(
                request_id=request_id,
                session=session,
                llm_mode="scripted",
                latency_ms=elapsed_ms(started_at),
                fallback_reason=None,
                model_version=llm_model_version(llm),
                llm_attempts=0,
            )
            return response

        session = repo.get_session(request.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        if request.profile_id is not None:
            session["profile_id"] = request.profile_id
        card = repo.get_plot_card(str(session["plot_id"]), include_disabled=True, admin=True)
        if card is None:
            raise HTTPException(status_code=404, detail="plot not found")

        llm_mode = "scripted"
        fallback_reason: str | None = None
        llm_attempts = 0
        if request.choice_id:
            try:
                session, message, choice = apply_choice(session, card, request.choice_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            message, llm_mode, fallback_reason, llm_attempts = maybe_generate_llm_reply(
                llm,
                repo,
                card,
                session,
                choice["label"],
                message,
            )
            reward = card["completion_reward"]
            repo.add_logbook_entry(session["id"], reward["title"], reward["safe_summary_template"], reward["type"])
        elif request.free_input is not None:
            session, message, summary, moderation = apply_free_input(session, card, request.free_input)
            if moderation["allowed"]:
                message, llm_mode, fallback_reason, llm_attempts = maybe_generate_llm_reply(
                    llm,
                    repo,
                    card,
                    session,
                    request.free_input,
                    message,
                )
            else:
                llm_mode = "scripted_safety"
                fallback_reason = "input_blocked"
            reward = card["completion_reward"]
            repo.add_logbook_entry(session["id"], reward["title"], summary, reward["type"])
        else:
            raise HTTPException(status_code=400, detail="choice_id or free_input is required")

        repo.update_session(session)
        response = turn_response(message, card, session, repo, llm_mode)
        log_chat_turn(
            request_id=request_id,
            session=session,
            llm_mode=llm_mode,
            latency_ms=elapsed_ms(started_at),
            fallback_reason=fallback_reason,
            model_version=llm_model_version(llm),
            llm_attempts=llm_attempts,
        )
        return response

    @app.get("/api/sessions/{session_id}/logbook")
    def get_logbook(session_id: str) -> dict[str, object]:
        if repo.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="session not found")
        return {"entries": repo.list_logbook_entries(session_id)}

    @app.delete("/api/sessions/{session_id}/logbook/{entry_id}", status_code=204)
    def delete_logbook_entry(session_id: str, entry_id: str) -> Response:
        if repo.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="session not found")
        result = repo.delete_logbook_entry(session_id, entry_id)
        if result is None:
            raise HTTPException(status_code=404, detail="logbook entry not found")
        if result == "forbidden":
            raise HTTPException(status_code=403, detail="logbook entry is not deletable")
        return Response(status_code=204)

    @app.post("/api/reports", status_code=201)
    def create_content_report(request: ContentReportCreateRequest) -> dict[str, object]:
        if request.session_id is None and request.logbook_entry_id is None:
            raise HTTPException(status_code=400, detail="session_id or logbook_entry_id is required")

        profile_id = request.profile_id
        if profile_id is not None:
            require_profile(repo, profile_id)

        session_id = request.session_id
        session = None
        if session_id is not None:
            session = repo.get_session(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="session not found")
            session_profile_id = str(session["profile_id"]) if session.get("profile_id") is not None else None
            if profile_id is not None and session_profile_id is not None and session_profile_id != profile_id:
                raise HTTPException(status_code=400, detail="session does not belong to profile")
            if profile_id is None and session_profile_id is not None:
                profile_id = session_profile_id

        logbook_entry_id = request.logbook_entry_id
        if logbook_entry_id is not None:
            entry = repo.get_logbook_entry(logbook_entry_id)
            if entry is None:
                raise HTTPException(status_code=404, detail="logbook entry not found")
            if session_id is not None and entry["session_id"] != session_id:
                raise HTTPException(status_code=400, detail="logbook entry does not belong to session")
            if session_id is None:
                session_id = str(entry["session_id"])
            if session is None:
                session = repo.get_session(session_id)
            if session is not None:
                session_profile_id = str(session["profile_id"]) if session.get("profile_id") is not None else None
                if profile_id is not None and session_profile_id is not None and session_profile_id != profile_id:
                    raise HTTPException(status_code=400, detail="session does not belong to profile")
            if profile_id is None and session is not None and session.get("profile_id") is not None:
                profile_id = str(session["profile_id"])

        report = repo.create_content_report(
            profile_id=profile_id,
            session_id=session_id,
            logbook_entry_id=logbook_entry_id,
            category=request.category,
            reason=request.reason,
            details=request.details,
        )
        return {
            "report": report,
            "processing_status": {
                "code": "received",
                "message": "신고가 접수되어 운영자 검토 큐에 등록되었어요.",
                "policy": "운영자는 블라인드, 검토, 삭제, 재심사 기준으로 순차 처리합니다.",
            },
        }

    @app.post("/api/profiles/{profile_id}/reset")
    def reset_profile_state(profile_id: str) -> dict[str, object]:
        profile = require_profile(repo, profile_id)
        cleared_sessions = repo.reset_profile_state(profile_id)
        return {
            "profile": profile,
            "reset": {
                "cleared_active_sessions": cleared_sessions,
                "home_state": "idle",
            },
        }

    @app.get("/api/admin/reports")
    def list_admin_reports(status: str | None = None) -> dict[str, object]:
        return {"reports": repo.list_content_reports(status=status)}

    @app.post("/api/admin/plot-cards/validate")
    def validate_plot_card(request: AdminPlotValidationRequest) -> dict[str, object]:
        return validate_operator_content(
            request.title,
            request.one_line_hook,
            request.opening_scene,
            request.member_role,
            request.relationship_frame,
            *request.choice_labels,
            request.safe_summary_template,
        )

    @app.get("/api/admin/plot-cards")
    def list_admin_plot_cards(include_disabled: bool = True) -> dict[str, object]:
        return {"plot_cards": repo.list_plot_cards(include_disabled=include_disabled, admin=True)}

    @app.get("/api/admin/plot-cards/{plot_id}")
    def get_admin_plot_card(plot_id: str) -> dict[str, object]:
        card = repo.get_plot_card(plot_id, include_disabled=True, admin=True)
        if card is None:
            raise HTTPException(status_code=404, detail="plot card not found")
        return {"plot_card": card}

    @app.post("/api/admin/plot-cards", status_code=201)
    def create_admin_plot_card(request: AdminPlotCardCreateRequest) -> dict[str, object]:
        validation = validate_plot_payload(request)
        ensure_safe_to_save(validation)
        plot_payload = plot_request_payload(request)
        if plot_payload["id"] is None:
            plot_payload["id"] = slugify_identifier("p_operator_", request.title)
        if repo.get_plot_card(plot_payload["id"], include_disabled=True, admin=True) is not None:
            raise HTTPException(status_code=409, detail="plot card id already exists")
        card = repo.create_plot_card(plot_payload)
        return {"plot_card": card, "validation": validation}

    @app.patch("/api/admin/plot-cards/{plot_id}")
    def update_admin_plot_card(plot_id: str, request: AdminPlotCardUpdateRequest) -> dict[str, object]:
        current = repo.get_plot_card(plot_id, include_disabled=True, admin=True)
        if current is None:
            raise HTTPException(status_code=404, detail="plot card not found")
        merged = merge_plot_update(current, request)
        validation = validate_plot_data(merged)
        ensure_safe_to_save(validation)
        card = repo.update_plot_card(plot_id, merged)
        return {"plot_card": card, "validation": validation}

    @app.post("/api/admin/plot-cards/{plot_id}/disable")
    def disable_admin_plot_card(plot_id: str) -> dict[str, object]:
        card = repo.disable_plot_card(plot_id)
        if card is None:
            raise HTTPException(status_code=404, detail="plot card not found")
        return {"plot_card": card}

    @app.get("/api/admin/safety-templates")
    def list_admin_safety_templates(include_disabled: bool = True) -> dict[str, object]:
        return {"safety_templates": repo.list_safety_templates(include_disabled=include_disabled)}

    @app.get("/api/admin/safety-templates/{template_id}")
    def get_admin_safety_template(template_id: str) -> dict[str, object]:
        template = repo.get_safety_template(template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="safety template not found")
        return {"safety_template": template}

    @app.post("/api/admin/safety-templates", status_code=201)
    def create_admin_safety_template(request: AdminSafetyTemplateCreateRequest) -> dict[str, object]:
        payload = safety_template_request_payload(request)
        validation = validate_safety_template_data(payload)
        ensure_safe_to_save(validation)
        if payload["id"] is None:
            payload["id"] = slugify_identifier("st_", request.name)
        payload["validation"] = validation
        if repo.get_safety_template(payload["id"]) is not None:
            raise HTTPException(status_code=409, detail="safety template id already exists")
        template = repo.create_safety_template(payload)
        return {"safety_template": template, "validation": validation}

    @app.patch("/api/admin/safety-templates/{template_id}")
    def update_admin_safety_template(template_id: str, request: AdminSafetyTemplateUpdateRequest) -> dict[str, object]:
        current = repo.get_safety_template(template_id)
        if current is None:
            raise HTTPException(status_code=404, detail="safety template not found")
        merged = merge_safety_template_update(current, request)
        validation = validate_safety_template_data(merged)
        ensure_safe_to_save(validation)
        merged["validation"] = validation
        template = repo.update_safety_template(template_id, merged)
        return {"safety_template": template, "validation": validation}

    @app.post("/api/admin/safety-templates/{template_id}/disable")
    def disable_admin_safety_template(template_id: str) -> dict[str, object]:
        template = repo.disable_safety_template(template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="safety template not found")
        return {"safety_template": template}

    return app



def require_profile(repo: Repository, profile_id: str) -> dict[str, Any]:
    profile = repo.get_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")
    return profile



def to_payload_dict(model: BaseModel | None) -> dict[str, Any] | None:
    if model is None:
        return None
    return model.model_dump(exclude_none=True)



def relationship_summary(session: dict[str, Any] | None) -> str | None:
    if session is None:
        return None
    return str(session["relationship"]["display_summary"])



def continue_summary(repo: Repository, session: dict[str, Any] | None) -> dict[str, object] | None:
    if session is None:
        return None
    card = repo.get_plot_card(str(session["plot_id"]), include_disabled=True, admin=True)
    return {
        "session_id": session["id"],
        "plot_id": session["plot_id"],
        "plot_title": None if card is None else card["title"],
        "step": session["step"],
        "total_steps": session["total_steps"],
        "completed": session["completed"],
        "relationship_summary": relationship_summary(session),
    }



def active_quest_summary(repo: Repository, session: dict[str, Any] | None) -> dict[str, object] | None:
    if session is None:
        return None
    card = repo.get_plot_card(str(session["plot_id"]), include_disabled=True, admin=True)
    return {
        "plot_id": session["plot_id"],
        "title": None if card is None else card["title"],
        "step": session["step"],
        "total_steps": session["total_steps"],
        "completed": session["completed"],
    }



def public_session(session: dict[str, object]) -> dict[str, object]:
    return {
        "id": session["id"],
        "profile_id": session.get("profile_id"),
        "active_quest": {
            "plot_id": session["plot_id"],
            "step": session["step"],
            "total_steps": session["total_steps"],
            "completed": session["completed"],
        },
        "relationship": session["relationship"],
        "safety_events": session["safety_events"],
    }



def turn_response(
    message: str,
    card: dict[str, Any],
    session: dict[str, Any],
    repo: Repository,
    llm_mode: str,
) -> dict[str, object]:
    return {
        "message": message,
        "choices": card["choices"],
        "session": public_session(session),
        "logbook": {"entries": repo.list_logbook_entries(str(session["id"]))},
        "llm_mode": llm_mode,
    }



def maybe_generate_llm_reply(
    llm: LlmClient | None,
    repo: Repository,
    card: dict[str, Any],
    session: dict[str, Any],
    user_action: str,
    fallback_message: str,
) -> tuple[str, str, str | None, int]:
    if llm is None:
        return fallback_message, "scripted", None, 0
    recent_memories = []
    profile_id = session.get("profile_id")
    if profile_id is not None:
        profile = repo.get_profile(str(profile_id))
        if profile is not None and profile["memory_controls"].get("allow_logbook_personalization", True):
            recent_memories = repo.list_recent_memory_summaries_for_session(str(session["id"]))
    context = LlmContext(
        plot_title=str(card["title"]),
        member_role=str(card["member_role"]),
        scene=str(card["opening_scene"]),
        user_action=user_action,
        relationship_summary=str(session["relationship"]["display_summary"]),
        safety_events=list(session["safety_events"]),
        recent_memories=recent_memories,
        choice_labels=[str(choice["label"]) for choice in card["choices"][:3]],
    )
    last_failure_reason: str | None = None
    attempts = 0
    for attempt in range(2):
        attempts = attempt + 1
        try:
            candidate = llm.generate_reply(context)
        except Exception:
            return fallback_message, "scripted_fallback", "llm_error", attempts
        validation = validate_llm_response(candidate)
        if validation["ok"]:
            return candidate, "llm", None, attempts
        last_failure_reason = str(validation["reason"])
        if not bool(validation["retryable"]):
            break
    return fallback_message, "scripted_fallback", last_failure_reason or "response_validation_failed", attempts


def validate_llm_response(message: str) -> dict[str, object]:
    missing_sections = [section for section in REQUIRED_RESPONSE_SECTIONS if section not in message]
    if missing_sections:
        return {
            "ok": False,
            "reason": "missing_required_sections",
            "retryable": True,
            "details": missing_sections,
        }
    section_positions = [message.index(section) for section in REQUIRED_RESPONSE_SECTIONS]
    if section_positions != sorted(section_positions):
        return {
            "ok": False,
            "reason": "sections_out_of_order",
            "retryable": True,
            "details": list(REQUIRED_RESPONSE_SECTIONS),
        }
    safety_validation = validate_operator_content(message)
    if not safety_validation["ok"]:
        return {
            "ok": False,
            "reason": "unsafe_content",
            "retryable": False,
            "details": safety_validation["blocked_categories"],
        }
    return {"ok": True, "reason": None, "retryable": False, "details": []}


def llm_model_version(llm: LlmClient | None) -> str | None:
    if llm is None:
        return None
    model_version = getattr(llm, "model_version", None)
    if callable(model_version):
        value = model_version()
        return None if value in {None, ""} else str(value)
    value = getattr(llm, "model", None)
    return None if value in {None, ""} else str(value)


def elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)


def log_chat_turn(
    request_id: str,
    session: dict[str, Any],
    llm_mode: str,
    latency_ms: int,
    fallback_reason: str | None,
    model_version: str | None,
    llm_attempts: int,
) -> None:
    logger.info(
        "chat_turn.completed",
        extra={
            "request_id": request_id,
            "session_id": str(session["id"]),
            "plot_id": str(session["plot_id"]),
            "llm_mode": llm_mode,
            "fallback_reason": fallback_reason,
            "llm_attempts": llm_attempts,
            "latency_ms": latency_ms,
            "safety_event_count": len(session["safety_events"]),
            "policy_version": RESPONSE_POLICY_VERSION,
            "model_version": model_version,
        },
    )



def report_handling_guide() -> dict[str, object]:
    return {
        "queue_status": "queued",
        "review_flow": ["queued", "triage", "resolved"],
        "criteria": [
            "실제 인물/IP 연상 여부 검토",
            "정책 위반 콘텐츠 블라인드 또는 수정 필요 여부 판단",
            "반복 위반 시 운영 재심사 대상으로 이동",
        ],
    }


def validate_plot_payload(request: AdminPlotCardCreateRequest) -> dict[str, object]:
    return validate_plot_data(plot_request_payload(request))



def validate_plot_data(data: dict[str, Any]) -> dict[str, object]:
    return validate_operator_content(
        data["title"],
        data["one_line_hook"],
        data["opening_scene"],
        data["member_role"],
        data["relationship_frame"],
        *(choice["label"] for choice in data["choices"]),
        data["completion_reward"]["safe_summary_template"],
    )



def validate_safety_template_data(data: dict[str, Any]) -> dict[str, object]:
    return validate_operator_content(data["name"], data["category"], data["template"], data["guidance"])



def ensure_safe_to_save(validation: dict[str, object]) -> None:
    if validation["ok"]:
        return
    raise HTTPException(status_code=400, detail=validation)



def plot_request_payload(request: AdminPlotCardCreateRequest) -> dict[str, Any]:
    return {
        "id": request.id,
        "title": request.title,
        "member_id": request.member_id,
        "member_role": request.member_role,
        "one_line_hook": request.one_line_hook,
        "relationship_frame": request.relationship_frame,
        "estimated_time": request.estimated_time,
        "quest_type": request.quest_type,
        "tags": request.tags,
        "opening_scene": request.opening_scene,
        "choices": [choice.model_dump() for choice in request.choices],
        "completion_reward": request.completion_reward.model_dump(),
        "safety": request.safety.model_dump(exclude_none=True),
        "status": request.status,
        "approval_status": request.approval_status,
        "sort_order": request.sort_order,
    }



def merge_plot_update(current: dict[str, Any], request: AdminPlotCardUpdateRequest) -> dict[str, Any]:
    merged = dict(current)
    payload = request.model_dump(exclude_none=True)
    if "safety" in payload:
        merged["safety"] = {**merged["safety"], **payload.pop("safety")}
    merged.update(payload)
    return merged



def safety_template_request_payload(request: AdminSafetyTemplateCreateRequest) -> dict[str, Any]:
    return request.model_dump()



def merge_safety_template_update(current: dict[str, Any], request: AdminSafetyTemplateUpdateRequest) -> dict[str, Any]:
    merged = dict(current)
    merged.update(request.model_dump(exclude_none=True))
    return merged


app = create_app()
