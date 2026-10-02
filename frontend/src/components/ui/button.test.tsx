import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Button } from "./button";

describe("Button loading and disabled behavior", () => {
  it.each(["default", "xs", "sm", "lg", "icon", "icon-xs", "icon-sm", "icon-lg"] as const)(
    "uses the shared pill-shaped radius for the %s size",
    (size) => {
      render(<Button size={size}>Action</Button>);
      expect(screen.getByRole("button", { name: "Action" })).toHaveClass("rounded-full");
    },
  );

  it("keeps its label, exposes aria-busy, shows a decorative spinner, and blocks activation while loading", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    const { container } = render(
      <Button loading onClick={onClick}>
        Save
      </Button>,
    );

    const button = screen.getByRole("button", { name: "Save" });
    expect(button).toHaveTextContent("Save");
    expect(button).toHaveAttribute("aria-busy", "true");

    const spinner = container.querySelector('[data-slot="icon"]');
    expect(spinner).not.toBeNull();
    expect(spinner).toHaveAttribute("aria-hidden", "true");

    await user.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("renders without a spinner and fires onClick when idle", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    const { container } = render(<Button onClick={onClick}>Save</Button>);

    expect(container.querySelector('[data-slot="icon"]')).toBeNull();
    const button = screen.getByRole("button", { name: "Save" });
    expect(button).not.toHaveAttribute("aria-busy");

    await user.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("does not fire onClick when caller-disabled", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Save
      </Button>,
    );

    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onClick).not.toHaveBeenCalled();
  });

  it("supports asChild links and blocks activation while loading", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn(() => undefined);
    const { rerender, container } = render(
      <Button asChild onClick={onClick}>
        <a href="/target">Go</a>
      </Button>,
    );

    await user.click(screen.getByRole("link", { name: "Go" }));
    expect(onClick).toHaveBeenCalledTimes(1);

    onClick.mockClear();
    rerender(
      <Button asChild loading onClick={onClick}>
        <a href="/target">Go</a>
      </Button>,
    );

    const busyLink = screen.getByRole("link", { name: "Go" });
    expect(busyLink).toHaveAttribute("aria-busy", "true");
    expect(busyLink).toHaveAttribute("aria-disabled", "true");
    expect(container.querySelector('[data-slot="icon"]')).not.toBeNull();

    await user.click(busyLink);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("suppresses child-owned click handlers when asChild is disabled or loading", async () => {
    const user = userEvent.setup();
    const childAction = vi.fn();
    const { rerender } = render(
      <Button asChild disabled>
        <a href="/target" onClick={childAction}>Go</a>
      </Button>,
    );

    await user.click(screen.getByRole("link", { name: "Go" }));
    expect(childAction).not.toHaveBeenCalled();

    rerender(
      <Button asChild loading>
        <a href="/target" onClick={childAction}>Go</a>
      </Button>,
    );
    await user.click(screen.getByRole("link", { name: "Go" }));
    expect(childAction).not.toHaveBeenCalled();
  });

  it("applies native disabled semantics to an asChild button", async () => {
    const user = userEvent.setup();
    const childAction = vi.fn();
    render(
      <Button asChild loading>
        <button type="button" onClick={childAction}>Save</button>
      </Button>,
    );

    const button = screen.getByRole("button", { name: "Save" });
    expect(button).toBeDisabled();
    await user.click(button);
    expect(childAction).not.toHaveBeenCalled();
  });
});
