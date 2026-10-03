import { useEffect, useState, type ComponentType, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { LoadingControl } from "@/components/ui/loading-control";
import type { ValidationContract } from "./model";

type Format = ValidationContract["format"];
type MonacoProps = { value: string; onChange: (value: string | undefined) => void; height: string; language: string; loading?: ReactNode; options?: Record<string, unknown> };
const formats: Format[] = ["text", "json", "yaml", "markdown"];
const schemaText = (schema: boolean | Record<string, unknown> | null | undefined) => schema === undefined || schema === null ? "" : typeof schema === "boolean" ? String(schema) : JSON.stringify(schema, null, 2);
const parseSchema = (text: string): Record<string, unknown> | boolean | undefined => {
  if (!text.trim()) return undefined;
  const parsed: unknown = JSON.parse(text);
  if (typeof parsed !== "boolean" && (typeof parsed !== "object" || parsed === null || Array.isArray(parsed))) throw new Error("schema must be a JSON object or boolean");
  return parsed as Record<string, unknown> | boolean;
};
const hasSettings = (contract: ValidationContract) => contract.format === "json"
  ? (contract.json_schema !== undefined && contract.json_schema !== null) || Boolean(contract.rules_code?.trim())
  : contract.format === "yaml" && Boolean(contract.rules_code?.trim());

export function OutputValidationDialog({ open, output, value, onOpenChange, onSave, onRemove }: { open: boolean; output: string; inputs: string[]; value?: ValidationContract; onOpenChange: (open: boolean) => void; onSave: (contract: ValidationContract) => void; onRemove: () => void }) {
  const { t } = useTranslation();
  const [format, setFormat] = useState<Format>(value?.format ?? "text");
  const [schema, setSchema] = useState("");
  const [rules, setRules] = useState("");
  const [schemaError, setSchemaError] = useState(false);
  const [monaco, setMonaco] = useState<ComponentType<MonacoProps> | null>(null);
  const [editorFailed, setEditorFailed] = useState(false);
  const [pendingFormat, setPendingFormat] = useState<Format | null>(null);
  const needsCodeEditor = open && (format === "json" || format === "yaml");
  useEffect(() => {
    if (!needsCodeEditor || monaco || editorFailed) return;
    let active = true;
    import("@monaco-editor/react").then((module) => { if (active) setMonaco(() => module.default); }).catch(() => { if (active) setEditorFailed(true); });
    return () => { active = false; };
  }, [needsCodeEditor, monaco, editorFailed]);
  useEffect(() => {
    if (!open) return;
    setFormat(value?.format ?? "text");
    setSchema(value?.format === "json" ? schemaText(value.json_schema) : "");
    setRules(value && (value.format === "json" || value.format === "yaml") ? value.rules_code ?? "" : "");
    setSchemaError(false);
  }, [open, value]);

  const changeFormat = (next: Format) => {
    if (next === format) return;
    const losingSettings = (format === "json" || format === "yaml") && hasSettings(format === "json" ? { format, json_schema: schemaTextToValue(schema), rules_code: rules } : { format, rules_code: rules });
    if (losingSettings) { setPendingFormat(next); return; }
    applyFormat(next);
  };
  const applyFormat = (next: Format) => {
    setFormat(next);
    setSchema("");
    setRules("");
    setSchemaError(false);
    setPendingFormat(null);
  };
  const save = () => {
    try {
      const parsedSchema = format === "json" ? parseSchema(schema) : undefined;
      setSchemaError(false);
      onSave(format === "json" ? { format, ...(parsedSchema !== undefined ? { json_schema: parsedSchema } : {}), ...(rules.trim() ? { rules_code: rules } : {}) }
        : format === "yaml" ? { format, ...(rules.trim() ? { rules_code: rules } : {}) }
          : { format });
      onOpenChange(false);
    } catch { setSchemaError(true); }
  };

  return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-2xl"><DialogHeader><DialogTitle>{t("editor.outputValidationTitle", { output })}</DialogTitle><DialogDescription>{t("editor.outputValidationDescription")}</DialogDescription></DialogHeader>
    <label className="grid gap-1.5 text-sm font-medium">{t("editor.validationFormat")}<select aria-label={t("editor.validationFormat")} className="rounded-md border border-input bg-background px-3 py-2" value={format} onChange={(event) => changeFormat(event.target.value as Format)}>{formats.map((item) => <option key={item} value={item}>{t(`editor.validationFormats.${item}` as never)}</option>)}</select></label>
    {(format === "text" || format === "markdown") && <p className="text-sm text-muted-foreground">{t("editor.parseOnlyExplanation")}</p>}
    {format === "yaml" && <p className="text-sm text-muted-foreground">{t("editor.standardYamlExplanation")}</p>}
    {format === "json" && <fieldset className="grid gap-2"><legend className="font-medium">{t("editor.jsonSchema")}</legend><p className="text-sm text-muted-foreground">{t("editor.jsonSchemaDraft")}</p><textarea aria-label={t("editor.jsonSchema")} value={schema} onChange={(event) => { setSchema(event.target.value); setSchemaError(false); }} rows={8} spellCheck={false} className="w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm focus-visible:outline-2 focus-visible:outline-ring" />{schemaError && <p role="alert" className="text-sm text-destructive">{t("editor.invalidJsonSchema")}</p>}</fieldset>}
    {(format === "json" || format === "yaml") && <fieldset className="grid gap-2">
      <legend className="font-medium">{t("editor.rules")}</legend>
      <label htmlFor="validation-python-rules" className="text-sm font-medium">{t("editor.pythonRules")}</label>
      {monaco && !editorFailed ? <div className="h-48 overflow-hidden rounded-md border border-input"><MonacoEditorComposed editor={monaco} value={rules} onChange={setRules} label={t("editor.pythonRules")} /></div> : <>
        {editorFailed ? <><p role="alert" className="text-xs text-destructive">{t("editor.codeEditorError")}</p><textarea id="validation-python-rules" aria-label={t("editor.pythonRules")} value={rules} onChange={(event) => setRules(event.target.value)} rows={8} spellCheck={false} className="w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm focus-visible:outline-2 focus-visible:outline-ring" /></> : <LoadingControl loading label={t("editor.codeLoading")}><textarea id="validation-python-rules" aria-label={t("editor.pythonRules")} value={rules} onChange={(event) => setRules(event.target.value)} rows={8} spellCheck={false} className="w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm focus-visible:outline-2 focus-visible:outline-ring" /></LoadingControl>}
      </>}
    </fieldset>}
    <DialogFooter className="flex-wrap sm:flex-row sm:justify-between"><Button type="button" variant="outline" onClick={onRemove}>{t("editor.removeValidation")}</Button><Button type="button" onClick={save}>{t("editor.saveValidation")}</Button></DialogFooter></DialogContent>
    <ConfirmDialog open={pendingFormat !== null} onOpenChange={(isOpen) => { if (!isOpen) setPendingFormat(null); }} title={t("editor.validationFormat")} description={t("editor.confirmFormatChange")} confirmLabel={t("common.confirm")} destructive={false} onConfirm={() => { if (pendingFormat) applyFormat(pendingFormat); }} />
  </Dialog>;
}

function schemaTextToValue(text: string): Record<string, unknown> | boolean | undefined {
  try { return parseSchema(text); } catch { return Boolean(text.trim()) ? { invalidDraft: true } : undefined; }
}

function MonacoEditorComposed({ editor: Editor, value, onChange, label }: { editor: ComponentType<MonacoProps>; value: string; onChange: (value: string) => void; label: string }) {
  return <Editor language="python" height="100%" value={value} onChange={(next) => onChange(next ?? "")} options={{ ariaLabel: label, minimap: { enabled: false } }} />;
}
