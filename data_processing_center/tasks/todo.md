# 开发任务清单 — P0 多知识库平台

## Phase 1: 数据库基础

- [ ] **Task 1**: 创建 knowledge_bases 表 + 数据迁移 (S)
  - files: `scripts/migrate_v2_kb.py`, `ragdata_manager/config.py`
- [ ] **Task 2**: 知识库 owner/admin 角色 (S)
  - files: `ragdata_manager/routes.py`
- [ ] **Task 3**: 现有 API 扩展 kb_id 参数 (M)
  - files: `ragdata_manager/routes.py`, `mineru_app/rag_ingest.py`, `ragdata_manager/config.py`

> **Checkpoint 1**: knowledge_bases 表可查，kb_id 参数有效

## Phase 2: 知识库管理 + 启用禁用

- [ ] **Task 4**: 知识库 CRUD API (M)
  - files: `ragdata_manager/routes.py`, `app/src/api/dataManage.js`
- [ ] **Task 5**: 知识库选择器 (前端) (M)
  - files: `KnowledgeBaseSelector.vue`, `ragManage.vue`, `dataManage.js`
- [ ] **Task 6**: 文档启用/禁用 + kb启用/禁用 (M)
  - files: `ragdata_manager/routes.py`, `ragManage.vue`
- [ ] **Task 7**: 文档元数据详情弹窗 (M)
  - files: `DocumentMetaDialog.vue`, `ragdata_manager/routes.py`, `ragManage.vue`

> **Checkpoint 2**: 多知识库可用，文档可以开关

## Phase 3: 批量上传 + 地区分配

- [ ] **Task 8**: 统一 file_parse 路由 (L)
  - files: `routes/file_parse.py`, `main.py`, `ragdata_manager/config.py`
- [ ] **Task 9**: 地区自动匹配引擎 (M)
  - files: `ragdata_manager/region_matcher.py`, `routes/file_parse.py`
- [ ] **Task 10**: 目录扫描 + 自动映射 (M)
  - files: `routes/file_parse.py`, `ragdata_manager/region_matcher.py`
- [ ] **Task 11**: 批量进度面板 (前端) (L)
  - files: `BatchImportPanel.vue`, `BatchProgressBar.vue`, `ragManage.vue`, `routes/file_parse.py`

> **Checkpoint 3**: 批量上传+地区自动分配可用，进度可见

## Phase 4: 性能优化

- [ ] **Task 12**: 批量 Embedding (S)
  - files: `mineru_app/rag_ingest.py`
- [ ] **Task 13**: COPY 批量写入 + 动态并发 (M)
  - files: `mineru_app/rag_ingest.py`, `ragdata_manager/routes.py`, `mineru_app/model_manager.py`

> **Checkpoint 4**: 入库速度 50x+，性能达标
