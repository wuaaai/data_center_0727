# Phase 1 — 基础架构 (P0) 实施计划

> 对应 PRD: 01-产品升级方案_PRD.md | 预计工期: 3-5 天

---

## 任务清单

### 任务 1: 创建 knowledge_bases 表 + 数据迁移

**目标:** 新增知识库元数据表，为现有数据创建默认知识库。

**涉及文件:**
- `data_processing_center/ragdata_manager/config.py` — 新增 `KB_TABLE` 配置
- `data_processing_center/mineru_app/rag_ingest.py` — metadata 字段扩展
- 新增迁移脚本 `data_processing_center/scripts/migrate_v2_kb.py`

**具体步骤:**
1. 在 PostgreSQL 创建 `knowledge_bases` 表
2. 自动创建 "默认知识库"（id=`kb_default`，name=`默认知识库`）
3. 为现有所有切片的 `c_metadata` 添加 `knowledge_base_id='kb_default'` 和 `enabled=true`
4. 创建 `/ragdata/knowledge-bases` CRUD API

**验证:** 
- 调用 `GET /ragdata/knowledge-bases` 返回 `[{id: "kb_default", name: "默认知识库", ...}]`
- 现有知识库数据显示不变

---

### 任务 2: 知识库 CRUD API

**目标:** 完整的知识库创建/列表/详情/编辑/删除接口。

**涉及文件:**
- `data_processing_center/ragdata_manager/routes.py` — 新增路由
- `data_processing_center/app/src/api/dataManage.js` — 新增 API 调用

**API 列表:**
| 方法 | URL | 说明 |
|------|-----|------|
| POST | `/ragdata/knowledge-bases` | 创建知识库 |
| GET | `/ragdata/knowledge-bases` | 知识库列表（含文档数/切片数统计） |
| GET | `/ragdata/knowledge-bases/{kb_id}` | 知识库详情 |
| PUT | `/ragdata/knowledge-bases/{kb_id}` | 编辑知识库 |
| DELETE | `/ragdata/knowledge-bases/{kb_id}` | 删除知识库（确认后清理全部切片） |
| POST | `/ragdata/knowledge-bases/{kb_id}/toggle` | 启用/禁用切换 |

**验证:**
- 创建 → 列表中出现新知识库
- 编辑 → 名称和描述更新
- 删除 → 知识库消失，切片被清理
- 切换 → `is_active` 翻转

---

### 任务 3: 知识库选择器 (前端)

**目标:** 页面顶部增加知识库下拉切换器。

**涉及文件:**
- 新建 `data_processing_center/app/src/components/KnowledgeBaseSelector.vue`
- `data_processing_center/app/src/views/ragManage.vue` — 集成选择器

**交互设计:**
```
[📁 知识库: 预算管理 ▼]  [+ 新建] [⚙]
  ├── 预算管理 (128 文档 / 9,320 切片)  ← 当前选中
  ├── 社保资金 (56 文档 / 4,201 切片)
  ├── 教育经费 (32 文档 / 2,150 切片)
  └── 默认知识库 (15 文档 / 832 切片)
```

**行为:**
- 切换知识库 → 文档列表、统计卡片自动刷新
- 新建知识库 → 弹窗输入名称和描述
- 管理按钮 → 跳转到知识库管理页

**验证:**
- 切换知识库后，文档列表数据变化
- 新建知识库后，下拉列表增加选项

---

### 任务 4: 文档启用/禁用

**目标:** 文档级别开关，检索时自动过滤禁用文档。

**后端改动:**
- `data_processing_center/mineru_app/rag_ingest.py` — metadata 增加 `enabled: true`
- `data_processing_center/ragdata_manager/routes.py` — 新增 toggle API + 检索过滤逻辑

**新增 API:**
| 方法 | URL | 说明 |
|------|-----|------|
| POST | `/ragdata/knowledge/documents/{source}/toggle` | 单文档启用/禁用 |
| POST | `/ragdata/knowledge/documents/batch-toggle` | 批量启用/禁用 |

**实现方式:**
```sql
-- 切换启用状态
UPDATE parent_child_db_1024
SET c_metadata = jsonb_set(c_metadata, '{enabled}', '"false"')
WHERE c_metadata->>'source' = :source;

-- 检索时过滤
SELECT * FROM parent_child_db_1024
WHERE c_metadata->>'enabled' = 'true'   -- 🆕
  AND ...其他条件...
```

**前端改动:**
- `ragManage.vue` 表格操作列增加 el-switch 开关
- 筛选栏增加"已启用/已禁用"选项
- 开关切换 → 调用 toggle API → 实时刷新

