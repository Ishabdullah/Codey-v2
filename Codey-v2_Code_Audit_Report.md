**CODEY-V2**

COMPREHENSIVE CODE AUDIT REPORT

  ---------------------- ------------------------------------------------
  **Repository**         github.com/Ishabdullah/Codey-v2

  **Version**            v2.6.9

  **Date**               March 24, 2026

  **Scope**              Full codebase (\~19,000 lines across 70+ files)

  **Auditor**            Automated Code Audit (Perplexity Computer)
  ---------------------- ------------------------------------------------

Executive Summary

Codey-v2 is a persistent, daemon-like AI coding agent designed for
Termux/Android. It uses Qwen2.5-Coder-7B with llama-server for local
inference, featuring a Unix socket daemon, hierarchical memory, task
orchestration, recursive self-refinement, and peer CLI escalation.

The codebase is ambitious and well-structured for a single-developer
project, but contains security vulnerabilities, architectural
inconsistencies, and significant documentation drift from the actual
code.

  ----------------- ----------- ----------------------------------------------
  **Severity**      **Count**   **Categories**

  **CRITICAL**      3           Shell injection, code injection

  **HIGH**          7           Broken tests, dead code, architectural
                                conflicts, broken dependencies

  **MEDIUM**        9           README inaccuracies, unused dependencies,
                                stale configs

  **LOW**           5           Committed backups, outdated TODOs, style
                                issues

  **RECOMMENDED**   8           Best practices, performance, maintainability
  ----------------- ----------- ----------------------------------------------

Critical Issues (3)

These issues represent security vulnerabilities that allow arbitrary
code execution. They should be fixed immediately before any other
changes.

C1. Shell Injection via codey2 Bash Client --- Prompt Interpolation

**File: codey2 \| Lines: 99, 284, 345**

**Description**

User-supplied prompts are interpolated directly into Python heredocs
using bash variable expansion. The construct \"\"\"\$prompt\"\"\" inside
a cat \> \"\$TMPSCRIPT\" \<\< PYEOF block allows shell escape sequences
in the prompt to break out of the Python string and execute arbitrary
Python code.

**Root Cause**

