# Kosmo Product Vision

Status: Working requirements record, pending clarification of the open questions.
Updated: 2026-09-30.

This document captures the owner's intended product, not implemented behavior
or an approved implementation spec. Requirements below come from the owner;
proposals are labeled explicitly. Document the full vision before assigning
features to implementation phases. Development-agent orchestration in
`AGENTS.md` is separate from agents that users configure inside Kosmo.
This document is the source of record for product requirements; `README.md`
and `docs/context/project.md` summarize and link to it.

## 1. Product, access model, and roles

Kosmo lets solo users and teams visually create, validate, version, and execute
deterministic or AI-assisted workflows. Execution creates a task for a concrete
set of inputs, prompt, and configuration. Steps may run sequentially, in
parallel, or through bounded feedback loops.

Authentication is initially local, with users, groups, and roles. OIDC/OAuth
is a future possibility. Whether a "public" workflow means anonymous or
any-authenticated-user access is still open.

### Roles

Five roles control capabilities:

| Role | Capabilities |
| --- | --- |
| Viewer | See the tasks they have been granted access to, individually or via groups. |
| Runner | Everything a viewer can do, plus execute tasks. |
| Builder | CRUD on workflows, agents, MCP servers, skills, and extensions, for themselves or their groups; view tasks. |
| Group Manager | Configure team-scoped platform settings; exact permissions remain to be defined. Capacity limits are global only. |
| Admin | Full control over the platform. |

Builders and admins can configure an MCP server's visibility as **personal**
(only themselves), **group**, or **a set of groups**. A builder can only grant
access to themselves or to groups they belong to. Global platform-wide
visibility is admin-only.

Open design problem: the same workflow may be shared by several teams that
need different integration configurations (for example one Jira workflow whose
MCP instance differs per team because each team accesses different projects).
How per-team resolution works alongside shared definitions is still open.

## 2. Platform configuration and extensions

Provide configuration management separate from workflow authoring and execution
for agents, MCP servers, skills, integration instances, extensions, and
repository access. All of this is administered inside the platform's
configuration section; workflow nodes only reference it (for example, an AI
node selects an agent rather than embedding its configuration).

An **extension** stores the integration configuration for a tool so that
scripts and agents can use it without duplicating configuration. Depending on
the extension, it may also contribute an MCP server and/or install useful
skills; it may also contribute none of those and exist purely as configuration.
An extension is code that supports creating multiple **instances**. Instance
visibility levels are personal (user), group/team, or global (admins only).
An Atlassian extension could provide Confluence and Jira access; multiple
instances hold different connection settings.

Configured values must be usable by scripts, for example
`integration1.config.url`. Exact binding names, object APIs, secret handling,
instance permissions, and extension packaging are open. The extension
mechanism and extensible workflow node types are related but must not be
assumed to be the same plugin interface.

## 3. Agents, provider runtimes, and node overrides

An agent definition groups specialization instructions, a model and reasoning
effort, MCP servers, and skills. Distinguish a model provider from an agent
runtime: initial runtime targets are OpenCode and Claude through ACP, and
Codex through its app server. All adapters expose a common Kosmo model for
session commands, events, responses, and human input. They do more than parse
output. The owner asserts the three runtimes support the required
interactions; verify per runtime/version at implementation.

Every AI node selects an agent. It inherits the agent's model by default and
its MCP/skill lists. The workflow author may add or remove MCP servers and
skills for that node. Whether the model is editable or locked is not yet
specified; the propagation rule below applies to MCPs, skills, **and agent
instructions**.

When an agent's MCP/skill/instruction configuration changes:

1. Display the affected workflows and nodes.
2. Identify nodes whose configuration differs from the agent defaults.
3. Apply changes automatically to nodes with unmodified configuration.
4. For modified nodes, offer replacing their overrides or retaining them.

Workflow nodes reference agents and instances rather than embedding their
configuration. Queued and running tasks retain their selected workflow version
when the workflow is updated, and published versions retain their definition.
At task submission, resolve and preserve the effective execution configuration
alongside the selected workflow/version. Nodes continue to reference resources
in the editor; later changes to those resources must not silently alter a task's
resolved configuration. How shared agent changes produce draft edits or new
publications still needs agreement.

MCP configuration can contain credentials, and task prompts can contain sensitive
information. Protect both when persisting and exposing task data. Do not copy
raw secrets into ordinary configuration snapshots, artifact manifests, audit
values, or logs. A proposed implementation is to snapshot non-secret settings
and protected credential references, with credential rotation, revocation,
encryption, and authorized runtime retrieval defined in the architecture.
Separate inheritance per MCP/skill list versus one combined override flag also
needs definition.

## 4. Workflows: versions, publication, and graph semantics

### Drafts, publication, and task version binding

Confirmed by the owner:

- Workflow authoring has `draft` and `published` states.
- A draft can be saved in any state, including with validation errors.
  However, a draft can only be **tested or published** when workflow validation
  reports no errors. Rejected test/publication attempts show the validation
  errors. Validate on the server as well as in the editor; detailed validation
  rules will be specified separately.
