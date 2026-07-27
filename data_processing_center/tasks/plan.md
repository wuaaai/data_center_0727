# 实施计划: 多知识库平台 P0 功能 (v2)

## 概述

将 01 PRD 和 04-05 合并方案中的 P0 需求整合。v2 基于 code review 发现的 10 个问题重新设计，每个风险有对应的防护任务。

## 核心原则

1. **防瘫痪** — 任何外部依赖（DB/API）不可用时，核心功能降级但不崩溃
2. **防越权** — 目录扫描/文件访问有白名单限制
3. **可回滚** — 数据迁移有备份+回滚脚本
4. **先验证再开发** — Embedding API / pgvector COPY 能力先探路

---

## Phase 0: 前置验证（1 天）

> 先确认外部依赖能力，避免开发到一半发现 API 不支持

### Task 0.1: Embedding API 能力探测

**Description:** 向 120.211.116.133:65325/embed 发送批量请求，确认是否支持数组输入。
- 如果支持批量 → Task 12 按设计执行
- 如果不支持 → Task 12 取消，保留逐条模式但用线程池并发发送

**Acceptance:**
- [ ] 调用 POST /embed body=json([text1, text2, text3]) 验证返回数组长度是否为 3

### Task 0.2: pgvector COPY 兼容性验证

**Description:** 写入 100 条测试切片到临时表验证 COPY 协议，确认后删除临时表。

**Acceptance:**
- [ ] COPY 写入 100 条耗时 < 1s, 数据完整
- [ ] 如果不支持 → Task 13 降级为批量 INSERT

### Task 0.3: Maas 接口可达性验证

**Description:** curl 内网接口，确认网络连通性 + 返回 JSON 结构。

**Acceptance:**
- [ ] HTTPS 可达, 返回 JSON code=200

---

## Phase 1: 数据库基础 + 安全防护

### Task 1: 创建 knowledge_bases 表 + 迁移 + 回滚

- 迁移前备份 c_metadata → 临时表 c_metadata_bak
- 分批 UPDATE (500条/批)，事务包裹
- 失败自动 ROLLBACK + 从备份恢复
- 迁移日志输出到文件
- **新增:** 本地 SQLite 缓存 kb 列表 (kb_cache.db)，PostgreSQL 不可用时降级读取

**Dependencies:** Phase 0 全通过

### Task 2: 现有 API 扩展 kb_id + enabled 过滤

- GET /ragdata/knowledge 支持 ?kb_id= + ?enabled=
- POST /ragdata/upload 支持 kb_id 参数
- ingress 时 metadata 写入 kb_id / enabled / tags
- 不传 kb_id → 默认 kb_default

**Dependencies:** Task 1

### Checkpoint 1
- [ ] 迁移成功且可回滚
- [ ] kb_id 参数有效，默认值兼容旧请求

---

## Phase 2: 知识库管理 + 安全防护

### Task 3: 知识库 CRUD API

- POST/GET/PUT/DELETE /ragdata/knowledge-bases
- kb 创建时写入 owner_id (读取 X-User-ID header)
- 删除 kb → 检查是否有文档 → 警告 → 二次确认 → 清理所有切片

### Task 4: 知识库选择器 (前端)

- el-select 可搜索模式，支持拼音首字母匹配
- 停用的知识库灰色显示
- 切换 kb → 文档列表/统计刷新

### Task 5: 文档 + kb 启用/禁用

- 文档 toggle: 更新 c_metadata.enabled
- kb toggle: 更新 knowledge_bases.is_active
- 检索 SQL 增加 WHERE enabled=true AND kb.is_active=true
- 禁用操作记录审计日志

### Task 6: 文档元数据详情弹窗

- 显示：文件信息/处理信息/权限信息/标签/启用状态/切片预览
- 标签支持编辑 + 保存

### Checkpoint 2
- [ ] 多知识库可用，开关生效，元数据可见

---

## Phase 3: 批量上传 + 安全防护

### Task 7: 统一 file_parse 路由

