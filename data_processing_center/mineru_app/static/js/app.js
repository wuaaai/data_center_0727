/**
 * 上传页面交互逻辑 — 支持多文件上传、替换、直接入库、统计筛选、嵌入模式。
 */

document.addEventListener('DOMContentLoaded', () => {
    setupUpload();
    setupStatsFilter();
    setupDirectUpload();
    setupReplaceDialog();
});


// ============================================================
// 上传功能
// ============================================================

function setupUpload() {
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const selectBtn = document.getElementById('select-btn');
    const uploadForm = document.getElementById('upload-form');
    const selectedFiles = document.getElementById('selected-files');
    const fileList = document.getElementById('file-list');
    const fileCount = document.getElementById('file-count');
    const clearAllBtn = document.getElementById('clear-all-btn');
    const uploadBtn = document.getElementById('upload-btn');
    const uploadStatus = document.getElementById('upload-status');

    if (!dropZone || !fileInput) return;

    let pendingFiles = [];

    function renderFileList() {
        fileList.innerHTML = '';
        pendingFiles.forEach((file, idx) => {
            const li = document.createElement('li');
            li.className = 'file-item';
            li.innerHTML = `
                <span class="file-item-name">${file.name} <em>(${formatSize(file.size)})</em></span>
                <button type="button" class="file-remove-btn" data-idx="${idx}" title="移除">✕</button>
            `;
            fileList.appendChild(li);
        });
        fileList.querySelectorAll('.file-remove-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.idx);
                pendingFiles.splice(idx, 1);
                if (pendingFiles.length === 0) {
                    selectedFiles.style.display = 'none';
                } else {
                    renderFileList();
                }
                fileCount.textContent = pendingFiles.length;
            });
        });
        fileCount.textContent = pendingFiles.length;
        selectedFiles.style.display = pendingFiles.length > 0 ? 'block' : 'none';
    }

    function addFiles(newFiles) {
        const validExts = ['.pdf', '.docx', '.doc'];
        for (const f of newFiles) {
            const ext = '.' + f.name.split('.').pop().toLowerCase();
            if (!validExts.includes(ext)) {
                alert('不支持的文件格式: ' + f.name + ' (' + ext + ')，仅支持 PDF/DOCX/DOC');
                continue;
            }
            if (f.size > 200 * 1024 * 1024) {
                alert('文件过大: ' + f.name + ' (' + formatSize(f.size) + ')，最大 200MB');
                continue;
            }
            if (!pendingFiles.some(p => p.name === f.name && p.size === f.size)) {
                pendingFiles.push(f);
            }
        }
        if (pendingFiles.length > 0) {
            renderFileList();
        }
    }

    const folderInput = document.getElementById('folder-input');
    const folderBtn = document.getElementById('folder-btn');

    if (selectBtn) selectBtn.addEventListener('click', () => fileInput.click());
    if (folderBtn) folderBtn.addEventListener('click', () => folderInput.click());
    dropZone.addEventListener('click', (e) => {
        if (e.target === selectBtn || e.target === folderBtn || e.target.closest('button')) return;
        fileInput.click();
    });

    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('drag-over');
    });
    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('drag-over');
    });
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('drag-over');
        if (e.dataTransfer.files.length > 0) {
            addFiles(e.dataTransfer.files);
        }
        fileInput.value = '';
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) addFiles(fileInput.files);
        fileInput.value = '';
    });

    if (folderInput) {
        folderInput.addEventListener('change', () => {
            if (folderInput.files.length > 0) addFiles(folderInput.files);
            folderInput.value = '';
        });
    }

    if (clearAllBtn) clearAllBtn.addEventListener('click', () => {
        pendingFiles = [];
        selectedFiles.style.display = 'none';
        fileCount.textContent = '0';
        uploadStatus.style.display = 'none';
    });

    uploadForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (pendingFiles.length === 0) return;

        uploadBtn.disabled = true;
        uploadBtn.textContent = '处理中...';
        uploadStatus.style.display = 'block';

        let successCount = 0;
        let failCount = 0;
        const jobIds = [];

        for (let i = 0; i < pendingFiles.length; i++) {
            const file = pendingFiles[i];
            uploadStatus.innerHTML = '<span class="spinner"></span> 上传中 (' + (i + 1) + '/' + pendingFiles.length + '): ' + file.name + '...';

            try {
                const formData = new FormData();
                formData.append('files', file);
                const resp = await fetch('/api/upload', { method: 'POST', body: formData });
                const data = await resp.json();
                if (resp.ok && data.jobs && data.jobs.length > 0) {
                    successCount++;
                    jobIds.push(data.jobs[0].job_id);
                } else {
                    failCount++;
                }
            } catch (err) {
                failCount++;
            }
        }

        pendingFiles = [];
        selectedFiles.style.display = 'none';

        let msg = '✅ 上传完成: ' + successCount + ' 个成功';
        if (failCount > 0) msg += ', ' + failCount + ' 个失败';
        uploadStatus.innerHTML = msg;

        uploadBtn.disabled = false;
        uploadBtn.textContent = '开始处理全部';

        if (jobIds.length === 1) {
            window.location.href = '/jobs/' + jobIds[0];
        } else if (jobIds.length > 1) {
            uploadStatus.innerHTML += ' | <a href="/jobs">查看所有任务 →</a>';
            setTimeout(() => window.location.reload(), 3000);
        }
    });
}