- Saving a draft does not increment the published workflow version.
- Each draft records the published version it is based on. Multiple users can
  maintain independent drafts of the same workflow at the same time, based on
  the same or different versions. Saving one user's draft does not replace
  another user's draft.
- Publishing changes automatically creates a new workflow version; version
  numbering is not a manual authoring step.
- Activating a published version is a manual action. The save/publication flow
  offers an explicit option to activate the version being published;
  publishing alone leaves the current active version unchanged.
- At task creation, the user selects a workflow. Its active version is
  selected by default, but the user can choose a different published version
  before submitting.
- A submitted task binds to a particular workflow and version. Queued and
  running tasks retain that version even if a newer one is published.
  Changing the active version also leaves already-submitted tasks unchanged.
- Users can explicitly select a valid saved draft for a test execution
  without publishing or activating it. Clearly identify draft selections and
  resulting tasks as `Draft` so they cannot be mistaken for published-version
  executions. Bind the task to the selected draft's saved revision and
  preserve that definition for execution; later draft edits must not alter a
  queued or running test task. This does not increment the published workflow
  version. The active published version remains the default for normal task
  creation.
- Saving must be atomic. Publication must not expose a partial definition or
  an inconsistent version assignment.
- When saving a draft, its base version is recorded. On publication, if that
  base version is older than the currently active version, the platform
  shows a message stating that the workflow being published is based on a
  version older than the active one and requires confirmation. This prevents
  unknowingly building on superseded work while still allowing publication
  from an older base.
- If another user published the workflow less than five minutes before the
  save/publication attempt, require explicit confirmation before overwriting
  the current authoring state with the user's changes. Use the server's time
  and recorded publishing user for this check.

"Overwrite" must preserve old published versions needed by existing tasks:
the resulting publication is a new version, not a mutation of an old one.
Exactly how the five-minute check applies to draft saves versus publication
is still to be clarified.

**Approved concurrency mechanism:** compare the editor's expected revision
with the current persisted revision using an atomic transaction or conditional
write. This protection also applies outside the five-minute window and to
concurrent edits of the same draft, including multiple tabs owned by one user.

Keep three identities distinct: the draft itself and its internal revision,
the published version on which it is based, and the current publication
revision of the workflow. Draft saves check the revision of that draft, not
another user's draft. A later publication does not prevent users from
retaining and editing drafts based on older versions.

When publishing, also check the publication state against which the user is
publishing. A stale base must be surfaced rather than silently replacing newer
published changes. Bind overwrite confirmation to the current publication
revision shown to the user and to the draft revision being published; if
either changes before confirmation completes, recheck instead of overwriting
unseen changes. Keep internal draft revisions separate from published version
numbers.

**Confirmed:** apply the same stale-base warning and
confirmation when *activating* a version based on one older than the current
active version. Activation, not publication, is what changes default launches.

Still open: whether a user can hold multiple drafts for one workflow, initial
version number/format, publishing unchanged content, behavior before any
version has been activated, how a user resolves a stale-base conflict
(refresh, reconcile changes, or explicitly publish their draft over the
acknowledged current publication), and how task creation handles a change of
active version while the creation form is open.

### Graph structure and execution semantics

Every workflow has exactly one **start node** and one **end node**. The start
node defines a dynamic input form for launching: for example a prompt text
area, a URL, a number, or other field types defined per workflow. Nodes have
their inputs on the left side and outputs on the right side.

An edge is both a data path and an execution dependency: a node runs when all
of its required inputs are available. Artifacts from other nodes feed inputs;
a node's outputs become artifacts for connected nodes.

- **Decision branches:** a decision node routes execution down one branch
  only. When branches reconverge, a join must not wait for a branch that a
  decision discarded: the join runs with the branch that arrived. The join
  must know which incoming edges were discarded versus expected.
- **Parallel convergence:** when several nodes run in parallel and converge
  on one node, that node waits for all of them. What happens when one parallel
  branch fails is still open (fail the join, continue with partial inputs, or
  configurable per join).
- **Dynamic fan-out:** the owner wants to model a pattern where an agent
  generates a plan, the plan becomes work packages, and multiple agents launch
  to cover those packages. The number of agents depends on the plan, which
  depends on runtime inputs, so it cannot be drawn statically in the workflow.
  The same mechanism must serve the system context workflow's variable number
  of documentation workers. A proposed construct is described below; its design
  is not yet approved.
- **Workflow nodes** invoke other user-defined or system workflows and require
  input/output mapping, a child-version resolution policy, context propagation,
  child stopping, and recursion bounds.

Initial node types:

| Type | Intended responsibility |
| --- | --- |
| Script | Execute Python in a sandbox with injected artifacts and selected integration/repository bindings. |
| HTTP | Make HTTP requests; detailed request, credential, and output settings are open. |
| AI | Execute a selected agent with node-specific resources and a task prompt. |
| Decision | Select a route using decision logic. Future model support ("Jev") is a future decision-aid consideration. |
| Workflow | Invoke an existing user-defined workflow or a system workflow. |

### Dynamic child workflows