- POST /file_parse sync: **独立线程池 (max_workers=4)**, 单文件 5 分钟硬限制
- POST /file_parse async: 复用当前异步架构
- 复用当前 parser 内部逻辑 (端口 8003 + MinerU pipeline)
- 参数: kb_id / default_region_code / tags / auto_allocate

### Task 8: 地区自动匹配引擎

- 内置 12 地市规则 (中文全称/简称/拼音/区划编码)
- POST /file_parse/preview-allocation 预览匹配
- auto_allocate=true 自动应用

### Task 9: 目录扫描 + 安全白名单

- **安全: 只在环境变量 ALLOWED_SCAN_PATHS 里的路径允许扫描**
- 默认白名单: data_processing_center/data/
- 拒绝 ../ 和绝对路径绕过
- 递归扫描 → 返回目录树 + 文件列表
- 子目录名 → 自动映射地区/知识库

### Task 10: 批量进度面板 (前端)

- SSE 实时推送批量进度
- 三阶段进度条
- 失败清单 + 重试

### Checkpoint 3
- [ ] 批量上传可用，安全合规 (白名单限制，无路径遍历风险)

---

## Phase 4: 性能优化 + 降级方案

### Task 11: 批量 Embedding (+ 降级)

- 如果 Phase 0 验证支持批量: BATCH_SIZE=32
- 如果不支持: 线程池 4 并发逐条 (不做虚假"批量")
- 单次失败重试 3 次

### Task 12: COPY 批量写入 (+ 降级)

- 如果 Phase 0 验证支持 COPY: StringIO + copy_from
- 如果不支持: executemany 批量 INSERT (executemany 比逐条快 5-10x)
- 入库锁: per-kb (每个 kb 独立锁, 两个不同 kb 可并行入库)

### Checkpoint 4
- [ ] 入库速度提升 (COPY 50x, executemany 10x)
- [ ] 降级方案可用

---

## 依赖图 (更新后)

```
Phase 0: 前置验证
  Embedding 能力 → COPY 能力 → Maas 可达性
      │
Phase 1: 数据库基础 + 安全
  Task 1 (迁移+回滚+SQLite缓存) → Task 2 (API扩展)
      │
Phase 2: 知识库管理
  Task 3 (CRUD) → Task 4 (选择器) → Task 5 (开关) → Task 6 (元数据)
      │
Phase 3: 批量上传 + 安全
  Task 7 (file_parse) → Task 8 (地区匹配) → Task 9 (目录扫描+白名单) → Task 10 (进度面板)
      │
Phase 4: 性能 + 降级
  Task 11 (Embedding) → Task 12 (COPY)
```

---

## 风险表 (完整版)

| 风险 | 影响 | 缓解 | Phase |
|------|------|------|-------|
| PostgreSQL 断连 | 高 — 知识库功能不可用 | SQLite 本地缓存降级 + 定时同步 | P1 |
| 数据迁移失败 | 高 — 数据不一致 | 备份表 + ROLLBACK + 回滚脚本 | P1 |
| 目录扫描路径遍历 | 高 — 安全漏洞 | ALLOWED_SCAN_PATHS 白名单 + 路径校验 | P3 |
| sync 模式阻塞线程池 | 中 — API 超时 | 独立线程池 + 5分钟硬限制 | P3 |
| Embedding 批量不支持 | 中 — 性能不达预期 | Phase 0 先验证, 降级方案 = 线程池并发 | P0 |
| COPY 不支持 | 中 — 性能不达预期 | Phase 0 先验证, 降级方案 = executemany | P0 |
| c_metadata UPDATE 死锁 | 中 | 分批 500 条 | P1 |
| 批量 Embedding 顺序错乱 | 低 | 按 index 排序后再匹配 | P4 |
| Maas 接口不可达 | 低 | 默认用本地引擎, Maas 仅当备选 | P0 |
| Worker 动态调整资源不足 | 低 | 上限 6, 安全范围 | P4 |
