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

export type PublishedVersionChoice = { id: string; version: number; /** Marks the currently active version (from the published-version listing). */ is_active?: boolean };

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
  /**
   * Whether the server has more published-version pages after `candidates`.
   * When true (and `onLoadMore` is set) an explicit load-more control lets
   * the user reach older published versions beyond the first page.
   */
  hasMore?: boolean;
  /** While the next version page is loading. */
  loadingMore?: boolean;
  /** Appends the next page of published versions to `candidates`. */
  onLoadMore?: () => void;
};

/**
 * Version picker for explicit activation (publishing never activates on its
 * own). Candidates come from the published-version listing, so every published
 * version — including previously published inactive ones — stays selectable
 * after a reload; the currently active one is marked. Older versions beyond
 * the loaded pages stay reachable through the load-more control. The parent
 * owns the activate request and the version pagination; this dialog only
 * reports the chosen version id and forwards load-more clicks.
 */
export function ActivateDialog({ open, onOpenChange, candidates, versionId, loading = false, onConfirm, hasMore = false, loadingMore = false, onLoadMore }: ActivateDialogProps) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<string | null>(versionId);
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
        closeDisabled={loading}
        onOpenAutoFocus={() => {
          // Record the opener before Radix moves focus to the shared close X
          // (the safe action); restore the opener on close.
          lastFocusedRef.current = document.activeElement as HTMLElement | null;
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
          <DialogTitle>{t("workflowEditor.activateTitle")}</DialogTitle>
          <DialogDescription>{t("workflowEditor.activateDescription")}</DialogDescription>
        </DialogHeader>
        {candidates.length > 0 ? (
          <label htmlFor="workflow-activate-version" className="grid gap-1.5 text-sm font-medium">
            {t("workflowEditor.activateVersionLabel")}
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
                  {candidate.is_active
                    // Pending catalog key (coordinator adds it).
                    ? String(t("workflowEditor.activateOptionActive" as never, { version: candidate.version } as never))
                    : t("workflows.list.activeVersion", { version: candidate.version })}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <p className="rounded-md bg-muted/60 px-3 py-3 text-sm">{t("workflowEditor.activateNoVersions")}</p>
        )}
        {candidates.length > 0 && hasMore && onLoadMore && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={loading}
            loading={loadingMore}
            onClick={onLoadMore}
          >
            {t("workflowEditor.activateLoadMore")}
          </Button>
        )}
        <DialogFooter>
          <Button type="button" loading={loading} disabled={!selected} onClick={() => selected && onConfirm(selected)}>
            {t("common.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
