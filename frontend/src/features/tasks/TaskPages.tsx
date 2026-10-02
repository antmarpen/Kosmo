import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { useTranslation } from "react-i18next";
import { api, authenticatedFetch } from "@/api/auth";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { KosmoErrorAlert, type KosmoError } from "@/components/KosmoErrorAlert";
import { RowActions, RowActionButton } from "@/components/RowActions";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import type { components } from "@/api/schema";
import { useTaskStream } from "./useTaskStream";

type Task = { id: string; state: string; workflow_id: string; workflow_name?: string; created_at: string; updated_at?: string; nodes?: any[]; node_executions?: any[]; notes?: any[]; artifacts?: any[] };
type TaskEvent = { event: string; data: Record<string, any> };

function unwrap<T>(result: { data?: T; error?: unknown }): T {
  if (result.error || result.data === undefined) throw result.error ?? new Error("Empty API response");
  return result.data;
}

/** Task states that accept the stop action (spec AC-08). */
const STOPPABLE_STATES = new Set(["running", "waiting_for_input"]);

function isStoppableState(state: string): boolean {
  return STOPPABLE_STATES.has(state);
}

function useTasks(taskId?: string) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState(false);
  const load = useCallback(async () => {
    try {
      const result = taskId
        ? await api.GET("/tasks/{task_id}", { params: { path: { task_id: taskId } } })
        : await api.GET("/tasks");
      setData(unwrap(result));
      setError(false);
    } catch { setError(true); }
  }, [taskId]);
  useEffect(() => { void load(); }, [load]);
  return { data, load, error, setData };
}

type TaskStopController = {
  /** Task id waiting for confirmation, if any. */
  confirmId: string | null;
  /** Task id with a stop request in flight, if any. */
  stoppingId: string | null;
  /** True when the last stop attempt failed. */
  error: boolean;
  /** Opens the confirmation dialog for a task. */
  request: (taskId: string) => void;
  /** Closes the dialog without sending anything. */
  cancel: () => void;
  /** Performs the confirmed stop for the pending task id. */
  confirm: () => void;
};

/**
 * Shared stop flow for the task list rows and the task detail page: one
 * controller owns the styled confirmation and the typed stop request so the
 * two surfaces cannot drift (spec AC-08/AC-16). `canStop` re-checks the
 * current task state right before sending, so a task that moved on (for
 * example through SSE) while the dialog was open is not stopped.
 */
function useTaskStop(onSettled: (taskId: string) => void | Promise<void>, canStop: (taskId: string) => boolean): TaskStopController {
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [stoppingId, setStoppingId] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const callbacks = useRef({ onSettled, canStop });
  callbacks.current = { onSettled, canStop };
  const request = useCallback((taskId: string) => { setError(false); setConfirmId(taskId); }, []);
  const cancel = useCallback(() => setConfirmId(null), []);
  const confirm = useCallback(() => {
    const taskId = confirmId;
    if (taskId === null || stoppingId !== null) return;
    if (!callbacks.current.canStop(taskId)) { setConfirmId(null); return; }
    setStoppingId(taskId);
    setError(false);
    void (async () => {
      try {
        unwrap(await api.POST("/tasks/{task_id}/stop", { params: { path: { task_id: taskId } } }));
        setConfirmId(null);
        await callbacks.current.onSettled(taskId);
      } catch {
        setError(true);
        setConfirmId(null);
      } finally {
        setStoppingId(null);
      }
    })();
  }, [confirmId, stoppingId]);
  return { confirmId, stoppingId, error, request, cancel, confirm };
}

/** Shared styled confirmation for stopping a task (spec AC-16). */
function StopTaskConfirmDialog({ stop }: { stop: TaskStopController }) {
  const { t } = useTranslation();
  return (
    <ConfirmDialog
      open={stop.confirmId !== null}
      onOpenChange={open => { if (!open) stop.cancel(); }}
      title={t("tasks.stop")}
      description={t("tasks.confirmStop")}
      confirmLabel={t("tasks.stop")}
      cancelLabel={t("common.cancel")}
      loading={stop.stoppingId !== null}
      onConfirm={stop.confirm}
    />
  );
}

