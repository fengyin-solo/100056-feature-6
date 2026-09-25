<template>
  <section class="page" data-module="task">
    <header class="page-head">
      <div>
        <h2>检修任务管理</h2>
        <p class="page-desc">维护检修任务，围绕任务编号、关联计划、检修人员、开始时间做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记检修任务</button>
        <button class="btn" type="button" @click="openBatch">批量转派</button>
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

    <div v-if="batchOpen" class="batch-bar">
      <span>已选 {{ selectedIds.length }} 条任务，转派给同一批检修人员：</span>
      <input v-model="assignee" placeholder="检修人员，多人用顿号隔开" />
      <button class="btn primary" type="button" @click="submitBatch">确认转派</button>
      <button class="btn ghost" type="button" @click="closeBatch">取消</button>
    </div>

    <div v-if="batchResult" class="batch-result">
      <p class="batch-summary">{{ batchResult.message }}</p>
      <table class="data-table">
        <thead>
          <tr><th>任务编号</th><th>转派结果</th><th>说明</th><th>遗留标记</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in batchResult.results" :key="item.id">
            <td>{{ item.code || item.id }}</td>
            <td>{{ item.ok ? '成功' : '失败' }}</td>
            <td>{{ item.message }}</td>
            <td><span v-if="item.flagged" class="flag-tag">遗留超标</span><span v-else>—</span></td>
          </tr>
        </tbody>
      </table>
      <button class="btn ghost" type="button" @click="batchResult = null">收起结果</button>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th class="check-cell">
            <input
              type="checkbox"
              :checked="allChecked"
              title="全选当前列表"
              @change="toggleAll"
            />
          </th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td class="check-cell">
            <input
              type="checkbox"
              :checked="selectedIds.includes(Number(row.id))"
              @change="toggleOne(Number(row.id))"
            />
          </td>
          <td v-for="column in columns" :key="column">
            <template v-if="column === '遗留问题数'">
              {{ row[column] ?? '—' }}
              <span v-if="isFlagged(row)" class="flag-tag">遗留超标</span>
            </template>
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
            <button class="link" type="button" @click="openDetail(row)">详情</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无检修任务数据，可先登记检修任务</td>
        </tr>
      </tbody>
    </table>

    <div v-if="detail" class="detail-panel">
      <h3>任务详情：{{ detail['任务编号'] ?? detail.id }}</h3>
      <dl class="detail-grid">
        <template v-for="column in columns" :key="column">
          <dt>{{ column }}</dt>
          <dd>{{ detail[column] ?? '—' }}</dd>
        </template>
      </dl>
      <button class="btn ghost" type="button" @click="detail = null">关闭详情</button>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条检修任务记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

type BatchItem = {
  id: number
  code: string
  ok: boolean
  flagged: boolean
  message: string
}

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
const statuses = ["待开始", "检修中", "待验收", "已完成"]

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<{ label: string; value: number }[]>([])
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const selectedIds = ref<number[]>([])
const batchOpen = ref(false)
const assignee = ref('')
const batchResult = ref<BatchResult | null>(null)
const detail = ref<Row | null>(null)

const allChecked = computed(() => rows.value.length > 0 && rows.value.every((row) => selectedIds.value.includes(Number(row.id))))

function toNumber(value: unknown): number | null {
  const parsed = Number(value)
  return Number.isFinite(parsed) && String(value ?? '').trim() !== '' ? parsed : null
}

function isFlagged(row: Row): boolean {
  const leftover = toNumber(row['遗留问题数'])
  const items = toNumber(row['检修项目数'])
  return leftover !== null && items !== null && leftover > items
}

function toggleOne(id: number) {
  selectedIds.value = selectedIds.value.includes(id)
    ? selectedIds.value.filter((item) => item !== id)
    : [...selectedIds.value, id]
}

function toggleAll() {
  selectedIds.value = allChecked.value ? [] : rows.value.map((row) => Number(row.id))
}

function openBatch() {
  if (!selectedIds.value.length) {
    errorMessage.value = '请先勾选需要转派的检修任务'
    return
  }
  errorMessage.value = ''
  batchResult.value = null
  batchOpen.value = true
}

function closeBatch() {
  batchOpen.value = false
  assignee.value = ''
}

async function submitBatch() {
  errorMessage.value = ''
  const target = assignee.value.trim()
  if (!target) {
    errorMessage.value = '请填写转派后的检修人员'
    return
  }
  try {
    const response = await request(`${ENDPOINT}/batch-reassign`, {
      method: 'POST',
      body: JSON.stringify({ ids: selectedIds.value, assignee: target }),
    })
    if (!response.ok) {
      throw new Error('批量转派请求未生效，请稍后重试')
    }
    batchResult.value = (await response.json()) as BatchResult
    closeBatch()
    selectedIds.value = []
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量转派失败'
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('检修任务详情读取失败')
    }
    detail.value = (await response.json()) as Row
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检修任务详情读取失败'
  }
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
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('检修任务动作未生效，请稍后重试')
    }
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检修任务操作失败'
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) {
      throw new Error('检修任务统计读取失败')
    }
    const payload = await response.json()
    stats.value = payload.cards ?? []
  } catch {
    stats.value = []
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
  void loadStats()
})
</script>
