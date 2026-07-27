<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Download, Delete, Upload, Refresh, Check, Close, View, Edit } from '@element-plus/icons-vue'
import {
  getKnowledgeBase, getRagJobs, downloadRagJob, deleteRagJob,
  ingestRagJob, unloadRagJob, uploadRagFile, batchQueryJobStatus, getRegions
} from '../api/dataManage'

const loading = ref(false); const keyword = ref(''); const keywordTasks = ref('')
const statusFilter = ref(''); const knowledgeSort = ref('time')
const knowledgeData = ref({ total_files: 0, total_chunks: 0, files: [] })
const selectedDocs = ref([]); const loadingJobs = ref(false)
const jobs = ref([]); const pollingTimer = ref(null); const pendingJobIds = ref(new Set())
const uploadVisible = ref(false); const uploading = ref(false)
const fileInput = ref(null); const uploadFiles = ref([]); const uploadFileRegions = ref({})
const previewVisible = ref(false); const previewJob = ref(null)
const previewText = ref(''); const previewLoading = ref(false)
const regionOptions = ref([])
const regionEditVisible = ref(false); const regionEditSource = ref(''); const regionEditFilename = ref('')
const regionEditCode = ref(''); const regionEditSaving = ref(false)

const filteredJobs = computed(() => {
  let list = jobs.value
  if (statusFilter.value) list = list.filter(j => j.status === statusFilter.value)
  if (keywordTasks.value.trim()) list = list.filter(j => j.filename.toLowerCase().includes(keywordTasks.value.trim().toLowerCase()))
  return list
})
const filteredKnowledge = computed(() => {
  if (!keyword.value.trim()) return knowledgeData.value.files
  const kw = keyword.value.trim().toLowerCase()
  return knowledgeData.value.files.filter(f =>
    f.filename.toLowerCase().includes(kw) ||
    f.source.toLowerCase().includes(kw)
  )
})
const statusCounts = computed(() => {
  const counts = {}
  jobs.value.forEach(j => { const s = j.status || 'unknown'; counts[s] = (counts[s] || 0) + 1 })
  return counts
})

async function loadAll() { await Promise.all([loadKnowledgeBase(), loadJobs()]) }
async function loadKnowledgeBase() { try { const d = await getKnowledgeBase(knowledgeSort.value); knowledgeData.value = d } catch (e) { console.error(e) } }
async function loadJobs() {
  loadingJobs.value = true
  try {
    const d = await getRagJobs({ per_page: 1000 })
    const newJobs = d.jobs || []
    const existingMap = new Map(jobs.value.map(j => [j.id, j]))
    const newIds = new Set(newJobs.map(j => j.id))

    for (const nj of newJobs) {
      const existing = existingMap.get(nj.id)
      if (!existing) {
        // 新 job：直接加入列表
        jobs.value.push(nj)
      } else {
        // 已存在的 job：更新所有字段。
        // status 由后端权威决定（unload/入库/取消 等操作会改变 status），
        // 轮询只在 processing/queued/ingesting 阶段更新 progress/progress_pct，
        // 这些值与 status 不会冲突（终态 job 不在 pendingJobIds 中）。
        existing.status = nj.status
        existing.progress = nj.progress
        existing.progress_pct = nj.progress_pct
        existing.file_size = nj.file_size
        existing.region_code = nj.region_code
        existing.region_name = nj.region_name
        existing.filename = nj.filename
        existing.output_path = nj.output_path
        existing.preview_text = nj.preview_text
        existing.ingest_error = nj.ingest_error
        existing.created_at = nj.created_at
      }
    }

    // 移除后端已不存在的 job（被其他标签页删除了）
    for (let i = jobs.value.length - 1; i >= 0; i--) {
      if (!newIds.has(jobs.value[i].id)) jobs.value.splice(i, 1)
    }
  } catch (e) { console.error(e) }
  finally { loadingJobs.value = false }
}