Status: Runtime-generated workflows with inter-package dependencies and artifact
bindings are confirmed requirements. The execution contract below is a proposal
for architecture, not an implemented feature or approved new node type.

The owner confirmed this example flow: task prompt -> context acquisition ->
planning agent -> work-package generation agent -> a runtime-dependent number
of workers. Package count and responsibilities vary by task. Context refresh
also needs a variable number of workers based on the application.

The earlier independent-item For each / Map proposal was rejected as insufficient.
Dependency-aware execution is required from the outset: a DAST work package may
wait for specific SAST packages and consume their findings artifacts. Do not
replace this with an all-parallel executor or require manually drawn batches.

The owner rejected requiring the generating agent to author full node
configuration, agent assignments, output file definitions, and validation rules.
When a Workflow node selects **use a definition**, the builder configures its
execution settings as for an AI node: agent, model, MCP servers, skills, and
artifact validation. Generated steps use that configuration rather than declaring
their own agents or resource policies. A heterogeneous role-to-agent mapping is
not part of this simplified requirement.

When creating each agent execution, provide the complete configured output
contract: expected artifacts, their purpose, formats/schemas, validation rules,
and the execution-specific output locations/conventions. The agent must know
what to generate and how to satisfy validation. Kosmo supplies this information;
the work-package generator does not redefine it per package.

**Confirmed requirement:** a generated package explicitly declares whether it
consumes another package's outputs. Waiting for a predecessor must not implicitly
import all its artifacts. For example, a DAST package can consume the findings
from a specific SAST package while merely waiting for other prerequisites.

**Confirmed minimal generated artifact:** packages contain `id`, `instructions`,
`depends_on` for ordering, and `inputs_from` listing source package IDs whose
validated output artifacts are imported. An empty/omitted `inputs_from` imports
no predecessor outputs. Each `inputs_from` source also implies a scheduling
dependency, so the generator need not repeat it in `depends_on`. Validate the
union of these dependency edges and reject unknown references. This initial
contract selects all exported outputs of a named package; selection of individual
named artifacts is a possible later refinement, not a requirement for generating
each package. Workflow/root inputs are a separate binding from predecessor outputs.

IDs are local to the generated definition and serve graph linkage, not access
grants. Kosmo expands packages using the Workflow node's configured execution/
output contract and derives internal execution IDs itself. Label imported artifacts
with their source package, artifact name, and iteration. The generator does not
define filesystem paths or validation schemas.
Distinct executions keep separate artifact namespaces even with the same output
contract, so repeated filenames do not collide.

### Workflow output collection

Status: Confirmed direction for variable-size workflow outputs.

Expose a stable `artifacts` collection output from an invoked dynamic workflow,
with zero or more artifact references and a machine-readable manifest. The
parent graph connects to this collection rather than requiring one statically
declared port per generated file. A reusable collection contract can also be
supported by predefined workflows alongside their named outputs.

Each entry identifies the artifact, source child-workflow execution, package/node,
logical output name, iteration, attempt, and media type. Store content outside the
manifest; Kosmo resolves authorized references to script bindings or agent mounts.
Mount paths are execution-specific and generated by Kosmo, not the planner.
Use distinct artifact identities/namespaces to avoid collisions between outputs
with the same filename. Shared notes and credentials are not automatically copied
into this result collection.

Collect validated exported artifacts from successful child
node executions, including intermediate results rather than terminal nodes only.
Publish the final collection when the child workflow completes successfully;
retained failed-attempt diagnostics are not automatically normal outputs.
Preserve successful artifacts from earlier loop iterations with their provenance,
but give the latest validated output priority for each logical artifact from the
same producing node and invocation. This priority is not a global "last file wins"
rule across different producers. Consumers can inspect history explicitly; earlier
iterations must not silently override the latest result. Failed candidates do
not replace valid outputs or make a failed execution successful.
Input consumers must be collection-aware and explicitly handle empty collections.
Per-artifact validation still applies; a valid manifest alone is not sufficient.

If any child node reaches a failed outcome, the invoking Workflow node is failed,
whether it invokes a predefined, system, or dynamic workflow. Propagate that
failure through enclosing Workflow nodes; partial successful outputs do not make
the invocation successful and are not published as its normal successful output.
Preserve available results for diagnosis according to task retention rules.
An AI validation failure that still permits correction is not yet a final node
failure; after its third failed completion validation, failure propagates.

Filtering rules, retention details, and aggregate completion validation remain
to be specified. Persist committed output references
atomically at successful completion so retries do not silently duplicate entries.

A Workflow invocation with a generated-definition input is the preferred
proposal over an unrelated second execution engine. Reuse graph validation,
scheduling, node completion validation, iteration tracking, and lifecycle
handling from authored workflows. The generated definition is execution-owned:
validate and persist it before launching children, and preserve it across retries
instead of silently asking the planner to generate a different graph. Whether
to promote it into a reusable published workflow is a separate future choice.

