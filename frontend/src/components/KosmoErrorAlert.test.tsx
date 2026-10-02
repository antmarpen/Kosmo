import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { KosmoErrorAlert } from "./KosmoErrorAlert";

describe("KosmoErrorAlert", () => {
  it("translates the message key and interpolates parameters", () => {
    render(<KosmoErrorAlert error={{ code: "VALIDATION_EXHAUSTED", message_key: "errors.node.validation_exhausted", params: { attempts: 3, node: "compile" }, details: [] }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Validation failed after 3 attempts for compile.");
  });

  it("renders localized error details as a list", () => {
    render(<KosmoErrorAlert error={{ code: "INVALID", message_key: "errors.provider.config_invalid", params: {}, details: [{ message_key: "errors.provider.auth_missing", params: {} }] }} />);
    expect(screen.getByRole("listitem")).toHaveTextContent("Add provider credentials before continuing.");
  });

  it("uses the generic localized message for an unknown translation key", () => {
    render(<KosmoErrorAlert error={{ code: "NEW_ERROR", message_key: "errors.not.catalogued", params: {}, details: [] }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("An unexpected error occurred.");
  });
});
