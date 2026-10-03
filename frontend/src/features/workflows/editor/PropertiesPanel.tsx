import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/api/auth";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { parseJsonObject, type FormField, type WorkflowEditorState, type WorkflowNode } from "./model";
import { ScriptEditor } from "./ScriptEditor";
import { ProviderModelSelect } from "./ProviderModelSelect";

type Props = { state: WorkflowEditorState; onUpdate: (id: string, update: Partial<WorkflowNode>) => void; errors?: Record<string, unknown[]>; sheetOpen?: boolean };
const inputClasses = "w-full min-w-0 rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ring";
const selectClasses = "w-full min-w-0 rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ring";

function Field({ label, value, onChange, multiline }: { label: string; value: string; onChange: (value: string) => void; multiline?: boolean }) {
  const common = { value, onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange(event.target.value), className: inputClasses };
  return <label className="grid min-w-0 gap-1.5 text-sm font-medium">{label}{multiline ? <textarea {...common} rows={4} /> : <input {...common} />}</label>;
}
function SelectField({ label, value, onChange, children }: { label: string; value: string; onChange: (value: string) => void; children: React.ReactNode }) {
  return <label className="grid min-w-0 gap-1.5 text-sm font-medium">{label}<select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)} className={selectClasses}>{children}</select></label>;
}
function JsonObjectField({ label, value, onChange }: { label: string; value: Record<string, unknown>; onChange: (value: Record<string, unknown>) => void }) {
  const { t } = useTranslation();
  const [text, setText] = useState(() => JSON.stringify(value, null, 2));
  const [invalid, setInvalid] = useState(false);
  useEffect(() => { setText(JSON.stringify(value, null, 2)); setInvalid(false); }, [value]);
  return <label className="grid gap-1.5 text-sm font-medium">{label}<textarea aria-label={label} className={`${inputClasses} font-mono text-xs`} rows={4} value={text} onChange={(event) => { setText(event.target.value); const result = parseJsonObject(event.target.value); setInvalid(!result.ok); if (result.ok) onChange(result.value); }} />{invalid && <span role="alert" className="text-sm text-destructive">{t("editor.invalidJson" as never)}</span>}</label>;
}

function FormFieldBuilder({ fields, onChange }: { fields: FormField[]; onChange: (fields: FormField[]) => void }) {
  const { t } = useTranslation();
  const update = (index: number, patch: Partial<FormField>) => onChange(fields.map((field, i) => i === index ? { ...field, ...patch } : field));
  return <fieldset className="grid gap-2"><legend className="text-sm font-medium">{t("editor.inputFormFields" as never)}</legend>
    <ul className="grid gap-2">{fields.map((field, index) => <li key={index} className="grid min-w-0 gap-2 rounded-md border border-border p-2">
      <Field label={`${t("editor.fieldName" as never)} ${index + 1}`} value={field.name} onChange={(name) => update(index, { name })} />
      <SelectField label={`${t("editor.fieldType" as never)} ${index + 1}`} value={field.type} onChange={(type) => update(index, { type: type as FormField["type"] })}>{["string", "number", "boolean"].map((type) => <option key={type}>{type}</option>)}</SelectField>
      <div className="flex items-center justify-between gap-3 text-sm"><span>{t("editor.fieldRequired" as never)}</span><Switch aria-label={`${t("editor.fieldRequired" as never)} ${index + 1}`} checked={field.required} onCheckedChange={(required) => update(index, { required })} /></div>
      <Button type="button" variant="outline" size="sm" className="w-fit" aria-label={`${t("editor.removeField" as never)} ${index + 1}`} onClick={() => onChange(fields.filter((_, i) => i !== index))}>{t("editor.removeField" as never)}</Button>
    </li>)}</ul>
    <Button type="button" variant="outline" size="sm" className="w-fit" onClick={() => onChange([...fields, { name: "", type: "string", required: true }])}>{t("editor.addField" as never)}</Button>
  </fieldset>;
}

