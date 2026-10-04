import type { paths } from "@/api/schema";

type JsonResponse<T> = T extends { content: { "application/json": infer Body } } ? Body : never;
// Current backend list/detail routes omit response_model, so OpenAPI emits `unknown`.
// Keep generated request contracts and expose unknown response bodies until WP-05 adds DTO schemas.
export type AgentCatalogEntry = JsonResponse<paths["/agents"]["get"]["responses"][200]>;
export type McpCatalogEntry = JsonResponse<paths["/mcp-servers"]["get"]["responses"][200]>;
export type SkillCatalogEntry = JsonResponse<paths["/skills"]["get"]["responses"][200]>;
