import { Navigate, useRoutes, type RouteObject } from "react-router";

import { AppShell } from "./AppShell";
import { NewTaskPage } from "@/features/tasks/TaskPages";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { LoginPage } from "@/features/auth/LoginPage";
import { RequireAuth } from "@/features/auth/AuthProvider";
import { TaskListPage, TaskDetailPage } from "@/features/tasks/TaskPages";
import { EditorPage } from "@/features/workflows/editor/EditorPage";
import { ProvidersPage } from "@/features/providers/ProvidersPage";
import { SkillsPage } from "@/features/skills/SkillsPage";
import { McpServersPage } from "@/features/mcp-servers/McpServersPage";
import { WorkflowListPage } from "@/features/workflows/WorkflowListPage";

export const appRoutes: RouteObject[] = [
  {
    // App frame: every future task view renders inside the shell.
    element: <RequireAuth><AppShell /></RequireAuth>,
    children: [
      { path: "/", element: <Navigate to="/tasks" replace /> },
      { path: "/tasks", element: <TaskListPage /> },
      { path: "/tasks/history", element: <PlaceholderPage /> },
      { path: "/tasks/:id", element: <TaskDetailPage /> },
      { path: "/tasks/new", element: <NewTaskPage /> },
      { path: "/workflows/:id/edit", element: <EditorPage /> },
      { path: "/workflows", element: <WorkflowListPage /> },
      { path: "/applications", element: <PlaceholderPage /> },
      { path: "/providers", element: <ProvidersPage /> },
      { path: "/admin/skills", element: <SkillsPage /> },
      { path: "/admin/mcps", element: <McpServersPage /> },
      { path: "*", element: <PlaceholderPage /> },
    ],
  },
  // Standalone full-screen page, outside the app frame.
  { path: "/login", element: <LoginPage /> },
];

/** Shared route tree: the app mounts it under BrowserRouter, tests under MemoryRouter. */
export function AppRoutes() {
  return useRoutes(appRoutes);
}
