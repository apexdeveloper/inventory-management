# Vue 3 analysis checklist

Checks that need reading the code. For each, the signal to look for, why it matters, and the usual suggestion. Only report a check when you can point at a specific location.

## Rendering performance

| Check | Signal | Why it matters | Suggestion |
|---|---|---|---|
| Filtering or sorting in the template | `v-for="x in items.filter(...)"`, `.slice()`, `.sort()`, or a method call as the `v-for` source | Re-runs on every render of the component, including renders unrelated to the list; `.sort()` also mutates the source | Move to a `computed` property |
| Expensive calls in interpolations inside `v-for` | `{{ calc(item) }}` where `calc` loops, parses dates, or searches arrays | Runs per row per render | Precompute per row in a `computed` map, or add fields to the computed list |
| `v-if` vs `v-show` | Element toggled often (tabs, dropdowns) using `v-if` with a heavy subtree, or rarely shown modal using `v-show` | `v-if` rebuilds on each toggle; `v-show` renders hidden content up front | `v-show` for frequent toggles, `v-if` for rarely opened content |
| Keys on filtered or sorted lists | `:key` is the index, or missing, on a list that the filters or sorting reorder | Vue reuses the wrong elements, so input state and transitions land on the wrong rows | Key by a stable id (`sku`, `id`, `order_number`, `month`) |
| Large static data made reactive | Big constant arrays or lookup tables in `ref()`/`reactive()` that never change | Deep reactive proxies cost memory and time to create | Plain `const` outside `setup`, or `markRaw`/`shallowRef` when it is large |

## Reactivity and data flow

| Check | Signal | Why it matters | Suggestion |
|---|---|---|---|
| Watcher that derives state | `watch(a, () => { b.value = f(a) })` | Extra render cycle, and state can go stale | `const b = computed(() => f(a.value))` |
| Deep watcher on large objects | `{ deep: true }` on filter or data objects | Walks the whole object on every change | Watch the specific fields, e.g. `watch(() => [filters.month, filters.warehouse], ...)` |
| Sequential independent requests | Several `await api.x()` one after another in a loader | Total wait is the sum, not the max | `await Promise.all([...])` |
| Refetch storms | Several watchers on filter fields each triggering a load | One filter change fires several requests | One watcher on the combined filter state, or use the existing `useFilters` composable |
| Derived data stored in refs | A ref updated by hand after the source changes | Breaks the project rule "raw data in refs, derived data in computed" | Turn it into a `computed` property |
| Missing cleanup | `addEventListener`, `setInterval`, or document click handlers in `onMounted` with no `onUnmounted` | Leaks and duplicate handlers after navigating back and forth | Remove them in `onUnmounted` |

## Code reuse

| Check | Signal | Suggestion |
|---|---|---|
| Duplicated formatters | Same or near-same `formatDate`, `formatMoney`, `translateCategory` in several files | One function in `client/src/utils/` (next to `currency.js`), with options for the differences |
| Local copy of an existing util | Component defines a function that `utils/` or `composables/` already exports | Import the shared one; check that its behavior matches first |
| Repeated modal shell | Several components with the same overlay, header, close button, footer markup and CSS | A `BaseModal.vue` with `title` prop, default and `footer` slots, `close` emit, Escape and backdrop-click handling in one place |
| Repeated dropdown behavior | `toggleDropdown` and `handleBlur` copied between menu components | A `useDropdown()` composable returning `isOpen`, `toggle`, `close` |
| Repeated status badges | Same status-to-class mapping (`getStockStatusClass`, priority colors) in several files | One mapping in `utils/` plus a small `StatusBadge.vue` |
| Repeated data loading | Same loading/error/fetch pattern in many views | A `useApi(fetcher, deps)` composable returning `data`, `loading`, `error`, `reload` |
| Copied CSS | The same rule blocks in several components' scoped styles | Shared component (when markup repeats too) or a global class in `client/src/App.vue` |

## Structure

| Check | Signal | Suggestion |
|---|---|---|
| Oversized component | Over about 500 lines, or a template with several independent sections (KPI cards, charts, tables) | Split into child components by section; each takes its data through props |
| Mixed API styles | Both `<script setup>` and `setup()` returning bindings | Consistency only; suggest `<script setup>` for new and touched files, not a mass rewrite |
| Eager route imports | `import View from './views/View.vue'` for every route | `component: () => import('./views/View.vue')` for heavy, rarely visited views; keep the landing view eager |
| Dead components | A `.vue` file nothing imports or routes to | Delete it or wire it up; confirm with the user which |
| Prop drilling | The same prop passed through two or more levels just to reach a child | Composable or `provide`/`inject` |
