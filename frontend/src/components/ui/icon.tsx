import * as React from "react";

import { cn } from "@/lib/utils";

import { ICON_NAMES, type MaterialIconName } from "./icon-names";

export type { MaterialIconName } from "./icon-names";

/** CSS class defined by the self-hosted `material-symbols/rounded.css`. */
const MATERIAL_SYMBOLS_CLASS = "material-symbols-rounded";

/** Optical size axis range of the Material Symbols variable font. */
const OPSZ_MIN = 20;
const OPSZ_MAX = 48;

function clampOpsz(px: number): number {
  return Math.min(OPSZ_MAX, Math.max(OPSZ_MIN, px));
}

export type IconProps = Omit<React.ComponentProps<"span">, "children"> & {
  /** Ligature name; must come from the `ICON_NAMES` registry. */
  name: MaterialIconName;
  /** Icon size as a px number or any CSS font-size string. Default 20. */
  size?: number | string;
  /** Variable-font weight axis (100–700). Default 400 (outline). */
  weight?: number;
  /** Fill the glyph instead of the outline variant. Default false. */
  fill?: boolean;
  /**
   * Accessible name for meaningful icons: renders `role="img"` with this
   * label. When omitted (or empty) the icon is decorative
   * (`aria-hidden="true"`). The ligature text itself never reaches the
   * accessibility tree.
   */
  label?: string;
};

/**
 * Shared Material Symbols Rounded icon (self-hosted variable font, no
 * network request). `name` is a semantic key from the `ICON_NAMES`
 * registry; the component renders its mapped ligature inside a span styled
 * by `material-symbols/rounded.css` (imported globally in `src/index.css`).
 */
function Icon({
  name,
  size = 20,
  weight = 400,
  fill = false,
  label,
  className,
  style,
  ...props
}: IconProps) {
  const labelled = typeof label === "string" && label.length > 0;
  const px = typeof size === "number" ? size : null;
  const fontVariationSettings = `'FILL' ${fill ? 1 : 0}, 'wght' ${weight}, 'GRAD' 0, 'opsz' ${
    px === null ? 24 : clampOpsz(px)
  }`;

  return (
    <span
      data-slot="icon"
      role={labelled ? "img" : undefined}
      aria-label={labelled ? label : undefined}
      aria-hidden={labelled ? undefined : true}
      className={cn(MATERIAL_SYMBOLS_CLASS, "shrink-0", className)}
      style={{
        fontSize: size,
        fontVariationSettings,
        ...style,
      }}
      {...props}
    >
      {ICON_NAMES[name]}
    </span>
  );
}

export { Icon };
