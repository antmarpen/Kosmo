import { api } from "@/api/auth";
import type { AgentCatalogEntry, McpCatalogEntry, McpCatalogListEntry, SkillCatalogEntry } from "./catalogTypes";

async function requireData<T>(result: { data?: T; error?: unknown }): Promise<T> {
  if (result.error !== undefined) throw result.error;
  if (result.data === undefined) throw new Error("Catalog request returned no data");
  return result.data;
}

export async function fetchAgents(): Promise<AgentCatalogEntry[]> { return requireData(await api.GET("/agents")); }
export async function fetchAgent(id: string): Promise<AgentCatalogEntry> { return requireData(await api.GET("/agents/{agent_id}", { params: { path: { agent_id: id } } })); }
export async function createAgent(body: paths["/agents"]["post"]["requestBody"]["content"]["application/json"]): Promise<AgentCatalogEntry> { return requireData(await api.POST("/agents", { body })); }
export async function updateAgent(id: string, body: paths["/agents/{agent_id}"]["patch"]["requestBody"]["content"]["application/json"]): Promise<AgentCatalogEntry> { return requireData(await api.PATCH("/agents/{agent_id}", { params: { path: { agent_id: id } }, body })); }
export async function deleteAgent(id: string): Promise<void> { const result = await api.DELETE("/agents/{agent_id}", { params: { path: { agent_id: id } } }); if (result.error !== undefined) throw result.error; }

export async function fetchMcps(): Promise<McpCatalogListEntry[]> { return requireData(await api.GET("/mcp-servers")); }
export async function fetchSkills(): Promise<SkillCatalogEntry[]> { return requireData(await api.GET("/skills")); }
export async function fetchMcp(id: string): Promise<McpCatalogEntry> { return requireData(await api.GET("/mcp-servers/{server_id}", { params: { path: { server_id: id } } })); }
export async function fetchSkill(id: string): Promise<SkillCatalogEntry> { return requireData(await api.GET("/skills/{skill_id}", { params: { path: { skill_id: id } } })); }
export async function createMcp(body: paths["/mcp-servers"]["post"]["requestBody"]["content"]["application/json"]): Promise<McpCatalogEntry> { return requireData(await api.POST("/mcp-servers", { body })); }
export async function updateMcp(id: string, body: paths["/mcp-servers/{server_id}"]["patch"]["requestBody"]["content"]["application/json"]): Promise<McpCatalogEntry> { return requireData(await api.PATCH("/mcp-servers/{server_id}", { params: { path: { server_id: id } }, body })); }
export async function deleteMcp(id: string): Promise<void> { const result = await api.DELETE("/mcp-servers/{server_id}", { params: { path: { server_id: id } } }); if (result.error !== undefined) throw result.error; }
export async function createSkill(body: paths["/skills"]["post"]["requestBody"]["content"]["application/json"]): Promise<SkillCatalogEntry> { return requireData(await api.POST("/skills", { body })); }
export async function updateSkill(id: string, body: paths["/skills/{skill_id}"]["patch"]["requestBody"]["content"]["application/json"]): Promise<SkillCatalogEntry> { return requireData(await api.PATCH("/skills/{skill_id}", { params: { path: { skill_id: id } }, body })); }
export async function deleteSkill(id: string): Promise<void> { const result = await api.DELETE("/skills/{skill_id}", { params: { path: { skill_id: id } } }); if (result.error !== undefined) throw result.error; }

import type { paths } from "@/api/schema";
