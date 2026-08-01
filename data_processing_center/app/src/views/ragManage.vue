<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Download, Delete, Upload, Refresh, Check, Close, View, Edit, FolderOpened } from '@element-plus/icons-vue'
import {
  getKnowledgeBase, getRagJobs, downloadRagJob, deleteRagJob,
  ingestRagJob, unloadRagJob, uploadRagFile, batchQueryJobStatus, getRegions,
  getKnowledgeBases, createKnowledgeBase, updateKnowledgeBase, deleteKnowledgeBase,
  toggleDocEnabled, getDocMetadata, updateDocMetadata
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

// ── KB 管理 ──
const selectedKbId = ref('')
const kbOptions = ref([])
const kbManageVisible = ref(false)
const kbFormVisible = ref(false); const kbFormMode = ref('create')
const kbForm = ref({ id: '', name: '', description: '' }); const kbFormSaving = ref(false)

// ── 元数据弹窗 ──
const metadataVisible = ref(false); const metadataSource = ref('')
const metadata = ref({}); const metadataTagsInput = ref('')
const metadataEditingTags = ref(false); const metadataEditingKb = ref(false); const metadataSelectedKbId = ref(''); const metadataSaving = ref(false)
const uploadFileTags = ref({})  // 上传弹窗每文件标签（key=文件名）
const ingestDialogVisible = ref(false); const ingestTargetJob = ref(null); const ingestTargetKbIds = ref([]); const ingestLoading = ref(false)
const unloadDialogVisible = ref(false); const unloadTargetJob = ref(null); const unloadTargetKbs = ref([]); const unloadLoading = ref(false)
const poolDocCount = ref(0); const poolChunkCount = ref(0)
const poolAssignVisible = ref(false); const poolAssignSources = ref([]); const poolAssignTargetKbs = ref([]); const poolAssignLoading = ref(false)
const addFromPoolVisible = ref(false); const addFromPoolSelections = ref([]); const addFromPoolDocs = ref([])
const uploadConfig = ref({ max_upload_files: 20, max_file_size_mb: 200 })

const enabledFilter = ref('')

const filteredJobs = computed(() => {
  let list = jobs.value
  if (statusFilter.value) list = list.filter(j => j.status === statusFilter.value)
  if (keywordTasks.value.trim()) list = list.filter(j => j.filename.toLowerCase().includes(keywordTasks.value.trim().toLowerCase()))
  return list
})
const filteredKnowledge = computed(() => {
  if (!keyword.value.trim()) return knowledgeData.value.files
  const kw = keyword.value.trim().toLowerCase()
  return knowledgeData.value.files.filter(f => f.filename.toLowerCase().includes(kw) || f.source.toLowerCase().includes(kw))
})
const statusCounts = computed(() => {
  const counts = {}
  jobs.value.forEach(j => { const s = j.status || 'unknown'; counts[s] = (counts[s] || 0) + 1 })
  return counts
})

async function loadAll() { await Promise.all([loadKnowledgeBase(), loadJobs(), loadKnowledgeBases()]) }
async function loadKnowledgeBase() {
  try {
    const params = { sort: knowledgeSort.value }
    if (selectedKbId.value === '__pool__') params.kb_id = '__pool__'
    else if (selectedKbId.value && selectedKbId.value !== '__all__') params.kb_id = selectedKbId.value
    if (enabledFilter.value && selectedKbId.value !== '__pool__' && selectedKbId.value !== '__all__') params.enabled = enabledFilter.value
    const data = await getKnowledgeBase(params)
    // 总览视图合并多KB同文档为一行
    if (selectedKbId.value === '__all__' && data.files) {
      const merged = new Map()
      for (const f of data.files) {
        const key = f.source
        if (merged.has(key)) {
          const exist = merged.get(key)
          exist.chunks += f.chunks
          exist.kb_names.push(f.kb_id === '' || !f.kb_id ? '文档池' : (kbOptions.value.find(k => k.value === f.kb_id)?.name || f.kb_id))
        } else {
          f.kb_names = [f.kb_id === '' || !f.kb_id ? '文档池' : (kbOptions.value.find(k => k.value === f.kb_id)?.name || f.kb_id)]
          merged.set(key, f)
        }
      }
      data.files = [...merged.values()]
      data.total_files = data.files.length
    }
    knowledgeData.value = data
  } catch (e) { console.error(e) }
}

async function loadKnowledgeBases() {
  try {
    const data = await getKnowledgeBases()
    kbOptions.value = (data.kbs || []).map(kb => ({
      value: kb.id, name: kb.name, is_active: kb.is_active, collection: kb.collection,
      description: kb.description || '', document_count: kb.document_count || 0, chunk_count: kb.chunk_count || 0,
      raw_name: kb.name
    }))
    poolDocCount.value = data.pool_document_count || 0
    poolChunkCount.value = data.pool_chunk_count || 0
  } catch (e) { console.error(e) }
}

function onKbChange(kbId) { selectedKbId.value = kbId || ''; loadKnowledgeBase() }

async function loadJobs() {
  loadingJobs.value = true
  try {
    const d = await getRagJobs({ per_page: 1000 })
    const newJobs = d.jobs || []
    const existingMap = new Map(jobs.value.map(j => [j.id, j]))
    const newIds = new Set(newJobs.map(j => j.id))
    for (const nj of newJobs) {
      const existing = existingMap.get(nj.id)
      if (!existing) { jobs.value.push(nj) }
      else {
        existing.status = nj.status; existing.progress = nj.progress; existing.progress_pct = nj.progress_pct
        existing.file_size = nj.file_size; existing.region_code = nj.region_code; existing.region_name = nj.region_name
        existing.filename = nj.filename; existing.output_path = nj.output_path; existing.preview_text = nj.preview_text
        existing.ingest_error = nj.ingest_error; existing.created_at = nj.created_at
      }
    }
    for (let i = jobs.value.length - 1; i >= 0; i--) { if (!newIds.has(jobs.value[i].id)) jobs.value.splice(i, 1) }
  } catch (e) { console.error(e) }
  finally { loadingJobs.value = false }
}
function startPolling(jobIds) {
  jobIds.forEach(id => pendingJobIds.value.add(id))
  if (pollingTimer.value) return
  pollingTimer.value = setInterval(async () => {
    if (pendingJobIds.value.size === 0) { stopPolling(); return }
    try {
      const result = await batchQueryJobStatus([...pendingJobIds.value])
      ;(result.jobs || []).forEach(j => {
        const existing = jobs.value.find(x => x.id === j.id)
        if (existing) { existing.status = j.status; existing.progress = j.progress; existing.progress_pct = j.progress_pct; existing.chunk_count = j.chunk_count; existing.processing_time = j.processing_time; existing.error = j.error }
        else { jobs.value.push(j) }
        if (['completed','failed','ingested','cancelled','cancelling'].includes(j.status)) { pendingJobIds.value.delete(j.id) }
      })
      const existingIds = new Set(jobs.value.map(jj => jj.id))
      for (const id of pendingJobIds.value) { if (!existingIds.has(id)) pendingJobIds.value.delete(id) }
      if (pendingJobIds.value.size === 0) { ElMessage.success('文档处理完成'); stopPolling() }
    } catch (e) {}
  }, 5000)
}
function stopPolling() { if (pollingTimer.value) { clearInterval(pollingTimer.value); pollingTimer.value = null } }
function openUploadDialog() { uploadFiles.value = []; uploadFileRegions.value = {}; uploadFileTags.value = {}; if (fileInput.value) fileInput.value.value = ''; uploadVisible.value = true }
function onFileChange(e) {
  const newFiles = [...(e.target.files || [])]; if (newFiles.length === 0) return
  const existingKeys = new Set(uploadFiles.value.map(f => `${f.name}|${f.size}|${f.lastModified}`))
  const added = newFiles.filter(f => !existingKeys.has(`${f.name}|${f.size}|${f.lastModified}`))
  if (added.length === 0) { ElMessage.info('文件已在列表中'); return }
  if (uploadFiles.value.length + added.length > uploadConfig.value.max_upload_files) { ElMessage.warning(`最多${uploadConfig.value.max_upload_files}个文件，当前已有${uploadFiles.value.length}个`); return }
  uploadFiles.value = [...uploadFiles.value, ...added]; e.target.value = ''
}
function removeFile(index) { const f = uploadFiles.value[index]; const key = f._originalName || f.name; delete uploadFileRegions.value[key]; delete uploadFileTags.value[key]; uploadFiles.value.splice(index, 1) }
async function confirmUpload() {
  if (uploading.value) return
  if (uploadFiles.value.length === 0) { ElMessage.warning('请选择要上传的文档'); return }
  const missing = uploadFiles.value.filter(f => !uploadFileRegions.value[f._originalName || f.name])
  if (missing.length > 0) { ElMessage.warning(`请为以下文档选择所属地区: ${missing.map(f => f.name).join('、')}`); return }
  const existingInKB = new Set(knowledgeData.value.files.map(f => f.filename))
  const activeJobNames = new Set(jobs.value.filter(j => ['processing','queued','ingesting','uploaded'].includes(j.status)).map(j => j.filename))
  const allExistingNames = new Set([...existingInKB, ...activeJobNames, ...jobs.value.filter(j => j.status === 'completed' || j.status === 'ingested').map(j => j.filename)])
  const inProgress = uploadFiles.value.filter(f => activeJobNames.has(f.name))
  if (inProgress.length > 0) { ElMessage.warning(`以下文档正在处理中：${inProgress.map(f => f.name).join('、')}`); return }
  // 自动重名处理：给文件名加递增序号
  const seenNames = new Map()  // 跟踪本批次内已处理的名称
  for (const f of uploadFiles.value) {
    let base = f.name.replace(/(\.[^.]+)$/, '')  // 去掉扩展名
    const ext = f.name.match(/(\.[^.]+)$/)?.[1] || ''
    let candidate = f.name
    let counter = 1
    while (allExistingNames.has(candidate) || seenNames.has(candidate)) {
      candidate = `${base} (${counter})${ext}`
      counter++
    }
    if (candidate !== f.name) {
      f._originalName = f.name
      f._uploadName = candidate
      seenNames.set(candidate, true)
      allExistingNames.add(candidate)
    } else {
      seenNames.set(candidate, true)
      allExistingNames.add(candidate)
    }
  }
  const renamed = uploadFiles.value.filter(f => f._uploadName)
  if (renamed.length > 0) {
    ElMessage.info(`以下文档因重名已自动重命名：${renamed.map(f => `${f.name} → ${f._uploadName}`).join('、')}`)
  }
  uploading.value = true; const results = []; let errorCount = 0
  try {
    // 并行上传，限制并发数 MAX_C=5
    const uploadTasks = uploadFiles.value.map(f => {
      const uploadFile = f._uploadName ? new File([f], f._uploadName, { type: f.type }) : f
      const fd = new FormData(); fd.append('files', uploadFile)
      const origName = f._originalName || f.name
      const r = uploadFileRegions.value[origName] || ''; if (r) fd.append('region_code', r)
      fd.append('kb_id', '')  // 默认文档池
      const fileTags = (uploadFileTags.value[origName] || '').split(',').map(t => t.trim()).filter(Boolean)
      if (fileTags.length > 0) fd.append('tags', JSON.stringify(fileTags))
      return uploadRagFile(fd)
    })
    const MAX_C = 5
    for (let i = 0; i < uploadTasks.length; i += MAX_C) {
      const batchRes = await Promise.all(uploadTasks.slice(i, i + MAX_C))
      for (const res of batchRes) {
        if (res.jobs) { results.push(...res.jobs); startPolling(res.jobs.map(j => j.job_id)) }
        if (res.errors) { res.errors.forEach(e => { ElMessage.error(`${e.filename}: ${e.error}`); errorCount++ }) }
      }
    }
    if (results.length > 0) { ElMessage.success(`已提交 ${results.length} 个文档${errorCount > 0 ? `，${errorCount} 个失败` : ''}`); uploadVisible.value = false; setTimeout(async () => { await loadJobs() }, 2000) }
  } catch (e) { ElMessage.error('上传失败: ' + e.message) } finally { uploading.value = false }
}
async function removeDocBySource(source) {
  try {
    await ElMessageBox.confirm(`确定要删除该文档的所有切片吗？`, '确认删除', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    const B = import.meta.env.VITE_API_BASE_URL || window.location.origin
    const res = await fetch(`${B}/ragdata/knowledge/remove`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sources: [source] }) }).then(r => r.json())
    ElMessage.success(res.message || '已删除')
    const job = jobs.value.find(j => j.id === source)
    if (job) { job.status = 'completed'; job.progress = '已从知识库移除'; job.progress_pct = 100 }
    await loadKnowledgeBase()
  } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败: ' + (e.message || e)) }
}
async function batchRemoveDocs() {
  if (selectedDocs.value.length === 0) { ElMessage.warning('请先选择要删除的文档'); return }
  try {
    await ElMessageBox.confirm(`确定要删除选中的 ${selectedDocs.value.length} 个文档吗？`, '确认批量删除', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    const B = import.meta.env.VITE_API_BASE_URL || window.location.origin
    const sources = selectedDocs.value.map(r => r.source)
    const res = await fetch(`${B}/ragdata/knowledge/remove`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sources }) }).then(r => r.json())
    ElMessage.success(res.message || `已删除`)
    for (const src of sources) { const job = jobs.value.find(j => j.id === src); if (job) { job.status = 'completed'; job.progress = '已从知识库移除'; job.progress_pct = 100 } }
    selectedDocs.value = []; await loadKnowledgeBase()
  } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败: ' + (e.message || e)) }
}
async function handleDelete(job) {
  const msg = job.status === 'ingested' ? `确定要删除 "${job.filename}" 吗？该文档已入库，删除将同时清理向量库中的切片。` : `确定要删除 "${job.filename}" 吗？`
  try { await ElMessageBox.confirm(msg, '确认删除', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }); await deleteRagJob(job.id); ElMessage.success('已删除'); await loadAll() } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败: ' + (e.message || e)) }
}
function openIngestDialog(job) { ingestTargetJob.value = job; ingestTargetKbIds.value = job.kb_id && job.kb_id !== '' ? [job.kb_id] : []; ingestDialogVisible.value = true }
async function confirmIngest() {
  if (!ingestTargetJob.value) return
  ingestLoading.value = true
  try {
    if (ingestTargetKbIds.value.length === 0) {
      // 未选知识库 → 入库到文档池（写入向量库但 kb_id 为空）
      await ingestRagJob(ingestTargetJob.value.id, { kb_id: '' })
      ElMessage.success('已入库到文档池')
    } else {
      for (const kbId of ingestTargetKbIds.value) { await ingestRagJob(ingestTargetJob.value.id, { kb_id: kbId }) }
      ElMessage.success(`已入库到 ${ingestTargetKbIds.value.length} 个知识库`)
    }
    ingestDialogVisible.value = false; await loadAll()
  } catch (e) { ElMessage.error('入库失败: ' + (e.message || e)) }
  finally { ingestLoading.value = false }
}
function openPoolAssign(sources) { poolAssignSources.value = Array.isArray(sources) ? sources : [sources]; poolAssignTargetKbs.value = []; poolAssignVisible.value = true }
async function openAddFromPool() {
  addFromPoolSelections.value = []; addFromPoolVisible.value = true
  try {
    const B = import.meta.env.VITE_API_BASE_URL || window.location.origin
    const res = await fetch(B + '/ragdata/knowledge?kb_id=__pool__&sort=time').then(r => r.json())
    addFromPoolDocs.value = res.files || []
  } catch (e) { ElMessage.error('加载文档池失败'); addFromPoolVisible.value = false }
}
async function confirmAddFromPool() {
  if (addFromPoolSelections.value.length === 0) { ElMessage.warning('请选择要添加的文档'); return }
  if (!selectedKbId.value) return
  try {
    for (const src of addFromPoolSelections.value) {
      await updateDocMetadata(src, { kb_id: selectedKbId.value })
    }
    ElMessage.success(`已将 ${addFromPoolSelections.value.length} 个文档添加到知识库`)
    addFromPoolVisible.value = false
    await Promise.all([loadKnowledgeBase(), loadKnowledgeBases()])
  } catch (e) { ElMessage.error('添加失败: ' + (e.message || e)) }
}
async function confirmPoolAssign() {
  poolAssignLoading.value = true
  try {
    const isEmpty = poolAssignTargetKbs.value.length === 0
    for (const src of poolAssignSources.value) {
      if (selectedKbId.value === '__pool__') {
        // 池分配：必须有选 KB
        if (isEmpty) continue
        await updateDocMetadata(src, { kb_id: poolAssignTargetKbs.value[0] })
        for (let i = 1; i < poolAssignTargetKbs.value.length; i++) {
          const job = jobs.value.find(j => j.id === src)
          if (job && job.output_path) { await ingestRagJob(src, { kb_id: poolAssignTargetKbs.value[i] }) }
        }
      } else {
        // 总览/KB 加入：不选 KB 则移回文档池，选了则改 kb_id（仅移动，非复制）
        if (isEmpty) {
          await updateDocMetadata(src, { kb_id: '' })
        } else {
          for (const kbId of poolAssignTargetKbs.value) {
            await updateDocMetadata(src, { kb_id: kbId })
          }
        }
      }
    }
    const msg = isEmpty ? '已移回文档池' : `已完成 ${poolAssignSources.value.length} 个文档的操作`
    ElMessage.success(msg); poolAssignVisible.value = false
    await Promise.all([loadKnowledgeBase(), loadKnowledgeBases()])
  } catch (e) { ElMessage.error('操作失败: ' + (e.message || e)) }
  finally { poolAssignLoading.value = false }
}
function openUnloadDialog(job) {
  unloadTargetJob.value = job; unloadTargetKbs.value = []; unloadDialogVisible.value = true
}
async function confirmUnload() {
  if (!unloadTargetJob.value) return
  unloadLoading.value = true
  try {
    if (unloadTargetKbs.value.length === 0) {
      if (await ElMessageBox.confirm('未选择知识库，将移除全部副本，确定？', '确认出库', { type: 'warning', confirmButtonText: '全部移除', cancelButtonText: '取消' }).catch(() => false)) {
        await unloadRagJob(unloadTargetJob.value.id)
        ElMessage.success('已从所有知识库移除')
      } else { unloadLoading.value = false; return }
    } else {
      for (const kbId of unloadTargetKbs.value) { await unloadRagJob(unloadTargetJob.value.id, { kb_id: kbId }) }
      ElMessage.success(`已从 ${unloadTargetKbs.value.length} 个知识库移除`)
    }
    unloadDialogVisible.value = false; await loadAll()
  } catch (e) { ElMessage.error('出库失败: ' + (e.message || e)) }
  finally { unloadLoading.value = false }
}
async function showPreview(job) { previewJob.value = job; previewVisible.value = true; previewLoading.value = true; try { const B = import.meta.env.VITE_API_BASE_URL || window.location.origin; const res = await fetch(`${B}/ragdata/jobs/${job.id}`).then(r => r.json()); previewText.value = res.preview_text || '暂无预览内容' } catch (e) { previewText.value = '加载预览失败' } finally { previewLoading.value = false } }
async function previewKnowledgeDoc(source) { previewJob.value = { filename: source }; previewVisible.value = true; previewLoading.value = true; try { const B = import.meta.env.VITE_API_BASE_URL || window.location.origin; const res = await fetch(`${B}/ragdata/knowledge/chunks?source=${encodeURIComponent(source)}`).then(r => r.json()); previewText.value = (res.chunks || []).map(c => c.content || '').join('\n---\n') || '暂无内容' } catch (e) { previewText.value = '加载预览失败' } finally { previewLoading.value = false } }
async function editRegion(row) { regionEditSource.value = row.source; regionEditFilename.value = row.filename; regionEditCode.value = ""; try { const B = import.meta.env.VITE_API_BASE_URL || window.location.origin; const res = await fetch(B + "/ragdata/region-permission?source=" + encodeURIComponent(row.source)).then(r => r.json()); regionEditCode.value = res.region_code || "" } catch (e) {}; regionEditVisible.value = true }
async function saveRegion() { if (regionEditSaving.value) return; regionEditSaving.value = true; try { const B = import.meta.env.VITE_API_BASE_URL || window.location.origin; const res = await fetch(B + "/ragdata/region-permission", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source: regionEditSource.value, filename: regionEditFilename.value, region_code: regionEditCode.value }) }).then(r => r.json()); if (res.status === "ok") { ElMessage.success("权限已更新"); await loadKnowledgeBase() } else ElMessage.error(res.error || "更新失败"); regionEditVisible.value = false } catch (e) { ElMessage.error("保存失败") } finally { regionEditSaving.value = false } }

