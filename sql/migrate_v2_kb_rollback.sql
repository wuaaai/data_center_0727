/*
 * 多知识库管理 — 数据库回滚脚本
 * 版本: v2.0 | 日期: 2026-07-27
 *
 * 执行方式: psql -h 10.32.10.161 -U postgres -d text2sql_vector -f migrate_v2_kb_rollback.sql
 *
 * 回滚内容:
 *   1. 从 c_metadata_bak_v2 恢复 c_metadata
 *   2. 删除新增的 jsonb key (kb_id / enabled / tags)
 *   3. 删除 knowledge_bases, region_match_rules, audit_log 表
 *   4. 删除相关索引
 */

BEGIN;

-- ═══════════════════════════════════════════════════════════════
-- 1. 从备份恢复 c_metadata
-- ═══════════════════════════════════════════════════════════════
UPDATE parent_child_db_1024 t
SET c_metadata = b.c_metadata
FROM c_metadata_bak_v2 b
WHERE t.ctid = b.ctid;

-- 如果有新增行（备份之后入库的），直接去掉新增的 key
UPDATE parent_child_db_1024
SET c_metadata = c_metadata - 'kb_id' - 'enabled' - 'tags'
WHERE c_metadata ? 'kb_id';

-- ═══════════════════════════════════════════════════════════════
-- 2. 删除索引
-- ═══════════════════════════════════════════════════════════════
DROP INDEX IF EXISTS idx_c_metadata_kb_id;
DROP INDEX IF EXISTS idx_c_metadata_enabled;
DROP INDEX IF EXISTS idx_c_metadata_source;
DROP INDEX IF EXISTS idx_kb_is_active;
DROP INDEX IF EXISTS idx_audit_target;

-- ═══════════════════════════════════════════════════════════════
-- 3. 删除表
-- ═══════════════════════════════════════════════════════════════
DROP TABLE IF EXISTS audit_log;
DROP TABLE IF EXISTS region_match_rules;
DROP TABLE IF EXISTS knowledge_bases;

-- ═══════════════════════════════════════════════════════════════
-- 4. 删除备份表
-- ═══════════════════════════════════════════════════════════════
DROP TABLE IF EXISTS c_metadata_bak_v2;

COMMIT;

SELECT '回滚完成' AS status;
