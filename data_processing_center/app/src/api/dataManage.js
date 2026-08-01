import { get, post, del, put } from './request'

// ── 数据源管理 ──
export function getAllTables(params = {}) {
  return get('/dataManage/tables', params)
}

// ── 元数据管理 ──
export function getMetadataTables(params = {}) {
  return get('/metadataManage/tables', params)
}

export function addMetadataTable(payload = {}) {
  return post('/metadataManage/tables', payload)
}

export function cancelMetadataTable(payload = {}) {
  return post('/metadataManage/tables/cancel', payload)
}

const BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001'

// ── 知识库管理 ──
export function getKnowledgeBase(params = {}) {
  return get('/ragdata/knowledge', { sort: params.sort || 'time', ...(params.kb_id ? { kb_id: params.kb_id } : {}), ...(params.enabled ? { enabled: params.enabled } : {}) })
}

export function checkKnowledgeFilename(filename) {
  return get('/ragdata/knowledge/check', { filename })
}

export function getRagJobs(params = {}) {
  return get('/ragdata/jobs', params)
}

export function getRagJob(jobId) {
  return get(`/ragdata/jobs/${jobId}`)
}

export function getRagStats() {
  return get('/ragdata/stats')
}

export function downloadRagJob(jobId) {
  window.open(`${BASE}/ragdata/jobs/${jobId}/download`, '_blank')
}

export function deleteRagJob(jobId) {
  return del(`/ragdata/jobs/${jobId}`)
}

export function ingestRagJob(jobId, body = null) {
  return post(`/ragdata/jobs/${jobId}/ingest`, body || {})
}

export function unloadRagJob(jobId, body = {}) {
  return post(`/ragdata/jobs/${jobId}/unload`, body)
}

export function uploadRagFile(formData) {
  return fetch(`${BASE}/ragdata/upload`, {
    method: 'POST',
    body: formData
  }).then(r => r.json())
}

export function batchQueryJobStatus(jobIds) {
  return fetch(`${BASE}/ragdata/jobs/list-batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_ids: jobIds })
  }).then(r => r.json())
}

// 区划
export function getRegions() {
  return get('/ragdata/regions')
}

// ── 知识库 CRUD ──
export function getKnowledgeBases(params = {}) {
  return get('/ragdata/knowledge-bases', params)
}

export function createKnowledgeBase(body = {}) {
  return post('/ragdata/knowledge-bases', body)
}

export function getKnowledgeBaseDetail(kbId) {
  return get(`/ragdata/knowledge-bases/${kbId}`)
}

export function updateKnowledgeBase(kbId, body = {}) {
  return put(`/ragdata/knowledge-bases/${kbId}`, body)
}

export function deleteKnowledgeBase(kbId, params = {}) {
  return del(`/ragdata/knowledge-bases/${kbId}`, params)
}

export function getKnowledgeBaseStats() {
  return get('/ragdata/knowledge-bases/stats')
}

// ── 文档启用/禁用 ──
export function toggleDocEnabled(source, enabled) {
  return put(`/ragdata/knowledge/${source}/toggle`, { enabled })
}

export function toggleDocEnabledBatch(sources, enabled) {
  return put('/ragdata/knowledge/toggle-batch', { sources, enabled })
}

// ── 文档元数据 ──
export function getDocMetadata(source) {
  return get(`/ragdata/knowledge/${source}/metadata`)
}

export function updateDocMetadata(source, body = {}) {
  return put(`/ragdata/knowledge/${source}/metadata`, body)
}

// ── 匹配规则 ──
export function getRegionMatchRules(params = {}) {
  return get('/ragdata/region-match-rules', params)
}

export function createRegionMatchRule(body = {}) {
  return post('/ragdata/region-match-rules', body)
}

export function deleteRegionMatchRule(ruleId) {
  return del(`/ragdata/region-match-rules/${ruleId}`)
}
