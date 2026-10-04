import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MarkdownPreview } from "./MarkdownPreview";

describe("MarkdownPreview", () => {
  it("renders authored Markdown as read-only prose", () => {
    render(<MarkdownPreview source={"# Ritual\n\nDo the **thing**."} />);
    expect(
      screen.getByRole("heading", { level: 1, name: "Ritual" }),
    ).toBeInTheDocument();
    expect(screen.getByText("thing")).toBeInTheDocument();
  });

  it("shows a localized note for empty or blank instructions", () => {
    render(<MarkdownPreview source="   " />);
    expect(screen.getByText("Nothing written yet.")).toBeInTheDocument();
  });

  it("never loads remote resources from the source", () => {
    const { container } = render(
      <MarkdownPreview source={"![x](https://evil.example/x.png)\n\n[y](javascript:alert(1))"} />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
  });
});
