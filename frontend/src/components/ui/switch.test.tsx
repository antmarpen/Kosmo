import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Switch } from "./switch";

describe("Switch", () => {
  it("exposes controlled checked state and toggles with keyboard", async () => {
    const user = userEvent.setup();
    const onCheckedChange = vi.fn();
    const { rerender } = render(<Switch aria-label="Required" checked={false} onCheckedChange={onCheckedChange} />);
    const control = screen.getByRole("switch", { name: "Required" });
    expect(control).toHaveAttribute("aria-checked", "false");
    control.focus();
    await user.keyboard(" ");
    expect(onCheckedChange).toHaveBeenCalledWith(true);
    rerender(<Switch aria-label="Required" checked onCheckedChange={onCheckedChange} />);
    expect(control).toHaveAttribute("aria-checked", "true");
  });
});
