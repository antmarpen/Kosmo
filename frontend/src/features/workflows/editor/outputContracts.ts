import type { WorkflowEditorState, WorkflowNode, ValidationContract, FormField } from "./model";

export type OutputDescriptor = {
  name: string;
  sourceNodeId: string;
  sourceNodeType: WorkflowNode["type"];
  kind: "form-value" | "artifact" | "http-response" | "workflow-output";
  valueType: string;
  validation?: ValidationContract;
  referencedValidation?: ValidationContract;
  orphaned?: boolean;
  referenceUnavailable?: boolean;
  referenceCycle?: boolean;
  repairRequired?: boolean;
  unresolvedLegacyValidation?: unknown;
};

export type ActiveWorkflowDefinitions = Record<string, WorkflowEditorState["definition"] | undefined>;

/** Resolve chip provenance without mutating authoring state. Unknown runtime artifact types stay explicit. */
export function resolveOutputDescriptor(
  state: WorkflowEditorState,
  sourceNodeId: string,
  name: string,
  activeDefinitions: ActiveWorkflowDefinitions = {},
  visitedWorkflowIds: readonly string[] = [],
): OutputDescriptor | undefined {
  const node = state.definition.nodes.find((item) => item.id === sourceNodeId);
  if (!node) return undefined;
  const configured = "output_validation" in node ? node.output_validation?.[name] : undefined;
  const orphaned = "output_validation" in node && Boolean(node.output_validation && !("outputs" in node ? node.outputs : []).includes(name));
  if (node.type === "start") {
    const field = node.input_form.find((item) => item.name === name);
      if (!field) return undefined;
      const validation = field.validation;
      const legacy = validation && "levels" in validation ? validation : undefined;
      return { ...descriptor(node, name, "form-value", field.type, legacy ? undefined : validation as ValidationContract | undefined), ...(legacy ? { repairRequired: true, unresolvedLegacyValidation: legacy } : {}) };
  }
  if (node.type === "http") return name === "response" ? descriptor(node, name, "http-response", "unknown/runtime", configured) : undefined;
  if (node.type === "script" || node.type === "ai") return (orphaned || node.outputs.includes(name))
    ? { ...descriptor(node, name, "artifact", "unknown/runtime", configured), ...(orphaned ? { orphaned: true } : {}) } : undefined;
  if (node.type === "workflow") {
    const ref = activeDefinitions[node.workflow_id];
    const cycle = visitedWorkflowIds.includes(node.workflow_id);
    let producer: { node: WorkflowNode; name: string } | undefined;
    if (ref && !cycle) {
      const byId = new Map(ref.nodes.map((candidate) => [candidate.id, candidate]));
      const end = ref.nodes.find((candidate) => candidate.type === "end");
      const incoming = ref.edges.filter((edge) => edge.to === end?.id);
      const sources = incoming.flatMap((edge) => {
        const candidate = byId.get(edge.from);
        const outputs = candidate?.type === "start" ? candidate.input_form.map((field: FormField) => field.name) : candidate && "outputs" in candidate ? candidate.outputs : [];
        return outputs.includes(name) && candidate ? [{ node: candidate, name }] : [];
      });
      producer = sources[0];
    }
    return { ...descriptor(node, name, "workflow-output", "unknown/runtime", configured), ...(producer && "output_validation" in producer.node && producer.node.output_validation?.[name] ? { referencedValidation: producer.node.output_validation[name] } : {}), ...(!ref ? { referenceUnavailable: true } : {}), ...(cycle ? { referenceCycle: true } : {}), ...(orphaned ? { orphaned: true } : {}) };
  }
  return undefined;
}

function descriptor(node: WorkflowNode, name: string, kind: OutputDescriptor["kind"], valueType: string, validation?: ValidationContract): OutputDescriptor {
  return { name, sourceNodeId: node.id, sourceNodeType: node.type, kind, valueType, ...(validation ? { validation } : {}) };
}
