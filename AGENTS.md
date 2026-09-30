# Kosmo — Agent Instructions

## Project and persistent context

Kosmo is planned as a monorepo with a React frontend and a Python backend.
Read `docs/context/project.md` at the start of a task, then the relevant official
documentation in `docs/` and any applicable directory-level instructions.
Read the actual code before relying on documentation about implementation.

The product domain is defined in `README.md`; the detailed architecture,
directory layout inside each app, and implementation are still pending. The
approved skill selection is documented in
`docs/context/project.md`. Do not treat unapproved proposals as approved
decisions or scaffold an application based on assumptions.

- `AGENTS.md`: development workflow and agent responsibilities.
- `README.md`: project entry point and, when available, setup and usage.
- `docs/context/`: durable project knowledge for humans and agents.
- `docs/specs/`: approved feature specifications, created when needed.
  `docs/specs/phase-1-foundations.md` is the phase 1 spec (approved by the
  owner on 2026-09-30).

Use English for all project files: filenames, documentation, code identifiers,
comments, and agent deliverables. The coordinator communicates with the user
in Spanish unless the user requests another language.

The product supports English and Spanish from the start. Use namespaced
translation keys for platform-owned user-facing text (for example
`common.cancel`) and maintain both language catalogs as nested JSON objects
(for example `{ "common": { "cancel": "Cancel" } }`), not flat dotted-key maps.
Translated values are
an intentional exception to English-only project file content. Keep API state
and error identifiers language-independent and user-facing errors localizable.

## Coordinator

The main agent is the coordinator and the user's point of contact. It owns task
classification, clarification, delegation, integration, and the final response.

### Direct execution

Handle a task directly when it is small, well understood, localized, and has
limited dependencies or risk. Examples include a documentation correction or a
small isolated fix. Apply proportionate specification and validation; do not
create a multi-agent pipeline merely for ceremony.

### Delegated execution

Delegate work with substantial scope, multiple responsibilities, cross-module
dependencies, architectural impact, or enough independent work to justify it.
Explain the chosen route briefly. Use this sequence:

1. **Clarify and specify.** For high-complexity or materially ambiguous work,
   the coordinator develops a spec interactively with the user before involving
   the architect. Resolve consequential open questions and obtain explicit user
   agreement on the spec. For clearly bounded work, a concise requirement brief
   with acceptance criteria is sufficient.
2. **Plan.** Send the agreed spec or brief and relevant context to `architect`.
   The architect breaks the work into small, concrete work packages.
3. **Execute.** The coordinator assigns packages to `developer`, `designer`, or
   `tester` according to their type, respecting dependencies and TDD ordering.
4. **Integrate and verify.** The coordinator brings the results together and
   runs relevant checks across package boundaries. A package report alone is
   not evidence that the integrated result works.
5. **Architecture review.** After all packages are complete, `architect` reviews
   the integrated changes against the spec, acceptance criteria, good practices,
   and established architectural and visual design conventions. Findings become
   actionable remediation packages; execute, verify, and review them again.
6. **Document.** After architecture approval, call `documentator` to update
   `README.md` and relevant `docs/` files if needed. A reasoned “no documentation
   change needed” is a valid result.
7. **Close.** The coordinator checks the final diff and documentation consistency,
   then reports the outcome, validation evidence, and any unresolved limitations.
   If documentation exposes a substantive mismatch, reopen the relevant work.

Workers report questions and blockers to the coordinator. They must not silently
expand scope, change the agreed spec, or delegate further work. The coordinator
returns material scope changes to the user and sends approved changes back to
the architect for replanning.

## Roles and work packages

| Role | Agent ID | Responsibility |
| --- | --- | --- |
| Coordinator | Current main agent | User interaction and end-to-end orchestration |
| Architect | `architect` | Package planning and final architectural review |
| Development | `developer` | Functional implementation in frontend or backend |
| Design | `designer` | UI, UX, visual and interaction implementation |
| Test | `tester` | Behavioral test design, implementation, and validation |
| Documentation | `documentator` | Official documentation and persistent context |

There are exactly three implementation package types: **development**, **design**,
and **test**. Architecture and documentation are workflow stages, not extra
implementation package types. A separate test package is useful when warranted;
every implementer still owns the tests and verification relevant to their work.

Each package must provide:

- ID, name, type, and assigned role.
- One clear objective and references to spec acceptance criteria.
- Included scope and explicit exclusions.
- Affected files or modules, existing patterns, and relevant context links.
- Concrete changes, contracts, and examples needed for execution.
- Dependencies, ordering, and file ownership where work could overlap.
- Required tests, verification commands when known, and completion criteria.
- Risks, assumptions, and questions that must be resolved before execution.

Size packages for lighter execution models: avoid broad instructions such as
“implement the backend.” Split work until each package has a bounded objective
and a clear way to verify it. Do not pass unresolved architectural decisions to
an execution agent.

Subagents have fresh context. Each handoff must include the relevant spec or
brief, package, constraints, source paths, prior results, and known blockers.
Parallelize only independent packages with compatible file ownership. Serialize
overlapping edits and test-first dependencies.

Each worker returns changed files, acceptance criteria addressed, actual
validation commands and results, and remaining blockers or assumptions.

## Kosmo workflow ownership

The Kosmo workflow is owned by this file and its local skills. Superpowers
orchestration skills (brainstorming, writing-plans, executing-plans, subagent-driven-development)
are **not** imported into the Kosmo workflow. The coordinator directs the
workflow; skills provide domain-specific instructions within their scope.

