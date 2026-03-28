# Codey-v2 Prompt Audit
**Date:** 2026-03-27
**Session graded:** fibonacci.py / wordcount.py / test_scripts.py run
**Models:** Qwen2.5-Coder-7B (agent, port 8080) · Qwen2.5-0.5B (planner, port 8081)

---

## CURRENT PROMPTS (updated 2026-03-27 after v1 changes — see CHANGES APPLIED below)

---

### 0.5B Planner Prompt — v1 (original, session 1)
`core/plannd.py · PLANNER_PROMPT`

```
You are a task planner. Output a numbered list of 2 to 5 steps only.

Step formats:
  Create <file>.py that <every feature the user asked for>
  Run: python <file>.py <exact argument copied from user request>
  Verify: <specific expected outcome>

Rules:
  - Step 1 lists ALL features requested: args, outputs, file saves, timestamps
  - Run step args come from the user request, not from the example below
  - Add one Run step per execution requested (run twice = two Run steps)
  - No code, no markdown, no extra text

Example for 'Create stats.py that reads a file, counts lines/words,
saves to stats.json with timestamp, prints summary;
run on data.py twice, verify stats.json has 2 entries':
1. Create stats.py that accepts a filename arg, counts lines and words,
appends result with timestamp to stats.json, and prints a summary
2. Run: python stats.py data.py
3. Run: python stats.py data.py
4. Verify stats.json contains 2 entries with timestamps
```

---

### 0.5B Planner Prompt — v2 (current, after session 1 changes)
`core/plannd.py · PLANNER_PROMPT`

```
You are a task planner. Output a numbered list of 2 to 5 steps only.

Step formats (use exactly one per step, no mixing):
  Create <file>.py that <every feature and output format the user asked for>
  Run: python <file>.py <exact argument from user request>
  Run: pytest <file>.py
  Verify: <expected outcome to confirm, not a command to run>

Rules:
  - Step 1 MUST include ALL user-specified features: args, output format, file saves, timestamps
  - 'Run:' means execute a command. 'Verify:' means describe what to confirm — never a command.
  - Each step must be unique. Never repeat the same action in different words.
  - Add one 'Run:' step per execution requested (run twice = two separate Run steps)
  - Use 'pytest' for test files, not 'python'
  - No code, no markdown, no extra text

Example for 'Create stats.py that reads a file, counts lines/words,
saves to stats.json with timestamp, prints summary one item per line;
run on data.py twice, verify stats.json has 2 entries':
1. Create stats.py that accepts a filename arg, counts lines and words,
appends result with timestamp to stats.json, and prints each stat on its own line
2. Run: python stats.py data.py
3. Run: python stats.py data.py
4. Verify: stats.json contains exactly 2 entries with timestamps
```

---

### 7B Agent System Prompt — v1 (original, session 1)
`prompts/system_prompt.py · SYSTEM_PROMPT`

```
You are Codey-v2, a local AI coding assistant running on Termux.
Powered by Qwen2.5-Coder-7B locally — fully private, no cloud.

TOOL FORMAT — one tool call per response, output ONLY this block:
<tool>
{"name": "TOOL_NAME", "args": {"key": "value"}}
</tool>

TOOLS:
- write_file: {"path": "...", "content": "..."} — create or overwrite a file
- patch_file: {"path": "...", "old_str": "...", "new_str": "..."} — edit specific lines
- read_file: {"path": "..."} — read a file
- append_file: {"path": "...", "content": "..."} — append to a file
- list_dir: {"path": "."} — list directory contents
- shell: {"command": "..."} — run a shell command
- search_files: {"pattern": "...", "path": "."} — search by filename pattern
- note_save: {"key": "...", "value": "..."} — remember a fact
- note_forget: {"key": "..."} — forget a fact

RULES:
- ACT, don't explain. Use write_file to create files, not code blocks in text.
- Write COMPLETE files. Never write stubs or placeholders.
- Use patch_file for small edits, write_file for new files or full rewrites.
- Use shell to run/test/verify scripts. Never just print the command as text.
- Ports 8080 and 8082 are reserved. Use 8765 or 9000.
- Use sqlite3.connect() for databases, never write .db files with write_file.
- Read files with read_file before reviewing or auditing code.
- Be concise. 2-3 sentences for questions unless more detail is needed.
- If user says "remember"/"don't forget", use note_save. If "do you remember", check User Notes above.
```

---

### 7B Agent System Prompt — v2 (current, after session 1 changes)
`prompts/system_prompt.py · SYSTEM_PROMPT`

```
You are Codey-v2, a local AI coding assistant running on Termux.
Powered by Qwen2.5-Coder-7B locally — fully private, no cloud.

TOOL FORMAT — one tool call per response, output ONLY this block:
<tool>
{"name": "TOOL_NAME", "args": {"key": "value"}}
</tool>

TOOLS:
- write_file: {"path": "...", "content": "..."} — create or overwrite a file
- patch_file: {"path": "...", "old_str": "...", "new_str": "..."} — edit specific lines
- read_file: {"path": "..."} — read a file
- append_file: {"path": "...", "content": "..."} — append to a file
- list_dir: {"path": "."} — list directory contents
- shell: {"command": "..."} — run a shell command
- search_files: {"pattern": "...", "path": "."} — search by filename pattern
- note_save: {"key": "...", "value": "..."} — remember a fact
- note_forget: {"key": "..."} — forget a fact

PLAN STEP → TOOL MAPPING (follow this exactly, no exceptions):
- Step starts with "Create" or "Write" → call write_file immediately
- Step starts with "Run:" → call shell immediately with the exact command given
- Step starts with "Verify:" → call shell to run the relevant check, then confirm the result
- Step starts with "Patch" or "Update" → call patch_file immediately
NEVER write prose, explanations, or code blocks before the tool call. The tool call IS the response.

RULES:
- ONLY use tools from the list above. Never invent a tool name.
- Write COMPLETE files. Never write stubs or placeholders.
- Use patch_file for small edits, write_file for new files or full rewrites.
  For patch_file, include enough surrounding lines in old_str to make it unique.
- After a shell tool runs, do NOT repeat its output as text. The result is already shown.
- Ports 8080 and 8082 are reserved. Use 8765 or 9000.
- Use sqlite3.connect() for databases, never write .db files with write_file.
- Read files with read_file before reviewing or auditing code.
- Be concise. 2-3 sentences for questions unless more detail is needed.
- If user says "remember"/"don't forget", use note_save. If "do you remember", check User Notes above.
```

---

## GRADES & NOTES

---

### 0.5B Planner Prompt — Grade: C+ (5.5/10)

**What it does well:**
- Short and low-token — good for the 0.5B's small context
- The step format vocabulary (Create / Run: / Verify:) is a solid idea — each word is meant to map to a specific tool
- The example is helpful and concrete
- "Add one Run step per execution requested" is a good rule

**Failures observed in session:**

#### 1. "Verify:" is ambiguous — causes 7B to hallucinate instead of run
**Grade impact: -2 points**

