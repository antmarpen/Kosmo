import ClaudeCodeColor from "@lobehub/icons/es/ClaudeCode/components/Color";
import CodexColor from "@lobehub/icons/es/Codex/components/Color";
import OpenCodeMono from "@lobehub/icons/es/OpenCode/components/Mono";
import { COLOR_PRIMARY as OPENCODE_COLOR } from "@lobehub/icons/es/OpenCode/style";

import type { ProviderType } from "./capabilities";

type MarkProps = {
  size?: number | string;
  className?: string;
  style?: Record<string, string>;
  "aria-hidden"?: "true" | "false";
  focusable?: string;
};
type Mark = (props: MarkProps) => React.ReactNode;

/**
 * Provider marks come from `@lobehub/icons` (the icon library approved in the
 * project stack). It covers OpenCode, Claude Code, Codex and 130+ other AI
 * providers and tools, so new providers do not need hand-drawn SVGs.
 *
 * Only the per-brand `components/*` entry points are imported: the package
 * index also exports preview/combine/avatar widgets that pull `@lobehub/ui`
 * and an emoji data set, which the app does not need. Codex and Claude Code
 * use their brand-coloured variants (Codex's mark is a blue/violet gradient,
 * Claude Code's is its orange); OpenCode has no colour variant and ships a
 * white/black mark, so its mono mark is drawn in its brand black.
 *
 * Marks are decorative: the accessible name always comes from the visible
 * localized provider label rendered next to them.
 */
const marks: Record<ProviderType, { Mark: Mark; color?: string }> = {
  opencode: { Mark: OpenCodeMono as unknown as Mark, color: OPENCODE_COLOR },
  claude_code: { Mark: ClaudeCodeColor as unknown as Mark },
  codex: { Mark: CodexColor as unknown as Mark },
};

export function ProviderIcon({ type, size = 20, className }: { type: ProviderType | string; size?: number; className?: string }) {
  const mark = marks[type as ProviderType];
  if (!mark) return null;
  return <mark.Mark aria-hidden="true" focusable="false" size={size} className={className} style={mark.color ? { color: mark.color } : undefined} />;
}
