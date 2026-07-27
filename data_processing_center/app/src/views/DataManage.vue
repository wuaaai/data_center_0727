<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Delete,
  EditPen,
  Plus,
  RefreshRight,
  Search,
  Setting,
  SwitchButton,
  View
} from '@element-plus/icons-vue'
import { datasourceDemoRows } from '../data/modules'

const emit = defineEmits(['view-detail'])

const datasourceRows = ref(datasourceDemoRows.map((item) => ({ ...item })))
const keyword = ref('')
const page = ref(1)
const pageSize = ref(5)
const drawerVisible = ref(false)
const isEditMode = ref(false)
const editingId = ref(null)

const formState = reactive({
  name: '',
  dbType: 'DM',
  host: '',
  port: 5236,
  databaseName: '',
  username: '',
  password: '',
  description: ''
})

const dbTypeOptions = [
  { label: '达梦 DM', value: 'DM' },
  { label: '崖山 Yashan', value: 'Yashan' }
]

const statusMap = {
  connected: { text: '已连接', color: '#22c55e' },
  failed: { text: '连接失败', color: '#ef4444' },
  syncing: { text: '同步中', color: '#f59e0b' },
  idle: { text: '未连接', color: '#94a3b8' }
}

const filteredRows = computed(() => {
  const value = keyword.value.trim().toLowerCase()
  if (!value) {
    return datasourceRows.value
  }

  return datasourceRows.value.filter((row) => {
    return row.name.toLowerCase().includes(value) || row.databaseName.toLowerCase().includes(value)
  })
})

const pagedRows = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredRows.value.slice(start, start + pageSize.value)
})

const resetForm = () => {
  formState.name = ''
  formState.dbType = 'DM'
  formState.host = ''
  formState.port = 5236
  formState.databaseName = ''
  formState.username = ''
  formState.password = ''
  formState.description = ''
  editingId.value = null
}

const setDefaultPort = () => {
  formState.port = formState.dbType === 'DM' ? 5236 : 1688
}

const openCreateDrawer = () => {
  isEditMode.value = false
  resetForm()
  drawerVisible.value = true
}

const openEditDrawer = (row) => {
  isEditMode.value = true
  editingId.value = row.id
  formState.name = row.name
  formState.dbType = row.dbType
  formState.host = row.host
  formState.port = row.port
  formState.databaseName = row.databaseName
  formState.username = 'readonly_user'
  formState.password = ''
  formState.description = `${row.name} 的静态演示配置项。`
  drawerVisible.value = true
}

const submitForm = () => {
  if (!formState.name || !formState.host || !formState.databaseName) {
    ElMessage.warning('请完整填写数据源名称、主机/IP 和数据库名。')
    return
  }

  if (isEditMode.value && editingId.value !== null) {
    datasourceRows.value = datasourceRows.value.map((row) =>
      row.id === editingId.value
        ? {
            ...row,
            name: formState.name,
            dbType: formState.dbType,
            host: formState.host,
            port: formState.port,
            databaseName: formState.databaseName
          }
        : row
    )
    ElMessage.success('数据源配置已更新。')
  } else {
    datasourceRows.value.unshift({
      id: Date.now(),
      name: formState.name,
      dbType: formState.dbType,
      host: formState.host,
      port: formState.port,
      databaseName: formState.databaseName,
      status: 'idle',
      syncTime: '未同步',
      isDefault: false
    })
    ElMessage.success('已新增静态数据源。')
  }

  page.value = 1
  drawerVisible.value = false
}

const onSearch = () => {
  page.value = 1
}

const handlePageChange = (value) => {
  page.value = value
}

const testConnection = (row) => {
  row.status = 'connected'
  ElMessage.success(`已触发 ${row.name} 的连接测试。`)
}

const setAsDefault = (row) => {
  datasourceRows.value = datasourceRows.value.map((item) => ({
    ...item,
    isDefault: item.id === row.id
  }))
  ElMessage.success(`${row.name} 已设为默认数据源。`)
}