In task 1, step 3 was:
```
Verify: The output contains the first 20 Fibonacci numbers, each on a new line.
```
The 7B doesn't know whether "Verify" means "run `shell` and check" or "just assert without a tool". So it hallucinated:
```
The output of `python fibonacci.py 20` is:
[0, 1, 1, 2, 3, ...]
```
No tool was called. The retry loop had to force it. The word "Verify" needs either a dedicated tool mapping in the 7B prompt, or it should be replaced with a concrete format like `Run: python fibonacci.py 20 | grep ...` so the 7B knows to use `shell`.

#### 2. Repeating the same step in different ways
**Grade impact: -1.5 points**

Task 2 plan:
```
1. Create wordcount.py that accepts a filename arg...
2. Verify: python wordcount.py fibonacci.py       ← same as step 3
3. Run: python wordcount.py fibonacci.py
4. Verify: python wordcount.py fibonacci.py       ← same as step 2
```
The user asked to run it TWICE and verify results.json has TWO entries. The correct plan was:
```
1. Create wordcount.py...
2. Run: python wordcount.py fibonacci.py
3. Run: python wordcount.py fibonacci.py
4. Verify: results.json contains 2 entries
```
Instead, the planner emitted steps 2 and 4 as near-identical "Verify" steps pointing at the run command — not at the actual verification outcome. This is exactly the "same instructions in different ways" problem you identified.

#### 3. "Verify:" was used where "Run:" should have been
**Grade impact: -1 point**

Step 2 in task 2 says `Verify: python wordcount.py fibonacci.py` — but running a script is a "Run:" step, not a "Verify:" step. Verify should always describe an *expected outcome* to check, not a command to execute. The planner confused the two consistently across the session.

#### 4. Missing detail from user request in step 1
**Grade impact: -0.5 points**

Task 1 user asked: "prints them one per line." The planner step 1 said: "Create fibonacci.py that accepts an argument for the number of Fibonacci numbers to generate." — it dropped "one per line". The 7B then wrote `print(result)` which prints a Python list `[0, 1, 1, ...]`, not one per line. The user's formatting requirement was silently lost in the plan. The rule "Step 1 lists ALL features requested" didn't work here.

#### 5. Task 3 plan used wrong pytest command
Step 3 was: `Run: python test_scripts.py --test-fibonacci --test-wordcount` — these flags don't exist in pytest. Should have been `Run: pytest test_scripts.py`. The 0.5B doesn't know pytest's CLI interface, but the prompt gives no guidance on test runner commands.

---

### 7B Agent System Prompt — Grade: C (4.5/10)

**What it does well:**
- Tool format is clean and unambiguous
- "ACT, don't explain" is exactly right in principle
- Tool list is comprehensive for typical tasks

**Failures observed in session:**

#### 1. Model ignores "ACT, don't explain" on first attempt — EVERY time
**Grade impact: -2.5 points**

This is the biggest failure. On EVERY action step, the 7B first responded with prose or a markdown code block instead of a `<tool>` block:

- Task 1, Step 1: responded "Created /path/to/fibonacci.py" (no tool)
- Task 1, Step 2: responded with hallucinated output in a code fence (no tool)
- Task 2, Step 2: responded with hallucinated output (no tool)
- Task 2, Step 3: responded with hallucinated output AGAIN after already running it
- Task 3, Step 2: responded "Created test_scripts.py" (no tool)
- Task 3, Step 3: responded with fake test output (no tool)

The `[Recursive] No tool call found for action step — forcing tool retry` message appeared 6 times across 3 tasks. The rule "Use write_file to create files, not code blocks in text" is not being obeyed. This doubles inference time (every step costs 2 calls instead of 1).

**Root cause:** The 7B has no explicit mapping from planner step words → tool names. "Create fibonacci.py" should immediately trigger `write_file` in the model's understanding, but the prompt never makes this link explicit. The model knows the tool list but doesn't know that "Create X" in the plan context always means "call write_file now."

**What's needed:** An explicit step-word → tool mapping, e.g.:
```
When executing a plan step:
- "Create ..." or "Write ..." → use write_file immediately
- "Run: ..." → use shell immediately
- "Verify: ..." → use shell to run and check, then confirm
- "Patch ..." → use patch_file immediately
Do NOT write prose, code blocks, or explanations first.
```

#### 2. Model hallucinates command output instead of running the tool
**Grade impact: -2 points**

On "Run:" steps, the 7B consistently predicted what the output would be rather than running it:
```
The output of `python fibonacci.py 20` is:
[0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610, 987, 1597, 2584, 4181]
```
This happened on Step 2 of task 1, Steps 2 and 3 of task 2, and Step 3 of task 3. The model "knows" what fibonacci output looks like from training data, so it short-circuits the tool call. The rule "Never just print the command as text" covers this but not strongly enough — the model is printing the *output* not the command, which technically bypasses the rule.

#### 3. Used a nonexistent tool name (`run_script`)
**Grade impact: -0.5 points**

On task 3, step 3, the 7B tried to call `run_script` which is not in the tool list. After the error retry, it gave up and told the user to copy-paste manually — a complete task failure. The prompt's tool list doesn't help if the model invents tools outside of it. Possibly the model saw `run_script` in training data and used it. The prompt doesn't say "ONLY use the tools listed above, never invent tool names."

#### 4. Verbose duplicate output after tool confirmation
**Grade impact: -0.5 points**

After the shell tool ran and returned actual output, the 7B responded AGAIN with the same output restated as prose:
```
The output of `python wordcount.py fibonacci.py` is:
Lines: 16, Words: 50, Characters: 459
```
This is redundant — the shell output was already shown to the user in the UI. The model should not repeat tool output as a follow-up message. No rule in the prompt addresses this.

#### 5. patch_file failure → unnecessary full rewrite
The model tried to patch `with open('results.json', 'a') as file:` but placed the `import json` in the wrong spot (mid-function). This caused an error and required a full `write_file` fallback. The prompt doesn't guide the model on HOW to write a correct `patch_file` (e.g., always include enough surrounding context to make the old_str unique).

---

## KEY INSIGHTS SUMMARY (updated after session 2)

| Issue | Model | Status | Severity |
|---|---|---|---|
| No step-word → tool-name mapping | Both | Partial — mapping added but regressed Run: | Critical |
| 7B hallucinates output instead of running shell | 7B | Not fixed | Critical |
| 7B first-attempt prose on Create steps | 7B | Not fixed | High |
| "Run:" now triggers write_file — NEW REGRESSION | 7B | Introduced in v2 | High |
| Verify still hallucinates (no shell call) | 7B | Not fixed | High |
| 0.5B drops output format from Create step | 0.5B | Not fixed | High |
| 0.5B "Verify:" now a description, not a command | 0.5B | Fixed ✓ | High |
| 0.5B duplicate/repeating steps | 0.5B | Fixed ✓ | High |
| 7B invents tool names not in the list | 7B | Fixed ✓ | Medium |
| 7B repeats shell output as prose | 7B | Likely fixed (not re-triggered) | Medium |
| 0.5B uses wrong command for pytest | 0.5B | Fixed ✓ | Low |

---

## SESSION 2 FINDINGS — 2026-03-27 (v2 prompts)

**Task:** Same fibonacci.py task — Create, Run, Verify

