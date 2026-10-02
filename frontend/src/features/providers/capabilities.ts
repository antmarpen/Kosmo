export type ProviderType = "opencode" | "claude_code" | "codex";
export type ProviderAuthMethod = "config" | "api_key";
export interface ProviderCapability {
  type: ProviderType;
  label: string;
  available: boolean;
  authMethods: ProviderAuthMethod[];
  description: string;
}
export const providerCapabilities: ProviderCapability[] = [
  {
    type: "opencode",
    label: "providers.types.opencode.label",
    available: true,
    authMethods: ["config"],
    description: "providers.types.opencode.description",
  },
  {
    type: "claude_code",
    label: "providers.types.claude_code.label",
    available: false,
    authMethods: ["api_key", "config"],
    description: "providers.types.claude_code.description",
  },
  {
    type: "codex",
    label: "providers.types.codex.label",
    available: false,
    authMethods: ["api_key", "config"],
    description: "providers.types.codex.description",
  },
];
export function getProviderCapability(type: ProviderType): ProviderCapability {
  const capability = providerCapabilities.find((candidate) => candidate.type === type);
  if (!capability) throw new Error(`Unknown provider type: ${type}`);
  return capability;
}
export function canProceedWithProvider(type: ProviderType): boolean {
  return getProviderCapability(type).available;
}
