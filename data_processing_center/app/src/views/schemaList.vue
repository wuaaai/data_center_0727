<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Search } from '@element-plus/icons-vue'
import { addMetadataTable, cancelMetadataTable, getAllTables } from '../api/dataManage'

const props = defineProps({
  datasource: {
    type: Object,
    default: null
  }
})

const emit = defineEmits(['back'])

const businessDomainOptions = ['预算草案', '预算执行', '预算调整', '决算']
const budgetBookOptions = ['一般公共预算', '国有资本经营预算', '政府性基金', '社会保险']

const loading = ref(false)
const operatingTableName = ref('')
const tableRows = ref([])

const queryForm = reactive({
  tableName: '',
  businessDomain: '',
  budgetBook: ''
})

const appliedQuery = reactive({
  tableName: '',
  businessDomain: '',
  budgetBook: ''
})

const filteredRows = computed(() => {
  return tableRows.value.filter((row) => {
    const commentName = String(row.table_comment || '').toLowerCase()
    const tableName = String(row.table_name || '').toLowerCase()
    const businessDomain = String(row.business_domain || '')
    const budgetBook = String(row.budget_book || '')

    const matchName =
      !appliedQuery.tableName ||
      commentName.includes(appliedQuery.tableName.toLowerCase()) ||
      tableName.includes(appliedQuery.tableName.toLowerCase())
    const matchDomain = !appliedQuery.businessDomain || businessDomain === appliedQuery.businessDomain
    const matchBudget = !appliedQuery.budgetBook || budgetBook === appliedQuery.budgetBook

    return matchName && matchDomain && matchBudget
  })
})

const loadTableData = async () => {
  loading.value = true
  try {
    const response = await getAllTables()
    tableRows.value = Array.isArray(response.data) ? response.data : []
  } catch (error) {
    ElMessage.error(error.message || '获取表列表失败')
    tableRows.value = []
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  appliedQuery.tableName = queryForm.tableName.trim()
  appliedQuery.businessDomain = queryForm.businessDomain
  appliedQuery.budgetBook = queryForm.budgetBook
}

const toggleMetadataStatus = async (row) => {
  operatingTableName.value = row.table_name
  try {
    if (row.metadata_status === '已添加') {
      await cancelMetadataTable({ table_name: row.table_name })
      ElMessage.success('已取消表元数据。')
    } else {
      await addMetadataTable({
        table_comment: row.table_comment,
        table_name: row.table_name,
        business_domain: row.business_domain || '未归类'
      })
      ElMessage.success('已添加为表元数据。')
    }
    await loadTableData()
  } catch (error) {
    ElMessage.error(error.message || '元数据操作失败')
  } finally {
    operatingTableName.value = ''
  }
}

const getStatusLabel = (status) => {
  return status === '已添加' ? '已添加' : '未添加'
}

const getActionLabel = (status) => {
  return status === '已添加' ? '取消' : '添加为元数据'
}

onMounted(() => {
  loadTableData()
})
</script>

<template>
  <div class="schema-page">
    <section class="schema-toolbar-panel">
      <div class="schema-header">
        <div>
          <div class="schema-top-line">
            <el-button text :icon="ArrowLeft" class="back-button" @click="emit('back')">返回</el-button>
            <h3>数据表列表</h3>
          </div>
          <p>
            当前数据源：{{ props.datasource?.name || '未选择数据源' }}
            <span v-if="props.datasource?.databaseName"> / {{ props.datasource.databaseName }}</span>
          </p>
        </div>
      </div>

      <div class="search-row">
        <el-input
          v-model="queryForm.tableName"
          class="search-item search-name"
          placeholder="请输入表名称搜索"
          :prefix-icon="Search"
          clearable
        />
        <el-select v-model="queryForm.businessDomain" class="search-item" placeholder="选择财政系统业务域" clearable>
          <el-option v-for="item in businessDomainOptions" :key="item" :label="item" :value="item" />
        </el-select>
        <el-select v-model="queryForm.budgetBook" class="search-item" placeholder="选择财政厅四本账" clearable>
          <el-option v-for="item in budgetBookOptions" :key="item" :label="item" :value="item" />
        </el-select>
        <el-button type="primary" class="search-button" @click="handleSearch">搜索</el-button>
      </div>
    </section>

    <section class="schema-table-panel">
      <el-table
        :data="filteredRows"
        v-loading="loading"
        element-loading-text="正在加载数据表..."
        class="schema-table"
        style="width: 100%"
        table-layout="auto"
      >
        <el-table-column label="序号" width="80">
          <template #default="{ row, $index }">
            {{ row.index || $index + 1 }}
          </template>
        </el-table-column>
        <el-table-column prop="table_comment" label="表中文名/注释" min-width="220" show-overflow-tooltip />
        <el-table-column prop="table_name" label="表名(物理名)" min-width="240" show-overflow-tooltip />
        <el-table-column prop="business_domain" label="所属业务域" min-width="140" />
        <el-table-column label="元数据状态" min-width="150">
          <template #default="{ row }">
            <div class="metadata-status">
              <span class="status-dot" :class="row.metadata_status === '已添加' ? 'is-added' : 'is-unadded'"></span>
              <span :class="row.metadata_status === '已添加' ? 'status-text-added' : 'status-text-unadded'">
                {{ getStatusLabel(row.metadata_status) }}
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="180" fixed="right">
          <template #default="{ row }">
            <el-button
              text
              :type="row.metadata_status === '已添加' ? 'danger' : 'primary'"
              :loading="operatingTableName === row.table_name"
              @click="toggleMetadataStatus(row)"
            >
              {{ getActionLabel(row.metadata_status) }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.schema-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-height: 100%;
}

.schema-toolbar-panel,
.schema-table-panel {
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(148, 163, 184, 0.14);
  box-shadow: 0 20px 60px rgba(15, 23, 42, 0.08);
  border-radius: 8px;
}

.schema-toolbar-panel {
  padding: 20px 22px;
}

.schema-header h3 {
  margin: 0;
  font-size: 24px;
}

.schema-header p {
  margin: 8px 0 0;
  color: #64748b;
}

.schema-top-line {
  display: flex;
  align-items: center;
  gap: 10px;
}

.back-button {
  padding-left: 0;
}

.search-row {
  margin-top: 18px;
  display: grid;
  grid-template-columns: minmax(240px, 1.4fr) minmax(180px, 1fr) minmax(180px, 1fr) 120px;
  gap: 14px;
}

.search-item {
  width: 100%;
}

.search-button {
  height: 40px;
}

.schema-table-panel {
  padding: 10px;
}

.schema-table {
  width: 100%;
}

.metadata-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
}

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.status-dot.is-added {
  background: #22c55e;
  box-shadow: 0 0 0 6px rgba(34, 197, 94, 0.08);
}

.status-dot.is-unadded {
  background: #cbd5e1;
  box-shadow: 0 0 0 6px rgba(203, 213, 225, 0.2);
}

.status-text-added {
  color: #16a34a;
}

.status-text-unadded {
  color: #94a3b8;
}

:deep(.schema-table .el-table__inner-wrapper::before) {
  display: none;
}

:deep(.schema-table th.el-table__cell) {
  background: rgba(248, 250, 252, 0.96);
  color: #64748b;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

:deep(.schema-table td.el-table__cell),
:deep(.schema-table th.el-table__cell) {
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
}

:deep(.schema-table .el-table__row:hover > td.el-table__cell) {
  background: rgba(82, 99, 255, 0.04);
}

@media (max-width: 1080px) {
  .search-row {
    grid-template-columns: 1fr;
  }
}
</style>