function startPolling(jobIds) {
  jobIds.forEach(id => pendingJobIds.value.add(id))
  if (pollingTimer.value) return  // 定时器已存在则只追加 ID，复用已有定时器
  pollingTimer.value = setInterval(async () => {
    if (pendingJobIds.value.size === 0) { stopPolling(); return }
    try {
      const result = await batchQueryJobStatus([...pendingJobIds.value])
      // 只更新进度和状态，不刷新整个列表
      ;(result.jobs || []).forEach(j => {
        const existing = jobs.value.find(x => x.id === j.id)
        if (existing) {
          existing.status = j.status
          existing.progress = j.progress
          existing.progress_pct = j.progress_pct
          existing.chunk_count = j.chunk_count
          existing.processing_time = j.processing_time
          existing.error = j.error
        } else {
          // Bug 28: job 尚未出现在列表（loadJobs 未返回或延迟），
          // 将其直接推入，避免本轮轮询数据丢失
          jobs.value.push(j)
        }
        // 终态：completed/failed/ingested/cancelled/cancelling
        if (['completed','failed','ingested','cancelled','cancelling'].includes(j.status)) {
          pendingJobIds.value.delete(j.id)
        }
      })
      // 清理已删除的任务
      const existingIds = new Set(jobs.value.map(jj => jj.id))
      for (const id of pendingJobIds.value) { if (!existingIds.has(id)) pendingJobIds.value.delete(id) }
      if (pendingJobIds.value.size === 0) { ElMessage.success('文档处理完成'); stopPolling() }
    } catch (e) {}
  }, 5000)
}
function stopPolling() { if (pollingTimer.value) { clearInterval(pollingTimer.value); pollingTimer.value = null } }

function openUploadDialog() { uploadFiles.value = []; uploadFileRegions.value = {}; if (fileInput.value) fileInput.value.value = ''; uploadVisible.value = true }
function onFileChange(e) {
  const newFiles = [...(e.target.files || [])]; if (newFiles.length === 0) return
  const existingKeys = new Set(uploadFiles.value.map(f => `${f.name}|${f.size}|${f.lastModified}`))
  const added = newFiles.filter(f => !existingKeys.has(`${f.name}|${f.size}|${f.lastModified}`))
  if (added.length === 0) { ElMessage.info('文件已在列表中'); return }
  if (uploadFiles.value.length + added.length > 3) { ElMessage.warning(`最多3个文件，当前已有${uploadFiles.value.length}个`); return }
  uploadFiles.value = [...uploadFiles.value, ...added]; e.target.value = ''
}
function removeFile(index) { delete uploadFileRegions.value[uploadFiles.value[index].name]; uploadFiles.value.splice(index, 1) }

