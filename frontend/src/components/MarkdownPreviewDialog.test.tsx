import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { MarkdownPreviewDialog } from "./MarkdownPreviewDialog";

// jsdom does not implement ResizeObserver (same convention as the Radix
// dropdown-menu tests).
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

/** Controlled host mirroring how screens open the preview dialog. The spy
 * lives outside the component so re-renders cannot replace it. */
function Host({
  source,
  onOpenChange,
}: {
  source: string;
  onOpenChange: (open: boolean) => void;
}) {
  const [open, setOpen] = useState(true);
  return (
    <MarkdownPreviewDialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        setOpen(next);
      }}
      title="Agent instructions"
      source={source}
    />
  );
}

describe("MarkdownPreviewDialog", () => {
  it("renders the title and the safe read-only Markdown content", () => {
    render(<Host source={"# Steps\n\nFirst `step`."} onOpenChange={() => undefined} />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Agent instructions")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 1, name: "Steps" }),
    ).toBeInTheDocument();
    expect(screen.getByText("step")).toBeInTheDocument();
  });

  it("stays read-only and safe: no inputs and no image loading", () => {
    const { container } = render(
      <Host source={"![pixel](https://evil.example/p.png)"} onOpenChange={() => undefined} />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("input,textarea")).toBeNull();
  });

  it("shows the localized empty note when nothing is written", () => {
    render(<Host source="" onOpenChange={() => undefined} />);
    expect(screen.getByText("Nothing written yet.")).toBeInTheDocument();
  });

  it("closes through the shared close affordance and reports the change", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    render(<Host source="Body" onOpenChange={onOpenChange} />);
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    render(<Host source="Body" onOpenChange={onOpenChange} />);
    await user.keyboard("{Escape}");
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
