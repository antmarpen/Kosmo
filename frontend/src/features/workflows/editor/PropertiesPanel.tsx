import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/api/auth";
import { Button } from "@/components/ui/button";
import { parseFormFieldArray, parseJsonObject, type FormField, type JsonParseResult, type WorkflowEditorState, type WorkflowNode } from "./model";
import { ScriptEditor } from "./ScriptEditor";

type Props = { state: WorkflowEditorState; onUpdate: (id: string, update: Partial<WorkflowNode>) => void; errors?: Record<string, unknown[]>; sheetOpen?: boolean };
type FieldProps = { label: string; value: string; onChange: (value: string) => void; multiline?: boolean };
const inputClasses = "w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ring";
const selectClasses = "rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ring";

function Field({ label, value, onChange, multiline }: FieldProps) {
  const common = { value, onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange(event.target.value), className: inputClasses };
  return <label className="grid gap-1.5 text-sm font-medium">{label}{multiline ? <textarea {...common} rows={4} /> : <input {...common} />}</label>;
}

function SelectField({ label, value, onChange, children }: { label: string; value: string; onChange: (value: string) => void; children: React.ReactNode }) {
  return <label className="grid gap-1.5 text-sm font-medium">{label}<select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)} className={selectClasses}>{children}</select></label>;
}

/**
 * Editor for the schema-declared identifier lists (Script/AI inputs and
 * outputs, HTTP outputs). Each entry is a SafeIdentifier
 * (^[a-zA-Z0-9._-]{1,64}$); pattern violations surface through the draft
 * validation errors, so the control commits verbatim.
 */
function IdentifierListField({ label, values, addLabel, removeLabel, onChange }: { label: string; values: string[]; addLabel: string; removeLabel: string; onChange: (values: string[]) => void }) {
  return <fieldset className="grid gap-1.5">
    <legend className="text-sm font-medium">{label}</legend>
    <ul className="grid gap-1.5">
      {values.map((value, index) => <li key={index} className="flex items-center gap-1.5">
        <input aria-label={`${label} ${index + 1}`} value={value} onChange={(event) => onChange(values.map((item, i) => (i === index ? event.target.value : item)))} className={inputClasses} />
        <Button type="button" variant="outline" size="icon-xs" aria-label={`${removeLabel} ${index + 1}`} onClick={() => onChange(values.filter((_, i) => i !== index))}>✕</Button>
      </li>)}
    </ul>
    <Button type="button" variant="outline" size="sm" className="w-fit" onClick={() => onChange([...values, ""])}>{addLabel}</Button>
  </fieldset>;
}

/**
 * Field builder for the Start node's `input_form` array. Each entry mirrors
 * backend/shared/graph/schema.py FormField: name (SafeIdentifier), type
 * (string|number|boolean), required, label_message_key.
 */