Schedule only eligible nodes whose dependencies and required inputs are
satisfied, subject to phase/branch semantics and available global agent capacity.
Unrelated eligible work can run in parallel. Child executions belong to the
root task and do not consume extra main-task slots; their live agents do consume
agent slots. Dynamic context-documentation refresh uses this same mechanism.

Example: `sast_auth` produces findings; `prepare_environment` obtains required
DAST configuration. `dast_verify_auth` waits for both and consumes the findings
plus authorized environment data. An unrelated SAST package may continue in
parallel; DAST need not wait for every SAST package unless the graph says so.

**Shared task notes:** use the root task's shared note store across all phases,
authored steps, and generated/nested workflow executions belonging to that task.
All AI agents in that execution tree can consult the complete notes, including
real sensitive values required for their work. Neither the builder nor a
producing agent selects recipient step IDs. The earlier proposal to scope notes
to individual Workflow nodes is superseded by this simpler task-wide policy.

For example, an answer collected by the security workflow's planning agent is
available to the DAST workers created later inside its generated workflow.
The platform establishes root-task identity from the authenticated execution;
agents cannot select an unrelated task's notes. Independent task launches do
not share notes merely because they use the same workflow definition.

Validation before execution checks graph references, artifact contracts, permitted
agent/resource bindings, and the existing bounded-loop/phase rules. This requirement
does not restrict every generated graph to a DAG; any supported cycles need explicit
iteration semantics and bounds. Runtime graph mutation after launch, handling of
already-running sibling nodes after a failure, and generated-node presentation
remain architecture decisions. Failure of a child fails its Workflow invocation.

### Loops

Feedback edges are allowed, for example developer -> tester -> developer: A
can receive its initial input from a node before the loop, and B can produce
an artifact that A receives again and processes as it processed the first
artifact, since each iteration runs in a completely new container with no
context from the previous one. When a cycle is detected, the workflow
configuration must set a maximum retry/iteration limit; unbounded cycles are
rejected. Graph loop iterations, transient execution retries, and a user's
retry of a failed task are distinct concepts with separate semantics.

Generated artifacts carry a metadata file indicating the iteration in which
they were produced; persistence must account for it. Whether artifacts are
stored in the database or on disk is still open. The precise iteration counter
scope, nested-loop rules, exit conditions, and limit-exhaustion result remain
open.

## 5. Node execution contract

A node does not simply "finish": it **requests termination**, and validation
runs at that point.

- A validator receives the node's declared outputs and enforces the three
  validation levels (format, schema, business rules) and the presence of all
  expected artifacts. Any rule failure or missing artifact is an error, and
  the validator records which artifact, which location, and why.
- **Deterministic nodes:** a validation failure marks the node as failed.
- **AI nodes:** when the agent requests termination, the node keeps its
  container alive, the platform coordinates validation outside that container
  (user Python validation code runs in a sandbox), and any problems are
  reported back to the agent through the adapter layer (ACP or Codex app
  server), so the agent can correct and request termination again.
- **Correction loop limit:** at most three validation cycles. Flow: the agent
  requests termination, the validator fails it and reports which artifact,
  which location, and why; the agent corrects and requests termination again;
  this repeats, and when the validator detects the third failed validation,
  the node is marked as failed.
- The platform provides AI agents an MCP exposing this validator so they can
  check their generated files before finishing.
- User Python code — script nodes and Python business-rule validators — runs
  in a **sandbox** (Docker or a lighter environment if sufficient), with the
  requirement to prevent access to host resources outside its assigned scope.
  This is an isolation requirement, not a verified absolute guarantee. Code
  authored by users with the appropriate authoring permissions must not execute
  inside the API or orchestration process. Concrete sandbox technology and
  restrictions are decided during architecture and implementation.

## 6. Artifacts and validation

### User-facing execution errors

The platform must show actionable error information rather than generic failure
messages or raw stack traces. Each error includes at least:

- A short, understandable title or primary cause.
- Detail explaining what happened, including relevant validation history.

For example, after three failed completion validations:

- **Title:** "Artifact validation failed after 3 attempts."
- **Detail:** list each attempt and its errors, identifying the artifact,
  location/field, and reason. The first attempt might miss a required file,
  the second violate its schema, and the third fail a business rule.

Keep the actual attempt history; do not replace it with only the last error.
When a child failure propagates to a Workflow node, preserve its underlying
cause and identify the failing step/invocation rather than showing only
"Workflow failed." Translate provider, infrastructure, and script failures into
the same title/detail pattern where applicable, using available evidence rather
than inventing causes. Detailed errors must not expose credentials or sensitive
prompt/note content; authorized runtime access to full notes remains separate.
Machine-readable error codes and the exact response schema are architecture work.

User-facing platform error titles and details follow the localization contract
below. Keep stable error/message identifiers and parameters separate from
rendered language so that stored errors are not restricted to the language of
the user who launched a task. Translation does not change artifact names,
field paths, or other diagnostic identifiers.

### Artifact contracts

Nodes declare output artifacts and consume output artifacts from other nodes.
The owner does not want a fixed product-level cap on input artifact count;
runtime capacity and storage limits still need definition.

Artifact validation has three levels:

