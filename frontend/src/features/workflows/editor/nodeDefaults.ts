import type { WorkflowNode } from "./model";

const validationLevels = ["syntax", "semantic", "contract"].map((name) => ({ name, message_key: `workflow.validation.${name}`, params_schema: {} }));

export function createNode(type: WorkflowNode["type"], id: string): WorkflowNode {
  switch (type) {
    case "start": return { type, id, input_form: [] };
    case "script": return { type, id, code: "", inputs: [], outputs: [] };
    case "http": return { type, id, method: "GET", url: "", outputs: [] };
    case "ai": return { type, id, agent: { runtime: "opencode", model: "", instructions: "" }, prompt_template: "", inputs: [], outputs: [], validation: { levels: validationLevels }, max_validation_cycles: 3 };
    case "decision": return { type, id, selected_next_node_id: "" };
    case "workflow": return { type, id, workflow_id: "" };
    case "end": return { type, id };
  }
}
