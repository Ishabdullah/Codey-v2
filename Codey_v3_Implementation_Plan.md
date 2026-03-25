+:---------------------------------------------------------------:+
| **CODEY**                                                       |
|                                                                 |
| **VERSION 3.0**                                                 |
|                                                                 |
| Implementation Plan                                             |
|                                                                 |
| *Pocket Dev Team Orchestrator*                                  |
|                                                                 |
| Evolving Codey-v2.6.9 into a full multi-agent project           |
| management system                                               |
+-----------------------------------------------------------------+

+:------------:+:------------:+:-----------------:+:----------------:+
| **6 Phases** | **4 Core     | **3 Routing       | **True           |
|              | Systems**    | Modes**           | Parallelism**    |
| Complete     |              |                   |                  |
| build path   | New          | Best/Balanced/Eco | Multi-project    |
|              | architecture |                   | queue            |
+--------------+--------------+-------------------+------------------+

**Built on:** Codey-v2.6.9 (Ishabdullah/Codey-v2) \| **Platform:**
Android / Termux / S24 Ultra

**1. Vision & Core Philosophy**

Codey-v3 is not a coder. It is a project manager. The peers (Claude
Code, Gemini CLI, Qwen CLI) are the coders. This distinction drives
every architectural decision in this document.

  --------------------- --------------------------------------------
  **CODEY-V3 OWNS**     THE PEERS DO

  Project registry &    Write code, tests, documentation
  context               

  Living outline (the   Refactor and debug
  spec)                 

  Global task queue     Architecture analysis and planning

  Routing decisions     Code generation and boilerplate

  Review gates          Security review
  (pass/fail)           

  Conflict detection vs Heavy generation tasks
  outline               

  User notifications    Anything above local 7B capability
  --------------------- --------------------------------------------

+-----------------------------------------------------------------+
| **Core Rule**                                                   |
|                                                                 |
| One peer per project at a time. Multiple projects can run       |
| simultaneously on different peers. No two peers touch the same  |
| codebase concurrently --- no merge conflicts, no lost context.  |
+-----------------------------------------------------------------+

**1.1 What Codey-v3 Feels Like to Use**

You tell Codey: \"Start a new gaming app like Candy Crush for Android.\"
Codey creates the project, builds the outline, generates a task list
(consulting peers if needed), then silently begins routing tasks to the
right peers in the background --- keeping multiple projects moving
simultaneously. When you come back and ask \"Where are we with the
gaming app?\" Codey tells you exactly what has been done, what is
running now, and what is next.

You never switch tools. You never manually hand off work. Codey handles
everything behind one interface.

**2. System Architecture**

**2.1 High-Level Diagram**

+---------------------------------------------------------------------+
| ┌─────────────────────────────────────────────────────────────────┐ |
|                                                                     |
| │ USER (codey2 CLI) │                                               |
|                                                                     |
| │ \"start gaming app\" /team status /performance /project │         |
|                                                                     |
| └─────────────────────────┬───────────────────────────────────────┘ |
|                                                                     |
| │ Unix Socket IPC                                                   |
|                                                                     |
| ┌─────────────────────────▼───────────────────────────────────────┐ |
|                                                                     |
| │ CODEY DAEMON (codeyd2) --- Always On │                            |
|                                                                     |
| │ │                                                                 |
|                                                                     |
| │ ┌─────────────────────────────────────────────────────────┐ │     |
|                                                                     |
| │ │ TeamOrchestrator (top-level) │ │                                |
|                                                                     |
| │ │ Receives all tasks → routes → dispatches → synthesizes│ │       |
|                                                                     |
| │ └──────────┬──────────────────┬──────────────────┬────────┘ │     |
|                                                                     |
| │ │ │ │ │                                                           |
|                                                                     |
| │ ┌──────────▼──┐ ┌────────────▼──┐ ┌───────────▼──────────┐ │      |
|                                                                     |
| │ │ TeamRouter │ │ PlannerV2 │ │ ProjectRegistry │ │                |
|                                                                     |
| │ │ (task-level)│ │ draft→critique│ │ All projects, their │ │       |
|                                                                     |
| │ │ 3 modes: │ │ →refine loops │ │ outlines, history, │ │           |
|                                                                     |
| │ │ Best │ │ + subtask │ │ changelogs, who did │ │                  |
|                                                                     |
| │ │ Balanced │ │ breakdown │ │ what, peer perf │ │                  |
|                                                                     |
| │ │ Economical │ └───────────────┘ └──────────────────────┘ │       |
|                                                                     |
| │ └──────────┬──┘ │                                                 |
|                                                                     |
| │ │ │                                                               |
|                                                                     |
| │ ┌──────────▼──────────────────────────────────────────────┐ │     |
|                                                                     |
| │ │ Global Task Queue │ │                                           |
|                                                                     |
| │ │ Dependency graph · Per-project slots · Peer slots │ │           |
|                                                                     |
| │ │ Scheduler fires on: task complete / new task / peer │ │         |
|                                                                     |
| │ │ becomes idle │ │                                                |
|                                                                     |
| │ └──────────┬──────────────────────────────────────────────┘ │     |
|                                                                     |
| │ │ Dispatch │                                                      |
|                                                                     |
| │ ┌──────────▼──────────────────────────────────────────────┐ │     |
|                                                                     |
| │ │ PeerBridge │ │                                                  |
|                                                                     |
| │ │ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌──────────┐ │ │            |
|                                                                     |
| │ │ │ Claude │ │ Gemini │ │ Qwen │ │ Local │ │ │                    |
|                                                                     |
| │ │ │ Code │ │ CLI │ │ CLI │ │ 7B/1.5B │ │ │                        |
|                                                                     |
| │ │ │ busy:? │ │ busy:? │ │ busy:? │ │ busy:? │ │ │                 |
|                                                                     |
| │ │ └─────────┘ └─────────┘ └─────────┘ └──────────┘ │ │            |
|                                                                     |
| │ └──────────────────────────────────────────────────────────┘ │    |
|                                                                     |
| │ │                                                                 |
|                                                                     |
| │ ┌──────────────────────────────────────────────────────────┐ │    |
|                                                                     |
| │ │ ResultSynthesizer + ReviewGate │ │                              |
|                                                                     |
| │ │ Apply diff → static analysis → tests → outline check │ │        |
|                                                                     |
| │ │ PASS: mark done, advance queue │ │                              |
|                                                                     |
| │ │ FAIL: create fix tasks, insert into queue │ │                   |
|                                                                     |
| │ └──────────────────────────────────────────────────────────┘ │    |
|                                                                     |
| │ │                                                                 |
|                                                                     |
| │ ┌──────────────────────────────────────────────────────────┐ │    |
|                                                                     |
| │ │ Memory & State (SQLite) │ │                                     |
|                                                                     |
| │ │ 4-tier RAG · ProjectState · PeerProfiles · TaskHistory │ │      |
|                                                                     |
| │ └──────────────────────────────────────────────────────────┘ │    |
|                                                                     |
| └─────────────────────────────────────────────────────────────────┘ |
+---------------------------------------------------------------------+

**2.2 The Four Core Systems**

Every feature in Codey-v3 lives inside one of these four systems.
Understand these first and the rest follows naturally.

  --------------------- --------------------------------------------
  **SYSTEM**            WHAT IT DOES

  1\. Project Registry  Knows every project: outline, changelog,
                        file ownership, task history, what worked,
                        what failed, who did what and when. The
                        single source of truth.

  2\. Global Task Queue A dependency graph of all tasks across all
                        projects. Scheduler runs continuously ---
                        dispatches work to idle peers the moment
                        tasks become unblocked.

  3\. TeamRouter        Decides which peer gets each task based on
                        routing mode (Best / Balanced / Economical).
                        Enforces one-peer-per-project constraint.
                        Manages fallbacks.

  4\. ReviewGate        Every completed task is checked against the
                        project outline before the queue advances.
                        Pass = done. Fail = fix tasks inserted.
                        Outline conflicts = user prompt.
  --------------------- --------------------------------------------

**3. Key Design Decisions**

**3.1 One Peer Per Project --- The Core Constraint**

Two peers working on the same codebase simultaneously causes merge
conflicts and context loss. The scheduler enforces this rule
unconditionally:

+-----------------------------------------------------------------+
| active_assignments = {                                          |
|                                                                 |
| \'project_alpha\': \'claude\', \# claude owns project_alpha     |
| right now                                                       |
|                                                                 |
| \'project_beta\': \'gemini\', \# gemini owns project_beta right |
| now                                                             |
|                                                                 |
| \'project_gamma\': \'qwen\', \# qwen owns project_gamma right   |
| now                                                             |
|                                                                 |
| }                                                               |
|                                                                 |
| \# When claude finishes project_alpha task:                     |
|                                                                 |
| \# 1. Clear active_assignments\[\'project_alpha\'\]             |
|                                                                 |
| \# 2. Clear peer_status\[\'claude\'\] = \'idle\'                |
|                                                                 |
| \# 3. Scheduler immediately re-evaluates queue                  |
|                                                                 |
| \# 4. Next unblocked task for any project gets dispatched       |
+-----------------------------------------------------------------+

**3.2 The Three Routing Modes**

Set globally with /performance. Can be overridden per-project. The
scoring function changes per mode --- not just the order.

  -------------- ---------------------------- -----------------------
  **MODE**       **SCORING FORMULA**          **BEST USED WHEN**

  BEST           capability × quality_history Critical project,
                                              quality matters most,
                                              short deadline

  BALANCED       (capability × quality) ×     Long sessions, multiple
                 (1 - 0.5 × workload_penalty) projects, avoid peer
                                              fatigue

  ECONOMICAL     tier_bonus (Gemini=1.0,      Cost control. Claude as
                 Qwen=0.75, Local=0.5,        last resort only
                 Claude=0.25). Claude blocked 
                 if any other peer scores \>  
                 0.4                          
  -------------- ---------------------------- -----------------------

+-----------------------------------------------------------------+
| **Economical Mode Safety Floor**                                |
|                                                                 |
| Economical mode still enforces a minimum capability threshold   |
| of 0.4. If Gemini and Qwen both score below 0.4 on a task,      |
| Claude is used regardless of mode. Codey will log: \"Escalated  |
| task 7 to Claude --- Gemini/Qwen below threshold for security   |
| review.\"                                                       |
+-----------------------------------------------------------------+

**3.3 The Living Outline**

