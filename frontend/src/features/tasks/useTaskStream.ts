import { useEffect, useRef } from "react";
import { authenticatedFetch } from "@/api/auth";

type TaskEvent = { id: string; event: string; data: Record<string, any> };
/** Fetch-based SSE supports Authorization headers and resumes with Last-Event-ID. */
export function useTaskStream(taskId: string | undefined, onEvent: (event: TaskEvent) => void, poll: () => void) {
  const callbacks = useRef({ onEvent, poll }); callbacks.current = { onEvent, poll };
  useEffect(() => {
    let stopped = false, failures = 0, lastId = "", controller: AbortController | undefined;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let pollTimer: ReturnType<typeof setInterval> | undefined;
    const reconnect = async () => {
      if (stopped) return;
      controller = new AbortController();
      try {
        const response = await authenticatedFetch(`/api/tasks${taskId ? `/${taskId}` : ""}/events`, { headers: lastId ? { "Last-Event-ID": lastId } : {}, signal: controller.signal });
        if (!response.ok || !response.body) throw new Error("Stream unavailable");
        failures = 0;
        if (pollTimer) { clearInterval(pollTimer); pollTimer = undefined; }
        const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = "", current: Partial<TaskEvent> = {};
        while (!stopped) {
          const { value, done } = await reader.read(); if (done) break;
          buffer += decoder.decode(value, { stream: true }); const lines = buffer.split(/\r?\n/); buffer = lines.pop() ?? "";
          for (const line of lines) {
            if (line.startsWith("id:")) current.id = line.slice(3).trim();
            else if (line.startsWith("event:")) current.event = line.slice(6).trim();
            else if (line.startsWith("data:")) { try { current.data = JSON.parse(line.slice(5)); } catch { continue; } }
            else if (!line && current.data) { if (current.id) lastId = current.id; callbacks.current.onEvent(current as TaskEvent); current = {}; }
          }
        }
        throw new Error("Stream ended");
      } catch { if (stopped) return; failures++; if (failures >= 3 && !pollTimer) pollTimer = setInterval(() => callbacks.current.poll(), 4000); retryTimer = setTimeout(reconnect, Math.min(1000 * 2 ** Math.min(failures, 5), 30000)); }
    };
    void reconnect(); return () => { stopped = true; controller?.abort(); if (retryTimer) clearTimeout(retryTimer); if (pollTimer) clearInterval(pollTimer); };
  }, [taskId]);
}
