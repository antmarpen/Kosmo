import { describe, expect, it } from "vitest";
import { deserializeWorkflow, serializeWorkflow } from "./serialization";
import { resolveOutputDescriptor } from "./outputContracts";
import type { WorkflowDefinition } from "./model";

const validation = { format: "json" as const, json_schema: { type: "object" }, rules_code: "return True" };
const legacy = { levels: ["syntax", "format", "rules"].map((name) => ({ name, message_key: name, params_schema: {} })) };
const definition = (nodes: WorkflowDefinition["nodes"], edges: WorkflowDefinition["edges"] = []): WorkflowDefinition => ({ schema_version: "v1", name: "test", nodes, edges });

describe("per-output contracts", () => {
  it("normalizes legacy AI validation per declared output and saves canonical shape", () => {
    const legacy = { type: "ai", id: "ai", agent: { runtime: "opencode", model: "m", instructions: "" }, prompt_template: "p", inputs: [], outputs: ["a", "b"], validation, max_validation_cycles: 3 } as unknown as WorkflowDefinition["nodes"][number];
    const state = deserializeWorkflow(definition([{ type: "start", id: "s", input_form: [] }, legacy, { type: "end", id: "e", inputs: [] }]));
    const ai = state.definition.nodes.find((n) => n.type === "ai")!;
    expect(ai.type === "ai" && ai.output_validation).toEqual({ a: validation, b: validation });
    expect(ai.type === "ai" && ai.output_validation?.a).not.toBe(ai.type === "ai" && ai.output_validation?.b);
    expect(JSON.stringify(serializeWorkflow(state))).not.toContain('"validation"');
  });

  it("resolves Start form value and unknown script value constrained only by validation", () => {
    const state = deserializeWorkflow(definition([
      { type: "start", id: "s", input_form: [{ name: "count", type: "number", required: true }] },
      { type: "script", id: "sc", code: "return count", inputs: ["count"], outputs: ["result"], output_validation: { result: validation } },
      { type: "end", id: "e", inputs: [] },
    ], [{ from: "s", to: "sc" }]));
    expect(resolveOutputDescriptor(state, "s", "count")).toMatchObject({ name: "count", sourceNodeId: "s", sourceNodeType: "start", kind: "form-value", valueType: "number" });
    expect(resolveOutputDescriptor(state, "sc", "result")).toMatchObject({ kind: "artifact", valueType: "unknown/runtime", validation });
  });

  it("preserves Start validation when round-tripping and exposes legacy repair", () => {
    const historical = definition([
      { type: "start", id: "s", input_form: [{ name: "payload", type: "string", required: true, validation: legacy }] } as unknown as WorkflowDefinition["nodes"][number],
      { type: "script", id: "sc", code: "", inputs: [], outputs: [] },
      { type: "end", id: "e", inputs: [] },
    ], [{ from: "s", to: "sc" }]);
    const state = deserializeWorkflow(historical);
    expect((state.definition.nodes[0] as any).input_form[0].validation).toEqual(legacy);
    expect(serializeWorkflow(state).nodes[0]).toMatchObject({ input_form: [{ validation: legacy }] });
    expect(resolveOutputDescriptor(state, "s", "payload")).toMatchObject({ repairRequired: true, unresolvedLegacyValidation: legacy });
  });

  it("preserves canonical validation on Start fields", () => {
    const field = { name: "payload", type: "string" as const, required: true, validation };
    const state = deserializeWorkflow(definition([{ type: "start", id: "s", input_form: [field] }, { type: "end", id: "e", inputs: [] }]));
    expect(serializeWorkflow(state).nodes[0]).toMatchObject({ input_form: [field] });
  });

  it("uses only actual incoming edges to identify direct producers", () => {
    const state = deserializeWorkflow(definition([
      { type: "start", id: "s", input_form: [{ name: "shared", type: "string", required: true, validation }] },
      { type: "script", id: "unrelated", code: "", inputs: [], outputs: ["shared"] },
      { type: "script", id: "consumer", code: "", inputs: [], outputs: [] },
      { type: "end", id: "e", inputs: [] },
    ], [{ from: "unrelated", to: "consumer" }, { from: "s", to: "consumer" }]));
    expect(resolveOutputDescriptor(state, "s", "shared")?.validation).toEqual(validation);
    expect(resolveOutputDescriptor(state, "unrelated", "shared")?.sourceNodeId).toBe("unrelated");
  });

  it("retains orphaned validation and reports it as a keyed issue", () => {
    const state = deserializeWorkflow(definition([
      { type: "start", id: "s", input_form: [] },
      { type: "script", id: "sc", code: "", inputs: [], outputs: [], output_validation: { gone: validation } },
      { type: "end", id: "e", inputs: [] },
    ]));
    expect(state.definition.nodes.find((n) => n.type === "script")).toMatchObject({ output_validation: { gone: validation } });
    expect(resolveOutputDescriptor(state, "sc", "gone")).toMatchObject({ orphaned: true });
  });

  it("preserves phase metadata through load and save", () => {
    const source = { ...definition([{ type: "start", id: "s", input_form: [] }, { type: "end", id: "e", inputs: [] }]), phases: [{ id: "p", node_ids: ["s", "e"] }] };
    expect(serializeWorkflow(deserializeWorkflow(source)).phases).toEqual(source.phases);
  });
});