function FormFieldBuilder({ fields, onChange }: { fields: FormField[]; onChange: (fields: FormField[]) => void }) {
  const { t } = useTranslation();
  const update = (index: number, patch: Partial<FormField>) => onChange(fields.map((field, i) => (i === index ? { ...field, ...patch } : field)));
  return <fieldset className="grid gap-2">
    <legend className="text-sm font-medium">{t("editor.inputFormFields" as never)}</legend>
    <ul className="grid gap-2">
      {fields.map((field, index) => <li key={index} className="grid gap-1.5 rounded-md border border-border p-2">
        <label className="grid gap-1 text-sm font-medium">{t("editor.fieldName" as never)}
          <input aria-label={`${t("editor.fieldName" as never)} ${index + 1}`} value={field.name} onChange={(event) => update(index, { name: event.target.value })} className={inputClasses} />
        </label>
        <label className="grid gap-1 text-sm font-medium">{t("editor.fieldType" as never)}
          <select aria-label={`${t("editor.fieldType" as never)} ${index + 1}`} value={field.type} onChange={(event) => update(index, { type: event.target.value as FormField["type"] })} className={selectClasses}>
            {["string", "number", "boolean"].map((type) => <option key={type} value={type}>{type}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm font-medium">
          <input type="checkbox" aria-label={`${t("editor.fieldRequired" as never)} ${index + 1}`} checked={field.required} onChange={(event) => update(index, { required: event.target.checked })} className="size-4" />
          {t("editor.fieldRequired" as never)}
        </label>
        <label className="grid gap-1 text-sm font-medium">{t("editor.fieldLabelKey" as never)}
          <input aria-label={`${t("editor.fieldLabelKey" as never)} ${index + 1}`} value={field.label_message_key} onChange={(event) => update(index, { label_message_key: event.target.value })} className={inputClasses} />
        </label>
        <Button type="button" variant="outline" size="sm" className="w-fit" aria-label={`${t("editor.removeField" as never)} ${index + 1}`} onClick={() => onChange(fields.filter((_, i) => i !== index))}>{t("editor.removeField" as never)}</Button>
      </li>)}
    </ul>
    <Button type="button" variant="outline" size="sm" className="w-fit" onClick={() => onChange([...fields, { name: "", type: "string", required: true, label_message_key: "" }])}>{t("editor.addField" as never)}</Button>
  </fieldset>;
}

/**
 * Shared safe-parse contract for the JSON paste controls: typed text commits
 * only when the parser accepts both the JSON syntax and the target authoring
 * shape; otherwise the last valid value stays in editor state and a localized
 * inline error explains what the text must look like. Nothing that could make
 * client validation throw ever reaches editor state.
 */
function JsonPasteField({ label, value, parse, messages, onCommit }: { label: string; value: unknown; parse: (text: string) => JsonParseResult<unknown>; messages: { malformed: string; kind: string; shape: string }; onCommit: (value: unknown) => void }) {
  const [text, setText] = useState(() => JSON.stringify(value, null, 2));
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setText(JSON.stringify(value, null, 2)); setError(null); }, [value]);
  return <div className="grid gap-1.5 text-sm font-medium"><label>{label}<textarea aria-label={label} rows={5} className="mt-1.5 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs" value={text} onChange={(event) => {
    const next = event.target.value;
    setText(next);
    const result = parse(next);
    if (result.ok) { setError(null); onCommit(result.value); }
    else setError(messages[result.reason]);
  }} /></label>{error && <p role="alert" className="text-sm text-destructive">{error}</p>}</div>;
}

/**
 * Secondary paste path for the start `input_form`: JSON arrays only. Entries
 * must satisfy the structural FormField contract (string name and label key,
 * a schema type, boolean required) so editor state stays type-safe; semantic
 * issues (empty name, unsafe identifier) remain committable and surface
 * through draft validation instead.
 */
function JsonArrayField({ label, value, onCommit }: { label: string; value: FormField[]; onCommit: (value: FormField[]) => void }) {
  const { t } = useTranslation();
  return <JsonPasteField label={label} value={value} parse={parseFormFieldArray} messages={{ malformed: t("editor.invalidJsonArray" as never), kind: t("editor.invalidJsonArray" as never), shape: t("editor.invalidFormFieldArray" as never) }} onCommit={(parsed) => onCommit(parsed as FormField[])} />;
}

/**
 * Object-valued paste path for a validation level's `params_schema`: JSON
 * objects only, unknown keys preserved verbatim for the validation contract.
 */
function JsonObjectField({ label, value, onCommit }: { label: string; value: Record<string, unknown>; onCommit: (value: Record<string, unknown>) => void }) {
  const { t } = useTranslation();
  return <JsonPasteField label={label} value={value} parse={parseJsonObject} messages={{ malformed: t("editor.invalidJson" as never), kind: t("editor.invalidJson" as never), shape: t("editor.invalidJson" as never) }} onCommit={(parsed) => onCommit(parsed as Record<string, unknown>)} />;
}

/**
 * Schema v1 (extra="forbid") rejects these legacy authoring leftovers, so
 * editing the node in the panel must not carry them into the next save.
 */
