import type { paths } from "@/api/schema";

type JsonResponse<T> = T extends { content: { "application/json": infer Body } } ? Body : never;
type ListItem<T> = T extends Array<infer Item> ? Item : never;
export type AgentCatalogEntry = ListItem<JsonResponse<paths["/agents"]["get"]["responses"][200]>>;
export type McpCatalogEntry = JsonResponse<paths["/mcp-servers/{server_id}"]["get"]["responses"][200]>;
export type McpCatalogListEntry = ListItem<JsonResponse<paths["/mcp-servers"]["get"]["responses"][200]>>;
export type SkillCatalogEntry = JsonResponse<paths["/skills/{skill_id}"]["get"]["responses"][200]>;
