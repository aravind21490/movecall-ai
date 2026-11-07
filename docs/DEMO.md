# 2:30 demo video script

Record the screen plus the phone's call audio (or the laptop speaker). Do a backup take.

**0:00 Problem (15 s)**
"Small moving companies miss calls and lose leads. But you cannot let an AI quote prices
or promise dates. MoveCall AI captures the lead and lets people decide."

**0:15 The call (60 s)**
Place the call. Show the terminal log on the left. Say: Ravi Kumar, Uppal to Gachibowli,
2BHK, around the 20th, upright piano, evening callback. Ask "how much will it cost?" and
"can you confirm the 20th?" to show it refuses both. Let it read back and say goodbye.

**1:15 Switch (60 s)**
Cut to Mattermost / Switch Console, the `movecall-leads` room.
- The lead appears with the CALLER-PROVIDED DATA block.
- `@movecall-reviewer` replies: summary, missing fields, piano flagged.
- It hands off to `@movecall-scripter`, which writes the callback script.
- Reply `approve #1` as the human owner.
Say: "Switch is what makes this safe. Two agents prepare the work, a human approves."

**2:15 Safety + close (15 s)**
Run `python simulate_lead.py --evil`. Show the injection text sitting inside the data block
and the agents ignoring it. "Built with Switch, Twilio, OpenAI Realtime and FastAPI."

Submission checklist: public repo (no `.env`, no `.db`), README, video link, #HowISwitch post.