// ============================================================
// 直接上传（跳过处理）
// ============================================================

function setupDirectUpload() {
    const input = document.getElementById('direct-upload-input');
    const btn = document.getElementById('direct-upload-btn');
    const status = document.getElementById('direct-upload-status');
    if (!input || !btn) return;

    btn.addEventListener('click', () => input.click());

    input.addEventListener('change', async () => {
        if (!input.files.length) return;
        const file = input.files[0];
        btn.disabled = true;
        btn.textContent = '上传中...';
        if (status) status.textContent = '正在处理...';

        const formData = new FormData();
        formData.append('file', file);
        try {
            const resp = await fetch('/api/direct-upload', { method: 'POST', body: formData });
            const data = await resp.json();
            if (resp.ok) {
                if (status) {
                    status.style.color = '#188038';
                    status.textContent = '✅ 已就绪！跳转到详情页...';
                }
                setTimeout(() => {
                    window.location.href = '/jobs/' + data.job_id;
                }, 800);
            } else {
                if (status) {
                    status.style.color = '#d93025';
                    status.textContent = '❌ ' + (data.error || '上传失败');
                }
                btn.disabled = false;
                btn.textContent = '直接上传（跳过处理）';
            }
        } catch (err) {
            if (status) {
                status.style.color = '#d93025';
                status.textContent = '❌ 网络错误: ' + err.message;
            }
            btn.disabled = false;
            btn.textContent = '直接上传（跳过处理）';
        }
        input.value = '';
    });
}


// ============================================================
// 替换修改版 DOCX
// ============================================================

let _replaceCallbackJobId = null;

function setupReplaceDialog() {
    const input = document.getElementById('replace-file-input');
    if (!input) return;

    input.addEventListener('change', () => {
        if (!input.files.length || !_replaceCallbackJobId) return;
        const file = input.files[0];
        replaceOutput(_replaceCallbackJobId, file);
        input.value = '';
        _replaceCallbackJobId = null;
    });
}

/**
 * 从卡片按钮触发：先记住 jobId，再触发隐藏的 file input。
 */
function showReplaceDialog(jobId) {
    _replaceCallbackJobId = jobId;
    const input = document.getElementById('replace-file-input');
    if (input) input.click();
}

/**
 * 实际上传替换文件。
 */
async function replaceOutput(jobId, file) {
    const card = document.getElementById('job-' + jobId);
    const progressEl = card ? card.querySelector('.job-progress') : null;
    if (progressEl) progressEl.textContent = '替换中...';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const resp = await fetch('/api/jobs/' + jobId + '/replace', { method: 'POST', body: formData });
        const data = await resp.json();
        if (resp.ok && data.status === 'ok') {
            if (progressEl) progressEl.textContent = '已替换修改版';
            window.location.reload();
        } else {
            alert('替换失败: ' + (data.error || data.detail || '未知错误'));
            if (progressEl) progressEl.textContent = '替换失败';
        }
    } catch (err) {
        alert('网络错误: ' + err.message);
        if (progressEl) progressEl.textContent = '替换失败';
    }
}


// ============================================================
// 统计栏可点击筛选
// ============================================================

function setupStatsFilter() {
    const statsBar = document.getElementById('stats-bar');
    if (!statsBar) return;

    // 高亮当前筛选状态
    const currentStatus = getUrlParam('status') || '';
    statsBar.querySelectorAll('.stat-item').forEach(item => {
        if (item.dataset.status === currentStatus) {
            item.classList.add('active');
        }
    });

    // 点击统计项跳转到筛选页面（页面导航方式，保留 embed 参数）
    // 链接已在 HTML 中通过 href 设置
}


// ============================================================
// 工具函数
// ============================================================

function getUrlParam(name) {
    const params = new URLSearchParams(window.location.search);
    return params.get(name) || '';
}