1. **File format:** JSON, YAML, Markdown, plain text, and other supported formats.
2. **Structural/domain representation rules:** applicable JSON/YAML/XML schemas,
   field formats, units, and related constraints.
3. **Business rules:** Python code with injected input artifacts and the
   candidate output artifact, executed in the sandbox. Example: an output
   `file` value must occur in input artifact X's `inputFiles` field.

Exact schema dialects, validation execution order, and error reporting format
follow from the node execution contract above.

Script nodes receive input artifacts as variables. AI nodes receive mounted
artifact files and a metadata manifest listing the imported artifacts, their
origin, their mount paths, and their iteration. A system prompt directs the
agent to read its principal instructions and artifact metadata and supplies
the task prompt.

**Out of scope (2026-09-30):** automatic recording, interception, and recovery
of external side effects. Nodes and agents may create, modify, or delete
entities in external systems (a Jira ticket, a GitLab MR comment) without
platform-level operation journals, gateways, idempotency guarantees, or
reconciliation. If such an action fails or repeats, it is resolved outside
the platform. These earlier sketches are not requirements or approved designs.

## 7. Repository integrations and applications

### Platform-level access

Configure GitHub and GitLab access using SSH keys or personal access tokens
(PATs). Verify the configured credential works. Separate credential validity
from permission to access a particular repository or operation.

### Node-level access

Script and AI nodes can request one or more repositories and a specific PR/MR
where applicable. Public repositories can be used; private ones require an
accessible configured integration instance. A node may explicitly request all
repositories available through a selected integration instead of enumerating
individual repositories.

Scripts receive a binding with operations such as cloning, reading files, and
searching. AI agents receive an MCP exposing the same operations. Both paths
must enforce the same repository scope: a credential that can access five
repositories does not authorize a node configured for only one to use the
other four. Out-of-scope operations return a permission error.

**Proposed enforcement:** use one authorization-aware repository service behind
both the Python binding and MCP tools. Do not hand a node an unrestricted PAT
or SSH key for the underlying account: arbitrary script/agent code could bypass
the scoped methods and access other repositories. Container, network, Git
credential, and service policies must support the same boundary. Normal
integration values such as `config.url` can remain directly accessible while
credential access is designed separately.

The all-repositories mode is an explicit scope choice, not the default. Whether
it includes repositories added to the integration after task submission is open.
Allowed mutations, branch/ref rules, PR/MR API capabilities, and submodule access
also need specification. SSH Git access alone must not be assumed to provide
authenticated GitHub/GitLab API access to PR/MR metadata.

### Applications

An application is a logical grouping of repositories and has at least one.
A workflow declares whether an application/repository assignment at task
creation is required, optional, or forbidden. Whether application and
repository requirements can be configured independently, and how many
repositories may be selected per task, remain open.

## 8. Task lifecycle, capacity, and human interaction

### States

| State | Meaning and supported actions |
| --- | --- |
| Queued / pending | A submitted main task is waiting for global task capacity; the final state name remains open. Node-level agent-capacity waits use allocating. |
| Running | Capacity was granted and workflow nodes execute. |
| Waiting for input | An AI node needs human input; a response allows progress. |
| Stopping | A stop was requested; active execution finishes naturally, except that an agent waiting for human input is stopped without waiting for a response. |
| Stopped | Execution has stopped; the user may resume or delete the task. |
| Failed | Execution failed before successful completion; the user may retry or delete. |
| Success | Execution finished without errors; the user may delete or clone. |

Cloning copies the task's configuration, prompt, and initial values into an
unsubmitted configuration. It does not submit or execute automatically; naming
and persistence of that unsubmitted state remain open.

### Stop, resume, and retry

Confirmed by the owner:

- **Stop** moves the task to `stopping` and then **waits for the currently
  active node to finish its execution naturally** — whether it is a 200 ms
  script or a one-hour AI agent. Normal stop does not kill the node; that graceful
  wait is the purpose of the `stopping` state. When the active node
  completes, the task transitions to `stopped`, with completed nodes and
  their artifacts retained.
- **Human-wait exception:** if the active node is in `waiting for input`, stop
  does not wait for an answer or natural completion. Stop its container and
  discard that runtime's pending wait state. On resume, relaunch this unfinished
  node in a new container; do not restore the old session or pending request.
- **Resume** restarts the task from the point where it was stopped — the
  next pending node after a graceful completion, or the unfinished node stopped
  during human input — rather than from scratch.
  A resumed node runs in a fresh container with no previous session context.
- **Retry** (from `failed`) behaves like resume: it starts from the last
  available node state and relaunches the node that failed.

Each task has one checkpoint writer consuming a queue of node completion records
sequentially. Nodes request recording their completion instead of writing the
file themselves. The writer updates the file atomically after each queued record.
Each task has a checkpoint file updated atomically to record completed node
executions and their validated, persisted artifacts. Retry, recovery, and resume
retain these completions rather than repeating successful work. Distinguish child
invocations, nodes, iterations, and attempts. Keep the checkpoint outside disposable
agent containers. Durable queue replay, completion deduplication, writer replacement,
and reconciliation with Temporal's durable history are architecture responsibilities.

