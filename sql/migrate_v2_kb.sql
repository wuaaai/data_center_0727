/*
 * 多知识库管理 — 数据库迁移脚本
 * 版本: v2.0 | 日期: 2026-07-27
 *
 * 执行方式: psql -h 10.32.10.161 -U postgres -d text2sql_vector -f migrate_v2_kb.sql
 *
 * 包含:
 *   1. knowledge_bases 表 + 索引
 *   2. region_match_rules 表 + 完整12地市默认规则
 *   3. audit_log 表
 *   4. c_metadata JSONB 扩展 (kb_id / enabled / tags)
 *   5. c_metadata 索引
 *   6. 默认知识库
 */

BEGIN;

-- ═══════════════════════════════════════════════════════════════
-- 1. c_metadata 备份
-- ═══════════════════════════════════════════════════════════════
DROP TABLE IF EXISTS c_metadata_bak_v2;
CREATE TABLE c_metadata_bak_v2 AS
SELECT ctid, c_metadata FROM parent_child_db_1024;

-- ═══════════════════════════════════════════════════════════════
-- 2. knowledge_bases 表
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS knowledge_bases (
    id                 VARCHAR(64) PRIMARY KEY,
    name               VARCHAR(255) NOT NULL,
    description        TEXT DEFAULT '',
    directory_keywords TEXT DEFAULT '[]',     -- JSON数组: ["预算","国库"]
    is_active          BOOLEAN DEFAULT TRUE,
    owner_id           VARCHAR(128) DEFAULT '',
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_kb_is_active ON knowledge_bases(is_active);

-- ═══════════════════════════════════════════════════════════════
-- 3. region_match_rules 表 + 内置 12 地市规则
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS region_match_rules (
    id           SERIAL PRIMARY KEY,
    pattern      VARCHAR(255) NOT NULL,
    region_code  VARCHAR(9) NOT NULL,
    kb_id        VARCHAR(64) DEFAULT '',
    match_type   VARCHAR(32) DEFAULT 'keyword', -- keyword / short / code / pinyin
    priority     INT DEFAULT 0,
    is_active    BOOLEAN DEFAULT TRUE,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- 完整 12 地市 + 省本级（从 RDYS_BAS_MOFDIV 同步）
INSERT INTO region_match_rules (pattern, region_code, match_type, priority) VALUES
  -- 石家庄市
  ('1301000',       '1301000', 'code',    30),
  ('石家庄',        '1301000', 'keyword', 20),
  ('石市',          '1301000', 'short',   10),
  ('shijiazhuang',  '1301000', 'pinyin',  5),
  ('sjz',           '1301000', 'pinyin',  5),
  -- 唐山市
  ('1302000',       '1302000', 'code',    30),
  ('唐山',          '1302000', 'keyword', 20),
  ('tangshan',      '1302000', 'pinyin',  5),
  ('ts',            '1302000', 'pinyin',  5),
  -- 秦皇岛市
  ('1303000',       '1303000', 'code',    30),
  ('秦皇岛',        '1303000', 'keyword', 20),
  ('秦市',          '1303000', 'short',   10),
  ('qinhuangdao',   '1303000', 'pinyin',  5),
  ('qhd',           '1303000', 'pinyin',  5),
  -- 邯郸市
  ('1304000',       '1304000', 'code',    30),
  ('邯郸',          '1304000', 'keyword', 20),
  ('邯市',          '1304000', 'short',   10),
  ('handan',        '1304000', 'pinyin',  5),
  ('hd',            '1304000', 'pinyin',  5),
  -- 邢台市
  ('1305000',       '1305000', 'code',    30),
  ('邢台',          '1305000', 'keyword', 20),
  ('xingtai',       '1305000', 'pinyin',  5),
  ('xt',            '1305000', 'pinyin',  5),
  -- 保定市
  ('1306000',       '1306000', 'code',    30),
  ('保定',          '1306000', 'keyword', 20),
  ('baoding',       '1306000', 'pinyin',  5),
  ('bd',            '1306000', 'pinyin',  5),
  -- 张家口市
  ('1307000',       '1307000', 'code',    30),
  ('张家口',        '1307000', 'keyword', 20),
  ('张市',          '1307000', 'short',   10),
  ('zhangjiakou',   '1307000', 'pinyin',  5),
  ('zjk',           '1307000', 'pinyin',  5),
  -- 承德市
  ('1308000',       '1308000', 'code',    30),
  ('承德',          '1308000', 'keyword', 20),
  ('chengde',       '1308000', 'pinyin',  5),
  ('cd',            '1308000', 'pinyin',  5),
  -- 沧州市
  ('1309000',       '1309000', 'code',    30),
  ('沧州',          '1309000', 'keyword', 20),
  ('cangzhou',      '1309000', 'pinyin',  5),
  ('cz',            '1309000', 'pinyin',  5),
  -- 廊坊市
  ('1310000',       '1310000', 'code',    30),
  ('廊坊',          '1310000', 'keyword', 20),
  ('langfang',      '1310000', 'pinyin',  5),
  ('lf',            '1310000', 'pinyin',  5),
  -- 衡水市
  ('1311000',       '1311000', 'code',    30),
  ('衡水',          '1311000', 'keyword', 20),
  ('hengshui',      '1311000', 'pinyin',  5),
  ('hs',            '1311000', 'pinyin',  5),
  -- 雄安新区
  ('1331000',       '1331000', 'code',    30),
  ('雄安',          '1331000', 'keyword', 20),
  ('xiongan',       '1331000', 'pinyin',  5),
  ('xa',            '1331000', 'pinyin',  5),
  -- 河北省本级（最高优先级）
  ('130000000',     '130000000', 'code',   50),
  ('省本级',        '130000000', 'keyword', 40),
  ('省本',          '130000000', 'short',   35),
  ('省级',          '130000000', 'keyword', 35)
ON CONFLICT DO NOTHING;

-- ═══════════════════════════════════════════════════════════════
-- 4. audit_log 表
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS audit_log (
    id           SERIAL PRIMARY KEY,
    action       VARCHAR(64) NOT NULL,        -- toggle_doc / disable_kb / delete_doc
    target_type  VARCHAR(32) NOT NULL,        -- document / knowledge_base
    target_id    VARCHAR(128) NOT NULL,
    detail       TEXT DEFAULT '',
    operator     VARCHAR(128) DEFAULT '',
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_log(target_type, target_id);

-- ═══════════════════════════════════════════════════════════════
-- 5. c_metadata JSONB 扩展 — 分批更新 500 条/批
-- ═══════════════════════════════════════════════════════════════
DO $$
DECLARE
    batch_size INT := 500;
    total_rows INT;
    updated_rows INT := 0;
BEGIN
    SELECT COUNT(*) INTO total_rows FROM parent_child_db_1024
    WHERE c_metadata->>'kb_id' IS NULL;

    RAISE NOTICE '待迁移行数: %', total_rows;

    LOOP
        UPDATE parent_child_db_1024
        SET c_metadata = c_metadata || jsonb_build_object(
            'kb_id', 'default',
            'enabled', true,
            'tags', '[]'::jsonb
        )
        WHERE ctid IN (
            SELECT ctid FROM parent_child_db_1024
            WHERE c_metadata->>'kb_id' IS NULL
            LIMIT batch_size
        );

        GET DIAGNOSTICS updated_rows = ROW_COUNT;
        EXIT WHEN updated_rows = 0;

        COMMIT;
        RAISE NOTICE '已迁移 % 行 (目标: % 行)', updated_rows, total_rows;
    END LOOP;
END $$;

-- ═══════════════════════════════════════════════════════════════
-- 6. c_metadata 索引
-- ═══════════════════════════════════════════════════════════════
CREATE INDEX IF NOT EXISTS idx_c_metadata_kb_id
    ON parent_child_db_1024 ((c_metadata->>'kb_id'));
CREATE INDEX IF NOT EXISTS idx_c_metadata_enabled
    ON parent_child_db_1024 ((c_metadata->>'enabled'));
CREATE INDEX IF NOT EXISTS idx_c_metadata_source
    ON parent_child_db_1024 ((c_metadata->>'source'));

-- ═══════════════════════════════════════════════════════════════
-- 7. 插入默认知识库
-- ═══════════════════════════════════════════════════════════════
INSERT INTO knowledge_bases (id, name, description, directory_keywords)
VALUES ('default',
        '默认知识库',
        '系统迁移时自动创建，包含所有历史文档',
        '[]')
ON CONFLICT (id) DO NOTHING;

COMMIT;

-- ═══════════════════════════════════════════════════════════════
-- 验证
-- ═══════════════════════════════════════════════════════════════
SELECT 'knowledge_bases' AS table_name, COUNT(*) AS row_count FROM knowledge_bases
UNION ALL
SELECT 'region_match_rules', COUNT(*) FROM region_match_rules
UNION ALL
SELECT 'audit_log', COUNT(*) FROM audit_log
UNION ALL
SELECT 'c_metadata 迁移验证',
    COUNT(*) FROM parent_child_db_1024 WHERE c_metadata->>'kb_id' = 'default';
