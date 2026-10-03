import { Component, useEffect, useRef, useState, type ComponentType, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

type MonacoProps = { value: string; onChange: (value: string | undefined) => void; height: string; language: string; loading?: ReactNode; options?: Record<string, unknown> };

type EditorProps = { value: string; onChange: (value: string) => void; label: string };

const textClasses = "w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm focus-visible:outline-2 focus-visible:outline-ring";

function FallbackTextarea({ value, onChange, label, className }: EditorProps & { className?: string }) {
  return <textarea aria-label={label} value={value} onChange={(event) => onChange(event.target.value)} rows={8} className={cn(textClasses, "resize-none", className)} />;
}

/** Skeleton shown inside the modal while the chunk (and monaco) loads. */
function EditorLoading({ text }: { text: string }) {
  return <div className="flex min-h-40 flex-1 flex-col gap-2 bg-muted/30 p-4">
    <div className="h-4 w-1/3 animate-pulse rounded bg-muted" />
    <div className="h-4 w-2/3 animate-pulse rounded bg-muted" />
    <div className="h-4 w-1/2 animate-pulse rounded bg-muted" />
    <p className="mt-auto text-xs text-muted-foreground">{text}</p>
  </div>;
}

/** Swaps in the localized error plus a plain-text fallback when the chunk (or Monaco itself) throws. */
class MonacoErrorBoundary extends Component<{ failed: ReactNode; ready: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? this.props.failed : this.props.ready; }
}

/**
 * Script node code editor for the properties panel. The panel shows a compact
 * one code action; the Monaco editor lives inside a
 * large modal with an explicit Save action and the shared close X (the X
 * discards the draft), mirroring the ConfirmDialog interaction contract
 * (initial focus on the shared close X, opener focus restored on close,
 * Escape/overlay dismissal held while the chunk loads). `onChange` receives
 * the draft only when the user saves, so closing the dialog always leaves
 * the stored node code untouched.
 */
export function ScriptEditor({ value, onChange, label }: EditorProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(value);
  const [monaco, setMonaco] = useState<ComponentType<MonacoProps> | null>(null);
  const [failed, setFailed] = useState(false);
  const lastFocusedRef = useRef<HTMLElement | null>(null);

  // Lazy boundary: the ~2 MB chunk is fetched on first open, never on page
  // load and never for other node types. A failed fetch offers a retry by
  // reopening the modal.
  useEffect(() => {
    if (!open || monaco) return;
    let active = true;
    import("@monaco-editor/react").then((module) => { if (active) setMonaco(() => module.default); }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [open, monaco]);

  const loading = open && !monaco && !failed;
  const dirty = draft !== value;
  const openEditor = () => { setDraft(value); setFailed(false); setOpen(true); };
  const save = () => { onChange(draft); setOpen(false); };

  // ConfirmDialog focus contract: Radix's first-tabbable default lands on the
  // shared close X (the safe action); record the opener so close can restore
  // it (Radix's modal default would target a DialogTrigger we do not render).
  const handleOpenAutoFocus = () => {
    lastFocusedRef.current = document.activeElement as HTMLElement | null;
  };
  const handleCloseAutoFocus = (event: Event) => {
    event.preventDefault();
    lastFocusedRef.current?.focus();
    lastFocusedRef.current = null;
  };
  const holdWhileLoading = (event: Event) => { if (loading) event.preventDefault(); };

  return <div className="grid gap-1.5">
    <Button type="button" className="w-full" onClick={openEditor}>{t("editor.editScript")}</Button>
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="flex h-[80vh] flex-col gap-4 sm:max-w-5xl" closeDisabled={loading} onOpenAutoFocus={handleOpenAutoFocus} onCloseAutoFocus={handleCloseAutoFocus} onEscapeKeyDown={holdWhileLoading} onInteractOutside={holdWhileLoading}>
        <DialogHeader>
          <DialogTitle>{t("workflowEditor.types.script")}</DialogTitle>
          <DialogDescription>{t("editor.codePlaceholder")}</DialogDescription>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col">
          {monaco ? <MonacoErrorBoundary failed={<p role="alert" className="text-sm text-destructive">{t("editor.codeEditorError")}</p>} ready={
            <div className="min-h-0 flex-1 overflow-hidden rounded-md border border-input">
              <MonacoEditorComposed editor={monaco} draft={draft} setDraft={setDraft} label={label} loadingText={t("editor.codeLoading")} />
            </div>
          } /> : failed
            ? <div className="flex min-h-0 flex-1 flex-col gap-2"><p role="alert" className="text-sm text-destructive">{t("editor.codeEditorError")}</p><FallbackTextarea value={draft} onChange={setDraft} label={label} className="min-h-0 flex-1" /></div>
            : <EditorLoading text={t("editor.codeLoading")} />}
        </div>
        <DialogFooter>
          <Button type="button" disabled={!dirty || loading} onClick={save}>{t("editor.save")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>;
}

function MonacoEditorComposed({ editor: Editor, draft, setDraft, label, loadingText }: { editor: ComponentType<MonacoProps>; draft: string; setDraft: (value: string) => void; label: string; loadingText: string }) {
  return <Editor language="python" height="100%" value={draft} onChange={(next) => setDraft(next ?? "")} loading={<EditorLoading text={loadingText} />} options={{ ariaLabel: label, minimap: { enabled: false } }} />;
}