function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}


// ============================================================
// 单文件 / 批量操作
// ============================================================

function deleteJob(jobId) {
    if (!confirm('确认删除此任务及关联文件？')) return;
    fetch('/api/jobs/' + jobId, { method: 'DELETE' })
        .then(r => r.json())
        .then(() => window.location.href = '/jobs?_=' + Date.now())
        .catch(err => alert('删除失败: ' + (err.message || '未知错误')));
}


async function unloadFromKB(jobId, btn) {
    if (!confirm('确认从向量库中删除此文件的所有内容？\n此操作不可恢复，但可重新入库。')) return;
    btn.disabled = true;
    btn.textContent = '移除中...';
    try {
        const resp = await fetch('/api/jobs/' + jobId + '/unload', { method: 'POST' });
        const data = await resp.json();
        if (resp.ok && data.status === 'ok') {
            btn.textContent = '已移除';
            const card = document.getElementById('job-' + jobId);
            if (card) {
                const badge = card.querySelector('.job-status');
                if (badge) { badge.className = 'job-status status-completed'; badge.textContent = 'completed'; }
                const cb = card.querySelector('.job-checkbox');
                if (cb) cb.dataset.status = 'completed';
                const progress = card.querySelector('.job-progress');
                if (progress) progress.textContent = '已从知识库移除';
                const actions = card.querySelector('.job-actions');
                if (actions) actions.innerHTML = renderJobActions({ id: jobId, status: 'completed', filename: '' });
            }
            loadStats();
            loadKnowledge();
        } else {
            alert('移除失败: ' + (data.error || '未知错误'));
            btn.disabled = false;
            btn.textContent = '移除(重试)';
        }
    } catch (err) {
        alert('请求失败: ' + err.message);
        btn.disabled = false;
        btn.textContent = '移除(重试)';
    }
}


async function singleIngest(jobId, btn) {
    const card = document.getElementById('job-' + jobId);
    const filename = card ? card.querySelector('.job-filename')?.textContent : '';
    let warn = '';
    if (filename) {
        try {
            const r = await fetch('/api/knowledge/check?filename=' + encodeURIComponent(filename));
            const d = await r.json();
            if (d.exists) {
                warn = '\n⚠ 该文件已在知识库中（' + d.chunks + ' 个切片），入库后将覆盖旧数据。';
            }
        } catch {}
    }
    if (!confirm('确认将此文档存入 RAG 知识库？' + warn)) return;
    btn.disabled = true;
    btn.textContent = '入库中...';
    try {
        const resp = await fetch('/api/jobs/' + jobId + '/ingest', { method: 'POST' });
        const data = await resp.json();
        if (resp.ok && data.status === 'ingested') {
            btn.textContent = '已入库';
            const card = document.getElementById('job-' + jobId);
            if (card) {
                const statusEl = card.querySelector('.job-status');
                if (statusEl) { statusEl.className = 'job-status status-ingested'; statusEl.textContent = 'ingested'; }
                const checkbox = card.querySelector('.job-checkbox');
                if (checkbox) checkbox.dataset.status = 'ingested';
                const progressEl = card.querySelector('.job-progress');
                if (progressEl) progressEl.textContent = '入库完成';
            }
            loadStats();
            loadKnowledge();
        } else {
            alert('入库失败: ' + (data.error || data.detail || '未知错误'));
            btn.disabled = false;
            btn.textContent = '入库(重试)';
            if (card) {
                const statusEl = card.querySelector('.job-status');
                if (statusEl) { statusEl.className = 'job-status status-completed'; statusEl.textContent = 'completed'; }
                const progressEl = card.querySelector('.job-progress');
                if (progressEl) progressEl.textContent = '入库失败';
            }
        }
    } catch (err) {
        alert('请求失败: ' + err.message);
        btn.disabled = false;
        btn.textContent = '入库(重试)';
    }
}


// ============================================================
// 统计 & 知识库
// ============================================================

function loadStats() {
    fetch('/api/stats')
        .then(r => r.json())
        .then(data => {
            const statsBar = document.getElementById('stats-bar');
            if (!statsBar) return;
            statsBar.style.display = 'flex';

            const c = data.counts || {};
            document.getElementById('stat-total').textContent = data.total || 0;
            document.getElementById('stat-queued').textContent = c.queued || 0;
            document.getElementById('stat-processing').textContent = c.processing || 0;
            document.getElementById('stat-completed').textContent = c.completed || 0;
            document.getElementById('stat-failed').textContent = c.failed || 0;
            document.getElementById('stat-ingested').textContent = c.ingested || 0;

            if ((c.completed || 0) > 0 || (c.ingested || 0) > 0) {
                const batchBar = document.getElementById('batch-actions');
                if (batchBar) batchBar.style.display = 'flex';
            }
        });
}


