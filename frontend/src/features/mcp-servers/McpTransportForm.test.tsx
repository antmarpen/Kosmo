import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// jsdom does not implement ResizeObserver, which the Radix popper-based
// tooltip content requires.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

import { McpTransportForm } from "./McpTransportForm";
import {
  addEntryDraft,
  createTransportDraft,
  transportFromDetail,
  updateEntryDraft,
  type TransportDraft,
  type TransportErrors,
} from "./transportState";

/** Controlled harness: applies changes so interactions re-render. */
function renderForm(initial: TransportDraft, errors: TransportErrors | null = null) {
  const onChange = vi.fn();
  function Harness() {
    const [draft, setDraft] = useState(initial);
    return (
      <McpTransportForm
        transport={draft}
        errors={errors}
        onChange={(next) => {
          onChange(next);
          setDraft(next);
        }}
      />
    );
  }
  render(<Harness />);
  return { onChange };
}

const detailWithStoredSecret = {
  transport: {
    type: "stdio",
    command: "npx",
    args: ["-y", "@acme/server"],
    env: [{ name: "API_TOKEN", secret: true, is_set: true }],
  },
} as const;

describe("mcp transport form — fields and secret safety", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders stdio fields with the hydrated entries", async () => {
    renderForm(transportFromDetail(detailWithStoredSecret.transport));
    expect(screen.getByLabelText("Command")).toHaveValue("npx");
    expect(screen.getByLabelText("Arguments")).toHaveValue("-y\n@acme/server");
    const nameInput = screen.getByLabelText("Environment variable name");
    expect(nameInput).toHaveValue("API_TOKEN");
    const row = nameInput.closest("li") as HTMLElement;
    const valueInput = within(row).getByLabelText("Value");
    // A stored secret is never preloaded: the masked input starts empty.
    expect(valueInput).toHaveAttribute("type", "password");
    expect(valueInput).toHaveValue("");
    expect(within(row).getByText("Set")).toBeInTheDocument();
    expect(
      within(row).getByText("Leave blank to keep the stored value."),
    ).toBeInTheDocument();
  });

  it("shows the value as text when the entry is not secret", async () => {
    const detail = {
      transport: {
        type: "http",
        url: "https://example.com/mcp",
        headers: [{ name: "X-Trace", secret: false, is_set: true, value: "trace-1" }],
      },
    } as const;
    renderForm(transportFromDetail(detail.transport));
    const valueInput = screen.getByLabelText("Value");
    expect(valueInput).toHaveAttribute("type", "text");
    // Nonsecret values may be shown; they come from the detail response.
    expect(valueInput).toHaveValue("trace-1");
    expect(screen.queryByText("Set")).not.toBeInTheDocument();
  });

  it("masks the value while the secret switch is on and reveals it when off", async () => {
    const { onChange } = renderForm(transportFromDetail(detailWithStoredSecret.transport));
    const nameInput = screen.getByLabelText("Environment variable name");
    const row = nameInput.closest("li") as HTMLElement;
    // Typing into the masked input replaces the stored secret.
    await userEvent.type(within(row).getByLabelText("Value"), "rotated");
    expect(within(row).getByLabelText("Value")).toHaveAttribute("type", "password");
    expect(within(row).getByLabelText("Value")).toHaveValue("rotated");
    await userEvent.click(within(row).getByRole("switch", { name: "Secret" }));
    await waitFor(() =>
      expect(within(row).getByLabelText("Value")).toHaveAttribute("type", "text"),
    );
    const lastChange = onChange.mock.calls.at(-1)?.[0] as TransportDraft;
    expect(lastChange.entries[0]).toMatchObject({ name: "API_TOKEN", secret: false });
  });
});

