import { fireEvent, render, screen } from "@testing-library/react";
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

  it("confirms destructive format changes and saves only the selected format contract", () => {
    const onSave = renderDialog({ format: "json", json_schema: { type: "object" }, rules_code: "return True" });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.change(screen.getByLabelText(label("validationFormat")), { target: { value: "text" } });
    expect(window.confirm).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: label("saveValidation") }));
    expect(onSave).toHaveBeenCalledWith({ format: "text" });
  });

  it("does not persist an uncommitted format change", () => {
    const onSave = renderDialog({ format: "json", json_schema: { type: "object" } });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    fireEvent.change(screen.getByLabelText(label("validationFormat")), { target: { value: "yaml" } });
    fireEvent.click(screen.getByRole("button", { name: label("saveValidation") }));
    expect(onSave).toHaveBeenCalledWith({ format: "json", json_schema: { type: "object" } });
  });
});