Crash recovery must preserve completed progress, but unlike graceful stopping,
a power loss or platform crash may interrupt a node before completion. Recovery
is based on the checkpoint; external actions performed before a crash are outside
the platform's recovery scope and are not recorded or reconciled automatically.

### Capacity and admission

- Admin-configurable global limits only: maximum concurrently active main
  tasks and maximum concurrently active agents. Per-team capacity limits are
  removed from the requirements; no team attribution is needed for scheduling.
- A main task is a top-level launch requested by a user. Child workflows and
  internal platform work belonging to that execution do not consume additional
  main-task slots; their live agent containers still consume global agent slots.
- Task artifacts are viewable and downloadable from the platform, subject to
  the viewer's task access permissions.
- Future periodic/scheduled top-level tasks count as user-originated main tasks
  for capacity even though the platform submits them automatically. Scheduling
  itself is future scope, not an implemented or MVP feature.
- Main tasks without capacity remain queued/pending. An agent node without
  agent capacity remains `allocating`. Admission uses FIFO; exact queue handling
  is defined in the scheduler contract.
- A node that requires an agent container counts against capacity while its
  container is alive; when the container dies, the capacity is freed.
- Script containers get a timeout: when it expires, the container is killed
  and the node is marked failed.

### Human interaction

Any user with access to the task can respond to an agent's input request.
By default there is no expiry: the task remains active in `waiting for input`
and its container keeps occupying an allocation unit. Users can also message
agent sessions on their own initiative. Both paths normalize through the
provider adapter layer; permission approvals and information questions may
have different protocol representations and must not be conflated.

The owner identified a persistence requirement: information supplied by a user
must remain usable after the agent container is destroyed and by subsequent
steps. Discarding a stopped node's pending wait does not imply discarding
information already supplied by the user.

Persisting answers or emitting an artifact only along existing graph edges is
not sufficient on its own. For example, an environment-check agent may obtain
missing DAST configuration from the user, but other dynamically launched DAST
workers must be able to use that information too. The owner requires task-owned
shared information available to all AI steps within the same root task, including
earlier steps on later loop iterations and future steps. Access must survive
the originating container. Authorized consumers must receive usable sensitive
values when needed, not redacted substitutes for required credentials.

**Confirmed simplified direction: task-wide shared notes.** Notes are shared
across all AI nodes in the root task, including its system, nested, and generated
workflow invocations. They are not global platform notes or scoped to just one
child workflow. Fine-grained per-step read permissions are not required.

- Store named text or structured entries outside runtime containers, associated
  with the task, author/source, producing node/iteration, and a revision.
- Do not require recipient IDs, phase selectors, or generated-step access lists.
  Kosmo automatically binds every agent execution to its root task's note store.
  Define write/update conflict behavior separately; task-wide reading does not
  imply that agents may silently overwrite concurrent contributions.
- Persist a user's shared answer before delivering it to the requesting agent.
  Correlate it with the input request while keeping the shared entry independent
  of that runtime session. Obsolete pending requests remain distinct from
  information already received.
- Expose notes through platform MCP tools; tell every agent instance how to
  consult and contribute task notes. Fetch current entries when needed rather
  than relying only on a startup manifest that becomes stale during execution.
  Equivalent script access remains a separate interface detail.
- Store sensitive fields through protected secret storage and resolve their real
  values for the task's authorized agents. Protect storage and UI access, and
  redact sensitive values in logs and audit records. Agent note retrieval returns
  the complete content, without masking or omitting required credential fields.
  Do not promise secrecy from a model if the model itself receives the value.
- Record revisions consumed by node attempts for traceability; define what
  happens when an entry changes while consumers are running. Newly executed
  iterations can read the permitted shared information, but completed executions
  are not retroactively changed or automatically rerun.
- Keep the existing artifact contract for declared node results. Shared notes
  supplement it; they do not make required input dependencies optional. If a
  consumer requires an entry that does not yet exist, an explicit prerequisite
  or wait condition is needed. Read permission alone does not imply readiness.

The API shape, required-entry declarations, retention, and
secret delivery mechanism remain architecture decisions. This task-scoped data
is distinct from general/workflow/application knowledge context and CRUD audit.

Task-level state aggregation for parallel branches still needs definition: a
branch waiting for input may coexist with running branches. Deletion removes
the task and everything associated with it; whether audit records about the
task survive deletion is open.

## 9. Isolation, sandboxing, and audit

AI agents run inside Docker containers with only explicitly assigned host
resources mounted. The goal is to prevent agent actions from affecting host
resources outside that scope. Container configuration and mount permissions
must enforce that boundary; Docker alone is not an absolute isolation
guarantee. User Python scripts and validators also run in sandboxes (see the
node execution contract).

Task runtime activity is not audited: execution is automatic and managed by
the platform. The audit log records **user-initiated actions**: creating,
stopping, deleting, or retrying a task; creating a workflow or publishing a
new version; changing agents, MCPs, skills, extensions, integrations, or
configuration values; and similar CRUD operations.