function withoutRejectedFields(node: WorkflowNode): WorkflowNode {
  if (node.type === "http") {
    const { headers: _headers, body: _body, ...rest } = node as WorkflowNode & Record<string, unknown>;
    return rest as WorkflowNode;
  }
  if (node.type === "end") {
    const { output_mapping: _outputMapping, ...rest } = node as WorkflowNode & Record<string, unknown>;
    return rest as WorkflowNode;
  }
  return node;
}

/** Bottom sheet below lg (same pattern as the node palette), side panel from lg up. */
const panelClasses = (sheetOpen: boolean) =>
  `${sheetOpen ? "fixed inset-x-0 bottom-0 z-20 max-h-[65vh] rounded-t-lg border-t bg-background shadow-lg" : "hidden"} w-full overflow-y-auto p-4 lg:static lg:block lg:max-h-none lg:w-80 lg:shrink-0 lg:border-l lg:border-t-0 lg:rounded-none lg:shadow-none lg:p-5`;

/**
 * Editor for the selected node's properties. The panel exists only while a
 * node is selected (spec: it appears on selection and closes when the canvas
 * is clicked); with no selection it renders nothing instead of a placeholder,
 * so the canvas keeps the full width and keyboard focus never lands in an
 * empty panel.
 */
export function PropertiesPanel({ state, onUpdate, errors = {}, sheetOpen = true }: Props) {
  const { t } = useTranslation();
  const id = state.selection.nodeIds[0];
  const node = state.definition.nodes.find((item) => item.id === id);
  const [workflows, setWorkflows] = useState<{ id: string; name: string }[] | null>(null);
  useEffect(() => {
    if (node?.type !== "workflow") return;
    let active = true;
    api.GET("/workflows").then((result) => {
      if (result.error || result.data === undefined) throw new Error("Workflow request failed");
      if (active) setWorkflows(result.data.map((workflow) => ({ id: workflow.id, name: workflow.name })));
    }).catch(() => { if (active) setWorkflows(null); });
    return () => { active = false; };
  }, [node?.type]);
  if (!node) return null;
  const update = (patch: Partial<WorkflowNode>) => onUpdate(node.id, { ...withoutRejectedFields(node), ...patch });
  const startForm = node.type === "start" && Array.isArray(node.input_form) ? node.input_form : [];
  const validationLevels = node.type === "ai" && Array.isArray(node.validation.levels) ? node.validation.levels : [];
  return <aside aria-label={t("editor.properties")} className={panelClasses(sheetOpen)}>
    <h2 className="mb-4 text-base font-semibold">{t("editor.properties")}: {t(`workflowEditor.types.${node.type}`)}</h2>
    <div className="grid gap-4">
      {node.type === "start" && <>
        <FormFieldBuilder fields={startForm} onChange={(input_form) => update({ input_form })} />
        <JsonArrayField label={t("editor.inputFormJson" as never)} value={startForm} onCommit={(input_form) => update({ input_form })} />
      </>}
      {node.type === "script" && <>
        <ScriptEditor label={t("editor.code")} value={node.code} onChange={(code) => update({ code })} />
        <IdentifierListField label={t("editor.inputs" as never)} values={node.inputs} addLabel={t("editor.addInput" as never)} removeLabel={t("editor.removeIdentifier" as never)} onChange={(inputs) => update({ inputs })} />
        <IdentifierListField label={t("editor.outputs" as never)} values={node.outputs} addLabel={t("editor.addOutput" as never)} removeLabel={t("editor.removeIdentifier" as never)} onChange={(outputs) => update({ outputs })} />
      </>}
      {node.type === "ai" && <>
        {/* The schema fixes the agent runtime to the single valid value. */}
        <SelectField label={t("editor.runtime" as never)} value={node.agent.runtime} onChange={(runtime) => update({ agent: { ...node.agent, runtime: runtime as "opencode" } })}><option value="opencode">opencode</option></SelectField>
        <Field label={t("editor.model")} value={node.agent.model} onChange={(model) => update({ agent: { ...node.agent, model } })} />
        <Field label={t("editor.instructions")} value={node.agent.instructions} onChange={(instructions) => update({ agent: { ...node.agent, instructions } })} multiline />
        <Field label={t("editor.prompt")} value={node.prompt_template} onChange={(prompt_template) => update({ prompt_template })} multiline />
        <IdentifierListField label={t("editor.inputs" as never)} values={node.inputs} addLabel={t("editor.addInput" as never)} removeLabel={t("editor.removeIdentifier" as never)} onChange={(inputs) => update({ inputs })} />
        <IdentifierListField label={t("editor.outputs" as never)} values={node.outputs} addLabel={t("editor.addOutput" as never)} removeLabel={t("editor.removeIdentifier" as never)} onChange={(outputs) => update({ outputs })} />
        {/* Exactly three levels (schema min/max), each with a JSON object
            editor for its params_schema (unknown keys preserved). */}
        <fieldset className="grid gap-1.5">
          <legend className="text-sm font-medium">{t("editor.validationContract" as never)}</legend>
          <ul className="grid gap-2">
            {validationLevels.map((level, index) => <li key={index} className="grid gap-1.5 rounded-md border border-border p-2">
              <input aria-label={`${t("editor.levelName" as never)} ${index + 1}`} value={level.name} onChange={(event) => update({ validation: { ...node.validation, levels: node.validation.levels.map((item, i) => (i === index ? { ...item, name: event.target.value } : item)) } })} className={inputClasses} />
              <input aria-label={`${t("editor.levelMessageKey" as never)} ${index + 1}`} value={level.message_key} onChange={(event) => update({ validation: { ...node.validation, levels: node.validation.levels.map((item, i) => (i === index ? { ...item, message_key: event.target.value } : item)) } })} className={inputClasses} />
              <JsonObjectField label={`${t("editor.levelParams" as never)} ${index + 1}`} value={level.params_schema} onCommit={(params_schema) => update({ validation: { ...node.validation, levels: node.validation.levels.map((item, i) => (i === index ? { ...item, params_schema } : item)) } })} />
            </li>)}
          </ul>
        </fieldset>
      </>}
      {node.type === "http" && <>
        <SelectField label={t("editor.method")} value={node.method} onChange={(method) => update({ method })}>{["GET", "POST", "PUT", "PATCH", "DELETE"].map((method) => <option key={method}>{method}</option>)}</SelectField>
        <Field label={t("editor.url")} value={node.url} onChange={(url) => update({ url })} />
        <IdentifierListField label={t("editor.outputs" as never)} values={node.outputs} addLabel={t("editor.addOutput" as never)} removeLabel={t("editor.removeIdentifier" as never)} onChange={(outputs) => update({ outputs })} />
      </>}
      {node.type === "decision" && <SelectField label={t("editor.route")} value={node.selected_next_node_id} onChange={(selected_next_node_id) => update({ selected_next_node_id })}><option value="" />{state.definition.edges.filter((edge) => edge.from === node.id).map((edge) => <option key={edge.to} value={edge.to}>{edge.to}</option>)}</SelectField>}
      {node.type === "workflow" && (workflows ? <SelectField label={t("editor.workflow")} value={node.workflow_id} onChange={(workflow_id) => update({ workflow_id })}><option value="" />{workflows.map((workflow) => <option key={workflow.id} value={workflow.id}>{workflow.name}</option>)}</SelectField> : <Field label={t("editor.workflow")} value={node.workflow_id} onChange={(workflow_id) => update({ workflow_id })} />)}
      {/* EndNode has no schema properties beyond its id: no controls. */}
    </div>
    {(errors[node.id] ?? []).map((error, index) => {
      // The errors prop is typed as string[] but EditorPage may pass
      // KosmoErrorDetail[] (objects with message_key).  Handle both:
      // resolve message_key through i18next for objects, pass strings through.
      const msg = typeof error === "object" && error !== null && "message_key" in error
        ? t((error as any).message_key as never)
        : error as string;
      return <p role="alert" className="mt-3 text-sm text-destructive" key={`${msg}-${index}`}>{msg}</p>;
    })}
  </aside>;
}