The bash \<\<PYEOF heredoc expands \$prompt before the Python script is
written. A prompt containing triple-quotes plus
\_\_import\_\_(\'os\').system(\'rm -rf /\') would break out of the
string and execute arbitrary code.

**Recommended Fix**

Pass prompts via environment variables instead of interpolation. Use
quoted heredoc (\<\< \'PYEOF\') to prevent variable expansion. Read from
os.environ in the Python script.

**Pros**

Eliminates code injection entirely; environment variables are safe from
string-escaping attacks.

**Cons**

Requires export/unset pattern; slightly more verbose; prompt size
limited by env var limits (\~2MB on Linux).

C2. Task ID Injection via codey2 Bash Client

**File: codey2 \| Lines: 284, 345**

**Description**

The \$TASK_ID variable is interpolated unsanitized into generated Python
code. A malicious task ID can break the JSON dictionary literal and
execute arbitrary code.

**Root Cause**

Same heredoc interpolation pattern as C1. \$TASK_ID is taken from \$1
(user command-line argument) and placed directly into Python source.

**Recommended Fix**

Same pattern as C1 --- pass via environment variable with quoted
heredoc, then parse as integer in Python with
int(os.environ\[\'CODEY_TASK_ID\'\]).

**Pros**

Complete injection prevention; integer parsing adds type safety.

**Cons**

None significant.

C3. Shell Metacharacter Bypass in shell() via skip_structure_check

**File: tools/shell_tools.py \| Lines: 50--100**

**Description**

The shell() function accepts a skip_structure_check parameter that
completely bypasses all metacharacter validation. Additionally, even
with the check enabled, the function uses subprocess.run(command,
shell=True) --- newline injection and other OS-level bypasses can
circumvent the string-level metacharacter list.

**Root Cause**

Defense-in-depth violation. The skip_structure_check=True provides a
trivial bypass. shell=True invokes /bin/sh -c which has many ways to
chain commands beyond the checked metacharacters. Newline characters are
not in the blocklist.

**Recommended Fix**

Remove skip_structure_check parameter entirely. Add newline to
blocklist. Parse with shlex.split() and use shell=False for simple
commands.

**Pros**

Eliminates shell injection when using shell=False; removes dangerous
escape hatch.

**Cons**

Some shell features (globbing, redirects) won\'t work with shell=False;
may need allowlist for complex commands.

High-Severity Issues (7)

These issues cause significant bugs, broken functionality, or
architectural problems that impact reliability and correctness.

H1. Test Suite for Hybrid Inference Imports Non-Existent Classes

**File: tests/test_hybrid_inference.py \| Lines: 18--26**

**Description**

Imports DirectBindingBackend, UnixSocketBackend, TcpHttpBackend,
HybridInferenceBackend, and BackendStats --- all removed in v2.6.0.
pytest crashes with ImportError on every run.

**Root Cause**

Test file written for v2.4.0 three-backend architecture, never updated
for v2.6.0 rewrite.

**Recommended Fix**

Rewrite test file to test ChatCompletionBackend, get_hybrid_backend, and
reset_hybrid_backend.

**Pros**

Tests actually run; validates current architecture.

**Cons**

Loses test coverage for old architecture (acceptable since it no longer
exists).

H2. Duplicate tool_patch_file Function --- Two Competing Implementations

**File: tools/file_tools.py + tools/patch_tools.py \| Lines: 144--159 /
10--79**

**Description**

tool_patch_file defined in two places. file_tools.py delegates to
Filesystem.patch() with workspace boundary enforcement. patch_tools.py
uses direct Path.read_text()/write_text(), bypassing workspace
boundaries. The agent imports from patch_tools.py, so workspace boundary
enforcement is completely bypassed for all patch operations.

**Root Cause**

v2 refactor introduced file_tools.py with filesystem-layer delegation,
but patch_tools.py kept its own direct implementation.

**Recommended Fix**

Merge both: keep patch_tools.py as canonical but route through the
Filesystem layer. Remove duplicate from file_tools.py.

**Pros**

Single source of truth; workspace boundaries enforced; keeps syntax
checking and snapshot features.

**Cons**

Slight API change in error reporting from Filesystem vs direct Path ops.

H3. router.py is a Tombstone --- README Still References Dual-Model
Routing

**File: core/router.py + README.md \| Lines: Multiple (569, 574,
780-784, 823-824, 1126-1134)**

**Description**

router.py was removed in v2.6.9 and replaced with a 10-line tombstone.
README still contains extensive references to the dual-model system,
ROUTER_CONFIG, architecture diagrams, and performance tables.

**Root Cause**

router.py deprecated in v2.6.9, but all documentation left unrevisioned.

**Recommended Fix**

Update all README sections to reflect single-model architecture. Remove
ROUTER_CONFIG. Update architecture diagram. Update storage from \~10GB
to \~5GB.

**Pros**

Accurate documentation; reduces user confusion during setup.

**Cons**

None.

H4. install.sh Still Downloads the 1.5B Secondary Model

**File: install.sh \| Lines: 28--34, 163--215**

**Description**

Install script still defines SECONDARY_MODEL_DIR/FILE/URL and downloads
\~2GB 1.5B model. Since v2.6.9 is single-model, this wastes \~2GB
storage and \~30 minutes of download time on mobile.

**Root Cause**

install.sh not updated for v2.6.9 single-model transition.

**Recommended Fix**

Remove secondary model download entirely from install.sh.

**Pros**

Saves 2GB+ storage and download time; consistent with v2.6.9.

**Cons**

Users who previously installed both models may wonder about the second
model (add CHANGELOG note).

H5. memory.py vs memory_v2.py --- Two Parallel Memory Systems

**File: core/memory.py + core/memory_v2.py \| Lines: 241 lines / 366
lines**

**Description**

Two independent memory systems exist. memory.py (MemoryManager,
file-focused) is used by the agent. memory_v2.py (HierarchicalMemory,
four-tier with SQLite + embeddings) is documented in README as canonical
API. Users following README examples would use a completely different
system than what the agent runs.

**Root Cause**

memory_v2.py designed for daemon-mode four-tier architecture but never
integrated into agent loop.

**Recommended Fix**

Option A: Migrate agent to memory_v2.py (best long-term). Option B:
Update README to document memory.py as active and mark memory_v2.py as
daemon-only (best short-term).

**Pros**

Option B: Minimal code changes; accurate docs.

**Cons**

Option B: Technical debt persists; two memory systems to maintain.

H6. \_auto_apply_peer_code Bypasses All File Safety Checks

**File: core/agent.py \| Lines: 490--545**

**Description**

When a peer CLI returns code, \_auto_apply_peer_code() writes files
directly using Path.write_text(), completely bypassing workspace
boundary enforcement, write-protected file checks, binary file blocking,
content size validation, and user confirmation.

**Root Cause**

Function written for convenience but skipped all safety layers.

**Recommended Fix**

Route peer file writes through tool_write_file from tools/file_tools.py.

**Pros**

Inherits all safety checks from tool_write_file.

**Cons**

Protected file writes may require user confirmation (this is a safety
feature, not a bug).

H7. requirements.txt Lists llama-cpp-python --- Code Uses llama-server
Subprocess

**File: requirements.txt \| Lines: 5**

**Description**

requirements.txt requires llama-cpp-python\>=0.2.50, but the codebase
exclusively uses llama-server as a subprocess. llama-cpp-python fails to
install on Termux/Android (no ARM64 wheels, C++ compilation fails), is
not imported anywhere in active code, and was only used in the v2.4.0
DirectBindingBackend which was removed.

**Root Cause**

Dependency not removed after v2.6.0 inference rewrite.

**Recommended Fix**

Remove llama-cpp-python from requirements.txt. Make
sentence-transformers optional.

**Pros**

pip install -r requirements.txt actually succeeds on Termux.

**Cons**

None.

Medium-Severity Issues (9)

Code quality issues, potential bugs, missing validation, and
documentation inconsistencies.

  -------- -------------------------------------- -------------------------------------------------
  **ID**   **File/Location**                      **Description**

  **M1**   README.md:798-839                      Architecture diagram still shows \'7B \<-\> 1.5B
                                                  hot-swap\' --- contradicts v2.6.9 single-model

  **M2**   README.md:780-784                      ROUTER_CONFIG example references non-existent
                                                  config keys removed in v2.6.9

  **M3**   README.md:397-399                      Quick Start says \'Both models (7B + 1.5B)\' ---
                                                  v2.6.9 is single model

  **M4**   README.md:771-778                      MODEL_CONFIG shows n_ctx: 8192 (actual: 32768),
                                                  temperature: 0.2 (actual: 0.7)

  **M5**   requirements.txt:8                     sentence-transformers listed as required but only
                                                  used by inactive memory_v2.py

  **M6**   main.py:50 + README.md:648-657         \--ft-model only accepts \'7b\' but README lists
                                                  \'1.5b\' and \'both\' options

  **M7**   core/inference_v2.py:132               Legacy HTTP fallback to port 8081 --- no server
                                                  ever runs on that port in v2.6.9

  **M8**   codey2:46,110,127,237,333,399          Temp files created with mktemp in \~/.codey-v2/
                                                  without cleanup on failure (no trap)

  **M9**   backups/layered_prompt_2026-03-17.py   Backup file committed to repository --- adds
                                                  unnecessary size, should be in .gitignore
  -------- -------------------------------------- -------------------------------------------------

Low-Severity Issues (5)

Style issues, minor improvements, and code readability concerns.

  -------- ----------------------- -------------------------------------------------
  **ID**   **File/Location**       **Description**

  **L1**   TODO.md:14              \'Create tests/ directory\' listed as TODO ---
                                   tests/ already exists with 12 files

  **L2**   TODO.md:4               States \'Current version: v2.6.8\' --- actual
                                   version is v2.6.9

  **L3**   tests/\_\_init\_\_.py   Broken test_hybrid_inference.py causes entire
                                   pytest suite to fail due to ImportError

  **L4**   core/agent.py:359-378   is_error() matches \'failed\' too broadly ---
                                   false positives for \'0 tests failed\'

  **L5**   CHANGELOG.md            Missing v2.6.7, v2.6.8, v2.6.9 entries
  -------- ----------------------- -------------------------------------------------

Recommended Improvements (8)

Best practices, enhancements, and new features to consider for long-term
quality.

  -------- ----------------------- ---------------------------------------------
  **ID**   **Enhancement**         **Description**

  **R1**   **Add Type Annotations  Many functions lack return type annotations
           Throughout**            and parameter type hints. Adding them
                                   improves IDE support, enables mypy checking.

  **R2**   **Centralize Socket     \~150 lines of duplicated socket code across
           Communication in        5 command handlers. Extract a shared
           codey2**                send_command.py utility.

  **R3**   **Add .gitignore        Missing entries for backups/,
           Entries for Common      \_\_pycache\_\_/, \*.pyc, .codey-v2/,
           Artifacts**             \*.egg-info/, dist/, build/

  **R4**   **Use pyproject.toml    Modern Python projects use pyproject.toml for
           Instead of              dependency management --- distinguishes
           requirements.txt**      required vs optional deps.

  **R5**   **Add Error Handling    inference_hybrid.py accesses private
           for response.fp.\_sock  response.fp.\_sock attribute --- fragile,
           Access**                could break across Python versions.

  **R6**   **Move                  Large constant lists in agent.py (lines
           HALLUCINATION_MARKERS   59-87) are essentially configuration. Move to
           to Config**             config.py or constants.py.

  **R7**   **Add Integration Test  No integration test exercises the full
           for Agent Loop**        run_agent() loop with a mock inference
                                   backend. Would catch regressions like tool
                                   import conflicts.

  **R8**   **Consider Rate         Daemon Unix socket server has no rate
           Limiting on Unix        limiting. A local process could flood it. Add
           Socket**                basic max 10 req/sec.
  -------- ----------------------- ---------------------------------------------

README vs Code Comparison

Systematic verification of every major README claim against the actual
codebase. Status key: CORRECT = matches code, PARTIAL = partially
accurate, OUTDATED = references removed features, MISLEADING =
technically exists but misrepresents functionality, INACCURATE =
factually wrong.

  ----------------------- ----------- --------------------------- ----------------
  **README Claim**        **Line**    **Actual Code**             **Status**

  Version v2.6.9          16          config.py: CODEY_VERSION =  **CORRECT**
                                      \'2.6.9\'                   

  Qwen2.5-Coder-7B        7, 222      config.py: MODEL_PATH       **CORRECT**
                                      points to qwen2.5-coder-7b  

  Single-Model            221-223     router.py is tombstone,     **CORRECT**
  Architecture                        loader_v2.py loads one      
                                      model                       

  nomic-embed-text-v1.5   24          config.py:                  **CORRECT**
  on port 8082                        EMBED_SERVER_PORT = 8082    

  BM25 + vector hybrid    26          tools/kb_semantic.py        **CORRECT**
  search                              implements both             

  Skill Loading via       32          core/skills.py exists (81   **CORRECT**
  core/skills.py                      lines)                      

  Recursive Planning with 38          core/recursive.py +         **CORRECT**
  critique                            core/planner_v2.py          

  Layered Context System  44-50       prompts/layered_prompt.py   **CORRECT**
                                      (413 lines)                 

  Voice Interface         88-94       core/voice.py (293 lines)   **CORRECT**

  Auto-lint on write      97-98       core/agent.py lines 298-323 **CORRECT**

  Pre-write syntax gate   98          Code says \'STILL WRITE the **PARTIAL**
                                      file\' (line 278) --- warns 
                                      but doesn\'t block          

  Peer CLI Escalation     103-111     core/peer_cli.py +          **CORRECT**
                                      core/peer_shell.py          

  Shell metacharacter     138         tools/shell_tools.py ---    **PARTIAL**
  blocking                            bypassable (see C3)         

  Self-modification       139         core/filesystem.py, main.py **CORRECT**
  opt-in                              line 69                     

  Simple Query uses 1.5B  569         No 1.5B model in v2.6.9     **OUTDATED**
  model                                                           

  Complex Task uses 7B    574         All tasks use 7B            **OUTDATED**
  model                                                           

  Both models (7B + 1.5B) 398         Single model only           **OUTDATED**

  ROUTER_CONFIG           780-784     Does not exist in config.py **OUTDATED**

  Architecture: 7B \<-\>  824         router.py is tombstone      **OUTDATED**
  1.5B hot-swap                                                   

  Performance: Secondary  1126-1134   No secondary model          **OUTDATED**
  Model stats                                                     

  Storage: \~10GB         419         \~5GB without 1.5B model    **OUTDATED**

  n_ctx: 8192             772         config.py: n_ctx = 32768    **OUTDATED**

  temperature: 0.2        775         config.py: temperature =    **OUTDATED**
                                      0.7                         

  Memory examples use     880-897     Agent uses memory.py, not   **MISLEADING**
  memory_v2                           memory_v2                   

  Project Structure lists 1008        Exists only as tombstone    **MISLEADING**
  router.py                                                       

  Test Coverage: 16 shell 1269        tests/security/ directory   **CORRECT**
  injection tests                     exists                      

  Pre-write syntax gate   346-347     Code explicitly says        **INACCURATE**
  blocks writes                       \'STILL WRITE the file\'    

  \--ft-model accepts     657         main.py only accepts \'7b\' **OUTDATED**
  1.5b, both                                                      

  \--lora-model accepts   689         main.py only accepts        **OUTDATED**
  secondary                           \'primary\'                 
  ----------------------- ----------- --------------------------- ----------------

**Summary: 13 correct, 2 partial, 11 outdated, 2 misleading, 1
inaccurate out of 29 claims verified.**

Recommended README Changes

1\. Remove all references to 1.5B model, dual-model routing,
ROUTER_CONFIG, and model hot-swap. The system is single-model since
v2.6.9.

2\. Update MODEL_CONFIG values: n_ctx should be 32768, temperature
should be 0.7.

3\. Update storage requirements from \~10GB to \~5GB.

4\. Update architecture diagram to remove \'Model router (7B \<-\> 1.5B
hot-swap)\'.

5\. Update memory examples to use memory.py (MemoryManager) instead of
memory_v2.py (HierarchicalMemory).

6\. Clarify pre-write syntax gate --- it warns but does not block writes
(code says \'STILL WRITE the file\').

7\. Update fine-tuning docs: \--ft-model only accepts \'7b\',
\--lora-model only accepts \'primary\'.

Why: The README is the first thing users see. 11 outdated claims and 2
misleading ones will cause setup failures, confusion, and wasted time.
Fixing documentation costs minutes but saves users hours.

Optimal Fix Order

Prioritized action plan organized by urgency and dependency. Earlier
fixes unblock later ones.

Priority 1: Security (Fix Immediately)

  ----------- ------------------------ ------------------------------------ ---------
  **ID(s)**   **Task**                 **Details**                          **Est.
                                                                            Time**

  **C1+C2**   codey2 shell injection   codey2 shell injection --- quoted    \~30 min
              --- quoted heredocs +    heredocs + env vars                  
              env vars                                                      

  **C3**      shell() metacharacter    shell() metacharacter bypass ---     \~1 hr
              bypass --- remove        remove skip_structure_check, add     
              skip_structure_check,    newline blocking                     
              add newline blocking                                          

  **H6**      \_auto_apply_peer_code   \_auto_apply_peer_code --- route     \~15 min
              --- route through        through tool_write_file              
              tool_write_file                                               
  ----------- ------------------------ ------------------------------------ ---------

Priority 2: Functional Correctness (This Week)

  ----------- -------------------------- ------------------------------------ ---------
  **ID(s)**   **Task**                   **Details**                          **Est.
                                                                              Time**

  **H1**      Rewrite                    Rewrite test_hybrid_inference.py for \~30 min
              test_hybrid_inference.py   current architecture                 
              for current architecture                                        

  **H7**      Remove llama-cpp-python    Remove llama-cpp-python from         \~5 min
              from requirements.txt      requirements.txt                     

  **H2**      Consolidate duplicate      Consolidate duplicate                \~30 min
              tool_patch_file            tool_patch_file                      
  ----------- -------------------------- ------------------------------------ ---------

Priority 3: Documentation Accuracy (This Week)

  ----------------- ------------------- ------------------------------------ ---------
  **ID(s)**         **Task**            **Details**                          **Est.
                                                                             Time**

  **H3+H4+M1-M6**   Batch README update Batch README update --- all          \~2 hrs
                    --- all dual-model  dual-model refs, config values,      
                    refs, config        architecture diagram                 
                    values,                                                  
                    architecture                                             
                    diagram                                                  

  **L1+L2**         TODO.md version and TODO.md version and checklist        \~5 min
                    checklist updates   updates                              

  **L5**            Add CHANGELOG       Add CHANGELOG entries for v2.6.7,    \~30 min
                    entries for v2.6.7, v2.6.8, v2.6.9                       
                    v2.6.8, v2.6.9                                           
  ----------------- ------------------- ------------------------------------ ---------

Priority 4: Technical Debt (Next Sprint)

  ----------- ------------------- ------------------------------------ ---------
  **ID(s)**   **Task**            **Details**                          **Est.
                                                                       Time**

  **H5**      Resolve memory.py   Resolve memory.py vs memory_v2.py    \~2 hrs
              vs memory_v2.py --- --- pick canonical system            
              pick canonical                                           
              system                                                   

  **M5+M7**   Clean up unused     Clean up unused deps and dead HTTP   \~20 min
              deps and dead HTTP  fallback                             
              fallback                                                 

  **M8+M9**   Temp file cleanup   Temp file cleanup (trap) + remove    \~15 min
              (trap) + remove     committed backup + .gitignore        
              committed backup +                                       
              .gitignore                                               
  ----------- ------------------- ------------------------------------ ---------

Priority 5: Quality Improvements (Ongoing)

  ----------- ------------------- ------------------------------------ ---------
  **ID(s)**   **Task**            **Details**                          **Est.
                                                                       Time**

  **R1-R8**   Type annotations,   Type annotations, dedup socket code, Ongoing
              dedup socket code,  pyproject.toml, integration tests,   
              pyproject.toml,     rate limiting                        
              integration tests,                                       
              rate limiting                                            
  ----------- ------------------- ------------------------------------ ---------

Appendix: Files Reviewed

  ---------------------- ------------------------ ------------------------
  **Directory**          **Files**                **Lines**

  Root                   main.py, codey2,         \~2,168
                         codeyd2,                 
                         requirements.txt,        
                         install.sh, setup.sh     

  core/                  48 Python files          \~13,000

  tools/                 file_tools.py,           \~1,318
                         patch_tools.py,          
                         shell_tools.py,          
                         kb_scraper.py,           
                         kb_semantic.py,          
                         setup_skills.sh          

  utils/                 config.py, logger.py,    \~294
                         file_utils.py            

  prompts/               system_prompt.py,        \~585
                         layered_prompt.py,       
                         critique_prompts.py      

  tests/                 12 test files            \~1,768

  docs/                  README.md, CHANGELOG.md, \~1,700
                         TODO.md,                 
                         importantdoc.md, LICENSE 

  **TOTAL**              **\~70+ files**          **\~19,000 lines**
  ---------------------- ------------------------ ------------------------