**Proposed implementation:** a shared CRUD service wrapper that registers
each mutation — action, user, entity, and, for create/edit, the changed
value — with PII and sensitive-value handling to be defined. Retention,
visibility, and deletion rules for the log still need definition; runtime
execution history is distinct from CRUD auditing.

## Localization

Kosmo supports localization from the start, with English (`en`) and Spanish
(`es`) as its initial languages. Use stable namespaced translation keys and
per-language values, rather than hard-coded user-facing platform strings.
Catalogs use nested JSON objects, not literal dotted keys. The lookup key
`common.cancel` resolves to `Cancel` in English and `Cancelar` in Spanish:

```json
{
  "common": {
    "cancel": "Cancel"
  }
}
```

The Spanish catalog has the same structure with `"cancel": "Cancelar"`.
Repository documentation, code identifiers, and comments remain
in English as required by `AGENTS.md`; product language support is independent.

Apply this contract to platform-owned labels, buttons, navigation, forms,
validation messages, status labels, notifications, and user-facing error titles
and explanations. Parameterize dynamic values rather than concatenating
translated fragments. Preserve machine-readable state and error identifiers
independently of the displayed language.

User-authored prompts, notes, workflow names, artifacts, and agent/provider
output retain their original content; automatic translation of that content
is not part of this requirement. Platform explanations around provider errors
can be localized while preserving the original diagnostic where relevant.

Both catalogs must cover the supported platform messages. Language selection,
default/fallback behavior, preference persistence, locale-sensitive formatting,
and the concrete i18n library remain architecture decisions. Build localization
into the first UI/API error contracts rather than adding it as a later phase.

## 10. Visual editor

### Phases and steps

The workflow editor supports grouping several nodes inside a visual container
called a **phase**, to simplify large graphs. The nodes within a phase are its
**steps**. This introduces the authoring vocabulary workflow -> phases -> steps;
a step is an existing workflow node, not a new executor type.

A phase container is distinct from an execution Docker container and from a
Workflow node that invokes another workflow. Phases have both visual and
execution semantics: phases execute sequentially, and a phase must complete
before the next phase begins. Steps within a phase need not be sequential;
their graph dependencies, branches, and parallelism govern execution.

The owner clarified that a phase-level feedback loop re-executes the target
phase as iteration X. Preserve previous phase/step execution records and
iteration-specific outputs rather than overwriting them. This is an explicit
return to an earlier phase; ordinary forward progression still observes phase
completion barriers. Workflow loop limits apply; exact accounting remains open.
Phase-level loops are not restricted to edges within one phase.

Proposed editor behavior, pending agreement: named phases that can collapse or
expand while preserving visibility of connections crossing their boundaries.
Whether all steps must belong to a phase, nested phases are allowed, or phases
have runtime status/actions will be defined with the editor and graph contracts.

**Confirmed:** make explicit phase authoring optional.
Simple workflows can use a flat graph, represented internally as one implicit
phase; authors add explicit sequential phases when useful. Define conversion
and ungrouped-step handling before allowing mixed layouts with ambiguous order.

### Layout

The editor has three vertical areas:

- Left: searchable node-type catalog, icons, and short descriptions; always
  visible.
- Center: the largest area, a React Flow canvas for adding and connecting
  nodes; always visible.
- Right: selected-node properties. The panel appears only when a node is
  selected. Clicking empty canvas closes it; clicking another node while it
  is open replaces its content with the new node's properties.

## 11. Context system

Context is information that helps an agent perform its task. Supported sources
include plain text, public URLs, uploaded files or directories, and private
URLs. A private URL references an extension instance or MCP server that allows
authorized access. Examples include official technology documentation,
application documentation, and a team's Confluence pages.

Context has three scopes:

- **General:** always applicable, intentionally small.
- **Workflow:** applies when that workflow runs.
- **Application:** applies when running against a selected application.

"Applicable" defines the candidate information; the context workflow below
selects what is relevant to the current task. Storage, provenance, conflicting
sources, access control, and refresh policies are still to be designed.

### System workflow: context acquisition and refresh

All reasoning steps use AI agents:

1. Receive the task context. The platform runs a query that gathers the
   registered context at the general, calling-workflow, and application
   levels, mounts it into the agent's container, and produces a metadata file
   pointing to the mounted files and their locations.
2. A context agent receives that metadata listing and assesses whether the
   context is up to date with the code.
3. For a selected application, if the relevant documentation is current, it
   produces an artifact listing the context to review and stating that no
   refresh is needed.
4. If documentation is stale, launch multiple agents in parallel to inspect
   code and update application documentation. Coverage can include
   technologies, architecture, general structure, and specific application
   areas.
5. After inspection/refresh, always run a final selection agent. It considers
   the mounted context listing and the user's prompt, then selects the
   context relevant to the task.

The platform explicitly scopes what is gathered via its registered context —
it is not unrestricted "look at everything" retrieval.

### Freshness model

Documentation freshness is tracked per repository, not per revision. The
default branch is the "standard version" of the documentation. Analysis of a
non-default branch produces a section for that branch with its
particularities, rather than replacing the standard version.