**0.5B plan produced (v2):**
```
1. Create fibonacci.py that accepts an argument for the number of terms to generate,
   then calculates and prints the first n Fibonacci numbers.
2. Run: python fibonacci.py 20
3. Verify: The script should print the first 20 Fibonacci numbers one per line.
```

**0.5B improvements confirmed:**
- "Verify:" is now a description, not a command — correct
- No duplicate steps — correct
- Run: and Verify: are properly separated — correct

**0.5B still failing:**
- Step 1 STILL dropped "one per line" from the Create step. It only appeared in Verify. The 7B wrote `print(result)` (prints a list) because step 1 just said "prints the first n Fibonacci numbers." The rule "MUST include ALL user-specified features: args, output format..." didn't stick. The model captured the format requirement in the wrong step.

---

**7B Step 1 (Create):**
- First attempt: "Created /path/to/fibonacci.py" as text — still no tool, still failing
- Retry: `write_file` called correctly ✓ — mapping worked on retry

**7B Step 2 (Run: python fibonacci.py 20) — REGRESSION:**
- First attempt: hallucinated the output as a code fence (same as before)
- Retry: called `write_file` — **rewrote the file instead of running it**
- After the write, responded with 9 tokens: "Run: python fibonacci.py 20" as plain text — no tool at all
- Script was **never actually executed**

Root cause of regression: The 7B noticed from the Verify step description ("print one per line") that the file it wrote has a bug (`print(result)` prints a list). So on the "Run:" retry, it decided to "fix" the file first via `write_file` instead of running `shell`. The model is treating the mapping rule as optional when it detects a perceived inconsistency. The `Run:` → `shell` mapping lost to the model's own judgment about what the task "needs."

This reveals a deeper problem: **the 7B model reasons across steps holistically rather than executing each step literally.** It saw that running the current file would produce wrong output and tried to fix it. Smart behavior in isolation, but breaks the step-execution contract.

**7B Step 3 (Verify):**
- Hallucinated the entire output: "The output of `python fibonacci.py 20` is: [numbers one per line]"
- No shell call — still no actual execution
- The output it hallucinated was coincidentally correct (one per line) because the Verify description told it what to expect — the model used the Verify text as a template for its fake output

**Net result:** fibonacci.py was written but never run. The user got back fake output. The script itself still has `print(result)` which would print a list not one per line.

---

## CHANGES APPLIED — 2026-03-27 (v1 → v2)

**0.5B (`core/plannd.py · PLANNER_PROMPT`):**
1. Locked down "Verify:" — added explicit rule: `'Verify:' means describe what to confirm — never a command`
2. Added deduplication rule: `Each step must be unique. Never repeat the same action in different words.`
3. Reinforced step 1: `MUST include ALL user-specified features: args, output format, file saves, timestamps`
4. Added pytest rule: `Use 'pytest' for test files, not 'python'`
5. Updated the example to include output format detail ("prints each stat on its own line")

**7B (`prompts/system_prompt.py · SYSTEM_PROMPT`):**
1. Added explicit PLAN STEP → TOOL MAPPING block (Create/Write → write_file, Run: → shell, Verify: → shell+confirm, Patch/Update → patch_file)
2. Added: `NEVER write prose, explanations, or code blocks before the tool call.`
3. Added: `ONLY use tools from the list above. Never invent a tool name.`
4. Added: `After a shell tool runs, do NOT repeat its output as text.`
5. Added patch_file guidance for unique old_str
6. Removed "ACT, don't explain" — replaced by mapping block

---

## CHANGES APPLIED — 2026-03-27 (v2 → v3)

**7B (`prompts/system_prompt.py · SYSTEM_PROMPT`):**
1. Moved the step→tool mapping to the very top of the prompt — before the tool list — so it gets maximum attention weight
2. Reformatted the mapping as a compact aligned table (visual lookup, not prose) so the model pattern-matches it faster
3. Added hard line for `Run:`: "do NOT rewrite the file, do NOT predict output, do NOT fix bugs first. Just run it." — directly addresses the session 2 regression
4. Added hard line for `Verify:`: "never describe or predict the result" — addresses the hallucinated output on Verify steps
5. Added: "Your first output token must be `<tool>`" — clearest possible instruction for no-prose-first
6. Kept "ONLY use tools from this list. Never invent a tool name." in-line with the tool list
7. Trimmed the RULES section — removed redundancy now that the mapping covers the main cases

**0.5B (`core/plannd.py · PLANNER_PROMPT`):**
1. Expanded the Create step rule into a dedicated block explaining WHY output format must go in Create (because "the Create step drives the code")
2. Added a WRONG vs RIGHT anti-pattern example directly in the prompt using the fibonacci case — shows the exact failure mode observed in sessions 1 and 2
3. Kept all v2 improvements (Verify: definition, deduplication, pytest rule)

---

---

## SESSION 3 FINDINGS — 2026-03-27 (v3 prompts)

**Task:** Same fibonacci.py task — Create, Run

**0.5B plan produced (v3):**
```
1. Create fibonacci.py that accepts an argument for the number of Fibonacci numbers to generate.
2. Run: python fibonacci.py <number>
```

**0.5B — what changed:**
- No improvement. 3 sessions, same core failure.

**0.5B new failures:**
- Step 1 STILL dropped "one per line". The WRONG/RIGHT example did not help. The 0.5B generated the same step 1 as session 1 word for word, ignoring the anti-pattern example entirely.
- Step 2 used `<number>` as a literal placeholder instead of `20`. The prompt says "exact argument from user request" — the model produced a template token. The 7B then ran `python fibonacci.py 10` (filled in its own guess).
- Only 2 steps — no Verify. Acceptable since user didn't explicitly ask to verify, but plan is thin.

---

**7B Step 1 (Create) — new failure mode, but also real progress:**

First attempt output:
```
write_file
{"path": "fibonacci.py", "content": "..."}
```
`[Recursive] No tool call found — forcing tool retry`

Retry output:
```
write_file
{"path": "fibonacci.py", "content": "..."}
```
`[Recursive] No tool call found — forcing tool retry` (again, identical)

**What changed from sessions 1 and 2:** The model now correctly identifies `write_file` for a Create step — no more "Created /path/to/file.py" prose. Tool selection is fixed.

**New problem:** The format is wrong in two ways:
1. No `<tool>...</tool>` wrapper — the model outputs the tool name on its own line followed by raw JSON
2. The JSON uses flat args `{"path": "...", "content": "..."}` instead of the required `{"name": "write_file", "args": {"path": "...", "content": "..."}}`

The model is pattern-matching from two places: the mapping table gives it the tool name, the TOOLS list gives it the arg shape. It combines them directly without applying the TOOL FORMAT wrapper. The abstract template `{"name": "TOOL_NAME", "args": {"key": "value"}}` is not concrete enough for the model to replicate correctly.

**Net result:** File was never written. Neither tool call was parsed. The model went to step 2 as if step 1 succeeded.

---

**7B Step 2 (Run:) — correct tool, same format failure:**

First attempt:
```
shell
{"command": "python fibonacci.py 10"}
```
Retry: identical.

**What changed:** Model correctly picked `shell` for a `Run:` step — no hallucinated output, no `write_file` regression. The hard `Run:` line worked for tool selection.

