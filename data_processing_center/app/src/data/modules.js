export const moduleMenus = [
  {
    key: 'datasource',
    name: '数据源配置管理',
    shortName: '接入与连接',
    icon: 'Connection',
    subtitle: '统一维护财政业务库的数据源接入配置、连接状态与表结构同步入口。'
  },
  {
    key: 'metadata',
    name: '表元数据管理',
    shortName: '目录与标签',
    icon: 'CollectionTag',
    subtitle: '集中维护库、Schema、表、字段、业务口径与主题标签等核心元数据资产。'
  },
  {
    key: 'vectorization',
    name: '知识库数据管理',
    shortName: '向量与索引',
    icon: 'Cpu',
    subtitle: '面向 RAG 场景维护文档切片、Embedding 建设、索引状态与召回准备数据。'
  },
  {
    key: 'sync',
    name: '数据同步中心',
    shortName: '任务与流水',
    icon: 'Refresh',
    subtitle: '统一调度元数据同步、增量刷新、全量校验和跨库同步执行记录。'
  },
  {
    key: 'scheduling',
    name: '定时维护任务',
    shortName: '调度与巡检',
    icon: 'Timer',
    subtitle: '集中管理夜间任务、巡检计划、异常重试与自动化维护窗口。'
  }
]
// 数据处理中心列表数据  目前只支持达梦数据库
export const datasourceDemoRows = [
  {
    id: 1,
    name: '财政预算库',
    dbType: 'DM',
    host: 'localhost',
    port: 5236,
    databaseName: 'RDYS_PUBLIC_TBS_DM',
    status: 'connected',
    syncTime: '2026-07-08 10:30:00',
    isDefault: true
  }
]

export const statusTypeMap = {
  正常: 'success',
  已发布: 'success',
  已连接: 'success',
  运行中: 'primary',
  同步中: 'warning',
  待补充: 'warning',
  待审核: 'warning',
  告警: 'danger',
  失败: 'danger',
  重试中: 'info'
}

