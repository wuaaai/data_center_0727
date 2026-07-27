# 实施计划: 多知识库平台 P0 功能

## 概述

将 01 PRD 和 04-05 合并方案中的 P0 需求整合为可执行的开发任务。按依赖关系排序：数据库变更在最底层，然后是 API 基础路由，再到前端组件。每 2-3 个任务设置检查点。

## 架构决策

- knowledge_bases 表存在 PostgreSQL (10.32.10.161)，pgvector 表不变
- c_metadata JSONB 新增 enabled / kb_id / tags / quality_score 字段
- 新路由统一在 ragdata_manager/routes.py 中扩展，文件解析在 routes/file_parse.py
- 前端新组件放在 app/src/components/，主页面 ragManage.vue 集成新组件
- region_code 自动匹配规则内置于 region_matcher.py，支持扩展

## 依赖图

```
Phase 1: 数据库基础
  knowledge_bases 表 + 数据迁移 → 现有 API 扩展 kb_id 参数
      │
Phase 2: 知识库 CRUD + 启用禁用
  知识库 CRUD API → 知识库选择器(前端) → 文档/kb启用禁用 → 检索过滤
      │
Phase 3: 批量上传 + 区域分配
  统一 file_parse 路由 → 地区匹配引擎 → 目录扫描 → 批量进度面板
      │
Phase 4: 性能优化
  批量 Embedding → COPY 写入 → 动态并发
```

---

## Phase 1: 数据库基础

### Task 1: 创建 knowledge_bases 表 + 数据迁移

**Description:** 在 PostgreSQL 创建知识库元数据表，为现有所有切片的 c_metadata 写入默认值。

**Acceptance criteria:**
- [ ] `knowledge_bases` 表创建成功，含 id/name/description/is_active/created_at/updated_at
- [ ] 自动创建"默认知识库"（id=kb_default）
- [ ] 所有现有切片 c_metadata 添加 enabled=true 和 kb_id=kb_default
- [ ] 现有功能不受影响

**Verification:**
- [ ] SELECT count(*) FROM knowledge_bases 返回 1
- [ ] 知识库列表页面正常显示

**Dependencies:** None

**Files likely touched:**
- 新建 `scripts/migrate_v2_kb.py`
- `ragdata_manager/config.py` (新增 KB_TABLE 配置)

**Estimated scope:** Small (1-2 files)

---

### Task 2: owner/admin 两种角色

**Description:** knowledge_bases 表新增 owner_id 字段，记录创建者；新增 is_public 字段控制可见性。先不做完整认证，用请求头 X-User-ID 兜底。

**Acceptance criteria:**
- [ ] kb 创建时写入 owner_id，后续 admin 可以管理
- [ ] is_public=true 的知识库对所有人可见

**Verification:**
- [ ] 调用 POST /ragdata/knowledge-bases 创建后 owner_id 正确

**Dependencies:** Task 1

**Files likely touched:**
- `ragdata_manager/routes.py`

**Estimated scope:** Small

### Task 3: 现有 API 扩展 kb_id 参数

**Description:** 知识库概览/上传/入库/检索等现有接口增加 kb_id 参数支持。

**Acceptance criteria:**
- [ ] GET /ragdata/knowledge 支持 ?kb_id= 过滤
- [ ] POST /ragdata/upload 上传时写入 kb_id
- [ ] POST /ragdata/jobs/{id}/ingest 入库时 metadata 写入 kb_id
- [ ] 不传 kb_id 时默认使用 kb_default（向后兼容）

**Verification:**
- [ ] 上传文档时指定 kb_id → 入库后 metadata 中 kb_id 正确

**Dependencies:** Task 1, Task 2

**Files likely touched:**
- `ragdata_manager/routes.py`
- `mineru_app/rag_ingest.py`
- `ragdata_manager/config.py`

**Estimated scope:** Medium (3-5 files)

---

### Checkpoint: Phase 1
- [ ] knowledge_bases 表可查询
- [ ] 现有接口加 kb_id 参数后能正确过滤
- [ ] 没有 kb_id 时向后兼容

---

## Phase 2: 知识库管理 + 启用禁用

### Task 4: 知识库 CRUD API

**Description:** 完整的知识库创建/列表/详情/编辑/删除/启用禁用接口。

**Acceptance criteria:**
- [ ] POST /ragdata/knowledge-bases 创建知识库
- [ ] GET /ragdata/knowledge-bases 列知识库（含文档数/切片数统计）
- [ ] GET /ragdata/knowledge-bases/{kb_id} 详情（含 owner/is_public）
- [ ] PUT /ragdata/knowledge-bases/{kb_id} 编辑
- [ ] DELETE /ragdata/knowledge-bases/{kb_id} 删除（确认+清理告警）
- [ ] POST /ragdata/knowledge-bases/{kb_id}/toggle 启用/禁用

