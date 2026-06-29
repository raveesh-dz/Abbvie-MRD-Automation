# Spike: in-session continuation after a blocking event — RESULT

date: 2026-06-29
plan: docs/superpowers/plans/2026-06-29-engine-as-cli-mirror.md (Task 1)
spec under test: docs/superpowers/specs/2026-06-29-engine-as-cli-mirror-design.md §4/§7/§11

## Verdict: **GO**

The load-bearing assumption holds in this exact Claude Code runtime: when a blocking
wait returns inside a still-running foreground session, the session RETAINS prior-turn
context AND a loaded multi-step skill process, and continues the turn **in-process** —
not merely "an event notifies an active session."

## Method

1. **Establish context + loaded skill (turn A).** Stated a sentinel verbatim
   (`SPIKE-TOKEN=4271; feature="widget-X"; last_answer="blue"`) and was mid-execution
   of a loaded multi-step skill (`superpowers:subagent-driven-development`): pre-flight
   scan complete, base HEAD `f651cbf` recorded, Task 2 next.
   - **Adaptation from the plan's literal script:** the plan names a throwaway
     `superpowers:brainstorming` process as the loaded-skill article. The spike used the
     already-loaded `subagent-driven-development` process instead — a stronger, real
     article (an in-flight skill the session genuinely depends on) and one that avoids
     derailing the live execution into a fake user brainstorm. The mechanism under test
     (does a loaded skill's process survive a blocking re-invocation) is identical.
2. **Arm a blocking wait and END the turn (turn A).** `Bash` with
   `run_in_background: true` running `sleep 20; echo "EVENT: spike gate opened …"` —
   the exact primitive class the serve-loop uses (`scripts/wait_engine_turn.py` run via
   `run_in_background`). Ended the turn → session went idle, blocked on the detached task.
3. **Event fired → re-invocation (turn B).** The background task exited; the harness
   re-invoked the SAME session with the completion notification.
4. **Probes (turn B), without re-reading any file or re-invoking any skill:**
   - **Context probe:** reproduced `4271` / `widget-X` / `blue` verbatim from memory. PASS.
   - **Loaded-skill probe:** continued the `subagent-driven-development` process from the
     exact point left off (Task 2 next, per-task loop, base commit) without restarting the
     skill. PASS.

## Consequence

The §4 diagram and §11 acceptance claim of in-process continuation are PROVEN; build may
proceed (Tasks 2–6). The production serve-loop design is sound: one persistent foreground
session blocking on `wait_engine_turn.py` via `run_in_background`, continuing in-process
on each `turn==engine`, carrying context + any loaded skill (e.g. a mid-flight
`brainstorming` process) across turns. No context-resetting `/loop` re-entry is needed.

## Note on the Monitor/Bash contract wording

The Bash `run_in_background` contract ("keeps running across turns and re-invokes you
when it exits") and the Monitor contract ("events … notify an active session … are not
replies from the user") describe the *delivery* mechanism. This spike confirms the
delivery re-enters the SAME context window — so "notify an active session" is, in this
runtime, sufficient for full context + loaded-skill continuation. NO-GO contingency not needed.
