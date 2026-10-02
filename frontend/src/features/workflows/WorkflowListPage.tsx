import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import { useTranslation } from "react-i18next";
import { api } from "@/api/auth";
import { RowActionLink, RowActions } from "@/components/RowActions";
import { KosmoErrorAlert, type KosmoError } from "@/components/KosmoErrorAlert";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import type { components } from "@/api/schema";

type Workflow = components["schemas"]["WorkflowResponse"];
type CreatedWorkflow = components["schemas"]["WorkflowVersionResponse"];
/** Contract of POST /workflows/{workflow_id}/drafts (route has no response_model). */
type CreatedDraft = { draft_id: string; revision: number };

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
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<KosmoError | null>(null);

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

  const createWorkflow = async () => {
    setCreating(true);
    setError(null);
    const name = t("workflows.new.defaultName");
    try {
      const created: CreatedWorkflow = unwrap(await api.POST("/workflows", { body: {
        schema_version: "v1",
        name,
        nodes: [
          { type: "start", id: "start", input_form: [{ name: "topic", type: "string", required: true, label_message_key: "workflow.topic.label" }] },
          { type: "end", id: "end" },
        ],
        edges: [{ from: "start", to: "end" }],
      } }));
      const draft = unwrap(await api.POST("/workflows/{workflow_id}/drafts", { params: { path: { workflow_id: created.workflow_id } } })) as CreatedDraft;
      if (!draft.draft_id) throw new Error("Draft response did not include draft_id");
      navigate(`/workflows/${created.workflow_id}/edit?draftId=${encodeURIComponent(draft.draft_id)}`);
    } catch (cause) {
      setError(toKosmoError(cause));
    } finally {
      setCreating(false);
    }
  };

  return <section className="mx-auto w-full max-w-7xl flex-1 px-5 py-8 sm:px-8 sm:py-10">
    <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-balance">{t("workflows.list.title")}</h1>
        <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">{t("workflows.list.description")}</p>
      </div>
      <Button className="w-full sm:w-auto" loading={creating} onClick={() => void createWorkflow()}>
        <Icon name="add" />
        {t("common.add")}
      </Button>
    </div>

    {error && <div className="mt-6"><KosmoErrorAlert error={error} /></div>}
    {loading ? <p className="mt-8 text-sm text-muted-foreground" role="status">{t("workflows.list.loading")}</p> : error ? null : workflows.length === 0 ? (
      <div className="mt-8 rounded-lg border border-border bg-card px-5 py-8 sm:px-7">
        <h2 className="font-medium">{t("workflows.list.emptyTitle")}</h2>
        <p className="mt-1 max-w-xl text-sm leading-6 text-muted-foreground">{t("workflows.list.emptyDescription")}</p>
        <Button className="mt-5" variant="outline" loading={creating} onClick={() => void createWorkflow()}>
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
            </RowActions>
          </li>;
        })}
      </ul>
    )}
  </section>;
}
