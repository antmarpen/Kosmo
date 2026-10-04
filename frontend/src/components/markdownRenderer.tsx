import { createElement, type ReactNode } from "react";

/**
 * Minimal, bounded Markdown → React renderer for user-authored catalog text
 * (agent/skill instructions, descriptions).
 *
 * Security model — this module is the vetted boundary for all authored text:
 * - Output is React elements only; there is **no HTML parsing** and no
 *   `dangerouslySetInnerHTML` anywhere. Raw HTML in the source renders as
 *   literal text because it never leaves the text channel.
 * - Links are allowlisted by scheme (`http`, `https`, `mailto`) plus
 *   in-app relative references. Any other scheme — and any URL containing
 *   whitespace or control characters, which browsers strip from schemes —
 *   is downgraded to plain text.
 * - Image syntax never loads anything: it renders the alt text, so authored
 *   Markdown cannot trigger remote resource loading.
 *
 * Deliberately out of scope (bounded syntax): tables, nested lists, footnotes,
 * autolinks and backslash escapes. Unknown syntax degrades to plain text.
 */

const BLOCK_SKIP_AT_LINE_START = /^(#{1,6}\s|>|(?:[-*]\s+)|(?:\d{1,9}[.)]\s*)|```)/;

/** Inline syntax: code, bold, italic, image or link. Hoisted source; each
 * traversal creates its own stateful instance (see `renderInline`). Link
 * destinations accept one level of balanced parentheses (CommonMark allows
 * `javascript:alert(1)`-shaped destinations, which the scheme allowlist then
 * rejects). */
const INLINE_SOURCE =
  "(`+)([^`]+?)\\1|\\*\\*([^*\\n]+?)\\*\\*|\\*([^*\\n]+?)\\*|(!?)\\[([^\\]\\n]*)\\]\\(([^()\\s]*(?:\\([^()\\s]*\\)[^()\\s]*)*)\\)";

/** Schemes a rendered link may point at. Everything else is text. */
const SAFE_LINK_SCHEMES = new Set(["http", "https", "mailto"]);

/** Control characters and whitespace: browsers strip these from schemes
 * (`java\tscript:`), so their presence means "unsafe", never "normalize". */
const UNSAFE_HREF_CHARS = /[\s\u0000-\u001f\u007f]/;

const SCHEME_PREFIX = /^([a-zA-Z][a-zA-Z0-9+.-]*):/;
const EXTERNAL_HTTP = /^https?:\/\//i;

/** External http(s) links open in a new tab with a hardened context. */
const EXTERNAL_LINK_ATTRS = { target: "_blank", rel: "noopener noreferrer" } as const;

// Presentation vocabulary (Tailwind theme tokens), kept next to the renderer
// so every consumer renders authored text identically.
const CLASS = {
  h1: "mt-5 text-lg font-semibold first:mt-0",
  h2: "mt-5 text-base font-semibold first:mt-0",
  h3: "mt-4 text-sm font-semibold first:mt-0",
  h4: "mt-4 text-sm font-semibold first:mt-0",
  h5: "mt-3 text-sm font-semibold first:mt-0",
  h6: "mt-3 text-sm font-semibold first:mt-0",
  p: "mt-2 whitespace-pre-wrap first:mt-0",
  ul: "mt-2 list-disc space-y-1 pl-5 first:mt-0",
  ol: "mt-2 list-decimal space-y-1 pl-5 first:mt-0",
  blockquote: "mt-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-muted-foreground first:mt-0",
  pre: "mt-2 overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs leading-5 first:mt-0",
  codeInline: "rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]",
  a: "font-medium text-primary underline underline-offset-2",
  hr: "mt-4 border-border first:mt-0",
  imageAlt: "text-muted-foreground",
} as const;

/**
 * Whether a link href may become an anchor. Relative references
 * (`/path`, `./…`, `../…`, `#fragment`, `?query`) are in-app and safe;
 * absolute URLs must carry an allowlisted scheme.
 */
export function isSafeMarkdownHref(href: string): boolean {
  const candidate = href.trim();
  if (candidate === "" || UNSAFE_HREF_CHARS.test(candidate)) return false;
  const scheme = candidate.match(SCHEME_PREFIX);
  if (!scheme) {
    // No scheme: only plain relative references are accepted. Anything else
    // (a bare word or unknown colon form) stays plain text.
    return /^[/#.?]/.test(candidate);
  }
  return SAFE_LINK_SCHEMES.has(scheme[1].toLowerCase());
}

/** Renders one line's inline syntax to React nodes (recursively for nesting). */
function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  // A fresh RegExp instance per call: the /g loop mutates lastIndex, and this
  // function recurses, so a shared instance would corrupt both iterations.
  const pattern = new RegExp(INLINE_SOURCE, "g");
  let last = 0;
  let key = 0;
  const push = (node: ReactNode) => nodes.push(node);

  for (let match = pattern.exec(text); match !== null; match = pattern.exec(text)) {
    if (match.index > last) push(text.slice(last, match.index));
    const [raw, , code, bold, italic, bang, label, href] = match;
    const nodeKey = `${keyPrefix}-${key++}`;

    if (code !== undefined) {
      push(
        <code key={nodeKey} className={CLASS.codeInline}>
          {code}
        </code>,
      );
    } else if (bold !== undefined) {
      push(<strong key={nodeKey}>{renderInline(bold, `${nodeKey}s`)}</strong>);
    } else if (italic !== undefined) {
      push(<em key={nodeKey}>{renderInline(italic, `${nodeKey}e`)}</em>);
    } else if (bang) {
      // Image syntax: never an <img> element — render the alt text instead so
      // authored Markdown cannot trigger remote resource loading.
      push(
        <span key={nodeKey} className={CLASS.imageAlt}>
          {label || href}
        </span>,
      );
    } else if (isSafeMarkdownHref(href)) {
      push(
        <a
          key={nodeKey}
          href={href}
          className={CLASS.a}
          {...(EXTERNAL_HTTP.test(href.trim()) ? EXTERNAL_LINK_ATTRS : undefined)}
        >
          {label ? renderInline(label, `${nodeKey}l`) : href}
        </a>,
      );
    } else {
      // Unsafe URL: the label stays as plain text; no anchor is emitted.
      push(<span key={nodeKey}>{label}</span>);
    }
    last = match.index + raw.length;
  }
  if (last < text.length) push(text.slice(last));
  return nodes;
}

/** Collects the body lines of a fenced code block starting at `start`. */
function collectFence(
  lines: string[],
  start: number,
): { content: string[]; next: number } {
  const content: string[] = [];
  let index = start + 1;
  while (index < lines.length && !/^\s*```/.test(lines[index])) {
    content.push(lines[index]);
    index += 1;
  }
  // The closing fence (or EOF) ends the block; the index moves past it.
  return { content, next: index < lines.length ? index + 1 : index };
}

/** Collects consecutive lines sharing one prefix pattern. */
function collectWhile(
  lines: string[],
  start: number,
  matches: (line: string) => boolean,
): { content: string[]; next: number } {
  const content: string[] = [];
  let index = start;
  while (index < lines.length && matches(lines[index])) {
    content.push(lines[index]);
    index += 1;
  }
  return { content, next: index };
}

const UL_ITEM = /^\s*[-*]\s+(.*)$/;
const OL_ITEM = /^\s*\d{1,9}[.)]\s+(.*)$/;
const QUOTE_LINE = /^\s*>\s?(.*)$/;
const HEADING = /^\s*(#{1,6})\s+(.*?)\s*#*\s*$/;
const HORIZONTAL_RULE = /^\s*(?:(?:\*\s*){3,}|(?:-\s*){3,})$/;
const FENCE_START = /^\s*```/;

function renderBlocks(lines: string[], keyPrefix: string): ReactNode[] {
  const blocks: ReactNode[] = [];
  let index = 0;
  let key = 0;
  const nodeKey = () => `${keyPrefix}-${key++}`;

  while (index < lines.length) {
    const line = lines[index];

    if (line.trim() === "") {
      index += 1;
      continue;
    }
    if (FENCE_START.test(line)) {
      const fence = collectFence(lines, index);
      blocks.push(
        <pre key={nodeKey()} className={CLASS.pre}>
          <code>{fence.content.join("\n")}</code>
        </pre>,
      );
      index = fence.next;
      continue;
    }
    const heading = line.match(HEADING);
    if (heading) {
      const level = heading[1].length;
      const headingClass = {
        1: CLASS.h1,
        2: CLASS.h2,
        3: CLASS.h3,
        4: CLASS.h4,
        5: CLASS.h5,
        6: CLASS.h6,
      }[level];
      blocks.push(
        createElement(
          `h${level}`,
          { key: nodeKey(), className: headingClass },
          ...renderInline(heading[2], nodeKey()),
        ),
      );
      index += 1;
      continue;
    }
    if (HORIZONTAL_RULE.test(line)) {
      blocks.push(<hr key={nodeKey()} className={CLASS.hr} />);
      index += 1;
      continue;
    }
    if (/^\s*>/.test(line)) {
      const quote = collectWhile(lines, index, (candidate) => /^\s*>/.test(candidate));
      blocks.push(
        <blockquote key={nodeKey()} className={CLASS.blockquote}>
          {renderBlocks(
            quote.content.map((quoteLine) => quoteLine.replace(QUOTE_LINE, "$1")),
            nodeKey(),
          )}
        </blockquote>,
      );
      index = quote.next;
      continue;
    }
    if (UL_ITEM.test(line)) {
      const items = collectWhile(lines, index, (candidate) => UL_ITEM.test(candidate));
      blocks.push(
        <ul key={nodeKey()} className={CLASS.ul}>
          {items.content.map((itemLine, itemIndex) => (
            <li key={`${keyPrefix}-li-${itemIndex}`}>
              {renderInline(itemLine.replace(UL_ITEM, "$1"), `${keyPrefix}-li-${itemIndex}`)}
            </li>
          ))}
        </ul>,
      );
      index = items.next;
      continue;
    }
    if (OL_ITEM.test(line)) {
      const items = collectWhile(lines, index, (candidate) => OL_ITEM.test(candidate));
      blocks.push(
        <ol key={nodeKey()} className={CLASS.ol}>
          {items.content.map((itemLine, itemIndex) => (
            <li key={`${keyPrefix}-oli-${itemIndex}`}>
              {renderInline(itemLine.replace(OL_ITEM, "$1"), `${keyPrefix}-oli-${itemIndex}`)}
            </li>
          ))}
        </ol>,
      );
      index = items.next;
      continue;
    }
    // Paragraph: consecutive plain lines until a blank line or a block start.
    const paragraph = collectWhile(
      lines,
      index,
      (candidate) => candidate.trim() !== "" && !BLOCK_SKIP_AT_LINE_START.test(candidate),
    );
    blocks.push(
      <p key={nodeKey()} className={CLASS.p}>
        {renderInline(
          paragraph.content.map((part) => part.trim()).join("\n"),
          nodeKey(),
        )}
      </p>,
    );
    index = paragraph.next;
  }
  return blocks;
}

/**
 * Renders bounded, safe Markdown to React nodes. The result is a fragment of
 * semantic elements ready to place inside a prose container; see
 * `MarkdownPreview` for the styled wrapper consumers should normally use.
 */
export function renderMarkdown(source: string): ReactNode {
  if (source.trim() === "") return null;
  return <>{renderBlocks(source.replace(/\r\n?/g, "\n").split("\n"), "md")}</>;
}
