import { describe, expect, it } from "vitest";

import en from "./locales/en.json";
import es from "./locales/es.json";

/** Collects every leaf value as a [dotted key path, value] pair. */
function collectLeafEntries(
  value: unknown,
  prefix = "",
): Array<[key: string, value: string]> {
  if (typeof value === "string") return [[prefix, value]];
  if (value === null || typeof value !== "object") {
    throw new TypeError(`Catalog leaf at "${prefix}" must be a string`);
  }
  return Object.entries(value).flatMap(([key, child]) =>
    collectLeafEntries(child, prefix ? `${prefix}.${key}` : key),
  );
}

/** Collects dotted key paths for every leaf value in a nested catalog. */
function collectLeafKeys(value: unknown, prefix = ""): string[] {
  return collectLeafEntries(value, prefix).map(([key]) => key);
}

/**
 * Detects encoding-corruption leftovers in the Spanish catalog: a literal `?`
 * standing in for an accented character (`"sesi?n"`), a mangled opening `¿`
 * (`"?Detener esta tarea?"`), or `…` rendered as a trailing `?` (`"Creando?"`).
 * A legitimate Spanish `?` is always opened by `¿`, so every unmatched
 * question mark is corruption.
 */
function isMojibake(value: string): boolean {
  if (!value.includes("?")) return false;
  const questionMarks = value.match(/\?/gu)?.length ?? 0;
  const openingMarks = value.match(/¿/gu)?.length ?? 0;
  if (questionMarks !== openingMarks) return true;
  return value.indexOf("?") < value.indexOf("¿");
}

