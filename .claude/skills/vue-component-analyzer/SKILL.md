---
name: vue-component-analyzer
description: Analyze Vue 3 component structure and suggest performance and code-reuse optimizations, as a ranked report with file:line evidence. Use when asked to review, audit, or analyze Vue components, find duplicated component logic or styles, find shared component/composable opportunities, or look for Vue rendering or reactivity performance problems in client/src. Reports only; does not edit code.
---

# Vue Component Analyzer

Produce a ranked, evidence-backed list of performance and reuse improvements for the Vue client. This skill **suggests**; it does not change code. Fixes are handed to the `vue-expert` subagent, which CLAUDE.md requires for any significant `.vue` change.

## Scope

- Default: all of `client/src`.
- If the user names a file, directory, or component, analyze only that, but still check the rest of `client/src` for duplicates of its helpers, markup, and styles. Reuse findings need the wider view.

## Workflow

### 1. Collect the structural inventory

From the repo root:

```bash
python3 -I .claude/skills/vue-component-analyzer/scripts/analyze_vue.py client/src
```

Add `--json` for machine-readable output. The script (standard library only) reports:

- Per-component size by block, script style, and counts of `ref`/`computed`/`watch`
- Components used in a template but never imported
- `v-for` without `:key`, with an index as the key, with `v-if` on the same tag, or calling a method in its source
- Deep watchers
- Helpers defined in several files, and local copies of helpers already exported from `utils/` or `composables/`
- Repeated modal shell markup, and CSS rules duplicated across files
- Components nothing imports
- Routes imported eagerly instead of lazy-loaded

The script works by regex, so **every item is a lead, not a finding**. Read the code at each location before reporting it.

### 2. Confirm the leads

For each lead, open the code and decide:

- **Duplicated helpers:** compare the function bodies. Same name with different behavior (for example, different date formats) is a reuse finding only if the differences can become parameters. Otherwise drop it, or note that the shared name is misleading.
- **Duplicated CSS:** check whether the duplicates are one pattern (modal shell, info grid, buttons) or a coincidence. Only a pattern justifies a shared component or a global class in `client/src/App.vue`, where global styles live.
- **Unreferenced components:** search for dynamic use (`<component :is>`, string names in routes) before calling one dead.
- **Unresolved components:** check `main.js` for `app.component(...)` global registration. If none, this is a bug; report it first.

### 3. Look for what the script can't see

Work through [references/checklist.md](references/checklist.md) for the components in scope, focusing on the largest ones and the ones on the main data path (views that fetch and filter data). These checks need judgment: filtering in templates, watchers that should be computed properties, sequential API calls, reactivity on large data, component boundaries.

### 4. Size performance claims to the real data

Performance suggestions must match the data volume. Check the size of the data a component renders (`server/data/*.json`, or API responses at `http://localhost:8001/api/...` if the server is running). In this app the lists are small, roughly 30 to 250 rows. Re-render cost is rarely the problem at that size, so don't suggest virtualization, memoization, or `shallowRef` without showing the cost is real. Say so plainly when a pattern is technically suboptimal but harmless at current size, and rank it low.

### 5. Report

Use the format below. Rank by impact and confidence, not by category. Bugs (unresolved components, broken keys on filtered or sorted lists) come first.

```markdown
## Vue component analysis: <scope>

<2–3 sentences: overall state, the biggest opportunity, anything broken.>

### Findings

| # | Type | Impact | Effort | Where | Finding | Suggestion |
|---|------|--------|--------|-------|---------|------------|
| 1 | Bug | High | S | `views/Dashboard.vue:289` | ... | ... |
| 2 | Reuse | Medium | M | 6 modal components | ... | ... |

Type: Bug, Performance, Reuse, Structure. Impact: High, Medium, Low. Effort: S (under an hour), M (part of a day), L (more).

### Reuse plan
For each proposed shared piece: name and location (`client/src/components/`, `client/src/composables/`, `client/src/utils/`), its API (props/slots/emits or function signature), which files would adopt it, and what each deletes.

### Checked and fine
Short list of things examined that need no change, so the reader knows they were covered.
```

End by offering to hand the selected findings to `vue-expert`, and wait for the user to choose. Don't start changes yourself.

## Rules

- **Evidence or it doesn't go in.** Every finding needs a `file:line` and a one-line reason that is specific to this code. Leave out generic Vue advice that doesn't point at a real location.
- **Follow project conventions** from CLAUDE.md: raw data in refs, derived data in computed properties; unique `v-for` keys (`sku`, `id`, `month`), not index; the slate/gray design system; no emojis in UI.
- **No new dependencies.** If a suggestion needs a library, say so and present it as optional.
- **Note the migration cost.** For example, converting `setup()` components to `<script setup>` is consistency work, not a performance fix. Rank it as Structure, Low.