**Same problem:** Still no `<tool>` wrapper, still flat JSON. And used `10` (its own guess) since the 0.5B gave `<number>` as the argument.

**Net result:** Shell command never executed. Nothing in this session actually ran.

---

**Root cause of session 3 failure — FORMAT, not logic:**

The model now knows which tool to use for each step word. That's solved. The remaining blocker is that the TOOL FORMAT section uses abstract placeholders (`TOOL_NAME`, `key`, `value`) which the model cannot pattern-match reliably into a concrete output. It needs to see a real example of a complete, correctly formatted tool call to copy from.

---

---

## SESSION 4 FINDINGS — 2026-03-27 (v4 prompts)

**Task:** Same fibonacci.py — Create, Run

**0.5B plan produced (v4):**
```
1. Create fibonacci.py that accepts n and generates Fibonacci numbers
2. Run: python fibonacci.py 20
3. Create fibonacci.py that accepts n and prints each Fibonacci number on its own line
4. Run: python fibonacci.py 20
```

**0.5B — progress:**
- `Run:` steps now use `20` instead of `<number>` — FIXED ✓

**0.5B — new failure (introduced by v4 prompt):**
The BAD/GOOD example backfired. The 0.5B is too small to understand "here is what NOT to do" — it treated both the WRONG and RIGHT example lines as valid plan steps and executed them sequentially. Step 1 came from the WRONG example ("generates Fibonacci numbers") and step 3 came from the RIGHT example ("prints each Fibonacci number on its own line"). The model ran the bad plan AND the good plan back to back.

This is a fundamental constraint of 500M parameter models: showing a counterexample inside a prompt risks teaching the model to do the wrong thing, not avoid it. The BAD example must be removed entirely.

---

**7B Step 1 (Create) — first attempt:**
```
<tool>
{"name": "write_file", "args": {"path": "fibonacci.py", "content": "..."}}
</tool>
```
`<tool>` format correct on first attempt — NO RETRY NEEDED ✓

File written successfully. Tool selection correct, format correct.
Code still has `print(result)` (list) because step 1 came from the WRONG 0.5B example — but the 7B did exactly what it was told.

**7B Step 2 (Run: python fibonacci.py 20) — first attempt:**
```
<tool>
{"name": "shell", "args": {"command": "python fibonacci.py 20"}}
</tool>
```
Format correct ✓. Shell ran. Output: `[0, 1, 1, 2, ...]` (list — expected since step 1 wrote wrong code).

**7B Step 2 — unsolicited extra tool call after success:**
After the shell returned output, the model called `pytest test_scripts.py` unprompted. The "don't repeat output as text" rule worked (no prose echo), but the model compensated by doing additional work instead. It ran pytest on a leftover test file from a prior session, got an import error, tried to patch it with an empty `old_str`, hit max retries, and escalated to Gemini — which was rate-limited and couldn't run shell commands anyway.

Root cause: after a successful shell call, the model should stop. Instead it scanned loaded file context (which included `test_scripts.py`) and decided to run tests unprompted. There is no rule saying "when a step completes successfully, do nothing more."

**7B Step 3 (Create - "prints each Fibonacci number on its own line"):**
Format correct ✓. Code now uses `print(a)` inside the loop — correct one-per-line output. File written.

**7B Step 4 (Run: python fibonacci.py 20):**
Format correct ✓. Shell ran. Output: 20 numbers, one per line — TASK COMPLETE ✓

After the shell, model responded with: `Run: python fibonacci.py 10` — trailing plain text after successful completion. Rule "don't repeat output" prevented prose but didn't prevent the model generating a new unsolicited step.

---

**Net result session 4:**
- Task eventually succeeded — 20 fibonacci numbers, one per line ✓
- `<tool>` format works consistently on first attempt — MAJOR fix confirmed ✓
- `Run:` → `shell` correct, no regression ✓
- `<number>` placeholder fixed ✓
- But: 4 steps instead of 2, wasted inference, unsolicited pytest run, Gemini fallback triggered
- The task succeeded by accident — the 0.5B's confused 4-step plan happened to fix the bug in step 3

---

---

## SESSION 5 FINDINGS — 2026-03-27 (v5 prompts)

### Task 1: fibonacci.py — PASS ✓

**0.5B plan:**
```
1. Create fibonacci.py that accepts n and prints each Fibonacci number on its own line
2. Run: python fibonacci.py 20
```
First clean plan in 5 sessions. Output format in step 1 ✓. Correct argument ✓. 2 steps ✓.

**7B execution:**
- Step 1: `<tool>` format correct, first attempt, `print(a)` inside loop, one per line ✓
- Step 2: `<tool>` format correct, shell ran, 20 numbers one per line ✓
- After shell: `"No further actions required. The Fibonacci numbers have been printed as requested."` — trailing text, but benign (no extra tool call). Minor.

**Result: Task completed correctly, cleanly, in 2 steps.**

---

### Task 2: wordcount.py — FAIL

**0.5B plan:**
```
1. Create wordcount.py that accepts a filename argument.
2. Run: python wordcount.py data.py
3. Verify: results.json contains exactly 5 entries with timestamps, each entry containing
   the total words, lines, and characters in the original file.
```

**0.5B failures:**
1. **Step 1 massively truncated** — "accepts a filename argument" is the entire Create step. Missing: counts words/lines/characters, saves to results.json with timestamp, prints clean summary. The 0.5B only captured the first feature and dropped everything else.
2. **Used `data.py` from the example** — the prompt example uses `run on data.py twice`. The model copied `data.py` instead of `fibonacci.py` from the user's actual request.
3. **"5 entries" instead of "2 entries"** — confabulated wrong count. User asked to run twice = 2 entries.
4. **Missing second Run step** — user explicitly asked to "run it again on the same file". Only one Run: step generated.

Root cause: the 0.5B is doing template-filling from the prompt examples, not reasoning about the user's request. When the task matches the example closely (fibonacci), it works. When the task is complex and multi-featured (wordcount), the model truncates step 1 to the first feature and copies artifacts from the examples (filenames, counts).

---

**7B Step 1 (Create wordcount.py):**
- Format correct ✓, file written ✓
- But code only counts words — no lines, no characters, no JSON save, no timestamp, no clean summary
- The 7B implemented exactly what the incomplete step 1 said. It did its job; the plan was wrong.
- Critique gave quality 8/10 — did not catch the missing features

**7B Step 2 (Run: python wordcount.py data.py) — new regression:**

First attempt: `"No further actions required. The number of words in the file has been printed as requested."`

The "One step = one tool call = stop" rule backfired. The model interpreted "stop" as permission to skip the tool call entirely if it believes the step is already complete. It produced a plain-text completion response instead of a shell call.

Retry: called `shell` correctly, but `data.py` doesn't exist → FileNotFoundError.
Auto-retry: model patched `open(filename)` → `open(args.filename)` — wrong fix. The bug was a missing file, not a variable name. The model misread the traceback.
After patch: output `"Run: python wordcount.py data.py"` as plain text — no tool call.

**7B Step 3 (Verify) — format regression:**
```
shell {"command": "cat results.json"}
```
No `<tool>` wrapper. The Verify step reverted to the old wrong format from session 3. Verify is the step the model is least certain about (it has to invent its own check command), and uncertainty causes it to fall back to an older output pattern. No Verify example exists in the concrete examples section of the prompt.