**Verification:**
- [ ] curl 测试每个接口返回正确
- [ ] 删除知识库后对应切片从向量表中移除

**Dependencies:** Task 3

**Files likely touched:**
- `ragdata_manager/routes.py`
- `app/src/api/dataManage.js`

**Estimated scope:** Medium (2 files, 6 endpoints)

---

### Task 5: 知识库选择器 (前端)

**Description:** 页面顶部增加知识库下拉切换器，新建知识库入口。

**Acceptance criteria:**
- [ ] 顶部下拉显示所有知识库（含文档数）
- [ ] 切换知识库后文档列表/统计自动刷新
- [ ] [+新建知识库] 按钮弹窗输入名称/描述
- [ ] 停用的知识库灰色显示

**Verification:**
- [ ] 切换知识库 → 文档列表变化
- [ ] 新建知识库 → 下拉列表新增选项

**Dependencies:** Task 4

**Files likely touched:**
- 新建 `app/src/components/KnowledgeBaseSelector.vue`
- `app/src/views/ragManage.vue`
- `app/src/api/dataManage.js`

**Estimated scope:** Medium (3 files)

---

### Task 6: 文档启用/禁用 + 知识库启用/禁用

**Description:** 文档级别和知识库级别的开关，检索时自动过滤禁用数据。

**Acceptance criteria:**
- [ ] POST /ragdata/knowledge/documents/{source}/toggle — 单文档开关
- [ ] POST /ragdata/knowledge/documents/batch-toggle — 批量开关
- [ ] 知识库级别 toggle 复用 Task 4 已有接口
- [ ] 检索召回 SQL 增加 enabled=true + kb.is_active=true 过滤
- [ ] 前端表格操作列增加 switch 开关

**Verification:**
- [ ] 禁用文档 → 检索测试台搜不到
- [ ] 重新启用 → 检索恢复
- [ ] 停用知识库 → 其所有文档不参与检索

**Dependencies:** Task 4, Task 5

**Files likely touched:**
- `ragdata_manager/routes.py` (2 个新 endpoint + WHERE 过滤)
- `app/src/views/ragManage.vue`

**Estimated scope:** Medium (2-3 files)

---

### Task 7: 文档元数据详情弹窗

**Description:** 点击文档名弹出元数据面板：基础信息/处理信息/权限信息/标签/切片预览。

**Acceptance criteria:**
- [ ] 弹窗显示：文件名/大小/格式/上传时间/入库时间/处理耗时/切片数/地区/知识库归属/启用状态
- [ ] 标签区域支持查看和编辑
- [ ] 切片预览前 5 条（可展开全部）

**Verification:**
- [ ] 点文档名 → 弹窗 2 秒内打开
- [ ] 标签可编辑保存

**Dependencies:** Task 6

**Files likely touched:**
- 新建 `app/src/components/DocumentMetaDialog.vue`
- `ragdata_manager/routes.py` (新增 metadata 查询接口)
- `app/src/views/ragManage.vue`

**Estimated scope:** Medium (3 files)

---

### Checkpoint: Phase 2
- [ ] 可以创建/切换/编辑知识库
- [ ] 文档可以启用/禁用
- [ ] 知识库可以启用/禁用
- [ ] 元数据弹窗正常工作

---

## Phase 3: 批量上传 + 地区分配

### Task 8: 统一 file_parse 路由

**Description:** 新建 routes/file_parse.py，兼容内网 Maas 接口，扩展 async 模式。

**Acceptance criteria:**
- [ ] POST /file_parse sync 模式返回 Markdown（与 Maas 兼容）
- [ ] POST /file_parse async 模式返回 task_id + batch_id
- [ ] GET /file_parse/{task_id} 查询异步任务状态
- [ ] POST /file_parse/batch 批量提交
- [ ] GET /file_parse/batch/{batch_id} 批量进度
- [ ] 支持 kb_id / default_region_code / tags / auto_allocate 参数

**Verification:**
- [ ] curl -F "files=@xxx.pdf" -F "format=markdown" 返回 markdown 文本
- [ ] 加 -F "mode=async" 返回 task_id

**Dependencies:** Task 3 (依赖 kb_id 参数支持)

**Files likely touched:**
- 新建 `routes/file_parse.py`
- `main.py` (注册新路由)
- `ragdata_manager/config.py`

**Estimated scope:** Large (5+ files)

---

### Task 9: 地区自动匹配引擎

**Description:** 内置 12 个地市的默认关键词规则，支持文件名自动匹配 region_code。