describe("mcp transport form — transport switch reset", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("asks for confirmation before discarding authored content", async () => {
    const { onChange } = renderForm(transportFromDetail(detailWithStoredSecret.transport));
    await userEvent.click(screen.getByRole("radio", { name: "HTTP endpoint" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Switch transport?");
    // Cancelling keeps the authored stdio content.
    await userEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.getByLabelText("Command")).toHaveValue("npx");
    expect(onChange).not.toHaveBeenCalled();
    // Confirming the switch resets every incompatible field and entry.
    await userEvent.click(screen.getByRole("radio", { name: "HTTP endpoint" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Switch" }),
    );
    await waitFor(() => expect(screen.getByLabelText("URL")).toBeInTheDocument());
    expect(screen.queryByLabelText("Command")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Environment variable name")).not.toBeInTheDocument();
    expect(screen.getByLabelText("URL")).toHaveValue("");
    const lastChange = onChange.mock.calls.at(-1)?.[0] as TransportDraft;
    expect(lastChange).toEqual({
      type: "http",
      command: "",
      argsText: "",
      url: "",
      entries: [],
      removals: [],
    });
  });

  it("switches immediately when there is nothing to discard", async () => {
    const { onChange } = renderForm(createTransportDraft("stdio"));
    await userEvent.click(screen.getByRole("radio", { name: "HTTP endpoint" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("URL")).toBeInTheDocument());
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ type: "http", url: "", entries: [] }),
    );
  });
});

describe("mcp transport form — entries", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("adds a nonsecret entry row", async () => {
    const { onChange } = renderForm(createTransportDraft("stdio"));
    await userEvent.click(screen.getByRole("button", { name: "Add environment variable" }));
    expect(await screen.findAllByLabelText("Environment variable name")).toHaveLength(1);
    const lastChange = onChange.mock.calls.at(-1)?.[0] as TransportDraft;
    expect(lastChange.entries).toHaveLength(1);
    expect(lastChange.entries[0]).toMatchObject({ name: "", secret: false, existing: false });
  });

  it("removes an existing entry into the removal list and drops a new one outright", async () => {
    const withNew = addEntryDraft(transportFromDetail(detailWithStoredSecret.transport));
    const { onChange } = renderForm(withNew);
    const rows = await screen.findAllByLabelText("Environment variable name");
    // Remove the stored entry: it must be sent as `remove` on submit.
    await userEvent.click(
      within(rows[0].closest("li") as HTMLElement).getByRole("button", { name: "Remove entry" }),
    );
    let lastChange = onChange.mock.calls.at(-1)?.[0] as TransportDraft;
    expect(lastChange.entries).toHaveLength(1);
    expect(lastChange.removals).toEqual([{ id: withNew.entries[0].id, name: "API_TOKEN", secret: true }]);
    // Remove the freshly added one: it was never stored, so no removal intent.
    await userEvent.click(
      within(
        screen.getByLabelText("Environment variable name").closest("li") as HTMLElement,
      ).getByRole("button", { name: "Remove entry" }),
    );
    lastChange = onChange.mock.calls.at(-1)?.[0] as TransportDraft;
    expect(lastChange.entries).toHaveLength(0);
    expect(lastChange.removals).toEqual([{ id: withNew.entries[0].id, name: "API_TOKEN", secret: true }]);
  });

  it("renders localized validation errors for fields and entries", () => {
    const draft = updateEntryDraft(transportFromDetail(detailWithStoredSecret.transport), "entry-1", {
      name: "1BAD",
    });
    const errors: TransportErrors = {
      command: true,
      entries: { [draft.entries[0].id]: ["name_invalid", "value_required"] },
      keepAfterRename: true,
    };
    renderForm(draft, errors);
    expect(screen.getByText("Enter a command without spaces. Put arguments on separate lines.")).toBeInTheDocument();
    expect(screen.getByText(/Stored secrets cannot be kept after renaming/)).toBeInTheDocument();
    const row = screen.getByLabelText("Environment variable name").closest("li") as HTMLElement;
    const alerts = within(row).getAllByRole("alert");
    const messages = alerts.map((alert) => alert.textContent).join(" ");
    expect(messages).toContain("Entry names cannot be empty or contain invalid characters.");
    expect(messages).toContain("Enter a value, or remove the entry.");
  });
});
