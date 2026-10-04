import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  isSafeMarkdownHref,
  renderMarkdown,
} from "./markdownRenderer";

/** Renders the produced nodes inside a stable container for DOM queries. */
function renderSource(source: string): HTMLElement {
  const { container } = render(<div data-testid="md">{renderMarkdown(source)}</div>);
  return container;
}

describe("isSafeMarkdownHref", () => {
  it("allows http(s), mailto and in-app relative references", () => {
    expect(isSafeMarkdownHref("https://example.com/docs")).toBe(true);
    expect(isSafeMarkdownHref("http://example.com/docs")).toBe(true);
    expect(isSafeMarkdownHref("mailto:user@example.com")).toBe(true);
    expect(isSafeMarkdownHref("/admin/agents")).toBe(true);
    expect(isSafeMarkdownHref("#section")).toBe(true);
    expect(isSafeMarkdownHref("./relative")).toBe(true);
    expect(isSafeMarkdownHref("../up")).toBe(true);
  });

  it("rejects script, data and other non-web schemes", () => {
    expect(isSafeMarkdownHref("javascript:alert(1)")).toBe(false);
    expect(isSafeMarkdownHref("JAVASCRIPT:alert(1)")).toBe(false);
    expect(isSafeMarkdownHref("data:text/html,<script>alert(1)</script>")).toBe(false);
    expect(isSafeMarkdownHref("vbscript:msgbox(1)")).toBe(false);
    expect(isSafeMarkdownHref("file:///etc/passwd")).toBe(false);
  });

  it("rejects scheme obfuscation with control characters or whitespace", () => {
    // Browsers strip tabs/newlines inside URL schemes, so "java\tscript:"
    // would execute; we reject instead of trying to normalize.
    expect(isSafeMarkdownHref("java\tscript:alert(1)")).toBe(false);
    expect(isSafeMarkdownHref("java\nscript:alert(1)")).toBe(false);
    expect(isSafeMarkdownHref(" javascript:alert(1)")).toBe(false);
    expect(isSafeMarkdownHref("\u0000javascript:alert(1)")).toBe(false);
    expect(isSafeMarkdownHref("")).toBe(false);
  });
});

describe("renderMarkdown security", () => {
  it("never parses raw HTML: script and img tags stay escaped text", () => {
    const container = renderSource(
      "Hello <script>alert(1)</script> and <img src=x onerror=alert(1)>",
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("iframe")).toBeNull();
    // The raw markup is still readable as authored text.
    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument();
  });

  it("never emits img elements for image syntax (no remote resource loading)", () => {
    const container = renderSource(
      "![Tracking pixel](https://evil.example/pixel.png)",
    );
    expect(container.querySelector("img")).toBeNull();
    // The alt text is preserved so readers know an image was authored.
    expect(screen.getByText("Tracking pixel")).toBeInTheDocument();
  });

  it("renders safe links as anchors with hardened rel/target", () => {
    const container = renderSource("[docs](https://example.com/a)");
    const link = container.querySelector("a");
    expect(link).not.toBeNull();
    expect(link).toHaveAttribute("href", "https://example.com/a");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveAttribute("target", "_blank");
    expect(screen.getByText("docs")).toBeInTheDocument();
  });

  it("downgrades links with unsafe URLs to plain text", () => {
    for (const href of [
      "javascript:alert(1)",
      "JAVASCRIPT:alert(1)",
      "data:text/html;base64,PHNjcmlwdD4=",
      "vbscript:msgbox(1)",
    ]) {
      const { container } = render(<div>{renderMarkdown(`[click me](${href})`)}</div>);
      expect(container.querySelector("a"), href).toBeNull();
      // The label survives as text; the URL never becomes an anchor.
      expect(within(container).getByText("click me")).toBeInTheDocument();
    }
  });

  it("keeps event-handler payloads inert inside link labels and URLs", () => {
    const container = renderSource(
      '[x"](https://example.com/)"onmouseover="alert(1)',
    );
    const link = container.querySelector("a");
    // The URL fragment after the closing paren is plain text; the anchor href
    // is exactly the safe URL.
    expect(link).toHaveAttribute("href", "https://example.com/");
    expect(container.querySelector("a")).not.toHaveAttribute("onmouseover");
  });

  it("does not allow markup smuggling through formatting delimiters", () => {
    const container = renderSource("**<script>alert(1)</script>**");
    expect(container.querySelector("script")).toBeNull();
    const strong = container.querySelector("strong");
    expect(strong).not.toBeNull();
    expect(strong).toHaveTextContent("<script>alert(1)</script>");
  });
});

describe("renderMarkdown structure", () => {
  it("renders headings, paragraphs, lists, quotes, rules and fenced code", () => {
    const container = renderSource(
      [
        "# Title",
        "",
        "A paragraph with **bold**, *italic* and `code`.",
        "",
        "- one",
        "- two",
        "",
        "1. first",
        "2. second",
        "",
        "> quoted wisdom",
        "",
        "---",
        "",
        "```python",
        "print('hi')",
        "```",
      ].join("\n"),
    );
    expect(container.querySelector("h1")).toHaveTextContent("Title");
    expect(container.querySelector("strong")).toHaveTextContent("bold");
    expect(container.querySelector("em")).toHaveTextContent("italic");
    expect(container.querySelector("p code")).toHaveTextContent("code");
    expect(container.querySelectorAll("ul li")).toHaveLength(2);
    expect(container.querySelectorAll("ol li")).toHaveLength(2);
    expect(container.querySelector("blockquote")).toHaveTextContent("quoted wisdom");
    expect(container.querySelector("hr")).not.toBeNull();
    expect(container.querySelector("pre code")).toHaveTextContent("print('hi')");
  });

  it("keeps fenced code lines verbatim without parsing markers inside", () => {
    const container = renderSource("```\n**not bold** [not a link](x)\n```");
    const code = container.querySelector("pre code");
    expect(code).toHaveTextContent("**not bold** [not a link](x)");
    expect(container.querySelector("strong")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
  });

  it("supports heading levels two to six", () => {
    const container = renderSource(
      ["## H2", "### H3", "#### H4", "##### H5", "###### H6"].join("\n"),
    );
    for (const level of [2, 3, 4, 5, 6]) {
      expect(container.querySelector(`h${level}`)).not.toBeNull();
    }
  });
});
