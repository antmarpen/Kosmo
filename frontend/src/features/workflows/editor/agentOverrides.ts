export type AiAgentDefaults = { model: string; reasoning_effort?: string | null; mcp_ids: string[]; skill_ids: string[] };
export type AgentOverrides = { model?: string; reasoning_effort?: string; added_mcp_ids?: string[]; removed_mcp_ids?: string[]; added_skill_ids?: string[]; removed_skill_ids?: string[] };
type Kind = "mcp" | "skill";

export function displayedAgentValues(input: { agent: AiAgentDefaults; overrides: AgentOverrides }): { model: string; reasoning_effort?: string; mcp_ids: string[]; skill_ids: string[] } {
  const { agent, overrides } = input;
  const merge = (base: string[], added: string[] = [], removed: string[] = []) => {
    const excluded = new Set(removed);
    return [...base.filter((id) => !excluded.has(id)), ...added.filter((id) => !excluded.has(id) && !base.includes(id))];
  };
  return { model: overrides.model ?? agent.model, reasoning_effort: overrides.reasoning_effort ?? agent.reasoning_effort ?? undefined,
    mcp_ids: merge(agent.mcp_ids, overrides.added_mcp_ids, overrides.removed_mcp_ids),
    skill_ids: merge(agent.skill_ids, overrides.added_skill_ids, overrides.removed_skill_ids) };
}

export function applyAgentSwitch(_overrides: AgentOverrides): AgentOverrides { return {}; }

export function resetAgentOverride(overrides: AgentOverrides, key: "model" | "reasoning_effort"): AgentOverrides {
  const next = { ...overrides };
  delete next[key];
  return next;
}

export function updateReferenceDeltas(baseline: string[], current: AgentOverrides, selected: string[], kind: Kind = "mcp"): AgentOverrides {
  const addedKey = `added_${kind}_ids` as const;
  const removedKey = `removed_${kind}_ids` as const;
  const added = new Set(current[addedKey] ?? []);
  const removed = new Set(current[removedKey] ?? []);
  const selectedSet = new Set(selected);
  for (const id of baseline) {
    if (selectedSet.has(id)) removed.delete(id);
    else { removed.add(id); added.delete(id); }
  }
  for (const id of selected) if (!baseline.includes(id)) { added.add(id); removed.delete(id); }
  return { ...current, [addedKey]: [...added], [removedKey]: [...removed] };
}