---

---

## SESSION 6 FINDINGS — 2026-03-27 (v6 prompts)

### Task 1: fibonacci.py — PASS ✓ (second clean run)
Plan correct, code correct, shell ran, output correct. Trailing "Next action or final answer:" text persists but benign.

### Task 2: wordcount.py — FAIL (complete collapse)

**0.5B plan (v6):**
```
1. Create wordcount.py that accepts a filename argument.
2. Run: python wordcount.py data.txt
3. Verify: results.json contains exactly 5 entries with timestamps...
```
- Step 1 still truncated to first feature only — "accepts a filename argument." ← same failure as session 5. The rule "include EVERY feature" had zero effect.
- `data.txt` — not from the user's request, not from the renamed examples (tracker.py/notes.py). The model invented a new wrong filename. Renaming the examples didn't fix this; the model generates plausible-looking filenames regardless.
- "5 entries" — wrong count again.
- Still only one Run step (user asked for two runs).

**Assessment:** After 6 sessions and 4 different rule formulations, the 0.5B cannot reliably expand the Create step beyond the first feature for complex tasks. This is a fundamental 500M model limitation, not a wording problem. A different structural approach is needed.

---

**7B Step 1 — Create step completely derailed:**
The existing wordcount.py (498 chars from a previous session) was auto-loaded as context. The 7B saw the file already existed and chose to verify it rather than overwrite it.

- Attempt 1: `"Created /path/to/wordcount.py"` — plain text (no tool). Reverted to session 1 behavior.
- Retry: called `shell {"command": "python wordcount.py --help"}` — wrong tool entirely (shell not write_file for a Create step). The `Create → write_file` mapping was abandoned when the model decided the file "already existed."
- Then made 2 MORE unsolicited shell calls: ran wordcount on fibonacci.py, ran wordcount on wordcount.py.
- Then: `"The word counts have been verified. No further actions required."` — declared done without ever writing the file.

Root cause: The mapping `Create → write_file` has an implicit exception in the model's logic: "unless the file already exists in context." There is no rule saying "Create always means write_file — even if the file is already loaded."

**7B Step 2 — hallucination returned and wrong command:**
- Attempt 1: `"Next action or final answer: The number of words in data.txt is: 10"` — hallucinated output. The hallucination pattern returned. The `"Next action or final answer:"` prefix is a template the model generates when it expects to wait for input — it's learned this from training data in agentic contexts.
- Retry: called `shell {"command": "python fibonacci.py 20"}` — completely wrong command. Should be `python wordcount.py data.txt`.

**7B Step 3 — Verify: format correct ✓:**
- Called `shell {"command": "cat results.json"}` — correct format, correct command, first attempt ✓
- The `cat results.json` concrete example in the prompt is working for Verify steps.
- results.json didn't exist (wordcount.py was never written), so it errored. Auto-retry output plain text.

---

---

## SESSION 7 FINDINGS — 2026-03-27 (v7 prompts)

**Task:** fibonacci.py only (session ended after step 2 failed, no wordcount tested)

**0.5B plan (v7):** Perfect for 3rd consecutive session ✓
```
1. Create fibonacci.py that accepts n and prints each Fibonacci number on its own line
2. Run: python fibonacci.py 20
```

**7B Step 1 (Create) — correct ✓**
`<tool>` format, first attempt, correct code, file written.

**7B Step 2 (Run:) — format regression, AGAIN**
```
shell
{"command": "python fibonacci.py 20"}
```
No `<tool>` wrapper. Same failure as session 3. Both attempts identical. Shell never ran.
Review gave quality 5/10 and hit max depth — even the reviewer noticed something was wrong but accepted the draft anyway.

**Root cause:** The 7B has two competing format patterns in its weights for `shell` calls:
- Pattern A (correct): `<tool>{"name": "shell", "args": {"command": "..."}}</tool>`
- Pattern B (wrong): `shell\n{"command": "..."}` — likely from training data

The concrete examples section shows the correct pattern. But the model's inference is non-deterministic: sometimes it selects Pattern A (sessions 4, 5), sometimes Pattern B (sessions 3, 7). The `write_file` pattern is stable because it appears earlier in the examples and is a less common pattern in training data. `shell` is a common tool name across many frameworks and has many competing format patterns.

**Key insight:** Showing the example in a separate "Concrete examples" block is not enough to anchor `shell` calls. The model pattern-matches the trigger ("Run:") to `shell`, then falls back to training data for the output format. The fix is to put a format example directly inline with the Run: mapping rule — so the trigger and the correct output format are seen together in one shot.

---

---

## SESSION 8 FINDINGS — 2026-03-27 (v8 prompts)

### Task 1: fibonacci.py — PASS but noisy

0.5B plan correct for 4th consecutive session ✓. 7B step 1 correct ✓. Step 2 shell format correct first attempt ✓ — the v8 inline example fix worked.

But after the shell ran successfully, the model kept generating tool calls:
```
shell {"command": "cat fibonacci.py"}         ← unsolicited
shell {"command": "python fibonacci.py 10"}   ← unsolicited, wrong argument
shell {"command": "cat fibonacci.py"}         ← unsolicited again
"Task completed."                             ← plain text to break loop
```

**Root cause — architectural deadlock:** The rule "no text after the tool call" combined with "the loop calls the model again after every tool result" creates a loop the model can only exit by generating more tool calls. In earlier sessions the model escaped via "No further actions required." text — but we banned that text. Now it generates tool calls instead, which re-trigger the loop. Eventually it outputs "Task completed." text to stop.

The fix: we need to allow one specific completion text to signal the end of a step. "Done." — short, unambiguous, breaks the loop cleanly without being prose or hallucination.

### Task 2: wordcount.py

**0.5B plan (v8):**
```
1. Create wordcount.py that accepts a filename argument.
2. Run: python wordcount.py fibonacci.py
3. Verify: results.json contains exactly 2 entries with timestamps and prints a clean summary.
```

**0.5B progress:**
- `fibonacci.py` — correct filename for the first time ✓ (v7 "copy exact filename" rule worked)
- "2 entries" — correct count ✓ (v7 changes worked)
- Still only one Run step (missing the second run the user asked for)
- Step 1 STILL truncated to "accepts a filename argument." — 8 sessions unresolved

**7B Step 1 — first attempt still fails when file is in context:**
- Attempt 1: "Created /path/to/wordcount.py" — plain text. The "even if it already exists" clarification in the mapping didn't stop this. The model's first-attempt failure for Create when a file is already loaded is persistent.
- Retry: `write_file` called, file written ✓ — but code only counts words (because step 1 was truncated)

**7B Step 2 — hallucination + wrong command:**
- Attempt 1: "The number of words in fibonacci.py is: 45" — hallucinated count
- Retry: called `shell {"command": "python fibonacci.py 20"}` — WRONG FILE. The model fell back to the last successful shell command it had seen (fibonacci.py 20 from step 1) instead of the plan's command (wordcount.py fibonacci.py). User declined, loop broke.

