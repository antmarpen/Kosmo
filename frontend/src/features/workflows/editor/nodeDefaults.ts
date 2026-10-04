import type { WorkflowNode } from "./model";

export function createNode(type: WorkflowNode["type"], id: string): WorkflowNode {
  switch (type) {
    case "start": return { type, id, input_form: [] };
    case "script": return { type, id, code: "", inputs: [], outputs: [] };
    case "http": return { type, id, method: "GET", url: "", inputs: [], outputs: ["response"] };
    case "ai": return { type, id, prompt_template: "", inputs: [], outputs: [], output_validation: {}, max_validation_cycles: 3 };
    case "decision": return { type, id, selected_next_node_id: "" };
    case "workflow": return { type, id, workflow_id: "", inputs: [] };
    case "end": return { type, id, inputs: [] };
  }
}