function toggleSelectAll(el) {
    const validStatuses = ['completed', 'ingested'];
    document.querySelectorAll('.job-checkbox').forEach(b => {
        b.checked = el.checked && validStatuses.includes(b.dataset.status);
    });
    updateBatchCount();
}


function updateBatchCount() {
    const checked = document.querySelectorAll('.job-checkbox:checked');
    const count = checked.length;
    document.getElementById('batch-count').textContent = count;
    document.getElementById('batch-ingest-btn').disabled = count === 0;
    document.getElementById('batch-delete-btn').disabled = count === 0;
}


async function batchIngest() {
    const checked = document.querySelectorAll('.job-checkbox:checked');
    const jobIds = Array.from(checked).map(cb => cb.dataset.jobId).filter(id => {
        const cb = document.querySelector('.job-checkbox[data-job-id="' + id + '"]');
        return cb && (cb.dataset.status === 'completed' || cb.dataset.status === 'ingested');
    });
    if (jobIds.length === 0) { alert('没有可入库的已完成任务'); return; }

    if (!confirm('确认批量入库 ' + jobIds.length + ' 个文档？将逐个追加写入（不删库），同文件覆盖更新。')) return;

    const btn = document.getElementById('batch-ingest-btn');
    const statusEl = document.getElementById('batch-status');
    btn.disabled = true;
    btn.textContent = '入库中...';

    try {
        const resp = await fetch('/api/ingest/batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_ids: jobIds }),
        });
        const data = await resp.json();
        const ok = data.ok || 0;
        const failed = (data.results || []).filter(r => r.status !== 'ok').length;
        statusEl.textContent = '完成: ' + ok + ' 成功, ' + failed + ' 失败';
        statusEl.style.color = failed > 0 ? '#d93025' : '#188038';
    } catch (err) {
        statusEl.textContent = '请求失败';
        statusEl.style.color = '#d93025';
    }
    btn.disabled = false;
    btn.textContent = '批量入库';
    setTimeout(() => window.location.reload(), 2000);
}


function batchDownload() {
    const checked = document.querySelectorAll('.job-checkbox:checked');
    if (checked.length === 0) return;
    const jobIds = Array.from(checked).map(cb => cb.dataset.jobId);

    fetch('/api/jobs/batch-download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_ids: jobIds }),
    })
    .then(r => {
        if (!r.ok) return r.json().then(d => { throw new Error(d.error || '下载失败'); });
        return r.blob();
    })
    .then(blob => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'documents.zip';
        a.click();
        URL.revokeObjectURL(url);
    })
    .catch(err => alert('下载失败: ' + (err.message || '未知错误')));
}


async function batchDelete() {
    const checked = document.querySelectorAll('.job-checkbox:checked');
    if (checked.length === 0) return;
    if (!confirm('确认删除 ' + checked.length + ' 个任务及关联文件？此操作不可恢复。')) return;

    const statusEl = document.getElementById('batch-status');
    const btn = document.getElementById('batch-delete-btn');
    btn.disabled = true;
    statusEl.textContent = '删除中...';

    let ok = 0, fail = 0;
    for (const cb of checked) {
        try {
            const resp = await fetch('/api/jobs/' + cb.dataset.jobId, { method: 'DELETE' });
            if (resp.ok) ok++; else fail++;
        } catch { fail++; }
    }
    statusEl.textContent = '删除: ' + ok + ' 成功, ' + fail + ' 失败';
    statusEl.style.color = fail > 0 ? '#d93025' : '#188038';
    btn.disabled = false;
    setTimeout(() => window.location.reload(), 1500);
}


function loadKnowledge() {
    const el = document.getElementById('knowledge-content');
    if (!el) return;
    el.innerHTML = '<p class="empty">加载中...</p>';
    fetch('/api/knowledge')
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                el.innerHTML = '<p class="empty" style="color:#e74c3c">加载失败: ' + data.error + '</p>';
                return;
            }
            const files = data.files || [];
            if (files.length === 0) {
                el.innerHTML = '<p class="empty">知识库为空，暂无入库文档</p>';
                return;
            }
            let html = '<div class="stats-bar" style="display:flex;margin-bottom:12px">' +
                '<span class="stat-item">文档数 <strong>' + data.total_files + '</strong></span>' +
                '<span class="stat-item">总切片 <strong>' + data.total_chunks + '</strong></span>' +
                '</div>';
            html += '<div style="max-height:300px;overflow-y:auto">';
            html += '<table style="width:100%;border-collapse:collapse;font-size:0.85rem">';
            html += '<tr style="border-bottom:2px solid #eee"><th style="text-align:left;padding:6px">文件名</th><th style="text-align:right;padding:6px">切片数</th></tr>';
            for (const f of files) {
                html += '<tr style="border-bottom:1px solid #f0f0f0">' +
                    '<td style="padding:6px">' + f.filename + '</td>' +
                    '<td style="text-align:right;padding:6px;color:#888">' + f.chunks + '</td>' +
                    '</tr>';
            }
            html += '</table></div>';
            el.innerHTML = html;
        })
        .catch(err => {
            el.innerHTML = '<p class="empty" style="color:#e74c3c">加载失败: ' + err.message + '</p>';
        });
}


