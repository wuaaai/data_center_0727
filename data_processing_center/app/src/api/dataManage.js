import { get, post, del } from './request'

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
export function getKnowledgeBase(sort) {
  return get('/ragdata/knowledge', { sort: sort || 'time' })
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

export function ingestRagJob(jobId) {
  return post(`/ragdata/jobs/${jobId}/ingest`)
}

export function unloadRagJob(jobId) {
  return post(`/ragdata/jobs/${jobId}/unload`)
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
