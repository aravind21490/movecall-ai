"""MoveCall AI: a phone call becomes a lead, and the lead goes to a Switch room.

Twilio (phone) <-> this server <-> OpenAI Realtime (voice model)
After save_lead: lead -> SQLite -> Switch room (reviewer + scripter agents) -> human.

Run:  uvicorn server:app --port 5050
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from xml.sax.saxutils import quoteattr

import websockets
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

import leads
from prompts import GREETING_PROMPT, SAVE_LEAD_TOOL, SYSTEM_MESSAGE
from switch_handoff import post_lead_to_room

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("movecall")

MODEL = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime")
VOICE = os.getenv("OPENAI_VOICE", "alloy")
OPENAI_URL = os.getenv("OPENAI_REALTIME_URL", f"wss://api.openai.com/v1/realtime?model={MODEL}")

app = FastAPI(title="MoveCall AI")
leads.init_db()


def session_update() -> dict:
    return {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "model": MODEL,
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcmu"},
                    "turn_detection": {"type": "server_vad"},
                },
                "output": {"format": {"type": "audio/pcmu"}, "voice": VOICE},
            },
            "instructions": SYSTEM_MESSAGE,
            "tools": [SAVE_LEAD_TOOL],
            "tool_choice": "auto",
        },
    }


@app.get("/health")
async def health():
    return {"ok": True, "switch_mode": os.getenv("SWITCH_POST_MODE", "console")}


@app.api_route("/incoming-call", methods=["GET", "POST"])
async def incoming_call(request: Request):
    """Twilio hits this when someone dials the number. Reply with TwiML."""
    caller = ""
    if request.method == "POST":
        try:
            form = await request.form()
            caller = str(form.get("From", ""))
        except Exception:  # noqa: BLE001
            caller = ""
    host = os.getenv("PUBLIC_HOST") or request.headers.get("host") or request.url.netloc
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response><Connect>"
        f"<Stream url={quoteattr('wss://' + host + '/media-stream')}>"
        f"<Parameter name=\"from\" value={quoteattr(caller)}/>"
        "</Stream></Connect></Response>"
    )
    return Response(content=xml, media_type="application/xml")


@app.websocket("/media-stream")
async def media_stream(twilio: WebSocket):
    await twilio.accept()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        log.error("OPENAI_API_KEY is not set; closing the call")
        await twilio.close()
        return

    state = {"stream_sid": None, "caller": "", "saved_lead": None}

    async with websockets.connect(
        OPENAI_URL, additional_headers={"Authorization": f"Bearer {api_key}"}
    ) as oai:
        await oai.send(json.dumps(session_update()))

        async def send_oai(payload: dict) -> None:
            await oai.send(json.dumps(payload))

        async def speak(prompt: str) -> None:
            await send_oai(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": prompt}],
                    },
                }
            )
            await send_oai({"type": "response.create"})

        async def from_twilio() -> None:
            try:
                async for raw in twilio.iter_text():
                    data = json.loads(raw)
                    event = data.get("event")
                    if event == "media" and oai.state.name == "OPEN":
                        await send_oai(
                            {"type": "input_audio_buffer.append", "audio": data["media"]["payload"]}
                        )
                    elif event == "start":
                        start = data["start"]
                        state["stream_sid"] = start["streamSid"]
                        state["caller"] = (start.get("customParameters") or {}).get("from", "")
                        log.info("call started (stream %s)", state["stream_sid"])
                        await speak(GREETING_PROMPT)
                    elif event == "stop":
                        log.info("call ended by caller")
                        break
            except WebSocketDisconnect:
                log.info("twilio socket closed")

        async def handle_tool_call(event: dict) -> None:
            if event.get("name") != "save_lead":
                output = {"ok": False, "error": "unknown tool"}
            elif state["saved_lead"]:
                output = {"ok": True, "lead_id": state["saved_lead"]["id"], "note": "already saved"}
            else:
                try:
                    args = json.loads(event.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                if not args.get("callback_number") and state["caller"]:
                    args["callback_number"] = state["caller"]
                lead = await asyncio.to_thread(leads.save_lead, args)
                state["saved_lead"] = lead
                log.info("lead #%s saved (%s)", lead["id"], lead["status"])
                # Fire and forget: a chat outage must never affect the call.
                asyncio.get_running_loop().run_in_executor(None, post_lead_to_room, lead)
                output = {
                    "ok": True,
                    "lead_id": lead["id"],
                    "instruction": (
                        "Tell the caller a team member will call them back. "
                        "Do not mention prices. Do not confirm any date or booking. Say goodbye."
                    ),
                }
            await send_oai(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": event.get("call_id"),
                        "output": json.dumps(output),
                    },
                }
            )
            await send_oai({"type": "response.create"})

        async def to_twilio() -> None:
            async for raw in oai:
                event = json.loads(raw)
                kind = event.get("type")
                try:
                    if kind == "response.output_audio.delta" and event.get("delta"):
                        if state["stream_sid"]:
                            await twilio.send_json(
                                {
                                    "event": "media",
                                    "streamSid": state["stream_sid"],
                                    "media": {"payload": event["delta"]},
                                }
                            )
                    elif kind == "input_audio_buffer.speech_started":
                        # Caller barged in: drop audio still queued at Twilio.
                        if state["stream_sid"]:
                            await twilio.send_json(
                                {"event": "clear", "streamSid": state["stream_sid"]}
                            )
                    elif kind == "response.function_call_arguments.done":
                        await handle_tool_call(event)
                    elif kind == "error":
                        log.error("OpenAI error: %s", event.get("error"))
                except WebSocketDisconnect:
                    break

        tasks = [asyncio.create_task(from_twilio()), asyncio.create_task(to_twilio())]
        try:
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
        finally:
            lead = state["saved_lead"]
            if not lead:
                log.info("call ended without a saved lead")


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    log.exception("unhandled error: %s", exc)
    return JSONResponse({"ok": False}, status_code=500)