const syncStructure = (row) => {
  row.status = 'syncing'
  row.syncTime = '2026-07-09 09:45:00'
  ElMessage.success(`已触发 ${row.name} 的表结构同步。`)
}

const seeDetail = (row) => {
  emit('view-detail', row)
}

const deleteRow = (row) => {
  datasourceRows.value = datasourceRows.value.filter((item) => item.id !== row.id)
  if (page.value > 1 && pagedRows.value.length === 0) {
    page.value -= 1
  }
  ElMessage.success(`${row.name} 已从静态列表移除。`)
}

const getDbTypeLabel = (type) => (type === 'DM' ? '达梦 DM' : '崖山 Yashan')
</script>

<template>
  <div class="datasource-page">
    <section class="toolbar-panel">
      <div class="toolbar-copy">
        <h3>数据源列表</h3>
        <p>支持按数据源名称或库名搜索，右侧主操作按钮用于新增数据源配置。</p>
      </div>

      <div class="toolbar-actions">
        <el-input
          v-model="keyword"
          class="datasource-search"
          placeholder="搜索数据源名称或库名"
          :prefix-icon="Search"
          clearable
          @input="onSearch"
          @clear="onSearch"
        />
        <el-button type="primary" class="primary-action-button" :icon="Plus" @click="openCreateDrawer">
          新增数据源
        </el-button>
      </div>
    </section>

    <section class="table-panel">
      <div class="table-wrap">
        <el-table :data="pagedRows" class="datasource-table" style="width: 100%" table-layout="auto">
          <el-table-column prop="name" label="数据源名称" min-width="160" show-overflow-tooltip />
          <el-table-column label="数据库类型" min-width="140">
            <template #default="{ row }">
              <span>{{ getDbTypeLabel(row.dbType) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="host" label="主机/IP" min-width="120" show-overflow-tooltip />
          <el-table-column prop="port" label="端口" width="90" />
          <el-table-column prop="databaseName" label="数据库名/服务名" min-width="170" show-overflow-tooltip />
          <el-table-column label="连接状态" min-width="120">
            <template #default="{ row }">
              <div class="status-display">
                <span class="status-dot" :style="{ backgroundColor: statusMap[row.status].color }"></span>
                <span :style="{ color: statusMap[row.status].color }">{{ statusMap[row.status].text }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="syncTime" label="元数据同步时间" min-width="170" show-overflow-tooltip />

          <el-table-column label="操作" min-width="460" fixed="right">
            <template #default="{ row }">
              <div class="row-actions">
                <el-button text :icon="SwitchButton" @click="testConnection(row)">测试连接</el-button>
                <el-button text :icon="Setting" @click="setAsDefault(row)">
                  {{ row.isDefault ? '已设默认' : '设为默认' }}
                </el-button>
                <el-button text :icon="EditPen" @click="openEditDrawer(row)">编辑</el-button>
                <el-button text :icon="Delete" class="danger-text-button" @click="deleteRow(row)">删除</el-button>
                <el-button text :icon="RefreshRight" @click="syncStructure(row)">同步表结构</el-button>
                <el-button text :icon="View" @click="seeDetail(row)">查看详情</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="datasource-pagination">
        <el-pagination
          background
          layout="total, prev, pager, next"
          :page-size="pageSize"
          :total="filteredRows.length"
          :current-page="page"
          @current-change="handlePageChange"
        />
      </div>
    </section>

    <el-drawer
      v-model="drawerVisible"
      :title="isEditMode ? '编辑数据源' : '新增数据源'"
      direction="rtl"
      size="520px"
      class="datasource-drawer"
    >
      <div class="drawer-intro">
        <h4>{{ isEditMode ? '数据源编辑表单' : '数据源新增表单' }}</h4>
        <p>这里保留前端静态配置界面，方便后续直接对接后台接口。</p>
      </div>

      <el-form label-position="top" class="datasource-form">
        <el-form-item label="数据源名称">
          <el-input v-model="formState.name" placeholder="例如：市本级财政预算库" />
        </el-form-item>

        <el-form-item label="数据库类型">
          <el-select v-model="formState.dbType" style="width: 100%" @change="setDefaultPort">
            <el-option
              v-for="option in dbTypeOptions"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </el-form-item>

        <div class="form-row-grid">
          <el-form-item label="主机/IP">
            <el-input v-model="formState.host" placeholder="例如：192.168.10.5" />
          </el-form-item>
          <el-form-item label="端口">
            <el-input-number v-model="formState.port" :min="1" :max="65535" controls-position="right" />
          </el-form-item>
        </div>

        <el-form-item label="数据库名/服务名">
          <el-input v-model="formState.databaseName" placeholder="例如：DM_FINANCE_DB" />
        </el-form-item>

        <div class="form-row-grid">
          <el-form-item label="用户名">
            <el-input v-model="formState.username" placeholder="请输入用户名" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="formState.password" type="password" show-password placeholder="请输入密码" />
          </el-form-item>
        </div>

        <el-form-item label="备注说明">
          <el-input
            v-model="formState.description"
            type="textarea"
            :rows="4"
            placeholder="可填写业务域说明、只读账号说明、同步策略等补充信息。"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <div class="drawer-footer">
          <el-button @click="drawerVisible = false">取消</el-button>
          <el-button @click="setDefaultPort">恢复默认端口</el-button>
          <el-button type="primary" @click="submitForm">保存配置</el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.datasource-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-height: 100%;
}

.toolbar-panel,
.table-panel {
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(148, 163, 184, 0.14);
  box-shadow: 0 20px 60px rgba(15, 23, 42, 0.08);
}

.toolbar-panel {
  border-radius: 8px;
  padding: 20px 22px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.toolbar-copy h3 {
  margin: 0 0 6px;
  font-size: 22px;
}

.toolbar-copy p {
  margin: 0;
  color: #64748b;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}

.datasource-search {
  width: 320px;
}

.primary-action-button {
  height: 42px;
  padding: 0 18px;
  box-shadow: 0 16px 28px rgba(82, 99, 255, 0.24);
}

.table-panel {
  width: 100%;
  border-radius: 8px;
  padding: 10px 10px 12px;
}

.table-wrap {
  width: 100%;
}

.datasource-table {
  width: 100%;
}

.status-display {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
}

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  box-shadow: 0 0 0 6px rgba(148, 163, 184, 0.08);
}

.row-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 2px;
}

.danger-text-button {
  color: #ef4444;
}

.datasource-pagination {
  display: flex;
  justify-content: flex-end;
  padding-top: 18px;
}

.drawer-intro {
  padding-bottom: 12px;
}

.drawer-intro h4 {
  margin: 0 0 6px;
  font-size: 22px;
}

.drawer-intro p {
  margin: 0;
  color: #64748b;
}

.datasource-form {
  padding-top: 8px;
}

.form-row-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 160px;
  gap: 14px;
}

.drawer-footer {
  width: 100%;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

:deep(.datasource-table .el-table__inner-wrapper::before) {
  display: none;
}

:deep(.datasource-table th.el-table__cell) {
  background: rgba(248, 250, 252, 0.96);
  color: #64748b;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

:deep(.datasource-table td.el-table__cell),
:deep(.datasource-table th.el-table__cell) {
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
}

:deep(.datasource-table .el-table__row:hover > td.el-table__cell) {
  background: rgba(82, 99, 255, 0.04);
}

:deep(.datasource-drawer .el-drawer__header) {
  margin-bottom: 0;
  padding-bottom: 0;
}

:deep(.el-input-number) {
  width: 100%;
}

@media (max-width: 640px) {
  .toolbar-actions,
  .form-row-grid {
    display: grid;
    grid-template-columns: 1fr;
  }

  .datasource-search {
    width: 100%;
  }

  .toolbar-panel,
  .table-panel {
    border-radius: 20px;
  }
}
</style>
