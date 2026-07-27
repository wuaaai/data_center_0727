# 开发任务清单 — P0 多知识库平台 v2

## Phase 0: 前置验证 (1天)

- [ ] **Task 0.1**: Embedding API 批量能力探测 (S)
- [ ] **Task 0.2**: pgvector COPY 兼容性验证 (S)
- [ ] **Task 0.3**: Maas 接口可达性验证 (S)

> **Checkpoint 0**: 外部依赖能力确认，决定后续降级方案

## Phase 1: 数据库基础 + 安全

- [ ] **Task 1**: knowledge_bases 表 + 迁移 + 回滚 + SQLite 缓存 (M)
- [ ] **Task 2**: 现有 API 扩展 kb_id + enabled 过滤 (M)

> **Checkpoint 1**: 迁移可回滚，API 向后兼容

## Phase 2: 知识库管理

- [ ] **Task 3**: 知识库 CRUD API (M)
- [ ] **Task 4**: 知识库选择器 (前端, 可搜索) (M)
- [ ] **Task 5**: 文档 + kb 启用/禁用 (M)
- [ ] **Task 6**: 文档元数据详情弹窗 (M)

> **Checkpoint 2**: 多知识库+开关可用

## Phase 3: 批量上传 + 安全

- [ ] **Task 7**: 统一 file_parse 路由 (独立线程池) (L)
- [ ] **Task 8**: 地区自动匹配引擎 (M)
- [ ] **Task 9**: 目录扫描 + 安全白名单 (M)
- [ ] **Task 10**: 批量进度面板 (L)

> **Checkpoint 3**: 批量上传+地区分配可用，安全合规

## Phase 4: 性能 + 降级

- [ ] **Task 11**: 批量 Embedding (+ 降级方案) (S)
- [ ] **Task 12**: COPY 批量写入 (+ 降级方案) (M)

> **Checkpoint 4**: 性能达标或降级可用