function StateBadge({ state }: { state: string }) {
  const { t } = useTranslation();
  const tones: Record<string, string> = {
    success: "bg-emerald-50 text-emerald-800", failed: "bg-red-50 text-red-800",
    running: "bg-blue-50 text-blue-800", waiting_for_input: "bg-amber-50 text-amber-900",
    stopped: "bg-muted text-muted-foreground",
  };
  return <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${tones[state] ?? "bg-secondary text-secondary-foreground"}`}>{t(`task.state.${state}` as any)}</span>;
}

function TaskList({ rows, stop }: { rows: Task[]; stop: TaskStopController }) {
  const { t } = useTranslation();
  if (!rows.length) return <div className="mt-8 border-y border-border py-10"><h2 className="font-medium">{t("tasks.list.empty")}</h2><p className="mt-1 text-sm text-muted-foreground">{t("tasks.list.emptyDescription")}</p></div>;
  return (
    <ul className="mt-7 divide-y divide-border border-y border-border">
      {rows.map(task => (
        <li key={task.id} className="flex items-center justify-between gap-3 py-4">
          <Link to={`/tasks/${task.id}`} className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-3 hover:bg-muted/40">
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium">{task.workflow_name ?? task.workflow_id}</span>
              <span className="mt-1 block text-xs text-muted-foreground">{new Date(task.created_at).toLocaleString()}</span>
            </span>
            <StateBadge state={task.state}/>
          </Link>
          {isStoppableState(task.state) && (
            <RowActions>
              <RowActionButton icon="stop" label={t("tasks.stop")} onClick={() => stop.request(task.id)} />
            </RowActions>
          )}
        </li>
      ))}
    </ul>
  );
}

export function TaskListPage() {
  const { t } = useTranslation();
  const { data, load, error, setData } = useTasks();
  const latestData = useRef(data);
  latestData.current = data;
  const onEvent = useCallback((event: TaskEvent) => {
    if (event.event !== "task.state") return;
    const current = latestData.current;
    const rows: Task[] = Array.isArray(current) ? current : current?.items ?? [];
    const found = rows.some(task => task.id === event.data.task_id);
    if (!found) { void load(); return; }
    setData((old: any) => {
      const existing: Task[] = Array.isArray(old) ? old : old?.items ?? [];
      const updated = existing.map(task => task.id === event.data.task_id ? { ...task, state: event.data.state ?? task.state, updated_at: event.data.at } : task);
      return Array.isArray(old) ? updated : { ...old, items: updated };
    });
  }, [load, setData]);
  const rows: Task[] = Array.isArray(data) ? data : data?.items ?? [];
  useTaskStream(undefined, onEvent, load);
  const canStopRow = useCallback((taskId: string) => {
    const current = latestData.current;
    const currentRows: Task[] = Array.isArray(current) ? current : current?.items ?? [];
    const row = currentRows.find(item => item.id === taskId);
    return row !== undefined && isStoppableState(row.state);
  }, []);
  const stop = useTaskStop(load, canStopRow);
  return <section className="mx-auto w-full max-w-7xl flex-1 px-5 py-8 sm:px-8"><div className="flex flex-wrap items-end justify-between gap-4"><div><h1 className="text-2xl font-semibold tracking-tight">{t("tasks.list.title")}</h1><p className="mt-1 text-sm text-muted-foreground">{t("tasks.list.description")}</p></div><Button asChild><Link to="/tasks/new"><Icon name="add" />{t("common.add")}</Link></Button></div>{error&&<p role="alert" className="mt-6 text-sm text-destructive">{t("tasks.loadError")}</p>}{stop.error&&<p role="alert" className="mt-6 text-sm text-destructive">{t("errors.generic")}</p>}{!data&&!error?<p className="mt-8 text-sm text-muted-foreground">{t("tasks.loading")}</p>:<TaskList rows={rows} stop={stop}/>}<StopTaskConfirmDialog stop={stop}/></section>;
}

function NodeTimeline({ nodes }: { nodes: any[] }) {
  const { t } = useTranslation();
  if (!nodes.length) return <p className="mt-2 text-sm text-muted-foreground">{t("tasks.noNodes")}</p>;
  return <ol className="mt-3 divide-y divide-border border-y border-border">{nodes.map((node, index) => <li key={node.id ?? `${node.node_id}-${index}`} className="flex items-center justify-between gap-3 py-3"><div className="min-w-0"><div className="flex items-center justify-between gap-3"><span className="truncate text-sm">{node.node_id ?? node.name}</span><StateBadge state={node.state}/></div>{node.error?.message_key&&<p className="mt-1 break-words text-xs text-destructive" role="status">{t(node.error.message_key as any,node.error.params??{})}{node.error.params?.reason?` · ${node.error.params.reason}`:""}</p>}</div></li>)}</ol>;
}

function TaskNotes({ task }: { task: Task }) {
  const { t } = useTranslation();
  return <section><h2 className="text-base font-semibold">{t("tasks.notesTitle")}</h2><ul className="mt-3 space-y-3">{(task.notes??[]).map((note:any,index:number)=><li key={note.id??index} className="rounded-md bg-muted/60 px-3 py-3"><p className="text-sm">{t(note.message_key,note.params??{})}</p>{note.params?.details?.map((detail:any,detailIndex:number)=><p key={detailIndex} className="mt-2 break-words text-sm text-muted-foreground">{t(detail.message_key,detail.params??{})}{detail.artifact?` (${detail.artifact})`:""}</p>)}<time className="mt-1 block text-xs text-muted-foreground">{note.created_at?new Date(note.created_at).toLocaleString():""}</time></li>)}</ul></section>;
}

function TaskArtifacts({ taskId, artifacts = [] }: { taskId: string; artifacts?: any[] }) {
  const { t } = useTranslation();
  const [downloadError,setDownloadError]=useState(false);
  const download=async(artifact:any)=>{setDownloadError(false);let objectUrl:string|undefined;try{const response=await authenticatedFetch(`/api/tasks/${taskId}/artifacts/${artifact.id}/download`);if(!response.ok)throw new Error("Download failed");const blob=await response.blob();objectUrl=URL.createObjectURL(blob);const anchor=document.createElement("a");anchor.href=objectUrl;anchor.download=artifact.logical_name??artifact.id;document.body.appendChild(anchor);anchor.click();anchor.remove();}catch{setDownloadError(true);}finally{if(objectUrl)URL.revokeObjectURL(objectUrl);}};
  return <section><h2 className="text-base font-semibold">{t("tasks.artifacts")}</h2>{downloadError&&<p role="alert" className="mt-2 text-sm text-destructive">{t("tasks.artifactDownloadError")}</p>}<ul className="mt-3 space-y-2">{artifacts.map(artifact=><li key={artifact.id}><a className="text-sm text-primary underline underline-offset-4" href={`/api/tasks/${taskId}/artifacts/${artifact.id}/download`} onClick={event=>{event.preventDefault();void download(artifact);}}>{artifact.logical_name??artifact.id}</a></li>)}</ul>{!artifacts.length&&<p className="mt-2 text-sm text-muted-foreground">{t("tasks.noArtifacts")}</p>}</section>;
}

function pendingInput(task: Task) {
  const notes = task.notes ?? [];
  const note = [...notes].reverse().find((item: any) => item.message_key === "tasks.notes.input_requested" && item.params?.answer_recorded === false);
  return note?.params as { node_execution_id?: string; request_id?: string | number } | undefined;
}

function TaskInputForm({ task, answer, setAnswer, busy, onAnswer }: { task: Task; answer: string; setAnswer: (value: string) => void; busy: boolean; onAnswer: (body: object) => void }) {
  const { t } = useTranslation();
  const request = pendingInput(task);
  if (task.state !== "waiting_for_input") return null;
  return <form className="space-y-3 border-t border-border pt-5" onSubmit={event=>{event.preventDefault();if(request?.node_execution_id&&request.request_id!==undefined)onAnswer({answer,node_execution_id:request.node_execution_id,request_id:request.request_id});}}><label htmlFor="task-answer" className="text-sm font-medium">{t("tasks.answerLabel")}</label><Input id="task-answer" value={answer} onChange={event=>setAnswer(event.target.value)} required/><Button type="submit" loading={busy} disabled={!answer.trim()||!request?.node_execution_id||request.request_id===undefined} className="w-full"><Icon name="send" />{t("tasks.sendAnswer")}</Button></form>;
}

export function TaskDetailPage() {
  const { id = "" } = useParams();
  const { t } = useTranslation();
  const { data, load, error } = useTasks(id);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(false);
  const task: Task | undefined = data?.task ?? data;
  const latestTask = useRef<Task | undefined>(undefined);
  latestTask.current = task;
  useTaskStream(id,(event: TaskEvent)=>{if(["task.state","node.state","task.note"].includes(event.event))void load();},load);
  const canStopCurrent = useCallback((taskId: string) => {
    const current = latestTask.current;
    return current !== undefined && current.id === taskId && isStoppableState(current.state);
  }, []);
  const stop = useTaskStop(load, canStopCurrent);
  const submitAnswer = async (body: object) => {
    setBusy(true);
    setActionError(false);
    try {
      unwrap(await api.POST("/tasks/{task_id}/input",{params:{path:{task_id:id}},body:body as any}));
      setAnswer(""); await load();
    } catch { setActionError(true); } finally { setBusy(false); }
  };
  if(error&&!task)return <p role="alert" className="p-8">{t("tasks.loadError")}</p>;
  if(!task)return <p className="p-8">{t("tasks.loading")}</p>;
  const nodes=task.node_executions??task.nodes??[];
  return <section className="mx-auto w-full max-w-7xl flex-1 px-5 py-8 sm:px-8"><Link to="/tasks" className="text-sm text-muted-foreground hover:text-foreground">{t("tasks.back")}</Link><div className="mt-5 flex flex-wrap items-start justify-between gap-4"><div><h1 className="text-2xl font-semibold tracking-tight">{task.workflow_name??task.workflow_id}</h1><p className="mt-1 text-xs text-muted-foreground">{task.id}</p></div><div className="flex items-center gap-2"><StateBadge state={task.state}/>{isStoppableState(task.state)&&<Button variant="outline" loading={stop.stoppingId!==null} disabled={busy} onClick={()=>stop.request(id)}><Icon name="stop" />{t("tasks.stop")}</Button>}</div></div>{(actionError||stop.error)&&<p role="alert" className="mt-2 text-sm text-destructive">{t("errors.generic")}</p>}<div className="mt-8 grid gap-9 lg:grid-cols-[minmax(0,1fr)_18rem]"><div className="space-y-9"><section><h2 className="text-base font-semibold">{t("tasks.nodes")}</h2><NodeTimeline nodes={nodes}/></section><TaskNotes task={task}/></div><aside className="space-y-8"><TaskArtifacts taskId={id} artifacts={task.artifacts}/><TaskInputForm task={task} answer={answer} setAnswer={setAnswer} busy={busy} onAnswer={body=>void submitAnswer(body)}/></aside></div><StopTaskConfirmDialog stop={stop}/></section>;
}

type Workflow = components["schemas"]["WorkflowResponse"];

function toKosmoError(cause: unknown): KosmoError {
  // Backend error bodies are flat {code, message_key, params?, details?}.
  const raw = cause as Partial<KosmoError> | undefined;
  return raw && typeof raw.code === "string" && typeof raw.message_key === "string"
    ? { code: raw.code, message_key: raw.message_key, params: raw.params, details: raw.details }
    : { code: "TASK_CREATE_FAILED", message_key: "errors.generic" };
}

/** A workflow can only be launched while it has an active (published) version. */
function isLaunchable(workflow: Workflow): boolean {
  return workflow.active_version !== null && workflow.active_version !== undefined;
}

/** Name of the seeded reference workflow, used as the default preselection. */
const DEFAULT_WORKFLOW_NAME = "reference-security-analysis";

/**
 * Initial workflow selection for the new-task form: a launchable
 * `?workflowId=` deep link wins, then the workflow named
 * `reference-security-analysis`, then the first launchable row. Version-less
 * workflows are never selected; "" means nothing is launchable and the page
 * renders an empty state instead of the form.
 */
function resolveInitialWorkflowId(rows: Workflow[], requestedId: string | null): string {
  const launchable = rows.filter(isLaunchable);
  const requested = requestedId ? launchable.find(item => item.id === requestedId) : undefined;
  return (requested ?? launchable.find(item => item.name === DEFAULT_WORKFLOW_NAME) ?? launchable[0])?.id ?? "";
}

function WorkflowSummary({ workflow }: { workflow: Workflow | null }) {
  const { t } = useTranslation();
  return <aside className="h-fit border-t border-border pt-5 lg:border-t-0 lg:border-l lg:pl-6"><h2 className="text-sm font-semibold">{t("tasks.workflow")}</h2><p className="mt-2 text-sm">{workflow?.name??workflow?.id??t("tasks.loading")}</p><p className="mt-2 text-sm leading-6 text-muted-foreground">{t("tasks.workflowDescription")}</p></aside>;
}

export function NewTaskPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const requestedWorkflowId = searchParams.get("workflowId");
  const [workflows,setWorkflows]=useState<Workflow[] | null>(null);
  const [workflowId,setWorkflowId]=useState("");
  const [topic,setTopic]=useState("");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState<KosmoError | null>(null);
  const [loadError,setLoadError]=useState(false);
  const loaded = workflows !== null;
  const rows = workflows ?? [];
  const launchable = rows.filter(isLaunchable);
  const selectedWorkflow = launchable.find(item => item.id === workflowId) ?? null;
  useEffect(()=>{
    let cancelled=false;
    void (async()=>{
      try{
        const rows=unwrap(await api.GET("/workflows"));
        if(cancelled)return;
        setWorkflows(rows);
        setWorkflowId(resolveInitialWorkflowId(rows,requestedWorkflowId));
      }catch{ if(!cancelled) setLoadError(true); }
    })();
    return ()=>{cancelled=true;};
  },[requestedWorkflowId]);
  const submit=async(event:FormEvent)=>{
    event.preventDefault();
    if(!selectedWorkflow)return;
    setBusy(true);
    setError(null);
    try{
      const result=unwrap(await api.POST("/tasks",{body:{workflow_id:selectedWorkflow.id,input_values:{topic}}})) as {id:string};
      navigate(`/tasks/${result.id}`);
    }catch(cause){ setError(toKosmoError(cause)); } finally { setBusy(false); }
  };
  const selectClassName="mt-2 h-9 w-full min-w-0 rounded-lg border border-input bg-transparent px-3 py-1 text-base shadow-xs outline-none md:text-sm dark:bg-input/30 focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50";
  return <section className="mx-auto w-full max-w-7xl flex-1 px-5 py-8 sm:px-8"><Link to="/tasks" className="text-sm text-muted-foreground">{t("tasks.back")}</Link><h1 className="mt-5 text-2xl font-semibold tracking-tight">{t("tasks.new.title")}</h1><p className="mt-1 text-sm text-muted-foreground">{t("tasks.new.description")}</p><div className="mt-7 grid gap-8 lg:grid-cols-[minmax(0,1fr)_18rem]">
    {!loaded&&!loadError?<p role="status" className="text-sm text-muted-foreground">{t("tasks.loading")}</p>
    :loadError?<p role="alert" className="text-sm text-destructive">{t("tasks.loadError")}</p>
    :launchable.length===0?(
      <div className="h-fit rounded-lg border border-border bg-card px-5 py-8">
        <h2 className="font-medium">{t("tasks.new.noLaunchableWorkflows" as never)}</h2>
      </div>
    ):(
      <form onSubmit={submit} className="space-y-5">
        <div>
          <label htmlFor="workflow" className="text-sm font-medium">{t("tasks.workflow")}</label>
          <select id="workflow" value={workflowId} onChange={event=>setWorkflowId(event.target.value)} className={selectClassName}>
            {rows.map(workflow=>(
              <option key={workflow.id} value={workflow.id} disabled={!isLaunchable(workflow)}>
                {workflow.name}{isLaunchable(workflow)?"":` — ${t("workflows.list.noActiveVersion")}`}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="topic" className="text-sm font-medium">{t("tasks.topic")}</label>
          <Input id="topic" value={topic} onChange={event=>setTopic(event.target.value)} required className="mt-2" placeholder={t("tasks.topicPlaceholder")}/>
        </div>
        {error&&<KosmoErrorAlert error={error}/>}
        <Button type="submit" loading={busy} disabled={!selectedWorkflow||!topic.trim()}><Icon name="add" />{t("common.add")}</Button>
      </form>
    )}
    <WorkflowSummary workflow={selectedWorkflow}/>
  </div></section>;
}
