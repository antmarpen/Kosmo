import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18next from "i18next";
import { AuthProvider } from "@/features/auth/AuthProvider";
import { setTokens } from "@/api/auth";
import { changeLanguage } from "@/i18n";
import { TaskDetailPage, TaskListPage, NewTaskPage } from "./TaskPages";

// jsdom does not implement ResizeObserver, which the Radix popper under the
// row-action tooltips measures with (same no-op stub as RowActions.test.tsx).
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

const stream = (event = "task.state", data = { task_id: "t1", state: "running" }) => new Response(new ReadableStream({ async start(controller) { await new Promise(resolve => setTimeout(resolve, 30)); controller.enqueue(new TextEncoder().encode(`id: 1\nevent: ${event}\ndata: ${JSON.stringify(data)}\n\n`)); controller.close(); } }), { status: 200 });
const emptyStream = () => new Response(new ReadableStream({ start(){} }));
function requestUrl(input: any) { return new URL(input instanceof Request ? input.url : String(input), "http://localhost").pathname; }
async function bodyOf(input: any) { return input instanceof Request ? input.clone().json() : undefined; }
function setup(path: string, fetcher: typeof fetch) { setTokens("test", "refresh"); globalThis.fetch = vi.fn(fetcher); return render(<AuthProvider><MemoryRouter initialEntries={[path]}><Routes><Route path="/tasks" element={<TaskListPage/>}/><Route path="/tasks/new" element={<NewTaskPage/>}/><Route path="/tasks/:id" element={<TaskDetailPage/>}/></Routes></MemoryRouter></AuthProvider>); }
const task = (state = "failed", notes: any[] = []) => ({ id:"t1",state,workflow_id:"reference-security-analysis",created_at:"2026-09-30T12:00:00Z",node_executions:[{id:"n1",node_id:"analyze",state,error:{code:"VALIDATION_EXHAUSTED",message_key:"errors.node.validation_exhausted",params:{attempts:3,node:"analyze"}}},{id:"n2",node_id:"runtime",state,error:{code:"AGENT_RUNTIME_FAILED",message_key:"errors.agent.runtime_failed",params:{reason:"RuntimeError"}}}],notes,artifacts:[] });
const inputRequest = [{ id:"input-request", message_key:"tasks.notes.input_requested", params:{ answer_recorded:false, node_execution_id:"node-exec-7", request_id:"request-9" } }];
/** WorkflowResponse fixtures: `active_version` is null until a version is published (backend/app/domain/workflows/schemas.py). The published definition carries the Start node's authored input_form (schema v1). */
const activeVersion = {
  id: "ver-1",
  version: 1,
  definition: {
    schema_version: "v1",
    name: "reference-security-analysis",
    nodes: [{ type: "start", id: "start", input_form: [{ name: "topic", type: "string", required: true, label_message_key: "tasks.topic" }] }],
    edges: [],
  },
};
const launchableWorkflow = (id: string, name: string) => ({ id, name, active_version: activeVersion });
const draftWorkflow = (id: string, name: string) => ({ id, name, active_version: null });
/** Resolves through i18next so assertions hold both before and after the pending catalog keys land. */
const catalogText = (key: string) => String(i18next.t(key as never));
beforeEach(() => { changeLanguage("en"); });