// ── KB 管理 ──
function openKbManager() { loadKnowledgeBases(); kbManageVisible.value = true }
function openKbForm(mode, kb = null) {
  kbFormMode.value = mode
  kbForm.value = { id: mode === 'edit' && kb ? kb.value : '', name: mode === 'edit' && kb ? kb.name : '', description: mode === 'edit' && kb ? (kb.description || '') : '' }
  kbFormVisible.value = true
}
async function saveKbForm() {
  if (kbFormSaving.value) return
  if (!kbForm.value.name.trim()) { ElMessage.warning('请输入知识库名称'); return }
  kbFormSaving.value = true
  try {
    if (kbFormMode.value === 'create') {
      const id = kbForm.value.name.trim().toLowerCase().replace(/[^a-z0-9_-]/g, '_') || 'kb_' + Date.now()
      await createKnowledgeBase({ id, name: kbForm.value.name.trim(), description: kbForm.value.description.trim() })
      ElMessage.success('知识库已创建')
    } else {
      await updateKnowledgeBase(kbForm.value.id, { name: kbForm.value.name.trim(), description: kbForm.value.description.trim() })
      ElMessage.success('知识库已更新')
    }
    kbFormVisible.value = false; await loadKnowledgeBases()
  } catch (e) { ElMessage.error(e.message || '保存失败') } finally { kbFormSaving.value = false }
}
async function toggleKbActive(kb) {
  try { await updateKnowledgeBase(kb.value, { is_active: kb.is_active }); ElMessage.success(kb.is_active ? '已启用' : '已停用'); await loadKnowledgeBases() }
  catch (e) { ElMessage.error(e.message || '操作失败') }
}
async function deleteKb(kb) {
  if (kb.value === 'default') { ElMessage.warning('不能删除默认知识库'); return }
  try {
    await ElMessageBox.confirm(`确定删除知识库"${kb.name}"？(${kb.document_count||0}个文档)`, '确认删除', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    await deleteKnowledgeBase(kb.value)
    ElMessage.success('已删除')
    if (selectedKbId.value === kb.value) { selectedKbId.value = ''; loadKnowledgeBase() }
    await loadKnowledgeBases()
  } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败') }
}

async function handleToggleEnabled(row) {
  const original = !row.enabled  // v-model 已翻转，回退到原值用于出错恢复
  try { await toggleDocEnabled(row.source, row.enabled); ElMessage.success(row.enabled ? '已启用' : '已禁用') }
  catch (e) { row.enabled = original; ElMessage.error(e.message || '操作失败') }  // API失败时回退
}

async function openMetadata(source) {
  metadataSource.value = source; metadataVisible.value = true
  try { metadata.value = await getDocMetadata(source); metadataEditingTags.value = false; metadataEditingKb.value = false } catch (e) { ElMessage.error('加载元数据失败') }
}
function startEditTags() { metadataTagsInput.value = (metadata.value.tags || []).join(', '); metadataEditingTags.value = true }
function cancelEditTags() { metadataEditingTags.value = false }
function startEditKb() { metadataSelectedKbId.value = metadata.value.kb_id || 'default'; metadataEditingKb.value = true }
function cancelEditKb() { metadataEditingKb.value = false }
async function saveMetadata() {
  if (metadataSaving.value) return; metadataSaving.value = true
  try {
    const body = {}
    if (metadataEditingTags.value) { body.tags = metadataTagsInput.value.split(',').map(t => t.trim()).filter(Boolean) }
    if (metadataEditingKb.value) { body.kb_id = metadataSelectedKbId.value }
    await updateDocMetadata(metadataSource.value, body)
    ElMessage.success('已保存'); metadataEditingTags.value = false; metadataEditingKb.value = false
    await loadKnowledgeBase()
  } catch (e) { ElMessage.error(e.message || '保存失败') } finally { metadataSaving.value = false }
}

const modelStatus = ref({ status: 'unknown', model_loaded: false, active_count: 0, queue_size: 0, uptime: 0, total_processed: 0 })
async function loadModelStatus() {
  try { const B = import.meta.env.VITE_API_BASE_URL || window.location.origin; modelStatus.value = await fetch(B + '/ragdata/model-service/status').then(r => r.json()) }
  catch (e) { modelStatus.value.status = 'offline' }
}
setInterval(loadModelStatus, 15000)

function resolveStatusType(s) { return { completed:'success', ingested:'success', cancelled:'info', processing:'warning', queued:'info', ingesting:'warning', uploaded:'info', failed:'danger' }[s] || 'info' }
function resolveStatusLabel(s) { return { completed:'已完成', ingested:'已入库', cancelled:'已取消', processing:'处理中', queued:'排队中', ingesting:'入库中', uploaded:'已上传', failed:'失败' }[s] || s }

onMounted(async () => {
  await loadAll(); loadModelStatus()
  getRegions().then(d => { regionOptions.value = (d.regions || []).map(r => ({ value: r.code, label: r.name })) }).catch(e => console.error(e))
  const active = jobs.value.filter(j => ['processing','queued','ingesting'].includes(j.status))
  if (active.length > 0) startPolling(active.map(j => j.id))
  // 从后端动态读取上传限制
  try { const B = import.meta.env.VITE_API_BASE_URL || window.location.origin; const d = await fetch(B + '/ragdata/stats').then(r => r.json()); if (d.max_upload_files) uploadConfig.value = d } catch (e) {}
})
</script>
<template>
  <div class="rag-page">
    <!-- ═══ 状态栏 ═══ -->
    <div class="model-status-bar" :class="modelStatus.model_loaded ? 'healthy' : (modelStatus.model_loading ? 'warming_up' : 'offline')">
      <span class="status-dot" :class="modelStatus.model_loaded?'healthy':(modelStatus.model_loading?'warming_up':'offline')"></span>
      <span v-if="modelStatus.model_loaded" class="status-text">模型就绪</span>
      <span v-else-if="modelStatus.model_loading" class="status-text">模型加载中...</span>
      <span v-else class="status-text">模型服务未启动</span>
      <span class="status-divider">|</span>
      <span>处理中 {{ (statusCounts.processing||0)+(statusCounts.queued||0)+(statusCounts.ingesting||0) }}</span>
      <span class="status-divider">|</span>
      <span>已完成 {{ statusCounts.completed||0 }}</span>
      <span class="status-divider">|</span>
      <span>已入库 {{ statusCounts.ingested||0 }}</span>
      <span class="status-right">模型已处理 {{ modelStatus.total_processed||0 }}</span>
    </div>

    <!-- ═══ 统计卡片 ═══ -->
    <div class="metric-grid">
      <article class="metric-card tone-primary"><div class="metric-label">文档资产</div><div class="metric-value">{{ knowledgeData.total_files }}</div><div class="metric-delta">个文档已入库</div></article>
      <article class="metric-card tone-success"><div class="metric-label">向量切片</div><div class="metric-value">{{ knowledgeData.total_chunks }}</div><div class="metric-delta">个切片可检索</div></article>
      <article class="metric-card tone-warning"><div class="metric-label">处理中</div><div class="metric-value">{{ (statusCounts.processing||0)+(statusCounts.queued||0) }}</div><div class="metric-delta">个任务排队/处理中</div></article>
      <article class="metric-card tone-info"><div class="metric-label">已完成任务</div><div class="metric-value">{{ statusCounts.completed||0 }}</div><div class="metric-delta">个待入库</div></article>
    </div>

    <!-- ═══ 知识库列表（初始视图）═══ -->
    <div v-if="!selectedKbId" class="card-panel">
      <div class="section-header">
        <div><h3>知识库</h3><p>选择一个知识库查看其中的文档</p></div>
        <div style="display:flex;align-items:center;gap:8px;">
          <el-button type="primary" size="small" @click="openKbForm('create')">新建知识库</el-button>
          <el-button size="small" @click="openKbManager">管理</el-button>
        </div>
      </div>
      <div v-if="kbOptions.length===0" style="text-align:center;padding:60px"><p style="color:#64748b">暂无知识库</p></div>
      <div v-else class="kb-card-grid">
        <div class="kb-card overview-card" @click="onKbChange('__all__')">
          <div class="kb-card-body">
            <div class="kb-card-name">总览</div>
            <div class="kb-card-meta">全部文档 · {{ kbOptions.reduce((s,k)=>s+(k.document_count||0),0) + poolDocCount }} 文档</div>
          </div>
          <div class="kb-card-arrow">&gt;</div>
        </div>
        <div class="kb-card pool-card" @click="onKbChange('__pool__')">
          <div class="kb-card-body">
            <div class="kb-card-name">文档池</div>
            <div class="kb-card-meta">待分配 · {{ poolDocCount }} 文档 / {{ poolChunkCount }} 切片</div>
          </div>
          <div class="kb-card-arrow">&gt;</div>
        </div>
        <div v-for="kb in kbOptions" :key="kb.value" class="kb-card" :class="{disabled:!kb.is_active}" @click="kb.is_active ? onKbChange(kb.value) : null">
          <div class="kb-card-icon">📁</div>
          <div class="kb-card-body">
            <div class="kb-card-name">{{ kb.name }}<span v-if="!kb.is_active" style="display:inline-block;margin-left:8px;padding:1px 8px;border-radius:999px;background:#fef2f2;color:#ef4444;font-size:11px;font-weight:600;vertical-align:middle">已停用</span></div>
            <div class="kb-card-meta">{{ kb.document_count||0 }} 文档 · {{ kb.chunk_count||0 }} 切片</div>
          </div>
          <div style="display:flex;align-items:center;gap:6px" @click.stop>
            <el-switch v-model="kb.is_active" size="small" @change="toggleKbActive(kb)"/>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══ 知识库文档列表（选中KB后）═══ -->
    <div v-if="selectedKbId">
      <div class="card-panel" style="margin-bottom:0;padding-bottom:12px">
        <div class="section-header">
          <div style="display:flex;align-items:center;gap:10px">
            <el-button link size="small" @click="onKbChange('')" style="font-size:18px;padding:0">← 返回</el-button>
            <div>
              <h3 style="margin-bottom:2px">{{ selectedKbId==='__all__' ? '总览' : (selectedKbId==='__pool__' ? '文档池' : (kbOptions.find(k=>k.value===selectedKbId)?.name || selectedKbId)) }}</h3>
              <p style="margin:0">{{ selectedKbId==='__all__' ? '全部知识库 + 文档池' : (selectedKbId==='__pool__' ? '待分配文档' : '') }} · {{ knowledgeData.total_files }} 文档 / {{ knowledgeData.total_chunks }} 切片</p>
            </div>
          </div>
          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
            <el-button v-if="selectedKbId!=='__pool__'&&selectedKbId!=='__all__'&&poolDocCount>0" type="primary" size="small" @click="openAddFromPool">从文档池添加</el-button>
            <el-select v-if="selectedKbId!=='__pool__'&&selectedKbId!=='__all__'" v-model="enabledFilter" @change="loadKnowledgeBase" clearable placeholder="启用筛选" size="small" style="width:100px"><el-option label="全部" value=""/><el-option label="已启用" value="true"/><el-option label="已禁用" value="false"/></el-select>
            <el-button v-if="selectedDocs.length>0&&selectedKbId==='__pool__'" type="success" size="small" @click="openPoolAssign(selectedDocs.map(d=>d.source))">分配到KB({{selectedDocs.length}})</el-button>
            <el-button v-if="selectedDocs.length>0&&selectedKbId!=='__pool__'" type="danger" :icon="Delete" size="small" @click="batchRemoveDocs">删除({{selectedDocs.length}})</el-button>
            <el-select v-model="knowledgeSort" @change="loadKnowledgeBase" size="small" style="width:110px"><el-option label="按时间" value="time"/><el-option label="按名称" value="name"/><el-option label="按切片数" value="chunks"/></el-select>
            <el-input v-model="keyword" style="width:180px" placeholder="搜索文档..." :prefix-icon="Search" clearable size="small"/>
          </div>
        </div>
      </div>
      <div class="card-panel">
        <div class="table-wrap">
          <el-table :data="filteredKnowledge" class="rag-table" v-loading="loading" @selection-change="(sel)=>selectedDocs=sel">
            <el-table-column type="selection" width="34"/>
            <el-table-column type="index" label="#" width="42"/>
            <el-table-column prop="filename" label="文档名称" min-width="150" show-overflow-tooltip/>
            <el-table-column v-if="selectedKbId!=='__all__'" label="启用" width="55" align="center"><template #default="{row}"><el-switch v-model="row.enabled" @change="handleToggleEnabled(row)" size="small"/></template></el-table-column>
            <el-table-column label="标签" width="90" align="center"><template #default="{row}"><span v-if="!Array.isArray(row.tags)||row.tags.length===0" class="text-muted" style="font-size:11px">-</span><el-tag v-for="(t,i) in (Array.isArray(row.tags)?row.tags.slice(0,2):[])" :key="i" size="small" style="margin:1px;font-size:11px">{{t}}</el-tag><span v-if="Array.isArray(row.tags)&&row.tags.length>2" class="text-muted" style="font-size:11px">+{{row.tags.length-2}}</span></template></el-table-column>
            <el-table-column label="时间" width="105" align="center"><template #default="{row}"><span class="text-muted" style="font-size:11px">{{row.last_ingest?new Date(Number(row.last_ingest)*1000).toLocaleDateString():'-'}}</span></template></el-table-column>
            <el-table-column label="地区" width="85" align="center"><template #default="{row}"><span class="text-muted" style="font-size:12px">{{row.region_name||row.region_code||'-'}}</span></template></el-table-column>
            <el-table-column v-if="selectedKbId==='__all__'" label="所属知识库" width="130" align="center"><template #default="{row}"><div style="display:flex;flex-wrap:wrap;gap:2px;justify-content:center"><el-tag v-for="(kn,i) in (row.kb_names||[]).filter(Boolean)" :key="i" size="small" style="font-size:10px;max-width:90px">{{kn}}</el-tag></div></template></el-table-column>
            <el-table-column label="切片" width="50" align="center"><template #default="{row}"><span class="text-muted">{{row.chunks||0}}</span></template></el-table-column>
            <el-table-column label="操作" :width="selectedKbId==='__all__'?220:260" align="center" fixed="right">
              <template #default="{row}">
                <el-button v-if="selectedKbId!=='__all__'" type="info" link size="small" @click="openMetadata(row.source)"><el-icon><View/></el-icon></el-button>
                <el-button type="primary" link size="small" @click="previewKnowledgeDoc(row.source)">预览</el-button>
                <el-button v-if="selectedKbId==='__pool__'" type="success" link size="small" @click="openPoolAssign(row.source)">分配</el-button>
                <el-button v-else type="warning" link size="small" @click="openPoolAssign(row.source)">加入</el-button>
                <el-button v-if="selectedKbId!=='__pool__'" type="warning" link size="small" @click="editRegion(row)"><el-icon><Edit/></el-icon></el-button>
                <el-button type="danger" link size="small" @click="removeDocBySource(row.source)"><el-icon><Delete/></el-icon></el-button>
            </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </div>

    <!-- ═══ 处理任务 ═══ -->
    <div class="card-panel">
      <div class="section-header"><div><h3>处理任务</h3><p>文档上传、解析与入库管理</p></div><div style="display:flex;align-items:center;gap:8px;"><el-button type="primary" :icon="Upload" size="large" @click="openUploadDialog">上传文档</el-button><el-button :icon="Refresh" @click="loadJobs" :loading="loadingJobs" circle/></div></div>
      <div class="filter-bar">
        <button class="filter-chip" :class="{active:!statusFilter}" @click="statusFilter=''">全部({{jobs.length}})</button>
        <button v-for="[k,l] in [['processing','处理中'],['completed','已完成'],['ingested','已入库'],['failed','失败']]" :key="k" class="filter-chip" :class="{active:statusFilter===k}" @click="statusFilter=statusFilter===k?'':k">{{l}}({{statusCounts[k]||0}})</button>
        <el-input v-model="keywordTasks" style="width:180px;margin-left:auto" placeholder="搜索任务..." :prefix-icon="Search" clearable size="small"/>
      </div>
      <div class="table-wrap">
        <el-table :data="filteredJobs" class="rag-table" v-loading="loadingJobs">
          <el-table-column prop="filename" label="文件名" min-width="160" show-overflow-tooltip/>
          <el-table-column label="地区" width="110" align="center"><template #default="{row}">{{row.region_name||row.region_code||'未设置'}}</template></el-table-column>
          <el-table-column label="大小" width="90" align="center"><template #default="{row}"><span class="text-muted">{{row.file_size?(row.file_size/1024/1024).toFixed(1)+'MB':'-'}}</span></template></el-table-column>
          <el-table-column label="状态" width="100" align="center"><template #default="{row}"><el-tag :type="resolveStatusType(row.status)" size="small" round>{{resolveStatusLabel(row.status)}}</el-tag></template></el-table-column>
          <el-table-column label="切片数" width="70" align="center"><template #default="{row}">{{row.chunk_count||'-'}}</template></el-table-column>
          <el-table-column label="耗时" width="70" align="center"><template #default="{row}"><span class="text-muted">{{row.processing_time?row.processing_time+'s':'-'}}</span></template></el-table-column>
          <el-table-column label="进度" min-width="200">
            <template #default="{row}">
              <div style="display:flex;flex-direction:column;gap:3px">
                <el-progress v-if="(row.status==='completed'&&row.progress==='处理完成')||(row.status==='completed'&&row.progress_pct===100)||row.status==='ingested'" :percentage="100" :stroke-width="6" color="#22c55e" :show-text="false"/>
                <el-progress v-else-if="row.status==='failed'" :percentage="0" :stroke-width="6" color="#ef4444" :show-text="false"/>
                <el-progress v-else-if="row.progress_pct>0" :percentage="row.progress_pct" :stroke-width="6" :show-text="false"/>
                <el-progress v-else :percentage="50" :indeterminate="true" :stroke-width="6" :show-text="false" :duration="2"/>
                <span class="text-muted" style="font-size:11px">{{row.progress||'-'}}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="220" align="center" fixed="right">
            <template #default="{row}"><div class="action-btns">
              <el-button v-if="row.status==='completed'||row.status==='ingested'" type="info" link size="small" @click="showPreview(row)"><el-icon><View/></el-icon></el-button>
              <el-button v-if="row.status==='completed'||row.status==='ingested'" type="primary" link size="small" @click="downloadRagJob(row.id)"><el-icon><Download/></el-icon></el-button>
              <el-button v-if="row.status==='completed'" type="success" link size="small" @click="openIngestDialog(row)"><el-icon><Check/></el-icon></el-button>
              <el-button v-if="row.status==='ingested'" type="warning" link size="small" @click="openUnloadDialog(row)"><el-icon><Close/></el-icon></el-button>
              <el-button type="danger" link size="small" @click="handleDelete(row)"><el-icon><Delete/></el-icon></el-button>
            </div></template>
          </el-table-column>
        </el-table>
      </div>
      <div v-if="!loadingJobs&&filteredJobs.length===0" class="empty-state"><p>暂无处理任务</p><p class="text-muted">点击"上传文档"提交 PDF / DOCX 文档</p></div>
    </div>

    <!-- ═══ 上传弹窗 ═══ -->
    <el-dialog v-model="uploadVisible" title="上传文档" width="540px" :close-on-click-modal="false" destroy-on-close>
      <div class="upload-dialog-body">
        <div class="upload-dialog-section"><div class="section-label">选择文档</div>
        <div class="upload-file-area" @click="fileInput?.click()"><el-icon :size="36" color="#94a3b8"><Upload/></el-icon><p>点击选择 PDF / DOCX / DOC 文件</p><p class="section-hint">最多{{uploadConfig.max_upload_files}}个，单个≤{{uploadConfig.max_file_size_mb}}MB</p><input ref="fileInput" type="file" accept=".pdf,.docx,.doc" multiple style="display:none" @change="onFileChange"/></div>
        <div v-if="uploadFiles.length>0" class="file-list"><div v-for="(f,i) in uploadFiles" :key="i" class="file-item"><div style="flex:1;min-width:0;display:flex;align-items:center;gap:6px;flex-wrap:wrap"><span style="min-width:80px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px">{{f._uploadName||f.name}}</span><el-select :model-value="uploadFileRegions[f._originalName||f.name]||''" @update:model-value="(val)=>{const k=f._originalName||f.name; uploadFileRegions[k]=val||''}" placeholder="地区*" size="small" style="width:100px" clearable><el-option v-for="r in regionOptions" :key="r.value" :label="r.label" :value="r.value"/></el-select><el-input :model-value="uploadFileTags[f._originalName||f.name]||''" @update:model-value="(val)=>{const k=f._originalName||f.name; uploadFileTags[k]=val}" placeholder="标签" size="small" style="width:120px"/></div><el-button type="danger" link size="small" @click="removeFile(i)"><el-icon><Close/></el-icon></el-button></div></div>
      </div></div>
      <template #footer><el-button @click="uploadVisible=false" :disabled="uploading">取消</el-button><el-button type="primary" :loading="uploading" @click="confirmUpload">开始上传处理</el-button></template>
    </el-dialog>

    <!-- ═══ 预览弹窗 ═══ -->
    <el-dialog v-model="previewVisible" :title="'预览: '+(previewJob?.filename||'')" width="800px" :close-on-click-modal="false" destroy-on-close><div v-loading="previewLoading" style="max-height:500px;overflow-y:auto;white-space:pre-wrap;font-size:13px;line-height:1.8;color:#334155;background:#f8fafc;padding:16px;border-radius:12px">{{previewText}}</div></el-dialog>

    <!-- ═══ 权限编辑 ═══ -->
    <el-dialog v-model="regionEditVisible" title="编辑文档权限" width="480px" :close-on-click-modal="false" destroy-on-close>
      <div style="display:flex;flex-direction:column;gap:16px"><div><div style="font-weight:600;margin-bottom:6px">文档名称</div><div style="color:#64748b">{{regionEditFilename}}</div></div><div><div style="font-weight:600;margin-bottom:6px">所属地区</div><el-select v-model="regionEditCode" placeholder="选择地区" style="width:100%" clearable><el-option v-for="r in regionOptions" :key="r.value" :label="r.label" :value="r.value"/></el-select></div></div>
      <template #footer><el-button @click="regionEditVisible=false" :disabled="regionEditSaving">取消</el-button><el-button type="primary" :loading="regionEditSaving" @click="saveRegion">保存</el-button></template>
    </el-dialog>

    <!-- ═══ KB 管理弹窗 ═══ -->
    <el-dialog v-model="kbManageVisible" title="知识库管理" width="700px" :close-on-click-modal="false" destroy-on-close>
      <div style="margin-bottom:12px"><el-button type="primary" size="small" @click="openKbForm('create')">新建知识库</el-button></div>
      <el-table :data="kbOptions" size="small">
        <el-table-column label="名称" min-width="160"><template #default="{row}"><span :style="!row.is_active?'color:#94a3b8;font-style:italic':''">{{row.name}}</span><span v-if="!row.is_active" style="display:inline-block;margin-left:6px;padding:0 6px;border-radius:999px;background:#fef2f2;color:#ef4444;font-size:11px;font-weight:600">已停用</span></template></el-table-column>
        <el-table-column label="ID" width="120" align="center"><template #default="{row}"><span class="text-muted" style="font-size:12px">{{row.value}}</span></template></el-table-column>
        <el-table-column label="文档" width="70" align="center"><template #default="{row}">{{row.document_count||0}}</template></el-table-column>
        <el-table-column label="切片" width="70" align="center"><template #default="{row}">{{row.chunk_count||0}}</template></el-table-column>
        <el-table-column label="启用" width="65" align="center"><template #default="{row}"><el-switch v-model="row.is_active" @change="toggleKbActive(row)" size="small"/></template></el-table-column>
        <el-table-column label="操作" width="160" align="center"><template #default="{row}"><el-button link size="small" @click="openKbForm('edit',row)">重命名</el-button><el-button link size="small" type="danger" @click="deleteKb(row)" v-if="row.value!=='default'">删除</el-button></template></el-table-column>
      </el-table>
    </el-dialog>

    <!-- ═══ KB 新建/编辑 ═══ -->
    <el-dialog v-model="kbFormVisible" :title="kbFormMode==='create'?'新建知识库':'编辑知识库'" width="460px" :close-on-click-modal="false" destroy-on-close>
      <div style="display:flex;flex-direction:column;gap:14px">
        <div><div style="font-weight:600;margin-bottom:4px">名称</div><el-input v-model="kbForm.name" placeholder="知识库名称" maxlength="100"/></div>
        <div><div style="font-weight:600;margin-bottom:4px">描述</div><el-input v-model="kbForm.description" type="textarea" placeholder="可选描述" maxlength="500"/></div>
      </div>
      <template #footer><el-button @click="kbFormVisible=false" :disabled="kbFormSaving">取消</el-button><el-button type="primary" :loading="kbFormSaving" @click="saveKbForm">保存</el-button></template>
    </el-dialog>

    <!-- ═══ 入库弹窗 ═══ -->
    <el-dialog v-model="ingestDialogVisible" title="入库到知识库" width="460px" :close-on-click-modal="false" destroy-on-close>
      <div v-if="ingestTargetJob" style="display:flex;flex-direction:column;gap:14px">
        <div><div style="font-weight:600;margin-bottom:4px">文档名称</div><div style="color:#64748b">{{ingestTargetJob.filename}}</div></div>
        <div><div style="font-weight:600;margin-bottom:4px">目标知识库（不选则默认文档池）</div>
          <el-select v-model="ingestTargetKbIds" placeholder="不选则入库到文档池" style="width:100%" multiple>
            <el-option v-for="kb in kbOptions" :key="kb.value" :label="kb.name" :value="kb.value"/>
          </el-select>
        </div>
      </div>
      <template #footer><el-button @click="ingestDialogVisible=false" :disabled="ingestLoading">取消</el-button><el-button type="primary" :loading="ingestLoading" @click="confirmIngest">确认入库</el-button></template>
    </el-dialog>

    <!-- ═══ 池分配/文档迁移弹窗 ═══ -->
    <el-dialog v-model="poolAssignVisible" :title="selectedKbId==='__pool__'?'分配到知识库':'加入知识库'" width="460px" :close-on-click-modal="false" destroy-on-close>
      <div style="display:flex;flex-direction:column;gap:14px">
        <div><div style="font-weight:600;margin-bottom:4px">已选文档</div><div style="color:#64748b">{{poolAssignSources.length}} 个文档</div></div>
        <div><div style="font-weight:600;margin-bottom:4px">目标知识库（不选则默认文档池）</div>
          <el-select v-model="poolAssignTargetKbs" placeholder="选择知识库" style="width:100%" multiple>
            <el-option v-for="kb in kbOptions" :key="kb.value" :label="kb.name" :value="kb.value"/>
          </el-select>
        </div>
      </div>
      <template #footer><el-button @click="poolAssignVisible=false" :disabled="poolAssignLoading">取消</el-button><el-button type="primary" :loading="poolAssignLoading" @click="confirmPoolAssign">确认</el-button></template>
    </el-dialog>

    <!-- ═══ 出库弹窗 ═══ -->
    <el-dialog v-model="unloadDialogVisible" title="从知识库移除" width="460px" :close-on-click-modal="false" destroy-on-close>
      <div v-if="unloadTargetJob" style="display:flex;flex-direction:column;gap:14px">
        <div><div style="font-weight:600;margin-bottom:4px">文档名称</div><div style="color:#64748b">{{unloadTargetJob.filename}}</div></div>
        <div><div style="font-weight:600;margin-bottom:4px">要移除的知识库（不选则全部移除）</div>
          <el-select v-model="unloadTargetKbs" placeholder="不选则移除全部" style="width:100%" multiple clearable>
            <el-option v-for="kb in kbOptions" :key="kb.value" :label="kb.name" :value="kb.value"/>
          </el-select>
        </div>
      </div>
      <template #footer><el-button @click="unloadDialogVisible=false" :disabled="unloadLoading">取消</el-button><el-button type="danger" :loading="unloadLoading" @click="confirmUnload">确认移除</el-button></template>
    </el-dialog>

    <!-- ═══ 从文档池添加弹窗 ═══ -->
    <el-dialog v-model="addFromPoolVisible" title="从文档池添加" width="600px" :close-on-click-modal="false" destroy-on-close>
      <div v-if="addFromPoolDocs.length===0" style="text-align:center;padding:30px;color:#94a3b8">文档池为空</div>
      <el-table v-else :data="addFromPoolDocs" @selection-change="(sel)=>addFromPoolSelections=sel.map(s=>s.source)" size="small" max-height="360">
        <el-table-column type="selection" width="40"/>
        <el-table-column prop="filename" label="文档名称" min-width="180" show-overflow-tooltip/>
        <el-table-column label="切片" width="60" align="center"><template #default="{row}">{{row.chunks||0}}</template></el-table-column>
        <el-table-column label="地区" width="100" align="center"><template #default="{row}"><span class="text-muted">{{row.region_name||row.region_code||'-'}}</span></template></el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="addFromPoolVisible=false">取消</el-button>
        <el-button type="primary" :disabled="addFromPoolSelections.length===0" @click="confirmAddFromPool">添加到当前知识库({{addFromPoolSelections.length}})</el-button>
      </template>
    </el-dialog>

    <!-- ═══ 元数据弹窗 ═══ -->
    <el-dialog v-model="metadataVisible" title="文档元数据" width="560px" :close-on-click-modal="false" destroy-on-close>
      <div v-if="metadata.source" style="display:flex;flex-direction:column;gap:16px">
        <div style="border:1px solid rgba(148,163,184,0.12);border-radius:10px;padding:14px">
          <div style="font-weight:700;font-size:14px;margin-bottom:8px;color:#0f172a">文件信息</div>
          <div class="meta-row"><span class="meta-label">文件名</span><span>{{metadata.filename||'-'}}</span></div>
          <div class="meta-row"><span class="meta-label">Source ID</span><span class="text-muted">{{metadata.source||'-'}}</span></div>
          <div class="meta-row"><span class="meta-label">切片数量</span><span>{{metadata.chunks||0}}</span></div>
        </div>
        <div style="border:1px solid rgba(148,163,184,0.12);border-radius:10px;padding:14px">
          <div style="font-weight:700;font-size:14px;margin-bottom:8px;color:#0f172a">处理信息</div>
          <div class="meta-row"><span class="meta-label">入库时间</span><span>{{metadata.created_at?new Date(Number(metadata.created_at)*1000).toLocaleString():'-'}}</span></div>
          <div class="meta-row"><span class="meta-label">启用状态</span><el-switch v-model="metadata.enabled" @change="updateDocMetadata(metadata.source,{enabled:metadata.enabled}).then(()=>ElMessage.success('已更新')).catch(e=>ElMessage.error(e.message))" size="small"/></div>
          <div class="meta-row"><span class="meta-label">标签</span>
            <template v-if="!metadataEditingTags"><el-tag v-for="(t,i) in (metadata.tags||[])" :key="i" size="small" style="margin:1px">{{t}}</el-tag><el-button link size="small" @click="startEditTags">编辑</el-button></template>
            <template v-else><el-input v-model="metadataTagsInput" size="small" placeholder="逗号分隔" style="flex:1"/><el-button type="primary" link size="small" @click="saveMetadata" :loading="metadataSaving">保存</el-button><el-button link size="small" @click="cancelEditTags">取消</el-button></template>
          </div>
        </div>
        <div style="border:1px solid rgba(148,163,184,0.12);border-radius:10px;padding:14px">
          <div style="font-weight:700;font-size:14px;margin-bottom:8px;color:#0f172a">权限信息</div>
          <div class="meta-row"><span class="meta-label">地区</span><span>{{metadata.region_code||'未设置'}}</span></div>
          <div class="meta-row"><span class="meta-label">知识库</span>
            <template v-if="!metadataEditingKb">
              <span>{{metadata.kb_name||metadata.kb_id||'文档池'}}</span>
              <el-button link size="small" @click="startEditKb">加入</el-button>
            </template>
            <template v-else>
              <el-select v-model="metadataSelectedKbId" size="small" style="flex:1">
                <el-option label="文档池" value=""/>
                <el-option v-for="kb in kbOptions" :key="kb.value" :label="kb.name" :value="kb.value"/>
              </el-select>
              <el-button type="primary" link size="small" @click="saveMetadata" :loading="metadataSaving">保存</el-button>
              <el-button link size="small" @click="cancelEditKb">取消</el-button>
            </template>
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.rag-page{display:flex;flex-direction:column;gap:16px;min-height:100%}
.model-status-bar{display:flex;align-items:center;gap:8px;padding:8px 16px;border-radius:12px;font-size:13px;color:#334155;background:rgba(255,255,255,.7);border:1px solid rgba(148,163,184,.12)}
.model-status-bar .status-dot{width:9px;height:9px;border-radius:50%;flex-shrink:0}
.model-status-bar .status-dot.healthy{background:#22c55e;box-shadow:0 0 6px rgba(34,197,94,.4)}
.model-status-bar .status-dot.warming_up{background:#f59e0b;animation:pulse 1.5s infinite}
.model-status-bar .status-dot.offline{background:#94a3b8}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.status-divider{color:rgba(148,163,184,.5)}
.status-right{margin-left:auto;color:#64748b}
.metric-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}
.metric-card{position:relative;overflow:hidden;padding:18px;border-radius:16px;background:rgba(255,255,255,.92);border:1px solid rgba(148,163,184,.14);box-shadow:0 16px 48px rgba(15,23,42,.06)}
.metric-card::after{content:"";position:absolute;inset:auto -20px -20px auto;width:80px;height:80px;border-radius:50%;opacity:.12}
.metric-card.tone-primary::after{background:#4f7cff}.metric-card.tone-success::after{background:#22c55e}.metric-card.tone-warning::after{background:#f59e0b}.metric-card.tone-info::after{background:#38bdf8}
.metric-label{color:#64748b;font-size:13px}.metric-value{margin:8px 0 6px;font-size:30px;font-weight:700;color:#0f172a}.metric-delta{color:#64748b;font-size:12px}
.card-panel{background:rgba(255,255,255,.5);border:1px solid rgba(148,163,184,.08);border-radius:16px;padding:18px}
.section-header{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:10px}
.section-header h3{margin:0 0 4px;font-size:18px}.section-header p{margin:0;color:#64748b;font-size:12px}
.filter-bar{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:10px}
.filter-chip{padding:5px 12px;border:1px solid rgba(148,163,184,.18);border-radius:999px;background:rgba(255,255,255,.7);color:#64748b;font-size:12px;cursor:pointer}
.filter-chip:hover{border-color:rgba(82,99,255,.3);color:#0f172a}.filter-chip.active{background:rgba(82,99,255,.1);border-color:rgba(82,99,255,.4);color:#5263ff;font-weight:600}
.table-wrap{width:100%;overflow-x:auto}.rag-table{width:100%;min-width:800px}
:deep(.rag-table .el-table__inner-wrapper::before){display:none}
:deep(.rag-table th.el-table__cell){background:rgba(248,250,252,.7);color:#64748b;font-size:11px;text-transform:uppercase;letter-spacing:.05em}
:deep(.rag-table td.el-table__cell),:deep(.rag-table th.el-table__cell){border-bottom:1px solid rgba(148,163,184,.08)}
:deep(.rag-table .el-table__row:hover>td.el-table__cell){background:rgba(79,124,255,.04)}
.action-btns{display:flex;align-items:center;justify-content:center;gap:1px}.action-btns .el-button{font-size:15px}
.empty-state{text-align:center;padding:36px 20px}.empty-state p{margin:4px 0;font-size:15px;font-weight:600}.text-muted{color:#64748b}
.kb-card-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:4px}
.kb-card{display:flex;align-items:center;gap:14px;padding:18px 16px;border-radius:14px;background:rgba(255,255,255,.92);border:1px solid rgba(148,163,184,.14);cursor:pointer;transition:all .2s}
.kb-card:hover{border-color:rgba(82,99,255,.3);box-shadow:0 8px 24px rgba(15,23,42,.08);transform:translateY(-2px)}
.kb-card.disabled{opacity:.6;background:rgba(248,250,252,.8);cursor:not-allowed}
.kb-card-icon{font-size:28px;flex-shrink:0}
.kb-card-body{flex:1;min-width:0}
.kb-card-name{font-size:15px;font-weight:600;color:#0f172a;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.kb-card-meta{font-size:12px;color:#64748b;margin-top:3px}
.kb-card-arrow{font-size:20px;color:rgba(148,163,184,.5)}
@media(max-width:1440px){.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.kb-card-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:640px){.metric-grid{grid-template-columns:1fr}.kb-card-grid{grid-template-columns:1fr}}
.upload-dialog-body{display:flex;flex-direction:column;gap:16px}.upload-dialog-section{display:flex;flex-direction:column;gap:6px}.section-label{font-size:14px;font-weight:600;color:#0f172a}.section-hint{font-size:12px;color:#94a3b8;margin:4px 0 0}
.upload-file-area{border:2px dashed rgba(148,163,184,.4);border-radius:14px;padding:32px;text-align:center;cursor:pointer;transition:all .2s;background:rgba(248,250,252,.6)}.upload-file-area:hover{border-color:#5263ff;background:rgba(82,99,255,.04)}.upload-file-area p{margin:6px 0 0;color:#64748b;font-size:13px}
.file-list{display:flex;flex-direction:column;gap:3px;padding:6px 0}.file-item{display:flex;align-items:center;gap:6px;padding:5px 8px;background:rgba(255,255,255,.8);border-radius:7px;font-size:13px;color:#0f172a}.file-item span{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.meta-row{display:flex;align-items:center;gap:8px;padding:3px 0;font-size:13px}.meta-label{color:#64748b;min-width:65px;font-weight:500}
@media(max-width:1440px){.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:640px){.metric-grid{grid-template-columns:1fr}}
</style>