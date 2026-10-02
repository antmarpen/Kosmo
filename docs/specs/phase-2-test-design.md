# Phase 2 — Acceptance Test Design

Status: Test design for P2-18; scenarios are planned, not executed.
Source: `phase-2-provider-editor.md` (approved 2026-10-01), AC-P2-01–AC-P2-10.

## Test strategy and prerequisites

- Use Playwright E2E for observable journeys and backend integration tests for authorization, persistence, schema validation, privacy, and conflict behavior. Assert stable API contracts and localized user-facing messages, not implementation internals.
- Reuse the login/API patterns in `frontend/e2e/phase1.e2e.ts`. Suggested env: `KOSMO_E2E_USERNAME`, `KOSMO_E2E_PASSWORD`, base URL/configured API URL, and dedicated builder, runner, group-manager, admin, and second-builder credentials. Do not use production data. Seed at least one group with two members, personal/group/global provider fixtures, and a workflow owned by builder A.
- Provider-config tests should use isolated fixtures and remove them afterward. A real Verify journey requires configured provider credentials and a reachable container runtime. `OPENCODE_API_KEY` is currently unset; therefore a successful real AI/provider verification or end-to-end AI task success cannot be claimed locally. Keep those scenarios skipped/config-gated unless a dedicated secret is supplied. Never log or assert secret values.
- Backend integration tests should exercise actual authenticated APIs and persistence; browser checks should establish rendered/localized behavior. Tests requiring backend contract additions or behavior not specified below are blockers/questions, not assumptions.

## Acceptance criteria scenarios

### AC-P2-01 — provider onboarding and verification

- **Checks:** Playwright happy-path/error presentation plus backend integration for provider APIs and role/scope authorization.
- **Journey/API:** Sign in as builder; navigate to Providers; choose OpenCode; upload valid `opencode.json`; advance through validation and model discovery; select a model; click Verify; choose personal scope; commit. Exercise the config-without-credentials branch separately.
- **Assertions:** Valid config is accepted; model options are displayed and selectable; commit persists metadata; Verify shows success and latency only with valid configured auth, otherwise a clear localized auth-missing/structured failure. Never expect success when credentials are absent.
- **Prerequisites:** Builder account; valid isolated config/model fixture; container runtime. Real success requires provider credentials; `OPENCODE_API_KEY` is unset, so credential-backed success is not currently runnable.
- **Journey coverage:** Happy path; invalid config is rejected without commit (AC-02); auth missing produces clear result; attempt to verify/use another task's provider is denied (backend 403 and no credential leakage). Cross-task denial is an important authorization regression, though the spec does not define the exact provider-to-task API contract.

### AC-P2-02 — invalid config handling and non-overwrite

- **Checks:** Playwright upload errors and backend integration persistence test.
- **Journey/API:** As builder, create a valid config and record its ID/metadata; upload malformed JSON, then valid JSON missing `providers`; attempt replacement of the existing config with each invalid file. Exercise ignored MCP/skill fields in an otherwise valid config.
- **Assertions:** Malformed JSON and missing providers produce specific structured/localized violations associated with file/section; invalid attempts do not alter the prior valid config or credentials; irrelevant MCP/skill sections do not trigger provider-schema rejection.
- **Prerequisites:** Builder; valid config fixture and malformed/missing-section files; config read access as owner.
- **OPENCODE_API_KEY:** Not required for schema checks.

### AC-P2-03 — scope permissions

- **Checks:** Playwright scope choices/error localization and backend integration status/visibility checks.
- **Journey/API:** Builder commits personal provider; group manager commits personal and own-group providers; admin commits personal, group, and global. Builder attempts global via UI and direct provider-config API. Query as owner, same-group member, unrelated user, and admin.
- **Assertions:** UI offers only allowed scopes; personal/group/global values persist; unauthorized global API request is 403 with KosmoError message key localized in en/es; visibility is personal-to-owner, group-to-members, global-to-authenticated users. Non-owners receive metadata only, never config/credential contents.
- **Prerequisites:** Builder, group manager, admin, same-group and unrelated accounts; group fixture; API auth tokens.
- **OPENCODE_API_KEY:** Not required.

### AC-P2-04 — create and save workflow draft