async function confirmUpload() {
  if (uploading.value) return
  if (uploadFiles.value.length === 0) { ElMessage.warning('请选择要上传的文档'); return }
  const missing = uploadFiles.value.filter(f => !uploadFileRegions.value[f.name])
  if (missing.length > 0) { ElMessage.warning(`请为以下文档选择所属地区: ${missing.map(f => f.name).join('、')}`); return }

  // ── 三层去重检查 ──
  // 1. 知识库已入库的文件名
  const existingInKB = new Set(knowledgeData.value.files.map(f => f.filename))
  // 2. 处理中/排队中的任务（禁止同文件重复提交）
  const activeJobNames = new Set(
    jobs.value
      .filter(j => ['processing', 'queued', 'ingesting', 'uploaded'].includes(j.status))
      .map(j => j.filename)
  )
  // 3. 已完成但未入库的文件名
  const completedJobNames = new Set(
    jobs.value
      .filter(j => j.status === 'completed')
      .map(j => j.filename)
  )

  // 硬阻止：文件正在处理中
  const inProgress = uploadFiles.value.filter(f => activeJobNames.has(f.name))
  if (inProgress.length > 0) {
    ElMessage.warning(`以下文档正在处理中，请等待完成后再上传：${inProgress.map(f => f.name).join('、')}`)
    return
  }

  // 软提示：已有已完成的同名任务
  const completedDupes = uploadFiles.value.filter(f => completedJobNames.has(f.name))
  // 软提示：知识库已有同名文件
  const kbDupes = uploadFiles.value.filter(f => existingInKB.has(f.name))
  // 同批次内重复
  const batchNameCount = {}
  uploadFiles.value.forEach(f => { batchNameCount[f.name] = (batchNameCount[f.name] || 0) + 1 })
  const batchDupes = Object.entries(batchNameCount).filter(([, c]) => c > 1).map(([n]) => n)

  const allSoftDupes = [...new Set([
    ...completedDupes.map(f => f.name),
    ...kbDupes.map(f => f.name),
    ...batchDupes,
  ])]
  if (allSoftDupes.length > 0) {
    let dupMsg = ''
    if (completedDupes.length > 0) dupMsg += `以下文档已有处理完成的记录：${completedDupes.map(f => f.name).join('、')}`
    if (kbDupes.length > 0) dupMsg += `${dupMsg ? '；' : ''}以下文档与知识库中已有文档同名：${kbDupes.map(f => f.name).join('、')}`
    const batchOnly = batchDupes.filter(n => !existingInKB.has(n) && !completedJobNames.has(n))
    if (batchOnly.length > 0) dupMsg += `${dupMsg ? '；' : ''}以下文档在当前批次内重复：${batchOnly.join('、')}`
    try {
      await ElMessageBox.confirm(`${dupMsg}，上传后将新增一份记录（不会覆盖原有数据）`, '重名提示', { type: 'warning', confirmButtonText: '继续上传', cancelButtonText: '取消' })
    } catch { return }
  }
  uploading.value = true; const results = []; let errorCount = 0
  try {
    for (const f of uploadFiles.value) {
      const fd = new FormData(); fd.append('files', f)
      const r = uploadFileRegions.value[f.name] || ''; if (r) fd.append('region_code', r)
      const res = await uploadRagFile(fd)
      if (res.jobs) {
        results.push(...res.jobs)
        // ★ Bug 2 修复：每上传成功一个文件，立即将其加入轮询
        startPolling(res.jobs.map(j => j.job_id))
      }
      if (res.errors) { res.errors.forEach(e => { ElMessage.error(`${e.filename}: ${e.error}`); errorCount++ }) }
    }
    if (results.length > 0) {
      ElMessage.success(`已提交 ${results.length} 个文档${errorCount > 0 ? `，${errorCount} 个失败` : ''}`)
      uploadVisible.value = false
      // 延迟加载完整列表，避免与轮询竞态 (Bug 2)
      setTimeout(async () => { await loadJobs() }, 2000)
    }
  } catch (e) { ElMessage.error('上传失败: ' + e.message) } finally { uploading.value = false }
}

async function removeDocBySource(source) {
  try {
    await ElMessageBox.confirm(`确定要删除该文档的所有切片吗？`, '确认删除', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    const B = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001'
    const res = await fetch(`${B}/ragdata/knowledge/remove`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sources: [source] }) }).then(r => r.json())
    ElMessage.success(res.message || '已删除')
    // Bug 8 修复：同步更新对应 job 状态
    const job = jobs.value.find(j => j.id === source)
    if (job) {
      job.status = 'completed'
      job.progress = '已从知识库移除'
      job.progress_pct = 100
    }
    await loadKnowledgeBase()
  } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败: ' + (e.message || e)) }
}
async function batchRemoveDocs() {
  if (selectedDocs.value.length === 0) { ElMessage.warning('请先选择要删除的文档'); return }
  try {
    await ElMessageBox.confirm(`确定要删除选中的 ${selectedDocs.value.length} 个文档吗？`, '确认批量删除', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    const B = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001'
    const sources = selectedDocs.value.map(r => r.source)
    const res = await fetch(`${B}/ragdata/knowledge/remove`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sources }) }).then(r => r.json())
    ElMessage.success(res.message || `已删除`)
    // Bug 8 修复：同步更新 job 列表，将对应 source 的 job 状态更新
    for (const src of sources) {
      const job = jobs.value.find(j => j.id === src)
      if (job) {
        job.status = 'completed'
        job.progress = '已从知识库移除'
        job.progress_pct = 100
      }
    }
    selectedDocs.value = []; await loadKnowledgeBase()
  } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败: ' + (e.message || e)) }
}