export const moduleOverviewMap = {
  metadata: {
    accent: '#6d5dfc',
    heroLabel: 'Metadata Catalog',
    statCards: [
      { label: '数据表总数', value: '24', delta: '较昨日 +36', tone: 'primary' },
      { label: '', value: '93.6%', delta: '较上周 +1.8%', tone: 'success' },
      { label: '业务标签条目', value: '1,276', delta: '本周新增 84', tone: 'warning' },
      { label: '待补充字段', value: '57', delta: '需人工梳理', tone: 'info' }
    ],
    tableTitle: '最近元数据治理动态',
    tableDescription: '展示表结构发布、字段补录和业务标签整理等最近处理事项。',
    rows: [
      { name: '预算指标表', scope: '预算域 / Table', owner: '目录中心', status: '已发布', time: '2026-07-08 09:14' },
      { name: '支付明细表', scope: '执行域 / Table', owner: '目录中心', status: '正常', time: '2026-07-08 08:55' },
      { name: '项目绩效字段注释', scope: '项目域 / Column', owner: '数据治理组', status: '待补充', time: '2026-07-08 08:11' },
      { name: '资产台账索引信息', scope: '资产域 / Index', owner: '目录中心', status: '正常', time: '2026-07-08 07:49' }
    ]
  },
  vectorization: {
    accent: '#4f7cff',
    heroLabel: 'RAG Knowledge Base',
    heroTitle: '知识片段、向量索引与语料质量维护',
    heroDescription:
      '统一管理制度文件、报表说明、政策材料和业务手册的切片、Embedding 与检索索引状态。',
    sideLabel: '索引可用率',
    sideValue: '99.1%',
    sideNote: '当前主知识库检索链路运行平稳，可支撑财政问答场景。',
    statCards: [
      { label: '文档资产总数', value: '4,286', delta: '本周新增 125', tone: 'primary' },
      { label: '向量切片数量', value: '96,320', delta: '昨夜重建 8,420', tone: 'success' },
      { label: '召回规则模板', value: '42', delta: '覆盖 9 类场景', tone: 'warning' },
      { label: '待复核文档', value: '16', delta: '需清洗标签', tone: 'info' }
    ],
    tableTitle: '最近知识库处理记录',
    tableDescription: '展示文档入库、切片更新、Embedding 构建和索引刷新等处理结果。',
    rows: [
      { name: '预算执行制度汇编', scope: '政策文档 / PDF', owner: '知识库维护组', status: '正常', time: '2026-07-08 10:18' },
      { name: '财政指标解释手册', scope: '业务手册 / DOCX', owner: '知识库维护组', status: '同步中', time: '2026-07-08 09:52' },
      { name: '预算公开问答集', scope: 'FAQ / Markdown', owner: '智能问答组', status: '已发布', time: '2026-07-08 09:27' },
      { name: '项目绩效评价规则', scope: '规则库 / TXT', owner: '智能问答组', status: '待审核', time: '2026-07-08 08:46' }
    ]
  },
  sync: {
    accent: '#22c55e',
    heroLabel: 'Sync Pipeline',
    heroTitle: '跨库同步、增量刷新与任务流水管理',
    heroDescription:
      '面向元数据、主题表和指标模型维护统一同步链路，支持手动触发、自动计划与失败追踪。',
    sideLabel: '任务成功率',
    sideValue: '98.4%',
    sideNote: '过去 24 小时共执行 126 次同步任务，异常已进入重试队列。',
    statCards: [
      { label: '今日同步任务', value: '126', delta: '成功 124 次', tone: 'primary' },
      { label: '增量刷新批次', value: '38', delta: '高峰期 11:00', tone: 'success' },
      { label: '待处理异常', value: '3', delta: '已自动告警', tone: 'warning' },
      { label: '全量校验任务', value: '8', delta: '昨夜已完成 6', tone: 'info' }
    ],
    tableTitle: '最近同步任务执行情况',
    tableDescription: '用于观察元数据同步、增量刷新、结构校验与跨库传输任务状态。',
    rows: [
      { name: '预算域元数据同步', scope: 'Oracle / 28 张表', owner: '调度器', status: '运行中', time: '2026-07-08 09:32' },
      { name: '执行域增量刷新', scope: 'Yashan / 12 张表', owner: '调度器', status: '正常', time: '2026-07-08 09:06' },
      { name: '分析库全量校验', scope: 'DM / 3 个 Schema', owner: '数据中台', status: '正常', time: '2026-07-08 08:20' },
      { name: '项目库注释回收', scope: 'PostgreSQL / 46 字段', owner: '调度器', status: '失败', time: '2026-07-08 07:58' }
    ]
  },
  scheduling: {
    accent: '#f59e0b',
    heroLabel: 'Scheduler Console',
    heroTitle: '夜间维护、巡检窗口与自动重试调度',
    heroDescription:
      '统一管理 Schema 巡检、知识库重建、元数据刷新、压测窗口与失败任务补偿策略。',
    sideLabel: '调度引擎状态',
    sideValue: '稳定运行',
    sideNote: '当前调度器心跳正常，所有计划任务均按 Asia/Shanghai 时区执行。',
    statCards: [
      { label: '启用中的计划任务', value: '27', delta: '本周新增 2 个', tone: 'primary' },
      { label: '夜间巡检覆盖率', value: '100%', delta: '全部主题域已纳入', tone: 'success' },
      { label: '重试队列数量', value: '5', delta: '已完成 3 次回补', tone: 'warning' },
      { label: '维护窗口配置', value: '9', delta: '含节假日策略', tone: 'info' }
    ],
    tableTitle: '最近调度与巡检记录',
    tableDescription: '帮助运维与治理团队查看定时任务执行、巡检结果和异常回补状态。',
    rows: [
      { name: '凌晨元数据刷新', scope: '全域任务', owner: 'Scheduler', status: '正常', time: '2026-07-08 03:00' },
      { name: '预算域质量复核', scope: '预算域', owner: 'Scheduler', status: '正常', time: '2026-07-08 05:30' },
      { name: '字段变更扫描', scope: '执行域', owner: 'Scheduler', status: '运行中', time: '2026-07-08 09:22' },
      { name: '向量失效重建', scope: '项目域', owner: 'Scheduler', status: '重试中', time: '2026-07-08 07:41' }
    ]
  }
}
