import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { useTranslation } from "react-i18next";
import { api } from "@/api/auth";
import { RowActionButton, RowActionLink, RowActions } from "@/components/RowActions";
import { KosmoErrorAlert, type KosmoError } from "@/components/KosmoErrorAlert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import type { components } from "@/api/schema";

type Workflow = components["schemas"]["WorkflowResponse"];
/**
 * Contract of POST /workflows: create-only. The response carries the workflow
 * plus its initial draft; no version is published at creation.
 */
type CreatedWorkflow = components["schemas"]["WorkflowCreatedResponse"];

function unwrap<T>(result: { data?: T; error?: unknown }): T {
  if (result.error || result.data === undefined) throw result.error ?? new Error("Empty API response");
  return result.data;
}

function toKosmoError(cause: unknown): KosmoError {
  // Backend error bodies are flat {code, message_key, params?, details?}.
  const raw = cause as Partial<KosmoError> | undefined;
  return raw && typeof raw.code === "string" && typeof raw.message_key === "string"
    ? { code: raw.code, message_key: raw.message_key, params: raw.params, details: raw.details }
    : { code: "WORKFLOW_LIST_FAILED", message_key: "errors.generic" };
}

export function WorkflowListPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<KosmoError | null>(null);
  // Creation dialog state: the workflow name is required and case-insensitively
  // unique, so conflicts from the backend surface inside the dialog and keep
  // the entered name for correction.
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [createError, setCreateError] = useState<KosmoError | null>(null);
  // Focus contract: this form dialog deliberately moves initial focus to the
  // name field (the form's primary input) instead of the shared close X, and
  // restores the opener on close.
  const nameRef = useRef<HTMLInputElement>(null);
  const lastFocusedRef = useRef<HTMLElement | null>(null);

  // Delete dialog state. The workflow row already carries task counts, so the
  // dialog decides whether tasks exist or are in progress without extra calls.
  const [deleteTarget, setDeleteTarget] = useState<Workflow | null>(null);
  const [deleteTasks, setDeleteTasks] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<KosmoError | null>(null);

  const openDelete = (workflow: Workflow) => {
    setDeleteTarget(workflow);
    setDeleteTasks(false);
    setDeleteError(null);
  };

  const confirmDelete = async () => {
    if (!deleteTarget || deleting) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      const result = await api.DELETE("/workflows/{workflow_id}", {
        params: { path: { workflow_id: deleteTarget.id } },
        body: { delete_tasks: deleteTasks },
      });
      if (result.error) throw result.error;
      setDeleteTarget(null);
      await load();
    } catch (cause) {
      setDeleteError(toKosmoError(cause));
    } finally {
      setDeleting(false);
    }
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setWorkflows(unwrap(await api.GET("/workflows")));
    } catch (cause) {
      setError(toKosmoError(cause));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const submitCreate = async (event: FormEvent) => {
    event.preventDefault();
    if (creating) return;
    setCreating(true);
    setCreateError(null);
    try {
      const created: CreatedWorkflow = unwrap(await api.POST("/workflows", { body: { name: name.trim() } }));
      setCreateOpen(false);
      navigate(`/workflows/${created.id}/edit?draftId=${encodeURIComponent(created.draft_id)}`);
    } catch (cause) {
      setCreateError(toKosmoError(cause));
    } finally {
      setCreating(false);
    }
  };

  const holdOpenWhileCreating = (event: Event) => {
    if (creating) event.preventDefault();
  };

  return <section className="mx-auto w-full max-w-7xl flex-1 px-5 py-8 sm:px-8 sm:py-10">
    <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-balance">{t("workflows.list.title")}</h1>
        <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">{t("workflows.list.description")}</p>
      </div>
      <Button className="w-full sm:w-auto" onClick={() => { setCreateError(null); setCreateOpen(true); }}>
        <Icon name="add" />
        {t("common.add")}
      </Button>
    </div>

    {error && <div className="mt-6"><KosmoErrorAlert error={error} /></div>}
    {loading ? <p className="mt-8 text-sm text-muted-foreground" role="status">{t("workflows.list.loading")}</p> : error ? null : workflows.length === 0 ? (
      <div className="mt-8 rounded-lg border border-border bg-card px-5 py-8 sm:px-7">
        <h2 className="font-medium">{t("workflows.list.emptyTitle")}</h2>
        <p className="mt-1 max-w-xl text-sm leading-6 text-muted-foreground">{t("workflows.list.emptyDescription")}</p>
        <Button className="mt-5" variant="outline" onClick={() => { setCreateError(null); setCreateOpen(true); }}>
          <Icon name="add" />
          {t("workflows.new.createFirst")}
        </Button>
      </div>
    ) : (
      <ul aria-label={t("workflows.list.title")} className="mt-7 space-y-3">
        {workflows.map((workflow) => {
          const active = workflow.active_version;
          const definition = active?.definition as { updated_at?: string } | undefined;
          const updatedAt = definition?.updated_at;
          return <li key={workflow.id} aria-label={workflow.name} className="flex flex-col gap-4 rounded-lg border border-border bg-card p-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-base font-medium">{workflow.name}</h2>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {active ? <span className="inline-flex items-center rounded-md bg-secondary px-2 py-0.5 text-xs font-medium text-secondary-foreground">{t("workflows.list.activeVersion", { version: active.version })}</span> : <span className="inline-flex items-center rounded-md border border-border px-2 py-0.5 text-xs font-medium text-muted-foreground">{t("workflows.list.noActiveVersion")}</span>}
                <span className={active ? "inline-flex items-center rounded-md bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary" : "inline-flex items-center rounded-md border border-border px-2 py-0.5 text-xs font-medium text-muted-foreground"}>{active ? t("workflows.list.published") : t("workflows.list.publicationUnknown")}</span>
                {/* Drafts are author-private: the count covers only the caller's own drafts. */}
                {workflow.draft_count > 0 && <span className="inline-flex items-center rounded-md border border-border px-2 py-0.5 text-xs font-medium text-muted-foreground">{t("workflows.list.draftCount", { count: workflow.draft_count })}</span>}
                <span className="text-xs text-muted-foreground">{updatedAt ? new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" }).format(new Date(updatedAt)) : t("workflows.list.dateUnavailable")}</span>
              </div>
            </div>
            <RowActions>
              <RowActionLink icon="edit" label={t("common.edit")}>
                <Link to={`/workflows/${workflow.id}/edit`} />
              </RowActionLink>
              {active ? (
                <RowActionLink icon="run" label={t("workflows.list.run" as never)}>
                  <Link to={`/tasks/new?workflowId=${encodeURIComponent(workflow.id)}`} />
                </RowActionLink>
              ) : (
                <RowActionLink icon="run" label={t("workflows.list.run" as never)} tooltip={t("workflows.list.runUnavailable" as never)} disabled>
                  <Link to={`/tasks/new?workflowId=${encodeURIComponent(workflow.id)}`} />
                </RowActionLink>
              )}
              <RowActionButton icon="delete" label={t("workflows.list.delete" as never)} onClick={() => openDelete(workflow)} />
            </RowActions>
          </li>;
        })}
      </ul>
    )}

    <Dialog open={createOpen} onOpenChange={(open) => { if (!creating) setCreateOpen(open); }}>
      <DialogContent
        closeDisabled={creating}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          lastFocusedRef.current = document.activeElement as HTMLElement | null;
          nameRef.current?.focus();
        }}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          lastFocusedRef.current?.focus();
          lastFocusedRef.current = null;
        }}
        onEscapeKeyDown={holdOpenWhileCreating}
        onInteractOutside={holdOpenWhileCreating}
      >
        <DialogHeader>
          <DialogTitle>{t("workflows.new.dialogTitle" as never)}</DialogTitle>
          <DialogDescription>{t("workflows.new.dialogDescription" as never)}</DialogDescription>
        </DialogHeader>
        <form onSubmit={(event) => void submitCreate(event)} className="flex flex-col gap-4">
          <label htmlFor="workflow-create-name" className="grid gap-1.5 text-sm font-medium">
            {t("workflows.new.nameLabel" as never)}
            <Input
              id="workflow-create-name"
              ref={nameRef}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("workflows.new.namePlaceholder" as never)}
              autoComplete="off"
              maxLength={200}
              required
              disabled={creating}
            />
          </label>
          {createError && <KosmoErrorAlert error={createError} />}
          <DialogFooter>
            <Button type="submit" loading={creating} disabled={!name.trim()}>
              {t("workflows.new.action")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>

    <Dialog open={deleteTarget !== null} onOpenChange={(open) => { if (!open && !deleting) setDeleteTarget(null); }}>
      <DialogContent
        closeDisabled={deleting}
        onEscapeKeyDown={(event) => { if (deleting) event.preventDefault(); }}
        onInteractOutside={(event) => { if (deleting) event.preventDefault(); }}
      >
        <DialogHeader>
          <DialogTitle>{t("workflows.delete.dialogTitle" as never)}</DialogTitle>
          <DialogDescription>{t("workflows.delete.dialogDescription", { name: deleteTarget?.name ?? "" })}</DialogDescription>
        </DialogHeader>
        {deleteTarget && deleteTarget.in_progress_task_count > 0 ? (
          <p className="text-sm text-muted-foreground">{t("workflows.delete.inProgress", { count: deleteTarget.in_progress_task_count })}</p>
        ) : deleteTarget && deleteTarget.task_count > 0 ? (
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4"
              checked={deleteTasks}
              onChange={(event) => setDeleteTasks(event.target.checked)}
              disabled={deleting}
            />
            <span>{t("workflows.delete.deleteTasksLabel", { count: deleteTarget.task_count })}</span>
          </label>
        ) : null}
        {deleteError && <KosmoErrorAlert error={deleteError} />}
        <DialogFooter>
          <Button variant="outline" onClick={() => setDeleteTarget(null)} disabled={deleting}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="destructive"
            loading={deleting}
            disabled={!deleteTarget || deleteTarget.in_progress_task_count > 0 || (deleteTarget.task_count > 0 && !deleteTasks)}
            onClick={() => void confirmDelete()}
          >
            {t("workflows.delete.action" as never)}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </section>;
}
