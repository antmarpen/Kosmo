import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/api/auth";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { RowActions, RowActionButton } from "@/components/RowActions";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { KosmoErrorAlert, type KosmoError } from "@/components/KosmoErrorAlert";
import { toKosmoError, unwrap } from "./apiError";
import { ProviderIcon } from "./providerIcons";
import { ProviderWizard } from "./ProviderWizard";
import { VerifyConnectionDialog } from "./VerifyConnectionDialog";

type ProviderMetadata = { id: string; name: string; provider_type: string; visibility: string; verification_status: string; owner_user_id: string };

export function ProvidersPage() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<ProviderMetadata[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<KosmoError | null>(null);
  const [wizard, setWizard] = useState(false);
  // Row actions: one target each for the connection-test dialog and the delete
  // confirmation, plus the delete mutation state.
  const [verifyTarget, setVerifyTarget] = useState<ProviderMetadata | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ProviderMetadata | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<KosmoError | null>(null);
  const load = useCallback(async (options?: { silent?: boolean }) => {
    // Silent refreshes (after a row action) keep the list mounted so Radix can
    // restore focus to the originating action button.
    if (!options?.silent) setLoading(true);
    setError(null);
    try { setRows(unwrap(await api.GET("/providers/opencode/config")) as ProviderMetadata[]); }
    catch (cause) { setError(toKosmoError(cause)); }
    finally { if (!options?.silent) setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  async function confirmDelete() {
    const target = deleteTarget;
    if (!target || deleting) return;
    setDeleting(true); setDeleteError(null);
    try {
      unwrap(await api.DELETE("/providers/opencode/config", { params: { query: { config_id: target.id } } }));
      // Close before refreshing so focus returns to the row action while the
      // row still exists; the refresh then removes it.
      setDeleteTarget(null);
      await load({ silent: true });
    } catch (cause) {
      setDeleteError(toKosmoError(cause));
      setDeleteTarget(null);
    } finally {
      setDeleting(false);
    }
  }
  if (wizard) return <ProviderWizard onCancel={() => { setWizard(false); void load(); }} onComplete={() => { setWizard(false); void load(); }} />;
  return <section className="mx-auto w-full max-w-7xl flex-1 px-5 py-8 sm:px-8 sm:py-10">
    <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between"><div><h1 className="text-2xl font-semibold tracking-tight text-balance">{t("providers.title")}</h1><p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">{t("providers.description")}</p></div><Button onClick={() => setWizard(true)} className="w-full sm:w-auto"><Icon name="add" />{t("common.add")}</Button></div>
    {(error || deleteError) && <div className="mt-6 space-y-3">{error && <KosmoErrorAlert error={error}/>}{deleteError && <KosmoErrorAlert error={deleteError}/>}</div>}
    {loading ? <p className="mt-8 text-sm text-muted-foreground">{t("providers.loading")}</p> : error ? null : rows.length === 0 ? <div className="mt-8 border-y border-border py-9"><h2 className="font-medium">{t("providers.emptyTitle")}</h2><p className="mt-1 max-w-xl text-sm leading-6 text-muted-foreground">{t("providers.emptyDescription")}</p><Button variant="outline" className="mt-5" onClick={() => setWizard(true)}>{t("providers.addFirst")}</Button></div> : <div className="mt-7 overflow-hidden rounded-lg border border-border"><div className="hidden grid-cols-[minmax(0,1.5fr)_1fr_1fr_1fr_auto] gap-4 bg-muted/60 px-4 py-3 text-xs font-medium text-muted-foreground sm:grid"><span>{t("providers.columns.name")}</span><span>{t("providers.columns.type")}</span><span>{t("providers.columns.visibility")}</span><span>{t("providers.columns.status")}</span></div><ul className="divide-y divide-border">{rows.map(row => <li key={row.id} className="grid gap-3 px-4 py-4 sm:grid-cols-[minmax(0,1.5fr)_1fr_1fr_1fr_auto] sm:items-center sm:gap-4"><div className="min-w-0"><span className="block truncate text-sm font-medium">{row.name}</span><span className="mt-1 block truncate text-xs text-muted-foreground">{t("providers.columns.owner")}: {row.owner_user_id}</span></div><div className="flex justify-between gap-3 text-sm sm:block"><span className="text-muted-foreground sm:hidden">{t("providers.columns.type")}</span><span className="flex items-center gap-2"><ProviderIcon type={row.provider_type} size={16} className="shrink-0"/>{t(`providers.types.${row.provider_type}.label`, { defaultValue: row.provider_type })}</span></div><div className="flex justify-between gap-3 text-sm sm:block"><span className="text-muted-foreground sm:hidden">{t("providers.columns.visibility")}</span>{t(`providers.visibility.${row.visibility}`, { defaultValue: row.visibility })}</div><div className="flex justify-between gap-3 text-sm sm:block"><span className="text-muted-foreground sm:hidden">{t("providers.columns.status")}</span>{t(`providers.verification.${row.verification_status}`, { defaultValue: row.verification_status })}</div><RowActions><RowActionButton icon="connectionTest" label={t("providers.wizard.testAction")} onClick={() => setVerifyTarget(row)} /><RowActionButton icon="delete" label={t("common.delete")} onClick={() => { setDeleteError(null); setDeleteTarget(row); }} /></RowActions></li>)}</ul></div>}
    <VerifyConnectionDialog open={verifyTarget !== null} onOpenChange={(open) => { if (!open) setVerifyTarget(null); }} onSettled={() => load({ silent: true })} />
    <ConfirmDialog open={deleteTarget !== null} onOpenChange={(open) => { if (!open) setDeleteTarget(null); }} title={t("providers.delete.title")} description={t("providers.delete.description")} confirmLabel={t("providers.delete.confirm")} cancelLabel={t("common.cancel")} loading={deleting} onConfirm={() => void confirmDelete()} />
  </section>;
}
