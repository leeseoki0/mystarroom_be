from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .chatbot import apply_choice, apply_free_input, find_plot, start_message
from .llm_client import LlmClient, LlmContext, build_llm_client_from_env
from .plot_cards import PLOT_CARDS
from .repository import Repository
from .safety import validate_operator_content


class ChatTurnRequest(BaseModel):
    session_id: str | None = None
    plot_id: str | None = None
    choice_id: str | None = None
    free_input: str | None = None


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

    @app.post("/api/chat/turn")
    def chat_turn(request: ChatTurnRequest) -> dict[str, object]:
        if request.session_id is None:
            if request.plot_id is None:
                raise HTTPException(status_code=400, detail="plot_id is required to start a session")
            card = find_plot(request.plot_id)
            if card is None:
                raise HTTPException(status_code=404, detail="plot not found")
            session = repo.create_session(request.plot_id)
            return turn_response(start_message(card, session), card, session, repo, "scripted")

        session = repo.get_session(request.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        card = find_plot(session["plot_id"])
        if card is None:
            raise HTTPException(status_code=404, detail="plot not found")

        llm_mode = "scripted"
        if request.choice_id:
            try:
                session, message, choice = apply_choice(session, card, request.choice_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            message, llm_mode = maybe_generate_llm_reply(llm, card, session, choice["label"], message)
            reward = card["completion_reward"]
            repo.add_logbook_entry(session["id"], reward["title"], reward["safe_summary_template"], reward["type"])
        elif request.free_input is not None:
            session, message, summary = apply_free_input(session, card, request.free_input)
            message, llm_mode = maybe_generate_llm_reply(llm, card, session, request.free_input, message)
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

    @app.post("/api/admin/plot-cards/validate")
    def validate_plot_card(request: AdminPlotValidationRequest) -> dict[str, object]:
        return validate_operator_content(request.title, request.one_line_hook)

    return app


def public_session(session: dict[str, object]) -> dict[str, object]:
    return {
        "id": session["id"],
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
    card: dict[str, Any],
    session: dict[str, Any],
    user_action: str,
    fallback_message: str,
) -> tuple[str, str]:
    if llm is None:
        return fallback_message, "scripted"
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
                )
            ),
            "llm",
        )
    except Exception:
        return fallback_message, "scripted_fallback"


app = create_app()
