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
});