Define write destinations, parallel edit coordination, permissions, failure
handling, and the final artifact format. Do not assume the workflow can
rewrite third-party sources or all manually maintained documents. Application
auto-generated documentation needs an explicit ownership and publication
policy, including how two concurrent tasks analyzing different branches of
the same application coordinate their updates.

## 12. Reference workflow

The default, first-class workflow is **repository security analysis**. It can
target a whole repository, an MR, or a specific part (for example
authentication), and perform SAST, DAST, or both depending on the prompt. Use
it as the end-to-end acceptance scenario for phasing and engine validation.

The initial task prompt should supply DAST target/environment information.
If it is missing, an earlier AI step asks the user for it before analysis.
The answer must survive container cleanup and be available to later steps,
as described under human interaction. Automatically building and launching
the target application is not an agreed requirement.

## 13. Implementation phasing — proposal, not approved scope

The overall MVP includes deterministic and AI-assisted execution. Intermediate
milestones do not redefine the MVP as deterministic-only. Not every feature in
this vision has been assigned to the MVP yet.

1. **Foundations and execution proof:** settle version snapshots, resource
   scopes, task transitions, and runtime choice; prove one isolated execution
   and one agent interaction, including interruption/recovery.
2. **First usable workflow path:** basic editor, versioning, validation,
   deterministic + AI nodes, artifact exchange, local access control, and CRUD
   audit. Validate adapters for all three initial agent runtimes.
3. **Integration and lifecycle depth:** configurable integrations, repository
   scope parity for scripts/MCP, application bindings, overrides, full
   stop/resume/retry/clone behavior, bounded cycles, and nested workflows.
4. **Context workflows:** context management, freshness checks, parallel
   documentation updates, and task-specific context selection.

Break these into smaller approved specs after clarifying the shared contracts.
Security boundaries (sandboxing, scopes, audit) and capacity admission should
be built with the relevant features, not added after unrestricted access has
already shipped.

## 14. Open questions

These are recorded for later resolution and are deferred to implementation
unless they become blocking.

1. **Effective configuration:** implement the confirmed submission-time snapshot
   with protected credentials and prompts; specify child-version resolution,
   secret rotation/revocation, and where inheritance updates land (draft versus
   automatic publication).
2. **Parallel branch failure:** a final child failure fails its Workflow invocation.
   Define how already-running siblings drain/cancel and how blocked joins appear
   in the UI; they must not produce an overall successful invocation.
3. **Dynamic fan-out construct:** how plan-derived work packages become N
   agent nodes at runtime.
4. **Loop details:** iteration counter scope, nested loops, exit conditions,
   and limit-exhaustion result.
5. **Typed MCP requirements:** how an agent declares it needs a capability
   type (for example "an Atlassian MCP") and how the platform resolves and
   validates it without an unscoped selector; per-team configuration for
   shared workflows.
6. **SSE versus polling** for live task progress in the UI.
7. **Human-in-the-loop protocol mapping:** how ACP and Codex app-server input
   requests map to the `waiting for input` state and response routing.
8. **Container management details:** base images per runtime, backend Docker
   driver, mounts per node, network policy, and how runtimes authenticate
   inside containers.
9. **Auth implementation:** session/token strategy, password hashing, and the
   roles/groups data model.
10. **Artifact storage:** database versus disk, retention, and iteration
    handling; audit retention on task deletion; whether voluntary validator MCP
    checks count toward the three failed completion validations; whether tasks
    can be stopped by users other than their launcher.
11. **Visibility semantics:** meaning of "public" workflow visibility and the
    "Jev" technology for decision nodes (future).
12. **Execution engine:** Temporal is approved as the architecture baseline;
    validate recovery, checkpoints, and agent interactions in a proof of concept
    before full implementation — see
    [Execution orchestration assessment](research/execution-orchestration.md).
13. **Task detail and agent session detail:** neither the UI design nor the API
    for the task detail page or the agent session detail/chat view has been
    defined yet. WebSocket is reserved for live bidirectional agent-session
    interaction; design both pages and their contracts before implementing
    interactive session features.

### Architecture clarification priorities

These affect core boundaries and should be addressed while drafting architecture,
before the relevant implementation packages:

- **Stop and parallel execution:** specify how active parallel nodes drain and
  new admission stops, using the confirmed exception for human-waiting nodes.
- **Integration authorization:** per-team capacity is removed, but selecting
  authorized integration instances for shared workflows still needs a contract.
- **Capacity and nested work:** children do not consume main-task slots. Ensure
  agent-slot handling does not leave a parent container occupying the final slot
  while waiting for child agents that cannot be admitted.
- **Durable shared task information:** define note visibility, availability,
  concurrent updates, dynamic-worker inheritance, and real credential retrieval
  independently of the originating agent session and artifact graph edges.
- **Phase barriers and feedback:** phase-level loops re-execute the target phase
  with a new iteration. Define input selection, barrier reset, and loop accounting
  without mixing previous-iteration outputs into current execution. Explicit
  phase authoring remains optional versus required as an open product choice.
