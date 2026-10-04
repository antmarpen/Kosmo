import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { KosmoError } from "@/components/KosmoErrorAlert";
import { Button } from "@/components/ui/button";

import {
  CatalogEmpty,
  CatalogList,
  CatalogLoadError,
  CatalogLoading,
  CatalogPageHeader,
  CatalogRow,
} from "./CatalogList";

describe("CatalogPageHeader", () => {
  it("renders the title, description and page action", () => {
    render(
      <CatalogPageHeader
        title="Skills"
        description="Reusable instruction packs."
        action={<Button>Add</Button>}
      />,
    );
    expect(
      screen.getByRole("heading", { level: 1, name: "Skills" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Reusable instruction packs.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add" })).toBeInTheDocument();
  });
});

describe("CatalogList and CatalogRow", () => {
  it("renders the column header, rows and a trailing actions cell", () => {
    render(
      <CatalogList columns={["Name", "Scope"]}>
        <CatalogRow>
          <div>Name cell</div>
          <div>Scope cell</div>
          <div>Actions</div>
        </CatalogRow>
      </CatalogList>,
    );
    expect(screen.getByRole("list")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Scope" })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText("Name cell")).toBeInTheDocument();
    expect(screen.getByText("Actions")).toBeInTheDocument();
  });

  it("hides the column header when no columns are supplied", () => {
    render(
      <CatalogList>
        <CatalogRow>
          <div>Solo cell</div>
        </CatalogRow>
      </CatalogList>,
    );
    expect(screen.queryByRole("columnheader")).toBeNull();
    expect(screen.getByText("Solo cell")).toBeInTheDocument();
  });
});

describe("CatalogLoading", () => {
  it("announces the loading state politely", () => {
    render(<CatalogLoading />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading…");
  });
});

describe("CatalogEmpty", () => {
  it("teaches the first entry with title, description and action", () => {
    render(
      <CatalogEmpty
        title="No skills yet"
        description="Create your first skill to reuse it in agents."
        action={<Button>Create</Button>}
      />,
    );
    expect(screen.getByText("No skills yet")).toBeInTheDocument();
    expect(
      screen.getByText("Create your first skill to reuse it in agents."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create" })).toBeInTheDocument();
  });
});

describe("CatalogLoadError", () => {
  it("renders the localized error and offers a retry", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    const error: KosmoError = {
      code: "REQUEST_FAILED",
      message_key: "errors.generic",
    };
    render(<CatalogLoadError error={error} onRetry={onRetry} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
