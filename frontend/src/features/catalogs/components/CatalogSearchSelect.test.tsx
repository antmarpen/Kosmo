import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type { CatalogSelectOption } from "./CatalogSearchSelect";
import { CatalogSearchSelect } from "./CatalogSearchSelect";

// jsdom does not implement ResizeObserver, which the Radix popper-based
// content measures with (same convention as the dropdown-menu tests).
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

const options: CatalogSelectOption[] = [
  { id: "opt-alpha", name: "Alpha", description: "First helper" },
  { id: "opt-beta", name: "Beta" },
  { id: "opt-gamma", name: "Gamma tool", description: "Second helper" },
];

function SingleHost({ initial = null as string | null, clearable = true }) {
  const [value, setValue] = useState<string | null>(initial);
  return (
    <div>
      <CatalogSearchSelect
        mode="single"
        options={options}
        value={value}
        onChange={setValue}
        placeholder="Choose an agent"
        clearable={clearable}
        aria-label="Agent"
      />
      <output data-testid="value">{value ?? "(none)"}</output>
    </div>
  );
}

function MultiHost({ initial = [] as string[] }) {
  const [value, setValue] = useState<string[]>(initial);
  return (
    <div>
      <CatalogSearchSelect
        mode="multi"
        options={options}
        value={value}
        onChange={setValue}
        aria-label="MCP servers"
      />
      <output data-testid="value">{value.join(",") || "(none)"}</output>
    </div>
  );
}

describe("CatalogSearchSelect — single", () => {
  it("opens a searchable listbox from the combobox trigger", async () => {
    const user = userEvent.setup();
    render(<SingleHost />);
    const input = screen.getByRole("combobox", { name: "Agent" });
    expect(input).toHaveAttribute("aria-expanded", "false");

    await user.click(input);
    expect(input).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Alpha/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Gamma tool/ })).toBeInTheDocument();
  });

  it("filters options while typing and explains when nothing matches", async () => {
    const user = userEvent.setup();
    render(<SingleHost />);
    const input = screen.getByRole("combobox", { name: "Agent" });
    await user.click(input);
    await user.type(input, "alp");
    expect(screen.getByRole("option", { name: /Alpha/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Beta/ })).toBeNull();

    await user.clear(input);
    await user.type(input, "zzz");
    expect(screen.getByText("No results match “zzz”.")).toBeInTheDocument();
  });

  it("selects with the keyboard and resets the search on close", async () => {
    const user = userEvent.setup();
    render(<SingleHost />);
    const input = screen.getByRole("combobox", { name: "Agent" });
    await user.click(input);
    await user.type(input, "gam");
    await user.keyboard("{Enter}");

    expect(screen.getByTestId("value")).toHaveTextContent("opt-gamma");
    // The listbox closed and the search query was reset.
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(input).toHaveAttribute("aria-expanded", "false");

    // Reopening shows the committed selection, not the stale query.
    await user.click(input);
    expect(input).toHaveValue("Gamma tool");
  });

  it("moves the highlight with ArrowDown/ArrowUp/Home/End and tracks it in aria-activedescendant", async () => {
    const user = userEvent.setup();
    render(<SingleHost />);
    const input = screen.getByRole("combobox", { name: "Agent" });
    await user.click(input);

    const firstOption = screen.getByRole("option", { name: /Alpha/ });
    expect(input).toHaveAttribute("aria-activedescendant", firstOption.id);

    await user.keyboard("{ArrowDown}");
    const secondOption = screen.getByRole("option", { name: /Beta/ });
    expect(input).toHaveAttribute("aria-activedescendant", secondOption.id);
    expect(secondOption).toHaveAttribute("aria-selected", "true");

    await user.keyboard("{End}");
    const lastOption = screen.getByRole("option", { name: /Gamma tool/ });
    expect(input).toHaveAttribute("aria-activedescendant", lastOption.id);

    await user.keyboard("{Home}");
    expect(input).toHaveAttribute("aria-activedescendant", firstOption.id);

    await user.keyboard("{ArrowUp}");
    // Wraps from the first option back to the last.
    expect(input).toHaveAttribute("aria-activedescendant", lastOption.id);
  });

  it("Escape closes the listbox, resets the query and keeps the value", async () => {
    const user = userEvent.setup();
    render(<SingleHost initial="opt-alpha" />);
    const input = screen.getByRole("combobox", { name: "Agent" });
    await user.click(input);
    await user.type(input, "zzz");
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("listbox")).toBeNull();
    expect(screen.getByTestId("value")).toHaveTextContent("opt-alpha");
    await user.click(input);
    expect(input).toHaveValue("Alpha");
  });

  it("offers a clear affordance when a value is set and clearable", async () => {
    const user = userEvent.setup();
    render(<SingleHost initial="opt-alpha" />);
    await user.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(screen.getByTestId("value")).toHaveTextContent("(none)");
  });

  it("hides the clear affordance when not clearable", () => {
    render(<SingleHost initial="opt-alpha" clearable={false} />);
    expect(screen.queryByRole("button", { name: "Clear selection" })).toBeNull();
  });
});

describe("CatalogSearchSelect — multi", () => {
  /** The chip's name span is its first child; icon ligature text inside the
   * remove button is excluded from this view of the label. */
  function chipName(chip: HTMLElement): string {
    return chip.querySelector("span")?.textContent ?? "";
  }

  it("renders the current value as ordered removable chips", async () => {
    const user = userEvent.setup();
    render(<MultiHost initial={["opt-beta", "opt-alpha"]} />);
    const list = screen.getByRole("list");
    const chips = within(list).getAllByRole("listitem");
    expect(chips.map(chipName)).toEqual(["Beta", "Alpha"]);

    await user.click(screen.getByRole("button", { name: "Remove Beta" }));
    expect(screen.getByTestId("value")).toHaveTextContent("opt-alpha");
  });

  it("toggles options from the listbox without closing and marks selected options", async () => {
    const user = userEvent.setup();
    render(<MultiHost />);
    const input = screen.getByRole("combobox", { name: "MCP servers" });
    await user.click(input);
    await user.click(screen.getByRole("option", { name: /Alpha/ }));

    expect(screen.getByTestId("value")).toHaveTextContent("opt-alpha");
    // Multi selection keeps the listbox open for more picks.
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Alpha/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    // Selecting again removes it from the ordered value.
    await user.click(screen.getByRole("option", { name: /Alpha/ }));
    expect(screen.getByTestId("value")).toHaveTextContent("(none)");
  });

  it("flags values that are no longer among the options as unavailable and removable", async () => {
    const user = userEvent.setup();
    render(<MultiHost initial={["opt-ghost"]} />);
    const chip = screen.getByRole("listitem");
    expect(chip).toHaveTextContent("Unavailable");
    expect(chip).toHaveTextContent("opt-ghost");

    await user.click(within(chip).getByRole("button"));
    expect(screen.getByTestId("value")).toHaveTextContent("(none)");
  });
});
