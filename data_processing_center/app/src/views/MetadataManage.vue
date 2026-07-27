<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, Search } from '@element-plus/icons-vue'
import { cancelMetadataTable, getMetadataTables } from '../api/dataManage'

const keyword = ref('')
const loading = ref(false)
const cancellingTableName = ref('')
const metadataRows = ref([])

const filteredRows = computed(() => {
  const value = keyword.value.trim().toLowerCase()
  if (!value) {
    return metadataRows.value
  }

  return metadataRows.value.filter((row) => {
    return (
      String(row.table_comment || '').toLowerCase().includes(value) ||
      String(row.table_name || '').toLowerCase().includes(value) ||
      String(row.business_domain || '').toLowerCase().includes(value)
    )
  })
})

const loadMetadataTables = async () => {
  loading.value = true
  try {
    const response = await getMetadataTables()
    metadataRows.value = Array.isArray(response.data) ? response.data : []
  } catch (error) {
    ElMessage.error(error.message || '获取元数据列表失败')
    metadataRows.value = []
  } finally {
    loading.value = false
  }
}

const handleCancel = async (row) => {
  cancellingTableName.value = row.table_name
  try {
    await cancelMetadataTable({ table_name: row.table_name })
    ElMessage.success('已取消元数据。')
    await loadMetadataTables()
  } catch (error) {
    ElMessage.error(error.message || '取消元数据失败')
  } finally {
    cancellingTableName.value = ''
  }
}

onMounted(() => {
  loadMetadataTables()
})
</script>

<template>
  <div class="metadata-page">
    <section class="table-panel">
      <div class="section-header">
        <div>
          <h3>元数据管理列表</h3>
          <p>当前展示已经被添加为元数据的表，支持按表名称快速搜索，并可取消元数据状态。</p>
        </div>
        <el-input
          v-model="keyword"
          class="table-search"
          placeholder="表名称搜索"
          :prefix-icon="Search"
          clearable
        />
      </div>

      <div class="table-wrap">
        <el-table
          :data="filteredRows"
          v-loading="loading"
          element-loading-text="正在加载元数据..."
          class="module-table"
          style="width: 100%"
          table-layout="auto"
        >
          <el-table-column label="序号" width="80">
            <template #default="{ row, $index }">
              {{ row.index || $index + 1 }}
            </template>
          </el-table-column>
          <el-table-column prop="table_comment" label="表中文名/注释" min-width="280" show-overflow-tooltip />
          <el-table-column prop="table_name" label="表名(物理名)" min-width="360" show-overflow-tooltip />
          <el-table-column prop="business_domain" label="所属业务域" min-width="160" show-overflow-tooltip />
          <el-table-column label="操作" width="140" fixed="right">
            <template #default="{ row }">
              <el-button
                text
                type="danger"
                :icon="Delete"
                :loading="cancellingTableName === row.table_name"
                @click="handleCancel(row)"
              >
                取消
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.metadata-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-height: 100%;
}

.table-panel {
  border-radius: 24px;
  padding: 20px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(148, 163, 184, 0.14);
  box-shadow: 0 20px 60px rgba(15, 23, 42, 0.08);
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
  color: #64748b;
}

.table-search {
  width: 240px;
}

.table-wrap {
  width: 100%;
  overflow-x: auto;
  margin-top: 16px;
}

.module-table {
  width: 100%;
  min-width: 980px;
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
  background: rgba(109, 93, 252, 0.04);
}

@media (max-width: 640px) {
  .section-header {
    flex-direction: column;
  }

  .table-search {
    width: 100%;
  }
}
</style>