**Acceptance criteria:**
- [ ] 中文全称/简称/拼音/区划编码 四种匹配方式
- [ ] 内置默认规则覆盖 11 地市 + 省本级
- [ ] POST /file_parse/preview-allocation 预览匹配结果
- [ ] auto_allocate=true 参数控制是否启用

**Verification:**
- [ ] 文件名含"石家庄市预算报告.pdf" → 匹配到 region_code=1301000
- [ ] 文件名含"sjz_2026.pdf" → 匹配到石家庄市
- [ ] 文件名"unknown.pdf" → 未匹配，返回 manual_required

**Dependencies:** Task 8

**Files likely touched:**
- 新建 `ragdata_manager/region_matcher.py`
- `routes/file_parse.py`

**Estimated scope:** Medium (2 files)

---

### Task 10: 目录扫描 + 自动映射

**Description:** 扫描服务器本地目录，按子目录名自动映射地区/知识库。

**Acceptance criteria:**
- [ ] POST /file_parse/scan-directory 递归扫描返回文件列表
- [ ] 子目录名含地市名/区划编码 → 自动映射为 region_code
- [ ] POST /file_parse/import-directory 确认导入
- [ ] 支持自定义 dir_name → kb_id 映射规则

**Verification:**
- [ ] 目录 D:\待处理\石家庄市\ → 扫描出 31 个文件，自动分配 1301000

**Dependencies:** Task 8, Task 9

**Files likely touched:**
- `routes/file_parse.py`
- `ragdata_manager/region_matcher.py`

**Estimated scope:** Medium (2 files)

---

### Task 11: 批量进度面板 (前端)

**Description:** 批量导入专用进度面板：三阶段进度条 + SSE 实时推送 + 失败清单。

**Acceptance criteria:**
- [ ] 面板显示：总文件数/已完成/失败/速度/预估剩余时间
- [ ] 三阶段进度条（提交→解析→入库）
- [ ] SSE 实时推送进度更新
- [ ] 失败文件清单 + 一键重试

**Verification:**
- [ ] 批量上传 10 个文件 → 进度条实时更新
- [ ] 人为制造失败 → 显示在失败清单中

**Dependencies:** Task 8

**Files likely touched:**
- 新建 `app/src/components/BatchImportPanel.vue`
- 新建 `app/src/components/BatchProgressBar.vue`
- `app/src/views/ragManage.vue`
- `routes/file_parse.py` (SSE endpoint)

**Estimated scope:** Large (4 files)

---

### Checkpoint: Phase 3
- [ ] 可以用 /file_parse 上传文件（sync + async）
- [ ] 文件名含地市名自动分配 region_code
- [ ] 目录扫描工作正常
- [ ] 批量进度面板实时更新

---

## Phase 4: 性能优化

### Task 12: 批量 Embedding

**Description:** rag_ingest.py 将逐条 Embedding 改为批量发送。

**Acceptance criteria:**
- [ ] BATCH_SIZE=32，每批发送到 Embedding API
- [ ] 错误时自动降级为逐条发送
- [ ] 埋点记录批量耗时

**Verification:**
- [ ] 200 个切片的文档入库时间从 ~200s 降到 ~10s

**Dependencies:** None

**Files likely touched:**
- `mineru_app/rag_ingest.py`

**Estimated scope:** Small (1 file)

---

### Task 13: COPY 批量写入 + 动态并发

**Description:** PostgreSQL INSERT 改为 COPY，入库锁改为知识库级别，MinerU worker 动态调整。

**Acceptance criteria:**
- [ ] 切片写入从逐行 INSERT 改为 StringIO + COPY
- [ ] 入库锁从全局互斥改为 per-kb 锁
- [ ] model_manager 根据队列积压动态调整 worker 数 (2-6)

**Verification:**
- [ ] 1000 切片写入时间从 ~5s 降到 < 0.5s
- [ ] 两个不同知识库可以同时入库

**Dependencies:** Task 12

**Files likely touched:**
- `mineru_app/rag_ingest.py`
- `ragdata_manager/routes.py`
- `mineru_app/model_manager.py`

**Estimated scope:** Medium (3 files)

---

### Checkpoint: Phase 4
- [ ] 入库速度提升 50x+
- [ ] 两个知识库可以并行入库
- [ ] worker 数动态调整

---

## 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| c_metadata 大批量 UPDATE 死锁 | 中 | 分批 UPDATE，每批 500 条 |
| 批量 Embedding API 返回顺序不确定 | 低 | 按 index 排序后再与 text 匹配 |
| 前端拖拽组件在旧浏览器上不兼容 | 低 | P1 优先级，先做文件选择方式 |

## 开放问题

- 是否需要为 kb 创建/编辑做权限校验（用户登录）？当前用 X-User-ID 头
- 批量入库的 COPY 模式是否需要回退方案（旧版 psycopg2）？

