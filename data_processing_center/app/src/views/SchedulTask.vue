<script setup>
import { computed, ref } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { moduleOverviewMap, statusTypeMap } from '../data/modules'

const pageData = moduleOverviewMap.scheduling
const keyword = ref('')

const filteredRows = computed(() => {
  const value = keyword.value.trim().toLowerCase()
  if (!value) {
    return pageData.rows
  }

  return pageData.rows.filter((row) => {
    return (
      row.name.toLowerCase().includes(value) ||
      row.scope.toLowerCase().includes(value) ||
      row.owner.toLowerCase().includes(value)
    )
  })
})

const resolveType = (status) => statusTypeMap[status] || 'info'
</script>

<template>
  <div class="module-page" :style="{ '--accent': pageData.accent }">
    <section class="hero-panel">
      <div class="hero-copy">
        <span class="hero-chip">{{ pageData.heroLabel }}</span>
        <h2>{{ pageData.heroTitle }}</h2>
        <p>{{ pageData.heroDescription }}</p>
      </div>

      <div class="hero-side">
        <span>{{ pageData.sideLabel }}</span>
        <strong>{{ pageData.sideValue }}</strong>
        <p>{{ pageData.sideNote }}</p>
      </div>
    </section>

    <section class="metric-grid">
      <article v-for="card in pageData.statCards" :key="card.label" class="metric-card" :class="`tone-${card.tone}`">
        <div class="metric-label">{{ card.label }}</div>
        <div class="metric-value">{{ card.value }}</div>
        <div class="metric-delta">{{ card.delta }}</div>
      </article>
    </section>

    <section class="table-panel">
      <div class="section-header">
        <div>
          <h3>{{ pageData.tableTitle }}</h3>
          <p>{{ pageData.tableDescription }}</p>
        </div>
        <el-input v-model="keyword" class="table-search" placeholder="搜索调度任务" :prefix-icon="Search" clearable />
      </div>

      <div class="table-wrap">
        <el-table :data="filteredRows" class="module-table" style="width: 100%" table-layout="auto">
          <el-table-column prop="name" label="任务名称" min-width="240" show-overflow-tooltip />
          <el-table-column prop="scope" label="范围" min-width="190" show-overflow-tooltip />
          <el-table-column prop="owner" label="执行方" min-width="140" show-overflow-tooltip />
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <el-tag round :type="resolveType(row.status)" disable-transitions>{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="time" label="更新时间" min-width="160" />
        </el-table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.module-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-height: 100%;
}

.hero-panel,
.table-panel,
.metric-card {
  border: 1px solid rgba(148, 163, 184, 0.14);
  box-shadow: 0 20px 60px rgba(15, 23, 42, 0.08);
}

.hero-panel {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  padding: 24px;
  border-radius: 28px;
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.14), rgba(255, 255, 255, 0.96));
}

.hero-chip {
  display: inline-flex;
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(245, 158, 11, 0.12);
  color: var(--accent);
  font-size: 13px;
  font-weight: 700;
}

.hero-copy h2 {
  margin: 14px 0 8px;
  font-size: 28px;
}

.hero-copy p,
.hero-side span,
.hero-side p,
.metric-label,
.metric-delta,
.section-header p {
  color: #64748b;
}

.hero-copy p {
  margin: 0;
  line-height: 1.75;
}

.hero-side {
  min-width: 260px;
  padding: 18px;
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(148, 163, 184, 0.14);
}

.hero-side strong {
  display: block;
  margin: 10px 0 8px;
  font-size: 28px;
  color: #0f172a;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.metric-card {
  position: relative;
  overflow: hidden;
  padding: 20px;
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.92);
}

.metric-card::after {
  content: "";
  position: absolute;
  inset: auto -24px -24px auto;
  width: 92px;
  height: 92px;
  border-radius: 50%;
  opacity: 0.12;
}

.metric-card.tone-primary::after {
  background: #f59e0b;
}

.metric-card.tone-success::after {
  background: #22c55e;
}

.metric-card.tone-warning::after {
  background: #fb7185;
}

.metric-card.tone-info::after {
  background: #38bdf8;
}

.metric-value {
  margin: 10px 0 8px;
  font-size: 32px;
  font-weight: 700;
  color: #0f172a;
}

.table-panel {
  border-radius: 24px;
  padding: 20px;
  background: rgba(255, 255, 255, 0.92);
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.section-header h3 {
  margin: 0 0 6px;
  font-size: 22px;
}

.section-header p {
  margin: 0;
}

.table-search {
  width: 220px;
}

.table-wrap {
  width: 100%;
  overflow-x: auto;
  margin-top: 16px;
}

.module-table {
  width: 100%;
  min-width: 1040px;
}

:deep(.module-table .el-table__inner-wrapper::before) {
  display: none;
}

:deep(.module-table th.el-table__cell) {
  background: rgba(248, 250, 252, 0.92);
  color: #64748b;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

:deep(.module-table td.el-table__cell),
:deep(.module-table th.el-table__cell) {
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
}

:deep(.module-table .el-table__row:hover > td.el-table__cell) {
  background: rgba(245, 158, 11, 0.04);
}

@media (max-width: 1440px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 1024px) {
  .hero-panel,
  .section-header {
    flex-direction: column;
  }
}

@media (max-width: 640px) {
  .metric-grid {
    grid-template-columns: 1fr;
  }

  .table-search {
    width: 100%;
  }
}
</style>
