import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import { api } from "@/api/auth";
import { ProviderModelSelect } from "./ProviderModelSelect";

vi.mock("@/api/auth", () => ({ api: { GET: vi.fn(), POST: vi.fn() } }));
const get = vi.mocked(api.GET);
const post = vi.mocked(api.POST);
const providers = (...items: { id: string; name: string; provider_type: string }[]) => ({ data: items.map((item) => ({ ...item, visibility: "personal", verification_status: "verified", auth_present: true })) });
const props = (runtime = "opencode", model = "saved-model", onChange = vi.fn()) => ({ runtime, model, onChange });

describe("ProviderModelSelect", () => {
  beforeEach(() => { get.mockReset(); post.mockReset(); get.mockResolvedValue(providers({ id: "c1", name: "Main", provider_type: "opencode" }) as never); post.mockResolvedValue({ data: { valid: true, models: ["new-model"] } } as never); });

  it("preserves saved provider type and model until edited, discovering only the unique config", async () => {
    render(<ProviderModelSelect {...props()} />);
    expect(await screen.findByRole("option", { name: "new-model" })).toBeInTheDocument();
    expect(screen.getByLabelText("Provider")).toHaveValue("opencode");
    expect(screen.getByLabelText("Model")).toHaveValue("saved-model");
    expect(post).toHaveBeenCalledWith("/providers/opencode/config/verify", { body: { config_id: "c1" } });
  });

  it("shows no model choice and makes no discovery request for multiple matching configs", async () => {
    get.mockResolvedValue(providers({ id: "c1", name: "One", provider_type: "opencode" }, { id: "c2", name: "Two", provider_type: "opencode" }) as never);
    const onChange = vi.fn();
    render(<ProviderModelSelect {...props("opencode", "saved", onChange)} />);
    expect(await screen.findByText(/chosen when/i)).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("stores only provider type and model, clearing model on type edit", async () => {
    const onChange = vi.fn();
    render(<ProviderModelSelect {...props("opencode", "", onChange)} />);
    await screen.findByRole("option", { name: "new-model" });
    fireEvent.change(screen.getByLabelText("Model"), { target: { value: "new-model" } });
    expect(onChange).toHaveBeenLastCalledWith("opencode", "new-model");
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "" } });
    expect(onChange).toHaveBeenLastCalledWith("", "");
  });

  it("does not offer unavailable provider types", async () => {
    render(<ProviderModelSelect {...props("claude", "legacy-model")} />);
    const select = await screen.findByLabelText("Provider");
    expect([...select.querySelectorAll("option")].map((option) => option.value)).toEqual(["claude", "", "opencode"]);
    expect(screen.getByLabelText("Model")).toHaveValue("legacy-model");
  });

  it("ignores a stale discovery response after provider selection changes", async () => {
    let resolve!: (value: unknown) => void;
    post.mockReturnValueOnce(new Promise((done) => { resolve = done; }) as never);
    get.mockResolvedValue(providers({ id: "c1", name: "Main", provider_type: "opencode" }, { id: "c2", name: "Second", provider_type: "other" }) as never);
    function Harness() { const [runtime, setRuntime] = useState(""); const [model, setModel] = useState(""); return <ProviderModelSelect runtime={runtime} model={model} onChange={(nextRuntime, nextModel) => { setRuntime(nextRuntime); setModel(nextModel); }} />; }
    render(<Harness />);
    await screen.findByRole("option", { name: "opencode" });
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "opencode" } });
    await waitFor(() => expect(post).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "" } });
    resolve({ data: { valid: true, models: ["stale"] } });
    await waitFor(() => expect(screen.queryByRole("option", { name: "stale" })).not.toBeInTheDocument());
  });

  it("shows an in-control spinner and live label during model discovery", async () => {
    let resolve!: (value: unknown) => void;
    post.mockReturnValueOnce(new Promise((done) => { resolve = done; }) as never);
    render(<ProviderModelSelect {...props("opencode", "")} />);
    const status = await screen.findByRole("status");
    expect(status).toHaveAttribute("aria-label", expect.stringMatching(/Loading models/i));
    expect(status.querySelector('[data-slot="icon"]')).toHaveClass("animate-spin");
    expect(status).toHaveClass("inset-0", "justify-center");
    expect(status).not.toHaveClass("absolute", "right-3");
    expect(screen.getByLabelText("Model")).toHaveTextContent(/Loading models/i);
    resolve({ data: { valid: true, models: ["new-model"] } });
    await screen.findByRole("option", { name: "new-model" });
  });
});
