# Agent, MCP server, and skill catalogs — work packages (execution record)

Status: **Planned; not implemented or verified** (2026-10-04).
Contract: `docs/specs/agent-mcp-skills.md`, approved 2026-10-04.
Owner of execution, delegation, integration and scope questions: coordinator.
Architect planning only; no application code or database changes were made.

## Coordinator decisions

- **2026-10-04 — Catalog authorization parity CONFIRMED.** The three catalogs
  mirror the provider-configuration policy exactly: any authenticated user may
  create personal entries; group creation requires admin or a `group_manager`
  membership role; global creation is admin-only; mutations are owner/admin under
  the same target-scope checks. No builder-only gate and no deviation from the
  shared provider policy.

## Evidence and precedence

- Read the approved spec completely, `AGENTS.md`, `docs/context/project.md`,
  and the earlier workflow-editor execution record. D7/D8 override the stale
  compatibility sentence in the spec's Constraints section and the older
  context's submission-snapshot direction: resolve catalogs live and **do not**
  implement an embedded-agent reader/normalizer or snapshot resolved secrets.
- Source confirms `AgentConfig` in `backend/shared/graph/schema.py`, inline
  agent use in `worker/activities/ai_node.py`, and provider resolution through
  `_load_provider_runtime_config`. `execute_opaque_node` reads the task creator
  and inputs inside the activity. Catalog resolution belongs here/in its direct
  worker-local callees, never in Temporal workflow code or a separate activity
  that returns resolved configuration.
- `OpenCodeACPAdapter.start_session` already sends `mcpServers` and selects the
  advertised model config option. It does not currently select reasoning effort.
  `orchestrate_ai_node` already prepends instructions to `session/prompt` text.
  `validator_mcp_server` supplies an HTTP ACP server with header name/value pairs.
- Provider patterns: `app/domain/provider_configs/{models,repository,service}.py`,
  `app/domain/identity/scope_policy.py`, `app/api/routes/provider_configs.py`.
  Reuse policy and Fernet/configuration-key conventions, not provider-specific
  verification, candidate operations, recency fallback, or upload requirements.
- Important policy fact: `can_create_personal` permits any authenticated user;
  group creation requires admin or **group membership role** `group_manager`,
  not merely platform role or ordinary membership. Owner/admin mutations and
  own/group/global visibility are the established provider behavior. This plan
  mirrors it, without adding a builder-only gate. Coordinator must flag any
  desired deviation before execution; do not silently change shared policies.
- Frontend source confirms local state/refetch, typed `api`, provider list/form
  conventions, `RowActions`, `ConfirmDialog`, Radix dialogs, and nested locale
  files at `frontend/src/i18n/locales/{en,es}.json`. Actual catalog routes currently
  fall through `frontend/src/app/router.tsx` to the placeholder; the shell nav
  links already exist. No TanStack Query migration is included.
- Graph discovery tools were unavailable in this session (tool discovery returned
  no codebase-memory tools). Source read/grep fallback was used. Graph generation,
  traces and `check_index_coverage` could not be verified. This is targeted source
  evidence, not an exhaustive dependency audit. No test commands or runtime
  probes were executed during planning. Migration filenames below are proposed;
  current inspected head is `0021_editor_contract_cleanup`.

## Contracts fixed for execution

### 1. Node reference schema (schema_version remains v1)

```json
{
  "type": "ai", "id": "summarize",
  "agent_id": "a-valid-catalog-uuid",
  "model": "provider/model-explicit-override",
  "reasoning_effort": "runtime-option-value",
  "added_mcp_ids": ["mcp-uuid"], "removed_mcp_ids": [],
  "added_skill_ids": [], "removed_skill_ids": ["skill-uuid"],
  "prompt_template": "Summarize the supplied report.",
  "inputs": ["report"], "outputs": ["summary.md"],
  "output_validation": {"summary.md": {"format": "markdown"}},
  "max_validation_cycles": 3
}
```

The example IDs illustrate references; actual catalog IDs are UUID strings.
`agent_id` is required on executable/publishable AI nodes. `model` and
`reasoning_effort` are optional nonempty strings (trimmed, at most 300 and 80
characters respectively); omission means inherit. Null is accepted only as
an API/editor request to clear an override and is omitted from canonical stored
definitions. Reasoning strings are runtime option values, not a guessed universal
low/medium/high enumeration. Agent reasoning is optional (`null` means runtime
default); non-null reasoning must actually be applied or fail explicitly.
Agent model is mandatory, including the existing explicit `default` convention.

Four delta lists default to empty, contain unique UUIDs, and the added/removed
sets for each kind must be disjoint. Canonical serialization omits empty delta
lists and absent scalar overrides. Reject unknown fields, `agent`, inline
instructions/runtime/transport/secret fields. **Remove `AgentConfig` and its
uses**, including frontend defaults/tests; do not copy the parsing-only legacy
`validation` convention for agents. Existing output-validation compatibility is
unrelated and remains intact.

Effective IDs = ordered unique agent IDs minus removed IDs, then added IDs not
already present, in authored order. Removals survive later agent edits even if
the removed ID is currently absent from the agent. Selecting a different agent
clears every override; merely loading/reopening/refetching a node never does.
Model/reasoning display inherited values without persisting them. Explicit
override state survives central changes even if it later equals the inherited
value; an explicit 'Use agent default' action removes it. MCP/skill control edits
update deltas relative to the current baseline and preserve untouched removal
intent. Catalog refresh must not rebase saved deltas automatically.

### 2. Catalog contracts and authorization

- Proposed domains: `backend/app/domain/{agents,mcp_servers,skills}/` with
  `models.py`, `repository.py`, `service.py`. Avoid a generic catalog framework;
  share only small proven scope/name/secret helpers where duplication warrants it.
- Common metadata: UUID `id`, `name` (trimmed 1..80), `owner_user_id`,
  `visibility`, nullable `group_id`, `updated_at`; group ID required iff group
  visibility. Names are case-insensitively unique **per entity kind, owner,
  visibility and group scope** (NULL-aware partial/functional indexes), unlike
  the provider's broader owner/provider index. Enforce both application checks
  and database race backstops; translate only the relevant constraint violation.
- Agent: `runtime: "opencode"`, `model`, nullable `reasoning_effort`, Markdown
  `instructions`, ordered unique `mcp_ids`, `skill_ids`. Skill: `description`,
  Markdown `instructions`. Bound description to 2,000 and instructions to
  100,000 characters; safe validation diagnostics never echo candidate content.
- Persist agent relationship ID lists without cascading away missing references.
  Deleting an MCP/skill must not silently alter agent behavior; stale references
  remain identifiable and block future execution. No FK that prevents approved
  deletion or cascade-removes the link. Validate selected references under the
  actor's visibility on create/change, but also recheck at execution under the
  task creator, with current memberships. Shared agents may contain references
  unavailable to another consumer: fail visibly, never use the owner's identity.
- Proposed REST roots `/agents`, `/mcp-servers`, `/skills`: authenticated
  `GET /`, visible `GET /{id}`, authorized `POST /`, `PATCH /{id}`,
  `DELETE /{id}`; mutations owner/admin plus target-scope policy checks.
  PATCH omission means preserve; explicit null only clears nullable fields.
  Stable keyed errors use `KosmoError`/`ErrorDetail`; no raw exception strings.
  Each module exposes `router` for existing dynamic route registration.
- All visible IDs remain selectable; list ordering personal > group > global,
  then deterministic name/id. Explicit ID resolution never substitutes a
  same-name higher-precedence entry: D9 forbids fallback. Provider runtime files
  continue their existing personal > group > global resolution by runtime type.
  Visibility and explicit selection are not name-shadowing semantics.
