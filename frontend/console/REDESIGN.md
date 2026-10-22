# Console redesign (Vercel Geist + shadcn-svelte)

One-pass visual and UX refactor approved by the user on 2026-10-22 (DECISIONS.md). Styling, layout,
components, theming and accessibility only: no route, API call, auth logic, `api_endpoint.ts` or
`config.ts` change, and no new data fetching.

## Feature map

| Area | Route | Role | Main pieces |
|------|-------|------|-------------|
| Home | `/` | viewer | area cards, live HARD/SOFT counts |
| Review queue + case | `/review?…&case=` | reviewer | QueueFilters, QueueList (j/k/Enter), CaseView → CaseHeader, FlagConsole → EvidencePane / ResolutionForm / DryRunPanel, apply bar |
| Rules | `/review/rules` | reviewer (deactivate: admin) | rules table, simulate, RuleForm |
| Docs viewer | `/docs/{id}/viewer?anchor=` | viewer | page render + bbox overlays, image, table, code, text, fallback notice, MetaPanel, translate |
| Benchmark | `/benchmark`, `/suites/[s]`, `/cases/[id]`, `/runs/[id]`, `/compare`, `/retrieval` | viewer (edit: reviewer) | suites, runs, CaseEditor, results + ResultDrilldown, compare, RetrievalLab |
| Entities | `/entities` | viewer | placeholder until its API exists |
| Ops | `/ops` | viewer (failed tasks: admin) | FailedTasks table; sync, queues and cost still to come |
| Settings | `/settings/[section]` | admin | SectionMenu + section panel |
| Audit | `/audit` | reviewer | URL filters, AuditTimeline |

## Shell and page layout

- Left sidebar (240 px): product mark, the six sections filtered by role, live review counts, live
  socket state, signed-in user with the highest role, sign out. `aria-current="page"` marks the area.
- Top bar (48 px, sticky): breadcrumb derived from the path (`breadcrumbs.ts`, also the document
  title) and the theme menu (Light / Dark / System).
- Skip link to `#main`. Every page uses `Page.svelte`: header (title, description, actions, `below`),
  optional filter bar, content, optional details panel on the right (stacks under 1280 px).
- Review is a split work screen: the queue is a full-height pane with its own scroll; the case
  scrolls with the window and ends in a sticky apply bar.

## Tokens (`src/app.css`, written once)

| Layer | Names | Notes |
|-------|-------|-------|
| Geist palette | `--ds-background-{100,200}`, `--ds-gray-{100…1000}`, `--ds-gray-alpha-*`, `--ds-{blue,green,amber,red}-{100,400,700,900,1000}`, `--ds-purple-*` | light on `:root`, dark on `.dark`; Geist step roles (100 bg … 900 secondary text, 1000 text) |
| Semantic (shadcn names) | `--background --foreground --card --popover --primary --secondary --muted --accent --border --input --ring --link --sidebar-*` | monochrome base; the one accent is blue, used for focus rings and links |
| Status | `--hard* --warn* --ok* --info* --handwriting*` (text, `-bg`, `-border`) | severity and outcome only: HARD, SOFT/warning, passed, info/suggestion, handwriting overlay |
| Shape | `--radius` 0.5 rem → `rounded-sm…4xl`; `--ds-shadow-{sm,md}` | Geist radii 6/8/12 px |
| Type | `--font-sans` Geist Variable, `--font-mono` Geist Mono Variable | 14 px body, 13 px dense rows, 12 px labels, 11 px badges; tabular numerals via `.num` |

All map into Tailwind through `@theme inline` (`bg-hard-bg`, `text-muted-foreground`, …).
Component classes: `.field`, `.field-label`, `.code-block`, `.num`, `.data-table` (sticky 32 px
header under the top bar via `--sticky-top`), `.table-scroll`, `.panel*`, `.kv`, `.eyebrow`.

## Theme

`app.html` sets `<html class="dark">` before first paint from `localStorage["dcl-theme"]`
(light | dark, absent = system). `theme.svelte.ts` follows `prefers-color-scheme` changes and the
toggle. No flash on load.

## Components

shadcn-svelte (bits-ui) generated under `src/lib/components/ui`: alert, badge, button, card,
dropdown-menu, input, label, native-select, separator, skeleton, table, textarea, tooltip.
Console shell components under `src/lib/components/shell`: Sidebar, TopBar, ThemeToggle, Page,
PageHeader, Notice (error = `role=alert`, success = `role=status`), EmptyState, ToneBadge,
SeverityBadge, RoleGate. Native `<select>`, `<input>` and radio/checkbox elements are kept on
purpose (keyboard, form semantics and the existing tests); they wear the `.field` style.

## Decisions

- Queue stays an ordered list, not a table: it is a narrow master pane with two-line rows; the
  other lists (rules, suites, runs, results, audit headers, retrieval hits) are tables.
- Secondary queue filters fold under "More filters", open by itself when one is set.
- Viewer overlays: cited = blue, handwriting = purple dashed, flag = red, with a legend.
- Evidence and resolution sit side by side only at 1536 px and up; below that they stack.
- Reduced motion: all animation and transition durations collapse under
  `prefers-reduced-motion: reduce`.

## Risks and follow-ups

- Viewer overlay regions are not keyboard-focusable (they are `role="note"` with labels and titles).
- Benchmark run status colors match on substrings (fail/error, done/complete/pass); confirm the
  backend's status set.
- `.wiki/frontend/console-shell-auth.md` still names `NavBar.svelte` (now `Sidebar.svelte` +
  `TopBar.svelte`); the wiki is outside this change's scope.
- Entities is a placeholder; Ops shows only failed tasks so far.