describe("task views",()=>{
  it("updates an existing task state from the authenticated SSE stream", async()=>{
    let listCalls=0;
    setup("/tasks",vi.fn(async(input:any)=>requestUrl(input)==="/api/tasks/events"?stream():new Response(JSON.stringify([ {...task(listCalls++===0?"queued":"running"),notes:[]} ]))));
    expect(await screen.findByText("Queued")).toBeInTheDocument();
    await screen.findByText("Running",{}, {timeout:3000});
  });
  it("never regresses the detail badge to a stale out-of-order response",async()=>{
    let eventCalls=0, detailCalls=0;
    const fetcher=vi.fn(async(input:any)=>{
      const path=requestUrl(input);
      // One SSE state event triggers a second load; the stream then stays open
      // (empty) so no further loads interfere with the race under test.
      if(path==="/api/tasks/t1/events")return eventCalls++===0?stream("task.state",{task_id:"t1",state:"failed"}):emptyStream();
      if(path==="/api/tasks/t1"){
        // Mount load is slow and carries the OLDER snapshot; the
        // SSE-triggered load resolves fast with the NEWER state. The slow
        // stale response must never overwrite the fresher badge.
        return detailCalls++===0
          ? new Promise<Response>(resolve=>setTimeout(()=>resolve(new Response(JSON.stringify({task:{...task("running"),notes:[]}}))),250))
          : new Response(JSON.stringify({task:{...task("failed"),notes:[]}}));
      }
      return new Response(JSON.stringify({task:{...task("failed"),notes:[]}}));
    });
    setup("/tasks/t1",fetcher);
    // The SSE-triggered load resolves fast with the fresh state; the slow
    // mount response (older snapshot) lands afterwards and must be ignored:
    // the badge must stay on the fresh state, never regress to the stale one.
    await new Promise(resolve=>setTimeout(resolve,600));
    expect(screen.getAllByText("Failed").length).toBeGreaterThan(0);
    expect(screen.queryAllByText("Running")).toHaveLength(0);
  });
  it("reconciles a state change missed across a normal stream close",async()=>{
    // Observed freeze (e2e phase1): the reload triggered by an event can race
    // the backend commit and still report the older state; the stream then
    // closes normally and the resumed connection has no new event to deliver
    // (the event id is already committed to Last-Event-ID). The reconnect
    // itself must reconcile, or the badge stays stale forever.
    let streamCalls=0, detailCalls=0;
    const fetcher=vi.fn(async(input:any)=>{
      const path=requestUrl(input);
      if(path==="/api/tasks/t1/events"){
        streamCalls++;
        // First connection delivers the state event, then closes normally.
        // The resumed connection stays open but has no event to replay.
        return streamCalls===1?stream("task.state",{task_id:"t1",state:"failed"}):emptyStream();
      }
      if(path==="/api/tasks/t1"){
        detailCalls++;
        // The event-triggered reload races the commit and still observes the
        // older state; only a reload fired after the reconnect sees "failed".
        return new Response(JSON.stringify({task:{...task(detailCalls<=2?"running":"failed"),notes:[]}}));
      }
      return new Response(JSON.stringify({task:{...task("failed"),notes:[]}}));
    });
    setup("/tasks/t1",fetcher);
    expect((await screen.findAllByText("Running")).length).toBeGreaterThan(0);
    await screen.findAllByText("Failed",{}, {timeout:4000});
    await waitFor(()=>expect(screen.queryAllByText("Running")).toHaveLength(0));
  });
  it("resumes with Last-Event-ID and applies events replayed after a normal close",async()=>{
    let streamCalls=0, detailCalls=0;
    const cursors:(string|null)[]=[];
    const gapEvent=new Response(new ReadableStream({async start(controller){await new Promise(resolve=>setTimeout(resolve,30));controller.enqueue(new TextEncoder().encode(`id: 2\nevent: task.state\ndata: ${JSON.stringify({task_id:"t1",state:"failed"})}\n\n`));}}),{status:200});
    const fetcher=vi.fn(async(input:any)=>{
      const path=requestUrl(input);
      if(path==="/api/tasks/t1/events"){
        streamCalls++;
        cursors.push(input instanceof Request?input.headers.get("Last-Event-ID"):null);
        return streamCalls===1?stream("task.state",{task_id:"t1",state:"running"}):gapEvent;
      }
      if(path==="/api/tasks/t1"){
        detailCalls++;
        return new Response(JSON.stringify({task:{...task(detailCalls<=2?"running":"failed"),notes:[]}}));
      }
      return new Response(JSON.stringify({task:{...task("failed"),notes:[]}}));
    });
    setup("/tasks/t1",fetcher);
    expect((await screen.findAllByText("Running")).length).toBeGreaterThan(0);
    await screen.findAllByText("Failed",{}, {timeout:4000});
    await waitFor(()=>expect(screen.queryAllByText("Running")).toHaveLength(0));
    expect(cursors[0]).toBeNull();
    expect(cursors[1]).toBe("1");
  });
  it("routes task-list 401 recovery through the shared refresh client",async()=>{
    let listAttempts=0;
    const fetcher=vi.fn(async(input:any)=>{
      const url=requestUrl(input);
      if(url==="/api/auth/refresh")return new Response(JSON.stringify({access_token:"renewed",refresh_token:"rotated"}),{status:200,headers:{"Content-Type":"application/json"}});
      if(url==="/api/tasks/events")return new Response(new ReadableStream({start(){}}),{status:200});
      if(url==="/api/tasks"&&listAttempts++===0)return new Response(null,{status:401});
      return new Response(JSON.stringify([]));
    });
    setup("/tasks",fetcher);
    await screen.findByText("No tasks yet");
    expect(fetcher.mock.calls.some(call=>requestUrl(call[0])==="/api/auth/refresh")).toBe(true);
    const retriedList=fetcher.mock.calls.filter(call=>requestUrl(call[0])==="/api/tasks").at(-1)![0] as Request;
    expect(retriedList.headers.get("Authorization")).toBe("Bearer renewed");
  });
  it("refetches to include a task created in another window",async()=>{
    let listCalls=0;
    setup("/tasks",vi.fn(async(input:any)=>requestUrl(input)==="/api/tasks/events"?stream("task.state",{task_id:"new-task",state:"running"}):new Response(JSON.stringify(listCalls++===0?[]:[{...task("running"),id:"new-task",workflow_name:"Other window run",notes:[]}]))));
    expect(await screen.findByText("Other window run")).toBeInTheDocument();
  });
  it("shows node progress and localized failure trail",async()=>{
    const attempts = [1,2,3].map(attempt=>({id:`note-${attempt}`,message_key:"tasks.notes.validation_failed",params:{attempt,level:"structure",details:[{message_key:"workflow.validation.required_sections",params:{reason:"required_sections_missing",sections:["Overview"]}}]}}));
    setup("/tasks/t1",vi.fn(async(input:any)=>requestUrl(input).endsWith("/events")?new Response(new ReadableStream({start(){}})):new Response(JSON.stringify({task:{...task("failed",attempts),error:undefined}}))));
    expect(await screen.findByText("Validation failed after 3 attempts for analyze.")).toBeInTheDocument();
    for (let attempt=1;attempt<=3;attempt++) expect(screen.getByText(`Validation failed on attempt ${attempt} (structure).`)).toBeInTheDocument();
    expect(screen.getAllByText(/Required sections are missing/)).toHaveLength(3);
    expect(screen.getByText("Agent runtime failed. · RuntimeError")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/Traceback|stacktrace/i);
    changeLanguage("es");
    expect(await screen.findByText("La validación falló en el intento 1 (structure)." )).toBeInTheDocument();
    expect(screen.getAllByText(/Faltan secciones obligatorias/)).toHaveLength(3);
  });
  it("downloads artifacts with the authenticated transport and revokes the object URL",async()=>{
    const blob=new Blob(["artifact"]); const create=vi.spyOn(URL,"createObjectURL").mockReturnValue("blob:artifact"); const revoke=vi.spyOn(URL,"revokeObjectURL");
    let downloadAttempts=0;
    const fetcher=vi.fn(async(input:any)=>{
      const path=requestUrl(input);
      if(path.endsWith("/events")) return new Response(new ReadableStream({start(){}}));
      if(path==="/api/auth/refresh") return new Response(JSON.stringify({access_token:"renewed",refresh_token:"rotated"}),{status:200,headers:{"Content-Type":"application/json"}});
      if(path.endsWith("/download")) return downloadAttempts++===0?new Response(null,{status:401}):new Response(blob,{status:200});
      return new Response(JSON.stringify({task:{...task(),notes:[],artifacts:[{id:"a1",logical_name:"report.md"}]}}));
    });
    setup("/tasks/t1",fetcher);
    create.mockImplementation(()=>"blob:artifact"); const click=vi.spyOn(HTMLAnchorElement.prototype,"click").mockImplementation(()=>{});
    await userEvent.setup().click(await screen.findByRole("link",{name:"report.md"}));
    await waitFor(()=>expect(fetcher.mock.calls.some(call=>requestUrl(call[0])==="/api/tasks/t1/artifacts/a1/download")).toBe(true));
    await waitFor(()=>expect(fetcher.mock.calls.filter(call=>requestUrl(call[0])==="/api/tasks/t1/artifacts/a1/download")).toHaveLength(2));
    expect(fetcher.mock.calls.some(call=>requestUrl(call[0])==="/api/auth/refresh")).toBe(true);
    expect(create).toHaveBeenCalledWith(blob); expect(click).toHaveBeenCalled(); expect(revoke).toHaveBeenCalledWith("blob:artifact");
    create.mockRestore(); revoke.mockRestore(); click.mockRestore();
  });
  it("shows a localized artifact download failure",async()=>{
    setup("/tasks/t1",vi.fn(async(input:any)=>requestUrl(input).endsWith("/events")?new Response(new ReadableStream({start(){}})):requestUrl(input).endsWith("/download")?new Response(null,{status:403}):new Response(JSON.stringify({task:{...task(),notes:[],artifacts:[{id:"a1",logical_name:"report.md"}]}}))));
    await userEvent.setup().click(await screen.findByRole("link",{name:"report.md"}));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not download this artifact.");
  });
  it("submits creation through the typed API and navigates to detail",async()=>{
    const user=userEvent.setup();
    const fetcher=vi.fn(async(input:any)=>requestUrl(input)==="/api/workflows"?new Response(JSON.stringify([{id:"reference-security-analysis",name:"Security analysis",active_version:activeVersion}])):requestUrl(input)==="/api/tasks"?new Response(JSON.stringify({id:"t1",state:"queued"}),{status:201}):new Response(JSON.stringify({task:{...task("queued"),notes:[]}})));
    setup("/tasks/new",fetcher);
    await user.type(await screen.findByLabelText("topic"),"smoke");
    await user.click(screen.getByRole("button",{name:"Add"}));
    await screen.findByText("reference-security-analysis");
    await waitFor(async()=>expect(await bodyOf(fetcher.mock.calls.find(call=>requestUrl(call[0])==="/api/tasks")![0])).toEqual({workflow_id:"reference-security-analysis",input_values:{topic:"smoke"}}));
  });
  it("renders the authored start input_form and submits typed values",async()=>{
    const user=userEvent.setup();
    const inputForm=[
      {name:"topic",type:"string",required:true,label_message_key:"tasks.topic"},
      {name:"retries",type:"number",required:true,label_message_key:"tasks.nodes"},
      {name:"verbose",type:"boolean",required:false,label_message_key:"tasks.artifacts"},
    ];
    const fetcher=vi.fn(async(input:any)=>{
      const path=requestUrl(input);
      if(path==="/api/workflows")return new Response(JSON.stringify([{id:"wf-form",name:"Form flow",active_version:{id:"ver-1",version:1,definition:{schema_version:"v1",name:"Form flow",nodes:[{type:"start",id:"start",input_form:inputForm}],edges:[]}}}]));
      if(path==="/api/tasks")return new Response(JSON.stringify({id:"t1",state:"queued"}),{status:201});
      return new Response(JSON.stringify({task:{...task("queued"),notes:[]}}));
    });
    setup("/tasks/new",fetcher);
    expect(await screen.findByLabelText("topic")).toBeInTheDocument();
    await user.type(screen.getByLabelText("topic"),"smoke");
    await user.type(screen.getByLabelText("retries"),"3");
    await user.click(screen.getByLabelText("verbose"));
    await user.click(screen.getByRole("button",{name:"Add"}));
    await waitFor(async()=>expect(await bodyOf(fetcher.mock.calls.find(call=>requestUrl(call[0])==="/api/tasks")![0])).toEqual({workflow_id:"wf-form",input_values:{topic:"smoke",retries:3,verbose:true}}));
  });
  it("labels the list creation action with the generic add key and a leading icon",async()=>{
    setup("/tasks",vi.fn(async(input:any)=>requestUrl(input).endsWith("/events")?emptyStream():new Response(JSON.stringify([{...task("queued"),notes:[]}]))));
    const add=await screen.findByRole("link",{name:"Add"});
    expect(add).toHaveAttribute("href","/tasks/new");
    expect(add.querySelector('[data-slot="icon"]')).toHaveAttribute("aria-hidden","true");
  });
  it("labels the new-task submit with the generic add key and a leading icon",async()=>{
    const user=userEvent.setup();
    setup("/tasks/new",vi.fn(async(input:any)=>requestUrl(input)==="/api/workflows"?new Response(JSON.stringify([{id:"reference-security-analysis",name:"Security analysis",active_version:activeVersion}])):new Response(JSON.stringify({task:{...task("queued"),notes:[]}}))));
    const button=await screen.findByRole("button",{name:"Add"});
    await user.type(await screen.findByLabelText("topic"),"smoke");
    await waitFor(()=>expect(button).toBeEnabled());
    expect(button.querySelector('[data-slot="icon"]')).toHaveAttribute("aria-hidden","true");
  });
  it("keeps the submit label, disables, and marks aria-busy while the task is being created",async()=>{
    const user=userEvent.setup();
    let resolveTask:(value:Response)=>void=()=>undefined;
    const fetcher=vi.fn(async(input:any)=>{
      const path=requestUrl(input);
      if(path==="/api/workflows")return new Response(JSON.stringify([{id:"reference-security-analysis",name:"Security analysis",active_version:activeVersion}]));
      if(path==="/api/tasks")return new Promise<Response>(resolve=>{resolveTask=resolve;});
      return new Response(JSON.stringify({task:{...task("queued"),notes:[]}}));
    });
    setup("/tasks/new",fetcher);
    await user.type(await screen.findByLabelText("topic"),"smoke");
    const button=await screen.findByRole("button",{name:"Add"});
    await waitFor(()=>expect(button).toBeEnabled());
    await user.click(button);
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy","true");
    expect(button).toHaveTextContent("Add");
    expect(button.textContent).not.toContain("Creating");
    resolveTask(new Response(JSON.stringify({id:"t1",state:"queued"}),{status:201}));
    await screen.findByText("reference-security-analysis");
  });
  it("answers a waiting task with the event correlation identifiers",async()=>{
    const user=userEvent.setup();
    const fetcher=vi.fn(async(input:any)=>requestUrl(input).endsWith("/events")?new Response(new ReadableStream({start(){}})):new Response(JSON.stringify({task:task("waiting_for_input",inputRequest)})));
    setup("/tasks/t1",fetcher);
    await user.type(await screen.findByLabelText("Your answer"),"Proceed");
    await user.click(screen.getByRole("button",{name:"Send answer"}));
    await waitFor(async()=>{const call=fetcher.mock.calls.find(item=>requestUrl(item[0])==="/api/tasks/t1/input");expect(call).toBeDefined();expect(await bodyOf(call![0])).toEqual({answer:"Proceed",node_execution_id:"node-exec-7",request_id:"request-9"});});
  });
  it("keeps the send-answer label, disables, and marks aria-busy while the answer is in flight",async()=>{
    const user=userEvent.setup();
    let resolveInput:(value:Response)=>void=()=>undefined;
    const fetcher=vi.fn(async(input:any)=>{
      const path=requestUrl(input);
      if(path.endsWith("/events"))return emptyStream();
      if(path==="/api/tasks/t1/input")return new Promise<Response>(resolve=>{resolveInput=resolve;});
      return new Response(JSON.stringify({task:task("waiting_for_input",inputRequest)}));
    });
    setup("/tasks/t1",fetcher);
    await user.type(await screen.findByLabelText("Your answer"),"Proceed");
    await user.click(screen.getByRole("button",{name:"Send answer"}));
    const button=screen.getByRole("button",{name:"Send answer"});
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy","true");
    expect(button).toHaveTextContent("Send answer");
    resolveInput(new Response("{}",{status:200,headers:{"Content-Type":"application/json"}}));
    expect(await screen.findByLabelText("Your answer")).toHaveValue("");
  });
  it("shows a localized error and re-enables Send answer when the answer fails",async()=>{
    const user=userEvent.setup();
    const fetcher=vi.fn(async(input:any)=>{
      const path=requestUrl(input);
      if(path.endsWith("/events"))return emptyStream();
      if(path==="/api/tasks/t1/input")return new Response(null,{status:500});
      return new Response(JSON.stringify({task:task("waiting_for_input",inputRequest)}));
    });
    setup("/tasks/t1",fetcher);
    await user.type(await screen.findByLabelText("Your answer"),"Proceed");
    await user.click(screen.getByRole("button",{name:"Send answer"}));
    expect(await screen.findByRole("alert")).toHaveTextContent("An unexpected error occurred.");
    expect(screen.getByRole("button",{name:"Send answer"})).toBeEnabled();
    expect(screen.getByLabelText("Your answer")).toHaveValue("Proceed");
  });
  it("offers the row Stop action only while the task is stoppable",async()=>{
    const queued=setup("/tasks",vi.fn(async(input:any)=>requestUrl(input).endsWith("/events")?emptyStream():new Response(JSON.stringify([{...task("queued"),notes:[]}]))));
    expect(await screen.findByText("Queued")).toBeInTheDocument();
    expect(screen.queryByRole("button",{name:"Stop task"})).not.toBeInTheDocument();
    queued.unmount();
    const running=setup("/tasks",vi.fn(async(input:any)=>requestUrl(input).endsWith("/events")?emptyStream():new Response(JSON.stringify([{...task("running"),notes:[]}]))));
    expect(await screen.findByText("Running")).toBeInTheDocument();
    expect(screen.getByRole("button",{name:"Stop task"})).toBeInTheDocument();
    running.unmount();
  });
  it("keeps the row navigation link and the row Stop action as siblings",async()=>{
    const fetcher=vi.fn(async(input:any)=>requestUrl(input).endsWith("/events")?emptyStream():new Response(JSON.stringify([{...task("running"),notes:[]}])));
    const user=userEvent.setup();
    setup("/tasks",fetcher);
    const link=await screen.findByRole("link",{name:/reference-security-analysis/});
    const row=link.closest("li");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getAllByRole("link")).toHaveLength(1);
    const stop=within(row as HTMLElement).getByRole("button",{name:"Stop task"});
    expect(within(link).queryByRole("button")).not.toBeInTheDocument();
    await user.click(stop);
    // The dialog is owned by the list page: it staying open proves the click
    // did not navigate through the row link.
    expect(await screen.findByRole("alertdialog",{name:"Stop task"})).toBeInTheDocument();
  });
  it("cancels the row stop without sending a request",async()=>{
    const confirm=vi.spyOn(window,"confirm");
    const fetcher=vi.fn(async(input:any)=>requestUrl(input).endsWith("/events")?emptyStream():new Response(JSON.stringify([{...task("running"),notes:[]}])));
    const user=userEvent.setup();
    setup("/tasks",fetcher);
    await user.click(await screen.findByRole("button",{name:"Stop task"}));
    await user.click(await screen.findByRole("button",{name:"Close"}));
    await waitFor(()=>expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(fetcher.mock.calls.some(call=>requestUrl(call[0]).endsWith("/stop"))).toBe(false);
    expect(confirm).not.toHaveBeenCalled();
    confirm.mockRestore();
  });
  it("dismisses the row stop with Escape without sending a request",async()=>{
    const confirm=vi.spyOn(window,"confirm");
    const fetcher=vi.fn(async(input:any)=>requestUrl(input).endsWith("/events")?emptyStream():new Response(JSON.stringify([{...task("running"),notes:[]}])));
    const user=userEvent.setup();
    setup("/tasks",fetcher);
    await user.click(await screen.findByRole("button",{name:"Stop task"}));
    expect(await screen.findByRole("alertdialog",{name:"Stop task"})).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(()=>expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(fetcher.mock.calls.some(call=>requestUrl(call[0]).endsWith("/stop"))).toBe(false);
    expect(confirm).not.toHaveBeenCalled();
    confirm.mockRestore();
  });
  it("confirms the row stop for the exact task id",async()=>{
    const confirm=vi.spyOn(window,"confirm");
    const fetcher=vi.fn(async(input:any)=>{
      const path=requestUrl(input);
      if(path.endsWith("/events"))return emptyStream();
      if(path.endsWith("/stop"))return new Response("{}",{status:200,headers:{"Content-Type":"application/json"}});
      return new Response(JSON.stringify([{...task("running"),notes:[]},{...task("running"),id:"t2",workflow_id:"reference-other",notes:[]}]));
    });
    const user=userEvent.setup();
    setup("/tasks",fetcher);
    const stops=await screen.findAllByRole("button",{name:"Stop task"});
    await user.click(stops[1]);
    const dialog=await screen.findByRole("alertdialog",{name:"Stop task"});
    await user.click(within(dialog).getByRole("button",{name:"Stop task"}));
    await waitFor(()=>expect(fetcher.mock.calls.some(call=>requestUrl(call[0])==="/api/tasks/t2/stop")).toBe(true));
    expect(fetcher.mock.calls.some(call=>requestUrl(call[0])==="/api/tasks/t1/stop")).toBe(false);
    expect(confirm).not.toHaveBeenCalled();
    confirm.mockRestore();
  });
  it("rechecks the row state and skips the stop when the task finished while confirming",async()=>{
    // The SSE event is delayed so the dialog is asserted open before the row
    // updates; the shared stream() helper fires at 30ms, which can unmount
    // the row button mid-click.
    const delayedStopEvent=new Response(new ReadableStream({async start(controller){await new Promise(resolve=>setTimeout(resolve,300));controller.enqueue(new TextEncoder().encode(`id: 1\nevent: task.state\ndata: ${JSON.stringify({task_id:"t1",state:"stopped"})}\n\n`));controller.close();}}),{status:200});
    const fetcher=vi.fn(async(input:any)=>requestUrl(input).endsWith("/events")?delayedStopEvent:new Response(JSON.stringify([{...task("running"),notes:[]}])));
    const user=userEvent.setup();
    setup("/tasks",fetcher);
    await user.click(await screen.findByRole("button",{name:"Stop task"}));
    expect(await screen.findByRole("alertdialog",{name:"Stop task"})).toBeInTheDocument();
    // SSE marks the row stopped while the confirmation is open.
    expect(await screen.findByText("Stopped")).toBeInTheDocument();
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button",{name:"Stop task"}));
    await waitFor(()=>expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(fetcher.mock.calls.some(call=>requestUrl(call[0]).endsWith("/stop"))).toBe(false);
  });
  it("confirms a detail stop through the styled dialog and posts through the typed API",async()=>{
    const confirm=vi.spyOn(window,"confirm");
    const fetcher=vi.fn(async(input:any)=>{
      const path=requestUrl(input);
      if(path.endsWith("/events"))return emptyStream();
      if(path.endsWith("/stop"))return new Response("{}",{status:200,headers:{"Content-Type":"application/json"}});
      return new Response(JSON.stringify({task:{...task("running"),notes:[]}}));
    });
    const user=userEvent.setup();
    setup("/tasks/t1",fetcher);
    await user.click(await screen.findByRole("button",{name:"Stop task"}));
    const dialog=await screen.findByRole("alertdialog",{name:"Stop task"});
    expect(dialog).toHaveTextContent("Stop this task?");
    await user.click(within(dialog).getByRole("button",{name:"Stop task"}));
    await waitFor(()=>expect(fetcher.mock.calls.some(call=>requestUrl(call[0])==="/api/tasks/t1/stop")).toBe(true));
    await waitFor(()=>expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(confirm).not.toHaveBeenCalled();
    confirm.mockRestore();
  });
  it("shows a localized error and re-enables Stop after a failed stop",async()=>{
    const fetcher=vi.fn(async(input:any)=>{
      const path=requestUrl(input);
      if(path.endsWith("/events"))return emptyStream();
      if(path.endsWith("/stop"))return new Response(null,{status:500});
      return new Response(JSON.stringify({task:{...task("running"),notes:[]}}));
    });
    const user=userEvent.setup();
    setup("/tasks/t1",fetcher);
    await user.click(await screen.findByRole("button",{name:"Stop task"}));
    await user.click(within(await screen.findByRole("alertdialog")).getByRole("button",{name:"Stop task"}));
    expect(await screen.findByRole("alert")).toHaveTextContent("An unexpected error occurred.");
    await waitFor(()=>expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(screen.getByRole("button",{name:"Stop task"})).toBeEnabled();
  });
  describe("new task workflow selection",()=>{
    it("preselects the launchable workflow named reference-security-analysis and submits its id",async()=>{
      const user=userEvent.setup();
      const fetcher=vi.fn(async(input:any)=>{
        const path=requestUrl(input);
        if(path==="/api/workflows")return new Response(JSON.stringify([launchableWorkflow("wf-other","Other flow"),launchableWorkflow("wf-ref","reference-security-analysis")]));
        if(path==="/api/tasks")return new Response(JSON.stringify({id:"t1",state:"queued"}),{status:201});
        return new Response(JSON.stringify({task:{...task("queued"),notes:[]}}));
      });
      setup("/tasks/new",fetcher);
      expect(await screen.findByLabelText("Workflow")).toHaveValue("wf-ref");
      await user.type(await screen.findByLabelText("topic"),"smoke");
      await user.click(screen.getByRole("button",{name:"Add"}));
      await waitFor(async()=>expect(await bodyOf(fetcher.mock.calls.find(call=>requestUrl(call[0])==="/api/tasks")![0])).toEqual({workflow_id:"wf-ref",input_values:{topic:"smoke"}}));
    });
    it("keeps version-less workflows unselectable and defaults to the first launchable one",async()=>{
      const fetcher=vi.fn(async(input:any)=>requestUrl(input)==="/api/workflows"?new Response(JSON.stringify([draftWorkflow("wf-draft","Draft flow"),launchableWorkflow("wf-live","Live flow")])):new Response(JSON.stringify({task:{...task("queued"),notes:[]}})));
      setup("/tasks/new",fetcher);
      const select=await screen.findByLabelText("Workflow");
      expect(select).toHaveValue("wf-live");
      const draft=within(select).getByRole("option",{name:/Draft flow/});
      expect(draft).toBeDisabled();
      expect(draft).toHaveTextContent("No active version");
    });
    it("honors a valid workflowId preselection from the URL",async()=>{
      const fetcher=vi.fn(async(input:any)=>requestUrl(input)==="/api/workflows"?new Response(JSON.stringify([launchableWorkflow("wf-a","First flow"),launchableWorkflow("wf-b","Second flow")])):new Response(JSON.stringify({task:{...task("queued"),notes:[]}})));
      setup("/tasks/new?workflowId=wf-b",fetcher);
      expect(await screen.findByLabelText("Workflow")).toHaveValue("wf-b");
    });
    it("ignores unknown and version-less workflowId preselections",async()=>{
      const fetcher=vi.fn(async(input:any)=>requestUrl(input)==="/api/workflows"?new Response(JSON.stringify([draftWorkflow("wf-draft","Draft flow"),launchableWorkflow("wf-live","Live flow")])):new Response(JSON.stringify({task:{...task("queued"),notes:[]}})));
      const unknown=setup("/tasks/new?workflowId=does-not-exist",fetcher);
      expect(await screen.findByLabelText("Workflow")).toHaveValue("wf-live");
      unknown.unmount();
      const versionless=setup("/tasks/new?workflowId=wf-draft",fetcher);
      expect(await screen.findByLabelText("Workflow")).toHaveValue("wf-live");
      versionless.unmount();
    });
    it("shows an empty state without a submit when no workflow can be launched",async()=>{
      const fetcher=vi.fn(async(input:any)=>requestUrl(input)==="/api/workflows"?new Response(JSON.stringify([draftWorkflow("wf-draft","Draft flow")])):new Response(JSON.stringify({task:{...task("queued"),notes:[]}})));
      setup("/tasks/new",fetcher);
      expect(await screen.findByRole("heading",{name:catalogText("tasks.new.noLaunchableWorkflows")})).toBeInTheDocument();
      expect(screen.queryByRole("button",{name:"Add"})).not.toBeInTheDocument();
      expect(screen.queryByLabelText("topic")).not.toBeInTheDocument();
    });
    it("renders the backend workflow-not-found error instead of the generic submit failure",async()=>{
      const user=userEvent.setup();
      const fetcher=vi.fn(async(input:any)=>{
        const path=requestUrl(input);
        if(path==="/api/workflows")return new Response(JSON.stringify([launchableWorkflow("wf-ref","reference-security-analysis")]));
        if(path==="/api/tasks")return new Response(JSON.stringify({code:"NOT_FOUND",message_key:"errors.workflow.not_found",params:{},details:[]}),{status:404,headers:{"Content-Type":"application/json"}});
        return new Response(JSON.stringify({task:{...task("queued"),notes:[]}}));
      });
      setup("/tasks/new",fetcher);
      await user.type(await screen.findByLabelText("topic"),"smoke");
      await user.click(await screen.findByRole("button",{name:"Add"}));
      expect(await screen.findByRole("alert")).toHaveTextContent("Workflow not found.");
      expect(screen.queryByText("Could not create the task. Please try again.")).not.toBeInTheDocument();
      expect(screen.getByRole("button",{name:"Add"})).toBeEnabled();
    });
    it("keeps the generic fallback for non-Kosmo submission failures",async()=>{
      const user=userEvent.setup();
      const fetcher=vi.fn(async(input:any)=>{
        const path=requestUrl(input);
        if(path==="/api/workflows")return new Response(JSON.stringify([launchableWorkflow("wf-ref","reference-security-analysis")]));
        if(path==="/api/tasks")return new Response(JSON.stringify({unexpected:true}),{status:500,headers:{"Content-Type":"application/json"}});
        return new Response(JSON.stringify({task:{...task("queued"),notes:[]}}));
      });
      setup("/tasks/new",fetcher);
      await user.type(await screen.findByLabelText("topic"),"smoke");
      await user.click(await screen.findByRole("button",{name:"Add"}));
      expect(await screen.findByRole("alert")).toHaveTextContent("An unexpected error occurred.");
    });
  });
});
