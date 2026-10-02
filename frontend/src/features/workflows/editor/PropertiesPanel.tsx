import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { WorkflowEditorState, WorkflowNode } from "./model";
import { ScriptEditor } from "./ScriptEditor";

type Props = { state: WorkflowEditorState; onUpdate: (id: string, update: Partial<WorkflowNode>) => void; errors?: Record<string, string[]>; sheetOpen?: boolean };
type FieldProps = { label: string; value: string; onChange: (value: string) => void; multiline?: boolean };
function Field({ label, value, onChange, multiline }: FieldProps) {
  const common = { value, onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange(event.target.value), className: "w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ring" };
  return <label className="grid gap-1.5 text-sm font-medium">{label}{multiline ? <textarea {...common} rows={4} /> : <input {...common} />}</label>;
}

/** Bottom sheet below lg (same pattern as the node palette), side panel from lg up. */
const panelClasses = (sheetOpen: boolean) =>
  `${sheetOpen ? "fixed inset-x-0 bottom-0 z-20 max-h-[65vh] rounded-t-lg border-t bg-background shadow-lg" : "hidden"} w-full overflow-y-auto p-4 lg:static lg:block lg:max-h-none lg:w-80 lg:shrink-0 lg:border-l lg:border-t-0 lg:rounded-none lg:shadow-none lg:p-5`;