Every project has an outline --- not just a README. The outline has two
parts: a human-readable prose section and a machine-readable structured
section that Codey uses for conflict detection.

+-----------------------------------------------------------------+
| \# PROJECT_OUTLINE.md --- machine-readable section              |
|                                                                 |
| \## SPEC                                                        |
|                                                                 |
| entities: \[User, Session, GameBoard, Piece, Score\]            |
|                                                                 |
| endpoints: \[POST /auth/register, POST /auth/login, GET         |
| /game/state\]                                                   |
|                                                                 |
| tech_stack: \[FastAPI, PostgreSQL, Redis, React Native\]        |
|                                                                 |
| auth_method: JWT                                                |
|                                                                 |
| storage: PostgreSQL for prod, SQLite for dev                    |
|                                                                 |
| \## GOALS                                                       |
|                                                                 |
| primary: Android puzzle game similar to Candy Crush             |
|                                                                 |
| target_platform: Android 10+                                    |
|                                                                 |
| mvp_deadline: 2026-06-01                                        |
+-----------------------------------------------------------------+

When a peer returns output, Codey checks new entities, endpoints, and
tech choices against the SPEC section. Structural drift triggers a user
prompt --- never silent auto-acceptance.

**3.4 Review Gate Logic**

+-----------------------------------------------------------------+
| On task completion:                                             |
|                                                                 |
| 1\. Apply diff (dry-run first, then real apply)                 |
|                                                                 |
| 2\. Run static analysis (ruff/flake8)                           |
|                                                                 |
| 3\. Run test suite                                              |
|                                                                 |
| 4\. Check output against project outline (structural diff)      |
|                                                                 |
| PASS (all 4 green):                                             |
|                                                                 |
| → Mark task DONE                                                |
|                                                                 |
| → Git commit with agent attribution                             |
|                                                                 |
| → Update ProjectRegistry (file ownership, peer profile)         |
|                                                                 |
| → Scheduler advances queue                                      |
|                                                                 |
| FAIL (any red):                                                 |
|                                                                 |
| → Create fix task(s)                                            |
|                                                                 |
| → Insert fix tasks BEFORE next dependent task in queue          |
|                                                                 |
| → Route fix to same peer (they have context) or fallback        |
|                                                                 |
| → Original task stays PENDING until fix passes gate             |
|                                                                 |
| OUTLINE CONFLICT:                                               |
|                                                                 |
| → PAUSE project queue (do not advance)                          |
|                                                                 |
| → Notify user: \'Task 4 conflicts with outline --- update       |
| outline or redo?\'                                              |
|                                                                 |
| → Wait for user decision before continuing                      |
+-----------------------------------------------------------------+

**3.5 Wait Threshold for Blocked Projects**

If a project\'s next task is waiting for a specific peer that is busy on
another project, Codey monitors the wait time. After a configurable
threshold (default 20 minutes), it notifies the user rather than
silently stalling.