- **Checks:** Playwright editor journey plus backend integration for draft save/persistence and full-definition contract.
- **Journey/API:** Builder opens `/workflows`, creates workflow, places Start, Script, AI, End; connects nodes; configures Start input, Script code/contracts, AI runtime/model/instructions/prompt/inputs/outputs/three validation levels; saves draft; reloads editor.
- **Assertions:** Catalog nodes can be placed and connected; properties reflect selected node and swap/close correctly; save submits the complete definition and draft remains after reload with node IDs, edges, properties and workflow name intact.
- **Prerequisites:** Builder; at least one selectable agent/model config; test workflow cleanup strategy. AI execution credentials are not needed to author/save.
- **OPENCODE_API_KEY:** Not required to save; required only for real provider-backed execution later.

### AC-P2-05 — inline server validation

- **Checks:** Playwright validation display and backend integration for structured validation details.
- **Journey/API:** Save a draft with missing End; then save with an unconnected output/invalid graph. Inspect request/response and editor.
- **Assertions:** Server validation returns structured details; UI maps each error to the correct node/field and renders inline (including missing end and unconnected output examples); errors clear/recompute after correction. Do not assert client-only feedback as proof of server validation.
- **Prerequisites:** Builder; drafts containing one or multiple deterministic validation errors.
- **OPENCODE_API_KEY:** Not required.

### AC-P2-06 — publication, versioning, activation default

- **Checks:** Playwright publish dialog/checkbox and backend integration version/activation checks.
- **Journey/API:** Save valid draft; publish with Activate unchecked (default); inspect workflow versions and active version; edit and publish again; optionally publish with Activate checked.
- **Assertions:** Invalid draft cannot publish; first publication creates next version (N+1 on subsequent publish); checkbox defaults off; publish-only creates immutable version and leaves activation unchanged; checked activation selects newly published version. Verify API and UI agree.
- **Prerequisites:** Builder; valid draft; known prior version/activation state; isolated workflow.
- **OPENCODE_API_KEY:** Not required for publication.

### AC-P2-07 — recent publication confirmation between users

- **Checks:** Two-user Playwright journey plus backend integration for concurrency/conflict metadata if exposed.
- **Journey/API:** Builder A publishes; within five minutes builder B opens/publishes based on stale authoring state. Repeat after five minutes using controlled clock/backend fixture where feasible.
- **Assertions:** Recent other-user publication forces an explicit confirmation before overwriting authoring state; cancel leaves B's state untouched, confirm continues according to server contract. Outside five minutes, no recent-publication confirmation is required. Assert actor/time context without leaking private data.
- **Prerequisites:** Two builder accounts, shared workflow authorization, deterministic clock or controlled timestamps, synchronized test execution.
- **OPENCODE_API_KEY:** Not required.

### AC-P2-08 — activation and execution end-to-end

- **Checks:** Playwright task submission/observation and backend integration for task binding to active workflow/version and completion/error state.
- **Journey/API:** Publish and activate workflow; sign in as runner; open `/tasks/new`; select workflow, provide required start inputs, submit; poll task/detail until terminal state; inspect node executions/artifacts.
- **Assertions:** Runner can select the active version and submission binds to it; configured Start→Script→AI→End executes in order and reaches success when dependencies/credentials work; structured failure is surfaced without stack trace when AI auth is missing. Include explicit unsupported HTTP/Workflow execution regression (see below).
- **Prerequisites:** Runner, activated valid workflow, worker/Temporal/container runtime, script sandbox; provider credentials for AI success. `OPENCODE_API_KEY` unset: success path cannot be certified; run credential-independent task portions and assert clear failure branch until secret is provisioned.

### AC-P2-09 — responsive behavior

- **Checks:** Playwright viewport/layout smoke tests.
- **Journey/API:** Open workflow editor at 768px and 1280px; select node and operate properties panel/canvas. Open task creation and task detail at 375px.
- **Assertions:** At editor widths catalog, canvas, and properties controls are visible/usable without blocking overflow; 768px properties panel behavior remains operable. At 375px task form and task detail primary actions/content fit viewport and remain usable. Mobile canvas editing is explicitly not a phase-2 requirement.
- **Prerequisites:** Authenticated builder and runner; valid workflow/task fixture.
- **OPENCODE_API_KEY:** Not required.

### AC-P2-10 — English/Spanish parity

- **Checks:** Automated catalog parity/unit test plus Playwright locale journeys covering all new provider/editor labels and errors.
- **Journey/API:** Open provider wizard, config errors, scope controls, workflow list/editor/catalog/properties, save validation and publish flows in English; switch to Spanish and traverse the same states.
- **Assertions:** All new UI labels, accessible names, validation/errors and action text are translated; nested en/es catalog key sets match for the new namespaces; no raw keys or untranslated English fallback appears in Spanish. Validate localized server KosmoError message keys too.
- **Prerequisites:** Both catalogs loaded; deterministic invalid-config and invalid-draft fixtures.
- **OPENCODE_API_KEY:** Not required.