function IdentifierList({ label, values, onChange, editable = false, addLabel, removeLabel }: { label: string; values: string[]; onChange?: (values: string[]) => void; editable?: boolean; addLabel: string; removeLabel: string }) {
  return <fieldset className="grid min-w-0 gap-1.5"><legend className="text-sm font-medium">{label}</legend>
    {values.length ? <ul className="flex min-w-0 flex-wrap gap-1.5">{values.map((value, i) => <li key={`${value}-${i}`} className={editable ? "flex min-w-0 items-center gap-1" : "max-w-full rounded-full border border-border bg-muted/40 px-2.5 py-1 text-xs"}>{editable ? <><input aria-label={`${label} ${i + 1}`} value={value} onChange={(event) => onChange?.(values.map((item, index) => index === i ? event.target.value : item))} className={`${inputClasses} min-w-0`} /><button type="button" aria-label={`${removeLabel} ${i + 1}`} onClick={() => onChange?.(values.filter((_, index) => index !== i))} className="rounded px-2 py-1 hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring">×</button></> : <span className="break-all">{value}</span>}</li>)}</ul> : <p className="text-sm text-muted-foreground">—</p>}
    {editable && <Button type="button" variant="outline" size="sm" className="w-fit" onClick={() => onChange?.([...values, ""])}>{addLabel}</Button>}
  </fieldset>;
}

const panelClasses = (sheetOpen: boolean) => `${sheetOpen ? "fixed inset-x-0 bottom-0 z-20 max-h-[65vh] rounded-t-lg border-t bg-background shadow-lg" : "hidden"} w-full min-w-0 overflow-y-auto p-4 lg:static lg:block lg:max-h-none lg:w-80 lg:shrink-0 lg:border-l lg:border-t-0 lg:rounded-none lg:shadow-none lg:p-5`;

