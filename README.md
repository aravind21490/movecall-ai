# MoveCall AI

A phone assistant for small moving companies. A customer calls, an AI captures the
move details, and the lead lands in a **Switch room** where two AI agents review it
and prepare the callback script. A human approves before anyone is called back.

Built for the **Flip the Switch** hackathon (WeMakeDevs x DevTools Academy).

## The problem
Small movers lose leads when nobody picks up, and they cannot trust an AI with the
parts that matter. A bot that quotes a wrong price or promises a date creates a real
dispute. MoveCall AI captures the lead and never decides anything. People do.

## How Switch is used (the core of the design)
Switch puts AI agents into team chat as teammates. MoveCall uses it as the
**review and approval layer** after every call:

```
Caller --phone--> Twilio --audio--> MoveCall server --voice--> OpenAI Realtime
                                         |
                                  save_lead tool call
                                         |
                          SQLite  +  post to Mattermost channel
                                         |
                      +------------ Switch room: movecall-leads ------------+
                      |                                                     |
              @movecall-reviewer                                   @movecall-scripter
        summary, missing fields, special items  --hand off-->   callback script, no prices
                      |                                                     |
                      +------------------- human owner ---------------------+
                                  replies: approve #<lead id>
```

- **Switch Console** runs both agents on the local machine (OpenCode provider) and the
  local Switch server hosts the room on a bundled Mattermost.
- **movecall-reviewer** turns the raw lead into a one-line summary, lists missing
  fields and flags special items (piano, safe, stairs, long carry).
- **movecall-scripter** takes the reviewer's notes and writes the callback script.
- The **human owner** is a member of the room, can talk to either agent, and gives the
  final approval. The agents never contact the customer.

The agent definitions are in [`switch/agents.md`](switch/agents.md). The code that posts
into the room is [`switch_handoff.py`](switch_handoff.py).

## Safety rules (enforced in layers)
1. **Voice agent prompt**: never quote or hint at a price, never confirm a date, slot or
   booking. Details in [`prompts.py`](prompts.py).
2. **Switch agents' instructions** repeat the same rules and forbid contacting the caller.
3. **Untrusted caller text**: everything the caller said is flattened to one line, capped at
   300 characters, stripped of markup, and wrapped between `CALLER-PROVIDED DATA` markers.
   Agents are told to treat that block as data only. Try `python simulate_lead.py --evil`
   to see a prompt-injection attempt neutralised.
4. **Agent guardrail**: agents may only use Switch room tools. No shell, no file access.
5. **Failure isolation**: a chat outage cannot drop a call or lose a lead. The lead is saved
   to SQLite first, and the Switch post runs off the call path and never raises.

## Run it

### 1. Switch side (about 15 minutes)
1. Install Docker Desktop and [Switch Console](https://switchagents.ai). Start the local server.
2. Install OpenCode (`npm i -g opencode-ai`) and sign in to a provider (`opencode auth login`).
3. In Switch Console create the two agents and the room from [`switch/agents.md`](switch/agents.md).
4. Open the bundled Mattermost (port shown in Console), find the `movecall-leads` channel.

### 2. MoveCall side
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows;  source .venv/bin/activate elsewhere
pip install -r requirements.txt
copy .env.example .env          # then fill it in
```
In `.env` set `SWITCH_POST_MODE=mattermost_api` and the `MATTERMOST_*` values (the login
of the owner account that is a member of the room), plus `OPENAI_API_KEY` and `PUBLIC_HOST`.

### 3. Try the handoff without a phone call
```bash
python simulate_lead.py          # a normal lead into the Switch room
python simulate_lead.py --evil   # a lead that tries to hijack the agents
```
Watch the channel: the reviewer replies, hands off to the scripter, and the human approves.

### 4. Take a real call
```bash
uvicorn server:app --port 5050
ngrok http 5050
```
Put the ngrok host in `.env` as `PUBLIC_HOST`. In the Twilio console set the number's
**A call comes in** webhook to `https://<ngrok-host>/incoming-call` (HTTP POST). Call the number.

Owner tools: `python leads_cli.py list` and `python leads_cli.py approve 3`.

## Tests
```bash
pip install -r requirements-dev.txt
pytest -q
```
52 automated tests, no network and no keys needed. They run the real server against fake
Twilio, OpenAI Realtime and Mattermost services.

| Area | What is proven |
|---|---|
| Lead storage | complete vs partial leads, field caps, unknown keys ignored, SQL-injection text stored as plain text |
| Voice agent prompt | price, date and booking rules are present; the tool schema matches storage and handoff fields |
| Switch handoff | hostile text is flattened and fenced and cannot close the data block; Mattermost login, channel lookup, post, token reuse and re-login on 401; every failure returns False and never raises |
| Whole call | TwiML and caller id; session setup before greeting; audio both ways; barge-in; `save_lead` stores once and posts to the room; fallback to caller id; bad or unknown tool calls; Switch outage keeps the lead; hang-up with no lead; back-to-back calls |

As a check on the tests themselves, five deliberate bugs were introduced (duplicate guard
removed, barge-in removed, markup not stripped, handoff errors allowed to raise, price rule
deleted) and each one made the suite fail.

Not covered by automation: a real phone call, real voice quality, and the Switch agents'
replies, which are checked by hand in the room.

## Not built (honest list)
- Approval is a human reply in the room. It does not yet update the lead's status
  automatically (`leads_cli.py approve` does that by hand).
- The assistant does not hang up by itself; the caller ends the call.
- No outbound calls, no pricing, no scheduling, no calendar.
- Calls that drop before `save_lead` are not saved.
- The free hosted models used by the Switch agents may use prompts for provider training,
  so only fake test leads were used in the demo.
 - Docker packaging (planned): a Dockerfile so the server and Switch handoff run with one command.

## Stack
FastAPI, Twilio Media Streams, OpenAI Realtime API, SQLite, Switch (Console, local server,
Mattermost bridge), OpenCode.