async function handleDelete(job) {
  const wasIngested = job.status === 'ingested'
  const msg = wasIngested
    ? `确定要删除 "${job.filename}" 吗？该文档已入库，删除将同时清理向量库中的切片。`
    : `确定要删除 "${job.filename}" 吗？`
  try { await ElMessageBox.confirm(msg, '确认删除', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }); await deleteRagJob(job.id); ElMessage.success('已删除'); await loadAll() } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败: ' + (e.message || e)) }
}
async function handleIngest(job) {
  try { await ElMessageBox.confirm(`确定将 "${job.filename}" 入库吗？`, '确认入库', { confirmButtonText: '入库', cancelButtonText: '取消' }); const res = await ingestRagJob(job.id); ElMessage.success(res.message || '入库完成'); await loadAll() } catch (e) { if (e !== 'cancel') ElMessage.error('入库失败: ' + (e.message || e)) }
}
async function handleUnload(job) {
  try { await ElMessageBox.confirm(`确定从知识库中移除 "${job.filename}" 吗？`, '确认出库', { type: 'warning', confirmButtonText: '移除', cancelButtonText: '取消' }); const res = await unloadRagJob(job.id); ElMessage.success(res.message || '已移除'); await loadAll() } catch (e) { if (e !== 'cancel') ElMessage.error('出库失败: ' + (e.message || e)) }
}
async function showPreview(job) {
  previewJob.value = job; previewVisible.value = true; previewLoading.value = true
  try { const B = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001'; const res = await fetch(`${B}/ragdata/jobs/${job.id}`).then(r => r.json()); previewText.value = res.preview_text || '暂无预览内容' } catch (e) { previewText.value = '加载预览失败' } finally { previewLoading.value = false }
}
async function previewKnowledgeDoc(source) {
  previewJob.value = { filename: source }; previewVisible.value = true; previewLoading.value = true
  try { const B = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001'; const res = await fetch(`${B}/ragdata/knowledge/chunks?source=${encodeURIComponent(source)}`).then(r => r.json()); previewText.value = (res.chunks || []).map(c => c.content || '').join('\n---\n') || '暂无内容' } catch (e) { previewText.value = '加载预览失败' } finally { previewLoading.value = false }
}
// 编辑权限
async function editRegion(row) {
  regionEditSource.value = row.source; regionEditFilename.value = row.filename; regionEditCode.value = ""
  try { const B = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8001"; const res = await fetch(B + "/ragdata/region-permission?source=" + encodeURIComponent(row.source)).then(r => r.json()); regionEditCode.value = res.region_code || "" } catch (e) {}
  regionEditVisible.value = true
}
async function saveRegion() {
  if (regionEditSaving.value) return; regionEditSaving.value = true
  try {
    const B = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8001"
    const body = JSON.stringify({ source: regionEditSource.value, filename: regionEditFilename.value, region_code: regionEditCode.value })
    const res = await fetch(B + "/ragdata/region-permission", { method: "POST", headers: { "Content-Type": "application/json" }, body }).then(r => r.json())
    if (res.status === "ok") { ElMessage.success("权限已更新"); await loadKnowledgeBase() }
    else ElMessage.error(res.error || "更新失败")
    regionEditVisible.value = false
  } catch (e) { ElMessage.error("保存失败") } finally { regionEditSaving.value = false }
}

// 模型服务状态
const modelStatus = ref({ status: 'unknown', model_loaded: false, active_count: 0, queue_size: 0, uptime: 0, total_processed: 0 })
const modelStatusLoading = ref(false)

async function loadModelStatus() {
  modelStatusLoading.value = true
  try {
    const B = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001'
    const r = await fetch(B + '/ragdata/model-service/status').then(r => r.json())
    modelStatus.value = r
  } catch (e) { modelStatus.value.status = 'offline' } finally { modelStatusLoading.value = false }
}
setInterval(loadModelStatus, 15000)  // 每15秒刷新

function resolveStatusType(s) { return { completed:'success', ingested:'success', cancelled:'info', processing:'warning', queued:'info', ingesting:'warning', uploaded:'info', failed:'danger' }[s] || 'info' }
function resolveStatusLabel(s) { return { completed:'已完成', ingested:'已入库', cancelled:'已取消', processing:'处理中', queued:'排队中', ingesting:'入库中', uploaded:'已上传', failed:'失败' }[s] || s }

onMounted(async () => {
  await loadAll()
  loadModelStatus()
  getRegions().then(d => { regionOptions.value = (d.regions || []).map(r => ({ value: r.code, label: r.name })) }).catch(e => console.error(e))
  // 确保 loadAll 完成后再检查活跃任务启动轮询，避免 jobs 尚未加载导致丢失
  const active = jobs.value.filter(j => ['processing','queued','ingesting'].includes(j.status))
  if (active.length > 0) startPolling(active.map(j => j.id))
})
</script>

<template>
  <div class="rag-page">
    <!-- ═══ 模型服务状态栏 ═══ -->
    <div class="model-status-bar" :class="modelStatus.model_loaded ? 'healthy' : (modelStatus.model_loading ? 'warming_up' : 'offline')">
      <span class="status-dot" :class="modelStatus.model_loaded ? 'healthy' : (modelStatus.model_loading ? 'warming_up' : 'offline')"></span>
      <span v-if="modelStatus.model_loaded" class="status-text">模型就绪</span>
      <span v-else-if="modelStatus.model_loading" class="status-text">模型加载中...</span>
      <span v-else class="status-text">模型服务未启动</span>
      <span class="status-divider">|</span>
      <span>处理中 {{ (statusCounts.processing || 0) + (statusCounts.queued || 0) + (statusCounts.ingesting || 0) }} 个</span>
      <span class="status-divider">|</span>
      <span>已完成 {{ statusCounts.completed || 0 }} 个</span>
      <span class="status-divider">|</span>
      <span>已入库 {{ statusCounts.ingested || 0 }} 个</span>
      <span class="status-right">模型已处理 {{ modelStatus.total_processed || 0 }} 个</span>
    </div>

    <div class="metric-grid">
      <article class="metric-card tone-primary"><div class="metric-label">文档资产</div><div class="metric-value">{{ knowledgeData.total_files }}</div><div class="metric-delta">个文档已入库</div></article>
      <article class="metric-card tone-success"><div class="metric-label">向量切片</div><div class="metric-value">{{ knowledgeData.total_chunks }}</div><div class="metric-delta">个切片可检索</div></article>
      <article class="metric-card tone-warning"><div class="metric-label">处理中</div><div class="metric-value">{{ (statusCounts.processing || 0) + (statusCounts.queued || 0) }}</div><div class="metric-delta">个任务排队/处理中</div></article>
      <article class="metric-card tone-info"><div class="metric-label">已完成任务</div><div class="metric-value">{{ statusCounts.completed || 0 }}</div><div class="metric-delta">个待入库</div></article>
    </div>

    <div class="card-panel">
      <div class="section-header">
        <div><h3>文档切片明细</h3><p>合计 {{ knowledgeData.total_files }} 文档 / {{ knowledgeData.total_chunks }} 切片</p></div>
        <div style="display:flex;align-items:center;gap:8px;">
          <el-button v-if="selectedDocs.length>0" type="danger" :icon="Delete" size="small" @click="batchRemoveDocs">删除选中({{ selectedDocs.length }})</el-button>
          <el-select v-model="knowledgeSort" @change="loadKnowledgeBase" size="small" style="width:120px">
            <el-option label="按时间" value="time"/><el-option label="按名称" value="name"/><el-option label="按切片数" value="chunks"/>
          </el-select>
          <el-input v-model="keyword" style="width:200px" placeholder="搜索文档名..." :prefix-icon="Search" clearable size="small"/>
        </div>
      </div>
      <div class="table-wrap">
        <el-table :data="filteredKnowledge" class="rag-table" v-loading="loading" @selection-change="(sel) => selectedDocs = sel">
          <el-table-column type="selection" width="44"/><el-table-column type="index" label="#" width="50"/>
          <el-table-column prop="filename" label="文档名称" min-width="240" show-overflow-tooltip/>
          <el-table-column label="入库时间" width="160" align="center"><template #default="{row}"><span class="text-muted">{{ row.last_ingest ? new Date(Number(row.last_ingest)*1000).toLocaleString() : '-' }}</span></template></el-table-column>
          <el-table-column label="地区" width="180" align="center">
            <template #default="{row}"><span class="text-muted">{{ row.region_name || row.region_code || '-' }}</span></template>
          </el-table-column>
          <el-table-column prop="chunks" label="切片数量" width="100" align="center"/>
          <el-table-column label="操作" width="160" align="center">
            <template #default="{row}">
              <el-button type="primary" link size="small" @click="previewKnowledgeDoc(row.source)"><el-icon><View/></el-icon></el-button>
              <el-button type="warning" link size="small" @click="editRegion(row)"><el-icon><Edit/></el-icon></el-button>
              <el-button type="danger" link size="small" @click="removeDocBySource(row.source)"><el-icon><Delete/></el-icon></el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <div class="card-panel">
      <div class="section-header">
        <div><h3>处理任务</h3><p>文档上传、解析与入库管理</p></div>
        <div style="display:flex;align-items:center;gap:8px;">
          <el-button type="primary" :icon="Upload" size="large" @click="openUploadDialog">上传文档</el-button>
          <el-button :icon="Refresh" @click="loadJobs" :loading="loadingJobs" circle/>
        </div>
      </div>
      <div class="filter-bar">
        <button class="filter-chip" :class="{active:!statusFilter}" @click="statusFilter=''">全部({{ jobs.length }})</button>
        <button v-for="[k,l] in [['processing','处理中'],['completed','已完成'],['ingested','已入库'],['failed','失败']]" :key="k" class="filter-chip" :class="{active:statusFilter===k}" @click="statusFilter = statusFilter===k ? '' : k">{{ l }}({{ statusCounts[k]||0 }})</button>
        <el-input v-model="keywordTasks" style="width:180px;margin-left:auto" placeholder="搜索任务..." :prefix-icon="Search" clearable size="small"/>
      </div>
      <div class="table-wrap">
        <el-table :data="filteredJobs" class="rag-table" v-loading="loadingJobs">
          <el-table-column prop="filename" label="文件名" min-width="160" show-overflow-tooltip/>
          <el-table-column label="地区" width="110" align="center"><template #default="{row}">{{ row.region_name || row.region_code || '未设置' }}</template></el-table-column>
          <el-table-column label="大小" width="90" align="center"><template #default="{row}"><span class="text-muted">{{ row.file_size ? (row.file_size/1024/1024).toFixed(1)+'MB' : '-' }}</span></template></el-table-column>
          <el-table-column label="状态" width="100" align="center"><template #default="{row}"><el-tag :type="resolveStatusType(row.status)" size="small" round>{{ resolveStatusLabel(row.status) }}</el-tag></template></el-table-column>
          <el-table-column label="切片数" width="70" align="center"><template #default="{row}">{{ row.chunk_count || '-' }}</template></el-table-column>
          <el-table-column label="耗时" width="70" align="center"><template #default="{row}"><span class="text-muted">{{ row.processing_time ? row.processing_time+'s' : '-' }}</span></template></el-table-column>
          <el-table-column label="进度" min-width="200">
            <template #default="{row}">
              <div style="display:flex;flex-direction:column;gap:3px">
                <!-- 处理完成(100%) 或 入库完成(100%) -->
                <el-progress
                  v-if="(row.status==='completed' && row.progress==='处理完成') || (row.status==='completed' && row.progress_pct===100) || row.status==='ingested'"
                  :percentage="100" :stroke-width="6" color="#22c55e" :show-text="false"
                />
                <el-progress
                  v-else-if="row.status==='failed'"
                  :percentage="0" :stroke-width="6" color="#ef4444" :show-text="false"
                />
                <el-progress
                  v-else-if="row.progress_pct>0"
                  :percentage="row.progress_pct" :stroke-width="6" :show-text="false"
                />
                <el-progress
                  v-else
                  :percentage="50" :indeterminate="true" :stroke-width="6" :show-text="false" :duration="2"
                />
                <span class="text-muted" style="font-size:11px">{{ row.progress || '-' }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="220" align="center" fixed="right">
            <template #default="{row}">
              <div class="action-btns">
                <el-button v-if="row.status==='completed'||row.status==='ingested'" type="info" link size="small" @click="showPreview(row)"><el-icon><View/></el-icon></el-button>
                <el-button v-if="row.status==='completed'||row.status==='ingested'" type="primary" link size="small" @click="downloadRagJob(row.id)"><el-icon><Download/></el-icon></el-button>
                <el-button v-if="row.status==='completed'" type="success" link size="small" @click="handleIngest(row)"><el-icon><Check/></el-icon></el-button>
                <el-button v-if="row.status==='ingested'" type="warning" link size="small" @click="handleUnload(row)"><el-icon><Close/></el-icon></el-button>
                <el-button type="danger" link size="small" @click="handleDelete(row)"><el-icon><Delete/></el-icon></el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <div v-if="!loadingJobs && filteredJobs.length===0" class="empty-state"><p>暂无处理任务</p><p class="text-muted">点击"上传文档"提交 PDF / DOCX 文档</p></div>
    </div>

    <el-dialog v-model="uploadVisible" title="上传文档" width="540px" :close-on-click-modal="false" destroy-on-close>
      <div class="upload-dialog-body">
        <div class="upload-dialog-section">
          <div class="section-label">选择文档</div>
          <div class="upload-file-area" @click="fileInput?.click()">
            <el-icon :size="36" color="#94a3b8"><Upload/></el-icon>
            <p>点击选择 PDF / DOCX / DOC 文件</p>
            <p class="section-hint" style="margin-top:4px">最多 3 个文件，单个最大 200MB</p>
            <input ref="fileInput" type="file" accept=".pdf,.docx,.doc" multiple style="display:none" @change="onFileChange"/>
          </div>
          <div v-if="uploadFiles.length>0" class="file-list">
            <div v-for="(f,i) in uploadFiles" :key="i" class="file-item">
              <span>{{ f.name }}</span>
              <el-select :model-value="uploadFileRegions[f.name]||''" @update:model-value="(val) => uploadFileRegions[f.name]=val||''" placeholder="选择地区*" size="small" style="width:150px" clearable>
                <el-option v-for="r in regionOptions" :key="r.value" :label="r.label" :value="r.value"/>
              </el-select>
              <el-button type="danger" link size="small" @click="removeFile(i)"><el-icon><Close/></el-icon></el-button>
            </div>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="uploadVisible=false" :disabled="uploading">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="confirmUpload">开始上传处理</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="previewVisible" :title="'预览: '+(previewJob?.filename||'')" width="800px" :close-on-click-modal="false" destroy-on-close>
      <div v-loading="previewLoading" style="max-height:500px;overflow-y:auto;white-space:pre-wrap;font-size:13px;line-height:1.8;color:#334155;background:#f8fafc;padding:16px;border-radius:12px">{{ previewText }}</div>
    </el-dialog>

    <el-dialog v-model="regionEditVisible" title="编辑文档权限" width="480px" :close-on-click-modal="false" destroy-on-close>
      <div style="display:flex;flex-direction:column;gap:16px">
        <div><div style="font-weight:600;margin-bottom:6px">文档名称</div><div style="color:#64748b">{{ regionEditFilename }}</div></div>
        <div><div style="font-weight:600;margin-bottom:6px">所属地区</div>
          <el-select v-model="regionEditCode" placeholder="选择地区" style="width:100%" clearable>
            <el-option v-for="r in regionOptions" :key="r.value" :label="r.label" :value="r.value"/>
          </el-select>
        </div>
      </div>
      <template #footer>
        <el-button @click="regionEditVisible=false" :disabled="regionEditSaving">取消</el-button>
        <el-button type="primary" :loading="regionEditSaving" @click="saveRegion">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.rag-page{display:flex;flex-direction:column;gap:18px;min-height:100%}
.model-status-bar{display:flex;align-items:center;gap:8px;padding:10px 18px;border-radius:14px;font-size:13px;color:#334155;background:rgba(255,255,255,0.7);border:1px solid rgba(148,163,184,0.12)}
.model-status-bar .status-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
.model-status-bar .status-dot.healthy{background:#22c55e;box-shadow:0 0 6px rgba(34,197,94,0.4)}
.model-status-bar .status-dot.warming_up{background:#f59e0b;animation:pulse 1.5s infinite}
.model-status-bar .status-dot.offline{background:#94a3b8}
.model-status-bar .status-dot.unknown{background:#94a3b8}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.3}}
.status-divider{color:rgba(148,163,184,0.5)}
.status-right{margin-left:auto;color:#64748b}
.metric-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}
.metric-card{position:relative;overflow:hidden;padding:20px;border-radius:18px;background:rgba(255,255,255,0.92);border:1px solid rgba(148,163,184,0.14);box-shadow:0 20px 60px rgba(15,23,42,0.08)}
.metric-card::after{content:"";position:absolute;inset:auto -24px -24px auto;width:92px;height:92px;border-radius:50%;opacity:0.12}
.metric-card.tone-primary::after{background:#4f7cff}.metric-card.tone-success::after{background:#22c55e}.metric-card.tone-warning::after{background:#f59e0b}.metric-card.tone-info::after{background:#38bdf8}
.metric-label{color:#64748b;font-size:13px}.metric-value{margin:10px 0 8px;font-size:32px;font-weight:700;color:#0f172a}.metric-delta{color:#64748b;font-size:13px}
.card-panel{background:rgba(255,255,255,0.5);border:1px solid rgba(148,163,184,0.08);border-radius:18px;padding:20px}
.section-header{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:12px}
.section-header h3{margin:0 0 6px;font-size:20px}.section-header p{margin:0;color:#64748b;font-size:13px}
.filter-bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.filter-chip{padding:6px 14px;border:1px solid rgba(148,163,184,0.18);border-radius:999px;background:rgba(255,255,255,0.7);color:#64748b;font-size:13px;cursor:pointer}
.filter-chip:hover{border-color:rgba(82,99,255,0.3);color:#0f172a}.filter-chip.active{background:rgba(82,99,255,0.1);border-color:rgba(82,99,255,0.4);color:#5263ff;font-weight:600}
.table-wrap{width:100%;overflow-x:auto}.rag-table{width:100%;min-width:800px}
:deep(.rag-table .el-table__inner-wrapper::before){display:none}
:deep(.rag-table th.el-table__cell){background:rgba(248,250,252,0.7);color:#64748b;font-size:12px;text-transform:uppercase;letter-spacing:0.06em}
:deep(.rag-table td.el-table__cell),:deep(.rag-table th.el-table__cell){border-bottom:1px solid rgba(148,163,184,0.08)}
:deep(.rag-table .el-table__row:hover>td.el-table__cell){background:rgba(79,124,255,0.04)}
.action-btns{display:flex;align-items:center;justify-content:center;gap:2px}.action-btns .el-button{font-size:16px}
.empty-state{text-align:center;padding:40px 20px}.empty-state p{margin:4px 0;font-size:16px;font-weight:600}.text-muted{color:#64748b}
.upload-dialog-body{display:flex;flex-direction:column;gap:20px}
.upload-dialog-section{display:flex;flex-direction:column;gap:8px}
.section-label{font-size:14px;font-weight:600;color:#0f172a}
.section-hint{font-size:12px;color:#94a3b8;margin:4px 0 0}
.upload-file-area{border:2px dashed rgba(148,163,184,0.4);border-radius:16px;padding:36px;text-align:center;cursor:pointer;transition:all .2s;background:rgba(248,250,252,0.6)}
.upload-file-area:hover{border-color:#5263ff;background:rgba(82,99,255,0.04)}
.upload-file-area p{margin:8px 0 0;color:#64748b;font-size:14px}
.file-list{display:flex;flex-direction:column;gap:4px;padding:8px 0}
.file-item{display:flex;align-items:center;gap:8px;padding:6px 10px;background:rgba(255,255,255,0.8);border-radius:8px;font-size:13px;color:#0f172a}
.file-item span{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
@media(max-width:1440px){.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:640px){.metric-grid{grid-template-columns:1fr}}
</style>