**7B Step 3 (Verify) — format correct ✓:**
- `shell {"command": "cat results.json"}` first attempt ✓. results.json doesn't exist so it errored. Auto-retry output plain text "Created /path/to/results.json" — nonsense.

---

## KEY INSIGHTS SUMMARY (updated after session 8)

| Issue | Model | Status | Severity |
|---|---|---|---|
| 0.5B truncates Create step for complex tasks | 0.5B | 8 sessions unresolved — structural limit | Critical |
| 7B extra tool calls after successful step — arch deadlock | 7B | Getting worse (s8: 3 extra calls) | High |
| 7B Create first-attempt text when file in context | 7B | Persists despite "even if exists" rule | High |
| 0.5B missing second Run step for "run twice" | 0.5B | Persists | Medium |
| 7B wrong command on retry after hallucination | 7B | Returned in s8 | Medium |
| 0.5B filename now correct (fibonacci.py) | 0.5B | Fixed ✓ (v7) | — |
| 0.5B entry count now correct (2) | 0.5B | Fixed ✓ (v7) | — |
| 7B Run: shell format — inline example fixed it | 7B | Fixed ✓ (v8) | — |
| 7B shell format intermittent | 7B | Fixed ✓ (v8) | — |
| fibonacci: 4 consecutive correct runs | Both | Stable ✓ | — |
| 7B Verify: format correct (cat results.json) | 7B | Fixed ✓ (v6) | — |
| 0.5B `<number>` placeholder | 0.5B | Fixed ✓ (v4) | — |
| 0.5B "Verify:" is a description not a command | 0.5B | Fixed ✓ | — |
| 0.5B duplicate/repeating steps | 0.5B | Fixed ✓ | — |

---

## OPEN PROBLEMS

### Problem 1 — 7B outputs tool name + flat JSON without `<tool>` wrapper
The model knows the right tool but can't format it. The TOOL FORMAT template is too abstract. Needs concrete examples:
```
<tool>
{"name": "write_file", "args": {"path": "hello.py", "content": "print('hello')"}}
</tool>
```
```
<tool>
{"name": "shell", "args": {"command": "python hello.py"}}
</tool>
```
The model needs to see the actual pattern, not `TOOL_NAME` / `key` / `value` tokens.

### Problem 2 — 0.5B drops output format from Create step — 3 sessions unresolved
The WRONG/RIGHT example had zero effect. The rule has been stated four different ways. Hypothesis: the 0.5B model (500M params) cannot follow conditional rules reliably at prompt-read time — it pattern-matches the most common "Create X.py" completion from training data and ignores the instruction. The step format template itself needs to force the output format to be included, so the model can't omit it:
```
Create <file>.py that <features> and prints output <format: "one per line" / "as a list" / etc>
```

### Problem 3 — 0.5B uses `<number>` placeholder instead of copying actual value
The model templates the Run: step instead of filling in the real argument. Needs an explicit rule: "Never use angle-bracket placeholders. Copy the exact value from the user's request word for word."

---

## CHANGES APPLIED — 2026-03-27 (v8 → v9)

**7B (`prompts/system_prompt.py`):**
Replaced the deadlocked stop rule with an explicit completion signal:
```
After the tool runs: if it succeeded with no error, respond with exactly the word Done. — nothing else.
If the tool errored, respond with a single tool call to fix it.
Never call extra tools to inspect, verify, or re-run after a step succeeds.
```
Previously: "no text after" + banned phrases → model kept calling tools to exit the loop.
Now: "Done." is the explicit exit signal. It's one word, not prose, not a hallucination, and it breaks the orchestrator loop cleanly. The "never call extra tools after success" rule names the exact behavior to stop.

**0.5B (`core/plannd.py`):**
Changed the Create step template from sentence format to colon + comma list format:
```
Old: Create <file>.py that <paste every feature the user listed, comma-separated>
New: Create <file>.py: accepts <input>, <feature1>, <feature2>, ..., prints <format>
```
The "that ..." sentence format has a natural stopping point after the first feature ("accepts a filename argument."). The colon + comma list format keeps the model in list-generation mode — commas signal "keep going" rather than sentence completion. The example also uses this format: `Create fib.py: accepts n, prints each Fibonacci number on its own line`

---

## CHANGES APPLIED — 2026-03-27 (v7 → v8)

**7B (`prompts/system_prompt.py`) — one change:**

Put the shell format example inline with the Run: and Verify: mapping rows:
```
Run: <cmd>   →  shell   output: <tool>{"name": "shell", "args": {"command": "<cmd>"}}</tool>
Verify: ...  →  shell   output: <tool>{"name": "shell", "args": {"command": "cat file.json"}}</tool>
```

**Why:** The model pattern-matches the trigger word ("Run:") to the tool name ("shell"), then separately decides on the output format. These are two independent decisions and the format decision sometimes falls back to training data (`shell\n{...}`). By putting the exact expected output on the same line as the trigger, both decisions are resolved in one token sequence — the model sees `Run:` and immediately has the full correct output pattern directly after it, with no gap where the wrong format can be substituted.

This is a different strategy from the separate "Concrete examples" block — those examples show format in isolation. The inline approach shows trigger→format as a single fused unit.

---

## CHANGES APPLIED — 2026-03-27 (v6 → v7)

**7B (`prompts/system_prompt.py`):**
1. Added `"Never output phrases like 'Next action', 'final answer', or 'No further actions' — these are not tool calls and are never valid responses."` — directly names the exact text patterns appearing in the trailing output.
2. Updated Create mapping: `"always write the complete file — even if it already exists in context"` — closes the loophole where the model saw an existing file and skipped write_file.
3. Cleaned up Run: mapping: merged the two existing notes into one tighter line.

**0.5B (`core/plannd.py`):**
1. Changed the Create step instruction from "include EVERY feature" (failed 4 times) to a structural approach: `"paste ALL features the user asked for as a comma-separated list inside one step"` with an explicit checklist of what to look for: what file to accept, what to count/process, what file to save to, whether to timestamp, how to print output.
2. Rule 2 is now more directive for the filename: `"copy the exact filename and argument from the user's message word for word. Do not invent a filename. If the user says 'run it on fibonacci.py', write 'fibonacci.py'."` — previous rule said "never copy from examples" which didn't stop the model inventing new filenames entirely.
3. Changed the second example to use `wc.py`/`main.py`/`out.json` — short, distinct names unlikely to collide with real project files or anything in the model's memorized training patterns.

---

## CHANGES APPLIED — 2026-03-27 (v5 → v6)

**7B (`prompts/system_prompt.py`):**
1. Added a third concrete example: `{"name": "shell", "args": {"command": "cat results.json"}}` — gives the model a pattern to copy when it reaches a Verify step (the step type where format regression kept occurring).
2. Replaced `"One step = one tool call = stop"` with: `"Every step requires exactly one tool call. Call the tool, then stop — no text before, no text after, no second tool call. You may never skip a step by outputting text instead of a tool call."` — explicitly prevents the "No further actions required" skip behaviour from session 5.

