import type { MaterialSymbol } from "material-symbols";

/**
 * Centralized registry of Material Symbols Rounded ligature names.
 *
 * Map a semantic role (nav item, action, state) to the font ligature here
 * instead of hard-coding strings in components. The `satisfies` clause
 * type-checks every entry against the ligature list shipped with the
 * installed `material-symbols` package, so a typo or a renamed glyph fails
 * the build instead of rendering a raw word.
 *
 * The keys were chosen to match the shell navigation and the standard action
 * vocabulary (see `docs/specs/ui-refresh-and-provider-instances.md`, AC-01).
 * Extend this object as new consumers need icons; the `Icon` component's
 * `name` prop only accepts keys of this registry.
 */
export const ICON_NAMES = {
  // Navigation — tasks group.
  tasks: "checklist",
  add: "add",
  history: "history",
  // Navigation — workspace group.
  workspace: "workspaces",
  workflows: "account_tree",
  applications: "apps",
  context: "layers",
  // Navigation — catalog group.
  catalog: "grid_view",
  agents: "smart_toy",
  mcp: "hub",
  skills: "psychology",
  extensions: "extension",
  providers: "cable",
  // Navigation — administration group.
  administration: "admin_panel_settings",
  audit: "fact_check",
  settings: "settings",
  // Shell controls.
  sidebarCollapse: "left_panel_close",
  sidebarExpand: "left_panel_open",
  openMenu: "menu",
  close: "close",
  logout: "logout",
  userMenu: "account_circle",
  // Row and form actions.
  edit: "edit",
  delete: "delete",
  stop: "stop",
  send: "send",
  save: "save",
  run: "play_arrow",
  login: "login",
  connectionTest: "network_check",
  search: "search",
  // Feedback and status.
  check: "check",
  error: "error",
  spinner: "progress_activity",
  info: "info",
} as const satisfies Readonly<Record<string, MaterialSymbol>>;

/** Semantic icon name accepted by the `Icon` component. */
export type MaterialIconName = keyof typeof ICON_NAMES;