- Lists are metadata-oriented; details return visible nonsecret content needed
  by editing/preview, **never decrypted MCP values or ciphertext**. No new audit
  infrastructure: reuse existing CRUD hooks if present; report their absence.
  User-authored instructions are not a credential store; no dedicated agent
  secret fields are introduced.

### 3. MCP transport / secret write and read contract

Architect-selected OQ4 field set, pending wire-capability proof in WP-01:

```json
{"transport":{"type":"stdio","command":"executable","args":["arg"],
 "env":[{"name":"API_TOKEN","secret":true,"action":"replace","value":"write-only"}]}}
```

HTTP substitutes `type: "http"`, `url`, `headers` for command/args/env.
Discriminated schemas reject mixed fields/unknown transports; stdio uses an
executable and argument vector, never a platform shell interpolation. HTTP URL
must be absolute http(s), with no userinfo; credentials belong in secret headers,
not URLs/commands/args. Reject duplicate env names and case-insensitive duplicate
header names, invalid names and CR/LF in headers. Reserve ACP name
`kosmo-validator`; user server wire names are `catalog-<uuid>` to avoid collisions.
No SSE/remote tool verification UI or host executable installation is included.
Stdio commands run **inside the agent container**, with its installed tools and
existing isolation; do not run them on the worker/API host.

Named env/header entries have explicit `secret` classification. Write actions
are `replace` (requires value), `keep` (existing entry only), `remove` (existing
entry only); create accepts replace only. PATCH omission preserves the whole
transport; if an entry collection is supplied it is an exact desired set, with
keep for retained secret entries. Reject keeping after transport/name changes or
changing secret classification without replacement. `remove` deletes the entry.
This distinguishes blank replacement from preservation and deletion.

Encrypt secret value bytes with the configured Fernet key before repository
writes; nonsecret configuration may remain JSON metadata. Secret read shape:
`{"name":"API_TOKEN","secret":true,"is_set":true}` (no value). Nonsecret
entries may include value in detail responses; lists expose only safe metadata
and presence markers. Encryption-key failures fail closed. Only a worker-local
resolver may decrypt and assemble ACP env/header `[{name,value}]` lists.
Validate and bound requests without logging/serializing their values on failure,
including FastAPI/Pydantic input-error bodies and request logging.

### 4. Live resolution and security boundary

Resolve after recovery checks, immediately before starting a **new** AI session,
using task DB `created_by`, never a caller-supplied identity. Read agent and
effective MCPs/skills in one bounded DB resolution phase. Check every surviving
inherited/addition reference; removed IDs need not resolve (they are exclusions).
New sessions on retry/resume resolve again; recovered completed artifacts do not
restart or require the catalog to still exist. An already-running session keeps
its local resolved configuration; no hot mutation is introduced.

Pass an ephemeral effective configuration object directly to the orchestration
and adapter, **separate from the authored node**, not as an embedded replacement
`node.agent`. Include the platform validator MCP separately, outside author
delta lists; it cannot be removed. Never return effective configuration from an
activity, store it in task definitions/checkpoints, or send it in Temporal
workflow/activity arguments, results, failure messages or history.

