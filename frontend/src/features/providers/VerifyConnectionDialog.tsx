import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/api/auth";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Icon } from "@/components/ui/icon";
import { KosmoErrorAlert, type KosmoError } from "@/components/KosmoErrorAlert";
import { toKosmoError, unwrap } from "./apiError";

type Violation = { message_key: string; params?: Record<string, unknown> };

/** Bodies of the saved-config verification endpoints (openapi-typescript types them as `unknown`). */
type SavedConfigVerification = { valid: boolean; violations: Violation[]; models: string[] };
type ModelVerification = { ok: boolean; latency_ms?: number; verification_id?: string; error?: KosmoError };

/**
 * Native select styled like the wizard's model picker. The shared ui kit has
 * no select primitive and `ProviderWizard` keeps its constant private, so the
 * class string is mirrored here until a primitive is extracted.
 */
const SELECT_CLASS = "h-9 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50";

export type VerifyConnectionDialogProps = {
  open: boolean;
  /** Id of the stored configuration this dialog's row targets. */
  configId: string | null;
  onOpenChange: (open: boolean) => void;
  /**
   * Runs after a model verification attempt settles. `verify-model` records
   * the row status server-side (even when it fails), so the list is re-fetched
   * instead of the dialog guessing the resulting status.
   */
  onSettled: () => void | Promise<void>;
};

/**
 * Row action dialog that tests a SAVED provider configuration: it lists the
 * models of the stored config named by `configId` through `/config/verify`,
 * lets the user mark one, and sends a real container request through
 * `/config/verify-model` with `{ model, config_id }`. No model is persisted:
 * the choice belongs to the test only, matching the wizard's connection step.
 * Success shows the measured latency; failures render the structured backend
 * error through `KosmoErrorAlert`.
 */
export function VerifyConnectionDialog({ open, configId, onOpenChange, onSettled }: VerifyConnectionDialogProps) {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [violations, setViolations] = useState<Violation[] | null>(null);
  const [loadError, setLoadError] = useState<KosmoError | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<KosmoError | null>(null);
  const [verified, setVerified] = useState<{ model: string; latencyMs: number } | null>(null);
  // Bumped on close and on each new attempt; in-flight responses compare
  // against it and discard themselves when stale (same pattern as the wizard).
  const requestSeq = useRef(0);
  // Focus contract (same as ConfirmDialog): this dialog is controlled without
  // a rendered trigger, so Radix's built-in restore would send focus to the
  // document body. Capture the opener (the row action) on open and restore it
  // on close.
  const lastFocusedRef = useRef<HTMLElement | null>(null);

  const handleOpenAutoFocus = () => {
    // Record the opener before Radix moves focus into the dialog; the default
    // content-focus behavior stays untouched.
    lastFocusedRef.current = document.activeElement as HTMLElement | null;
  };

  const handleCloseAutoFocus = (event: Event) => {
    event.preventDefault();
    lastFocusedRef.current?.focus();
    lastFocusedRef.current = null;
  };

  useEffect(() => {
    if (!open || !configId) return;
    const seq = ++requestSeq.current;
    setModels([]); setSelectedModel(""); setViolations(null); setLoadError(null);
    setError(null); setVerified(null); setLoading(true);
    void (async () => {
      try {
        // The generated schema documents no error status for /verify, but the
        // backend still answers 404/503 with flat KosmoError bodies; unwrap
        // throws them so the structured key survives.
        const response = unwrap(await api.POST("/providers/opencode/config/verify",
          { body: { config_id: configId } })) as SavedConfigVerification;
        if (seq !== requestSeq.current) return;
        if (!response.valid) { setViolations(response.violations ?? []); return; }
        setModels(response.models ?? []);
        setSelectedModel(response.models?.[0] ?? "");
      } catch (cause) {
        if (seq !== requestSeq.current) return;
        setLoadError(toKosmoError(cause));
      } finally {
        if (seq === requestSeq.current) setLoading(false);
      }
    })();
    return () => { requestSeq.current += 1; };
  }, [open, configId]);

  async function verifyModel() {
    if (!selectedModel || verifying || !configId) return;
    const seq = ++requestSeq.current;
    setVerifying(true); setError(null);
    try {
      const response = unwrap(await api.POST("/providers/opencode/config/verify-model",
        { body: { model: selectedModel, config_id: configId } })) as ModelVerification;
      if (seq !== requestSeq.current) return;
      if (!response.ok) {
        setError(response.error ?? { code: "PROVIDER_VERIFICATION_FAILED", message_key: "errors.provider.verification_failed" });
      } else {
        setVerified({ model: selectedModel, latencyMs: response.latency_ms ?? 0 });
      }
    } catch (cause) {
      if (seq !== requestSeq.current) return;
      setError(toKosmoError(cause));
    } finally {
      if (seq === requestSeq.current) setVerifying(false);
    }
    await onSettled();
  }

  // While a real request is in flight the result cannot be orphaned: Escape
  // and outside dismissal are held (same contract as `ConfirmDialog`).
  const holdOpenWhileVerifying = (event: Event) => { if (verifying) event.preventDefault(); };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        onOpenAutoFocus={handleOpenAutoFocus}
        onCloseAutoFocus={handleCloseAutoFocus}
        onEscapeKeyDown={holdOpenWhileVerifying}
        onInteractOutside={holdOpenWhileVerifying}
      >
        <DialogHeader>
          <DialogTitle>{t("providers.actions.verifyTitle")}</DialogTitle>
          <DialogDescription>{t("providers.actions.verifyDescription")}</DialogDescription>
        </DialogHeader>
        {loadError ? <KosmoErrorAlert error={loadError} /> :
          violations ? <KosmoErrorAlert error={{ code: "PROVIDER_CONFIG_INVALID", message_key: "errors.provider.config_invalid", details: violations }} /> :
          loading ? <p role="status" className="text-sm text-muted-foreground">{t("providers.wizard.testing")}</p> : (
            <div className="space-y-4">
              {models.length > 0 ? (
                <div className="space-y-2">
                  <label htmlFor="provider-verify-model" className="block text-sm font-medium">{t("providers.wizard.modelsTitle")}</label>
                  <select
                    id="provider-verify-model"
                    value={selectedModel}
                    disabled={verifying}
                    onChange={(event) => setSelectedModel(event.target.value)}
                    className={SELECT_CLASS}
                  >
                    {models.map((model) => <option key={model} value={model}>{model}</option>)}
                  </select>
                </div>
              ) : <p className="rounded-md bg-muted/60 px-3 py-3 text-sm">{t("providers.wizard.noModels")}</p>}
              {verified && (
                <div role="status" className="flex items-start gap-2 rounded-md border border-border bg-muted/30 px-3 py-2">
                  <Icon name="check" className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden="true" />
                  <p className="min-w-0 text-sm">{t("providers.wizard.verifiedWith", { model: verified.model, latency: verified.latencyMs })}</p>
                </div>
              )}
              {error && <KosmoErrorAlert error={error} />}
            </div>
          )}
        <DialogFooter>
          <Button type="button" variant="outline" disabled={verifying} onClick={() => onOpenChange(false)}>
            {t("providers.actions.close")}
          </Button>
          <Button
            type="button"
            loading={verifying}
            disabled={loading || violations !== null || loadError !== null || models.length === 0 || !selectedModel}
            onClick={() => void verifyModel()}
          >
            {t("providers.wizard.testAction")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
