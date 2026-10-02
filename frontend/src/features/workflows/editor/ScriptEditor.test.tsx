import userEvent from "@testing-library/user-event";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import en from "@/i18n/locales/en.json";
import { createNode, deserializeWorkflow, type WorkflowEditorState } from "./model";
import { PropertiesPanel } from "./PropertiesPanel";

/**
 * Counting mock: `imports` records how many times the dynamic import of
 * `@monaco-editor/react` ran, so the first tests can prove that only opening
 * the script modal ever loads it. The tests that assert the count must stay
 * first in this file: after the first successful import the module cache hides
 * any later factory runs.
 */
const { MockMonacoEditor, monacoImports } = vi.hoisted(() => {
  const monacoImports = { count: 0 };
  const MockMonacoEditor = vi.fn((props: { value: string; onChange: (value: string | undefined) => void }) => (
    <textarea aria-label="monaco editor mock" value={props.value} onChange={(event) => props.onChange(event.target.value)} />
  ));
  return { MockMonacoEditor, monacoImports };
});

vi.mock("@monaco-editor/react", () => {
  monacoImports.count += 1;
  return { default: MockMonacoEditor };
});

/**
 * The script-editor catalog keys are applied by the coordinator; until then
 * i18next renders the raw dotted key, so expectations resolve the value when
 * present and fall back to the full key path itself.
 */
const editorCatalog = en.editor as unknown as Record<string, string | undefined>;
const expected = (key: string) => editorCatalog[key] ?? `editor.${key}`;
/** A missing plural key renders as the base key until the catalog values land. */
const lineCount = (count: number) => {
  const template = editorCatalog[count === 1 ? "codeLines_one" : "codeLines_other"];
  return template ? template.replace("{{count}}", String(count)) : "editor.codeLines";
};

function panelWithScript(code = ""): WorkflowEditorState {
  const state = deserializeWorkflow({ schema_version: "v1", name: "test", nodes: [createNode("script", "n")], edges: [] });
  state.selection.nodeIds = ["n"];
  (state.definition.nodes[0] as { code: string }).code = code;
  return state;
}

describe("ScriptEditor modal", () => {
  it("never imports Monaco for a non-Script node", () => {
    const state = deserializeWorkflow({ schema_version: "v1", name: "test", nodes: [createNode("start", "s")], edges: [] });
    state.selection.nodeIds = ["s"];
    render(<PropertiesPanel state={state} onUpdate={vi.fn()} />);
    expect(monacoImports.count).toBe(0);
  });

  it("shows the Script properties as a read-only summary plus an edit button, with no editor", () => {
    render(<PropertiesPanel state={panelWithScript("pass\nprint(1)")} onUpdate={vi.fn()} />);
    expect(screen.getByRole("button", { name: expected("editScript") })).toBeInTheDocument();
    // No direct code editor outside the modal; the declared-input controls the
    // panel shows are not code editors.
    expect(screen.queryByRole("textbox", { name: "Code" })).not.toBeInTheDocument();
    expect(screen.getByText(lineCount(2))).toBeInTheDocument();
    // Read-only monospace preview of the stored code.
    const preview = screen.getByLabelText("Code");
    expect(preview).toHaveTextContent("pass");
    expect(preview).toHaveTextContent("print(1)");
    expect(monacoImports.count).toBe(0);
  });

  it("opens the dialog, holds dismissal while loading, and only then imports Monaco", async () => {
    const before = monacoImports.count;
    const user = userEvent.setup();
    render(<PropertiesPanel state={panelWithScript()} onUpdate={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: expected("editScript") }));
    // Loading state inside the modal while the chunk resolves, and the dialog
    // holds Escape dismissal until the editor is ready (ConfirmDialog contract).
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(expected("codeLoading"))).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(await screen.findByRole("textbox", { name: "monaco editor mock" })).toBeInTheDocument();
    expect(monacoImports.count).toBe(before + 1);
  });

  it("saves the edited code into the node model and closes", async () => {
    const onUpdate = vi.fn();
    render(<PropertiesPanel state={panelWithScript("pass")} onUpdate={onUpdate} />);
    fireEvent.click(screen.getByRole("button", { name: expected("editScript") }));
    const mock = await screen.findByRole("textbox", { name: "monaco editor mock" });
    // Save is only enabled once the draft differs from the stored code.
    const save = screen.getByRole("button", { name: expected("save") });
    expect(save).toBeDisabled();
    fireEvent.change(mock, { target: { value: "print('hi')" } });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(onUpdate).toHaveBeenCalledWith("n", expect.objectContaining({ id: "n", type: "script", code: "print('hi')" }));
  });

  it("cancel discards the draft and leaves the stored code untouched", async () => {
    const onUpdate = vi.fn();
    render(<PropertiesPanel state={panelWithScript("stored")} onUpdate={onUpdate} />);
    fireEvent.click(screen.getByRole("button", { name: expected("editScript") }));
    const mock = await screen.findByRole("textbox", { name: "monaco editor mock" });
    fireEvent.change(mock, { target: { value: "edited" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(onUpdate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: expected("editScript") }));
    expect(await screen.findByRole("textbox", { name: "monaco editor mock" })).toHaveValue("stored");
  });

  it("Escape discards the edits once the editor is ready", async () => {
    const onUpdate = vi.fn();
    const user = userEvent.setup();
    render(<PropertiesPanel state={panelWithScript("stored")} onUpdate={onUpdate} />);
    fireEvent.click(screen.getByRole("button", { name: expected("editScript") }));
    const mock = await screen.findByRole("textbox", { name: "monaco editor mock" });
    fireEvent.change(mock, { target: { value: "edited" } });
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(onUpdate).not.toHaveBeenCalled();
  });
});