+-----------------------------------------------------------------+
| **Example Notification**                                        |
|                                                                 |
| Project \'gaming-app\' has been waiting 22 minutes for Claude   |
| (currently working on \'startup-api\'). Route gaming-app task   |
| to Gemini instead? \[y/n/wait\]                                 |
+-----------------------------------------------------------------+

**4. File Structure --- New vs Modified**

**4.1 New Files (v3 Additions)**

  ---------------------------- --------------------------------------------
  **FILE**                     PURPOSE

  core/project_registry.py     ProjectRegistry class. All project context:
                               outline, changelog, task history, file
                               ownership, peer performance per project.

  core/team_router.py          Task-level router (NOT the model router).
                               Implements Best/Balanced/Economical scoring.
                               Enforces one-peer-per-project.

  core/team_orchestrator.py    Top-level workflow manager. Entry point for
                               all user tasks. Calls registry → planner →
                               router → bridge → synthesizer.

  core/global_queue.py         Dependency graph task queue. Async scheduler
                               loop. Dispatches when: task completes, peer
                               goes idle, new task arrives.

  core/peer_bridge.py          Refactored peer_cli.py. Typed HandoffPayload
                               out, PeerResult in. Secret redaction,
                               timeout enforcement, output parsing.

  core/review_gate.py          Pass/fail gate for every completed task.
                               Runs diff → static analysis → tests →
                               outline check. Creates fix tasks on failure.

  core/result_synthesizer.py   Applies peer output to filesystem. Validates
                               scope, runs gate, commits with attribution,
                               updates registry.

  core/handoff.py              Dataclasses only: HandoffPayload,
                               PeerResult, RoutingDecision,
                               SynthesisOutcome.
  ---------------------------- --------------------------------------------

**4.2 Modified Files**

  -------------------------- --------------------------------------------
  **FILE**                   CHANGES NEEDED

  core/planner_v2.py         Accept ProjectRegistry context when
                             decomposing. Emit structured subtasks with
                             peer hints.

  core/state.py              Add tables: project_registry,
                             peer_performance, task_history,
                             project_queue.

  core/memory_v2.py          Inject ProjectRegistry summary into RAG
                             context for every prompt.

  core/daemon.py             Register new commands: /team, /project,
                             /performance, /route, /peer.

  prompts/system_prompt.py   Inject project context summary header into
                             every local model prompt.

  utils/config.py            Add TEAM_CONFIG, ROUTING_CONFIG,
                             QUEUE_CONFIG blocks.
  -------------------------- --------------------------------------------

**5. Implementation Plan**

Six phases. Each phase leaves Codey fully functional --- nothing breaks
between phases. Build and test each phase before starting the next.

+-----------------------------------------------------------------+
| **Before You Start**                                            |
|                                                                 |
| Create a git branch: git checkout -b v3-dev from your v2.6.9    |
| tag. Each phase gets its own commit. This way you can always    |
| roll back to a working state.                                   |
+-----------------------------------------------------------------+

+-----------------------------------------------------------------+
| **PHASE 1**                                                     |
|                                                                 |
| **Foundation --- Project Registry**                             |
|                                                                 |
| Build the single source of truth before anything else. No       |
| routing, no queue, no peers yet.                                |
+-----------------------------------------------------------------+

Everything in v3 depends on the Project Registry. Build it first, get it
solid, then build everything else on top of it. This phase adds zero
user-facing features --- it just ensures Codey knows what project it is
working on.

  --------- -------------------------------------------------------------
   **1.1**  **Create core/handoff.py --- Dataclasses Only**

  --------- -------------------------------------------------------------

This file contains only dataclass definitions. No logic. It is imported
by everything else so it must exist first.

+-----------------------------------------------------------------+
| \# core/handoff.py                                              |
|                                                                 |
| from dataclasses import dataclass, field                        |
|                                                                 |
| from typing import Optional                                     |
|                                                                 |
| \@dataclass                                                     |
|                                                                 |
| class HandoffPayload:                                           |
|                                                                 |
| task_id: str                                                    |
|                                                                 |
| subtask_description: str                                        |
|                                                                 |
| expected_output_format: str \# \'unified_diff\' \|              |
| \'new_files\' \|                                                |
|                                                                 |
| \# \'analysis_report\' \| \'free_text\'                         |
|                                                                 |
| relevant_files: list                                            |
|                                                                 |
| project_state_summary: str                                      |
|                                                                 |
| files_to_modify: list                                           |
|                                                                 |
| files_to_read_only: list                                        |
|                                                                 |
| forbidden_patterns: list                                        |
|                                                                 |
| max_output_tokens: int                                          |
|                                                                 |
| requested_peer: str                                             |
|                                                                 |
| fallback_peer: Optional\[str\]                                  |
|                                                                 |
| parent_task_id: str                                             |
|                                                                 |
| timeout_sec: int                                                |
|                                                                 |
| \@dataclass                                                     |
|                                                                 |
| class PeerResult:                                               |
|                                                                 |
| task_id: str                                                    |
|                                                                 |
| peer_name: str                                                  |
|                                                                 |
| success: bool                                                   |
|                                                                 |
| output_format: str                                              |
|                                                                 |
| unified_diff: Optional\[str\] = None                            |
|                                                                 |
| new_files: list = field(default_factory=list)                   |
|                                                                 |
| analysis_text: Optional\[str\] = None                           |
|                                                                 |
| commit_message: Optional\[str\] = None                          |
|                                                                 |
| self_assessed_confidence: float = 0.0                           |
|                                                                 |
| files_actually_modified: list = field(default_factory=list)     |
|                                                                 |
| latency_sec: float = 0.0                                        |
|                                                                 |
| exit_code: int = 0                                              |
|                                                                 |
| error_message: Optional\[str\] = None                           |
|                                                                 |
| \@dataclass                                                     |
|                                                                 |
| class RoutingDecision:                                          |
|                                                                 |
| target: str                                                     |
|                                                                 |
| fallback: Optional\[str\]                                       |
|                                                                 |
| confidence: float                                               |
|                                                                 |
| reason: str                                                     |
|                                                                 |
| complexity_score: float                                         |
|                                                                 |
| tags: list                                                      |
+-----------------------------------------------------------------+

  --------- -------------------------------------------------------------
   **1.2**  **Create core/project_registry.py --- The Source of Truth**

  --------- -------------------------------------------------------------

This is the most important file in v3. Build it carefully. It must
handle both new projects (bootstrap) and existing projects (load and
continue).

**ProjectRegistry Dataclass**

+-----------------------------------------------------------------+
| \# core/project_registry.py                                     |
|                                                                 |
| from dataclasses import dataclass, field                        |
|                                                                 |
| from datetime import datetime                                   |
|                                                                 |
| from typing import Optional                                     |
|                                                                 |
| import json, sqlite3                                            |
|                                                                 |
| from pathlib import Path                                        |
|                                                                 |
| \@dataclass                                                     |
|                                                                 |
| class ProjectOutline:                                           |
|                                                                 |
| \# Human-readable                                               |
|                                                                 |
| description: str                                                |
|                                                                 |
| goals: str                                                      |
|                                                                 |
| target_platform: str                                            |
|                                                                 |
| \# Machine-readable (for conflict detection)                    |
|                                                                 |
| entities: list \# key data models                               |
|                                                                 |
| endpoints: list \# API routes                                   |
|                                                                 |
| tech_stack: list                                                |
|                                                                 |
| auth_method: str                                                |
|                                                                 |
| storage: str                                                    |
|                                                                 |
| mvp_deadline: str                                               |
|                                                                 |
| \@dataclass                                                     |
|                                                                 |
| class ProjectRecord:                                            |
|                                                                 |
| \# Identity                                                     |
|                                                                 |
| project_id: str \# slug, e.g. \'gaming-app\'                    |
|                                                                 |
| display_name: str                                               |
|                                                                 |
| root_path: str                                                  |
|                                                                 |
| created_at: str                                                 |
|                                                                 |
| last_active: str                                                |
|                                                                 |
| \# The spec                                                     |
|                                                                 |
| outline: ProjectOutline                                         |
|                                                                 |
| \# History                                                      |
|                                                                 |
| architecture_decisions: list = field(default_factory=list)      |
|                                                                 |
| changelog: list = field(default_factory=list)                   |
|                                                                 |
| \# {\'task_id\', \'description\', \'agent\', \'timestamp\',     |
|                                                                 |
| \# \'result\': \'pass\'\|\'fail\', \'files_changed\'}           |
|                                                                 |
| \# Ownership                                                    |
|                                                                 |
| file_ownership: dict = field(default_factory=dict)              |
|                                                                 |
| \# {\'auth/jwt.py\': {\'agent\': \'claude\', \'modified\':      |
| \'\...\', \'count\': 3}}                                        |
|                                                                 |
| \# Routing data                                                 |
|                                                                 |
| peer_performance: dict = field(default_factory=dict)            |
|                                                                 |
| \# {\'claude\': {\'calls\':12, \'quality\':0.88,                |
| \'latency\':11.2, \'failures\':1}}                              |
|                                                                 |
| \# Queue state                                                  |
|                                                                 |
| active_peer: Optional\[str\] = None                             |
|                                                                 |
| routing_mode: str = \'best\' \# per-project override            |
|                                                                 |
| status: str = \'active\' \#                                     |
| \'active\'\|\'paused\'\|\'complete\'                            |
|                                                                 |
| schema_version: str = \'3.0\'                                   |
+-----------------------------------------------------------------+

**ProjectRegistryManager Methods**

+-----------------------------------------------------------------+
| class ProjectRegistryManager:                                   |
|                                                                 |
| def detect_or_create(self, user_request: str,                   |
|                                                                 |
| path: str) -\> ProjectRecord:                                   |
|                                                                 |
| \# 1. Check if path exists                                      |
|                                                                 |
| \# 2. If yes: scan codebase, read CODEY.md/README/changelog,    |
|                                                                 |
| \# reconstruct ProjectRecord from what exists                   |
|                                                                 |
| \# 3. If no: bootstrap empty record, create directory,          |
|                                                                 |
| \# call peer to generate outline + file structure               |
|                                                                 |
| \...                                                            |
|                                                                 |
| def load(self, project_id: str) -\> ProjectRecord: \...         |
|                                                                 |
| def save(self, record: ProjectRecord) -\> None: \...            |
|                                                                 |
| def list_projects(self) -\> list\[ProjectRecord\]: \...         |
|                                                                 |
| def to_summary(self, project_id: str,                           |
|                                                                 |
| max_chars: int = 1200) -\> str:                                 |
|                                                                 |
| \# Returns the context block injected into every prompt         |
|                                                                 |
| \...                                                            |
|                                                                 |
| def record_task_complete(self, project_id: str,                 |
|                                                                 |
| task_result: dict) -\> None: \...                               |
|                                                                 |
| def record_file_touch(self, project_id: str,                    |
|                                                                 |
| filepath: str, agent: str) -\> None: \...                       |
|                                                                 |
| def update_peer_performance(self, project_id: str,              |
|                                                                 |
| peer: str, quality: float,                                      |
|                                                                 |
| latency: float,                                                 |
|                                                                 |
| success: bool) -\> None: \...                                   |
|                                                                 |
| def check_outline_conflict(self, project_id: str,               |
|                                                                 |
| peer_output: str) -\> list\[str\]:                              |
|                                                                 |
| \# Returns list of conflict descriptions (empty = no conflict)  |
|                                                                 |
| \...                                                            |
+-----------------------------------------------------------------+

**Bootstrapping a New Project**

+-----------------------------------------------------------------+
| def \_bootstrap_new_project(self, name: str, description: str,  |
|                                                                 |
| path: str) -\> ProjectRecord:                                   |
|                                                                 |
| \# 1. Create directory                                          |
|                                                                 |
| Path(path).mkdir(parents=True, exist_ok=True)                   |
|                                                                 |
| \# 2. Route to peer (Gemini preferred in Economical,            |
|                                                                 |
| \# Claude in Best) to generate:                                 |
|                                                                 |
| \# - Outline (SPEC section)                                     |
|                                                                 |
| \# - Initial file structure                                     |
|                                                                 |
| \# - Initial task list                                          |
|                                                                 |
| outline_text = self.\_get_outline_from_peer(name, description)  |
|                                                                 |
| \# 3. Parse outline into ProjectOutline dataclass               |
|                                                                 |
| outline = self.\_parse_outline(outline_text)                    |
|                                                                 |
| \# 4. Write PROJECT_OUTLINE.md to disk                          |
|                                                                 |
| \# 5. Write initial CODEY.md                                    |
|                                                                 |
| \# 6. Git init + first commit                                   |
|                                                                 |
| \# 7. Return populated ProjectRecord                            |
+-----------------------------------------------------------------+

**Scanning an Existing Project**

+-----------------------------------------------------------------+
| def \_scan_existing_project(self, path: str) -\> ProjectRecord: |
|                                                                 |
| \# 1. Read PROJECT_OUTLINE.md if exists                         |
|                                                                 |
| \# 2. Read CODEY.md if exists                                   |
|                                                                 |
| \# 3. Read git log \-- extract: who committed what when         |
|                                                                 |
| \# 4. Scan file tree for key files (requirements.txt, etc.)     |
|                                                                 |
| \# 5. Read CHANGELOG.md if exists                               |
|                                                                 |
| \# 6. Build ProjectRecord from all of the above                 |
|                                                                 |
| \# 7. If outline missing: generate it from codebase scan via    |
| peer                                                            |
+-----------------------------------------------------------------+

  --------- -------------------------------------------------------------
   **1.3**  **Extend core/state.py --- New Database Tables**

  --------- -------------------------------------------------------------

+-----------------------------------------------------------------+
| \# Add to state.py \_ensure_tables():                           |
|                                                                 |
| CREATE TABLE IF NOT EXISTS project_registry (                   |
|                                                                 |
| project_id TEXT PRIMARY KEY,                                    |
|                                                                 |
| data TEXT NOT NULL,                                             |
|                                                                 |
| updated_at TEXT NOT NULL                                        |
|                                                                 |
| );                                                              |
|                                                                 |
| CREATE TABLE IF NOT EXISTS task_history (                       |
|                                                                 |
| id INTEGER PRIMARY KEY AUTOINCREMENT,                           |
|                                                                 |
| project_id TEXT NOT NULL,                                       |
|                                                                 |
| task_id TEXT NOT NULL,                                          |
|                                                                 |
| description TEXT,                                               |
|                                                                 |
| agent TEXT,                                                     |
|                                                                 |
| result TEXT,                                                    |
|                                                                 |
| files TEXT,                                                     |
|                                                                 |
| timestamp TEXT NOT NULL                                         |
|                                                                 |
| );                                                              |
|                                                                 |
| CREATE TABLE IF NOT EXISTS project_queue (                      |
|                                                                 |
| task_id TEXT PRIMARY KEY,                                       |
|                                                                 |
| project_id TEXT NOT NULL,                                       |
|                                                                 |
| description TEXT,                                               |
|                                                                 |
| status TEXT DEFAULT \'pending\',                                |
|                                                                 |
| depends_on TEXT,                                                |
|                                                                 |
| assigned_to TEXT,                                               |
|                                                                 |
| priority INTEGER DEFAULT 5,                                     |
|                                                                 |
| created_at TEXT,                                                |
|                                                                 |
| started_at TEXT,                                                |
|                                                                 |
| completed_at TEXT                                               |
|                                                                 |
| );                                                              |
+-----------------------------------------------------------------+

  --------- -------------------------------------------------------------
   **1.4**  **Wire Registry Into Daemon Startup**

  --------- -------------------------------------------------------------

On daemon start, load the project registry. On any task, call
detect_or_create() before doing anything else. This is the only change
to daemon.py in Phase 1.

+-----------------------------------------------------------------+
| \# core/daemon.py --- add to \_\_init\_\_                       |
|                                                                 |
| from core.project_registry import ProjectRegistryManager        |
|                                                                 |
| self.registry = ProjectRegistryManager()                        |
|                                                                 |
| \# In handle_task():                                            |
|                                                                 |
| project = self.registry.detect_or_create(                       |
|                                                                 |
| user_request=task_text,                                         |
|                                                                 |
| path=inferred_path                                              |
|                                                                 |
| )                                                               |
|                                                                 |
| \# Now every task has project context before any routing        |
| happens                                                         |
+-----------------------------------------------------------------+

  --------- -------------------------------------------------------------
   **1.5**  **Test Phase 1**

  --------- -------------------------------------------------------------

Run these tests before moving to Phase 2. Do not proceed until all pass.

- Tell Codey: \'Start a new app called TestApp that is a simple todo
  list.\' Verify: directory created, PROJECT_OUTLINE.md written,
  ProjectRecord saved to SQLite.

- In a project directory you already have, tell Codey to work on it.
  Verify: git log parsed correctly, existing files detected,
  ProjectRecord populated.

- Run /project status and verify it returns meaningful output about the
  loaded project.

- Restart the daemon and verify the project loads correctly from SQLite
  on startup.

+-----------------------------------------------------------------+
| **PHASE 2**                                                     |
|                                                                 |
| **Global Task Queue & Scheduler**                               |
|                                                                 |
| The dependency graph queue and async dispatcher. Still no peers |
| --- all tasks route to local.                                   |
+-----------------------------------------------------------------+

Phase 2 builds the queue engine. By the end of this phase, Codey can
manage multi-project task lists, respect dependencies, and dispatch
tasks to local. Adding peers in Phase 3 is then just adding dispatch
targets.

  --------- -------------------------------------------------------------
   **2.1**  **Create core/global_queue.py**

  --------- -------------------------------------------------------------

**Task Model**

+-----------------------------------------------------------------+
| \# core/global_queue.py                                         |
|                                                                 |
| \@dataclass                                                     |
|                                                                 |
| class QueueTask:                                                |
|                                                                 |
| task_id: str                                                    |
|                                                                 |
| project_id: str                                                 |
|                                                                 |
| description: str                                                |
|                                                                 |
| depends_on: list\[str\] \# task_ids that must be DONE first     |
|                                                                 |
| preferred_peer: str                                             |
|                                                                 |
| fallback_peer: str                                              |
|                                                                 |
| expected_output: str \# \'unified_diff\' \| \'new_files\' \|    |
| \...                                                            |
|                                                                 |
| priority: int \# 1=highest, 10=lowest                           |
|                                                                 |
| status: str \# pending\|running\|done\|failed\|blocked          |
|                                                                 |
| assigned_to: Optional\[str\] = None                             |
|                                                                 |
| created_at: str = \...                                          |
|                                                                 |
| started_at: Optional\[str\] = None                              |
|                                                                 |
| completed_at: Optional\[str\] = None                            |
|                                                                 |
| retry_count: int = 0                                            |
+-----------------------------------------------------------------+

**Scheduler Logic**

+-----------------------------------------------------------------+
| class GlobalQueueScheduler:                                     |
|                                                                 |
| def \_\_init\_\_(self, registry, peer_bridge, config):          |
|                                                                 |
| self.queue: list\[QueueTask\] = \[\]                            |
|                                                                 |
| self.active_projects: dict\[str, str\] = {}                     |
|                                                                 |
| \# {\'project_id\': \'peer_name\'}                              |
|                                                                 |
| self.peer_status: dict\[str, str\] = {}                         |
|                                                                 |
| \# {\'claude\': \'idle\'\|\'busy\', \...}                       |
|                                                                 |
| self.wait_timers: dict\[str, float\] = {}                       |
|                                                                 |
| \# {\'project_id\': timestamp_when_started_waiting}             |
|                                                                 |
| async def tick(self):                                           |
|                                                                 |
| \"\"\"Call on: task complete, new task added, peer goes         |
| idle.\"\"\"                                                     |
|                                                                 |
| ready = self.\_get_ready_tasks()                                |
|                                                                 |
| for task in ready:                                              |
|                                                                 |
| peer = self.\_find_available_peer(task)                         |
|                                                                 |
| if peer:                                                        |
|                                                                 |
| await self.\_dispatch(task, peer)                               |
|                                                                 |
| else:                                                           |
|                                                                 |
| self.\_start_wait_timer(task)                                   |
|                                                                 |
| def \_get_ready_tasks(self) -\> list\[QueueTask\]:              |
|                                                                 |
| \"\"\"Tasks where: status=pending AND all depends_on are DONE   |
|                                                                 |
| AND project not already active\"\"\",                           |
|                                                                 |
| \...                                                            |
|                                                                 |
| def \_find_available_peer(self,                                 |
|                                                                 |
| task: QueueTask) -\> Optional\[str\]:                           |
|                                                                 |
| \# 1. Is task.preferred_peer idle?                              |
|                                                                 |
| \# 2. Is task.project_id free (no active peer)?                 |
|                                                                 |
| \# 3. If preferred busy → check fallback                        |
|                                                                 |
| \# 4. Apply routing mode scoring                                |
|                                                                 |
| \...                                                            |
|                                                                 |
| async def \_check_wait_thresholds(self):                        |
|                                                                 |
| \"\"\"Run every 60s. Notify user if project waiting \>          |
| threshold.\"\"\"                                                |
|                                                                 |
| threshold = self.config.get(\'wait_threshold_sec\', 1200)       |
|                                                                 |
| for project_id, start_time in self.wait_timers.items():         |
|                                                                 |
| if time.time() - start_time \> threshold:                       |
|                                                                 |
| self.\_notify_user_wait(project_id)                             |
+-----------------------------------------------------------------+

  --------- -------------------------------------------------------------
   **2.2**  **Create core/team_router.py**

  --------- -------------------------------------------------------------

The task-level router. Distinct from core/router.py which is the model
router (7B vs 1.5B). Do not confuse these two files.

+-----------------------------------------------------------------+
| \# core/team_router.py                                          |
|                                                                 |
| COMPLEXITY_KEYWORDS = \[                                        |
|                                                                 |
| \'authentication\', \'authorization\', \'database\',            |
| \'schema\',                                                     |
|                                                                 |
| \'migration\', \'refactor\', \'architecture\', \'security\',    |
| \'async\',                                                      |
|                                                                 |
| \'all files\', \'entire codebase\', \'performance\',            |
| \'scaling\',                                                    |
|                                                                 |
| \]                                                              |
|                                                                 |
| PEER_STRENGTH_MAP = {                                           |
|                                                                 |
| \'claude\': \[\'refactor\', \'debug\', \'security\', \'auth\',  |
| \'test\',                                                       |
|                                                                 |
| \'review\', \'explain\', \'fix\', \'optimize\', \'api\'\],      |
|                                                                 |
| \'gemini\': \[\'analyze\', \'plan\', \'architecture\',          |
| \'compare\',                                                    |
|                                                                 |
| \'document\', \'research\', \'design\', \'schema\'\],           |
|                                                                 |
| \'qwen\': \[\'generate\', \'create\', \'boilerplate\',          |
| \'template\',                                                   |
|                                                                 |
| \'complete\', \'implement\', \'scaffold\'\],                    |
|                                                                 |
| \'local\': \[\'rename\', \'move\', \'small\', \'simple\',       |
| \'git\',                                                        |
|                                                                 |
| \'status\', \'format\', \'lint\', \'update\'\],                 |
|                                                                 |
| }                                                               |
|                                                                 |
| COST_TIERS = {                                                  |
|                                                                 |
| \'gemini\': 0, \# Free tier (generous)                          |
|                                                                 |
| \'qwen\': 1, \# Free tier                                       |
|                                                                 |
| \'local\': 2, \# Free (on-device)                               |
|                                                                 |
| \'claude\': 3, \# Paid                                          |
|                                                                 |
| }                                                               |
|                                                                 |
| class TeamRouter:                                               |
|                                                                 |
| COMPLEXITY_THRESHOLD = 0.60                                     |
|                                                                 |
| ECONOMICAL_MIN_SCORE = 0.40                                     |
|                                                                 |
| def route(self, task: str, project: ProjectRecord,              |
|                                                                 |
| mode: str, online: bool,                                        |
|                                                                 |
| session_stats: dict,                                            |
|                                                                 |
| forced_peer: str = None) -\> RoutingDecision: \...              |
|                                                                 |
| def \_score_best(self, peer, task, project) -\> float:          |
|                                                                 |
| return capability_match(peer, task) \* project.peer_performance |
|                                                                 |
| .get(peer, {}).get(\'quality\', 0.7)                            |
|                                                                 |
| def \_score_balanced(self, peer, task, project,                 |
|                                                                 |
| session_stats) -\> float:                                       |
|                                                                 |
| base = self.\_score_best(peer, task, project)                   |
|                                                                 |
| workload = session_stats.get(peer, {}).get(\'tasks_done\', 0)   |
|                                                                 |
| max_work = max((s.get(\'tasks_done\', 0)                        |
|                                                                 |
| for s in session_stats.values()), default=1)                    |
|                                                                 |
| penalty = workload / (max_work + 1)                             |
|                                                                 |
| return base \* (1 - 0.5 \* penalty)                             |
|                                                                 |
| def \_score_economical(self, peer, task, project) -\> float:    |
|                                                                 |
| base = self.\_score_best(peer, task, project)                   |
|                                                                 |
| if base \< self.ECONOMICAL_MIN_SCORE and peer != \'claude\':    |
|                                                                 |
| return 0.0 \# Below floor, skip                                 |
|                                                                 |
| tier = COST_TIERS.get(peer, 3)                                  |
|                                                                 |
| tier_bonus = 1.0 - (tier \* 0.25)                               |
|                                                                 |
| return base \* tier_bonus                                       |
+-----------------------------------------------------------------+

  --------- -------------------------------------------------------------
   **2.3**  **Add /route Command (Dry-Run)**

  --------- -------------------------------------------------------------

Before wiring real dispatch, add /route so you can test routing
decisions without executing anything. Essential for debugging the
router.

+-----------------------------------------------------------------+
| \# In daemon.py handle_command():                               |
|                                                                 |
| elif cmd == \'/route\':                                         |
|                                                                 |
| task_text = args                                                |
|                                                                 |
| project = self.registry.load(self.current_project_id)           |
|                                                                 |
| decision = self.router.route(                                   |
|                                                                 |
| task=task_text, project=project,                                |
|                                                                 |
| mode=self.config\[\'routing_mode\'\],                           |
|                                                                 |
| online=self.\_check_online(),                                   |
|                                                                 |
| session_stats=self.session_stats,                               |
|                                                                 |
| )                                                               |
|                                                                 |
| return (                                                        |
|                                                                 |
| f\'Routing decision: {decision.target}\\n\'                     |
|                                                                 |
| f\' Confidence: {decision.confidence:.2f}\\n\'                  |
|                                                                 |
| f\' Reason: {decision.reason}\\n\'                              |
|                                                                 |
| f\' Complexity: {decision.complexity_score:.2f}\\n\'            |
|                                                                 |
| f\' Tags: {decision.tags}\\n\'                                  |
|                                                                 |
| f\' Fallback: {decision.fallback}\'                             |
|                                                                 |
| )                                                               |
+-----------------------------------------------------------------+

  --------- -------------------------------------------------------------
   **2.4**  **Test Phase 2**

  --------- -------------------------------------------------------------

- Create a task list for a project and verify dependencies are respected
  --- task B with depends_on=\[task_A_id\] does not dispatch until task
  A is done.

- Run /route \'add JWT authentication\' and verify it returns claude
  with appropriate tags.

- Run /route \'rename variable x to user_count in utils.py\' and verify
  it returns local with low complexity score.

- Switch routing mode to economical, run /route \'add authentication\',
  verify gemini or qwen returned first.

- Verify session stats accumulate correctly after completing several
  local tasks.

+-----------------------------------------------------------------+
| **PHASE 3**                                                     |
|                                                                 |
| **Peer Bridge & Handoff Protocol**                              |
|                                                                 |
| Connect the queue to real peer CLIs. One peer at a time ---     |
| start with Claude, then add Gemini and Qwen.                    |
+-----------------------------------------------------------------+

Do not build all three peers at once. Build Claude first, get the full
round-trip working end-to-end, then add Gemini and Qwen. Each peer is
just a different subprocess command with the same HandoffPayload input
and PeerResult output.

  --------- -------------------------------------------------------------
   **3.1**  **Create core/peer_bridge.py --- Base Class**

  --------- -------------------------------------------------------------

+-----------------------------------------------------------------+
| \# core/peer_bridge.py                                          |
|                                                                 |
| import subprocess, json, time, shutil                           |
|                                                                 |
| from core.handoff import HandoffPayload, PeerResult             |
|                                                                 |
| from utils.secret_redactor import redact_secrets                |
|                                                                 |
| class PeerBridge:                                               |
|                                                                 |
| PEER_COMMANDS = {                                               |
|                                                                 |
| \'claude\': \[\'claude\',                                       |
| \'\--dangerously-skip-permissions\'\],                          |
|                                                                 |
| \'gemini\': \[\'gemini\', \'\--yolo\'\],                        |
|                                                                 |
| \'qwen\': \[\'qwen-cli\'\],                                     |
|                                                                 |
| }                                                               |
|                                                                 |
| def is_available(self, peer: str) -\> bool:                     |
|                                                                 |
| cmd = self.PEER_COMMANDS.get(peer, \[peer\])\[0\]               |
|                                                                 |
| return shutil.which(cmd) is not None                            |
|                                                                 |
| def dispatch(self, peer: str,                                   |
|                                                                 |
| payload: HandoffPayload) -\> PeerResult:                        |
|                                                                 |
| \# 1. Redact secrets from payload                               |
|                                                                 |
| payload = self.\_redact(payload)                                |
|                                                                 |
| \# 2. Serialize to prompt string                                |
|                                                                 |
| prompt = self.\_build_prompt(payload)                           |
|                                                                 |
| \# 3. Run subprocess with timeout                               |
|                                                                 |
| start = time.time()                                             |
|                                                                 |
| try:                                                            |
|                                                                 |
| result = subprocess.run(                                        |
|                                                                 |
| self.PEER_COMMANDS\[peer\] + \[prompt\],                        |
|                                                                 |
| capture_output=True, text=True,                                 |
|                                                                 |
| timeout=payload.timeout_sec                                     |
|                                                                 |
| )                                                               |
|                                                                 |
| except subprocess.TimeoutExpired:                               |
|                                                                 |
| return PeerResult(task_id=payload.task_id,                      |
|                                                                 |
| peer_name=peer, success=False,                                  |
|                                                                 |
| output_format=\'error\',                                        |
|                                                                 |
| error_message=\'timeout\')                                      |
|                                                                 |
| \# 4. Parse \<CODEY_RESULT\> block from output                  |
|                                                                 |
| return self.\_parse_result(                                     |
|                                                                 |
| payload.task_id, peer, result, time.time() - start              |
|                                                                 |
| )                                                               |
|                                                                 |
| def \_build_prompt(self, payload: HandoffPayload) -\> str:      |
|                                                                 |
| \# Inject project context + task + file slices +                |
|                                                                 |
| \# \<CODEY_RESULT\> contract with 2-shot example                |
|                                                                 |
| \...                                                            |
|                                                                 |
| def \_parse_result(self, task_id, peer,                         |
|                                                                 |
| proc_result, latency) -\> PeerResult:                           |
|                                                                 |
| \# Find \<CODEY_RESULT\>\...\</CODEY_RESULT\> block             |
|                                                                 |
| \# Parse JSON inside it                                         |
|                                                                 |
| \# If not found: attempt heuristic extraction                   |
|                                                                 |
| \# If heuristic fails: success=False                            |
|                                                                 |
| \...                                                            |
+-----------------------------------------------------------------+

**The CODEY_RESULT Contract**

Every peer prompt must end with this instruction block and a 2-shot
example. This is what PeerBridge parses on return.

+-----------------------------------------------------------------+
| \# Appended to every peer prompt:                               |
|                                                                 |
| When you have completed the task, output ONLY this block at the |
| end:                                                            |
|                                                                 |
| \<CODEY_RESULT\>                                                |
|                                                                 |
| {                                                               |
|                                                                 |
| \"output_format\": \"unified_diff\",                            |
|                                                                 |
| \"confidence\": 0.88,                                           |
|                                                                 |
| \"commit_message\": \"feat(auth): add JWT token generation\",   |
|                                                                 |
| \"diff\": \"\-\-- a/auth/jwt.py\\n+++ b/auth/jwt.py\\n\...\"    |
|                                                                 |
| }                                                               |
|                                                                 |
| \</CODEY_RESULT\>                                               |
|                                                                 |
| output_format must be one of:                                   |
|                                                                 |
| unified_diff, new_files, analysis_report, free_text             |
|                                                                 |
| confidence is your self-assessment from 0.0 to 1.0              |
|                                                                 |
| diff field: full unified diff string if                         |
| output_format=unified_diff                                      |
|                                                                 |
| new_files field: array of {path, content} if                    |
| output_format=new_files                                         |
+-----------------------------------------------------------------+

  --------- -------------------------------------------------------------
   **3.2**  **Create core/result_synthesizer.py**

  --------- -------------------------------------------------------------

+-----------------------------------------------------------------+
| \# core/result_synthesizer.py                                   |
|                                                                 |
| class ResultSynthesizer:                                        |
|                                                                 |
| def process(self, result: PeerResult,                           |
|                                                                 |
| payload: HandoffPayload,                                        |
|                                                                 |
| project: ProjectRecord) -\> SynthesisOutcome:                   |
|                                                                 |
| if not result.success:                                          |
|                                                                 |
| return self.\_handle_failure(result, payload)                   |
|                                                                 |
| \# 1. Validate scope (peer didn\'t touch forbidden files)       |
|                                                                 |
| violations = self.\_check_scope(result, payload)                |
|                                                                 |
| if violations:                                                  |
|                                                                 |
| return SynthesisOutcome(success=False,                          |
|                                                                 |
| reason=\'scope_violation\')                                     |
|                                                                 |
| \# 2. Dry-run diff application                                  |
|                                                                 |
| if result.unified_diff:                                         |
|                                                                 |
| ok = self.\_dry_run_patch(result.unified_diff)                  |
|                                                                 |
| if not ok:                                                      |
|                                                                 |
| return SynthesisOutcome(success=False,                          |
|                                                                 |
| reason=\'patch_failed\')                                        |
|                                                                 |
| \# 3. Apply for real                                            |
|                                                                 |
| changed = self.\_apply(result)                                  |
|                                                                 |
| \# 4. Static analysis                                           |
|                                                                 |
| gate = self.\_run_static_analysis(changed)                      |
|                                                                 |
| \# 5. Test suite                                                |
|                                                                 |
| tests = self.\_run_tests()                                      |
|                                                                 |
| \# 6. Outline conflict check                                    |
|                                                                 |
| conflicts = self.registry.check_outline_conflict(               |
|                                                                 |
| project.project_id, result                                      |
|                                                                 |
| )                                                               |
|                                                                 |
| if conflicts:                                                   |
|                                                                 |
| \# PAUSE --- ask user                                           |
|                                                                 |
| self.\_notify_outline_conflict(conflicts, project)              |
|                                                                 |
| return SynthesisOutcome(success=False,                          |
|                                                                 |
| reason=\'outline_conflict\',                                    |
|                                                                 |
| conflicts=conflicts)                                            |
|                                                                 |
| if gate and tests:                                              |
|                                                                 |
| self.\_git_commit(result, payload)                              |
|                                                                 |
| self.\_update_registry(result, project, changed)                |
|                                                                 |
| return SynthesisOutcome(success=True,                           |
|                                                                 |
| files_changed=changed)                                          |
|                                                                 |
| else:                                                           |
|                                                                 |
| return SynthesisOutcome(success=False,                          |
|                                                                 |
| reason=\'gate_failed\')                                         |
+-----------------------------------------------------------------+

  --------- -------------------------------------------------------------
   **3.3**  **Create core/review_gate.py**

  --------- -------------------------------------------------------------

Separate from ResultSynthesizer. ReviewGate is called after every task
AND optionally after every milestone as a full audit.

+-----------------------------------------------------------------+
| \# core/review_gate.py                                          |
|                                                                 |
| class ReviewGate:                                               |
|                                                                 |
| def evaluate(self, task: QueueTask,                             |
|                                                                 |
| result: PeerResult,                                             |
|                                                                 |
| project: ProjectRecord) -\> GateResult:                         |
|                                                                 |
| checks = {                                                      |
|                                                                 |
| \'static_analysis\': self.\_static_analysis(result),            |
|                                                                 |
| \'tests_pass\': self.\_run_tests(project),                      |
|                                                                 |
| \'outline_match\': self.\_check_outline(result, project),       |
|                                                                 |
| \'scope_clean\': self.\_check_scope(result),                    |
|                                                                 |
| }                                                               |
|                                                                 |
| passed = all(checks.values())                                   |
|                                                                 |
| return GateResult(passed=passed, checks=checks)                 |
|                                                                 |
| def full_audit(self, project: ProjectRecord,                    |
|                                                                 |
| peer: str = None) -\> AuditResult:                              |
|                                                                 |
| \# Run after all tasks in a milestone complete                  |
|                                                                 |
| \# Optionally route to peer for deep review                     |
|                                                                 |
| \# Returns: issues found, tasks to create, overall health       |
|                                                                 |
| \...                                                            |
|                                                                 |
| def on_fail(self, task: QueueTask,                              |
|                                                                 |
| gate_result: GateResult,                                        |
|                                                                 |
| queue: GlobalQueueScheduler) -\> None:                          |
|                                                                 |
| \# Create fix tasks for each failing check                      |
|                                                                 |
| \# Insert fix tasks before next dependent task in queue         |
|                                                                 |
| fix_tasks = self.\_generate_fix_tasks(task, gate_result)        |
|                                                                 |
| for fix in fix_tasks:                                           |
|                                                                 |
| queue.insert_before_dependents(fix, task.task_id)               |
+-----------------------------------------------------------------+

  --------- -------------------------------------------------------------
   **3.4**  **Wire End-to-End: Queue → Router → Bridge → Synthesizer**

  --------- -------------------------------------------------------------

+-----------------------------------------------------------------+
| \# core/team_orchestrator.py                                    |
|                                                                 |
| class TeamOrchestrator:                                         |
|                                                                 |
| async def run_task(self, task: QueueTask) -\> None:             |
|                                                                 |
| project = self.registry.load(task.project_id)                   |
|                                                                 |
| \# 1. Build handoff payload                                     |
|                                                                 |
| rag_slice = self.memory.search(                                 |
|                                                                 |
| task.description, project_id=task.project_id                    |
|                                                                 |
| )                                                               |
|                                                                 |
| payload = HandoffPayload(                                       |
|                                                                 |
| task_id=task.task_id,                                           |
|                                                                 |
| subtask_description=task.description,                           |
|                                                                 |
| project_state_summary=self.registry.to_summary(                 |
|                                                                 |
| task.project_id                                                 |
|                                                                 |
| ),                                                              |
|                                                                 |
| relevant_files=rag_slice,                                       |
|                                                                 |
| requested_peer=task.assigned_to,                                |
|                                                                 |
| \...)                                                           |
|                                                                 |
| \# 2. Dispatch                                                  |
|                                                                 |
| result = self.peer_bridge.dispatch(                             |
|                                                                 |
| task.assigned_to, payload                                       |
|                                                                 |
| )                                                               |
|                                                                 |
| \# 3. Synthesize                                                |
|                                                                 |
| outcome = self.synthesizer.process(                             |
|                                                                 |
| result, payload, project                                        |
|                                                                 |
| )                                                               |
|                                                                 |
| \# 4. Gate                                                      |
|                                                                 |
| gate = self.review_gate.evaluate(                               |
|                                                                 |
| task, result, project                                           |
|                                                                 |
| )                                                               |
|                                                                 |
| if gate.passed:                                                 |
|                                                                 |
| self.queue.mark_done(task.task_id)                              |
|                                                                 |
| \# Scheduler.tick() fires automatically                         |
|                                                                 |
| else:                                                           |
|                                                                 |
| self.review_gate.on_fail(task, gate, self.queue)                |
+-----------------------------------------------------------------+

  --------- -------------------------------------------------------------
   **3.5**  **Test Phase 3**

  --------- -------------------------------------------------------------

- Dispatch a simple task to Claude. Verify PeerResult is parsed
  correctly from the CODEY_RESULT block.

- Intentionally return a malformed result (no CODEY_RESULT block).
  Verify heuristic extraction or graceful failure --- never a crash.

- Verify dry-run patch runs before real apply. Break the patch
  intentionally and confirm the filesystem is not touched.

- Verify a failing test triggers fix task creation and insertion into
  the queue.

- Run a full task → gate pass → git commit. Check git log shows agent
  attribution in commit message.

+-----------------------------------------------------------------+
| **PHASE 4**                                                     |
|                                                                 |
| **Multi-Project Parallelism**                                   |
|                                                                 |
| Multiple projects running on different peers simultaneously.    |
| The one-peer-per-project constraint. True parallel dispatch.    |
+-----------------------------------------------------------------+

  --------- -------------------------------------------------------------
   **4.1**  **Enforce One-Peer-Per-Project in Scheduler**

  --------- -------------------------------------------------------------

+-----------------------------------------------------------------+
| \# core/global_queue.py --- add to \_find_available_peer()      |
|                                                                 |
| def \_find_available_peer(self, task: QueueTask) -\>            |
| Optional\[str\]:                                                |
|                                                                 |
| \# RULE 1: Is this project already being worked on?             |
|                                                                 |
| if task.project_id in self.active_projects:                     |
|                                                                 |
| return None \# Project slot occupied --- wait                   |
|                                                                 |
| \# RULE 2: Try preferred peer                                   |
|                                                                 |
| if self.peer_status.get(task.preferred_peer) == \'idle\':       |
|                                                                 |
| return task.preferred_peer                                      |
|                                                                 |
| \# RULE 3: Try fallback peer                                    |
|                                                                 |
| if (task.fallback_peer and                                      |
|                                                                 |
| self.peer_status.get(task.fallback_peer) == \'idle\'):          |
|                                                                 |
| return task.fallback_peer                                       |
|                                                                 |
| \# RULE 4: All suitable peers busy --- start wait timer         |
|                                                                 |
| return None                                                     |
|                                                                 |
| def \_on_task_complete(self, task: QueueTask) -\> None:         |
|                                                                 |
| \# Release BOTH slots simultaneously                            |
|                                                                 |
| del self.active_projects\[task.project_id\]                     |
|                                                                 |
| self.peer_status\[task.assigned_to\] = \'idle\'                 |
|                                                                 |
| \# Clear wait timer if set                                      |
|                                                                 |
| self.wait_timers.pop(task.project_id, None)                     |
|                                                                 |
| \# Immediately re-evaluate                                      |
|                                                                 |
| asyncio.create_task(self.tick())                                |
+-----------------------------------------------------------------+

  --------- -------------------------------------------------------------
   **4.2**  **Add Project Switching**

  --------- -------------------------------------------------------------

When the user gives Codey work on a different project mid-session, it
should load that project\'s context, add the tasks to the global queue
under that project_id, and the scheduler handles interleaving
automatically.

+-----------------------------------------------------------------+
| \# In daemon.py handle_task():                                  |
|                                                                 |
| def handle_task(self, task_text: str) -\> str:                  |
|                                                                 |
| \# 1. Detect which project this is for                          |
|                                                                 |
| project = self.registry.detect_or_create(task_text, \...)       |
|                                                                 |
| \# 2. Load project context into working memory                  |
|                                                                 |
| self.memory.load_project(project.project_id)                    |
|                                                                 |
| \# 3. Plan the task (creates subtasks)                          |
|                                                                 |
| subtasks = self.planner.decompose(task_text, project)           |
|                                                                 |
| \# 4. Add all subtasks to global queue under this project       |
|                                                                 |
| for st in subtasks:                                             |
|                                                                 |
| self.queue.add_task(QueueTask(                                  |
|                                                                 |
| project_id=project.project_id,                                  |
|                                                                 |
| description=st.description,                                     |
|                                                                 |
| preferred_peer=st.peer_hint,                                    |
|                                                                 |
| depends_on=st.depends_on,                                       |
|                                                                 |
| \...                                                            |
|                                                                 |
| ))                                                              |
|                                                                 |
| \# 5. Trigger scheduler --- it will dispatch what it can now    |
|                                                                 |
| asyncio.create_task(self.queue.tick())                          |
|                                                                 |
| return (f\'Added {len(subtasks)} tasks for                      |
| {project.display_name}.\'                                       |
|                                                                 |
| f\'\\n{self.\_get_queue_summary()}\')                           |
+-----------------------------------------------------------------+

  --------- -------------------------------------------------------------
   **4.3**  **Add /team status Command**

  --------- -------------------------------------------------------------

+-----------------------------------------------------------------+
| \# Output format for /team status:                              |
|                                                                 |
| ╔══ CODEY TEAM STATUS ════════════════════════════════════════╗ |
|                                                                 |
| ║ Routing Mode: BALANCED Online: YES Projects: 3 ║              |
|                                                                 |
| ╠═════════════════════════════════════════════════════════════╣ |
|                                                                 |
| ║ ACTIVE NOW ║                                                  |
|                                                                 |
| ║ gaming-app \[claude\] Task 4: Implement game board ║          |
|                                                                 |
| ║ startup-api \[gemini\] Task 2: Design DB schema ║             |
|                                                                 |
| ║ todo-app \[local\] Task 1: Add tests ║                        |
|                                                                 |
| ╠═════════════════════════════════════════════════════════════╣ |
|                                                                 |
| ║ QUEUED (next up) ║                                            |
|                                                                 |
| ║ gaming-app Task 5: Add scoring system → claude ║              |
|                                                                 |
| ║ startup-api Task 3: JWT implementation → claude ║             |
|                                                                 |
| ╠═════════════════════════════════════════════════════════════╣ |
|                                                                 |
| ║ PEER UTILIZATION (this session) ║                             |
|                                                                 |
| ║ claude ████████████ 12 tasks 48% quality 0.88 ✅ ║            |
|                                                                 |
| ║ gemini ██████ 6 tasks 24% quality 0.91 ✅ ║                   |
|                                                                 |
| ║ qwen ██████ 6 tasks 24% quality 0.84 ✅ ║                     |
|                                                                 |
| ║ local █ 1 task 4% quality 0.79 ✅ ║                           |
|                                                                 |
| ╚═════════════════════════════════════════════════════════════╝ |
+-----------------------------------------------------------------+

  --------- -------------------------------------------------------------
   **4.4**  **Test Phase 4**

  --------- -------------------------------------------------------------

- Start two projects. Add tasks for both. Verify they run on different
  peers simultaneously and never the same peer on two projects.

- Start three projects, exhaust all peers. Add a fourth project\'s task.
  Verify it queues and dispatches the moment any peer finishes.

- While Project A is running on Claude, give Codey new work for
  Project B. Verify Project B\'s tasks are added to queue and dispatched
  to an idle peer.

- Verify /team status shows correct real-time state of all active and
  queued work.

+-----------------------------------------------------------------+
| **PHASE 5**                                                     |
|                                                                 |
| **Routing Modes & Performance Settings**                        |
|                                                                 |
| Best / Balanced / Economical scoring with the /performance      |
| command.                                                        |
+-----------------------------------------------------------------+

  --------- -------------------------------------------------------------
   **5.1**  **Implement All Three Scoring Functions in TeamRouter**

  --------- -------------------------------------------------------------

The scoring functions were sketched in Phase 2. Now fully implement them
with real session stats integration.

  -------------- ---------------------------- -----------------------
  **MODE**       **KEY DIFFERENCE**           **WHEN TO USE**

  BEST           Ignores workload entirely.   Critical project.
                 Pure capability × quality.   Quality over
                                              everything.

  BALANCED       Workload penalty: overworked Long sessions. Multiple
                 peers score lower even if    projects over hours.
                 capable.                     

  ECONOMICAL     Cost tier multiplier. Claude Day-to-day work.
                 only if others score below   Minimize paid API
                 0.4.                         usage.
  -------------- ---------------------------- -----------------------

  --------- -------------------------------------------------------------
   **5.2**  **Add /performance Command**

  --------- -------------------------------------------------------------

+-----------------------------------------------------------------+
| \# In daemon.py:                                                |
|                                                                 |
| elif cmd == \'/performance\':                                   |
|                                                                 |
| stats = self.queue.get_session_stats()                          |
|                                                                 |
| current = self.config\[\'routing_mode\'\]                       |
|                                                                 |
| return self.\_render_performance_menu(stats, current)           |
|                                                                 |
| def \_render_performance_menu(self, stats, current):            |
|                                                                 |
| \# Show current mode, session stats bar chart,                  |
|                                                                 |
| \# prompt user to pick new mode                                 |
|                                                                 |
| \# On selection: update config + re-score any pending tasks     |
|                                                                 |
| \...                                                            |
|                                                                 |
| \# Output:                                                      |
|                                                                 |
| \# Current mode: BEST                                           |
|                                                                 |
| \#                                                              |
|                                                                 |
| \# Session stats:                                               |
|                                                                 |
| \# claude ████████████ 12 tasks (48%)                           |
|                                                                 |
| \# gemini ██████ 6 tasks (24%)                                  |
|                                                                 |
| \# qwen ██████ 6 tasks (24%)                                    |
|                                                                 |
| \# local █ 1 task (4%)                                          |
|                                                                 |
| \#                                                              |
|                                                                 |
| \# \[1\] BEST --- optimal peer per task                         |
|                                                                 |
| \# \[2\] BALANCED --- equal workload distribution               |
|                                                                 |
| \# \[3\] ECONOMICAL --- minimize Claude usage (paid)            |
|                                                                 |
| \# \[4\] Set per-project override                               |
|                                                                 |
| \#                                                              |
|                                                                 |
| \# Current: BEST \> \_                                          |
+-----------------------------------------------------------------+

  --------- -------------------------------------------------------------
   **5.3**  **Per-Project Mode Override**

  --------- -------------------------------------------------------------

+-----------------------------------------------------------------+
| \# Command: /project set-mode \<project-id\> \<mode\>           |
|                                                                 |
| \# Stored in ProjectRecord.routing_mode                         |
|                                                                 |
| \# TeamRouter checks project.routing_mode first,                |
|                                                                 |
| \# falls back to global config if not set                       |
|                                                                 |
| def route(self, task, project, global_mode, \...):              |
|                                                                 |
| mode = project.routing_mode or global_mode                      |
|                                                                 |
| \# rest of routing logic uses this mode                         |
+-----------------------------------------------------------------+

  --------- -------------------------------------------------------------
   **5.4**  **Test Phase 5**

  --------- -------------------------------------------------------------

- Run /performance, switch to BALANCED, run 20 tasks across multiple
  projects. Verify workload distribution approaches equal split over
  time.

- Switch to ECONOMICAL. Verify Claude is not selected for any task where
  Gemini or Qwen scores above 0.4. Verify Claude IS selected when a
  security review task falls below the threshold for others.

- Set a per-project override of BEST on one project while global is
  ECONOMICAL. Verify that project uses best-fit routing while others use
  economical.

- Verify /performance shows accurate session stats that update in real
  time as tasks complete.

+-----------------------------------------------------------------+
| **PHASE 6**                                                     |
|                                                                 |
| **Project Awareness, Audits & Polish**                          |
|                                                                 |
| Outline conflict detection, full code audits, bug insertion,    |
| milestone tracking, and all user-facing commands.               |
+-----------------------------------------------------------------+

  --------- -------------------------------------------------------------
   **6.1**  **Outline Conflict Detection**

  --------- -------------------------------------------------------------

The most important correctness feature of Codey-v3. When a peer produces
output that contradicts the project outline, Codey catches it before
applying.

+-----------------------------------------------------------------+
| \# core/project_registry.py                                     |
|                                                                 |
| def check_outline_conflict(self, project_id: str,               |
|                                                                 |
| peer_output: str) -\> list\[str\]:                              |
|                                                                 |
| project = self.load(project_id)                                 |
|                                                                 |
| outline = project.outline                                       |
|                                                                 |
| conflicts = \[\]                                                |
|                                                                 |
| \# Check 1: New tech stack entries not in outline               |
|                                                                 |
| detected_tech = self.\_extract_tech(peer_output)                |
|                                                                 |
| for tech in detected_tech:                                      |
|                                                                 |
| if tech not in outline.tech_stack:                              |
|                                                                 |
| conflicts.append(                                               |
|                                                                 |
| f\'New technology detected: {tech} not in outline\'             |
|                                                                 |
| )                                                               |
|                                                                 |
| \# Check 2: New endpoints not in outline                        |
|                                                                 |
| detected_endpoints = self.\_extract_endpoints(peer_output)      |
|                                                                 |
| for ep in detected_endpoints:                                   |
|                                                                 |
| if ep not in outline.endpoints:                                 |
|                                                                 |
| conflicts.append(                                               |
|                                                                 |
| f\'New endpoint: {ep} not in outline\'                          |
|                                                                 |
| )                                                               |
|                                                                 |
| \# Check 3: Auth method change                                  |
|                                                                 |
| if self.\_detects_auth_method(peer_output,                      |
| outline.auth_method):                                           |
|                                                                 |
| conflicts.append(\'Auth method change detected\')               |
|                                                                 |
| return conflicts                                                |
|                                                                 |
| \# On conflict: PAUSE project queue, notify user:               |
|                                                                 |
| \# \'Task 4 conflicts with outline:\'                           |
|                                                                 |
| \# \' - New technology: Redis not in outline\'                  |
|                                                                 |
| \# \'Options: \[1\] Update outline \[2\] Redo task \[3\]        |
| Ignore\'                                                        |
+-----------------------------------------------------------------+

  --------- -------------------------------------------------------------
   **6.2**  **Full Code Audit After Milestones**

  --------- -------------------------------------------------------------

After all tasks in a milestone are marked done, trigger a full code
audit. This can be routed to a peer different from the one that wrote
the code --- cross-peer review.

+-----------------------------------------------------------------+
| \# core/review_gate.py                                          |
|                                                                 |
| def full_audit(self, project: ProjectRecord,                    |
|                                                                 |
| reviewer_peer: str = None) -\> AuditResult:                     |
|                                                                 |
| \# 1. If reviewer_peer not specified:                           |
|                                                                 |
| \# Use a different peer from the one that did most work         |
|                                                                 |
| \# (writer != reviewer)                                         |
|                                                                 |
| if not reviewer_peer:                                           |
|                                                                 |
| reviewer_peer = self.\_pick_reviewer(project)                   |
|                                                                 |
| \# 2. Build audit payload:                                      |
|                                                                 |
| \# - Full codebase summary                                      |
|                                                                 |
| \# - Project outline                                            |
|                                                                 |
| \# - Task history for this milestone                            |
|                                                                 |
| \# - Request: list issues, rate quality, suggest improvements   |
|                                                                 |
| \# 3. Dispatch to reviewer peer                                 |
|                                                                 |
| \# 4. Parse audit result into structured issues                 |
|                                                                 |
| \# 5. For each issue: create task, add to queue                 |
|                                                                 |
| \# 6. Update ProjectRecord with audit timestamp + result        |
+-----------------------------------------------------------------+

  --------- -------------------------------------------------------------
   **6.3**  **Bug / Issue Insertion Mid-Queue**

  --------- -------------------------------------------------------------

When a bug is discovered mid-session --- by a peer, by tests, or
reported by the user --- Codey consults a peer on the fix, creates
tasks, and inserts them at the correct queue position.

+-----------------------------------------------------------------+
| \# User: \'There\'s a login bug --- users can\'t log in after   |
| token expiry\'                                                  |
|                                                                 |
| def handle_bug_report(self, description: str,                   |
|                                                                 |
| project_id: str) -\> str:                                       |
|                                                                 |
| \# 1. Route to diagnostic peer (claude preferred for debug)     |
|                                                                 |
| diagnosis = self.peer_bridge.dispatch(\'claude\',               |
|                                                                 |
| HandoffPayload(subtask_description=f\'Diagnose:                 |
| {description}\',                                                |
|                                                                 |
| expected_output_format=\'analysis_report\', \...))              |
|                                                                 |
| \# 2. Parse diagnosis into fix tasks                            |
|                                                                 |
| fix_tasks = self.\_parse_fix_tasks(diagnosis)                   |
|                                                                 |
| \# 3. Determine insertion point:                                |
|                                                                 |
| \# - If bug blocks current work → insert immediately (priority  |
| 1)                                                              |
|                                                                 |
| \# - If bug is non-blocking → insert after current task         |
| (priority 3)                                                    |
|                                                                 |
| \# - If cosmetic → append to end of milestone (priority 7)      |
|                                                                 |
| insertion = self.\_determine_insertion(fix_tasks, project_id)   |
|                                                                 |
| \# 4. Insert into queue                                         |
|                                                                 |
| for task in fix_tasks:                                          |
|                                                                 |
| self.queue.insert_at(task, insertion)                           |
|                                                                 |
| return f\'Created {len(fix_tasks)} fix tasks.                   |
| {insertion.description}\'                                       |
+-----------------------------------------------------------------+

  --------- -------------------------------------------------------------
   **6.4**  **Full Command Suite**

  --------- -------------------------------------------------------------

  --------------------- --------------------------------------------
  **COMMAND**           WHAT IT DOES

  /team status          Real-time view: active tasks, peer
                        assignments, queue depth, all projects.

  /team history         Last N completed tasks with peer breakdown
  \[project\]           and pass/fail results.

  /team pause           Pause a project\'s queue. Peer finishes
  \[project\]           current task then idles on this project.

  /team resume          Resume paused project queue.
  \[project\]           

  /project list         All known projects with status, active
                        tasks, last worked date.

  /project status       Full detail on one project: outline,
  \[name\]              milestones, recent work, peer performance.

  /project update       Open PROJECT_OUTLINE.md in \$EDITOR. On
  \[name\]              save: validate schema, persist, re-inject.

  /project audit        Trigger full code audit on a project. Routes
  \[name\]              to non-primary peer.

  /performance          Show routing mode selector with session
                        utilization stats.

  /route \<task\>       Dry-run: show routing decision + confidence
                        without executing.

  /peer status          Check availability of all peers. Shows:
                        installed, API key present, idle/busy.

  /peer stats           Peer performance table: calls, quality
                        scores, latency, failure rates.
  --------------------- --------------------------------------------

  --------- -------------------------------------------------------------
   **6.5**  **Final Integration Test**

  --------- -------------------------------------------------------------

The full end-to-end test. Run this last.

1.  Tell Codey: \'Create a new Android gaming app like Candy Crush.\'
    Verify: directory created, outline generated, initial tasks created,
    first tasks dispatched to peers.

2.  Mid-session, tell Codey: \'Also start a simple REST API for a todo
    app.\' Verify: second project added, tasks queued, running in
    parallel on different peer.

3.  Report a bug: \'The game board doesn\'t render on small screens.\'
    Verify: diagnosis dispatched, fix tasks created, inserted before
    next dependent task.

4.  Switch routing mode to ECONOMICAL. Verify pending tasks re-scored
    and re-assigned if needed.

5.  Ask: \'Where are we with the gaming app?\' Verify: coherent status
    report with tasks done, in progress, and queued.

6.  Trigger a full audit on the gaming app after milestone 1 completes.
    Verify: different peer does the review, issues become tasks in
    queue.

7.  Verify git log shows clean commit history with agent attribution on
    every commit.

**6. Configuration Reference**

Add these blocks to utils/config.py. All values are overridable by the
user.

+--------------------------------------------------------------------+
| \# utils/config.py --- new blocks for v3                           |
|                                                                    |
| TEAM_CONFIG = {                                                    |
|                                                                    |
| \'enabled\': False, \# Off by default. User opts in.               |
|                                                                    |
| \'routing_mode\': \'best\', \#                                     |
| \'best\'\|\'balanced\'\|\'economical\'                             |
|                                                                    |
| \'max_concurrent_peers\': 3, \# All 3 can run simultaneously       |
|                                                                    |
| \'peer_timeout_sec\': 120, \# Kill peer process after this         |
|                                                                    |
| \'wait_threshold_sec\': 1200, \# 20min wait → notify user          |
|                                                                    |
| \'min_free_ram_mb\': 500, \# Peers are thin clients, low req       |
|                                                                    |
| \'secret_redaction\': True, \# Always on                           |
|                                                                    |
| \'auto_advance_queue\': True, \# Auto-dispatch on task complete    |
|                                                                    |
| \'require_confirm_arch\': True, \# Pause for outline conflicts     |
|                                                                    |
| }                                                                  |
|                                                                    |
| ROUTING_CONFIG = {                                                 |
|                                                                    |
| \'complexity_threshold\': 0.60,                                    |
|                                                                    |
| \'economical_min_score\': 0.40, \# Floor before escalating to      |
| Claude                                                             |
|                                                                    |
| \'balanced_penalty\': 0.50, \# How much to penalize overwork       |
|                                                                    |
| \'peer_strengths\': {                                              |
|                                                                    |
| \'claude\':                                                        |
| \[\'refactor\',\'debug\',\'security\',\'auth\',\'test\',\'api\'\], |
|                                                                    |
| \'gemini\':                                                        |
| \[\'analyze\',\'plan\',\'architecture\',\'schema\',\'docs\'\],     |
|                                                                    |
| \'qwen\':                                                          |
| \[\'generate\',\'boilerplate\',\'template\',\'scaffold\'\],        |
|                                                                    |
| \'local\': \[\'rename\',\'small\',\'git\',\'format\',\'lint\'\],   |
|                                                                    |
| },                                                                 |
|                                                                    |
| \'cost_tiers\': {                                                  |
|                                                                    |
| \'gemini\': 0, \'qwen\': 1, \'local\': 2, \'claude\': 3            |
|                                                                    |
| },                                                                 |
|                                                                    |
| }                                                                  |
|                                                                    |
| QUEUE_CONFIG = {                                                   |
|                                                                    |
| \'max_retries\': 2,                                                |
|                                                                    |
| \'retry_delay_sec\': 30,                                           |
|                                                                    |
| \'fix_task_priority\': 1, \# Fix tasks always jump queue           |
|                                                                    |
| \'audit_after_tasks\': 10, \# Auto-audit every N task completions  |
|                                                                    |
| \'milestone_auto_audit\':True,                                     |
|                                                                    |
| }                                                                  |
|                                                                    |
| PEER_COMMANDS = {                                                  |
|                                                                    |
| \'claude\': \[\'claude\', \'\--dangerously-skip-permissions\'\],   |
|                                                                    |
| \'gemini\': \[\'gemini\', \'\--yolo\'\],                           |
|                                                                    |
| \'qwen\': \[\'qwen-cli\'\],                                        |
|                                                                    |
| }                                                                  |
+--------------------------------------------------------------------+

**7. Risks & Android/Termux Gotchas**

**7.1 Critical Risks**

  --------------------- --------------------------------------------
  **RISK**              MITIGATION

  Android kills daemon  Use termux-wake-lock during active
  mid-task              orchestration. Write subtask progress to
                        SQLite after every step so resumption is
                        possible from last checkpoint.

  Peers don\'t follow   Always include 2-shot example in prompt.
  CODEY_RESULT contract Heuristic fallback parser. If both fail:
                        graceful PeerResult(success=False) --- never
                        crash, never apply raw output.

  Diff application      Mandatory dry-run before real apply using
  corrupts files        patch \--dry-run -p1. If dry-run fails:
                        reject, log, fallback. Never use string
                        replace on source files with peer output.

  Secret leakage to     secret_redactor runs on HandoffPayload
  cloud peers           before dispatch. Add .env, \*.pem, \*.key,
                        \*secret\* to .codeyignore. This check is
                        non-optional.

  Outline conflict      require_confirm_arch=True in config.
  auto-accepted         Conflicts always PAUSE the project queue and
  silently              prompt user. Never auto-resolve without user
                        input.

  Context window        Enforce MAX_PEER_PROMPT_TOKENS per peer. RAG
  blowout on peers      slice truncated to: budget - state_summary -
                        task_desc - 500. Peer prompts fail fast with
                        clear error if budget exceeded.

  Multi-project git     ResultSynthesizer checks git status before
  conflicts             every diff apply. Conflict detected → stop,
                        notify user, do not auto-resolve. Narrow
                        file_to_modify scope in next decomposition.
  --------------------- --------------------------------------------

**7.2 Context Window Budgets Per Peer**

  -------------- ---------------------------- -----------------------
  **PEER**       **MAX PROMPT TOKENS**        **NOTES**

  claude         180,000                      Claude Sonnet has huge
                                              context. Use it for
                                              large codebase tasks.

  gemini         100,000                      Gemini 2.0 Flash
                                              context is generous.
                                              Good for large
                                              analysis.

  qwen           32,000                       CLI may use smaller
                                              model. Keep prompts
                                              tight.

  local (7B)     3,500                        Leave room for
                                              response. RAG slice
                                              must be small.

  local (1.5B)   1,500                        Simple tasks only.
                                              Minimal context.
  -------------- ---------------------------- -----------------------

**7.3 Termux-Specific Notes**

- Peer CLIs (Claude, Gemini, Qwen) are thin API clients --- \~50-150MB
  RAM each. Running all three simultaneously is safe on S24 Ultra.

- llama.cpp (local model) is the only heavy process. Peers don\'t
  compete with it for RAM significantly.

- Use termux-wake-lock when starting a long orchestration session.
  Without it, Android may suspend the daemon mid-task.

- Add \'ulimit -v 800000\' before peer subprocess calls as a safety cap.
  Prevents any single peer from taking unexpected RAM.

- Unix socket IPC (already in v2) is the right approach. Do not switch
  to TCP for daemon communication.

- If llama-server fails to bind to socket on restart (stale socket
  file), add socket cleanup to daemon startup.

**8. Quick Reference**

**8.1 Phase Checklist**

  --------------- --------------- --------------- ---------------------------
  **PHASE**       **NAME**        **CODEY         **KEY DELIVERABLE**
                                  FUNCTIONAL?**   

  1               Project         YES --- local   ProjectRecord,
                  Registry        only            detect_or_create(), SQLite
                                                  schema

  2               Global Queue    YES --- local   Dependency graph,
                                  only            scheduler, /route dry-run

  3               Peer Bridge     YES --- Claude  End-to-end task→diff→commit
                                  first           via Claude

  4               Multi-Project   YES --- full    1-peer-per-project, project
                                  parallel        switching, /team status

  5               Routing Modes   YES --- all     Best/Balanced/Economical,
                                  features        /performance command

  6               Audits & Polish YES ---         Outline conflict detection,
                                  complete        audits, bug insertion
  --------------- --------------- --------------- ---------------------------

**8.2 The Rules That Must Never Break**

+-----------------------------------------------------------------+
| **Rule 1**                                                      |
|                                                                 |
| One peer per project at a time. No exceptions. Two peers on the |
| same codebase = merge conflicts.                                |
+-----------------------------------------------------------------+

+-----------------------------------------------------------------+
| **Rule 2**                                                      |
|                                                                 |
| Never apply raw peer output to the filesystem. Always: dry-run  |
| → static analysis → tests → outline check first.                |
+-----------------------------------------------------------------+

+-----------------------------------------------------------------+
| **Rule 3**                                                      |
|                                                                 |
| Always redact secrets from HandoffPayload before dispatch. This |
| check is non-optional regardless of which peer is targeted.     |
+-----------------------------------------------------------------+

+-----------------------------------------------------------------+
| **Rule 4**                                                      |
|                                                                 |
| Outline conflicts always pause and prompt the user. Never       |
| auto-resolve. The outline is the source of truth.               |
+-----------------------------------------------------------------+

**8.3 The Four New Core Files (Build These First)**

+-----------------------------------------------------------------+
| Phase 1: core/handoff.py \# Dataclasses. No logic.              |
|                                                                 |
| Phase 1: core/project_registry.py \# The source of truth.       |
|                                                                 |
| Phase 2: core/global_queue.py \# Dependency graph + scheduler.  |
|                                                                 |
| Phase 2: core/team_router.py \# Task routing, 3 modes.          |
|                                                                 |
| Phase 3: core/peer_bridge.py \# Subprocess dispatch + parsing.  |
|                                                                 |
| Phase 3: core/result_synthesizer.py \# Apply + gate + commit.   |
|                                                                 |
| Phase 3: core/review_gate.py \# Pass/fail + fix task creation.  |
|                                                                 |
| Phase 4+: core/team_orchestrator.py \# Ties everything          |
| together.                                                       |
+-----------------------------------------------------------------+

**Remember:** core/team_router.py is the TASK router. core/router.py is
the MODEL router (7B vs 1.5B). These are two different files with two
different jobs. Do not confuse them.

+:---------------------------------------------------------------:+
| **CODEY-V3 IMPLEMENTATION PLAN**                                |
|                                                                 |
| Built on Codey-v2.6.9 · Ishabdullah/Codey-v2 · Android / Termux |
| / S24 Ultra                                                     |
+-----------------------------------------------------------------+
