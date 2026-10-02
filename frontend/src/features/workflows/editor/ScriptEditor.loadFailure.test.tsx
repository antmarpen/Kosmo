import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import en from "@/i18n/locales/en.json";
import { ScriptEditor } from "./ScriptEditor";

// The mock module itself rejects, which is what a failed chunk fetch produces
// at the `import("@monaco-editor/react")` call site.
vi.mock("@monaco-editor/react", () => {
  throw new Error("Failed to fetch dynamically imported module");
});

/** Missing keys render as the raw dotted key until the coordinator applies the catalog values. */
const editorCatalog = (en.editor as unknown as Record<string, string | undefined>);
const expected = (key: string) => editorCatalog[key] ?? `editor.${key}`;

describe("ScriptEditor chunk load failure", () => {
  it("shows a localized error and keeps the modal usable through a plain-text fallback", async () => {
    const onChange = vi.fn();
    render(<ScriptEditor value="pass" onChange={onChange} label="Code" />);
    fireEvent.click(screen.getByRole("button", { name: expected("editScript") }));
    // The import rejection lands in the error state instead of a blank area.
    const error = await screen.findByRole("alert");
    expect(error).toHaveTextContent(expected("codeEditorError"));
    // The fallback keeps the code editable and the save contract intact.
    const fallback = screen.getByRole("textbox", { name: "Code" }) as HTMLTextAreaElement;
    expect(fallback).toHaveValue("pass");
    fireEvent.change(fallback, { target: { value: "pass#" } });
    const save = screen.getByRole("button", { name: expected("save") });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(onChange).toHaveBeenCalledWith("pass#");
  });
});
