import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { CatalogScopeField, type CatalogScope } from "./CatalogScopeField";

const managedGroups = [
  { id: "g-platform", name: "Platform" },
  { id: "g-design", name: "Design" },
];

/** Controlled host mirroring how the catalog forms will bind scope state. */
function Host({
  managedGroups: groups = [],
  globalAllowed = false,
  onScopeChange,
  onGroupIdChange,
  disabled = false,
}: {
  managedGroups?: Array<{ id: string; name: string }>;
  globalAllowed?: boolean;
  onScopeChange?: (scope: CatalogScope) => void;
  onGroupIdChange?: (groupId: string) => void;
  disabled?: boolean;
}) {
  const [scope, setScope] = useState<CatalogScope>("personal");
  const [groupId, setGroupId] = useState("");
  return (
    <div>
      <CatalogScopeField
        scope={scope}
        onScopeChange={(next) => {
          onScopeChange?.(next);
          setScope(next);
        }}
        groupId={groupId}
        onGroupIdChange={(next) => {
          onGroupIdChange?.(next);
          setGroupId(next);
        }}
        managedGroups={groups}
        globalAllowed={globalAllowed}
        disabled={disabled}
      />
      <output data-testid="scope">{scope}</output>
      <output data-testid="group-id">{groupId || "(none)"}</output>
    </div>
  );
}

describe("CatalogScopeField", () => {
  it("always offers personal and never offers group or global without permission", () => {
    render(<Host />);
    const group = screen.getByRole("radiogroup", { name: "Availability" });
    expect(group).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Just me" })).toBeChecked();
    expect(screen.queryByRole("radio", { name: "A managed group" })).toBeNull();
    expect(screen.queryByRole("radio", { name: "Everyone (global)" })).toBeNull();
  });

  it("offers the group scope only when managed groups exist and lists exactly those groups", async () => {
    const user = userEvent.setup();
    const onScopeChange = vi.fn();
    render(<Host managedGroups={managedGroups} onScopeChange={onScopeChange} />);

    const groupRadio = screen.getByRole("radio", { name: "A managed group" });
    expect(groupRadio).not.toBeChecked();
    await user.click(groupRadio);
    expect(onScopeChange).toHaveBeenCalledWith("group");
    expect(screen.getByTestId("scope")).toHaveTextContent("group");

    // The group picker lists only the managed groups — unavailable groups are
    // never offered as options.
    const picker = screen.getByRole("combobox", { name: "Group" });
    const values = Array.from(picker.querySelectorAll("option")).map(
      (option) => option.value,
    );
    expect(values).toEqual(["", "g-platform", "g-design"]);
    expect(screen.getByRole("option", { name: "Platform" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Finance" })).toBeNull();

    await user.selectOptions(picker, "g-design");
    expect(screen.getByTestId("group-id")).toHaveTextContent("g-design");
  });

  it("offers the global scope only to administrators", async () => {
    const user = userEvent.setup();
    const onScopeChange = vi.fn();
    render(<Host globalAllowed onScopeChange={onScopeChange} />);
    expect(screen.queryByRole("radio", { name: "A managed group" })).toBeNull();
    const globalRadio = screen.getByRole("radio", { name: "Everyone (global)" });
    await user.click(globalRadio);
    expect(onScopeChange).toHaveBeenCalledWith("global");
    expect(screen.getByTestId("scope")).toHaveTextContent("global");
  });

  it("disables every control while a submission is in flight", () => {
    render(<Host managedGroups={managedGroups} globalAllowed disabled />);
    expect(screen.getByRole("radio", { name: "Just me" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "A managed group" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "Everyone (global)" })).toBeDisabled();
  });
});
