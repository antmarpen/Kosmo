import { describe, expect, it } from "vitest";
import { applyAgentSwitch, displayedAgentValues, resetAgentOverride, updateReferenceDeltas } from "./agentOverrides";

describe("AI agent override state", () => {
  it("separates live inherited display values from intentional overrides", () => {
    const displayed = displayedAgentValues({ agent: { model: "new", reasoning_effort: null, mcp_ids: ["a", "b"], skill_ids: ["s"] }, overrides: { model: "custom", added_mcp_ids: ["c"], removed_mcp_ids: ["a"] } });
    expect(displayed).toEqual({ model: "custom", reasoning_effort: undefined, mcp_ids: ["b", "c"], skill_ids: ["s"] });
  });
  it("does not rebase persisted deltas when baseline changes", () => {
    const state = { added_mcp_ids: ["c"], removed_mcp_ids: ["a"] };
    displayedAgentValues({ agent: { model: "m", mcp_ids: ["a", "b"], skill_ids: [] }, overrides: state });
    expect(state).toEqual({ added_mcp_ids: ["c"], removed_mcp_ids: ["a"] });
  });
  it("clears all overrides on agent switch and reset removes scalar override", () => {
    expect(applyAgentSwitch({ model: "m", reasoning_effort: "high", added_mcp_ids: ["x"], removed_skill_ids: ["s"] })).toEqual({});
    expect(resetAgentOverride({ model: "x", reasoning_effort: "high" }, "model")).toEqual({ reasoning_effort: "high" });
  });
  it("updates delta while retaining unrelated removal intent", () => {
    expect(updateReferenceDeltas(["a", "b"], { added_mcp_ids: ["c"], removed_mcp_ids: ["gone"] }, ["b", "c"])).toEqual({ added_mcp_ids: ["c"], removed_mcp_ids: ["gone", "a"] });
  });
});
