import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

import { renderMarkdown } from "./markdownRenderer";

/**
 * Read-only preview for user-authored Markdown (agent/skill instructions).
 *
 * Safety is delegated entirely to `renderMarkdown` (no HTML parsing, scheme
 * allowlisted links, no image loading, no `dangerouslySetInnerHTML`); this
 * component only adds the prose presentation and the empty state. Consumers
 * that need the content in a modal should use `MarkdownPreviewDialog`.
 */
export function MarkdownPreview({ source, className }: { source: string; className?: string }) {
  const { t } = useTranslation();

  if (source.trim() === "") {
    return (
      <p className={cn("text-sm text-muted-foreground", className)}>
        {t("catalog.markdown.empty")}
      </p>
    );
  }
  return (
    <div
      data-slot="markdown-preview"
      className={cn("text-sm leading-6 text-foreground", className)}
    >
      {renderMarkdown(source)}
    </div>
  );
}
