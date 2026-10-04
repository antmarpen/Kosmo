import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useCatalogFormFocus } from "./useCatalogFormFocus";

function FocusableCatalogForm() {
  const formRef = useCatalogFormFocus();

  return (
    <form ref={formRef}>
      <input type="hidden" data-testid="hidden" />
      <div hidden>
        <input data-testid="hidden-name" />
      </div>
      <input aria-label="Name" />
      <button type="submit">Save</button>
    </form>
  );
}

describe("useCatalogFormFocus", () => {
  it("focuses the first enabled visible form control on mount", () => {
    render(<FocusableCatalogForm />);

    expect(screen.getByLabelText("Name")).toHaveFocus();
  });
});
