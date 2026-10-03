import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import en from "@/i18n/locales/en.json";
import { OutputValidationDialog } from "./OutputValidationDialog";
import type { ValidationContract } from "./model";

const label = (key: string) => (en.editor as unknown as Record<string, string>)[key] ?? `editor.${key}`;
function renderDialog(value?: ValidationContract, onSave = vi.fn()) {
  render(<OutputValidationDialog open output="answer" inputs={[]} value={value} onOpenChange={vi.fn()} onSave={onSave} onRemove={vi.fn()} />);
  return onSave;
}

describe("output validation format editor", () => {
  it("shows the parse-only explanation for text and markdown without structure or rules controls", () => {
    renderDialog();
    expect(screen.getByLabelText(label("validationFormat")).querySelectorAll("option")).toHaveLength(4);
    expect(screen.queryByText("auto")).not.toBeInTheDocument();
    expect(screen.getByText(label("parseOnlyExplanation"))).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(label("validationFormat")), { target: { value: "markdown" } });
    expect(screen.getByText(label("parseOnlyExplanation"))).toBeInTheDocument();
    expect(screen.queryByLabelText(label("jsonSchema"))).not.toBeInTheDocument();
    expect(screen.queryByLabelText(label("pythonRules"))).not.toBeInTheDocument();
  });

  it("shows JSON Schema draft 2020-12 and optional Python rules for JSON", () => {
    renderDialog();
    fireEvent.change(screen.getByLabelText(label("validationFormat")), { target: { value: "json" } });
    expect(screen.getByText(label("jsonSchemaDraft"))).toBeInTheDocument();
    expect(screen.getByLabelText(label("jsonSchema"))).toBeInTheDocument();
    expect(screen.getByLabelText(label("pythonRules"))).toBeInTheDocument();
    expect(screen.queryByText(label("standardYamlExplanation"))).not.toBeInTheDocument();
  });

  it("shows standard YAML guidance and Python rules, without a schema editor", () => {
    renderDialog();
    fireEvent.change(screen.getByLabelText(label("validationFormat")), { target: { value: "yaml" } });
    expect(screen.getByText(label("standardYamlExplanation"))).toBeInTheDocument();
    expect(screen.getByLabelText(label("pythonRules"))).toBeInTheDocument();
    expect(screen.queryByLabelText(label("jsonSchema"))).not.toBeInTheDocument();
  });

  it("confirms destructive format changes in the shared dialog and saves only the selected format contract", async () => {
    const onSave = renderDialog({ format: "json", json_schema: { type: "object" }, rules_code: "return True" });
    fireEvent.change(screen.getByLabelText(label("validationFormat")), { target: { value: "text" } });
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText(label("confirmFormatChange"))).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: label("saveValidation") }));
    expect(onSave).toHaveBeenCalledWith({ format: "text" });
  });

  it("keeps the original format when the styled format confirmation is dismissed", async () => {
    const onSave = renderDialog({ format: "json", json_schema: { type: "object" } });
    fireEvent.change(screen.getByLabelText(label("validationFormat")), { target: { value: "yaml" } });
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("alertdialog"), { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Close" }));
    fireEvent.click(screen.getByRole("button", { name: label("saveValidation") }));
    expect(onSave).toHaveBeenCalledWith({ format: "json", json_schema: { type: "object" } });
  });

  it("switches formats without confirmation when the current schema and rules are empty", () => {
    renderDialog({ format: "json" });
    const format = screen.getByLabelText(label("validationFormat"));
    fireEvent.change(format, { target: { value: "text" } });
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(format).toHaveValue("text");
  });

  it("shows shared lively feedback while the code editor is loading", () => {
    renderDialog();
    fireEvent.change(screen.getByLabelText(label("validationFormat")), { target: { value: "yaml" } });
    expect(screen.getByRole("status", { name: label("codeLoading") })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: label("codeLoading") }).querySelector("[data-slot='icon']")).toBeTruthy();
  });

  it.each([false, true])("round-trips boolean JSON Schema %s", (json_schema) => {
    const onSave = renderDialog({ format: "json", json_schema });
    expect((screen.getByLabelText(label("jsonSchema")) as HTMLTextAreaElement).value).toBe(String(json_schema));
    fireEvent.click(screen.getByRole("button", { name: label("saveValidation") }));
    expect(onSave).toHaveBeenCalledWith({ format: "json", json_schema });
  });
});
