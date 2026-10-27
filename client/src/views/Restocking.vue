<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else-if="rankedItems.length === 0" class="card empty-state">{{ t('restocking.noForecasts') }}</div>
    <div v-else>
      <div class="card budget-card">
        <div class="budget-header">
          <label for="budget-slider" class="budget-label">{{ t('restocking.budget') }}</label>
          <span class="budget-value">{{ formatMoney(budget) }}</span>
        </div>
        <input
          id="budget-slider"
          v-model.number="budget"
          type="range"
          class="budget-slider"
          min="0"
          :max="maxBudget"
          :step="BUDGET_STEP"
          :aria-valuetext="formatMoney(budget)"
        />
        <div class="budget-scale">
          <span>{{ formatMoney(0) }}</span>
          <span>{{ formatMoney(maxBudget) }}</span>
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.selectedTotal') }}</div>
          <div class="stat-value">{{ formatMoney(selectedTotal) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.remainingBudget') }}</div>
          <div class="stat-value">{{ formatMoney(remainingBudget) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.itemsSelected') }}</div>
          <div class="stat-value">{{ selectedItems.length }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.orderLeadTime') }}</div>
          <div class="stat-value">{{ t('restocking.days', { count: orderLeadTime }) }}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <div>
            <h3 class="card-title">{{ t('restocking.recommendations') }}</h3>
            <p class="card-hint">{{ t('restocking.recommendationHint') }}</p>
          </div>
          <button
            type="button"
            class="place-order-btn"
            :disabled="selectedItems.length === 0 || submitting"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placing') : t('restocking.placeOrder') }}
          </button>
        </div>

        <div v-if="submitError" class="error">{{ submitError }}</div>
        <div v-if="lastOrder" class="confirmation" role="status">
          <span>{{ t('restocking.orderPlaced', { orderNumber: lastOrder.order_number, days: lastOrder.lead_time_days }) }}</span>
          <router-link to="/orders" class="confirmation-link">{{ t('restocking.viewOrders') }}</router-link>
        </div>

        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th class="col-include">{{ t('restocking.table.include') }}</th>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.itemName') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th class="num">{{ t('restocking.table.quantity') }}</th>
                <th class="num">{{ t('restocking.table.unitCost') }}</th>
                <th class="num">{{ t('restocking.table.lineCost') }}</th>
                <th class="num">{{ t('restocking.table.leadTime') }}</th>
                <th>{{ t('restocking.table.status') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in rows"
                :key="row.item_sku"
                :class="{ 'row-inactive': row.status !== 'recommended' }"
              >
                <td class="col-include">
                  <!-- Checked means "in the order". Over-budget items can't be added directly;
                       raising the budget or unchecking a higher-ranked item makes room for them. -->
                  <input
                    type="checkbox"
                    :checked="row.status === 'recommended'"
                    :disabled="row.status === 'overBudget'"
                    :aria-label="row.item_name"
                    @change="toggleItem(row.item_sku, $event)"
                  />
                </td>
                <td><strong>{{ row.item_sku }}</strong></td>
                <td>{{ translateProductName(row.item_name) }}</td>
                <td>
                  <span :class="['badge', row.trend]">{{ t(`trends.${row.trend}`) }}</span>
                </td>
                <td class="num">{{ row.forecasted_demand.toLocaleString() }}</td>
                <td class="num">{{ formatMoney(row.unit_cost, 2) }}</td>
                <td class="num"><strong>{{ formatMoney(row.lineCost) }}</strong></td>
                <td class="num">{{ t('restocking.days', { count: row.lead_time_days }) }}</td>
                <td>
                  <span :class="['badge', STATUS_BADGE[row.status]]">
                    {{ t(`restocking.itemStatus.${row.status}`) }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrencyWithDecimals } from '../utils/currency'

const BUDGET_STEP = 500

// Lower rank = restocked first
const TREND_RANK = { increasing: 0, stable: 1, decreasing: 2 }

const STATUS_BADGE = {
  recommended: 'success',
  overBudget: 'warning',
  excluded: 'info'
}

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, translateProductName } = useI18n()

    const loading = ref(true)
    const error = ref(null)
    const forecasts = ref([])
    const budget = ref(0)
    // SKUs the user unchecked; a reactive Set so the selection recomputes on change
    const excluded = ref(new Set())
    const submitting = ref(false)
    const submitError = ref(null)
    const lastOrder = ref(null)

    // Budget amounts are held in USD; formatting converts for the JPY locale
    const formatMoney = (amount, decimals = 0) => {
      return formatCurrencyWithDecimals(amount, currentCurrency.value, decimals)
    }

    const growthRate = (f) => {
      return f.current_demand > 0 ? (f.forecasted_demand - f.current_demand) / f.current_demand : 0
    }

    const rankedItems = computed(() => {
      return forecasts.value
        .map(f => ({
          ...f,
          // Round to cents so summed line costs don't drift from the server's total
          lineCost: Math.round(f.forecasted_demand * f.unit_cost * 100) / 100
        }))
        .sort((a, b) => {
          const trendDiff = (TREND_RANK[a.trend] ?? 3) - (TREND_RANK[b.trend] ?? 3)
          return trendDiff !== 0 ? trendDiff : growthRate(b) - growthRate(a)
        })
    })

    const maxBudget = computed(() => {
      const total = rankedItems.value.reduce((sum, item) => sum + item.lineCost, 0)
      return Math.ceil(total / 1000) * 1000
    })

    // Greedy fill in priority order. An item that doesn't fit is skipped rather than
    // ending the walk, so cheaper lower-ranked items can still use the leftover budget.
    // Works in integer cents so repeated float subtraction can't reject an item that fits exactly.
    const selectedSkus = computed(() => {
      const selected = new Set()
      let remainingCents = Math.round(budget.value * 100)
      for (const item of rankedItems.value) {
        if (excluded.value.has(item.item_sku)) continue
        const costCents = Math.round(item.lineCost * 100)
        if (costCents <= remainingCents) {
          selected.add(item.item_sku)
          remainingCents -= costCents
        }
      }
      return selected
    })

    const rows = computed(() => {
      return rankedItems.value.map(item => {
        let status = 'overBudget'
        if (excluded.value.has(item.item_sku)) status = 'excluded'
        else if (selectedSkus.value.has(item.item_sku)) status = 'recommended'
        return { ...item, status }
      })
    })

    const selectedItems = computed(() => rows.value.filter(row => row.status === 'recommended'))

    const selectedTotal = computed(() => {
      return selectedItems.value.reduce((sum, item) => sum + item.lineCost, 0)
    })

    const remainingBudget = computed(() => Math.max(0, budget.value - selectedTotal.value))

    // Items ship together, so the order's lead time is its slowest item's
    const orderLeadTime = computed(() => {
      return selectedItems.value.reduce((max, item) => Math.max(max, item.lead_time_days), 0)
    })

    const toggleItem = (sku, event) => {
      const next = new Set(excluded.value)
      if (next.has(sku)) next.delete(sku)
      else next.add(sku)
      excluded.value = next
      lastOrder.value = null
      // Re-including an item that no longer fits leaves its status non-recommended, so the
      // bound :checked value doesn't change and Vue won't undo the browser's toggle. Sync it.
      event.target.checked = selectedSkus.value.has(sku)
    }

    // A changed selection makes the previous confirmation stale
    watch(budget, () => {
      lastOrder.value = null
    })

    const loadForecasts = async () => {
      try {
        loading.value = true
        error.value = null
        forecasts.value = await api.getDemandForecasts()
        budget.value = Math.round(maxBudget.value / 2 / BUDGET_STEP) * BUDGET_STEP
      } catch (err) {
        error.value = t('restocking.loadFailed') + ': ' + err.message
      } finally {
        loading.value = false
      }
    }

    const placeOrder = async () => {
      if (selectedItems.value.length === 0) return
      try {
        submitting.value = true
        submitError.value = null
        lastOrder.value = await api.createRestockOrder(
          // The server prices each line from its own catalog, so only SKU and quantity are sent
          selectedItems.value.map(item => ({
            sku: item.item_sku,
            quantity: item.forecasted_demand
          }))
        )
        excluded.value = new Set()
      } catch (err) {
        submitError.value = t('restocking.orderFailed') + ': ' + (err.response?.data?.detail || err.message)
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadForecasts)

    return {
      t,
      translateProductName,
      BUDGET_STEP,
      STATUS_BADGE,
      loading,
      error,
      budget,
      maxBudget,
      rankedItems,
      rows,
      selectedItems,
      selectedTotal,
      remainingBudget,
      orderLeadTime,
      submitting,
      submitError,
      lastOrder,
      formatMoney,
      toggleItem,
      placeOrder
    }
  }
}
</script>

<style scoped>
.budget-card {
  padding: 1.5rem;
}

.budget-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 1rem;
}

.budget-label {
  color: var(--muted);
  font-size: 0.875rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.budget-value {
  font-size: 2rem;
  font-weight: 700;
  color: var(--text);
  letter-spacing: -0.025em;
}

.budget-slider {
  width: 100%;
  cursor: pointer;
}

.budget-scale {
  display: flex;
  justify-content: space-between;
  margin-top: 0.375rem;
  font-size: 0.813rem;
  color: var(--muted);
}

.card-hint {
  margin-top: 0.25rem;
  font-size: 0.813rem;
  color: var(--muted);
}

.place-order-btn {
  flex-shrink: 0;
  margin-left: 1rem;
  padding: 0.625rem 1.25rem;
  background: var(--text);
  color: var(--on-solid);
  border: none;
  border-radius: 8px;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}

.place-order-btn:hover:not(:disabled) {
  background: var(--text);
}

.place-order-btn:disabled {
  background: var(--border-strong);
  cursor: not-allowed;
}

.confirmation {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  background: var(--success-bg);
  border: 1px solid var(--success-border);
  color: var(--success-text);
  padding: 0.875rem 1rem;
  border-radius: 8px;
  margin-bottom: 1rem;
  font-size: 0.938rem;
}

.confirmation-link {
  color: var(--success-text);
  font-weight: 600;
  white-space: nowrap;
}

.col-include {
  width: 70px;
  text-align: center;
}

.num {
  text-align: right;
}

.row-inactive td {
  color: var(--faint);
}

.empty-state {
  text-align: center;
  color: var(--muted);
  padding: 3rem;
}
</style>