**0.5B (`core/plannd.py`):**
1. Rule 1 now says "include EVERY feature from the user's request in one step" and "do not split features across multiple Create steps and do not drop any feature" — addresses the truncated step 1 on wordcount.
2. Rule 2 now explicitly says "Never copy filenames from the examples below — use what the user said." — addresses `data.py` being copied from the prompt example into the actual plan.
3. Renamed the example files from `stats.py`/`data.py` to `tracker.py`/`notes.py` — makes the example filenames clearly distinct from any real project files and harder to accidentally copy-paste.

---

## CHANGES APPLIED — 2026-03-27 (v4 → v5)

**7B (`prompts/system_prompt.py`):**
- Replaced "Do not write any text before or after" with: `"The <tool> block is your entire response — no text before it, no text after it, no second tool call. One step = one tool call = stop."` — directly addresses the unsolicited `pytest` call and trailing "Run: python..." text from session 4.

**0.5B (`core/plannd.py`):**
- Removed the WRONG example entirely. A 500M model treats counterexamples as valid plan steps — it copied the WRONG step 1 as step 1 and the RIGHT step 1 as step 3, producing a 4-step plan that ran both. Only the RIGHT examples remain.

---

## CHANGES APPLIED — 2026-03-27 (v3 → v4 — full rewrite)

### 7B (`prompts/system_prompt.py · SYSTEM_PROMPT`) — v4

**Core change:** Replaced the abstract TOOL FORMAT template with two concrete copy-paste examples at the top of the prompt — one `write_file`, one `shell`. The model no longer has to combine the mapping table + tool list into a format it has never seen concretely. It can pattern-match directly from the examples.

Structure of v4:
1. Identity (1 line)
2. "YOUR RESPONSE IS ALWAYS ONE TOOL CALL" + abstract template
3. **Two concrete examples** — `write_file` and `shell` with real paths/commands
4. "Do not write any text before or after the `<tool>` block" — explicit single sentence
5. STEP WORD → TOOL mapping (kept from v3 — tool selection was working)
6. AVAILABLE TOOLS list (lean, reference only)
7. RULES (trimmed — removed anything covered by the examples or mapping)

What was removed: the verbose "Run: do NOT rewrite the file" and "Verify: never describe" sentences — the mapping table already says "run the exact command given" and "run a command to check" inline, which is tighter.

### 0.5B (`core/plannd.py · PLANNER_PROMPT`) — v4

**Core changes:**
1. **Step template for Create now includes output format as a structural slot:** `Create <file>.py that <features> and prints <output format>` — the slot is in the template itself, not a rule the model has to apply conditionally
2. **Rule 2 directly addresses the `<number>` placeholder failure:** "copy the exact value from the user's request. Never write `<number>` or `<arg>` — use the real value (e.g. 20, not `<number>`)"
3. **Two examples — both show the BAD and GOOD side by side** using the fibonacci case (the exact task that failed 3 sessions in a row). Bad example shows both failure modes simultaneously: missing "one per line" AND `<number>` placeholder
4. Added a second full example (stats.py) to show the complete multi-run-verify pattern
5. Rules are numbered 1–6 and short — easier for a 500M model to follow than prose paragraphs

---

## SESSION 9 FINDINGS — 2026-03-27 (v9 prompts)

### Task 1: fibonacci.py — PASS ✓ (with minor noise)

**0.5B plan (v9):**
```
1. Create fib.py: accepts n, prints each Fibonacci number on its own line
2. Run: python fibonacci.py 20
3. Verify: The output should be:
```