// ============================================================
// 卡片轮询更新
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
    if (document.querySelectorAll('.job-checkbox').length > 0) {
        document.getElementById('batch-actions').style.display = 'flex';
    }
    loadStats();
    loadKnowledge();
    setInterval(loadStats, 5000);
    setInterval(updateBatchCount, 2000);
    refreshJobCards();
    setInterval(refreshJobCards, 3000);
});


function refreshJobCards() {
    const cards = document.querySelectorAll('.job-card');
    if (cards.length === 0) return;

    const ids = Array.from(cards).map(c => c.id.replace('job-', ''));
    fetch('/api/jobs/list-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_ids: ids }),
    })
    .then(r => r.json())
    .then(data => {
        const jobs = data.jobs || [];
        for (const job of jobs) {
            const card = document.getElementById('job-' + job.id);
            if (!card) continue;

            const badge = card.querySelector('.job-status');
            if (badge && badge.textContent.trim() !== job.status) {
                badge.className = 'job-status status-' + job.status;
                badge.textContent = job.status;
            }

            const progress = card.querySelector('.job-progress');
            if (progress && progress.textContent.trim() !== (job.progress || '')) {
                progress.textContent = job.progress || '';
            }

            const actions = card.querySelector('.job-actions');
            if (actions) {
                const newActions = renderJobActions(job);
                if (newActions !== actions.innerHTML) {
                    actions.innerHTML = newActions;
                }
            }

            const cb = card.querySelector('.job-checkbox');
            if (cb && cb.dataset.status !== job.status) {
                cb.dataset.status = job.status;
            }
        }

        loadStats();
        if (document.querySelectorAll('.job-checkbox').length > 0) {
            document.getElementById('batch-actions').style.display = 'flex';
        }
    })
    .catch(() => {});
}


/**
 * 根据 job 状态渲染操作按钮 HTML。
 */
function renderJobActions(job) {
    let html = '';
    // 替换按钮：completed 和 ingested 都显示
    if (job.status === 'completed' || job.status === 'ingested') {
        html += '<button class="btn btn-sm btn-warning" onclick="showReplaceDialog(\'' + job.id + '\')" title="上传修改版 DOCX">替换</button>';
    }
    if (job.status === 'completed') {
        const ingestLabel = job.ingest_error ? '入库(重试)' : '入库';
        html += '<button class="btn btn-sm btn-success" onclick="singleIngest(\'' + job.id + '\', this)">' + ingestLabel + '</button>';
        html += '<a href="/api/jobs/' + job.id + '/download" class="btn btn-sm">下载</a>';
        html += '<a href="/jobs/' + job.id + '" class="btn btn-sm">预览</a>';
    } else if (job.status === 'ingesting') {
        if (job.ingest_error) {
            html += '<button class="btn btn-sm btn-success" onclick="singleIngest(\'' + job.id + '\', this)">入库(重试)</button>';
        } else {
            html += '<span class="ingesting-indicator">入库中...</span>';
        }
    } else if (job.status === 'ingested') {
        html += '<span class="ingested-indicator">已入库</span>';
        html += '<button class="btn btn-sm btn-warning" onclick="unloadFromKB(\'' + job.id + '\', this)">移除</button>';
        html += '<a href="/api/jobs/' + job.id + '/download" class="btn btn-sm">下载</a>';
        html += '<a href="/jobs/' + job.id + '" class="btn btn-sm">预览</a>';
    } else if (job.status === 'failed') {
        html += '<a href="/jobs/' + job.id + '" class="btn btn-sm">查看错误</a>';
    } else {
        html += '<a href="/jobs/' + job.id + '" class="btn btn-sm">查看进度</a>';
    }
    html += '<button class="btn btn-sm btn-danger" onclick="deleteJob(\'' + job.id + '\')">删除</button>';
    return html;
}
