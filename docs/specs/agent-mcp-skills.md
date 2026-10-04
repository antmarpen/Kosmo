# Agent, MCP server, and skill catalogs + AI node selection

Status: **Implemented** (2026-10-04)
Owner: product owner
Related: `docs/product-vision.md` §2–3, `docs/context/project.md`,
`docs/specs/phase-2-workflow-editor.md`.

## Problem

Today an AI node embeds its whole agent configuration inline
(`AiNode.agent = {runtime, model, instructions}`), and the "Agentes", "MCP" and
"Skills" navigation entries are placeholders with no entities or APIs. The
product vision says workflow nodes must **reference** platform configuration
instead of embedding it: an AI node selects an agent, and the agent groups the
specialization instructions, model, MCP servers and skills.

This increment introduces the three configuration catalogs and makes the AI node
select and consume them.

## Intended users

- **Builders** author workflows and select an agent/MCPs/skills for AI nodes.
- **Builders, group managers, admins** create and share catalog entries at
  personal, group or global scope.
- **Admins** curate global entries.

## Goals

- First-class, scoped **Agent**, **MCP server** and **Skill** catalogs with CRUD,
  mirroring the visibility model already used by provider configurations
  (`personal` / `group` / `global`, precedence personal > group > global).
- The AI node **selects an agent by reference** and inherits its model,
  reasoning effort, MCP servers and skills.
- Instructions **move to the agent**; the node no longer stores instructions and
  offers a read-only **View instructions** action rendered as Markdown.
- The node may **override the model and reasoning effort** and may **edit the
  effective MCP and skill lists** (add/remove).
- Execution resolves the effective configuration and injects it into the agent
  runtime (OpenCode ACP `session/new` `mcpServers`, plus the skill delivery
  mechanism).

## Non-goals (deferred)

- Propagation of agent changes into existing drafts/versions (the vision's diff /
  auto-apply / replace-or-retain rules). **Deferred by owner decision.**
- Extensions and integration instances.
- Claude Code / Codex adapters; agent egress filtering.
- A skill marketplace/browser, MCP credential verification UI.
- Notes/audit UI beyond what the catalogs already emit.

## Confirmed decisions

- **D1 — Full catalogs.** Build Agents, MCP servers and Skills as first-class,
  scoped entities with CRUD and visibility `personal`/`group`/`global`, reusing
  the provider-configuration scope policy and secret handling.
- **D2 — Node selects an agent.** The AI node references an agent; it inherits
  the agent's model, reasoning effort, MCP servers and skills. Instructions live
  on the agent only.
- **D3 — Node overrides.** The author can override the model and reasoning effort
  and can add/remove MCP servers and skills at the node.
- **D4 — View instructions.** Selecting an agent exposes a read-only
  "View instructions" affordance that renders the agent's instructions as
  Markdown.
- **D5 — Reasoning effort now.** The agent carries a reasoning-effort field; the
  node can override it.
- **D6 — Propagation deferred.** Changing an agent does not rewrite existing
  workflow drafts or versions in this increment.
- **D7 — Live agent + node overrides.** The node stores the agent reference plus
  only its intentional overrides. At execution the agent is resolved live
  (visible to the task user) and the node overrides are applied, so central agent
  edits take effect for referencing nodes. Consequence: an agent edit changes the
  behavior of every referencing workflow; link/affected-node visibility is
  deferred with propagation (D6).
- **D8 — Destructive reset, no legacy.** The new agent-reference shape is the new
  standard. There is no compatibility path for embedded `AgentConfig`: a
  destructive migration resets workflow data (reseeding if no workflows remain).
  Existing embedded-agent definitions are not preserved.
- **D9 — Missing/invisible agent blocks.** If the referenced agent (or a
  referenced MCP/skill) is missing or not visible to the task user at execution,
  the task fails with a blocking, localized error and no silent fallback.

## Expected behavior

### Agent catalog

- Create/edit/delete an agent with: name (unique per owner scope), provider
  runtime (initially `opencode`), model, reasoning effort, instructions
  (Markdown), selected MCP servers, selected skills, and visibility
  (`personal`/`group`/`global` + `group_id` when group-scoped).
- Only entries the caller can see (own, their groups, global) are listed and
  resolvable; visibility checks mirror provider configurations.

### MCP server catalog

- Create/edit/delete an MCP server with: name, transport configuration
  (stdio: command/args/env; and/or http: url/headers) and visibility.
- Secret values (env/header values flagged secret) are stored encrypted and are
  never written to workflow definitions, Temporal arguments/history, logs, or
  list responses (only a "set/not set" marker is returned).

### Skill catalog

- Create/edit/delete a skill with: name, description, and Markdown instructions.
- Visibility as above.

### AI node in the editor

