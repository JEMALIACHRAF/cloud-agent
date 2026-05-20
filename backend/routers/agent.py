"""Agent router v2 — SSE streaming, human-in-the-loop, profile, proactive scan."""
from __future__ import annotations
import json
import os
import traceback
from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.agent import stream_agent, get_thread_history
from core.user_profile import get_profile
from core.proactive import get_scanner

router = APIRouter()


class AgentRequest(BaseModel):
    user_input:        str
    thread_id:         str = "default"
    credentials:       dict[str, str] = Field(default_factory=dict)
    profile:           str = "default"
    model:             str | None = None
    resume:            str | None = None
    openai_api_key:    str = ""
    anthropic_api_key: str = ""


def _apply_llm_keys(req: AgentRequest):
    """Temporarily set LLM keys from request if provided."""
    if req.openai_api_key:
        os.environ["OPENAI_API_KEY"] = req.openai_api_key
    if req.anthropic_api_key:
        os.environ["ANTHROPIC_API_KEY"] = req.anthropic_api_key


@router.post("/stream")
async def stream(req: AgentRequest):
    _apply_llm_keys(req)

    async def generator():
        try:
            async for event in stream_agent(
                user_input=req.user_input,
                thread_id=req.thread_id,
                credentials=req.credentials,
                profile=req.profile,
                model=req.model,
                resume_value=req.resume,
            ):
                yield f"data: {json.dumps(event, default=str)}\n\n"
        except Exception as exc:
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'run_end', 'status': 'error', 'error': str(exc)})}\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/history/{thread_id}")
async def history(thread_id: str):
    msgs = await get_thread_history(thread_id)
    return {"thread_id": thread_id, "messages": msgs}


@router.post("/resume")
async def resume(req: AgentRequest):
    _apply_llm_keys(req)

    async def generator():
        async for event in stream_agent(
            user_input="",
            thread_id=req.thread_id,
            credentials=req.credentials,
            profile=req.profile,
            model=req.model,
            resume_value=req.resume,
        ):
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@router.get("/profile/{thread_id}")
async def get_user_profile(thread_id: str):
    profile = get_profile(thread_id)
    return profile.to_dict()


@router.post("/scan")
async def trigger_scan(req: AgentRequest, background_tasks: BackgroundTasks):
    scanner = get_scanner()
    background_tasks.add_task(
        scanner.scan,
        req.credentials,
        req.credentials.get("aws_region", "us-east-1"),
    )
    return {"status": "scan_started"}


@router.get("/scan/results")
async def get_scan_results():
    scanner = get_scanner()
    result = scanner.get_cached_result()
    if not result:
        return {"alerts": [], "scanned_at": None}
    return {
        "alerts": [
            {"severity": a.severity, "category": a.category, "title": a.title,
             "detail": a.detail, "service": a.service, "region": a.region, "action": a.action}
            for a in result.alerts
        ],
        "scanned_at": result.scanned_at.isoformat(),
    }



# ── Direct tool execution endpoint (no LLM) ────────────────────────────────────
# Used by Manifest page to fetch inventory without triggering the agent
# pipeline (which would consume ~3-4 LLM calls per tool = rate-limit hell).

class ToolDirectRequest(BaseModel):
    tool_name:   str
    credentials: dict[str, str] = Field(default_factory=dict)
    args:        dict[str, str] = Field(default_factory=dict)
    profile:     str = "default"


@router.post("/tool")
async def execute_tool_direct(req: ToolDirectRequest):
    """
    Execute an AWS tool DIRECTLY without going through the LLM agent.
    Returns the raw JSON result. No tokens consumed.
    Intended for inventory / dashboard use-cases.
    """
    from core.session import set_session
    from core.agent import ALL_TOOLS

    set_session(req.credentials, req.profile)

    tool = next((t for t in ALL_TOOLS if t.name == req.tool_name), None)
    if not tool:
        return {"error": f"Tool '{req.tool_name}' not found",
                "available": [t.name for t in ALL_TOOLS[:30]]}

    try:
        # All our tools are async via @tool decorator
        result = await tool.ainvoke(req.args or {})
        return {"tool": req.tool_name, "result": result, "ok": True}
    except Exception as e:
        return {"tool": req.tool_name, "error": str(e), "ok": False}
