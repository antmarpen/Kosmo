import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export type PublishedVersionChoice = { id: string; version: number };

export type ActivateDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Published versions the editor knows about, newest first. */
  candidates: PublishedVersionChoice[];
  /** Version preselected when the dialog opens (the just-published one when present). */
  versionId: string | null;
  /** While the activation request is in flight the dialog cannot be dismissed. */
  loading?: boolean;
  onConfirm: (versionId: string) => void;
};

/**
 * Version picker for explicit activation (publishing never activates on its
 * own). Only shows versions the editor can name — the one just published in
 * this session and the currently active one — because the API has no
 * version-list endpoint yet. The parent owns the activate request; this
 * dialog only reports the chosen version id.
 */
export function ActivateDialog({ open, onOpenChange, candidates, versionId, loading = false, onConfirm }: ActivateDialogProps) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<string | null>(versionId);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const lastFocusedRef = useRef<HTMLElement | null>(null);

  // Re-derive the preselection every time the dialog opens (the just-published
  // version may have changed since the last open).
  useEffect(() => {
    if (open) setSelected(versionId);
  }, [open, versionId]);

  const holdOpenWhileLoading = (event: Event) => {
    if (loading) event.preventDefault();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        onOpenAutoFocus={(event) => {
          // Initial focus on Cancel (the safe action), same contract as
          // ConfirmDialog; restore the opener on close.
          event.preventDefault();
          lastFocusedRef.current = document.activeElement as HTMLElement | null;
          cancelRef.current?.focus();
        }}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          lastFocusedRef.current?.focus();
          lastFocusedRef.current = null;
        }}
        onEscapeKeyDown={holdOpenWhileLoading}
        onInteractOutside={holdOpenWhileLoading}
      >
        <DialogHeader>
          <DialogTitle>{t("workflowEditor.activateTitle" as never)}</DialogTitle>
          <DialogDescription>{t("workflowEditor.activateDescription" as never)}</DialogDescription>
        </DialogHeader>
        {candidates.length > 0 ? (
          <label htmlFor="workflow-activate-version" className="grid gap-1.5 text-sm font-medium">
            {t("workflowEditor.activateVersionLabel" as never)}
            {/* Select styling mirrored from VerifyConnectionDialog until a
                shared select primitive is extracted. */}
            <select
              id="workflow-activate-version"
              value={selected ?? ""}
              disabled={loading}
              onChange={(event) => setSelected(event.target.value)}
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
            >
              {candidates.map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {t("workflows.list.activeVersion", { version: candidate.version })}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <p className="rounded-md bg-muted/60 px-3 py-3 text-sm">{t("workflowEditor.activateNoVersions" as never)}</p>
        )}
        <DialogFooter>
          <Button ref={cancelRef} type="button" variant="outline" disabled={loading} onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button type="button" loading={loading} disabled={!selected} onClick={() => selected && onConfirm(selected)}>
            {t("common.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