- The node's properties replace the embedded agent form with:
  - an **agent selector** (searchable list of visible agents);
  - a read-only **View instructions** action (Markdown preview);
  - editable **model** and **reasoning effort** (initialized from the agent,
    overridable);
  - editable **MCP servers** and **skills** multi-selection (initialized from the
    agent, add/remove allowed).
- Selecting a different agent re-initializes the overrides from the new agent.
- The node keeps its prompt template, inputs, outputs and per-output validation.

### Execution

- At execution, the effective configuration is resolved **live** (D7): the
  referenced agent is resolved under the task user's visibility and the node
  overrides are applied (model/reasoning override; MCP/skill add/remove). The
  effective MCP list is passed to `session/new` as `mcpServers`; skills are
  delivered by the runtime mechanism agreed in OQ3.
- Resolution failure (agent missing or no longer visible to the task user, or a
  referenced MCP/skill missing) is a blocking, localizable error surfaced on the
  task, consistent with existing provider-resolution failures (D9).

## Constraints and contracts

- Workflow schema is `v1`. Replacing the embedded `AgentConfig` with an agent
  reference + overrides is a definition-shape change and needs a compatible
  read/normalize path and a data migration (see OQ5).
- Secrets follow the provider-configuration pattern: encrypted at rest, resolved
  at execution, never snapshotted raw.
- All platform-owned user-facing text uses namespaced i18n keys with both `en`
  and `es` catalogs (nested JSON).

## Acceptance criteria

- **AC-AMS-01** Agents, MCP servers and skills can be created, edited, listed and
  deleted at personal/group/global scope by authorized roles; unauthorized scope
  creation is rejected.
- **AC-AMS-02** Listing and resolution only expose entries visible to the caller
  (own, their groups, global), by the provider-config precedence.
- **AC-AMS-03** An AI node stores an agent reference and node overrides; it does
  not store instructions.
- **AC-AMS-04** Selecting an agent initializes model, reasoning effort, MCP
  servers and skills from the agent; the author can override model/reasoning and
  add/remove MCPs/skills. The node stores only the overrides, not a frozen copy.
- **AC-AMS-05** A read-only "View instructions" renders the agent's instructions
  as Markdown.
- **AC-AMS-06** At execution the effective configuration is resolved live under
  the task user's visibility and injected into the runtime; MCP servers reach
  `session/new`, and skills are delivered per OQ3.
- **AC-AMS-07** MCP secret values never appear in workflow definitions, Temporal
  arguments/history, logs, or list responses.
- **AC-AMS-08** Missing/invisible agent or MCP at execution produces a blocking,
  localized error on the task, not a silent fallback.
- **AC-AMS-09** A destructive migration moves the platform to the agent-reference
  shape; no embedded `AgentConfig` compatibility remains and workflow data is
  reset (reseeding if none remain). This is an owner-approved destructive change.
- **AC-AMS-10** English and Spanish labels render on the three catalogs and the
  AI node properties.

## Open questions (implementation investigations)

- **OQ3 — Skill delivery mechanism.** How OpenCode receives skills: injected
  instruction text, files placed in the session workspace, or another runtime
  facility. Requires a small runtime investigation; the owner's model (name,
  description, Markdown instructions) is fixed.
- **OQ4 — MCP transport fields and secret marking.** Exact stdio/http field set
  and which values are secret. Reuse the provider-configuration secret handling.

## Resolved questions

- **OQ1 — Execution model.** Resolved: live agent + node overrides (D7).
- **OQ2 — Node list semantics.** Resolved by D7: the node stores explicit
  add/remove overrides; the effective MCP/skill list is the agent's live list
  with the node's additions and removals applied. Exact field names/shape are an
  architect decision.
- **OQ5 — Migration.** Resolved: destructive reset, no legacy (D8).
- **OQ6 — Missing/invisible at execution.** Resolved: blocking localized error
  (D9).

## Agreed decisions log

- 2026-10-04: Owner approved the increment scope (full catalogs), the
  node/agent relationship (inherit model + editable MCP/skill lists; instructions
  move to the agent with a Markdown "View instructions"; model editable),
  reasoning effort included now, and propagation deferred.
- 2026-10-04: Owner resolved the consequential questions: live agent + node
  overrides at execution (D7); destructive reset with no legacy compatibility
  (D8); blocking localized error when the referenced agent/MCP is missing or
  invisible (D9). OQ3 (skill delivery) and OQ4 (MCP transport fields) remain
  implementation investigations for the architect.

## Implementation Notes
- **Architecture Approval:** Implementation followed the architecture approved by the owner on 2026-10-04.
- **Accepted Residuals:**
  - **WP-R2:** End-to-end Temporal history/replay assertion for MCP/provider secrets not built (covered by AR3-05 + WP-10 + WP-24).
  - **WP-R3:** Partial coverage for central-edit/live-execution and long-name browser interaction.