**0.5B — colon format BREAKTHROUGH:**
- Step 1 is fully expanded for the first time ✓ — the colon + comma list format worked. The model stayed in list-generation mode instead of stopping at the first sentence boundary.
- Correct argument `20` in Run step ✓
- **New failure: wrong filename in Run step** — step 1 uses `fib.py` (from the example in the prompt), step 2 uses `fibonacci.py` (from the user's message). The model mixed the example filename into one step and the user filename into the other. The 0.5B is still pulling filenames from the prompt examples rather than consistently using the user's actual filename.
- **New noise: spurious truncated Verify** — step 3 is `Verify: The output should be:` with no content after the colon. The model started a Verify step it couldn't complete — suggests max_tokens or sentence-boundary truncation hit mid-step.

**7B execution:**
- Step 1: `write_file` called, code correct (`print(a)` inside loop), file written ✓
- Step 2: `shell` format correct, ran `python fibonacci.py 20`, output 20 numbers one per line ✓
- After success: `Done.` — **no extra tool calls** ✓ — the "Done." exit signal worked perfectly. This is the first clean stop in any session.
- Truncated/empty Verify step was gracefully skipped by the orchestrator.

**Result: Task completed correctly, cleanly, with no extra tool calls. fibonacci.py stable for 5th consecutive session.**

---

### Task 2: wordcount.py — FAIL (new failure modes)

**0.5B plan (v9):**
```
1. Create wc.py: accepts a filename, counts words, lines, and characters,
   appends result with timestamp to out.json, prints a clean summary
2. Run: python wc.py main.py
3. Run: python wc.py main.py
4. Verify: out.json contains exactly 2 entries with timestamps
```

**0.5B — what worked:**
- Step 1 is **fully expanded** ✓ — all features listed: words, lines, characters, timestamp, JSON append, clean summary. This is the first time in 9 sessions that step 1 for the wordcount task contains ALL the features the user asked for. The colon format solved the truncation problem.
- Two Run steps ✓ — first time the second run was included. The example pattern for "run twice" finally registered.
- Correct Verify ✓ — describes the expected outcome, not a command.

**0.5B — still failing:**
- **Wrong filename throughout** — every step uses filenames from the prompt examples (`wc.py`, `main.py`, `out.json`) instead of what the user asked for (`wordcount.py`, `fibonacci.py`, `results.json`). The rule "copy the exact filename from the user's message" is not overriding the example-copying instinct.
- Root cause: the wc.py example in the PLANNER_PROMPT is too similar to the actual wordcount task — the 0.5B matches the example as a template and fills in the example's filenames. The example needs either very different names or the rule needs to be architectural (see proposed fix below).

---

**7B Step 1 (Create wc.py) — first attempt fails when file in context:**
- The loaded file context contained the previous `wordcount.py`. The 7B read this as "file already exists — I don't need to create it."
- Attempt 1: `"No further actions required. The wordcount.py file already contains the required functionality."` — skipped the tool entirely.
- Retry: called `write_file` correctly, created `wc.py` ✓

**7B Step 2 (Run: python wc.py main.py):**
- `main.py` doesn't exist in the working directory.
- shell ran: `FileNotFoundError: [Errno 2] No such file or directory: 'main.py'`
- **"Done." used to skip error recovery** — model output `Done.` after the FileNotFoundError instead of fixing the command. This is a new failure mode introduced by the "Done." signal: the model treats any completed tool call as "success" and outputs `Done.`, even when the shell returned an error.
- Root cause: the rule says "if it succeeded with no error, respond with exactly the word Done." — but the model is not reliably distinguishing between shell exit 0 and shell exit 1. It pattern-matches "tool call completed" → `Done.` without checking the output for error text.

**7B Step 3 (second Run: python wc.py main.py) — SyntaxError in generated code:**
- After the first `Done.` skip, the orchestrator moved to step 3.
- Shell ran `python wc.py main.py` again: `SyntaxError: f-string expression part cannot include a backslash`
- The 7B had written the print summary using an f-string with `\n` inside it — invalid in Python 3.11 and earlier.
- **"Done." used again to skip error recovery** — same failure as step 2. Two consecutive errors, two `Done.` skips. No attempt to fix the code.

**7B Step 4 (Verify: out.json contains 2 entries):**
- `shell {"command": "cat out.json"}` — format correct ✓
- `out.json` didn't exist (wc.py never ran successfully). Error returned.

**Net result session 9 wordcount:**
- 0.5B plan structure is now correct (all features, two runs, good Verify) ✓
- But wrong filenames caused shell failures
- "Done." signal incorrectly used to skip both error recoveries — wordcount never ran

---

## KEY INSIGHTS SUMMARY (updated after session 9)

| Issue | Model | Status | Severity |
|---|---|---|---|
| 0.5B copies filenames from examples, not user's message | 0.5B | 9 sessions unresolved — worsened in v9 (now uses exact example names) | Critical |
| 7B "Done." skips error recovery — treats all tool results as success | 7B | New in v9 | Critical |
| 7B Create first-attempt text/skip when file is in context | 7B | Persists despite rules | High |
| 0.5B missing second Run step for "run twice" | 0.5B | **Fixed ✓ (v9)** | — |
| 0.5B Create step truncated to first feature | 0.5B | **Fixed ✓ (v9) — colon format breakthrough** | — |
| 7B extra tool calls after successful step | 7B | **Fixed ✓ (v9) — "Done." signal works for success** | — |
| 7B Run: shell format — inline example fixed it | 7B | Fixed ✓ (v8) | — |
| 0.5B filename in Run: sometimes wrong | 0.5B | Regressed in v9 — example filenames override user's | High |
| 7B wrong command on retry after hallucination | 7B | Persists | Medium |
| fibonacci: 5 consecutive correct runs | Both | Stable ✓ | — |
| 7B Verify: format correct (cat results.json) | 7B | Fixed ✓ (v6) | — |
| 0.5B `<number>` placeholder | 0.5B | Fixed ✓ (v4) | — |
| 0.5B "Verify:" is a description not a command | 0.5B | Fixed ✓ | — |
| 0.5B duplicate/repeating steps | 0.5B | Fixed ✓ | — |

---

## ARCHITECTURAL DISCUSSION — post session 9

### Proposed: 7B receives BOTH the 0.5B plan AND the original user prompt

**Problem it solves:**
The 7B currently treats the 0.5B plan as a rigid script. When the plan is wrong (wrong filename, missing feature, wrong file), the 7B executes it faithfully and fails. The 7B has no way to cross-reference the plan against what the user actually asked for.

**Proposed change:**
Pass both inputs to the 7B:
1. The 0.5B plan (numbered steps)
2. The original user prompt

Frame the 0.5B plan explicitly as a *guide* — not a transcript to execute. Something like:
```
## User Request
Create wordcount.py that accepts a filename...

## Suggested Plan (use as a guide — verify against the User Request)
1. Create wc.py: accepts a filename...
2. Run: python wc.py main.py
...
```

Then instruct the 7B:
```
The Suggested Plan is a rough guide. Before executing each step, cross-reference it against
the User Request. If the plan uses the wrong filename, fix it. If the plan is missing a feature
the user asked for, add it. The User Request is authoritative.
```

**Why this addresses the root failures:**
- Wrong filename in Run steps: 7B sees the plan says `main.py` but user said `fibonacci.py` → uses `fibonacci.py`
- Missing features in Create step: 7B sees user asked for JSON save but plan step omits it → adds it anyway
- Spurious steps: 7B sees extra steps that don't correspond to anything in the user request → skips them

**Risk:**
- Adds tokens to every inference call (~200-400 tokens for the user prompt repeat)
- May cause 7B to "freelance" on tasks where the plan was correct
- The 7B needs clear precedence rules — plan is a guide, user request is authoritative

**Status:** Implemented — see CHANGES APPLIED v9 → v10 below.

---

## CHANGES APPLIED — 2026-03-27 (v9 → v10)

Two targeted changes. Everything else is unchanged from v9.

---

### Change 1 — `prompts/system_prompt.py` · SYSTEM_PROMPT

**What changed:** Added 2 lines after the STEP WORD → TOOL block.

**Lines added (after the `Patch / Update` row, before the blank line that precedes AVAILABLE TOOLS):**
```
The "Current step" is a guide from a planning model. The "Overall goal" is authoritative — if they differ on filenames or features, follow the Overall goal.
```

**Before (v9):**
```
STEP WORD → TOOL (no exceptions, no substitutions):
  Create / Write  →  write_file   (always write the complete file — even if it already exists in context)
  Run: <cmd>      →  shell        output: <tool>{"name": "shell", "args": {"command": "<cmd>"}}</tool>
  Verify: ...     →  shell        output: <tool>{"name": "shell", "args": {"command": "cat file.json"}}</tool>
  Patch / Update  →  patch_file   (edit existing file — include enough context in old_str to be unique)

AVAILABLE TOOLS:
```

**After (v10):**
```
STEP WORD → TOOL (no exceptions, no substitutions):
  Create / Write  →  write_file   (always write the complete file — even if it already exists in context)
  Run: <cmd>      →  shell        output: <tool>{"name": "shell", "args": {"command": "<cmd>"}}</tool>
  Verify: ...     →  shell        output: <tool>{"name": "shell", "args": {"command": "cat file.json"}}</tool>
  Patch / Update  →  patch_file   (edit existing file — include enough context in old_str to be unique)

The "Current step" is a guide from a planning model. The "Overall goal" is authoritative — if they differ on filenames or features, follow the Overall goal.

AVAILABLE TOOLS:
```

**To revert:** Delete the line `The "Current step" is a guide...` and the blank line before `AVAILABLE TOOLS`.

**Why:** The orchestrator already passes `Overall goal: {original_request}` and `Current step: {step}` to the 7B — both are in the prompt. Without this instruction, the 7B treats both as equally authoritative and defaults to the step (which has the planner's wrong filenames). This tells it explicitly which one wins.

---

### Change 2 — `core/orchestrator.py` · `run_queue()` · line ~409

**What changed:** The tool hint injected at the bottom of each subtask prompt now pulls filenames from the original user request first, falling back to the step description only if the original has none.

**Before (v9):**
```python
_target_files = _FILE_RE.findall(task.description)
if _target_files:
```

**After (v10):**
```python
# Prefer filenames from the original user request — planner sometimes uses wrong names
_target_files = _FILE_RE.findall(original) if original else []
if not _target_files:
    _target_files = _FILE_RE.findall(task.description)
if _target_files:
```

**To revert:** Replace the 4-line block above with the original 2 lines:
```python
_target_files = _FILE_RE.findall(task.description)
if _target_files:
```

**Why:** The hint block appended to every subtask prompt includes the concrete tool call example with the filename hardcoded — e.g. `Use write_file to create wc.py ... "path": "wc.py"`. When this used the step's filename (`wc.py` from the 0.5B plan) it was actively reinforcing the wrong name at the bottom of the prompt, overriding the correct `wordcount.py` in the Overall goal above. By sourcing the filename from the original request instead, the hint now matches what the user actually asked for.
