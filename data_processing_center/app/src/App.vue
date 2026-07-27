<script setup>
import { computed, ref } from 'vue'
import SidebarMenu from './components/SidebarMenu.vue'
import { moduleMenus } from './data/modules'
import DatasourceManagementView from './views/DataManage.vue'
import KnowledgeBaseManagementView from './views/ragManage.vue'
import MetadataManagementView from './views/MetadataManage.vue'
import SchedulingTaskView from './views/SchedulTask.vue'
import SyncManagementView from './views/SyncManage.vue'
import SchemaList from './views/schemaList.vue'

const activeKey = ref(moduleMenus[0].key)
const datasourcePage = ref('list')
const currentDatasource = ref(null)

const viewMap = {
  datasource: DatasourceManagementView,
  metadata: MetadataManagementView,
  vectorization: KnowledgeBaseManagementView,
  sync: SyncManagementView,
  scheduling: SchedulingTaskView
}

const activeView = computed(() => {
  if (activeKey.value === 'datasource' && datasourcePage.value === 'schema') {
    return SchemaList
  }
  return viewMap[activeKey.value] || DatasourceManagementView
})

const handleMenuChange = (key) => {
  activeKey.value = key
  if (key !== 'datasource') {
    datasourcePage.value = 'list'
    currentDatasource.value = null
  }
}

const handleViewDetail = (row) => {
  currentDatasource.value = row
  datasourcePage.value = 'schema'
}

const handleBackToDatasource = () => {
  datasourcePage.value = 'list'
}
</script>

<template>
  <div class="console-page">
    <SidebarMenu :modules="moduleMenus" :active-key="activeKey" @change="handleMenuChange" />

    <main class="main-shell">
      <section class="view-shell">
        <Suspense>
          <component
            :is="activeView"
            :datasource="currentDatasource"
            @view-detail="handleViewDetail"
            @back="handleBackToDatasource"
          />
          <template #fallback>
            <div style="padding:40px;color:#64748b;">加载中...</div>
          </template>
        </Suspense>
      </section>
    </main>
  </div>
</template>

<style scoped>
.console-page {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.main-shell {
  flex: 1;
  min-width: 0;
  height: 100vh;
  padding: 20px 24px 24px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.view-shell {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-top: 16px;
}

.view-shell::-webkit-scrollbar {
  width: 10px;
}

.view-shell::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.3);
  border-radius: 999px;
}

@media (max-width: 1080px) {
  .console-page {
    flex-direction: column;
    height: auto;
    min-height: 100vh;
  }

  .main-shell {
    height: auto;
    padding: 16px;
  }

  .view-shell {
    overflow: visible;
  }
}
</style>