## Required cross-journey coverage

### Provider onboarding detail

Test the full sequence: type selection → auth method/config upload → schema validation → model discovery → model selection → real verification → scope selection → commit. Positive coverage uses valid OpenCode config, discovers/selects a model, verifies a non-empty response, and persists at chosen allowed scope. Failure branches: malformed/missing-provider config rejected and existing config retained; valid shape but missing credentials yields clear structured auth failure; unsupported scope denied; cross-task access/use denied with no secret returned. Claude Code/Codex auth choices (API key or config) need UI selection/schema tests only unless adapters are explicitly in scope; their adapters are phase 3. The real verification success branch requires external credentials/runtime and is blocked by unset `OPENCODE_API_KEY`.

### Workflow editor detail

Exercise create → place nodes → connect → configure properties → save draft → server validation errors inline → publish → activate → execute. Include selection-change/close behavior, node deletion, save/reload round trip, publish checkbox-off default, and revision/conflict behavior if the API exposes it. Monaco must load only when Script properties open; assert no Monaco bundle request on editor load or non-Script selection, and a lazy load on Script selection (performance contract from spec).

### Two-user scope/privacy/publication

Use two builders and role/scope fixtures. Verify recent-publication confirmation within five minutes. Verify personal/group/global visibility as owner/member/unrelated user. For every visible non-owned provider, assert only name, type, visibility, model count, and status are returned/rendered; explicitly assert secrets and raw config are absent in API payload and DOM. Verify owner/admin edit/delete restrictions via UI and direct API. Global visibility is admin-only.

### Node authoring and unsupported-execution regression

Place/configure Decision with manual routes and Workflow node selecting an existing workflow; assert their schema-compatible properties persist in drafts. Execute each unsupported HTTP and Workflow node in isolated tasks and assert deterministic, structured “not supported” failure (not silent success, hang, or stack trace), matching the approved spec's explicit phase-2 execution limitation. Decision execution behavior should be verified for supported manual route selection only; model-backed decisions are phase 3.

### Responsive and localization

Run editor screenshots/interaction checks at 768 and 1280 widths, task views at 375. Exercise English/Spanish parity across provider onboarding, config/schema errors, scope-denial errors, editor catalog/properties, validation and publication confirmation; enforce catalog nested-key parity and absence of untranslated-key fallback.

## Spec gaps and risks to resolve before implementation tests are made executable

1. AC-P2-01 says “Administration > Providers” while approved behavior moves Providers to the main sidebar for all authenticated users. Test navigation against the explicit cross-cutting navigation decision; coordinator should reconcile AC wording.
2. AC-P2-03 says a builder can set personal or group scope, while expected role model restricts builders to personal and group managers to group. Test role table in expected behavior; clarify whether AC's “group they belong to” is an exception.
3. Phase 1 notes say no group tables yet, but phase 2 depends on group membership and group-scoped providers; seed/API fixture strategy and group endpoints are unspecified.
4. Draft endpoints, draft persistence/ownership, optimistic revision/conflict response, and recent-publication signal/confirmation contract are not concretely specified. AC-P2-07 does not define what state is overwritten or the API mechanism/time source.
5. “Cross-task denial” and provider-to-task relationship are not defined by phase-2 ACs. Test only once exact endpoint/permission semantics are specified; do not invent an API.
6. Provider config API payload shapes, config upload limits, duplicate/replacement semantics, API-key transport, and exact structured schema-error keys are unspecified. Tests should bind to finalized API contract and stable message keys.
7. Model discovery and real verification depend on provider/container availability; `OPENCODE_API_KEY` is unset. Mocked contract tests cannot prove a real non-empty response.
8. AC-P2-08 demands complete AI task success, but phase 1 E2E explicitly branches on missing `OPENCODE_API_KEY`. Provision a CI secret or retain a clearly reported skipped credential-backed assertion; never treat missing-auth failure as success-path evidence.
9. AC-P2-10 “no hardcoded strings” is broader than browser E2E can prove. Catalog key parity/static extraction should complement runtime locale checks.
10. Phase 1 work-package notes are implementation/coordinator notes rather than a definitive feature inventory; use actual API contracts when implementation lands and update scenarios if they differ.