export function PropertiesPanel({ state, onUpdate, errors = {}, sheetOpen = true }: Props) {
  const { t } = useTranslation();
  const id = state.selection.nodeIds[0];
  const node = state.definition.nodes.find((item) => item.id === id);
  const [providers, setProviders] = useState<string[] | null>(null);
  const [workflows, setWorkflows] = useState<{ id: string; name: string }[] | null>(null);
  useEffect(() => {
    if (node?.type !== "ai") return;
    let active = true;
    fetch("/api/providers").then((response) => { if (!response.ok) throw new Error("Provider request failed"); return response.json(); }).then((data) => { if (active) setProviders(Array.isArray(data) ? data.map((item) => item.name ?? item.id).filter(Boolean) : data.providers?.map((item: { name?: string; id?: string }) => item.name ?? item.id).filter(Boolean) ?? []); }).catch(() => { if (active) setProviders(null); });
    return () => { active = false; };
  }, [node?.type]);
  useEffect(() => {
    if (node?.type !== "workflow") return;
    let active = true;
    fetch("/api/workflows").then((response) => { if (!response.ok) throw new Error("Workflow request failed"); return response.json(); }).then((data) => { if (active) setWorkflows(Array.isArray(data) ? data : data.workflows ?? []); }).catch(() => { if (active) setWorkflows(null); });
    return () => { active = false; };
  }, [node?.type]);
  if (!node) return <aside className={panelClasses(sheetOpen)} aria-label={t("editor.properties")}><p className="text-sm text-muted-foreground">{t("editor.selectNode")}</p></aside>;
  const update = (patch: Partial<WorkflowNode>) => onUpdate(node.id, { ...node, ...patch });
  const jsonField = (label: string, value: unknown, commit: (value: unknown) => void) => <JsonField label={label} value={value} onCommit={commit} />;
  return <aside aria-label={t("editor.properties")} className={panelClasses(sheetOpen)}>
    <h2 className="mb-4 text-base font-semibold">{t("editor.properties")}: {t(`workflowEditor.types.${node.type}`)}</h2>
    <div className="grid gap-4">
      {node.type === "start" && jsonField(t("editor.inputForm"), node.input_form, (input_form) => update({ input_form } as Partial<WorkflowNode>))}
      {node.type === "script" && <ScriptEditor label={t("editor.code")} value={node.code} onChange={(code) => update({ code } as Partial<WorkflowNode>)} />}
      {node.type === "ai" && <>
        {providers?.length ? <label className="grid gap-1.5 text-sm font-medium">{t("editor.provider")}<select aria-label={t("editor.provider")} className="rounded-md border border-input bg-background px-3 py-2" value={node.agent.runtime} onChange={(event) => update({ agent: { ...node.agent, runtime: event.target.value } } as Partial<WorkflowNode>)}>{providers.map((provider) => <option key={provider}>{provider}</option>)}</select></label> : <Field label={t("editor.provider")} value={node.agent.runtime} onChange={(runtime) => update({ agent: { ...node.agent, runtime } } as Partial<WorkflowNode>)} />}
        <Field label={t("editor.model")} value={node.agent.model} onChange={(model) => update({ agent: { ...node.agent, model } } as Partial<WorkflowNode>)} />
        <Field label={t("editor.instructions")} value={node.agent.instructions} onChange={(instructions) => update({ agent: { ...node.agent, instructions } } as Partial<WorkflowNode>)} multiline />
        <Field label={t("editor.prompt")} value={node.prompt_template} onChange={(prompt_template) => update({ prompt_template } as Partial<WorkflowNode>)} multiline />
      </>}
      {node.type === "http" && <><label className="grid gap-1.5 text-sm font-medium">{t("editor.method")}<select aria-label={t("editor.method")} value={node.method} onChange={(event) => update({ method: event.target.value } as Partial<WorkflowNode>)} className="rounded-md border border-input bg-background px-3 py-2">{["GET", "POST", "PUT", "PATCH", "DELETE"].map((method) => <option key={method}>{method}</option>)}</select></label><Field label={t("editor.url")} value={node.url} onChange={(url) => update({ url } as Partial<WorkflowNode>)} />{jsonField(t("editor.headers"), (node as any).headers ?? {}, (headers) => update({ headers } as Partial<WorkflowNode>))}<Field label={t("editor.body")} value={(node as any).body ?? ""} onChange={(body) => update({ body } as Partial<WorkflowNode>)} multiline /></>}
      {node.type === "decision" && <label className="grid gap-1.5 text-sm font-medium">{t("editor.route")}<select aria-label={t("editor.route")} value={node.selected_next_node_id} onChange={(event) => update({ selected_next_node_id: event.target.value } as Partial<WorkflowNode>)} className="rounded-md border border-input bg-background px-3 py-2"><option value="" />{state.definition.edges.filter((edge) => edge.from === node.id).map((edge) => <option key={edge.to} value={edge.to}>{edge.to}</option>)}</select></label>}
      {node.type === "workflow" && (workflows ? <label className="grid gap-1.5 text-sm font-medium">{t("editor.workflow")}<select aria-label={t("editor.workflow")} value={node.workflow_id} onChange={(event) => update({ workflow_id: event.target.value } as Partial<WorkflowNode>)} className="rounded-md border border-input bg-background px-3 py-2"><option value="" />{workflows.map((workflow) => <option key={workflow.id} value={workflow.id}>{workflow.name}</option>)}</select></label> : <Field label={t("editor.workflow")} value={node.workflow_id} onChange={(workflow_id) => update({ workflow_id } as Partial<WorkflowNode>)} />)}
      {node.type === "end" && jsonField(t("editor.outputMapping"), (node as any).output_mapping ?? {}, (output_mapping) => update({ output_mapping } as Partial<WorkflowNode>))}
    </div>
    {(errors[node.id] ?? []).map((error, index) => <p role="alert" className="mt-3 text-sm text-destructive" key={`${error}-${index}`}>{error}</p>)}
  </aside>;
}

function JsonField({ label, value, onCommit }: { label: string; value: unknown; onCommit: (value: unknown) => void }) {
  const { t } = useTranslation();
  const [text, setText] = useState(() => JSON.stringify(value, null, 2));
  const [invalid, setInvalid] = useState(false);
  useEffect(() => { setText(JSON.stringify(value, null, 2)); }, [value]);
  return <div className="grid gap-1.5 text-sm font-medium"><label>{label}<textarea aria-label={label} rows={5} className="mt-1.5 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs" value={text} onChange={(event) => { setText(event.target.value); try { const parsed = JSON.parse(event.target.value); if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error(); setInvalid(false); onCommit(parsed); } catch { setInvalid(true); } }} /></label>{invalid && <p role="alert" className="text-sm text-destructive">{t("editor.invalidJson")}</p>}</div>;
}