Missing/invisible agent/MCP/**skill** produces `CATALOG_REFERENCE_UNAVAILABLE`
with `errors.catalog.reference_unavailable`, safe `{kind,id}` parameters; no
existence disclosure distinction at runtime and no fallback. Decryption and
unsupported reasoning/transport errors are distinct keyed blocking failures.
Add en/es messages. Raw ACP failures may contain headers/env/prompt content:
replace current `logger.exception` leakage at the AI boundary with bounded
metadata logging; prevent `normalize_frame` error text and permission payloads
from leaking configured secrets into notes/SSE/history. Redact known runtime
secrets at diagnostic/event persistence boundaries, not at actual tool use.
This is configured-secret boundary protection, not a new egress-filter feature.

### Spikes / investigations (OQ3 and OQ4)

- **OQ3 architectural choice:** deliver each effective skill's name, description
  and full Markdown instructions in deterministic, delimited sections of the
  first session prompt, after agent instructions and before task instructions.
  Existing `send_prompt` provides this seam; no native skill discovery, generated
  workspace filename, or runtime plugin dependency is necessary. Removed skills
  are absent. WP-01 proves this on the installed container/runtime and records
  practical payload limits. Fallback is the same explicit text mechanism rather
  than unverified native skill files; if prompt limits invalidate the chosen
  bounded contract, return a blocking result for architect/coordinator revision.
- **OQ4 architectural choice:** support stdio and HTTP field sets above; HTTP
  wire shape is evidenced by the validator helper, but installed runtime stdio
  support/capability checks remain unproven. WP-01 verifies initialization
  capabilities and both `session/new` shapes with fixture servers. If a transport
  is unsupported, fail with a keyed error, **not** silently omit it. A runtime
  upgrade or reduced catalog transport scope needs coordinator agreement; the
  spike cannot silently change the approved functional delivery.
- **Related blocker:** reasoning selection has no existing adapter path. WP-01
  records the advertised option ID/value set after model selection and proves a
  non-default setting. Use advertised ACP config options rather than a guessed
  option ID. No support means explicit blocked runtime delivery; do not equate
  storing a field or writing a prompt instruction with applying reasoning effort.

## Numbered package list

All proposed paths are labeled by their package; existing paths above are verified.
Every package begins Planned. Workers append changed files, ACs, red/green proof,
actual commands/results, skips and blockers in the status log. They do not commit
unless separately authorized by the coordinator.

| ID | Package name | Type / assigned role | Dependencies |
| --- | --- | --- | --- |
| WP-01 | OpenCode delivery capability proof | development / developer | none |
| WP-02 | Catalog persistence and migration | development / developer | none |
| WP-03 | Scoped Skill CRUD | development / developer | WP-02 |
| WP-04 | Encrypted MCP CRUD | development / developer | WP-01, WP-02 |
| WP-05 | Scoped Agent CRUD and references | development / developer | WP-03, WP-04 |
| WP-06 | Reference-only AI schema | development / developer | WP-01 |
| WP-07 | Worker-local effective catalog resolver | development / developer | WP-03, WP-04, WP-05, WP-06 |
| WP-08 | Runtime and secrecy tests first | test / tester | WP-01, WP-07 |
| WP-09 | ACP model/reasoning/transport delivery | development / developer | WP-08 |
| WP-10 | Live AI session integration and safe diagnostics | development / developer | WP-07, WP-08, WP-09 |
| WP-11 | Typed frontend catalog and override state | development / developer | WP-05, WP-06 |
| WP-12 | Shared catalog controls and safe Markdown | design / designer | WP-11 |
| WP-13 | Skill catalog screen | design / designer | WP-03, WP-12 |
| WP-14 | MCP catalog screen | design / designer | WP-04, WP-13 |
| WP-15 | Agent catalog screen | design / designer | WP-05, WP-14 |
| WP-16 | AI reference and override properties | design / designer | WP-11, WP-12, WP-15 |
| WP-17 | Destructive workflow reset and reference reseed | development / developer | WP-02, WP-05, WP-06, WP-10, WP-16 |
| WP-18 | Integrated acceptance and browser proof | test / tester | WP-01…WP-17 |

### WP-01 — OpenCode delivery capability proof
- Type / owner: development / Developer (`developer`).
- Objective / acceptance IDs: prove OQ3/OQ4 and reasoning runtime contracts;
  AC-AMS-06/07 and D5. Research/proof only, no product runtime implementation.
- Included scope / exclusions: installed OpenCode version, initialize capabilities,
  model then reasoning options, skill prompt receipt, local fixture stdio/HTTP
  MCP connection. No marketplace, extra adapter, dependency upgrade or credentials.
- Files / patterns: read `backend/docker/opencode/Dockerfile`,
  `worker/adapters/opencode_acp.py`, `worker/activities/agent.py`; proposed
  `backend/tests/worker/test_catalog_runtime_probe.py` and a bounded results
  section in this execution record. Inspect available container tooling first.
- Changes / contracts: record version, exact capability/option response shapes,
  request order, supported reasoning values, stdio env and HTTP header wire
  mapping, and synthetic skill text receipt. Do not publish raw credentials.
- Dependencies / ownership: independent of WP-02. Own probe test only, no adapter
  edits; update record results before WP-04/06/08 consume findings.
- Required skills: `python-testing-patterns`, `verification-before-completion`;
  `systematic-debugging` for unexpected protocol failures.
- Tests / commands: existing full backend command below, focused probe via
  `uv run --project backend --directory backend pytest tests/worker/test_catalog_runtime_probe.py`;
  live Docker invocation to be recorded after fixture discovery. No guessed
  successful command. LLM-required checks must be credential-gated explicitly.
- Completion: reproducible nonsecret evidence, fixed capability contract or an
  explicit blocker. Mark skips as unverified, not successful delivery.
- Risks / questions: ACP reasoning may be model-dependent; supplied prompt text
  proves delivery, not that an LLM will obey skills. Unsupported transport or
  inability to apply nondefault reasoning blocks dependent runtime work.

#### WP-01 results

- **Status:** Live ACP initialization, model-dependent effort selection and
  application, live skill prompt receipt, and HTTP MCP handshake are proven on
  scratch OpenCode 2.0.22. The v1 pin did not advertise effort in its observed
  default session. Stdio fixture handshake remains unproven.
- **Part A — source/version/release check:** `backend/docker/opencode/Dockerfile`
  installs official npm package `opencode-ai@1.18.33` globally, not a GitHub
  binary. Ran `npm view opencode-ai version` and `npm view opencode-ai dist-tags
  --json`: latest stable tag for legacy package `opencode-ai` was `1.18.34`;
  `latest-0` was `1.0.142`, `latest-1` was `1.1.4`, while its `beta` tag points
  to a beta build. Ran `npm view @opencode/cli version dist-tags --json` and
  `npm view @opencode/cli@latest version`: the current package for v2 reports
  `latest: 2.0.22`, `beta: 0.0.0-beta-19507`, `dev: 0.0.0-dev-20531`; latest
  stable is **OpenCode 2.0.22**. Official sources checked: release page
  `https://github.com/anomalyco/opencode/releases` showed v1.18.34 as latest
  GitHub release at lookup time; `https://opencode.ai/v2/docs` states new v2 is
  available; v2 CLI docs recommend `npm install -g @opencode/cli`. This makes
  package identity important: Dockerfile's old package tag does not identify the
  new v2 stable line.
- **Scratch v2 build:** Built `wp01-opencode2:2.0.22` only in local Docker using
  a temporary Dockerfile under `$env:TEMP\wp01-opencode2` with `FROM
  node:22-bookworm-slim`, `RUN npm install --global @opencode/cli@2.0.22`,
  `/workspace` workdir and `opencode` entrypoint; repository pin unchanged.
  `docker run --rm --entrypoint opencode wp01-opencode2:2.0.22 --version`
  printed `opencode v2.0.22`.
- **v1.18.33 initialize/session evidence:** Process launched with
  `docker run --rm -i --entrypoint opencode kosmo-opencode:local acp`.
  Request order was initialize → session/new → set model (advertised model).
  Initialize result had `protocolVersion: 1`, `agentCapabilities:
  {loadSession: true, mcpCapabilities: {http:true,sse:true},
  promptCapabilities:{embeddedContext:true,image:true},
  sessionCapabilities:{close:{},fork:{},list:{},resume:{}}}`, auth method
  `opencode-login`, and `agentInfo:{name:"OpenCode",version:"1.18.33"}`.
  `session/new({cwd:"/workspace",mcpServers:[]})` advertised `model` current
  `opencode/big-pickle` (10 OpenCode Zen models) and `mode` current `build`
  with values `build` and `plan`. `session/set_config_option` on advertised
  `model` returned the same options. No reasoning config option was present.
- **v2.0.22 initialize/session evidence:** Same JSON-RPC harness, image
  `wp01-opencode2:2.0.22`. Initialize advertised
  `mcpCapabilities:{http:true,sse:false}`, prompt embeddedContext/image, session
  capabilities additionalDirectories/close/delete/fork/list/resume plus
  `_meta:{"opencode/child-session-updates":true}`; `agentInfo.version` was
  `2.0.22`. Fresh sessions returned model and mode, with available model
  list/current varying between starts; `opencode/fledge-alpha-free` and
  `opencode/longcat-2.5-preview-free` were observed. Fledge's model values were
  `opencode/big-pickle`, `opencode/fledge-alpha-free`,
  `opencode/ling-3.0-flash-fin-free`, `opencode/ling-3.1-flash-free`,
  `opencode/longcat-2.5-preview-free`, `opencode/mimo-v2.6-flash-free`,
  `opencode/muse-spark-1.3-contributor-free`, `opencode/nemotron-3-ultra-free`,
  `opencode/nemotron-3.5-lightning-free`, `opencode/space-bunny-free`; its mode
  was current `build`, values `build`, `plan`. A first scratch run without
  `/workspace` returned JSON-RPC `-32603`, `Internal error: Internal service
  failure`; adding `/workspace` resolved the harness setup issue.
- **Reasoning investigation:** OpenCode v2 official model docs
  (`https://opencode.ai/v2/docs/models/`, checked 2026-10-04) specify variants
  selected as `provider/model#variant`; their example uses `openai/gpt-5.2#high`.
  Docs also show variant `settings.reasoningEffort` values and provider/model
  settings, e.g. `reasoningEffort: "medium"`, with a `deep` variant setting it
  to `high`; model docs say the selected variant is applied after provider and
  model settings. The v2 config docs
  (`https://opencode.ai/v2/docs/config/`) expose model `settings` and `variants`.
  Live v2 `session/new` on a session with selected model
  `opencode/fledge-alpha-free` returned complete effort option
  `{id:"effort",name:"Effort",description:"Available effort levels for this
  model",category:"thought_level",type:"select",currentValue:"default",
  options:[{value:"low",name:"Low"},{value:"high",name:"High"},
  {value:"max",name:"Max"},{value:"default",name:"Default"}]}`. Order:
  initialize → session/new → set model with advertised `configId:"model"` and
  advertised current `opencode/fledge-alpha-free`; response again listed
  `effort`; then set advertised `configId:"effort", value:"high"`. Successful
  response returned options with `effort.currentValue:"high"`. This proves
  advertised non-default effort application on v2 without a guessed ID/value.
  It is model/session-dependent; an earlier fresh session lacked `effort` until
  a Fledge session was observed. The live prompt also triggered
  `config_option_update` with effort for a dynamically selected Fledge model.
  During a synthetic prompt, v2 emitted `agent_thought_chunk` update frames;
  thought body omitted here. The current pinned v1 session advertised no effort.
  v2 therefore closes the ACP application proof, but provider-specific request
  payload mapping to a backend `reasoningEffort` setting was not observed.
  OpenCode docs show `#variant` and provider model settings, but our scratch
  custom provider config (visible in `opencode debug config`) did not enter the
  ACP model list. Recommendation: use v2's dynamically advertised `effort`
  option when available; retain explicit unsupported handling for v1/other
  models; verify provider payload on an authorized configured runtime before
  claiming backend parameter semantics. Do not hardcode the `effort` ID
  universally.
- **`mode` option:** Both versions advertised `build` and `plan`; v2 descriptions
  identify build as default permission-based execution and plan as read-only
  planning. Live v2 requests setting advertised `configId:"mode"` to `plan`
  and then `build` each succeeded and returned corresponding currentValue.
  These are agent modes, not thinking effort.
- **Part C — MCP fixtures:** An earlier combined v1 attempt with a stdio Node process
  (`process.stdin.resume()`) and host HTTP handler at
  `http://host.docker.internal:18765/mcp` waited 30 seconds for `session/new`
  and raised `asyncio.TimeoutError` with no JSON-RPC result/error. The stdio
  process was not a faithful MCP responder and timed out; it does not prove
  unsupported transport. A corrected v2 run used local Node stdio and Python
  HTTP fixtures. `session/new` returned a result. HTTP fixture captured
  `initialize` using protocol version `2025-11-25`, client `{name:"acp",
  version:"2.0.22"}`, then `notifications/initialized`, then `tools/list`.
  Initial fixture observed `X-WP01: synthetic` on each request; the final marker
  fixture observed `X-WP01: synthetic-header-observed` on each request.
  `mcpServers` supplied HTTP url/headers and stdio `command:"node"`, args
  `[-e,<fixture source>]`, env `[{name:"WP01_SYNTHETIC",value:"safe"}]`.
  This proves v2 session/new accepted both shapes and HTTP connectivity/header
  mapping. A final marker probe mounted a scratch-only host directory at
  `/wp01`; the stdio fixture wrote the environment value to
  `/wp01/stdio-marker` only when it received MCP `initialize`. The final fixture
  env was `[{name:"WP01_SYNTHETIC",value:"stdio-env-observed"}]`; host observed
  marker content `stdio-env-observed`. This proves v2 started the stdio fixture and delivered
  its env entry. Both transport shapes and HTTP headers are proven on v2.
- **Skill prompt receipt:** Live v2 first prompt contained
  `<skill name="synthetic">WP01_SKILL_RECEIPT_MARKER</skill>\nReply OK.`.
  `session/update` `agent_thought_chunk` frames referred to the unique marker;
  runtime then returned `agent_message_chunk` `OK` and prompt result
  `stopReason:"end_turn"`. This proves text reached runtime/model response
  path, not general LLM obedience. Reported cost was zero; no real credentials
  were supplied. Offline test remains a serialization regression proof.
- **Exact validation performed:** `docker run --rm kosmo-opencode:local
  --version` → `1.18.33`; the npm queries above returned the versions/tags
  recorded above; scratch `docker build -t wp01-opencode2:2.0.22 $env:TEMP\wp01-opencode2`
  succeeded; v2 version and `acp --help` commands succeeded; Python asyncio
  ACP initialize/options/mode/effort/prompt/MCP probes returned results above;
  `python "$env:TEMP\wp01_v2_effort_probe.py"` set advertised effort to `high`;
  `python "$env:TEMP\wp01_mode_probe.py"` set both advertised mode values;
  `python "$env:TEMP\wp01_v2_prompt_probe.py"` captured prompt/update/result;
  `python "$env:TEMP\wp01_mcp_faithful.py"` captured HTTP fixture requests;
  `python "$env:TEMP\wp01_mcp_marker_probe.py"` confirmed stdio env receipt.
  The earlier unfaithful fixture command timed out; and
  `uv run --project backend --directory backend pytest
  tests/worker/test_catalog_runtime_probe.py` passed 1 test. No real credentials
  used; no repo image pin, adapter or dependencies changed.
- **Direct coordinator probe (2026-10-04, independent):** Reproduced the v2.0.22
  `session/new` config options exactly: `model` (category `model`), `effort`
  (category `thought_level`, description "Available effort levels for this
  model", values `low`/`high`/`max`/`default`, `currentValue:"default"`) and
  `mode` (build/plan). With a scratch `nan` provider config (from the operator's
  own v2 config) planted at `~/.config/opencode/opencode.json`, `opencode debug
  config` showed it and `opencode --print-logs models` listed `nan/qwen3.6`, but
  the ACP session still offered only the built-in `opencode/*` models. Root
  cause is the **v2 credential store**, not the provider schema: v2.0.22 does
  not consume the v1 `auth.json` object (`opencode auth export` -> `[]`,
  `opencode auth list` -> "No authenticated integrations"); `opencode auth
  import` expects a JSON **array**, and `opencode auth login nan --method key`
  requires an interactive terminal. **Upgrade implication:** moving the Kosmo
  agent runtime to v2 is not just an image bump — provider credential injection
  (currently a v1 `auth.json`) must be reworked for the v2 auth store. Reasoning
  `effort` is confirmed available on v2; model-specific `effort` for
  `nan/qwen3.6` was not confirmable until v2 auth is wired.

### WP-02 — Catalog persistence and migration
- Type / owner: development / Developer (`developer`).
- Objective / ACs: durable three-entity storage, scope/name/race invariants;
  AC-AMS-01/02/07 foundation.
- Included / exclusions: models and repositories only; no CRUD business rules,
  API or workflow reset. Additive table migration, not D8 deletion yet.
- Files / patterns: proposed three domain `models.py`/`repository.py` modules,
  `backend/alembic/versions/0022_agent_catalogs.py`, Alembic model-registration
  imports where required; proposed `backend/tests/domain/test_catalog_persistence.py`.
- Changes / contracts: common metadata/indexes and ordered reference storage per
  contracts; MCP secret ciphertext isolated from safe config. Import identity
  model registration for fresh worker processes. Repositories offer by-id,
  visible candidates, memberships, name conflicts and atomic CRUD. Roll back
  failed commits, no cascading deletion of agent reference IDs.
- Dependencies / ownership: none; owns all three persistence modules and first
  migration. Later domain packages must not change these concurrently.
- Skills: `test-driven-development`, `python-design-patterns`,
  `python-testing-patterns`, `verification-before-completion`.
- Tests / command: RED first for scope checks, DB name races, ordered references,
  fresh-process FK registration and migration upgrade on disposable PostgreSQL;
  `uv run --project backend --directory backend pytest tests/domain/test_catalog_persistence.py`.
- Completion: additive upgrade and repository behavior proven on real PostgreSQL;
  fake repositories alone do not prove indexes/constraints.
- Risks: NULL uniqueness, migration head collisions, accidental JSON reference
  removal. Never point destructive/disposable tests at the owner's database.

### WP-03 — Scoped Skill CRUD
- Type / owner: development / Developer (`developer`).
- Objective / ACs: complete scoped skill service/API; AC-AMS-01/02/10.
- Included / exclusions: description/instructions CRUD, visibility/mutation
  policy, safe DTOs/keyed errors; no frontend or runtime injection.
- Files: proposed `domain/skills/service.py`, `api/routes/skills.py`,
  `tests/domain/test_skills.py`, `tests/api/test_skills.py` under `backend/`.
- Changes / contracts: `/skills` endpoints and shared scope/name contract;
  authenticated reads, owner/admin writes, target-scope policy, no credential
  fields. Keep group-membership role semantics explicit in tests.
- Dependencies / ownership: WP-02. Own skill service/routes/tests; no locale or
  generated-client edits. Dynamic API discovery requires `router`, not main edits.
- Skills: `test-driven-development`, `fastapi-python`, `python-design-patterns`,
  `python-testing-patterns`, `verification-before-completion`.
- Tests / command: test CRUD, invisible IDs, role/group matrix, scope changes,
  duplicate races and bounded safe invalid-body responses RED→GREEN;
  `uv run --project backend --directory backend pytest tests/domain/test_skills.py tests/api/test_skills.py`.
- Completion: complete visible edit/detail flow and unauthorized writes rejected.
- Risks: group members must not acquire edit rights from read visibility alone.

### WP-04 — Encrypted MCP CRUD
- Type / owner: development / Developer (`developer`).
- Objective / ACs: transport authoring with write-only secrets;
  AC-AMS-01/02/07/10, OQ4.
- Included / exclusions: service/routes, input/output schemas, encryption and
  secret keep/replace/remove; no runtime probe endpoint or transport execution.
- Files: proposed `domain/mcp_servers/service.py`, `api/routes/mcp_servers.py`,
  `tests/domain/test_mcp_servers.py`, `tests/api/test_mcp_servers.py` under backend;
  private error-handler changes only if safe validation-body tests require them.
- Changes / contracts: implement discriminated transport and entry write/read
  contracts above. Reuse configured Fernet convention; helpers must be small,
  not a provider service inheritance hierarchy. Redacted detail/list DTOs,
  safe request errors; encrypt before repository writes, never decrypt for API.
- Dependencies / ownership: WP-01/02. Sole MCP service/schema/routes owner;
  coordinate shared error-handler changes with WP-03/05 (serialize if needed).
- Skills: same backend TDD/API/design/testing/verification skills as WP-03.
- Tests / command: RED sentinel tests across DB bytes, DTOs, invalid requests,
  error responses/log capture, all entry actions and encryption-key failure;
  `uv run --project backend --directory backend pytest tests/domain/test_mcp_servers.py tests/api/test_mcp_servers.py`.
- Completion: no secret/ciphertext read endpoint, safe edit retention and explicit
  replacement/deletion proven; authorized scope CRUD complete.
- Risks: Pydantic error `input` echo, URL/command credentials, implicit deletion,
  secret classification toggles and accidental decryption in responses.

### WP-05 — Scoped Agent CRUD and references
- Type / owner: development / Developer (`developer`).
- Objective / ACs: selectable agent defaults and specialization;
  AC-AMS-01/02/04/05/10, D2/D5/D6.
- Included / exclusions: agent service/API, visible relationship validation;
  no workflow rewrite, instruction override, provider credential duplication.
- Files: proposed `domain/agents/service.py`, `api/routes/agents.py`,
  `tests/domain/test_agents.py`, `tests/api/test_agents.py` under backend.
- Changes / contracts: runtime/model/reasoning/instructions/reference fields and
  `/agents` CRUD. Validate changed IDs as actor, retain untouched stale IDs for
  readable repair; safe detail supplies Markdown/defaults. Delete catalog row
  without rewriting referencing workflows; references fail when later used.
- Dependencies / ownership: WP-03/04; owns agent service/routes/tests only.
- Skills: backend skills as WP-03.
- Tests / command: RED→GREEN defaults, unique IDs, scope/reference rejection,
  partial update, deletion with surviving node/reference data;
  `uv run --project backend --directory backend pytest tests/domain/test_agents.py tests/api/test_agents.py`.
- Completion: agent detail supports editor initialization and read-only preview;
  reasoning is a bounded runtime-value contract, no fabricated enum.
- Risks: a shared agent's resources may not be visible to all consumers; document
  that execution uses consumer identity, not agent owner.

### WP-06 — Reference-only AI schema
- Type / owner: development / Developer (`developer`).
- Objective / ACs: exact new definition shape; AC-AMS-03/04/09.
- Included / exclusions: Pydantic node schema, publication/validation contracts,
  affected fixtures; no destructive DB operation or embedded-agent compatibility.
- Files: `backend/shared/graph/schema.py`, relevant graph validators and
  workflow schema/API tests in `backend/tests/{shared,domain,api}/` discovered by
  targeted source search; proposed `tests/shared/test_agent_reference_schema.py`.
- Changes / contracts: node contract above; remove `AgentConfig`, reject legacy
  inline fields; serialize absent overrides minimally. Preserve prompt, inputs,
  outputs and output-validation compatibility. Incomplete drafts remain saveable
  through the existing draft path but cannot publish/test without agent selection.
  Do not add DB catalog calls to pure graph validation; contextual publication
  checks use service boundaries where appropriate and do not freeze resolutions.
- Dependencies / ownership: WP-01 validates reasoning contract; owns shared
  schema and associated fixtures. WP-17 later owns seed; do not race seed edits.
- Skills: `test-driven-development`, `python-testing-patterns`,
  `verification-before-completion`.
- Tests / command: RED missing ID, legacy rejection, UUID/delta overlap/duplicate
  validation, canonical omission and draft/publication behavior;
  `uv run --project backend --directory backend pytest tests/shared/test_agent_reference_schema.py` plus affected workflow tests.
- Completion: no agent-specific normalize/legacy reader remains; fixture audit
  records remaining seed transition assigned to WP-17, not a hidden fallback.
- Risks: many tests hardcode inline agents; migrate those fixtures deliberately,
  never weaken existing validation behavior to accommodate them.

### WP-07 — Worker-local effective catalog resolver
- Type / owner: development / Developer (`developer`).
- Objective / ACs: pure delta application plus authorized live resolution;
  AC-AMS-02/04/06/07/08.
- Included / exclusions: resolve agent/MCP/skill data for a new session, decrypt
  only in worker-local calls; no Temporal activity declaration or UI.
- Files: proposed `backend/app/domain/agents/resolution.py` for composed service
  resolution and pure deltas, `backend/tests/domain/test_agent_resolution.py`;
  worker-only entry/helper if needed to distinguish safe DTOs from runtime data.
- Changes / contracts: resolve exact visible ID and effective lists using current
  memberships of task creator; no name fallback. Ephemeral runtime DTO, deterministic
  order, blocked missing/invisible resources and encryption failure. Decrypt
  after permission checks, no secret repr/logs. Return safe keyed failure kinds.
- Dependencies / ownership: WP-03/04/05/06; owns new resolver/tests. Do not edit
  `ai_node.py` (WP-10 owns integration).
- Skills: `test-driven-development`, `python-design-patterns`,
  `python-testing-patterns`, `verification-before-completion`.
- Tests / command: RED→GREEN precedence/order, all delta edge cases, agent edits,
  membership revocation, missing resources, removed missing IDs, consumer identity;
  `uv run --project backend --directory backend pytest tests/domain/test_agent_resolution.py`.
- Completion: later resolution sees central edits without mutating definitions;
  every failure blocks, permissions precede secret access.
- Risks: accidental use of creator membership cached at submission or agent owner's
  permissions, resolving removals unnecessarily, nondeterministic merged sets.

### WP-08 — Runtime and secrecy tests first
- Type / owner: test / Tester (`tester`).
- Objective / ACs: meaningful RED coverage for adapter/session integration and
  security boundaries before runtime changes; AC-AMS-06/07/08.
- Included / exclusions: behavioral contract tests and opt-in Temporal proof;
  no production implementation or weakening existing input-secrecy tests.
- Files: proposed `backend/tests/worker/test_agent_catalog_execution.py`,
  `test_agent_catalog_secrecy.py`, existing adapter/session tests; reuse
  `test_task_input_secrecy.py` harness patterns without altering its contract.
- Changes / contracts: adapter sees effective model/reasoning, merged MCPs plus
  validator and only effective skills. Sentinel stored encrypted, passed only to
  runtime; activity arguments/results/failures, recorded history, definitions,
  notes/events and logs stay sentinel-free even when ACP raises/echoes it.
  Include a production activity/resolver path with DB or faithful repository
  wiring, not only substitute Temporal activities; replay recorded history.
- Dependencies / ownership: WP-01/07. Tester owns tests until RED report accepted;
  transfer adapter tests to WP-09, integration tests to WP-10 serially. New
  Temporal tests may remain tester-owned until WP-18 runs them after GREEN.
- Skills: `test-driven-development`, `python-testing-patterns`,
  `verification-before-completion`.
- Tests / command: focused new files with standard backend command; real history
  proof in backend container using `KOSMO_TEMPORAL_INTEGRATION=1`, as below.
- Completion: expected missing-behavior failures recorded, no unrelated failure
  misreported as RED; agreed test ownership prevents simultaneous edits.
- Risks: Windows Temporal test-server hangs, Docker/DB skips, overly mocked proof
  that never exercises production resolution. Report environmental blockers.

### WP-09 — ACP model/reasoning/transport delivery
- Type / owner: development / Developer (`developer`).
- Objective / ACs: actual adapter configuration delivery; AC-AMS-06/07, D5.
- Included / exclusions: initialization capability validation, model then reasoning
  config-option selection, MCP wire conversion; no catalog queries or orchestration.
- Files: `backend/worker/adapters/opencode_acp.py`, adapter tests handed off WP-08;
  small proposed pure transport-mapping module if warranted.
- Changes / contracts: keep current advertised-default model resolution. Select
  reasoning using WP-01's discovered capability path after model selection;
  unsupported requested value/capability blocks safely. Map stdio/http catalog
  data to ACP server union; inspect initialize capabilities, do not discard servers.
- Dependencies / ownership: WP-08; owns adapter only. WP-10 runs afterward because
  diagnostic/event boundary changes may also touch adapter normalization.
- Skills: `test-driven-development`, `python-testing-patterns`,
  `verification-before-completion`.
- Tests / command: make assigned RED adapter tests GREEN, test unsupported option,
  changed options after model selection and HTTP/stdio mapping; focused adapter
  files plus `uv run --project backend --directory backend pytest tests/worker`.
- Completion: proven request shapes/order, no silent reasoning/transport fallback.
- Risks: config options can vary by model/runtime version; avoid hardcoded IDs.

### WP-10 — Live AI session integration and safe diagnostics
- Type / owner: development / Developer (`developer`).
- Objective / ACs: new sessions use live consumer-visible catalogs and never
  expose resolved secrets; AC-AMS-03/06/07/08.
- Included / exclusions: activity-side resolution, effective config argument to
  orchestration, skills text delivery and safe error/event handling. No Temporal
  workflow-side DB calls, propagation, snapshot or second credential activity.
- Files: `backend/worker/activities/{ai_node,agent,tasks}.py`, bounded adapter
  event normalization changes if required, WP-08 integration tests. Task workflow
  should need no catalog logic; inspect it for payload regressions.
- Changes / contracts: derive task creator from DB, resolve inside activity,
  pass effective config separately to `orchestrate_ai_node`; replace all inline
  `node.agent` consumption. First prompt includes full skill sections; platform
  validator remains non-removable. Preserve provider files, isolation, recovery,
  completion validation, human input and cleanup. Replace raw traceback logging
  and sanitize configured-secret echoes before note/event/diagnostic persistence.
  Safe localized resolution/unsupported-option errors survive task reporting.
- Dependencies / ownership: WP-07/08/09; owns activity edits and transferred tests;
  serialize adapter edits after WP-09. No locale edits (WP-12 owns error messages).
- Skills: `test-driven-development`, `python-design-patterns`,
  `python-testing-patterns`, `verification-before-completion`;
  `systematic-debugging` for regression failures.
- Tests / command: make WP-08 runtime tests GREEN; replay/input-secrecy regression,
  retry sees updated agent, recover avoids session, creator visibility ignores
  spoofed payload user; `uv run --project backend --directory backend pytest tests/worker`.
- Completion: live successful execution plus blocked D9 results, no plaintext
  crossings; session close still occurs on failure/stop and secrets stay tmpfs/
  runtime-local rather than mounted credential files.
- Risks: raw ACP exceptions/input requests can echo tokens; catch-all generic
  failure must not swallow catalog error keys; durable recovery must not repeat work.

### WP-11 — Typed frontend catalog and override state
- Type / owner: development / Developer (`developer`).
- Objective / ACs: functional frontend data/serialization seam;
  AC-AMS-03/04/09 foundation, no visual redesign.
- Included / exclusions: OpenAPI client regeneration, typed catalog fetch/mutate
  helpers, editor model/default/reducer/serialization; no screens or UI components.
- Files: `frontend/src/api/schema.d.ts`, proposed
  `frontend/src/features/catalogs/api.ts`, `catalogTypes.ts`,
  `frontend/src/features/workflows/editor/model.ts`, associated tests and proposed
  `agentOverrides.ts`/`agentOverrides.test.ts`. Inspect exact editor store modules.
- Changes / contracts: use `api` and generated response types, local refetch
  patterns; no manual generated-file editing. Pure helpers compute display and
  intentional overrides; agent switch clears, reset scalar removes, refresh does
  not rewrite deltas. New unsaved AI nodes have unset selection and publication
  issue, not a fabricated catalog ID. Remove embedded agent defaults/normalizers.
- Dependencies / ownership: WP-05/06. Sole generated client/editor model owner;
  WP-12/16 consume contracts afterward. Persist reference-only canonical JSON.
- Skills: `test-driven-development`, `vercel-react-best-practices`,
  `verification-before-completion`.
- Tests / commands: RED roundtrip/refetch/switch/reset/live baseline/delta tests;
  `pnpm -C frontend test`, `pnpm -C frontend build`; regenerate with the CI
  export/OpenAPI command pattern below and verify generated diff.
- Completion: model helpers preserve unrelated node data/phases/output contracts;
  explicit overrides never become inherited snapshots on save.
- Risks: handwritten broad node union and fixtures; API draft save permissiveness
  must remain compatible with incomplete selection.

### WP-12 — Shared catalog controls and safe Markdown
- Type / owner: design / Designer (`designer`).
- Objective / ACs: consistent reusable presentation and read-only preview;
  AC-AMS-01/05/10 foundations.
- Included / exclusions: small catalog list/form building blocks, scope controls,
  accessible searchable single/multi selection, safe Markdown preview/dialog;
  no entity screens or editor panel edits yet.
- Files: proposed `frontend/src/features/catalogs/components/`,
  Markdown preview shared component/tests, both `src/i18n/locales/{en,es}.json`,
  dependency manifest/lock only for justified Markdown rendering dependency.
- Changes / contracts: reuse `Button`, `Icon`, `RowActions`, `ConfirmDialog`,
  Radix dialog, `KosmoErrorAlert` and provider loading/focus/refetch behavior.
  No new generic form engine. Markdown renders without raw HTML, unsafe links,
  scripts or embedded remote resource loading; no `dangerouslySetInnerHTML` on
  authored text. Reuse an existing safe renderer if source inspection finds one;
  otherwise add one minimal vetted renderer with HTML disabled and link checks.
  Add backend error keys and common catalog strings in en/es.
- Dependencies / ownership: WP-11; owns shared components and locale files until
  done. Later screen packages serialize all locale edits. Record new dependency
  need and sync containers before testing.
- Skills: `impeccable`, `test-driven-development` for interactions,
  `vercel-react-best-practices`, `verification-before-completion`.
- Tests / commands: RED focus/search/selection/reset, Markdown XSS/unsafe URL,
  namespace parity and backend-key translations; `pnpm -C frontend test` and build.
- Completion: reusable bounded controls with loading/empty/error/keyboard states;
  Markdown is read-only and safe in both agent edit preview and node view.
- Risks: Markdown package absent in inspected package.json, focus traps and screen
  widths; don't expand into a design-system or dependency migration.

### WP-13 — Skill catalog screen
- Type / owner: design / Designer (`designer`).
- Objective / ACs: usable scoped skill catalog; AC-AMS-01/02/10.
- Included / exclusions: list/create/edit/delete/detail form and scope controls;
  no agent editor or marketplace.
- Files: proposed `frontend/src/features/skills/SkillsPage.tsx` and tests,
  `src/app/router.tsx`, locale catalogs. Preserve current `/admin/skills` URL.
- Changes / contracts: typed API, common Add, owner/admin actions, Markdown
  instructions editor with preview, description/name/scope, deletion confirmation,
  errors/refetch/focus continuity; unavailable group options not offered.
- Dependencies / ownership: WP-03/12; owns router/locales during package. WP-14
  follows to avoid overlap; server remains authoritative for authorization.
- Skills: same frontend design/TDD/React/verification skills as WP-12.
- Tests / commands: RED CRUD interactions, scope rejection, invisible entries,
  form preservation on error, cancel/delete focus; `pnpm -C frontend test` and build.
- Completion: real catalog route replaces placeholder and en/es text renders.
- Risks: viewing an entry is not permission to edit; no role inference from URL.

### WP-14 — MCP catalog screen
- Type / owner: design / Designer (`designer`).
- Objective / ACs: transport authoring with safe write-only secret interaction;
  AC-AMS-01/02/07/10.
- Included / exclusions: MCP CRUD UI, discriminated fields and entry secret
  actions; no verification wizard or actual MCP invocation from browser.
- Files: proposed `frontend/src/features/mcp-servers/McpServersPage.tsx` and
  bounded transport form/tests, router/locales; keep `/admin/mcps` URL.
- Changes / contracts: command+args+env or URL+headers, name/scope, secret switches,
  set/not-set markers and explicit replace/remove. Editing retains via `keep`,
  never preloads secret/ciphertext. Secret inputs masked, no console/error logging,
  browser storage or reusable secret placeholders sent as replacement values.
- Dependencies / ownership: WP-04/13; sole router/locales owner until WP-15.
- Skills: `impeccable`, `test-driven-development`,
  `vercel-react-best-practices`, `verification-before-completion`.
- Tests / commands: RED exact request action shapes, retention/blank replacement,
  transport switch, duplicate entries and safe server error display;
  `pnpm -C frontend test`, `pnpm -C frontend build`.
- Completion: all authorized scoped CRUD and secret operations work without a
  client-side secret readback path.
- Risks: ambiguous empty inputs, transport switching destroys hidden values;
  require explicit confirmation when discarding secret entries.

### WP-15 — Agent catalog screen
- Type / owner: design / Designer (`designer`).
- Objective / ACs: agent specialization and default-resource authoring;
  AC-AMS-01/02/04/05/10.
- Included / exclusions: agent CRUD, defaults and visible reference controls;
  no affected-node propagation/diff or credential storage.
- Files: proposed `frontend/src/features/agents/AgentsPage.tsx` and tests,
  router/locales; preserve `/admin/agents`. Reuse provider model-discovery API
  and relevant selector parts without requiring a new provider instance ID.
- Changes / contracts: runtime fixed opencode, model/default selection, reasoning
  option value (WP-01 contract), instructions Markdown edit+preview, searchable
  MCP/skill selection and scope. Existing stale references appear as unavailable
  removable chips, not silently dropped during unrelated edits. Explain live
  central-change behavior without introducing propagation controls.
- Dependencies / ownership: WP-05/14; owns router/locales until WP-16.
- Skills: same design/TDD/React/verification skills as WP-14.
- Tests / commands: RED create/edit defaults, unavailable references, ordered
  multi-select, read-only permissions and central-edit save; frontend test/build.
- Completion: visible agent detail supplies all default fields and instructions;
  no inline workflow edits or arbitrary unsupported runtime options claimed valid.
- Risks: providers advertise model-dependent reasoning; preserve stored value
  with clear unsupported indication rather than silently normalizing it.

### WP-16 — AI reference and override properties
- Type / owner: design / Designer (`designer`).
- Objective / ACs: complete agent-based AI properties; AC-AMS-03/04/05/10.
- Included / exclusions: agent selector, inherited defaults, intentional override
  controls and read-only preview; preserve prompt/IO/output validation.
- Files: `frontend/src/features/workflows/editor/PropertiesPanel.tsx`, proposed
  `AiAgentProperties.tsx` and tests, relevant existing panel tests and locales;
  remove old inline controls, reuse provider model selector parts where useful.
- Changes / contracts: searchable visible agents, initialized display without
  snapshotting, explicit model/reasoning override/reset, effective MCP/skills
  add/remove, different agent clears overrides, reopen/refresh preserves them.
  'View instructions' opens safe Markdown read-only dialog; empty/deleted/
  invisible reference shows localized blocking authoring state, never chooses
  another agent automatically. Async stale responses cannot overwrite selection.
- Dependencies / ownership: WP-11/12/15; owns panel/locales. Do not alter WP-11
  helpers without serialized handoff. Publish/draft flows retain existing behavior.
- Skills: `impeccable`, `test-driven-development`,
  `vercel-react-best-practices`, `verification-before-completion`.
- Tests / commands: RED selector/change/reset/refetch/multi-select requests,
  saved JSON lacks instructions/default snapshots; Markdown read-only, stale
  response and loading/error tests; `pnpm -C frontend test`, build.
- Completion: all four inherited settings overridable, agent switch resets them,
  no prompt/IO/phase/output-validation regression; en/es panel is complete.
- Risks: confusing 'same as current default' with 'inherit'; editing list deltas
  must not erase a removal just because the agent temporarily removed that ID.

### WP-17 — Destructive workflow reset and reference reseed
- Type / owner: development / Developer (`developer`).
- Objective / ACs: deliberate one-way cutover to new standard; AC-AMS-09,
  with AC-AMS-03/06 reference workflow integration.
- Included / exclusions: destructive migration, seed update, obsolete fixture
  cleanup and cutover procedure; do not preserve embedded-agent definitions.
- Files: proposed `backend/alembic/versions/0023_agent_reference_reset.py`,
  `backend/scripts/seed.py`, proposed migration/seed tests under
  `backend/tests/domain/`; update this record with operational evidence only.
- Changes / contracts: explicitly reset all workflow authoring/execution DB data:
  dependent task rows first, then activations/drafts/versions/workflows, including
  orphan drafts without workflow ID. Use actual FK dependency inspection and
  existing 0021 conventions, **not** an unreviewed TRUNCATE CASCADE. Task-owned
  metadata cascades are verified; catalog/provider/identity data preserved.
  Frozen migration SQL must not import mutable application seed/schema code.
  Record non-restorability in downgrade. Run updated idempotent seed after
  upgrade when no workflows remain: create/reuse global reference agent owned
  by seeded admin (model default, no reasoning override, no user MCP/skills),
  then active reference workflow uses its UUID; ensure admin is flushed first.
  Separate migration deletion from explicit post-migration reseed invocation;
  both steps belong to the cutover, not an optional forgotten manual follow-up.
- Dependencies / ownership: WP-02/05/06/10/16 and integrated preflight. Sole new
  reset migration/seed owner. Allocate migration head after WP-02, serialize.
- Skills: `test-driven-development`, `python-testing-patterns`,
  `verification-before-completion`.
- Tests / commands: disposable PostgreSQL populated with published versions,
  drafts/orphans, tasks/dependents and catalogs; RED→GREEN reset completeness,
  preserved credentials/identity, empty database seed, repeated seed no duplicate,
  reference definition parse+active publication. Run new focused migration tests
  via backend pytest. Application commands, after operator gate only:
  `docker compose exec backend uv run alembic upgrade head` then
  `docker compose exec backend uv run python -m scripts.seed`.
- Completion: disposable-DB proof first; approved target cutover records backup,
  affected IDs/counts, terminated/drained Temporal executions, empty workflow
  state then one reference workflow and reference agent, no legacy read path.
- Risks: D8 approves destruction, not unmanaged production execution. Coordinator
  schedules maintenance, backup/restore check, stops affected Temporal runs and
  workers, prevents old workers/API from serving during cutover, and arranges
  deletion/quarantine of old task-storage/checkpoint directories by captured IDs
  outside Alembic (DB migration cannot clean Docker volumes/history). Existing
  Temporal history is not retroactively sanitized. Restart upgraded worker/API
  only after upgrade+seed, then resume traffic. No owner DB test runs.

### WP-18 — Integrated acceptance and browser proof
- Type / owner: test / Tester (`tester`).
- Objective / ACs: verify AC-AMS-01…10 across actual API/editor/worker boundaries.
- Included / exclusions: integrated regression/E2E/secret history/replay and
  responsive evidence; not the only test stage, no broad test-debt cleanup.
- Files: proposed `frontend/e2e/agent-mcp-skills.e2e.ts`, relevant existing E2E
  setup/fixtures, WP-08 tests after ownership transfer, record status/results.
- Changes / contracts: real API scoped catalog authoring → reference-only draft
  → publish → agent central edit → execute/retry observes new values; negative
  missing/invisible agent/MCP/skill and revocation paths block with translated
  keys; three CRUD screens and panel in en/es. Verify set/keep/replace/remove and
  no secret readback/history/logs using synthetic sentinels. Real fixture MCP
  stdio+HTTP delivery and skills prompt proof; real-model outcome is separately
  credential-gated, never replaced by mocked success claims.
- Dependencies / ownership: all prior packages, clean cutover on disposable/dev
  test stack. Own E2E tests; no production fixes except coordinator-assigned
  remediation packages. Update stale old inline-agent journeys explicitly.
- Skills: `test-driven-development` for new integration regressions,
  `python-testing-patterns`, `verification-before-completion`,
  `systematic-debugging` for failures; `web-design-guidelines` for targeted UI review.
- Tests / commands: full backend/frontend/build/client regen/compose checks below,
  `pnpm -C frontend e2e`; run Temporal proof in container. Browser evidence at
  375/768/1280px includes no overflow, keyboard selection/dialog focus, secret
  controls, Markdown and long/unavailable resource names. Record failures/skips.
- Completion: AC evidence matrix, integrated GREEN results and explicit remaining
  environment limitations ready for architect review; no 'implemented' claim
  based solely on mocks or passing package reports.
- Risks: worker reload requires restart; tests with OpenCode/provider credentials
  are not safe to run with arbitrary external tool destinations.

## Ordering, test-first rules and shared-file ownership

1. WP-01 and WP-02 may run in parallel (probe versus persistence ownership).
2. WP-03 can follow WP-02 while WP-01 finishes. WP-04 follows both gates;
   WP-05 follows WP-03/04. WP-06 may run separately after WP-01 but catalog
   fixtures must use the fixed IDs/contracts, not invent alternate schemas.
3. WP-07 → WP-08 (RED handoff) → WP-09 → WP-10. No integration implementation
   before the relevant RED evidence. Pure resolver TDD is owned within WP-07.
4. WP-11 can run after WP-05/06 alongside WP-07…10 (distinct frontend files).
   WP-12 → WP-13 → WP-14 → WP-15 → WP-16 serialize router/locale/shared UI edits.
5. Every development/design package owns its behavioral RED→GREEN→refactor
   cycle unless WP-08 supplies it. Pure presentation changes use proportionate
   browser checks rather than artificial unit tests. Migration tests are
   test-first on disposable databases before any target reset.
6. Preflight integrated tests, confirm destructive cutover prerequisites, then
   WP-17, restart containers and WP-18. Do not serve half-migrated schemas.
7. Coordinator integrates and requests architecture review; findings become
   remediation packages. Only after approval invoke documentator to reconcile
   durable context/README/spec status (including old live-versus-snapshot text).
   Architecture/documentation are stages, not additional package types.

## Acceptance coverage

| Criterion | Implementation packages | Verification |
| --- | --- | --- |
| AC-AMS-01 | 02–05, 12–15 | domain/API role matrix, screen tests, WP-18 scoped CRUD |
| AC-AMS-02 | 02–05, 07, 11–16 | visible list/exact-ID tests, consumer revocation, WP-18 |
| AC-AMS-03 | 06, 10, 11, 16 | legacy rejection, serialized workflow/API roundtrip, WP-18 |
| AC-AMS-04 | 05–07, 11, 15–16 | delta/live-edit/refetch/switch tests, WP-18 |
| AC-AMS-05 | 05, 12, 15–16 | safe read-only Markdown tests and browser WP-18 |
| AC-AMS-06 | 01, 07–10 | adapter/probe/worker integration, WP-18 actual delivery |
| AC-AMS-07 | 02, 04, 07–10, 14 | encrypted DB, DTO/log/event/history sentinel tests, WP-18 |
| AC-AMS-08 | 07, 10, 12, 16 | keyed blocked task tests; missing skill also required by D9 |
| AC-AMS-09 | 06, 11, 17 | PostgreSQL reset/reseed, legacy-path audit and WP-18 |
| AC-AMS-10 | 12–16 | nested locale parity and en/es journeys, WP-18 |

## Verification commands and execution notes

Verified **command definitions/patterns**, not passing execution results:

```powershell
uv run --project backend --directory backend pytest
pnpm -C frontend test
pnpm -C frontend build
pnpm -C frontend e2e
docker compose -f docker-compose.yml config -q
```

Client regeneration (matching CI; generated output owned by WP-11):

```powershell
uv run --project backend --directory backend python -c "import json; from pathlib import Path; from app.main import create_app; Path('../openapi.json').write_text(json.dumps(create_app().openapi()), encoding='utf-8')"
pnpm -C frontend exec openapi-typescript ../openapi.json -o src/api/schema.d.ts
```

Do not commit the temporary OpenAPI export. After committed API/client changes,
CI regeneration must have no new generated diff. A pre-commit dirty generated
file alone is not a regeneration failure.

Proposed new secrecy proof command, after WP-08 creates that test module:

```powershell
docker compose exec -e KOSMO_TEMPORAL_INTEGRATION=1 backend uv run pytest tests/worker/test_agent_catalog_secrecy.py tests/worker/test_task_input_secrecy.py
```

Use `KOSMO_TEST_DATABASE_URL` with a dedicated disposable PostgreSQL database
for DB boundary tests. Inspect fixture setup before invoking migration tests;
never assume a skipped DB/Docker/Temporal suite proves acceptance. New backend
dependencies require container `uv sync`, frontend ones `pnpm install`; restart
the worker after worker module changes. No host/container availability was
proven during this planning session.

## Status log (living record)

- 2026-10-04: WP-01…WP-18 **Planned**. No implementation, tests, runtime probes,
  destructive migration or commits executed. OQ3/OQ4 architectural contracts
  selected; installed-runtime proof and reasoning capability remain WP-01 gates.
- Coordinator scope confirmation to record: provider-policy parity (personal
  for authenticated users; group manager membership/admin for group sharing).
  If owner expects ordinary builders to share to any joined group or runner/
  viewer writes to be forbidden, return that policy change for explicit agreement
  before dependent CRUD execution, rather than altering policies silently.
