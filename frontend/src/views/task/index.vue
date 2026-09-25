<template>
  <section class="page" data-module="task">
    <header class="page-head">
      <div>
        <h2>检修任务管理</h2>
        <p class="page-desc">维护检修任务，围绕任务编号、关联计划、检修人员、开始时间做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记检修任务</button>
        <button class="btn" type="button" @click="exportRows">导出检修任务清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div class="batch-bar">
      <span>已选 {{ selectedIds.length }} 条任务</span>
      <input v-model="assignee" placeholder="接收任务的检修人员" />
      <button
        class="btn primary"
        type="button"
        :disabled="!selectedIds.length || batchRunning"
        @click="runBatchReassign"
      >
        按该人员批量转派
      </button>
      <button class="btn ghost" type="button" :disabled="!selectedIds.length" @click="clearSelection">
        清空选择
      </button>
      <span class="batch-tip">已确认完成的任务不能再次转派；遗留问题数超过检修项目数的任务会单独标出。</span>
    </div>

    <div v-if="batchResult" class="result-panel">
      <p class="result-title">{{ batchResult.message }}</p>
      <p v-if="flaggedCodes.length" class="result-fail">
        遗留超标（遗留问题数超过检修项目数）：{{ flaggedCodes.join('、') }}
      </p>
      <ul class="result-list">
        <li
          v-for="item in batchResult.results"
          :key="item.id"
          :class="item.ok ? 'result-ok' : 'result-fail'"
        >
          {{ item.code || `#${item.id}` }}：{{ item.message }}
          <span v-if="item.flagged" class="badge">遗留超标</span>
        </li>
      </ul>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th class="check-col">
            <input type="checkbox" :checked="allChecked" @change="toggleAll" />
          </th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-abnormal': isOverloaded(row) }">
          <td class="check-col">
            <input
              type="checkbox"
              :checked="selectedIds.includes(Number(row.id))"
              @change="toggleRow(Number(row.id))"
            />
          </td>
          <td v-for="column in columns" :key="column">
            <span v-if="column === '遗留问题数' && isOverloaded(row)" class="danger-text">
              {{ row[column] ?? '—' }}
            </span>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无检修任务数据，可先登记检修任务</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条检修任务记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type Row = Record<string, string | number | null>
type BatchItem = { id: number; code: string; ok: boolean; flagged: boolean; message: string }
type BatchResult = {
  ok: boolean
  message: string
  total: number
  succeeded: number
  failed: number
  flagged: number
  results: BatchItem[]
}

const ENDPOINT = '/api/task'
const columns = ["任务编号", "关联计划", "检修人员", "开始时间", "完成时间", "检修项目数", "遗留问题数", "任务状态"]
const actions = ["开始任务", "提交验收", "确认完成"]

const stats = ref([
  { label: '待开始任务', value: 0 },
  { label: '检修中任务', value: 0 },
  { label: '遗留问题合计', value: 0 },
  { label: '遗留超标任务', value: 0 },
])

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const selectedIds = ref<number[]>([])
const assignee = ref('')
const batchRunning = ref(false)
const batchResult = ref<BatchResult | null>(null)

const allChecked = computed(
  () => rows.value.length > 0 && rows.value.every((row) => selectedIds.value.includes(Number(row.id))),
)
const flaggedCodes = computed(() =>
  (batchResult.value?.results ?? [])
    .filter((item) => item.flagged)
    .map((item) => item.code || `#${item.id}`),
)

function toInt(value: unknown): number {
  const parsed = Number.parseInt(String(value ?? ''), 10)
  return Number.isNaN(parsed) ? 0 : parsed
}

function isOverloaded(row: Row): boolean {
  return toInt(row['遗留问题数']) > toInt(row['检修项目数'])
}

function toggleRow(id: number) {
  selectedIds.value = selectedIds.value.includes(id)
    ? selectedIds.value.filter((item) => item !== id)
    : [...selectedIds.value, id]
}

function toggleAll() {
  selectedIds.value = allChecked.value ? [] : rows.value.map((row) => Number(row.id))
}

function clearSelection() {
  selectedIds.value = []
  batchResult.value = null
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '检修任务登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('检修任务动作未生效，请稍后重试')
    }
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检修任务操作失败'
  }
}

async function runBatchReassign() {
  errorMessage.value = ''
  batchResult.value = null
  const target = assignee.value.trim()
  if (!target) {
    errorMessage.value = '请先填写接收任务的检修人员'
    return
  }
  batchRunning.value = true
  try {
    const response = await request(`${ENDPOINT}/batch-reassign`, {
      method: 'POST',
      body: JSON.stringify({ ids: selectedIds.value, assignee: target }),
    })
    const payload = (await response.json()) as BatchResult
    if (!response.ok) {
      throw new Error('批量转派请求未生效，请稍后重试')
    }
    if (!payload.ok && payload.results.length === 0) {
      errorMessage.value = payload.message
      return
    }
    batchResult.value = payload
    selectedIds.value = []
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量转派失败'
  } finally {
    batchRunning.value = false
  }
}

async function loadSummary() {
  try {
    const payload = await fetchJson<Record<string, number>>(`${ENDPOINT}/summary`)
    stats.value = [
      { label: '待开始任务', value: payload['待开始任务'] ?? 0 },
      { label: '检修中任务', value: payload['检修中任务'] ?? 0 },
      { label: '遗留问题合计', value: payload['遗留问题合计'] ?? 0 },
      { label: '遗留超标任务', value: payload['遗留超标任务'] ?? 0 },
    ]
  } catch {
    // 统计卡片读取失败不阻断列表，列表报错会统一提示
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('检修任务列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检修任务列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadSummary()
})
</script>
