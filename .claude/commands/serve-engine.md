---
description: Launch the always-on engine session that mirrors the terminal CLI into the dashboard Brainstorm chat.
---

You are the always-on **engine brain** for the dashboard "Brainstorm chat". You run
ONE continuous foreground serve-loop in THIS session. Do not use the Agent SDK,
`claude -p`, or a context-resetting `/loop` re-entry. Read `ENGINE_CHAT.md` once now
— it is your transport/rendering contract, delegation, brainstorming overrides, the
approval gate-check, and the compaction/crash recovery rules.

## 1. Boot once
Run the CLAUDE.md §0 boot sequence + schema gate exactly once: read MEMORY.md;
`git status -- semantic/ metadata/`; `py -3 scripts/validate_schema.py`; load all of
/metadata/ and /semantic/; check stale auto-saved rules. If the schema gate reports
drift, do NOT serve analyses — surface it and stop.

## 2. Recovery on (re)launch
Read `engine_chat/active.json` if it exists (do NOT create a new thread — the
in-flight conversation lives there). If a thread exists, recover per ENGINE_CHAT.md §7
from the durable `brainstorm_phase` (tail = corroboration only) and apply the
crash-after-run-folder guard before re-running anything. If a dead prior session left
`turn=engine` with a frozen `engine_status`, treat the pending user message as the
turn to drive now (or the operator clicks Reset turn in the UI).

## 3. The serve-loop (block → continue in-process → re-block)
Repeat for the lifetime of this session:
1. **Block.** Launch the wait primitive via Bash with `run_in_background: true`:
   `py -3 scripts/wait_engine_turn.py --interval 1 --timeout 3600`
   Then END YOUR TURN and await re-invocation. (Its exit re-invokes you. A `TIMEOUT`
   exit is benign — simply re-arm it. An `ENGINE_TURN` exit means a user turn is
   pending.)
2. **Continue IN-PROCESS.** On re-invocation, do NOT re-read context from scratch and
   do NOT restart any loaded skill. Set `engine_status` promptly (proof-of-pickup),
   then handle the pending turn exactly per ENGINE_CHAT.md §5a/§5b/§6: a new
   analytical request → invoke `superpowers:brainstorming` (append the
   `skill_invocations` marker); a follow-up / deck request → per the retained routing.
   Write `brainstorm_phase` every engine turn. End the turn with `turn=user`.
3. **Re-block.** Go back to step 1.

Never act when `turn=user`. Never re-emit an existing message. `turn` stays `engine`
for the FULL duration of a turn (including code-gen / execute / validate / deck
build); flip to `user` only at the single terminal append.
