import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useTranslation } from "react-i18next";
import { api, authenticatedFetch } from "@/api/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useTaskStream } from "./useTaskStream";

type Task = { id: string; state: string; workflow_id: string; workflow_name?: string; created_at: string; updated_at?: string; nodes?: any[]; node_executions?: any[]; notes?: any[]; artifacts?: any[] };
type TaskEvent = { event: string; data: Record<string, any> };

function unwrap<T>(result: { data?: T; error?: unknown }): T {
  if (result.error || result.data === undefined) throw result.error ?? new Error("Empty API response");
  return result.data;
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

function StateBadge({ state }: { state: string }) {
  const { t } = useTranslation();
  const tones: Record<string, string> = {
    success: "bg-emerald-50 text-emerald-800", failed: "bg-red-50 text-red-800",
    running: "bg-blue-50 text-blue-800", waiting_for_input: "bg-amber-50 text-amber-900",
    stopped: "bg-muted text-muted-foreground",
  };
  return <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${tones[state] ?? "bg-secondary text-secondary-foreground"}`}>{t(`task.state.${state}` as any)}</span>;
}

function TaskList({ rows }: { rows: Task[] }) {
  const { t } = useTranslation();
  if (!rows.length) return <div className="mt-8 border-y border-border py-10"><h2 className="font-medium">{t("tasks.list.empty")}</h2><p className="mt-1 text-sm text-muted-foreground">{t("tasks.list.emptyDescription")}</p></div>;
  return <ul className="mt-7 divide-y divide-border border-y border-border">{rows.map(task => <li key={task.id}><Link to={`/tasks/${task.id}`} className="flex flex-wrap items-center justify-between gap-3 py-4 hover:bg-muted/40"><span className="min-w-0"><span className="block truncate text-sm font-medium">{task.workflow_name ?? task.workflow_id}</span><span className="mt-1 block text-xs text-muted-foreground">{new Date(task.created_at).toLocaleString()}</span></span><StateBadge state={task.state}/></Link></li>)}</ul>;
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
  return <section className="mx-auto w-full max-w-5xl flex-1 px-5 py-8 sm:px-8"><div className="flex flex-wrap items-end justify-between gap-4"><div><h1 className="text-2xl font-semibold tracking-tight">{t("tasks.list.title")}</h1><p className="mt-1 text-sm text-muted-foreground">{t("tasks.list.description")}</p></div><Button asChild><Link to="/tasks/new">{t("tasks.new.submit")}</Link></Button></div>{error&&<p role="alert" className="mt-6 text-sm text-destructive">{t("tasks.loadError")}</p>}{!data&&!error?<p className="mt-8 text-sm text-muted-foreground">{t("tasks.loading")}</p>:<TaskList rows={rows}/>}</section>;
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
  return <form className="space-y-3 border-t border-border pt-5" onSubmit={event=>{event.preventDefault();if(request?.node_execution_id&&request.request_id!==undefined)onAnswer({answer,node_execution_id:request.node_execution_id,request_id:request.request_id});}}><label htmlFor="task-answer" className="text-sm font-medium">{t("tasks.answerLabel")}</label><Input id="task-answer" value={answer} onChange={event=>setAnswer(event.target.value)} required/><Button disabled={busy||!answer.trim()||!request?.node_execution_id||request.request_id===undefined} type="submit" className="w-full">{t("tasks.sendAnswer")}</Button></form>;
}

export function TaskDetailPage() {
  const { id = "" } = useParams();
  const { t } = useTranslation();
  const { data, load, error } = useTasks(id);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const task: Task | undefined = data?.task ?? data;
  useTaskStream(id,(event: TaskEvent)=>{if(["task.state","node.state","task.note"].includes(event.event))void load();},load);
  const action = async (kind: "input" | "stop", body?: object) => {
    setBusy(true);
    try {
      const result = kind === "input"
        ? await api.POST("/tasks/{task_id}/input",{params:{path:{task_id:id}},body:body as any})
        : await api.POST("/tasks/{task_id}/stop",{params:{path:{task_id:id}}});
      unwrap(result); setAnswer(""); await load();
    } finally { setBusy(false); }
  };
  if(error&&!task)return <p role="alert" className="p-8">{t("tasks.loadError")}</p>;
  if(!task)return <p className="p-8">{t("tasks.loading")}</p>;
  const nodes=task.node_executions??task.nodes??[];
  return <section className="mx-auto w-full max-w-5xl flex-1 px-5 py-8 sm:px-8"><Link to="/tasks" className="text-sm text-muted-foreground hover:text-foreground">{t("tasks.back")}</Link><div className="mt-5 flex flex-wrap items-start justify-between gap-4"><div><h1 className="text-2xl font-semibold tracking-tight">{task.workflow_name??task.workflow_id}</h1><p className="mt-1 text-xs text-muted-foreground">{task.id}</p></div><div className="flex items-center gap-2"><StateBadge state={task.state}/>{["running","waiting_for_input"].includes(task.state)&&<Button variant="outline" disabled={busy} onClick={()=>{if(window.confirm(t("tasks.confirmStop")))void action("stop");}}>{t("tasks.stop")}</Button>}</div></div><div className="mt-8 grid gap-9 lg:grid-cols-[minmax(0,1fr)_18rem]"><div className="space-y-9"><section><h2 className="text-base font-semibold">{t("tasks.nodes")}</h2><NodeTimeline nodes={nodes}/></section><TaskNotes task={task}/></div><aside className="space-y-8"><TaskArtifacts taskId={id} artifacts={task.artifacts}/><TaskInputForm task={task} answer={answer} setAnswer={setAnswer} busy={busy} onAnswer={body=>void action("input",body)}/></aside></div></section>;
}

function WorkflowSummary({ workflow }: { workflow: any }) {
  const { t } = useTranslation();
  return <aside className="h-fit border-t border-border pt-5 lg:border-t-0 lg:border-l lg:pl-6"><h2 className="text-sm font-semibold">{t("tasks.workflow")}</h2><p className="mt-2 text-sm">{workflow?.name??workflow?.id??t("tasks.loading")}</p><p className="mt-2 text-sm leading-6 text-muted-foreground">{workflow?.description??t("tasks.workflowDescription")}</p></aside>;
}

export function NewTaskPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [workflow,setWorkflow]=useState<any>(null);
  const [topic,setTopic]=useState("");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState(false);
  useEffect(()=>{void api.GET("/workflows").then(result=>{const data=unwrap(result) as any;const rows=Array.isArray(data)?data:data.items??[];setWorkflow(rows.find((item:any)=>item.id==="reference-security-analysis")??rows[0]);}).catch(()=>setError(true));},[]);
  const submit=async(event:FormEvent)=>{event.preventDefault();if(!workflow)return;setBusy(true);setError(false);try{const result=unwrap(await api.POST("/tasks",{body:{workflow_id:workflow.id,input_values:{topic}}}) as any) as any;navigate(`/tasks/${result.id}`);}catch{setError(true);}finally{setBusy(false);}};
  return <section className="mx-auto w-full max-w-5xl flex-1 px-5 py-8 sm:px-8"><Link to="/tasks" className="text-sm text-muted-foreground">{t("tasks.back")}</Link><h1 className="mt-5 text-2xl font-semibold tracking-tight">{t("tasks.new.title")}</h1><p className="mt-1 text-sm text-muted-foreground">{t("tasks.new.description")}</p><div className="mt-7 grid gap-8 lg:grid-cols-[minmax(0,1fr)_18rem]"><form onSubmit={submit} className="space-y-5"><div><label htmlFor="topic" className="text-sm font-medium">{t("tasks.topic")}</label><Input id="topic" value={topic} onChange={event=>setTopic(event.target.value)} required className="mt-2" placeholder={t("tasks.topicPlaceholder")}/></div>{error&&<p role="alert" className="text-sm text-destructive">{t("tasks.submitError")}</p>}<Button type="submit" disabled={!workflow||!topic.trim()||busy}>{busy?t("tasks.submitting"):t("tasks.new.submit")}</Button></form><WorkflowSummary workflow={workflow}/></div></section>;
}