export function PropertiesPanel({ state, onUpdate, errors = {}, sheetOpen = true }: Props) {
  const { t } = useTranslation();
  const id = state.selection.nodeIds[0];
  const node = state.definition.nodes.find((item) => item.id === id);
  const [workflows, setWorkflows] = useState<{ id: string; name: string; inputs: string[]; outputs: string[] }[] | null>(null);
  const [workflowsError, setWorkflowsError] = useState(false);
  useEffect(() => {
    if (node?.type !== "workflow") return;
    let active = true;
    api.GET("/workflows").then((result) => {
      if (result.error || result.data === undefined) throw new Error("Workflow request failed");
      if (active) { setWorkflowsError(false); setWorkflows(result.data.map((workflow) => {
        const definition = workflow.active_version?.definition as { nodes?: { type?: string; input_form?: { name: string }[]; inputs?: string[] }[] } | undefined;
        return { id: workflow.id, name: workflow.name, inputs: definition?.nodes?.find((item) => item.type === "start")?.input_form?.map((field) => field.name) ?? [], outputs: definition?.nodes?.find((item) => item.type === "end")?.inputs ?? [] };
      })); }
    }).catch(() => { if (active) { setWorkflowsError(true); setWorkflows([]); } });
    return () => { active = false; };
  }, [node?.type]);
  if (!node) return null;
  const update = (patch: Record<string, unknown>) => onUpdate(node.id, { ...node, ...patch } as WorkflowNode);
  const form = node.type === "start" ? node.input_form : [];
  const referencedWorkflow = node.type === "workflow" ? workflows?.find((workflow) => workflow.id === node.workflow_id) : undefined;
  const outputs = node.type === "http" ? ["response"] : node.type === "script" || node.type === "ai" ? node.outputs : node.type === "workflow" ? workflows?.find((workflow) => workflow.id === node.workflow_id)?.outputs ?? [] : [];
  return <aside aria-label={t("editor.properties")} className={panelClasses(sheetOpen)}>
    <h2 className="mb-4 text-base font-semibold">{t("editor.properties")}: {t(`workflowEditor.types.${node.type}`)}</h2>
    <div className="grid min-w-0 gap-4">
      {node.type === "start" && <FormFieldBuilder fields={form} onChange={(input_form) => update({ input_form })} />}
      {node.type === "script" && <ScriptEditor label={t("editor.code")} value={node.code} onChange={(code) => update({ code })} />}
      {node.type === "ai" && <>
        <ProviderModelSelect runtime={node.agent.runtime} model={node.agent.model} onChange={(runtime, model) => update({ agent: { ...node.agent, runtime, model } })} />
        <Field label={t("editor.instructions")} value={node.agent.instructions} onChange={(instructions) => update({ agent: { ...node.agent, instructions } })} multiline />
        <Field label={t("editor.prompt")} value={node.prompt_template} onChange={(prompt_template) => update({ prompt_template })} multiline />
        <fieldset className="grid gap-1.5"><legend className="text-sm font-medium">{t("editor.validationContract" as never)}</legend>{node.validation.levels.map((level, index) => <div key={index} className="grid min-w-0 gap-1.5 rounded-md border border-border p-2"><Field label={t("editor.levelName" as never)} value={level.name} onChange={(name) => update({ validation: { ...node.validation, levels: node.validation.levels.map((item, i) => i === index ? { ...item, name } : item) } })} /><Field label={t("editor.levelMessageKey" as never)} value={level.message_key} onChange={(message_key) => update({ validation: { ...node.validation, levels: node.validation.levels.map((item, i) => i === index ? { ...item, message_key } : item) } })} /><JsonObjectField label={`${t("editor.levelParams" as never)} ${index + 1}`} value={level.params_schema} onChange={(params_schema) => update({ validation: { ...node.validation, levels: node.validation.levels.map((item, i) => i === index ? { ...item, params_schema } : item) } })} /></div>)}</fieldset>
      </>}
      {node.type === "http" && <><SelectField label={t("editor.method")} value={node.method} onChange={(method) => update({ method })}>{["GET", "POST", "PUT", "PATCH", "DELETE"].map((method) => <option key={method}>{method}</option>)}</SelectField><Field label={t("editor.url")} value={node.url} onChange={(url) => update({ url })} /></>}
      {node.type === "decision" && <p className="rounded-md bg-muted/50 p-3 text-sm text-muted-foreground">{t("editor.decisionNotFunctional" as never)}</p>}
      {node.type === "workflow" && <><SelectField label={t("editor.workflow" as never)} value={node.workflow_id} onChange={(workflow_id) => update({ workflow_id })}><option value="" />{workflows?.map((workflow) => <option key={workflow.id} value={workflow.id}>{workflow.name}</option>)}</SelectField>{workflowsError ? <p role="alert" className="break-words text-sm text-destructive">{t("editor.workflowsLoadError" as never)}</p> : !workflows ? <p role="status" className="text-sm text-muted-foreground">{t("editor.loadingWorkflows" as never)}</p> : node.workflow_id && !referencedWorkflow ? <p className="text-sm text-muted-foreground">{t("editor.workflowUnavailable" as never)}</p> : referencedWorkflow && <div className="grid min-w-0 gap-3 rounded-md border border-border p-3"><IdentifierList label={t("editor.referencedInputs" as never)} values={referencedWorkflow.inputs} addLabel="" removeLabel=""/></div>}</>}
      {node.type !== "start" && <IdentifierList label={t("editor.inputs" as never)} values={node.type === "decision" ? [] : node.inputs} addLabel={t("editor.addInput" as never)} removeLabel={t("editor.removeIdentifier" as never)} />}
      {node.type !== "start" && node.type !== "end" && <IdentifierList label={t("editor.outputs" as never)} values={outputs} editable={node.type === "ai"} onChange={(outputs) => update({ outputs })} addLabel={t("editor.addOutput" as never)} removeLabel={t("editor.removeIdentifier" as never)} />}
      {node.type === "start" && <IdentifierList label={t("editor.inputs" as never)} values={node.input_form.map((field) => field.name)} addLabel="" removeLabel="" />}
    </div>
    {(errors[node.id] ?? []).map((error, index) => <p role="alert" className="mt-3 text-sm text-destructive" key={index}>{typeof error === "string" ? error : t(((error as { message_key?: string }).message_key ?? "") as never)}</p>)}
  </aside>;
}