describe("translation catalogs", () => {
  it("en and es expose exactly the same key structure", () => {
    expect(collectLeafKeys(es).sort()).toEqual(collectLeafKeys(en).sort());
  });

  it("only contains non-empty string leaf values in both languages", () => {
    for (const [locale, catalog] of [
      ["en", en],
      ["es", es],
    ] as const) {
      for (const key of collectLeafKeys(catalog)) {
        const value = key
          .split(".")
          .reduce<unknown>(
            (acc, part) => (acc as Record<string, unknown>)[part],
            catalog,
          );
        expect(value, `${locale}:${key}`).toEqual(expect.any(String));
        expect(String(value).trim().length, `${locale}:${key}`).toBeGreaterThan(0);
      }
    }
  });

  it("exposes the common and auth namespaces required by WP-02", () => {
    for (const catalog of [en, es]) {
      expect(Object.keys(catalog)).toEqual(expect.arrayContaining(["common", "auth"]));
      expect(catalog.common?.cancel).toEqual(expect.any(String));
      expect(catalog.common?.submit).toEqual(expect.any(String));
      expect(catalog.auth?.login?.title).toEqual(expect.any(String));
      expect(catalog.auth?.login?.username).toEqual(expect.any(String));
      expect(catalog.auth?.login?.password).toEqual(expect.any(String));
      expect(catalog.auth?.login?.action).toEqual(expect.any(String));
    }
  });

  it("does not contain mojibake in Spanish values", () => {
    for (const [key, value] of collectLeafEntries(es)) {
      expect(isMojibake(value), `es:${key} is "${value}"`).toBe(false);
    }
  });

  it("repairs the previously corrupted Spanish values", () => {
    expect(es.auth?.login?.pending).toBe("Iniciando sesión…");
    expect(es.auth?.login?.error).toBe(
      "No se pudo iniciar sesión. Comprueba el usuario y la contraseña.",
    );
    expect(es.auth?.login?.logout).toBe("Cerrar sesión");
    expect(es.tasks?.list?.empty).toBe("Aún no hay tareas");
    expect(es.tasks?.topic).toBe("Tema de análisis");
    expect(es.tasks?.submitError).toBe(
      "No se pudo crear la tarea. Inténtalo de nuevo.",
    );
    expect(es.tasks?.confirmStop).toBe("¿Detener esta tarea?");
    expect(es.tasks?.noNodes).toBe("Aún no hay pasos registrados.");
    expect(es.tasks?.notes?.validation_passed).toBe(
      "La validación se completó correctamente.",
    );
    expect(es.tasks?.notes?.input_requested).toBe(
      "El flujo solicita información adicional.",
    );
    expect(es.tasks?.notes?.input_answer).toBe("Se envió una respuesta.");
    expect(es.tasks?.noArtifacts).toBe("Aún no hay artefactos.");
    expect(es.tasks?.notesTitle).toBe("Notas de ejecución");
    expect(es.errors?.workflow?.not_found).toBe("No se encontró el flujo.");
    expect(es.errors?.auth?.invalid_credentials).toBe(
      "El usuario o la contraseña no son válidos.",
    );
    expect(es.errors?.agent?.input_missing).toBe(
      "El agente solicitó datos que no están disponibles.",
    );
    expect(es.errors?.script?.failed).toBe("Falló la ejecución del script.");
    expect(es.errors?.script?.timeout).toBe(
      "Se agotó el tiempo de ejecución del script.",
    );
    expect(es.errors?.task?.not_found).toBe("No se encontró la tarea.");
    expect(es.editor?.code).toBe("Código");
    expect(es.editor?.method).toBe("Método");
    expect(es.editor?.codePlaceholder).toBe(
      "Código Python que se ejecuta cuando el flujo llega a este nodo.",
    );
    expect(es.editor?.invalidJson).toBe("Introduce un objeto JSON válido.");
    // The ellipsis placeholders were mangled in both catalogs.
    expect(en.tasks?.submitting).toBe("Creating…");
    expect(en.tasks?.loading).toBe("Loading…");
    expect(en.editor?.codePlaceholder).toBe(
      "Python code that runs when the workflow reaches this node.",
    );
  });

  it("exposes the shared action and user-menu vocabulary", () => {
    expect(en.common?.add).toBe("Add");
    expect(es.common?.add).toBe("Añadir");
    expect(en.common?.edit).toBe("Edit");
    expect(es.common?.edit).toBe("Editar");
    expect(en.common?.delete).toBe("Delete");
    expect(es.common?.delete).toBe("Eliminar");
    expect(en.common?.confirm).toBe("Confirm");
    expect(es.common?.confirm).toBe("Confirmar");
    expect(en.app?.userMenu).toBe("User menu");
    expect(es.app?.userMenu).toBe("Menú de usuario");
  });

  it("exposes the provider friendly-name vocabulary", () => {
    expect(en.providers?.name).toBe("Name");
    expect(es.providers?.name).toBe("Nombre");
    expect(en.providers?.namePlaceholder).toEqual(expect.any(String));
    expect(es.providers?.namePlaceholder).toEqual(expect.any(String));
    expect(en.providers?.wizard?.steps?.name).toEqual(expect.any(String));
    expect(es.providers?.wizard?.steps?.name).toEqual(expect.any(String));
    expect(en.providers?.wizard?.stepDescriptions?.name).toEqual(
      expect.any(String),
    );
    expect(es.providers?.wizard?.stepDescriptions?.name).toEqual(
      expect.any(String),
    );
    expect(en.providers?.wizard?.configKept).toBe(
      "Keeping the saved configuration file unless you upload a new one.",
    );
    expect(es.providers?.wizard?.configKept).toBe(
      "Se conserva el archivo de configuración guardado a menos que subas uno nuevo.",
    );
    expect(en.providers?.wizard?.authKept).toEqual(expect.any(String));
    expect(es.providers?.wizard?.authKept).toEqual(expect.any(String));
    expect(en.providers?.delete?.title).toEqual(expect.any(String));
    expect(en.providers?.delete?.description).toEqual(expect.any(String));
    expect(en.providers?.delete?.confirm).toBe("Delete");
    expect(es.providers?.delete?.confirm).toBe("Eliminar");
  });

  it("exposes provider friendly-name validation errors", () => {
    expect(en.errors?.provider?.name_required).toBe(
      "A configuration name is required.",
    );
    expect(en.errors?.provider?.name_duplicate).toBe(
      "You already have a configuration with this name for this provider.",
    );
    expect(es.errors?.provider?.name_required).toBe(
      "El nombre de la configuración es obligatorio.",
    );
    expect(es.errors?.provider?.name_duplicate).toBe(
      "Ya tienes una configuración con este nombre para este proveedor.",
    );
  });

  it("exposes the provider wizard connection-test vocabulary", () => {
    expect(en.providers?.wizard?.testAction).toBe("Test connection");
    expect(es.providers?.wizard?.testAction).toBe("Probar conexión");
    expect(en.providers?.wizard?.testing).toBe("Testing…");
    expect(es.providers?.wizard?.testing).toBe("Probando…");
    expect(en.providers?.wizard?.verifiedWith).toBe(
      "Connection verified with {{model}} ({{latency}} ms).",
    );
    expect(es.providers?.wizard?.verifiedWith).toBe(
      "Conexión verificada con {{model}} ({{latency}} ms).",
    );
    expect(en.providers?.wizard?.verifiedOtherSelected).toBe(
      "Now selected: {{model}}. Run the test again to verify it.",
    );
    expect(es.providers?.wizard?.verifiedOtherSelected).toBe(
      "Ahora seleccionado: {{model}}. Vuelve a ejecutar la prueba para verificarlo.",
    );
    expect(en.providers?.wizard?.connectionTitle).toBe("Test the connection");
    expect(es.providers?.wizard?.connectionTitle).toBe("Prueba la conexión");
    expect(en.providers?.wizard?.connectionDescription).toEqual(
      expect.any(String),
    );
    expect(es.providers?.wizard?.connectionDescription).toEqual(
      expect.any(String),
    );
  });

  // --- WP-12: shared catalog controls and safe Markdown ---

  it("exposes the shared catalog list state vocabulary (WP-12)", () => {
    expect(en.catalog?.list?.loading).toBe("Loading…");
    expect(es.catalog?.list?.loading).toBe("Cargando…");
    expect(en.catalog?.list?.retry).toBe("Retry");
    expect(es.catalog?.list?.retry).toBe("Reintentar");
  });

  it("exposes the shared catalog scope-control vocabulary (WP-12)", () => {
    expect(en.catalog?.scope?.legend).toBe("Availability");
    expect(es.catalog?.scope?.legend).toBe("Disponibilidad");
    expect(en.catalog?.scope?.personal).toBe("Just me");
    expect(es.catalog?.scope?.personal).toBe("Solo para mí");
    expect(en.catalog?.scope?.group).toBe("A managed group");
    expect(es.catalog?.scope?.group).toBe("Un grupo que gestiono");
    expect(en.catalog?.scope?.global).toBe("Everyone (global)");
    expect(es.catalog?.scope?.global).toBe("Para todos (global)");
    expect(en.catalog?.scope?.groupLabel).toBe("Group");
    expect(es.catalog?.scope?.groupLabel).toBe("Grupo");
    expect(en.catalog?.scope?.chooseGroup).toBe("Choose a group");
    expect(es.catalog?.scope?.chooseGroup).toBe("Selecciona un grupo");
  });

  it("exposes the shared searchable-selection vocabulary (WP-12)", () => {
    expect(en.catalog?.selection?.searchPlaceholder).toBe("Search…");
    expect(es.catalog?.selection?.searchPlaceholder).toBe("Buscar…");
    expect(en.catalog?.selection?.noResults).toBe(
      "No results match “{{query}}”.",
    );
    expect(es.catalog?.selection?.noResults).toBe(
      "Ningún resultado coincide con «{{query}}».",
    );
    expect(en.catalog?.selection?.remove).toBe("Remove {{name}}");
    expect(es.catalog?.selection?.remove).toBe("Quitar {{name}}");
    expect(en.catalog?.selection?.clear).toBe("Clear selection");
    expect(es.catalog?.selection?.clear).toBe("Quitar la selección");
    expect(en.catalog?.selection?.unavailable).toBe("Unavailable");
    expect(es.catalog?.selection?.unavailable).toBe("No disponible");
  });

  it("exposes the safe Markdown preview vocabulary (WP-12)", () => {
    expect(en.catalog?.markdown?.empty).toBe("Nothing written yet.");
    expect(es.catalog?.markdown?.empty).toBe("Todavía no hay nada escrito.");
  });

  it("translates the backend catalog runtime error keys (WP-12)", () => {
    // Raised by the worker resolver as CATALOG_REFERENCE_UNAVAILABLE with
    // safe {kind, id} parameters (agent/mcp/skill).
    expect(en.errors?.catalog?.reference_unavailable).toBe(
      "The referenced {{kind}} entry is unavailable. It may have been deleted or you may no longer have access to it.",
    );
    expect(es.errors?.catalog?.reference_unavailable).toBe(
      "La entrada de tipo {{kind}} referenciada no está disponible. Puede que se haya eliminado o que ya no tengas acceso a ella.",
    );
    // Raised as CATALOG_DECRYPTION_UNAVAILABLE when stored MCP secrets
    // cannot be decrypted (blocking, never silent).
    expect(en.errors?.mcp_server?.encryption_unavailable).toBe(
      "The platform encryption configuration is unavailable, so MCP secrets cannot be stored or read safely. Ask an administrator to check the configuration.",
    );
    expect(es.errors?.mcp_server?.encryption_unavailable).toBe(
      "La configuración de cifrado de la plataforma no está disponible, así que no se pueden guardar ni leer los secretos del MCP de forma segura. Pide a un administrador que revise la configuración.",
    );
  });

  it("translates the backend agent CRUD error keys (WP-12)", () => {
    const requiredKeys = [
      "field_required",
      "scope_invalid",
      "scope_forbidden",
      "global_admin_only",
      "name_invalid",
      "model_invalid",
      "reasoning_effort_invalid",
      "instructions_invalid",
      "runtime_invalid",
      "reference_ids_invalid",
      "reference_unavailable",
      "name_duplicate",
      "not_found",
      "forbidden",
    ] as const;
    for (const key of requiredKeys) {
      expect(en.errors?.agent?.[key], `en:errors.agent.${key}`).toEqual(
        expect.any(String),
      );
      expect(es.errors?.agent?.[key], `es:errors.agent.${key}`).toEqual(
        expect.any(String),
      );
    }
    expect(en.errors?.agent?.global_admin_only).toBe(
      "Only administrators can create global agents.",
    );
    expect(es.errors?.agent?.global_admin_only).toBe(
      "Solo los administradores pueden crear agentes globales.",
    );
  });

  it("translates the backend skill CRUD error keys (WP-12)", () => {
    const requiredKeys = [
      "field_required",
      "name_invalid",
      "name_too_long",
      "scope_invalid",
      "global_admin_only",
      "group_forbidden",
      "forbidden",
      "name_duplicate",
      "not_found",
      "description_invalid",
      "instructions_invalid",
    ] as const;
    for (const key of requiredKeys) {
      expect(en.errors?.skill?.[key], `en:errors.skill.${key}`).toEqual(
        expect.any(String),
      );
      expect(es.errors?.skill?.[key], `es:errors.skill.${key}`).toEqual(
        expect.any(String),
      );
    }
    expect(en.errors?.skill?.name_duplicate).toBe(
      "You already have a skill with this name in this scope.",
    );
    expect(es.errors?.skill?.name_duplicate).toBe(
      "Ya tienes una habilidad con este nombre en este ámbito.",
    );
  });

  it("translates the backend MCP server CRUD error keys (WP-12)", () => {
    const requiredKeys = [
      "field_required",
      "invalid",
      "name_invalid",
      "name_reserved",
      "scope_invalid",
      "scope_forbidden",
      "global_admin_only",
      "name_duplicate",
      "not_found",
      "forbidden",
    ] as const;
    for (const key of requiredKeys) {
      expect(
        en.errors?.mcp_server?.[key],
        `en:errors.mcp_server.${key}`,
      ).toEqual(expect.any(String));
      expect(
        es.errors?.mcp_server?.[key],
        `es:errors.mcp_server.${key}`,
      ).toEqual(expect.any(String));
    }
    expect(en.errors?.mcp_server?.name_reserved).toBe(
      "This name is reserved for the platform validator.",
    );
    expect(es.errors?.mcp_server?.name_reserved).toBe(
      "Este nombre está reservado para el validador de la plataforma.",
    );
  });
});
