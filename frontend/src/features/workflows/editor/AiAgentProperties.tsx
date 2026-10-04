import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { MarkdownPreviewDialog } from "@/components/MarkdownPreviewDialog";
import { CatalogSearchSelect, type CatalogSelectOption } from "@/features/catalogs/components/CatalogSearchSelect";
import { fetchAgents, fetchMcps, fetchSkills } from "@/features/catalogs/api";
import type { AgentCatalogEntry } from "@/features/catalogs/catalogTypes";
import { displayedAgentValues, updateReferenceDeltas } from "./agentOverrides";
import type { AiNode } from "./model";

export function AiAgentProperties({ node, onChange }: { node: AiNode; onChange: (patch: Partial<AiNode>) => void }) {
  const { t } = useTranslation();
  const [agents, setAgents] = useState<AgentCatalogEntry[]>([]);
  const [mcps, setMcps] = useState<CatalogSelectOption[]>([]);
  const [skills, setSkills] = useState<CatalogSelectOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [preview, setPreview] = useState(false);
  useEffect(() => {
    let active = true;
    void Promise.all([fetchAgents(), fetchMcps(), fetchSkills()]).then(([a, m, s]) => {
      if (!active) return;
      setAgents(a); setMcps(m.map(({ id, name }) => ({ id, name }))); setSkills(s.map(({ id, name }) => ({ id, name })));
    }).catch(() => { if (active) setError(true); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  const agent = agents.find((item) => item.id === node.agent_id);
  const validRef = Boolean(agent);
  const overrides = { model: node.model, reasoning_effort: node.reasoning_effort, added_mcp_ids: node.added_mcp_ids, removed_mcp_ids: node.removed_mcp_ids, added_skill_ids: node.added_skill_ids, removed_skill_ids: node.removed_skill_ids };
  const effective = agent ? displayedAgentValues({ agent: { model: agent.model, reasoning_effort: agent.reasoning_effort, mcp_ids: agent.mcp_ids, skill_ids: agent.skill_ids }, overrides }) : undefined;
  const chooseAgent = (id: string | null) => {
    if (id === (node.agent_id ?? null)) return;
    onChange({ agent_id: id, model: undefined, reasoning_effort: undefined, added_mcp_ids: undefined, removed_mcp_ids: undefined, added_skill_ids: undefined, removed_skill_ids: undefined });
  };
  const optionAgents = agents.map(({ id, name }) => ({ id, name }));
  return <section className="grid min-w-0 gap-3">
    <label className="grid gap-1.5 text-sm font-medium">{t("editor.aiAgent" as never)}
      <CatalogSearchSelect options={optionAgents} value={node.agent_id ?? null} onChange={chooseAgent} clearable aria-label={t("editor.aiAgent" as never)} disabled={loading || error} />
    </label>
    {loading && <p role="status" className="text-sm text-muted-foreground">{t("editor.aiAgentsLoading" as never)}</p>}
    {error && <p role="alert" className="text-sm text-destructive">{t("editor.aiAgentsError" as never)}</p>}
    {!loading && !error && !validRef && <p role="alert" className="text-sm text-destructive">{t("editor.aiAgentUnavailable" as never)}</p>}
    {agent && effective && <>
      <div className="grid gap-1.5 text-sm font-medium"><label>{t("editor.model" as never)}<input className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2" value={effective.model} onChange={(e) => onChange({ model: e.target.value })} /></label>
        {node.model !== undefined && <Button type="button" variant="outline" size="sm" className="w-fit" onClick={() => onChange({ model: undefined })}>{t("editor.useAgentDefault" as never)}</Button>}</div>
      <div className="grid gap-1.5 text-sm font-medium"><label>{t("editor.reasoningEffort" as never)}<select className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2" value={effective.reasoning_effort ?? ""} onChange={(e) => onChange({ reasoning_effort: e.target.value || undefined })}><option value="">{t("editor.useAgentDefault" as never)}</option>{["none", "low", "medium", "high", "max", "default"].map((v) => <option key={v}>{v}</option>)}</select></label>
        {node.reasoning_effort !== undefined && <Button type="button" variant="outline" size="sm" className="w-fit" onClick={() => onChange({ reasoning_effort: undefined })}>{t("editor.useAgentDefault" as never)}</Button>}</div>
      <label className="grid gap-1.5 text-sm font-medium">{t("editor.mcpServers" as never)}<CatalogSearchSelect mode="multi" options={mcps} value={effective.mcp_ids} onChange={(ids) => onChange(updateReferenceDeltas(agent.mcp_ids, overrides, ids, "mcp"))} aria-label={t("editor.mcpServers" as never)} /></label>
      <label className="grid gap-1.5 text-sm font-medium">{t("editor.skills" as never)}<CatalogSearchSelect mode="multi" options={skills} value={effective.skill_ids} onChange={(ids) => onChange(updateReferenceDeltas(agent.skill_ids, overrides, ids, "skill"))} aria-label={t("editor.skills" as never)} /></label>
      <Button type="button" variant="outline" size="sm" className="w-fit" onClick={() => setPreview(true)}>{t("editor.viewInstructions" as never)}</Button>
      <MarkdownPreviewDialog open={preview} onOpenChange={setPreview} title={t("editor.instructions" as never)} source={agent.instructions} />
    </>}
  </section>;
}
