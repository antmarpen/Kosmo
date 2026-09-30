import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "@/features/auth/AuthProvider";
import { setTokens } from "@/api/auth";
import { changeLanguage } from "@/i18n";
import { TaskDetailPage, TaskListPage, NewTaskPage } from "./TaskPages";

const stream = (event = "task.state", data = { task_id: "t1", state: "running" }) => new Response(new ReadableStream({ async start(controller) { await new Promise(resolve => setTimeout(resolve, 30)); controller.enqueue(new TextEncoder().encode(`id: 1\nevent: ${event}\ndata: ${JSON.stringify(data)}\n\n`)); controller.close(); } }), { status: 200 });
function requestUrl(input: any) { return new URL(input instanceof Request ? input.url : String(input), "http://localhost").pathname; }
async function bodyOf(input: any) { return input instanceof Request ? input.clone().json() : undefined; }
function setup(path: string, fetcher: typeof fetch) { setTokens("test", "refresh"); globalThis.fetch = vi.fn(fetcher); return render(<AuthProvider><MemoryRouter initialEntries={[path]}><Routes><Route path="/tasks" element={<TaskListPage/>}/><Route path="/tasks/new" element={<NewTaskPage/>}/><Route path="/tasks/:id" element={<TaskDetailPage/>}/></Routes></MemoryRouter></AuthProvider>); }
const task = (state = "failed", notes: any[] = []) => ({ id:"t1",state,workflow_id:"reference-security-analysis",created_at:"2026-09-30T12:00:00Z",node_executions:[{id:"n1",node_id:"analyze",state,error:{code:"VALIDATION_EXHAUSTED",message_key:"errors.node.validation_exhausted",params:{attempts:3,node:"analyze"}}},{id:"n2",node_id:"runtime",state,error:{code:"AGENT_RUNTIME_FAILED",message_key:"errors.agent.runtime_failed",params:{reason:"RuntimeError"}}}],notes,artifacts:[] });
beforeEach(() => { changeLanguage("en"); });

describe("task views",()=>{
  it("updates an existing task state from the authenticated SSE stream", async()=>{
    let listCalls=0;
    setup("/tasks",vi.fn(async(input:any)=>requestUrl(input)==="/api/tasks/events"?stream():new Response(JSON.stringify([ {...task(listCalls++===0?"queued":"running"),notes:[]} ]))));
    expect(await screen.findByText("Queued")).toBeInTheDocument();
    await screen.findByText("Running",{}, {timeout:3000});
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
    const fetcher=vi.fn(async(input:any)=>requestUrl(input)==="/api/workflows"?new Response(JSON.stringify([{id:"reference-security-analysis",name:"Security analysis"}])):requestUrl(input)==="/api/tasks"?new Response(JSON.stringify({id:"t1",state:"queued"}),{status:201}):new Response(JSON.stringify({task:{...task("queued"),notes:[]}})));
    setup("/tasks/new",fetcher);
    await user.type(await screen.findByLabelText("Analysis topic"),"smoke");
    await user.click(screen.getByRole("button",{name:"Create task"}));
    await screen.findByText("reference-security-analysis");
    await waitFor(async()=>expect(await bodyOf(fetcher.mock.calls.find(call=>requestUrl(call[0])==="/api/tasks")![0])).toEqual({workflow_id:"reference-security-analysis",input_values:{topic:"smoke"}}));
  });
  it("answers a waiting task with the event correlation identifiers",async()=>{
    const user=userEvent.setup();
    const pending=[{id:"input-request",message_key:"tasks.notes.input_requested",params:{answer_recorded:false,node_execution_id:"node-exec-7",request_id:"request-9"}}];
    const fetcher=vi.fn(async(input:any)=>requestUrl(input).endsWith("/events")?new Response(new ReadableStream({start(){}})):new Response(JSON.stringify({task:task("waiting_for_input",pending)})));
    setup("/tasks/t1",fetcher);
    await user.type(await screen.findByLabelText("Your answer"),"Proceed");
    await user.click(screen.getByRole("button",{name:"Send answer"}));
    await waitFor(async()=>{const call=fetcher.mock.calls.find(item=>requestUrl(item[0])==="/api/tasks/t1/input");expect(call).toBeDefined();expect(await bodyOf(call![0])).toEqual({answer:"Proceed",node_execution_id:"node-exec-7",request_id:"request-9"});});
  });
  it("confirms then posts stop through the typed API",async()=>{
    const confirm=vi.spyOn(window,"confirm").mockReturnValue(true);
    const fetcher=vi.fn(async(input:any)=>requestUrl(input).endsWith("/events")?new Response(new ReadableStream({start(){}})):new Response(JSON.stringify({task:{...task("running"),notes:[]}})));
    const user=userEvent.setup();setup("/tasks/t1",fetcher);
    await user.click(await screen.findByRole("button",{name:"Stop task"}));
    expect(confirm).toHaveBeenCalled();
    await waitFor(()=>expect(fetcher.mock.calls.some(call=>requestUrl(call[0])==="/api/tasks/t1/stop")).toBe(true));
    confirm.mockRestore();
  });
});