**验证:**
- 禁用文档 → 检索测试台搜不到该文档的切片
- 重新启用 → 检索恢复

---

### 任务 5: 知识库启用/禁用

**目标:** 知识库级别开关。

**新增 API:**
| 方法 | URL | 说明 |
|------|-----|------|
| POST | `/ragdata/knowledge-bases/{kb_id}/toggle` | 切换启用/禁用 |

**实现方式:**
```sql
UPDATE knowledge_bases SET is_active = false WHERE id = :kb_id;
```

**检索过滤:**
- JOIN knowledge_bases 表，过滤 `is_active = false` 的知识库
- 或者在 metadata 中缓存 `kb_is_active`

**前端改动:**
- 知识库管理页表格增加状态列和开关
- 停用的知识库在知识库下拉中显示灰色（但仍可选择查看数据）

**验证:**
- 停用知识库 → 检索测试台搜不到该知识库的文档

---

### 任务 6: 文档元数据详情弹窗

**目标:** 点击文档名 → 弹出完整元数据面板。

**涉及文件:**
- 新建 `data_processing_center/app/src/components/DocumentMetaDialog.vue`
- `data_processing_center/ragdata_manager/routes.py` — `/ragdata/knowledge/documents/{source}/metadata`

**面板内容:**
```
┌─── 文档元数据 ──────────────────────────┐
│ 📄 预算编制办法.docx                     │
│ ──────────────────────────────────────── │
│ 基础信息                                 │
│   文件大小: 2.4 MB                       │
│   文件格式: .docx                        │
│   上传时间: 2026-07-25 14:30:00          │
│   入库时间: 2026-07-25 14:35:12          │
│ ──────────────────────────────────────── │
│ 处理信息                                 │
│   处理耗时: 45.2 秒                      │
│   切片数量: 128                          │
│   分块策略: default                      │
│   处理状态: completed                    │
│ ──────────────────────────────────────── │
│ 权限信息                                 │
│   所属知识库: 预算管理                     │
│   地区权限: 1301000 (石家庄市)            │
│   状态: ✓ 已启用                         │
│ ──────────────────────────────────────── │
│ 标签                                     │
│   [预算] [2026] [中央文件] [+ 添加标签]   │
│ ──────────────────────────────────────── │
│ 切片预览 (前5条)                          │
│   1. 第一章 总则... (256 字符)            │
│   2. 第二章 预算编制... (312 字符)         │
│   [查看全部 128 条切片]                   │
└──────────────────────────────────────────┘
```

**验证:**
- 点击文档名 → 弹窗正确显示所有元数据
- 标签可编辑保存

---

### 任务 7: 检索召回增加过滤

**目标:** 确保检索/召回接口自动过滤 `enabled=false` 和 `is_active=false` 的文档。

**改动点:**
- 所有查询 `parent_child_db_1024` 的 SQL 增加 `c_metadata->>'enabled' = 'true'` 条件
- 如果后续实现检索 API，JOIN knowledge_bases 过滤 `is_active`
- `knowledge/chunks` 等预览接口同步增加过滤

**验证:**
- 禁用文档后，调用 chunks 预览接口返回空或提示"已禁用"

---

## 完成标准

- [ ] 可以创建多个知识库并切换
- [ ] 每个文档有独立启用/禁用开关
- [ ] 每个知识库有启用/禁用开关
- [ ] 禁用文档/知识库后检索不会返回其切片
- [ ] 元数据弹窗可在 2 秒内打开并显示完整信息
- [ ] 现有功能不受影响（向后兼容）

---

## 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `ragdata_manager/routes.py` | 修改 | 新增 6 个知识库 API + toggle API + metadata API |
| `ragdata_manager/config.py` | 修改 | 新增 KB_TABLE 等配置 |
| `mineru_app/rag_ingest.py` | 修改 | metadata 增加 kb_id/enabled/tags 字段 |
| `app/src/views/ragManage.vue` | 修改 | 集成选择器/开关/筛选 |
| `app/src/api/dataManage.js` | 修改 | 新增知识库相关 API 调用 |
| `app/src/components/KnowledgeBaseSelector.vue` | 新建 | 知识库下拉选择器 |
| `app/src/components/DocumentMetaDialog.vue` | 新建 | 文档元数据详情弹窗 |
| `app/src/components/DocumentTagEditor.vue` | 新建 | 标签编辑器 |
| `scripts/migrate_v2_kb.py` | 新建 | 数据迁移脚本 |
