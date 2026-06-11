from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .chatbot import apply_choice, apply_free_input, find_plot, start_message
from .llm_client import LlmClient, LlmContext, build_llm_client_from_env
from .plot_cards import PLOT_CARDS
from .repository import Repository
from .safety import validate_operator_content


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


class AdminPlotValidationRequest(BaseModel):
    title: str = Field(default="")
    one_line_hook: str = Field(default="")



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
        return {"plot_cards": PLOT_CARDS}

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
            "continue_session": continue_summary(session),
            "active_quest": active_quest_summary(session),
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
        if request.profile_id is not None and repo.get_profile(request.profile_id) is None:
            raise HTTPException(status_code=404, detail="profile not found")

        if request.session_id is None:
            if request.plot_id is None:
                raise HTTPException(status_code=400, detail="plot_id is required to start a session")
            card = find_plot(request.plot_id)
            if card is None:
                raise HTTPException(status_code=404, detail="plot not found")
            session = repo.create_session(request.plot_id, request.profile_id)
            return turn_response(start_message(card, session), card, session, repo, "scripted")

        session = repo.get_session(request.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        if request.profile_id is not None:
            session["profile_id"] = request.profile_id
        card = find_plot(session["plot_id"])
        if card is None:
            raise HTTPException(status_code=404, detail="plot not found")

        llm_mode = "scripted"
        if request.choice_id:
            try:
                session, message, choice = apply_choice(session, card, request.choice_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            message, llm_mode = maybe_generate_llm_reply(llm, repo, card, session, choice["label"], message)
            reward = card["completion_reward"]
            repo.add_logbook_entry(session["id"], reward["title"], reward["safe_summary_template"], reward["type"])
        elif request.free_input is not None:
            session, message, summary = apply_free_input(session, card, request.free_input)
            message, llm_mode = maybe_generate_llm_reply(llm, repo, card, session, request.free_input, message)
            reward = card["completion_reward"]
            repo.add_logbook_entry(session["id"], reward["title"], summary, reward["type"])
        else:
            raise HTTPException(status_code=400, detail="choice_id or free_input is required")

        repo.update_session(session)
        return turn_response(message, card, session, repo, llm_mode)

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

    @app.post("/api/admin/plot-cards/validate")
    def validate_plot_card(request: AdminPlotValidationRequest) -> dict[str, object]:
        return validate_operator_content(request.title, request.one_line_hook)

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


def continue_summary(session: dict[str, Any] | None) -> dict[str, object] | None:

    if session is None:
        return None
    card = find_plot(str(session["plot_id"]))
    return {
        "session_id": session["id"],
        "plot_id": session["plot_id"],
        "plot_title": None if card is None else card["title"],
        "step": session["step"],
        "total_steps": session["total_steps"],
        "completed": session["completed"],
        "relationship_summary": relationship_summary(session),
    }



def active_quest_summary(session: dict[str, Any] | None) -> dict[str, object] | None:
    if session is None:
        return None
    card = find_plot(str(session["plot_id"]))
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
) -> tuple[str, str]:
    if llm is None:
        return fallback_message, "scripted"
    recent_memories = []
    profile_id = session.get("profile_id")
    if profile_id is not None:
        profile = repo.get_profile(str(profile_id))
        if profile is not None and profile["memory_controls"].get("allow_logbook_personalization", True):
            recent_memories = repo.list_recent_memory_summaries_for_session(str(session["id"]))
    try:
        return (
            llm.generate_reply(
                LlmContext(
                    plot_title=str(card["title"]),
                    member_role=str(card["member_role"]),
                    scene=str(card["opening_scene"]),
                    user_action=user_action,
                    relationship_summary=str(session["relationship"]["display_summary"]),
                    safety_events=list(session["safety_events"]),
                    recent_memories=recent_memories,
                )
            ),
            "llm",
        )
    except Exception:
        return fallback_message, "scripted_fallback"


app = create_app()
