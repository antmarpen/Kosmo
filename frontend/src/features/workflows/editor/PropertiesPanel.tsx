import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/api/auth";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { type FormField, type WorkflowEditorState, type WorkflowNode } from "./model";
import { ScriptEditor } from "./ScriptEditor";
import { OutputValidationDialog } from "./OutputValidationDialog";
import { resolveOutputDescriptor } from "./outputContracts";
import type { ValidationContract } from "./model";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

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

function FormFieldBuilder({ fields, onChange, onEditValidation }: { fields: FormField[]; onChange: (fields: FormField[]) => void; onEditValidation: (index: number) => void }) {
  const { t } = useTranslation();
  const update = (index: number, patch: Partial<FormField>) => onChange(fields.map((field, i) => i === index ? { ...field, ...patch } : field));
  return <fieldset className="grid gap-2"><legend className="text-sm font-medium">{t("editor.inputFormFields" as never)}</legend>
    <ul className="grid gap-2">{fields.map((field, index) => <li key={index} className="grid min-w-0 gap-2 rounded-md border border-border p-2">
      <Field label={`${t("editor.fieldName" as never)} ${index + 1}`} value={field.name} onChange={(name) => update(index, { name })} />
      <SelectField label={`${t("editor.fieldType" as never)} ${index + 1}`} value={field.type} onChange={(type) => update(index, { type: type as FormField["type"] })}>{["string", "number", "boolean"].map((type) => <option key={type}>{type}</option>)}</SelectField>
      <div className="flex items-center justify-between gap-3 text-sm"><span>{t("editor.fieldRequired" as never)}</span><Switch aria-label={`${t("editor.fieldRequired" as never)} ${index + 1}`} checked={field.required} onCheckedChange={(required) => update(index, { required })} /></div>
      <div className="flex items-center gap-2"><Button type="button" variant="outline" size="sm" className="w-fit" onClick={() => onEditValidation(index)}>{t("editor.fieldValidation" as never)}</Button><span role="status" className="text-xs text-muted-foreground">{field.validation ? t("editor.validationConfigured" as never) : t("editor.validationNotConfigured" as never)}</span></div>
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
  const [editingOutput, setEditingOutput] = useState<string | null>(null);
  const [editingField, setEditingField] = useState<number | null>(null);
  useEffect(() => { setEditingField(null); setEditingOutput(null); }, [id]);
  const selectedForm = node?.type === "start" ? node.input_form : undefined;
  useEffect(() => { setEditingField(null); }, [selectedForm]);
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
  const contracts = "output_validation" in node ? node.output_validation ?? {} : {};
  const form = node.type === "start" ? node.input_form : [];
  const referencedWorkflow = node.type === "workflow" ? workflows?.find((workflow) => workflow.id === node.workflow_id) : undefined;
  const outputs = node.type === "http" ? ["response"] : node.type === "script" || node.type === "ai" ? node.outputs : node.type === "workflow" ? workflows?.find((workflow) => workflow.id === node.workflow_id)?.outputs ?? [] : [];
  return <aside aria-label={t("editor.properties")} className={panelClasses(sheetOpen)}>
    <h2 className="mb-4 text-base font-semibold">{t("editor.properties")}: {t(`workflowEditor.types.${node.type}`)}</h2>
    <div className="grid min-w-0 gap-4">
      {node.type === "start" && <FormFieldBuilder fields={form} onChange={(input_form) => update({ input_form })} onEditValidation={setEditingField} />}
      {node.type === "script" && <ScriptEditor label={t("editor.code")} value={node.code} onChange={(code) => update({ code })} />}
      {node.type === "ai" && <>
        <Field label={t("editor.prompt")} value={node.prompt_template} onChange={(prompt_template) => update({ prompt_template })} multiline />
      </>}
      {node.type === "http" && <><SelectField label={t("editor.method")} value={node.method} onChange={(method) => update({ method })}>{["GET", "POST", "PUT", "PATCH", "DELETE"].map((method) => <option key={method}>{method}</option>)}</SelectField><Field label={t("editor.url")} value={node.url} onChange={(url) => update({ url })} /></>}
      {node.type === "decision" && <p className="rounded-md bg-muted/50 p-3 text-sm text-muted-foreground">{t("editor.decisionNotFunctional" as never)}</p>}
      {node.type === "workflow" && <><SelectField label={t("editor.workflow" as never)} value={node.workflow_id} onChange={(workflow_id) => update({ workflow_id })}><option value="" />{workflows?.map((workflow) => <option key={workflow.id} value={workflow.id}>{workflow.name}</option>)}</SelectField>{workflowsError ? <p role="alert" className="break-words text-sm text-destructive">{t("editor.workflowsLoadError" as never)}</p> : !workflows ? <p role="status" className="text-sm text-muted-foreground">{t("editor.loadingWorkflows" as never)}</p> : node.workflow_id && !referencedWorkflow ? <p className="text-sm text-muted-foreground">{t("editor.workflowUnavailable" as never)}</p> : referencedWorkflow && <div className="grid min-w-0 gap-3 rounded-md border border-border p-3"><IdentifierList label={t("editor.referencedInputs" as never)} values={referencedWorkflow.inputs} addLabel="" removeLabel=""/></div>}</>}
      {node.type !== "start" && <fieldset className="grid min-w-0 gap-1.5"><legend className="text-sm font-medium">{t("editor.inputs" as never)}</legend><ul className="flex min-w-0 flex-wrap gap-1.5">{(node.type === "decision" ? [] : node.inputs).map((input, index) => { const source = state.definition.nodes.find((candidate) => candidate.id !== node.id && "outputs" in candidate && (candidate.outputs as string[]).includes(input)); const descriptor = source ? resolveOutputDescriptor(state, source.id, input) : undefined; return <li key={`${input}-${index}`} className="flex max-w-full min-w-0 items-center gap-1 rounded-full border border-border bg-muted/40 px-2 py-1 text-xs"><span className="break-all">{input}</span><Popover><PopoverTrigger asChild><Button type="button" variant="ghost" size="sm" aria-label={`${t("editor.inputInfo" as never)} ${input}`}>ⓘ</Button></PopoverTrigger><PopoverContent role="note"><p className="break-all font-medium">{input}</p><dl className="mt-3 grid min-w-0 gap-1 break-all text-sm [&>dt]:font-medium [&>dt]:text-muted-foreground [&>dt:not(:first-child)]:mt-2 [&>dt:not(:first-child)]:border-t [&>dt:not(:first-child)]:pt-2"><dt>{t("editor.sourceNode" as never)}</dt><dd>{descriptor?.sourceNodeId ?? t("editor.provenanceUnavailable" as never)}</dd><dt>{t("editor.outputKind" as never)}</dt><dd>{descriptor?.kind ?? "artifact"} · {descriptor?.valueType ?? "unknown/runtime"}</dd><dt>{t("editor.validationSummary" as never)}</dt><dd>{descriptor?.validation ? t("editor.validationConfigured" as never) : t("editor.validationNotConfigured" as never)}</dd></dl></PopoverContent></Popover></li>; })}</ul></fieldset>}
      {node.type !== "start" && node.type !== "end" && <fieldset className="grid min-w-0 gap-1.5"><legend className="text-sm font-medium">{t("editor.outputs" as never)}</legend>{outputs.map((output) => { const descriptor = resolveOutputDescriptor(state, node.id, output); return <div key={output} className="flex min-w-0 flex-wrap items-center gap-1">{node.type === "ai" ? <input aria-label={`${t("editor.outputs" as never)} ${outputs.indexOf(output) + 1}`} value={output} onChange={(e) => { const next = outputs.map((item) => item === output ? e.target.value : item); const nextContracts = { ...contracts } as Record<string, ValidationContract>; if (nextContracts[output]) { nextContracts[e.target.value] = nextContracts[output]; delete nextContracts[output]; } update({ outputs: next, output_validation: nextContracts }); }} className={`${inputClasses} w-28`} /> : <span className="max-w-full break-all rounded-full border border-border bg-muted/40 px-2.5 py-1 text-xs">{output}</span>}{node.type === "ai" && <Button type="button" variant="ghost" size="sm" aria-label={`${t("editor.removeOutput" as never)} ${output}`} onClick={() => update({ outputs: node.outputs.filter((_, index) => index !== outputs.indexOf(output)) })}>×</Button>}<Button type="button" size="sm" variant="outline" aria-label={`${t("editor.validationButton" as never)} ${output}`} onClick={() => setEditingOutput(output)}>✓</Button><Popover><PopoverTrigger asChild><Button type="button" variant="ghost" size="sm" aria-label={`${t("editor.outputInfo" as never)} ${output}`}>ⓘ</Button></PopoverTrigger><PopoverContent role="note"><p className="font-medium">{output}</p><dl className="mt-3 grid gap-1 text-sm [&>dt]:font-medium [&>dt]:text-muted-foreground [&>dt:not(:first-child)]:mt-2 [&>dt:not(:first-child)]:border-t [&>dt:not(:first-child)]:pt-2"><dt>{t("editor.sourceNode" as never)}</dt><dd>{descriptor?.sourceNodeId ?? node.id}</dd><dt>{t("editor.outputKind" as never)}</dt><dd>{descriptor?.kind ?? "artifact"} · {descriptor?.valueType ?? "unknown/runtime"}</dd><dt>{t("editor.validationSummary" as never)}</dt><dd>{descriptor?.validation ? t("editor.validationConfigured" as never) : t("editor.validationNotConfigured" as never)}</dd></dl>{descriptor?.orphaned && <p role="alert">{t("editor.orphanedContract" as never)}</p>}{descriptor?.referenceUnavailable && <p role="alert">{t("editor.workflowUnavailable" as never)}</p>}{descriptor?.referenceCycle && <p role="alert">{t("workflowEditor.validation.unreachable" as never)}</p>}</PopoverContent></Popover>{descriptor?.orphaned && <span role="status" className="text-xs text-destructive">{t("editor.orphanedContract" as never)}</span>}</div>; })}{node.type === "ai" && <Button type="button" variant="outline" size="sm" className="w-fit" onClick={() => update({ outputs: [...outputs, ""] })}>{t("editor.addOutput" as never)}</Button>}</fieldset>}
      {node.type !== "start" && node.type !== "end" && Object.entries(contracts).filter(([name]) => !outputs.includes(name)).map(([name]) => <div key={`orphan-${name}`} className="flex min-w-0 flex-wrap items-center gap-1"><span className="break-all text-xs">{name}</span><span role="status" className="text-xs text-destructive">{t("editor.orphanedContract" as never)}</span><Button type="button" variant="outline" size="sm" aria-label={`${t("editor.validationButton" as never)} ${name}`} onClick={() => setEditingOutput(name)}>{t("editor.validationButton" as never)}</Button></div>)}
      {editingOutput !== null && <OutputValidationDialog open output={editingOutput} inputs={"inputs" in node ? node.inputs : []} value={contracts[editingOutput]} onOpenChange={(open) => { if (!open) setEditingOutput(null); }} onSave={(contract) => update({ output_validation: { ...contracts, [editingOutput]: contract } })} onRemove={() => { const next = { ...contracts }; delete next[editingOutput]; update({ output_validation: next }); setEditingOutput(null); }} />}
      {node.type === "start" && editingField !== null && <OutputValidationDialog open output={form[editingField]?.name || t("editor.fieldName" as never)} inputs={[]} value={form[editingField]?.validation && "format" in form[editingField].validation ? form[editingField].validation as ValidationContract : undefined} onOpenChange={(open) => { if (!open) setEditingField(null); }} onSave={(validation) => update({ input_form: form.map((field, index) => index === editingField ? { ...field, validation } : field) })} onRemove={() => { update({ input_form: form.map((field, index) => index === editingField ? { ...field, validation: undefined } : field) }); setEditingField(null); }} />}
      {node.type === "start" && <IdentifierList label={t("editor.inputs" as never)} values={node.input_form.map((field) => field.name)} addLabel="" removeLabel="" />}
    </div>
    {(errors[node.id] ?? []).map((error, index) => <p role="alert" className="mt-3 text-sm text-destructive" key={index}>{typeof error === "string" ? error : t(((error as { message_key?: string }).message_key ?? "") as never)}</p>)}
  </aside>;
}