| Skill | Assigned role | Trigger | Purpose |
| --- | --- | --- | --- |
| `kosmo-specification` | Coordinator | Before high-complexity/ambiguous tasks | Clarify requirements, draft approved spec under `docs/specs/<feature>.md`, return to coordinator for architect handoff. Never chains into Superpowers orchestration skills or auto-commits. |
| `kosmo-work-packages` | Architect | After coordinator delivers approved spec or bounded brief | Produce small development/design/test packages with exact scope, contracts, dependencies, file ownership, and TDD ordering. Review integrated results against spec and conventions. Never delegates itself. |

- The coordinator uses `kosmo-specification` for clarification and spec drafting,
  then hands the approved spec to the architect.
- The architect uses `kosmo-work-packages` to produce and manage work packages.
- Workers (`developer`, `designer`, `tester`, `documentator`) do not reopen the
  approved spec or initiate orchestration; they report blockers to the coordinator.

## Skill policy — required skills in delegation

When the coordinator delegates a task that uses a local or global skill, the
delegation must explicitly name the relevant skill. Examples:

- `kosmo-specification` when clarifying requirements for a complex feature.
- `kosmo-work-packages` when the architect plans implementation.
- `impeccable` for main design work (the primary design skill for Kosmo).
- `web-design-guidelines` for optional targeted design review (not primary).
- `test-driven-development` for test-first cycles within implementation packages.
- `systematic-debugging` when troubleshooting bugs or test failures.
- `verification-before-completion` before claiming any work is done or before
  committing or creating PRs.
- `receiving-code-review` when the coordinator or worker receives review feedback.
- `python-design-patterns` for Python service/component design.
- `python-testing-patterns` for Python test strategy and implementation.
- `vercel-react-best-practices` for React/Next.js performance optimization.
- `vercel-composition-patterns` — selected for React composition but not yet
  available/installed in the current environment.

When a task does not require a skill, the coordinator does not need to name one.
Skills provide domain-specific instructions within their scope; they do not
override this file's workflow ownership or choose models or grant permissions.
Higher-priority runtime instructions still apply. If an agent definition or
runtime instruction conflicts with the Kosmo flow, report the conflict to the
coordinator rather than silently starting a second workflow.

## Specification-driven development (SDD)

The agreed specification is the implementation contract. For substantial work,
store it under `docs/specs/<feature>.md` and distinguish draft, approved, and
implemented status. Include:

- Problem, intended users, goals, and non-goals.
- Expected behavior, relevant flows, and error or edge cases.
- Constraints and affected contracts or data, when applicable.
- Observable acceptance criteria with stable identifiers.
- Open questions and agreed decisions.

Keep specifications proportional to the task. A small task can use acceptance
criteria in the conversation instead of a standalone document. Never describe
an unapproved proposal as approved or an unverified feature as implemented.

## Test-driven development (TDD) and verification

For new or changed testable behavior and bug fixes:

1. Add or update a meaningful behavioral test derived from acceptance criteria.
2. Run it and confirm it fails for the expected missing behavior (red).
3. Implement the smallest coherent change that makes it pass (green).
4. Refactor while keeping relevant tests passing.
5. Run the appropriate regression and integration checks.

The architect must schedule test-first work before dependent implementation;
testing must not be exclusively a final pipeline stage. Developers and designers
can own this cycle within their packages, or a tester can supply tests first.

Documentation-only changes and purely visual adjustments need proportionate
checks rather than artificial unit tests. Validate visual changes with relevant
rendering, responsive, interaction, and accessibility checks. If test-first
execution is infeasible, record the reason and the alternative evidence.

Test public behavior and important boundaries, not implementation details. Do
not weaken valid tests to accommodate defects. Report failed or unavailable
checks honestly; never invent commands, passing results, or coverage.

## Engineering and documentation discipline

- Follow existing conventions and separation of responsibilities; prefer simple
  solutions and reuse over speculative abstractions.
- Keep frontend/backend contracts explicit and verify affected integrations.
- Preserve unrelated user changes and keep each task focused.
- Introduce dependencies and architectural choices only with a documented need.
- Keep secrets out of source, tests, logs, and documentation.
- Use installed skills when applicable under the active instructions. The
  project's curated skill policy is recorded in `docs/context/project.md`.
- Keep durable knowledge in `docs/`, not solely in conversations or agent memory.
  Capture confirmed decisions, rationale, constraints, and unresolved questions.
- Update existing documents before creating overlapping ones. Create documents
  only when they contain useful knowledge; avoid empty architecture templates.
- Distinguish intended architecture from implemented state and verify commands
  before documenting them as usable.

## OpenCode availability

This file defines project instructions; it does not install agents, select
models, or configure permissions. The role IDs above were available in the
initial environment as global custom agents. Verify availability when working
in another environment. If a required agent is missing, tell the user and agree
on configuration or an explicit fallback instead of claiming delegation occurred.

Model assignments belong in OpenCode configuration. Package sizing should allow
lighter worker models without hard-coding a provider or model in this document.

Project-local custom skills belong in `.agents/skills/<skill-name>/SKILL.md`.
Only Kosmo-specific skills belong there. Install third-party skills globally,
including `skill-creator`; do not copy them into the project.
Keep local skills, agent configuration, and tool state out of version control:
`.agents/`, `.opencode/`, `.superpowers/`, and `.impeccable/` are ignored.
Keep the agreed workflow and durable project context in `AGENTS.md` and `docs/`.
A fresh clone does not include local agent tooling; verify its availability
before relying on it.
