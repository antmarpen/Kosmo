import { useLayoutEffect, useRef } from "react";

/** Focus the first enabled, non-hidden form control when a catalog form mounts. */
export function useCatalogFormFocus() {
  const formRef = useRef<HTMLFormElement>(null);

  useLayoutEffect(() => {
    const form = formRef.current;
    if (!form) return;

    const controls = form.querySelectorAll<HTMLElement>(
      'input:not([type="hidden"]), select, textarea, button, [tabindex]:not([tabindex="-1"])',
    );
    const control = Array.from(controls).find((candidate) => {
      if (
        candidate.matches(":disabled") ||
        candidate.closest('[hidden], [aria-hidden="true"], [inert]')
      ) {
        return false;
      }
      return true;
    });
    control?.focus();
  }, []);

  return formRef;
}
