"""合成脱敏演示数据（幂等）。

大白话：这是"全量功能 Demo"的样例填充脚本——两条机构树、十几个合成账号、角色、
文号、自查任务、问题整改、提案、知识发布、审计链、插件与场景包。
全部为**合成脱敏演示数据**，姓名均标注"（演示）"；重复执行不重复插入
（固定主键 + demo_state.seeded_version 双保险）。

检查项编号一律引用现有系统真实 checkCode（kb_source.fetch_checks），
失败时回退内置样本，保证不硬编码不存在的编号。
"""
from __future__ import annotations

import json
import re
import datetime

from . import store

SEED_VERSION = "demo-v1.9"

# ===========================================================================
# 可引用的知识库清单（演示目录）
# ===========================================================================
# 大白话：设置页要能"看到全部可引用的知识库并勾选"。知识库平台（WeKnora）
# 在本地容器/离线演示环境里通常不可达，此时若只回当前生效的那一个库，
# 清单就只剩一行、无从选择。这里给出完整演示目录作为降级数据源；
# 首条与 WEKNORA_KB_ID 默认值一致，保证"当前生效库"始终在清单内。
DEMO_KB_CATALOG = [
    ("59ad56fe-6673-49af-9380-b7d11f194a0d", "数据安全统一知识库", 1284),
    ("3f2a91c4-7d18-4e05-9b63-2c40a1e7f5b8", "金融监管法规库（人行 · 金融监管总局）", 316),
    ("7c5e04b2-9a37-41d8-8f2e-6b93c7d0a451", "银行数据安全制度库", 208),
    ("b18d6a07-53c9-42f1-a7d5-9e8041c2b6f3", "保险数据安全制度库", 164),
    ("f92c37d5-1b48-4a6e-93c7-58d0b2e9a741", "监管检查项与处罚案例库", 137),
    ("d47f2b19-8e6a-4c37-b0f5-12a95de3c8a7", "数据分类分级模板库", 92),
]

# ===========================================================================
# 现状诊断 · 五个维度 × 三问（方法论参考内容，静态只读）
# ---------------------------------------------------------------------------
# 口径：一份自查报告承载一次完整的现状诊断，覆盖组织、制度、流程、规范工具，
#      以及机构当前应对数据安全监管检查与检查规范的现状；每层都过同一组三问
#      「有没有 / 有没有执行 / 有没有证据」，三问逐层收紧。
# 全代号化、无机构真名、无绝对路径、无条目数承诺。
# ===========================================================================
DIAG_QUESTIONS = ["有没有", "有没有执行", "有没有证据"]

DIAG_DIMENSIONS = [
    {
        "no": 1, "name": "组织",
        "answers": [
            {"q": "有没有", "text": "是否明确牵头部门与岗位职责", "state": "yes"},
            {"q": "有没有执行", "text": "分工是否实际运转", "state": "partial"},
            {"q": "有没有证据", "text": "议事、决策、派单记录", "state": "no"},
        ],
        "note": "牵头部门已设，条线分工在总部运转；到分支机构一层，同一场景「谁发起、"
                "谁审批、谁复核、谁问责」的说明口径不一致。",
        "next": "先统一责任矩阵，把发起、审批、复核、问责落到场景与岗位。",
    },
    {
        "no": 2, "name": "制度",
        "answers": [
            {"q": "有没有", "text": "是否成文、是否覆盖到处理环节", "state": "yes"},
            {"q": "有没有执行", "text": "是否被执行而非仅发布", "state": "partial"},
            {"q": "有没有证据", "text": "执行记录与复核留痕", "state": "no"},
        ],
        "note": "制度文本齐备、覆盖主要处理环节；执行留痕偏薄，部分条线以发布代替执行。",
        "next": "为已发布制度补执行记录与复核留痕，先补高风险处理环节。",
    },
    {
        "no": 3, "name": "流程",
        "answers": [
            {"q": "有没有", "text": "是否定义谁发起、谁审批、谁复核、谁问责", "state": "partial"},
            {"q": "有没有执行", "text": "流程是否跑起来", "state": "partial"},
            {"q": "有没有证据", "text": "各环节留痕与审批记录", "state": "no"},
        ],
        "note": "核心系统内的处理环节已定义并跑通；报表、导出、接口缓存等非结构化环节"
                "尚未纳入同一套流程，各环节留痕未统一。",
        "next": "把非结构化数据所在环节纳入同一套流程定义，并统一留痕口径。",
    },
    {
        "no": 4, "name": "规范工具",
        "answers": [
            {"q": "有没有", "text": "权限、脱敏、导出审批、日志是否配置", "state": "yes"},
            {"q": "有没有执行", "text": "控制是否真实生效", "state": "no"},
            {"q": "有没有证据", "text": "可核验的配置与运行记录", "state": "no"},
        ],
        "note": "控制项已配置，但没有跟着数据实际流动的链路走：存在仅在页面展示层脱敏、"
                "后台接口仍返回明文，应用日志记录敏感字段的情况。",
        "next": "按使用场景逐项对账，先做展示层与后台接口返回内容比对。",
    },
    {
        "no": 5, "name": "应对监管检查与检查规范的现状",
        "answers": [
            {"q": "有没有", "text": "是否有统一的组织与口径", "state": "partial"},
            {"q": "有没有执行", "text": "配合监管检查是否按规范运转", "state": "partial"},
            {"q": "有没有证据", "text": "台账、复测、验收审批与根因分析记录", "state": "no"},
        ],
        "note": "配合检查已有统一组织，口径尚需统一；历次发现未全部形成台账，"
                "整改时限、复测验收、验收审批与根因分析记录不完整。",
        "next": "先建问题台账与整改时限，再补复测验收与根因分析记录。",
    },
]

# ===========================================================================
# 应用与业务层台账（分类分级对账，静态只读）
# ---------------------------------------------------------------------------
# 口径：沿用已有分类分级成果、接口优先复用，补的是应用与业务这一层——
#      把后台接口、导出、角色权限、报表与应用日志，同分级结果、权限、脱敏、
#      导出审批逐项对账，从「管库表」走向「管使用场景」。
# 对账结论：aligned 已对上 / partial 部分对上 / missing 未对上。
# 全代号化：系统以甲、乙、丙……指代。
# ===========================================================================
LEDGER_ROWS = [
    {"scene": "系统甲 · 报表导出", "level": "敏感",
     "should": "导出审批 + 字段最小化 + 到期回收与删除验证",
     "actual": "已有审批入口；字段范围与到期回收未逐项登记", "result": "partial"},
    {"scene": "系统乙 · 后台接口返回", "level": "敏感",
     "should": "服务端脱敏，与展示层同一口径",
     "actual": "展示层已脱敏；后台接口返回明文", "result": "missing"},
    {"scene": "系统丙 · 角色权限调用", "level": "重要",
     "should": "岗位最小授权 + 职责分离",
     "actual": "已按岗位授权；存在共享账号使用痕迹", "result": "partial"},
    {"scene": "系统丁 · 应用日志", "level": "敏感",
     "should": "日志敏感字段过滤",
     "actual": "日志记录敏感字段原文", "result": "missing"},
    {"scene": "系统戊 · 报表订阅分发", "level": "内部",
     "should": "分发范围审批 + 数字水印与溯源",
     "actual": "已加水印；分发范围未登记", "result": "partial"},
    {"scene": "系统己 · 测试数据使用", "level": "敏感",
     "should": "测试数据脱敏 + 脱敏有效性验证",
     "actual": "已脱敏；缺脱敏有效性验证记录", "result": "partial"},
    {"scene": "系统庚 · 外发邮件附件", "level": "内部",
     "should": "外发审批 + 敏感内容识别",
     "actual": "尚未接入外发管控", "result": "missing"},
    {"scene": "系统辛 · 数据共享接口", "level": "重要",
     "should": "共享审批 + 接口台账纳管",
     "actual": "接口尚未纳入台账", "result": "missing"},
]

# ===========================================================================
# 逐类问题处置 · 九类 × 失效层 × 管理策略 × 技术防护策略 × 证据与验收
# ---------------------------------------------------------------------------
# 口径：每一类已识别的问题同时落到管理策略与技术防护策略上；管理策略固定按
#      「制度／培训／流程规范／审计检查」四项展开，技术防护策略给出工具能力类别，
#      两组统一收口到「证据与验收」。失效层四层：治理层 / 资产层 / 执行层 / 机制层。
# 全代号化、无厂商与产品名称、无条目数承诺。
# ===========================================================================
ISSUE_CLASSES = [
    {
        "no": "①", "name": "数据安全责任体系未有效穿透", "layer": "治理层",
        "mgmt": {
            "制度": "修订责任制，统一责任文件与制度口径",
            "培训": "对业务条线、分支机构开展责任分工宣贯",
            "流程规范": "建立覆盖各层级的责任矩阵，落到场景、岗位、审批节点",
            "审计检查": "定期核查文件一致性、抽查条线可说明性",
        },
        "tech": ["统一身份目录与岗位主数据", "职责分离配置", "审批工作流与电子留痕", "责任矩阵台账"],
        "evidence": ["统一后的责任文件", "责任矩阵", "岗位授权清单", "审批链流转日志", "一致性核查与抽查记录"],
        "accept": "每个高风险处理场景可指名到岗",
    },
    {
        "no": "②", "name": "数据分类分级和数据目录覆盖不完整", "layer": "资产层",
        "mgmt": {
            "制度": "分类分级办法与目录维护规范",
            "培训": "数据归属方分级标准与打标培训",
            "流程规范": "目录动态维护，新增系统、移动渠道与外部接口纳管流程",
            "审计检查": "核查非结构化数据覆盖、抽查分级结果是否被控制策略引用",
        },
        "tech": ["数据资产发现与目录", "非结构化数据识别", "元数据管理", "自动分类分级打标",
                 "分级结果与权限／脱敏／加密／日志／接口／共享审批联动", "目录动态维护"],
        "evidence": ["资产目录清单（含非结构化数据、移动应用、外部接口）", "打标结果",
                     "目录变更记录", "联动配置与逐项核对记录"],
        "accept": "目录覆盖到高风险场景，且联动可逐项对账",
    },
    {
        "no": "③", "name": "生产数据提取和报表导出闭环不足", "layer": "执行层",
        "mgmt": {
            "制度": "数据提取与导出管理办法，明确审批权限、用途期限、留存与销毁要求",
            "培训": "导出岗位合规培训",
            "流程规范": "统一入口、事前审批、最小字段、最短期限、到期回收、删除验证",
            "审计检查": "专项核查审批、用途期限、到期删除与销毁验证记录",
        },
        "tech": ["统一导出入口管控", "导出审批工作流", "字段级最小化与期限控制", "下载加密",
                 "数字水印与溯源", "到期回收与安全销毁", "销毁验证"],
        "evidence": ["导出审批单", "字段范围与期限配置", "下载加密与水印记录",
                     "到期回收与删除验证记录", "完整证据链"],
        "accept": "每一笔导出可追溯至审批、用途期限与删除结果",
    },
    {
        "no": "④", "name": "敏感数据全链路保护措施不足", "layer": "执行层",
        "mgmt": {
            "制度": "覆盖采集、传输、存储、使用、测试、展示、日志的全链路保护基线",
            "培训": "研发、测试、运维的脱敏与日志规范",
            "流程规范": "上线前脱敏与日志过滤验收、测试用生产数据审批与脱敏有效性验证",
            "审计检查": "接口明文、应用日志敏感字段、测试环境、办公终端专项排查",
        },
        "tech": ["服务端与接口脱敏", "静态脱敏", "动态脱敏", "传输加密", "敏感字段与存储加密",
                 "日志敏感字段过滤", "测试数据脱敏与有效性验证", "明文检测"],
        "evidence": ["全链路保护基线", "脱敏策略生效核查记录", "展示层与后台接口返回内容比对",
                     "日志敏感字段扫描报告", "测试环境脱敏证明与有效性验证报告"],
        "accept": "后台接口与展示层同口径，测试环境无可用生产明文",
    },
    {
        "no": "⑤", "name": "邮件、云盘和终端数据防泄漏控制有效性不足", "layer": "执行层",
        "mgmt": {
            "制度": "办公渠道与移动介质统一管控制度、明文凭据禁令",
            "培训": "全员防泄漏与凭据管理",
            "流程规范": "外发审批、告警处置—复核—重复问题治理",
            "审计检查": "数据防泄漏及文件加密策略对抗性验证、明文凭据清理核查",
        },
        "tech": ["数据防泄漏（邮件／云盘／终端／网络）", "文件与透明加密", "敏感内容识别",
                 "明文凭据检测与清理", "外发管控与拦截", "告警处置与复核"],
        "evidence": ["防泄漏与文件加密策略配置", "对抗性验证记录", "明文凭据清理记录",
                     "告警处置与复核记录", "重复问题治理台账"],
        "accept": "策略经验证有效，无明文凭据与高权限凭据留存",
    },
    {
        "no": "⑥", "name": "高权限账号和运维访问管理粗放", "layer": "执行层",
        "mgmt": {
            "制度": "账号与特权访问管理办法",
            "培训": "运维及外包账号使用规范",
            "流程规范": "实名专用、最小授权、职责分离、临时提权与到期回收、项目结束账号注销、禁止共享账号与直连",
            "审计检查": "定期清理僵尸账号、核查绕过运维审计通道直连、高权限操作审计",
        },
        "tech": ["统一身份认证", "特权账号管理", "最小授权与职责分离", "临时提权与到期回收",
                 "僵尸与共享账号检测", "运维安全审计", "高权限操作审计与录屏"],
        "evidence": ["实名账号台账", "授权与职责分离配置", "提权与到期回收记录",
                     "僵尸账号清理记录", "共享账号与直连核查记录", "高权限操作审计日志"],
        "accept": "高权限操作可追溯到个人，无共享、直连、僵尸账号",
    },
    {
        "no": "⑦", "name": "第三方、外包及委托数据处理管控不足", "layer": "执行层",
        "mgmt": {
            "制度": "第三方全流程管理制度与合同范本，明确处理范围、权限、使用限制、删除返还与审计权",
            "培训": "外包准入与数据交付要求交底",
            "流程规范": "准入—评估—合同—接入—监控—审计—退出全流程，退出时删除返还验证",
            "审计检查": "第三方持续监测、审计检查与退出验证",
        },
        "tech": ["第三方准入评估与合同管理", "第三方账号与远程接入管控", "数据交付脱敏",
                 "第三方行为监控与审计", "删除返还与退出验证", "第三方台账与名录"],
        "evidence": ["准入评估与合同（含处理范围、权限、使用限制、删除返还、审计权条款）",
                     "第三方台账", "接入与监控记录", "持续监测与审计报告", "退出与删除验证记录"],
        "accept": "项目结束数据已删除或返还且可验证，无残留访问权限",
    },
    {
        "no": "⑧", "name": "移动互联网应用第三方组件检测覆盖不完整", "layer": "资产层",
        "mgmt": {
            "制度": "移动应用与第三方组件管理办法",
            "培训": "研发与发布岗位组件安全规范",
            "流程规范": "建立覆盖 APP、H5、公众号、小程序的应用及组件台账，上线、版本变更、组件升级前安全评估及动态检测",
            "审计检查": "按渠道检查 SDK、插件、JS 库、外链脚本及接口调用",
        },
        "tech": ["移动应用安全检测", "第三方组件成分分析", "多渠道应用与组件台账",
                 "外链脚本与接口调用检测", "个人信息采集与权限调用检测"],
        "evidence": ["分渠道应用及组件台账", "SDK／插件／JS 库／外链脚本／接口调用检查记录",
                     "上线与变更升级前评估及动态检测报告", "超范围采集与越权调用处置记录"],
        "accept": "各渠道纳入检测，发布前有评估与检测记录",
    },
    {
        "no": "⑨", "name": "监测告警和问题整改未形成闭环", "layer": "机制层",
        "mgmt": {
            "制度": "告警分级与处置标准、整改闭环制度",
            "培训": "告警研判与台账填报",
            "流程规范": "告警人工分析—责任人—整改任务—整改时限—复测验收—整改验收—根因分析",
            "审计检查": "对重复问题开展专项问责和治理",
        },
        "tech": ["日志集中采集与关联分析", "数据库审计", "漏洞扫描", "防泄漏告警接入",
                 "告警分级与工单化", "问题台账与整改时限管理", "复测验收与根因分析工具"],
        "evidence": ["告警分级与处置标准", "告警人工分析记录", "问题台账（含责任人、整改任务、整改时限）",
                     "复测验收与整改验收记录", "根因分析报告"],
        "accept": "每条告警有分析、有责任人、有整改、有复测与验收证据",
    },
]

# ===========================================================================
# 三层治理框架 · 管理域 / 技术域 / 平台域 + 闭合链六环节
# ---------------------------------------------------------------------------
# 口径：三层不是三个模块，而是同一件事的三个落点——管理域把要求写成制度职责
#      与流程，技术域把要求变成数据实际被使用链路上生效的控制，平台域让治理动作
#      可复用、可留痕、可追溯；闭合链把「问题 → 依据 → 责任 → 控制 → 证据 →
#      整改验收」串成一条回到下一轮的回路。全代号化、无厂商与产品名称。
# ===========================================================================
GOV_FRAME_DOMAINS = [
    {"no": 1, "name": "管理域",
     "summary": "把要求落成制度、职责与流程，让每件事都有人负责、有据可依。",
     "items": [
         {"code": "制度", "text": "责任制、分类分级、数据全生命周期管理要求"},
         {"code": "职责", "text": "牵头部门、条线责任、岗位授权与问责"},
         {"code": "流程", "text": "发起、审批、复核、留痕的作业流程"},
     ]},
    {"no": 2, "name": "技术域",
     "summary": "把制度要求变成数据实际被使用链路上生效的控制。",
     "items": [
         {"code": "分级", "text": "数据分类分级与标识"},
         {"code": "防护", "text": "脱敏、水印、访问控制"},
         {"code": "监测", "text": "接口与日志监测、异常告警"},
     ]},
    {"no": 3, "name": "平台域",
     "summary": "让治理动作可复用、可留痕、可追溯。",
     "items": [
         {"code": "知识", "text": "制度、依据与检查项的统一知识底座"},
         {"code": "编排", "text": "自查、诊断、整改的作业编排"},
         {"code": "证据", "text": "证据归集、复核签署与审计留痕"},
     ]},
]

GOV_FRAME_CHAIN = [
    {"no": 1, "name": "问题", "desc": "逐项对照，形成问题清单"},
    {"no": 2, "name": "依据", "desc": "每条问题挂到可核对的依据口径"},
    {"no": 3, "name": "责任", "desc": "拆到发起、审批、复核、问责岗位"},
    {"no": 4, "name": "控制", "desc": "给出管理策略与技术防护策略"},
    {"no": 5, "name": "证据", "desc": "逐项归集可举证的材料"},
    {"no": 6, "name": "整改验收", "desc": "复检、验收与根因分析，回到下一轮"},
]


# ===========================================================================
# 第八轮：8 个扩展视图功能化 · 作业种子
# ---------------------------------------------------------------------------
# 口径：为可写作业表提供一份"已经在跑"的初始状态，让页面一进入就有可操作的
#      输入输出与流程节点；所有内容均为合成脱敏、全代号化示例。
# ===========================================================================


# —— 逐类问题处置：已在流转中的处置工单 ——
ISSUE_SEED_DISPOSALS = [
    {"issue_no": "②", "status": "assigned", "org_name": "数据管理部", "position": "数据治理岗",
     "plan": "按分类分级办法补齐目录，新增系统、移动渠道与外部接口逐项纳管。"},
    {"issue_no": "⑥", "status": "in_progress", "org_name": "信息科技部", "position": "运维安全岗",
     "plan": "特权账号实名单列，临时提权到期回收，清理僵尸与共享账号。"},
]

# —— 治理框架 · 闭合链在办案件（环序推进）——
FRAME_SEED_CASES = [
    {"issue_no": "②", "title": "分类分级与目录覆盖不完整 —— 闭合链推进（演示）",
     "rings": [
         (1, "逐项对照，形成问题清单", "形成分级覆盖缺口清单：系统甲、移动渠道各一处未覆盖", ""),
         (2, "每条问题挂到可核对的依据口径", "挂接分类分级办法与目录维护规范",
          "分类分级办法相关条款、目录维护规范"),
         (3, "拆到发起、审批、复核、问责岗位", "明确数据归属方与牵头部门责任，落到数据治理岗", ""),
     ]},
]

# —— 现状诊断：一份在填的诊断批次（留存证据说明待补，用于演示提交校验）——
DIAG_SEED_TITLE = "首轮现状诊断（演示）"
# 前两个维度已补齐证据说明，后三个维度留空 → 提交时触发"证据说明必填"校验
DIAG_SEED_EVIDENCE_FILLED = {1, 2}


# ===========================================================================
# 报告脱敏样例（白皮书附录 B 形态）
# ---------------------------------------------------------------------------
# 口径：用于展示自查报告五项结构与填写方式的示例化、代号化样例；主题仅作结构
#      演示。字段形状与自查报告「五项结构」一致（problems / bases / ownership /
#      evidenceGaps / nextSteps），供前端复用同一渲染逻辑。
# ===========================================================================
REPORT_SAMPLE = {
    "header": {
        "org": "机构 A（代号）",
        "topic": "示例主题（按机构当前关注点自选，此处仅作结构演示）",
        "cycle": "首轮",
        "review": "由指定人员复核确认后，作为机构自己的结论",
    },
    "five": {
        "note": "样例说明：以下为脱敏示例，用于展示自查报告的五项结构与填写方式。机构、系统、岗位、主题、字段与数据均为示例化、代号化内容；主题仅作结构演示。",
        "problems": [
            {"code": "B-1", "text": "系统甲（代号）的报表导出环节，导出审批记录与分级结果未逐项对应"},
            {"code": "B-1", "text": "系统乙（代号）的某后台接口，展示层已做脱敏处理，接口返回内容未按同一口径核对"},
            {"code": "B-1", "text": "某业务场景的敏感字段在处理链路上的留痕不完整"},
        ],
        "bases": [
            {"requirement": "数据导出与接口返回应按分级结果实施相应控制",
             "criterion": "以「控制是否在数据被实际使用的链路上生效」为准，不以页面展示为准"},
        ],
        "ownership": [
            {"code": "B-3", "title": "报表导出",
             "initiator": "业务岗 A（代号）", "approver": "业务负责人 B（代号）",
             "reviewer": "牵头部门", "accountable": "岗位 C（代号）"},
            {"code": "B-3", "title": "后台接口",
             "initiator": "系统岗 D（代号）", "approver": "科技负责人 E（代号）",
             "reviewer": "牵头部门", "accountable": "岗位 F（代号）"},
        ],
        "evidenceGaps": [
            {"code": "B-4", "text": "导出审批的完整记录尚未归集，无法逐项举证"},
            {"code": "B-4", "text": "接口返回内容的核对记录缺失，展示层与后台链路是否一致尚无材料"},
            {"code": "B-4", "text": "某使用场景下的角色权限清单尚未补入台账"},
        ],
        "nextSteps": [
            {"priority": "优先级一", "text": "补一份应用与业务层台账，把示例主题涉及的导出、接口、角色权限、报表与应用日志逐项对账"},
            {"priority": "优先级二", "text": "按对账结果补齐归档审批记录与核对记录"},
        ],
    },
}

# ===========================================================================
# 能力矩阵（§2.8）：键 → 中文；角色 → 能力集合
# ===========================================================================
CAPABILITY_LABELS = {
    "dashboard.view": "查看驾驶舱",
    "kb.view": "浏览知识库",
    "kb.publish": "发起/回滚知识发布",
    "kb.rebuild": "增量重建",
    "kb.rollback": "版本回滚",
    "kb.qa": "知识检索问答",
    "kb.collect": "外部采集",
    "kb.category": "知识库分类映射维护",
    "selfcheck.view": "查看自查任务",
    "selfcheck.create": "创建自查任务",
    "selfcheck.item": "登记自查单项",
    "selfcheck.signoff": "复核签署（职责分离）",
    "selfcheck.assign": "责任分配与下发",
    "selfcheck.evidence": "上传证据",
    "selfcheck.report": "查看/导出报告",
    "finding.manage": "问题登记与管理",
    "remediation.manage": "整改管理",
    "recheck.run": "发起复检",
    "review.proposal": "提案审核",
    "hitl.decide": "人工确认决策",
    "admin.org": "组织与岗位管理",
    "admin.role": "角色与授权管理",
    "admin.user": "账号状态管理",
    "admin.audit": "审计查询与导出",
    "admin.doc": "文号注册与结构确认",
    "admin.rule": "责任规则维护",
    "scenario.manage": "场景包管理",
    "plugin.invoke": "插件调用",
}

ROLE_CAPS = {
    "sys_admin": ["*"],
    # 对齐 PRD §2.8 权限基准矩阵（△ 需审批项在 Demo 粒度下按“允许”并入：
    # 逐键为细粒度派生，语义与 §2.8 一致；唯一硬约束"职责分离"由后端强校验，不受本表影响）
    "kb_ops": ["dashboard.view", "kb.view", "kb.qa", "kb.publish", "kb.rebuild", "kb.rollback",
               "kb.collect", "kb.category", "admin.doc", "review.proposal", "hitl.decide",
               "selfcheck.report", "recheck.run"],
    "l0_lead": ["dashboard.view", "kb.view", "kb.qa", "selfcheck.view", "selfcheck.create",
                "selfcheck.assign", "selfcheck.signoff", "selfcheck.report", "recheck.run",
                "finding.manage", "review.proposal"],
    "l1_handle": ["kb.view", "kb.qa", "selfcheck.view", "selfcheck.item", "selfcheck.assign",
                  "selfcheck.evidence", "finding.manage", "remediation.manage", "recheck.run",
                  "selfcheck.report", "review.proposal"],
    "l1_review": ["kb.view", "kb.qa", "selfcheck.view", "selfcheck.item", "selfcheck.evidence",
                  "selfcheck.signoff", "selfcheck.assign", "selfcheck.report", "recheck.run",
                  "finding.manage", "review.proposal", "hitl.decide"],
    "l2_handle": ["kb.view", "kb.qa", "selfcheck.view", "selfcheck.item", "selfcheck.evidence",
                  "finding.manage", "remediation.manage", "review.proposal"],
    "l3_exec": ["kb.view", "kb.qa", "selfcheck.view", "selfcheck.item", "selfcheck.evidence",
                "remediation.manage", "review.proposal"],
    "manager": ["dashboard.view", "kb.view", "kb.qa", "selfcheck.view", "selfcheck.report",
                "recheck.run", "admin.audit"],
}

ROLE_META = [
    ("sys_admin", "系统管理员", "L0", {"industries": ["bank", "insurance"], "orgLevels": ["L0", "L1", "L2", "L3"]}),
    ("kb_ops", "知识运营", "L0", {"industries": ["bank", "insurance"], "orgLevels": ["L0"]}),
    ("l0_lead", "L0 牵头", "L0", {"industries": ["bank"], "orgLevels": ["L0", "L1", "L2", "L3"]}),
    ("l1_handle", "L1 经办", "L1", {"industries": ["bank"], "orgLevels": ["L1", "L2", "L3"]}),
    ("l1_review", "L1 复核", "L1", {"industries": ["bank"], "orgLevels": ["L1", "L2", "L3"]}),
    ("l2_handle", "L2 经办", "L2", {"industries": ["bank"], "orgLevels": ["L2", "L3"]}),
    ("l3_exec", "L3 执行", "L3", {"industries": ["bank"], "orgLevels": ["L3"]}),
    ("manager", "管理者", "L0", {"industries": ["bank", "insurance"], "orgLevels": ["L0", "L1", "L2", "L3"]}),
]

# ---- 组织树（bank / insurance 两条完整树）----
ORG_NODES = [
    # 银行：L0 → L1×3 → 各 L2×2 → 各 L3×1
    ("bank-hq", None, "L0", "示范银行总行", "hq", "", "bank", 0),
    ("bank-east", "bank-hq", "L1", "华东分行", "branch", "east", "bank", 1),
    ("bank-north", "bank-hq", "L1", "华北分行", "branch", "north", "bank", 2),
    ("bank-south", "bank-hq", "L1", "华南分行", "branch", "south", "bank", 3),
    ("bank-east-1", "bank-east", "L2", "上海一支行", "subbranch", "east", "bank", 10),
    ("bank-east-2", "bank-east", "L2", "杭州支行", "subbranch", "east", "bank", 11),
    ("bank-east-1-1", "bank-east-1", "L3", "陆家嘴网点", "outlet", "east", "bank", 100),
    ("bank-east-2-1", "bank-east-2", "L3", "西湖网点", "outlet", "east", "bank", 101),
    ("bank-north-1", "bank-north", "L2", "北京一支行", "subbranch", "north", "bank", 12),
    ("bank-north-2", "bank-north", "L2", "天津支行", "subbranch", "north", "bank", 13),
    ("bank-north-1-1", "bank-north-1", "L3", "中关村网点", "outlet", "north", "bank", 102),
    ("bank-north-2-1", "bank-north-2", "L3", "滨海网点", "outlet", "north", "bank", 103),
    ("bank-south-1", "bank-south", "L2", "广州一支行", "subbranch", "south", "bank", 14),
    ("bank-south-2", "bank-south", "L2", "深圳支行", "subbranch", "south", "bank", 15),
    ("bank-south-1-1", "bank-south-1", "L3", "天河网点", "outlet", "south", "bank", 104),
    ("bank-south-2-1", "bank-south-2", "L3", "福田网点", "outlet", "south", "bank", 105),
    # 保险：L0 → L1×2 → 各 L2×2 → 各 L3×1
    ("ins-hq", None, "L0", "示范保险总公司", "hq", "", "insurance", 200),
    ("ins-east", "ins-hq", "L1", "华东分公司", "branch", "east", "insurance", 201),
    ("ins-north", "ins-hq", "L1", "华北分公司", "branch", "north", "insurance", 202),
    ("ins-east-1", "ins-east", "L2", "上海中心支公司", "subbranch", "east", "insurance", 210),
    ("ins-east-2", "ins-east", "L2", "南京中心支公司", "subbranch", "east", "insurance", 211),
    ("ins-east-1-1", "ins-east-1", "L3", "浦东柜面", "counter", "east", "insurance", 300),
    ("ins-east-2-1", "ins-east-2", "L3", "鼓楼柜面", "counter", "east", "insurance", 301),
    ("ins-north-1", "ins-north", "L2", "北京中心支公司", "subbranch", "north", "insurance", 212),
    ("ins-north-2", "ins-north", "L2", "石家庄中心支公司", "subbranch", "north", "insurance", 213),
    ("ins-north-1-1", "ins-north-1", "L3", "朝阳柜面", "counter", "north", "insurance", 302),
    ("ins-north-2-1", "ins-north-2", "L3", "裕华柜面", "counter", "north", "insurance", 303),
]

ORG_POSITIONS = [
    ("pos-admin", "bank-hq", "平台管理员", "active"),
    ("pos-kbops", "bank-hq", "知识运营岗", "active"),
    ("pos-lead", "bank-hq", "数据安全牵头人", "active"),
    ("pos-manager", "bank-hq", "分管领导", "active"),
    ("pos-inspector", "bank-hq", "监管主查岗", "active"),
    ("pos-handle-bank-east", "bank-east", "分行经办岗", "active"),
    ("pos-review-bank-east", "bank-east", "分行复核岗", "active"),
    ("pos-handle-bank-east-1", "bank-east-1", "支行经办岗", "active"),
    ("pos-exec-bank-east-1-1", "bank-east-1-1", "网点执行岗", "active"),
    ("pos-handle-bank-north", "bank-north", "分行经办岗", "active"),
    ("pos-handle-bank-south", "bank-south", "分行经办岗", "active"),
    ("pos-lead-ins", "ins-hq", "保险牵头人", "active"),
    ("pos-handle-ins-east", "ins-east", "分公司经办岗", "active"),
    ("pos-handle-ins-east-1", "ins-east-1", "中支经办岗", "active"),
]

# 账号（≥14，合成姓名，均标注"（演示）"）
USERS = [
    ("admin", "系统管理员（演示）", "bank-hq", "pos-admin", ["sys_admin"], "active", 1),
    ("kbops", "刘运营（演示）", "bank-hq", "pos-kbops", ["kb_ops"], "active", 0),
    ("wangzong", "王总（演示）", "bank-hq", "pos-lead", ["l0_lead"], "active", 0),
    ("chenzong", "陈总（演示）", "bank-hq", "pos-manager", ["manager"], "active", 0),
    ("sunjc", "孙检查（演示）", "bank-hq", "pos-inspector", ["manager"], "active", 0),
    ("lijb", "李经办（演示）", "bank-east", "pos-handle-bank-east", ["l1_handle"], "active", 0),
    ("lifh", "李复核（演示）", "bank-east", "pos-review-bank-east", ["l1_review"], "active", 0),
    ("fengsh", "冯审查（演示）", "bank-east", "pos-review-bank-east", ["l1_review"], "active", 0),
    ("zhangjb", "张经办（演示）", "bank-east-1", "pos-handle-bank-east-1", ["l2_handle"], "active", 0),
    ("zhaogui", "赵柜员（演示）", "bank-east-1-1", "pos-exec-bank-east-1-1", ["l3_exec"], "active", 0),
    ("duorole", "钱多角（演示）", "bank-north", "pos-handle-bank-north", ["l1_handle", "l1_review"], "active", 0),
    ("inszhou", "周总保（演示）", "ins-hq", "pos-lead-ins", ["l0_lead"], "active", 0),
    ("inswu", "吴经办（演示）", "ins-east", "pos-handle-ins-east", ["l1_handle"], "active", 0),
    ("inszheng", "郑经办（演示）", "ins-east-1", "pos-handle-ins-east-1", ["l2_handle"], "active", 0),
    ("hantq", "韩停用（演示）", "bank-south", "pos-handle-bank-south", ["l2_handle"], "disabled", 0),
]

INDUSTRY_PROFILES = [
    ("prof-bank", "bank", "银行业安全自查档案",
     {"orgTypes": ["总行", "分行", "支行", "网点"]},
     {"lines": [
         {"code": "acct", "label": "账户与支付"},
         {"code": "credit", "label": "信贷"},
         {"code": "creditref", "label": "征信"},
         {"code": "wealth", "label": "理财"},
         {"code": "interbank", "label": "同业"},
         {"code": "openbank", "label": "开放银行"}]},
     {"sensitiveTypes": ["账户信息", "交易流水", "征信信息", "身份信息"]},
     {"docFocus": ["jg24", "pboc3"], "primary": "jg24"},
     "bank-selfcheck-v1"),
    ("prof-ins", "insurance", "保险业安全自查档案",
     {"orgTypes": ["总公司", "分公司", "中心支公司", "柜面"]},
     {"lines": [
         {"code": "underwrite", "label": "投保"},
         {"code": "uwreview", "label": "核保"},
         {"code": "claim", "label": "理赔"},
         {"code": "preserve", "label": "保全"},
         {"code": "actuary", "label": "精算"},
         {"code": "reinsure", "label": "再保"},
         {"code": "agent", "label": "中介"}]},
     {"sensitiveTypes": ["健康医疗", "生物识别", "保单信息", "受益人信息"]},
     {"docFocus": ["jg24", "jg93"], "primary": "jg93"},
     "insurance-selfcheck-v1"),
]

DOC_REGISTRY = [
    ("jg24", "金规〔2024〕24号", "银行保险机构数据安全管理办法", "国家金融监督管理总局",
     "2024-12-27", {"levels": ["章", "条", "检查项"], "checkPattern": "N.N"}, "active", 116, "admin"),
    ("jg93", "金办发〔2025〕93号", "金融机构数据安全管理自查要点", "国家金融监督管理总局办公厅",
     "2025-06-01", {"levels": ["大类", "细项"], "checkPattern": "93-N.N"}, "active", 142, "admin"),
    ("pboc3", "中国人民银行令〔2025〕第3号", "业务领域数据安全管理办法", "中国人民银行",
     "2025-03-01", {"levels": ["条"], "checkPattern": "pb3-N"}, "active", 56, "admin"),
    ("jf8", "金发〔2026〕8号", "人工智能安全开发应用治理规范", "国家金融监督管理总局",
     "2026-01-15", {"levels": ["条"], "checkPattern": "jf8-N"}, "active", 32, "admin"),
    ("jf26", "金发〔2026〕26号", "银行保险机构数据出境安全管理通知", "国家金融监督管理总局",
     "2026-05-20", {"levels": ["条"], "checkPattern": "jf26-N"}, "active", 18, "kbops"),
    ("pboc8", "中国人民银行令〔2026〕第8号", "数据出境安全评估与申报管理办法", "中国人民银行",
     "2026-10-01", {"levels": ["章", "条"], "checkPattern": "pb8-N"}, "pending", 0, "kbops"),
]

# 内置回退检查项（kb_source 不可用时使用；编号与真实体系一致）
FALLBACK_CHECKS = {
    "jg24": [("1.1", "党委（党组）、董（理）事会主体责任"), ("1.2", "第一责任人与直接责任人"),
             ("1.3", "各层级负责人责任"), ("1.4", "归口管理部门职责"), ("1.5", "信息科技部门职责"),
             ("1.6", "各业务领域数据安全管理责任"), ("2.1", "组织架构/岗位职责/工作机制"),
             ("2.2", "数据分类分级制度"), ("3.1", "数据收集合法合规"), ("3.2", "数据存储与加密"),
             ("3.3", "数据使用与加工"), ("3.4", "数据传输与提供")],
    "jg93": [("93-1.1", "数据安全治理架构"), ("93-1.2", "数据安全责任落实"),
             ("93-2.1", "数据分类分级管理"), ("93-2.2", "重要数据目录管理"),
             ("93-3.1", "数据全生命周期安全管理"), ("93-3.2", "个人信息保护"),
             ("93-4.1", "技术防护措施"), ("93-4.2", "访问控制与日志审计"),
             ("93-5.1", "风险监测与应急"), ("93-5.2", "安全评估与审查"),
             ("93-6.1", "外包与第三方管理"), ("93-6.2", "监管报送与整改")],
}


def _code_key(cc: str):
    m = re.search(r"(\d+)\.(\d+)", cc or "")
    if m:
        return (0, int(m.group(1)), int(m.group(2)))
    m = re.search(r"(\d+)", cc or "")
    if m:
        return (0, int(m.group(1)), 0)
    return (1, 0, 0)


def _real_checks(doc: str) -> list[dict]:
    """取真实检查项（优先 kb_source.fetch_checks）；异常/为空回退内置样本。"""
    try:
        from ..services import kb_source
        env = kb_source.fetch_checks(doc)
        checks = (env.get("content") or {}).get("checks") or []
        out = [{"checkCode": c.get("checkCode"), "title": c.get("title"),
                "domain": c.get("domain") or "", "priority": c.get("priority") or "P1"}
               for c in checks if c.get("checkCode")]
        if out:
            return sorted(out, key=lambda x: _code_key(x["checkCode"]))
    except Exception:  # noqa: BLE001 — 取数不可达一律回退，绝不阻断种子
        pass
    return [{"checkCode": c, "title": t, "domain": "", "priority": "P1"}
            for c, t in FALLBACK_CHECKS.get(doc, [])]


def _pick(checks: list[dict], n: int) -> list[dict]:
    """截取前 n 项（按编号排序后）。"""
    return checks[:n]


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _synthetic_hash(seed: str) -> str:
    import hashlib
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


# ===========================================================================
# 主流程
# ===========================================================================
def ensure_seeded(force: bool = False) -> dict:
    """幂等灌种：已灌过（版本一致）则不重复；force=True 先清空再灌。"""
    store.init_demo_db()
    if not force and store.get_state("seeded_version") == SEED_VERSION:
        return {"seeded": False, "version": SEED_VERSION}
    store.reset_demo_db()
    _seed_all()
    store.set_state("seeded_version", SEED_VERSION)
    store.set_state("current_account", store.get_state("current_account") or "admin")
    store.set_state("reset_count", int(store.get_state("reset_count", 0) or 0) + (1 if force else 0))
    return {"seeded": True, "version": SEED_VERSION}


def reset_seed() -> dict:
    """演示重置：清空并重灌，返回重置计数与时间。"""
    store.reset_demo_db()
    _seed_all()
    store.set_state("seeded_version", SEED_VERSION)
    store.set_state("current_account", "admin")
    store.set_state("reset_count", int(store.get_state("reset_count", 0) or 0) + 1)
    store.set_state("reset_at", _now())
    return {"version": SEED_VERSION, "reset_at": _now(),
            "reset_count": store.get_state("reset_count", 1)}


def _seed_all() -> None:
    now = _now()
    # ---- 组织 / 岗位 / 账号 / 角色 / 绑定 ----
    for nid, pid, lvl, name, kind, line, ind, sort in ORG_NODES:
        store.insert("org_node", {"node_id": nid, "parent_id": pid, "level": lvl, "name": name,
                                  "kind": kind, "line_code": line, "industry": ind, "sort": sort})
    for pid, nid, name, status in ORG_POSITIONS:
        store.insert("org_position", {"position_id": pid, "org_node_id": nid, "name": name, "status": status})
    for account, disp, nid, pid, roles, status, boot in USERS:
        store.insert("user_account", {
            "account": account, "display_name": disp,
            "idp_subject": f"idp|{account}", "idp_type": "oidc",
            "org_node_id": nid, "position_id": pid, "email": f"{account}@demo.example.com",
            "status": status, "last_login_at": now if status == "active" else None,
            "is_bootstrap": boot})
        for rid in roles:
            store.insert("role_binding", {
                "binding_id": f"rb-{account}-{rid}", "account": account, "role_id": rid,
                "org_node_id": nid, "position_id": pid})
    for rid, name, lvlvis, scope in ROLE_META:
        store.insert("role_def", {
            "role_id": rid, "name": name,
            "capabilities_json": json.dumps(ROLE_CAPS[rid], ensure_ascii=False),
            "scope_json": json.dumps(scope, ensure_ascii=False),
            "level_visibility": lvlvis, "status": "active", "builtin": 1,
            "updated_by": "admin", "updated_at": now})

    # ---- 行业档案 / 文号 ----
    for pid, ind, name, orgtypes, lines, sens, focus, tpl in INDUSTRY_PROFILES:
        store.insert("industry_profile", {
            "profile_id": pid, "industry": ind, "name": name,
            "org_types_json": json.dumps(orgtypes, ensure_ascii=False),
            "lines_json": json.dumps(lines, ensure_ascii=False),
            "sensitive_types_json": json.dumps(sens, ensure_ascii=False),
            "doc_focus_json": json.dumps(focus, ensure_ascii=False),
            "report_template": tpl})
    for dk, no, title, body, eff, prof, status, cnt, by in DOC_REGISTRY:
        store.insert("doc_registry", {
            "doc_key": dk, "doc_no": no, "title": title, "issuing_body": body,
            "effective_date": eff, "structure_profile_json": json.dumps(prof, ensure_ascii=False),
            "status": status, "check_count": cnt, "registered_by": by, "registered_at": now})

    # ---- 分类映射 ----
    for i, (pfx, cat) in enumerate([("法规", "合规法规"), ("检查项", "监管检查"),
                                    ("控制", "控制措施"), ("资产", "数据资产"),
                                    ("证据", "证据材料"), ("责任", "职责分工")]):
        store.insert("kb_category_mapping", {"mapping_id": f"km-{i}", "type_prefix": pfx,
                                              "category": cat, "sort": i})

    # ---- 检查项（真实编号）----
    jg24 = _real_checks("jg24")
    jg93 = _real_checks("jg93")
    bank_checks = _pick(jg24, 18)
    ins_checks = _pick(jg93, 16)

    # ---- 计划 + 任务 ----
    _seed_plans_and_tasks(now, bank_checks, ins_checks)
    # ---- 责任分配 ----
    _seed_assignment(now, bank_checks, ins_checks)
    # ---- 知识发布 ----
    _seed_publish(now)
    # ---- 治理：提案 / 人工确认 / 采集 ----
    _seed_governance(now, jg24, jg93)
    # ---- 插件 / 场景包 ----
    _seed_plugins_scenarios(now)
    # ---- 第八轮：8 个扩展视图功能化作业种子 ----
    _seed_extended(now)
    # ---- 第九轮：闭环工作流 / 知识发布治理 / 资产台账 / 插件治理 / 权限精细化 ----
    _seed_round9(now)
    # ---- 审计（≥60，哈希链）----
    _seed_audit(now)


def _plan(pid, name, industry, scope, ver, status, by, ts):
    store.insert("inspection_plan", {
        "plan_id": pid, "name": name, "industry": industry,
        "scope_json": json.dumps(scope, ensure_ascii=False), "checklist_version": ver,
        "status": status, "created_by": by, "created_at": ts})


def _seed_plans_and_tasks(now: str, bank_checks: list[dict], ins_checks: list[dict]) -> None:
    _plan("plan-bank-q4", "银行 2026Q4 全条线自查计划", "bank",
          {"lines": ["acct", "credit", "creditref", "wealth", "interbank", "openbank"], "docs": ["jg24"]},
          "v3.0", "active", "wangzong", now)
    _plan("plan-ins-q4", "保险 2026Q4 理赔条线自查计划", "insurance",
          {"lines": ["claim", "preserve"], "docs": ["jg93"]}, "v3.0", "active", "inszhou", now)
    _plan("plan-bank-q3", "银行 2026Q3 已闭环自查计划", "bank",
          {"lines": ["acct", "credit"], "docs": ["jg24"]}, "v2.0", "closed", "wangzong", now)

    tasks = [
        dict(task_id="t-bank-2026q4", plan_id="plan-bank-q4", industry="bank",
             org_name="华东分行", org_type="分行", org_node_id="bank-east", cycle="2026Q4",
             owner="lijb", assignees=["lijb", "lifh"], stage="季度自查", topic="数据安全专项",
             status="in_progress", progress=62, risk_level="medium",
             start_date="2026-10-01", end_date="2026-12-20", created_by="wangzong",
             created_at=now, updated_at=now,
             scope={"lines": ["acct", "credit", "creditref", "wealth"]}),
        dict(task_id="t-ins-2026q4", plan_id="plan-ins-q4", industry="insurance",
             org_name="华东分公司", org_type="分公司", org_node_id="ins-east", cycle="2026Q4",
             owner="inswu", assignees=["inswu"], stage="季度自查", topic="理赔数据安全",
             status="in_progress", progress=45, risk_level="high",
             start_date="2026-10-08", end_date="2026-12-25", created_by="inszhou",
             created_at=now, updated_at=now,
             scope={"lines": ["claim", "preserve"]}),
        dict(task_id="t-bank-2026q3", plan_id="plan-bank-q3", industry="bank",
             org_name="华东分行", org_type="分行", org_node_id="bank-east", cycle="2026Q3",
             owner="lijb", assignees=["lijb", "lifh"], stage="季度自查", topic="账户数据安全",
             status="closed", progress=100, risk_level="low",
             start_date="2026-07-01", end_date="2026-09-30", created_by="wangzong",
             created_at=now, updated_at=now, scope={"lines": ["acct", "credit"]}),
        dict(task_id="t-bank-2026q4-draft", plan_id="plan-bank-q4", industry="bank",
             org_name="华东分行", org_type="分行", org_node_id="bank-east", cycle="2026Q4",
             owner="lijb", assignees=[], stage="季度自查", topic="专项待下发",
             status="draft", progress=0, risk_level="medium",
             start_date="2026-12-01", end_date="2026-12-31", created_by="lijb",
             created_at=now, updated_at=now, scope={"lines": ["openbank"]}),
        dict(task_id="t-bank-east1-2026q4", plan_id="plan-bank-q4", industry="bank",
             org_name="上海一支行", org_type="支行", org_node_id="bank-east-1", cycle="2026Q4",
             owner="zhangjb", assignees=["zhangjb", "zhaogui"], stage="季度自查", topic="柜面数据安全",
             status="in_progress", progress=38, risk_level="medium",
             start_date="2026-10-05", end_date="2026-12-20", created_by="lijb",
             created_at=now, updated_at=now, scope={"lines": ["acct"]}),
        dict(task_id="t-bank-north-2026q4", plan_id="plan-bank-q4", industry="bank",
             org_name="华北分行", org_type="分行", org_node_id="bank-north", cycle="2026Q4",
             owner="duorole", assignees=["duorole"], stage="季度自查", topic="信贷数据安全",
             status="in_progress", progress=30, risk_level="medium",
             start_date="2026-10-10", end_date="2026-12-20", created_by="duorole",
             created_at=now, updated_at=now, scope={"lines": ["credit"]}),
    ]
    for t in tasks:
        row = dict(t)
        row["assignees_json"] = json.dumps(t["assignees"], ensure_ascii=False)
        row["scope_json"] = json.dumps(t["scope"], ensure_ascii=False)
        row.pop("assignees"); row.pop("scope")
        store.insert("selfcheck_task", row)

    # 分区 / 单项 / 运行 / 结果 / 证据 / 签核 / 问题 / 整改
    _seed_task_details(now, tasks, bank_checks, ins_checks)


def _seed_task_details(now, tasks, bank_checks, ins_checks):
    bank_lines = [("acct", "账户与支付"), ("credit", "信贷"), ("creditref", "征信"), ("wealth", "理财")]
    ins_lines = [("claim", "理赔"), ("preserve", "保全")]
    statuses = ["pass", "partial", "fail", "supplement"]

    for t in tasks:
        tid = t["task_id"]
        checks = ins_checks if t["industry"] == "insurance" else bank_checks
        lines = ins_lines if t["industry"] == "insurance" else bank_lines
        # sections
        for i, (code, label) in enumerate(lines):
            pct = max(0, min(100, int(t["progress"]) - i * 7))
            st = "closed" if t["status"] == "closed" else ("open" if pct < 100 else "closed")
            store.insert("selfcheck_section", {
                "section_id": f"sec-{tid}-{code}", "task_id": tid, "line_code": code,
                "line_label": label, "owner": t["owner"], "due_date": t["end_date"],
                "status": st, "progress": pct})
        # items（四录入项）
        for i, c in enumerate(checks):
            status = "pass" if (i % 5) else statuses[i % len(statuses)]
            has_policy = 1 if i % 3 != 0 else 0
            ev = [{"name": f"证据-{c['checkCode']}-制度.pdf", "hash": _synthetic_hash(tid + c["checkCode"])[:16],
                   "status": "provided"}] if i % 2 == 0 else []
            store.insert("selfcheck_item_state", {
                "state_id": f"it-{tid}-{c['checkCode']}", "task_id": tid,
                "check_code": c["checkCode"], "line_code": (lines[i % len(lines)][0] if lines else ""),
                "applicability": "applicable", "status": status, "owner": t["owner"],
                "has_policy": has_policy, "evidence_json": json.dumps(ev, ensure_ascii=False),
                "actual_value": f"覆盖率 {60 + (i * 3) % 40}%",
                "note": "演示数据：合成登记", "updated_at": now})
        # 运行
        _seed_run(now, t, checks, run_type="preliminary",
                  submitter=t["owner"], run_suffix="main")
        if t["status"] in ("in_progress", "closed"):
            _seed_run(now, t, checks, run_type="recheck", submitter=t["owner"], run_suffix="recheck")

    # 证据 + 签核
    store.insert("inspection_evidence", {
        "evidence_id": "ev-t1-1", "run_id": "run-t-bank-2026q4-main", "task_id": "t-bank-2026q4",
        "check_code": bank_checks[0]["checkCode"], "file_name": "账户数据安全制度v3.pdf",
        "storage_ref": "demo://evidence/ev-t1-1.pdf",
        "file_hash": _synthetic_hash("ev-t1-1"), "size": 245678,
        "uploaded_by": "lijb", "uploaded_at": now})
    store.insert("inspection_evidence", {
        "evidence_id": "ev-t1-2", "run_id": "run-t-bank-2026q4-main", "task_id": "t-bank-2026q4",
        "check_code": bank_checks[2]["checkCode"], "file_name": "访问控制日志截图.png",
        "storage_ref": "demo://evidence/ev-t1-2.png",
        "file_hash": _synthetic_hash("ev-t1-2"), "size": 88421,
        "uploaded_by": "lijb", "uploaded_at": now})
    store.insert("inspection_signoff", {
        "signoff_id": "so-t3-1", "run_id": "run-t-bank-2026q3-main", "task_id": "t-bank-2026q3",
        "signer": "chenzong", "signer_name": "陈总（演示）", "role": "manager",
        "decision": "approve", "comment": "季度自查结论已复核，同意闭环。", "signed_at": now})

    _seed_findings(now)


def _seed_run(now, t, checks, run_type, submitter, run_suffix):
    run_id = f"run-{t['task_id']}-{run_suffix}"
    store.insert("inspection_run", {
        "run_id": run_id, "plan_id": t["plan_id"], "task_id": t["task_id"],
        "run_type": run_type, "inspected_target": t["org_name"], "inspector": submitter,
        "assignees_json": json.dumps(t["assignees"], ensure_ascii=False), "ran_at": now,
        "submitter_account": submitter})
    for i, c in enumerate(checks):
        # 复检运行普遍好于初检（用于复检前后对比演示）
        if run_type == "recheck":
            res = "pass" if i % 6 != 0 else "partial"
        else:
            res = "pass" if i % 4 != 0 else ("fail" if i % 8 == 0 else "partial")
        store.insert("check_result", {
            "result_id": f"res-{run_id}-{c['checkCode']}", "run_id": run_id,
            "check_code": c["checkCode"],
            "elements_json": json.dumps([{"element": "制度", "ok": res != "fail"},
                                         {"element": "证据", "ok": res == "pass"}], ensure_ascii=False),
            "metrics_json": json.dumps([{"metric": "覆盖率", "value": f"{55 + (i * 4) % 45}%"}], ensure_ascii=False),
            "result": res, "judge_source": "symbolic", "confidence": round(0.6 + (i % 4) * 0.1, 2),
            "why_json": json.dumps([f"{c['checkCode']} 判定依据：要素与度量聚合"], ensure_ascii=False)})


def _seed_findings(now):
    findings = [
        ("f-1", "t-bank-2026q4", "15.5", "high", "敏感数据操作日志记录要素不完整",
         "日志采集组件未覆盖全部敏感数据操作", "remediating", "lijb", "2026-12-10",
         "run-t-bank-2026q4-main"),
        ("f-2", "t-bank-2026q4", "16.4", "high", "测试环境未与生产隔离且敏感数据未脱敏",
         "测试数据直接取自生产库", "assigned", "lijb", "2026-12-15",
         "run-t-bank-2026q4-main"),
        ("f-3", "t-bank-2026q3", "15.8", "medium", "个人身份鉴别数据存在明文展示",
         "前端回显未做脱敏", "passed", "lijb", "2026-09-20",
         "run-t-bank-2026q3-main"),
        ("f-4", "t-bank-2026q3", "13.3", "medium", "数据销毁管理制度缺失",
         "制度未覆盖介质报废环节", "closed", "zhangjb", "2026-09-25",
         "run-t-bank-2026q3-main"),
        ("f-5", "t-ins-2026q4", "93-3.1", "low", "理赔单据影像留存周期不明确",
         "留存策略未在制度中固化", "open", "inswu", "2026-12-18",
         "run-t-ins-2026q4-main"),
        ("f-6", "t-bank-2026q4", "11.3", "medium", "委托处理记录与审计不完整",
         "受托方操作记录未纳管", "recheck", "lijb", "2026-12-05",
         "run-t-bank-2026q4-main"),
        ("f-7", "t-bank-east1-2026q4", "15.11", "high", "终端与移动存储介质受控访问不足",
         "网点终端未启用外设管控", "open", "zhangjb", "2026-12-12",
         "run-t-bank-east1-2026q4-main"),
    ]
    for fid, tid, code, sev, prob, rc, st, owner, due, src in findings:
        store.insert("selfcheck_finding", {
            "finding_id": fid, "task_id": tid, "check_code": code, "severity": sev,
            "problem": prob, "root_cause": rc, "status": st, "owner": owner,
            "due_date": due, "created_at": now, "source_run_id": src})

    remediations = [
        ("rem-1", "f-3", "t-bank-2026q3", "lijb", "2026-09-18",
         "对身份鉴别数据全链路启用脱敏展示，前端回显按字段策略脱敏。", "done",
         "demo://evidence/rem-1.md"),
        ("rem-2", "f-4", "t-bank-2026q3", "zhangjb", "2026-09-23",
         "发布《数据销毁管理制度》，补充介质报废与重用前彻底清除条款。", "done",
         "demo://evidence/rem-2.md"),
        ("rem-3", "f-1", "t-bank-2026q4", "lijb", "2026-12-08",
         "扩展日志采集组件覆盖范围，补齐操作主体/客体/时间/结果四要素。", "in_progress",
         "demo://evidence/rem-3.md"),
        ("rem-4", "f-2", "t-bank-2026q4", "lijb", "2026-12-12",
         "测试数据脱敏后入测试环境，网络域隔离并加白名单。", "assigned", None),
        ("rem-5", "f-5", "t-ins-2026q4", "inswu", "2026-12-16",
         "在理赔制度中固化影像留存周期（不少于 5 年）。", "open", None),
    ]
    for rid, fid, tid, owner, due, measures, st, evref in remediations:
        store.insert("remediation_task", {
            "remediation_id": rid, "finding_id": fid, "task_id": tid, "owner": owner,
            "due_date": due, "measures": measures, "status": st, "evidence_ref": evref,
            "created_at": now, "updated_at": now})


def _seed_assignment(now, bank_checks, ins_checks):
    # 规则编号一律取"真实检查项编号"，保证「分配预览」能命中（否则预览覆盖率恒为 0）
    b = [c["checkCode"] for c in bank_checks]
    s = [c["checkCode"] for c in ins_checks]
    bc = lambda i, fb: b[i % len(b)] if b else fb   # noqa: E731
    ic = lambda i, fb: s[i % len(s)] if s else fb   # noqa: E731
    rules = [
        ("rule-1", bc(0, "1.1"), "bank", {"orgLevels": ["L1", "L2"]}, "季度自查", "数据安全专项",
         "bank-east", "pos-handle-bank-east", "l1_handle", 1, "active"),
        ("rule-2", bc(1, "1.2"), "bank", {"orgLevels": ["L1"]}, "季度自查", "数据安全专项",
         "bank-east", "pos-handle-bank-east", "l1_handle", 1, "active"),
        ("rule-3", bc(2, "1.3"), "bank", {"orgLevels": ["L1", "L2"]}, "季度自查", "数据安全专项",
         "bank-east", "pos-review-bank-east", "l1_review", 1, "active"),
        ("rule-4", bc(3, "2.1"), "bank", {"orgLevels": ["L0", "L1"]}, "季度自查", "数据安全专项",
         "bank-hq", "pos-lead", "l0_lead", 1, "active"),
        ("rule-5", bc(4, "2.2"), "bank", {"orgLevels": ["L2", "L3"]}, "季度自查", "柜面数据安全",
         "bank-east-1", "pos-handle-bank-east-1", "l2_handle", 1, "active"),
        ("rule-6", bc(5, "3.1"), "bank", {"orgLevels": ["L1", "L2"]}, "季度自查", "数据安全专项",
         "bank-east", "pos-review-bank-east", "l1_review", 1, "active"),
        ("rule-7", bc(6, "3.2"), "bank", {"orgLevels": ["L1"]}, "季度自查", "数据安全专项",
         "bank-east", "pos-handle-bank-east", "l1_handle", 1, "active"),
        ("rule-8", bc(7, "4.1"), "bank", {"orgLevels": ["L1"]}, "季度自查", "数据安全专项",
         "bank-east", "pos-handle-bank-east", "l1_handle", 1, "active"),
        # 冲突演示：rule-9 与 rule-8 命中同一检查项（预览将提示"需人工裁定"）
        ("rule-9", bc(7, "4.1"), "bank", {"orgLevels": ["L2", "L3"]}, "季度自查", "数据安全专项",
         "bank-east-1", "pos-handle-bank-east-1", "l2_handle", 1, "active"),
        # 保险侧规则（同样取真实 jg93 检查项编号）
        ("rule-10", ic(0, "93-1.1"), "insurance", {"orgLevels": ["L1"]}, "季度自查", "理赔数据安全",
         "ins-east", "pos-handle-ins-east", "l1_handle", 1, "active"),
        ("rule-11", ic(1, "93-1.2"), "insurance", {"orgLevels": ["L1", "L2"]}, "季度自查", "理赔数据安全",
         "ins-east", "pos-handle-ins-east", "l1_handle", 1, "active"),
        ("rule-12", ic(2, "93-2.1"), "insurance", {"orgLevels": ["L2"]}, "季度自查", "理赔数据安全",
         "ins-east-1", "pos-handle-ins-east-1", "l2_handle", 1, "active"),
    ]
    for rid, code, ind, scope, stage, topic, dept, pos, role, ver, st in rules:
        store.insert("check_assignment_rule", {
            "rule_id": rid, "check_code": code, "industry": ind,
            "org_scope_json": json.dumps(scope, ensure_ascii=False), "stage": stage, "topic": topic,
            "target_dept_id": dept, "target_position_id": pos, "target_role_id": role,
            "version": ver, "status": st})

    mapping = []
    for i, c in enumerate(_pick(bank_checks, 8)):
        r = rules[i % len(rules)]
        mapping.append({"checkCode": c["checkCode"], "title": c["title"],
                        "deptId": r[6], "positionId": r[7], "roleId": r[8], "source": "rule"})
    store.insert("assignment_batch", {
        "batch_id": "batch-t-bank-2026q4-1", "task_id": "t-bank-2026q4", "rule_version": 1,
        "scope_json": json.dumps({"lines": ["acct", "credit"]}, ensure_ascii=False),
        "mapping_snapshot_json": json.dumps(mapping, ensure_ascii=False),
        "unmatched_json": json.dumps([], ensure_ascii=False),
        "conflicts_json": json.dumps([], ensure_ascii=False),
        "coverage": round(len(mapping) / 8 * 100, 1), "confirmed_by": "lijb", "confirmed_at": now})
    store.insert("check_assignment_override", {
        "override_id": "ov-1", "batch_id": "batch-t-bank-2026q4-1",
        "check_code": bank_checks[0]["checkCode"], "target_dept_id": "bank-east",
        "target_position_id": "pos-review-bank-east", "target_role_id": "l1_review",
        "reason": "该检查项涉及日志审计，改由复核岗负责", "changed_by": "lijb", "changed_at": now})


def _seed_publish(now):
    runs = [
        ("run-20261001", "schedule", "incremental", "2026-10-01T02:00:00", "2026-10-01T02:03:12",
         "success", "v2026.10.01", 12, 24, 192000, None, "system"),
        ("run-20261015", "manual", "incremental", "2026-10-15T10:12:00", "2026-10-15T10:15:40",
         "success", "v2026.10.15", 8, 24, 220000, None, "kbops"),
        ("run-20261028", "manual", "full", "2026-10-28T09:30:00", "2026-10-28T09:30:45",
         "failed", "v2026.10.28", 0, 24, 45000, "质量校验未通过：3 条文档哈希校验失败", "kbops"),
        ("run-20261101", "manual", "incremental", "2026-11-01T08:00:00", "2026-11-01T08:02:50",
         "success", "v2026.11.01", 6, 24, 170000, None, "kbops"),
        ("run-20261105", "schedule", "incremental", "2026-11-05T02:00:00", "2026-11-05T02:02:05",
         "success", "v2026.11.05", 4, 24, 125000, None, "system"),
        ("run-20261110", "manual", "incremental", "2026-11-10T15:20:00", "2026-11-10T15:22:35",
         "success", "v2026.11.10", 5, 26, 155000, None, "kbops"),
    ]
    for rid, trg, mode, st, fin, status, vdir, changed, total, dur, err, op in runs:
        store.insert("kb_publish_run", {
            "run_id": rid, "trigger": trg, "mode": mode, "started_at": st, "finished_at": fin,
            "status": status, "version_dir": vdir, "changed_docs": changed, "total_docs": total,
            "duration_ms": dur, "error": err, "operator": op})
    store.set_state("publish_current", "v2026.11.10")

    docs = [
        ("jg24", "金规〔2024〕24号 银行保险机构数据安全管理办法"),
        ("jg93", "金办发〔2025〕93号 金融机构数据安全管理自查要点"),
        ("pboc3", "人民银行令〔2025〕第3号 业务领域数据安全管理办法"),
        ("jf8", "金发〔2026〕8号 人工智能安全开发应用治理规范"),
        ("jf26", "金发〔2026〕26号 数据出境安全管理通知"),
        ("pboc8", "人民银行令〔2026〕第8号 数据出境安全评估办法"),
    ]
    # ≥24 条变更清单：6 文号 × 4 分片
    idx = 0
    for dk, title in docs:
        for shard in range(1, 5):
            idx += 1
            status = "failed" if (dk == "pboc8" or (dk == "jf26" and shard == 4)) else "published"
            store.insert("kb_publish_manifest", {
                "doc_id": f"man-{idx:03d}", "doc_key": dk, "title": f"{title} · 分片{shard}",
                "content_hash": _synthetic_hash(f"{dk}-{shard}"),
                "artifact_path": f"kb/v2026.11.10/{dk}/shard-{shard}.json",
                "pipeline_fingerprint": _synthetic_hash("pipeline-" + dk)[:32],
                "status": status, "built_at": now})


def _seed_governance(now, jg24, jg93):
    # 提案（RA1/RA2/RB1/RB3/RD1/RD2/RC1/RH1）
    proposals = [
        ("p-1", "RA1", "新增检查要素：敏感数据操作日志四要素", "pending", "lijb", None,
         {"checkCode": (jg24[0]["checkCode"] if jg24 else "15.5"),
          "element": "日志要素完备性", "evidence": "现场抽查 30 条日志缺 2 项"},
         "t-bank-2026q4"),
        ("p-2", "RA2", "登记新增文号：人民银行令〔2026〕第8号", "pending", "kbops", None,
         {"docKey": "pboc8", "docNo": "中国人民银行令〔2026〕第8号"}, "collect"),
        ("p-3", "RB1", "修订检查项描述：13.3 数据销毁", "approved", "zhangjb", "kbops",
         {"checkCode": (jg24[3]["checkCode"] if len(jg24) > 3 else "13.3"),
          "old": "数据销毁管理制度", "new": "数据销毁管理制度（含介质报废）"}, "t-bank-2026q3"),
        ("p-4", "RB3", "责任映射调整：日志审计改由复核岗负责", "pending", "lijb", None,
         {"checkCode": "15.5", "roleId": "l1_review"}, "t-bank-2026q4"),
        ("p-5", "RD1", "新增证据要求：终端外设管控配置快照", "rejected", "zhaogui", "fengsh",
         {"checkCode": "15.11", "evidence": "外设管控配置快照"}, "t-bank-east1-2026q4"),
        ("p-6", "RD2", "调整度量阈值：日志留存不少于 6 个月", "pending", "lijb", None,
         {"checkCode": "15.5", "metric": "日志留存时长", "old": "3 个月", "new": "6 个月"},
         "t-bank-2026q4"),
        ("p-7", "RC1", "控制缺口补齐：数据销毁控制项", "approved", "zhangjb", "kbops",
         {"control": "ctrl-destroy", "gap": "O6 无对应控制"}, "t-bank-2026q3"),
        ("p-8", "RH1", "人工确认规则：置信度 < 0.6 一律转人工", "pending", "kbops", None,
         {"rule": "置信度 < 0.6 → 转人工", "scope": "AI 匹配"}, "governance"),
        ("p-9", "RA1", "新增检查要素：跨境数据流动标识", "approved", "inswu", "kbops",
         {"checkCode": "12.6", "element": "跨境标识"}, "t-ins-2026q4"),
        # ---- 补齐 14 类回流类目（RA3/RB2/RB4/RB5/RC2/RD3）----
        ("p-10", "RA3", "补充判定要点：日志留存时长以最近一次审计为准", "pending", "wangzong", None,
         {"checkCode": "15.5", "keyPoint": "留存时长以最近一次审计报告为准"}, "t-bank-2026q4"),
        ("p-11", "RB2", "条线归属调整：开放银行专项归入“开放银行”条线", "pending", "lijb", None,
         {"checkCode": "12.6", "fromLine": "acct", "toLine": "openbank"}, "t-bank-2026q4"),
        ("p-12", "RB4", "关联关系修正：数据销毁 ↔ 介质报废 建立关联边", "approved", "fengsh", "kbops",
         {"from": "ctrl-destroy", "to": "ctrl-media-dispose", "edge": "relatedTo"}, "t-bank-2026q3"),
        ("p-13", "RB5", "控制措施映射：敏感数据识别 → 分级分类控制项", "pending", "sunjc", None,
         {"control": "ctrl-classify", "mapsTo": "O4"}, "t-ins-2026q4"),
        ("p-14", "RC2", "条款失效：旧版《数据安全指引》第 12 条已废止", "rejected", "hantq", "kbops",
         {"docKey": "jf8", "clause": "12", "reason": "被新文号替代"}, "collect"),
        ("p-15", "RD3", "访谈问题沉淀：新增“外包人员数据访问审批”访谈题", "pending", "zhaogui", None,
         {"checkCode": "15.11", "interview": "外包人员数据访问是否留审批痕迹"}, "t-bank-east1-2026q4"),
    ]
    for pid, cat, title, st, by, reviewer, payload, src in proposals:
        store.insert("knowledge_proposal", {
            "proposal_id": pid, "category": cat, "title": title,
            "payload_json": json.dumps(payload, ensure_ascii=False), "raised_from": src,
            "status": st, "raised_by": by, "reviewed_by": reviewer,
            "review_comment": "演示：已审阅" if reviewer else None,
            "created_at": now, "decided_at": now if reviewer else None})

    # 人工确认候选（≥5）
    hitl = [
        ("h-1", "extraction", "doc-x1", (jg24[0]["checkCode"] if jg24 else "15.5"),
         "抽取候选：操作日志要素缺失", 0.52, "pending", "fengsh"),
        ("h-2", "ai_match", "t-ins-2026q4", (jg93[0]["checkCode"] if jg93 else "93-3.1"),
         "AI 匹配：制度条文与检查项弱相关", 0.48, "pending", None),
        ("h-3", "manual_judge", "t-bank-2026q3", "15.8", "人工判定：明文展示确认",
         0.71, "approved", "lifh"),
        ("h-4", "ai_match", "t-bank-2026q4", "16.4", "AI 匹配：测试环境隔离证据不足",
         0.35, "pending", None),
        ("h-5", "extraction", "doc-x2", "11.2", "抽取候选：委托处理合同六要素",
         0.83, "approved", "fengsh"),
        ("h-6", "manual_judge", "t-bank-east1-2026q4", "15.11", "人工判定：外设管控未落实",
         0.60, "rejected", "fengsh"),
    ]
    for cid, stype, sid, code, title, conf, st, rev in hitl:
        store.insert("hitl_candidate", {
            "candidate_id": cid, "source_type": stype, "source_id": sid, "check_code": code,
            "title": title, "confidence": conf, "status": st, "assigned_reviewer": rev,
            "payload_json": json.dumps({"note": "演示数据"}, ensure_ascii=False),
            "created_at": now, "decided_at": now if st != "pending" else None})

    # 采集任务（≥4）
    collects = [
        ("ct-1", "数据出境安全评估办法（征求意见稿）", "https://example.gov.cn/pboc8-draft",
         "中国人民银行", "regulation", "2026-09-15", "pending", 0.72, None),
        ("ct-2", "人工智能安全治理框架 2.0", "https://example.gov.cn/ai-framework",
         "国家网信办", "guideline", "2026-08-20", "approved", 0.88, "p-2"),
        ("ct-3", "银行业数据分类分级指引（更新）", "https://example.gov.cn/bank-cls",
         "国家金融监督管理总局", "guideline", "2026-07-11", "approved", 0.91, "p-1"),
        ("ct-4", "个人信息保护合规审计管理办法要点", "https://example.gov.cn/pipl-audit",
         "国家网信办", "notice", "2026-06-30", "pending", 0.66, None),
        ("ct-5", "金融数据安全 数据生命周期安全规范（报批稿）", "https://example.gov.cn/jr-t",
         "中国人民银行", "standard", "2026-05-18", "pending", 0.58, None),
    ]
    for cid, title, url, body, ctype, pdate, st, cred, pid in collects:
        store.insert("collect_task", {
            "collect_id": cid, "title": title, "source_url": url, "issuing_body": body,
            "content_type": ctype, "publish_date": pdate, "collected_at": now,
            "status": st, "credibility": cred, "proposal_id": pid})


def _seed_plugins_scenarios(now):
    plugins = [
        ("pl-grading", "数据分级插件", "grading", "在线", 120),
        ("pl-class", "数据分类插件", "classification", "在线", 140),
        ("pl-mask", "脱敏插件", "masking", "在线", 90),
        ("pl-scan", "敏感数据识别插件", "scan", "降级", 800),
        ("pl-watermark", "水印插件", "watermark", "在线", 110),
    ]
    for pid, name, cap, status, lat in plugins:
        store.insert("plugin_registry", {
            "plugin_id": pid, "name": name, "capability": cap,
            "io_schema_json": json.dumps({"input": {"type": "object"}, "output": {"type": "object"}},
                                         ensure_ascii=False),
            "auth_type": "bearer", "rate_limit": "600/min", "status": status,
            "vendor": "平台自研" if status == "在线" else "第三方（离线）",
            "latency_ms": lat})
    # 插件调用记录（≥3）
    for i, (pid, st, lat) in enumerate([("pl-grading", "ok", 118), ("pl-class", "ok", 142),
                                        ("pl-scan", "degraded", 800), ("pl-mask", "ok", 88)]):
        store.insert("plugin_invocation", {
            "invocation_id": f"inv-{i+1}", "plugin_id": pid, "task_id": "t-bank-2026q4",
            "input_ref": f"demo://input/{pid}-{i+1}", "output_ref": f"demo://output/{pid}-{i+1}",
            "status": st, "latency_ms": lat, "actor": "lijb", "created_at": now})

    # 场景包作为「平台扩展场景」平铺呈现：新增场景只加包、不改底座。
    scenarios = [
        ("sp-selfcheck", "企业安全自查", "bank", "active",
         {"lines": ["acct", "credit"], "docs": ["jg24"]}, 1,
         "bank-selfcheck-v1"),
        ("sp-report", "监管报送辅助", "bank", "active",
         {"reports": ["重要数据目录", "季度报送"]}, 0, "bank-report-v1"),
        ("sp-itgrading", "信息科技评级治理", "bank", "active",
         {"domains": ["治理", "技术", "外包"]}, 0, "it-grading-v1"),
        ("sp-dsra", "数据安全风险评估（DSRA）", "insurance", "active",
         {"scope": ["理赔", "保全"]}, 0, "dsra-v1"),
        ("sp-rating", "监管评级（机构评级）", "bank", "active",
         {"domains": ["治理", "指标", "举证"]}, 0, "bank-rating-v1"),
        ("sp-compliance", "等保／密评／关基保护自评估", "bank", "active",
         {"domains": ["等保", "密评", "关基保护"]}, 0, "bank-compliance-v1"),
        ("sp-pipl", "个人信息保护合规审计", "insurance", "active",
         {"scope": ["采集", "共享", "委托处理"]}, 0, "insurance-pipl-v1"),
        ("sp-vendor", "供应商／外包数据安全尽调", "insurance", "active",
         {"scope": ["准入", "监控", "退出"]}, 0, "insurance-vendor-v1"),
    ]
    for pid, name, ind, st, scope, builtin, tpl in scenarios:
        store.insert("scenario_pack", {
            "pack_id": pid, "name": name, "industry": ind, "status": st,
            "scope_json": json.dumps(scope, ensure_ascii=False),
            "mapping_json": json.dumps({"checkSource": "jg24", "lineMap": {}}, ensure_ascii=False),
            "form_json": json.dumps({"fields": ["orgName", "cycle", "topic"]}, ensure_ascii=False),
            "report_template": tpl, "builtin": builtin})


def _seed_extended(now: str) -> None:
    """第八轮：8 个扩展视图功能化的作业种子（让页面一进入就有在办状态）。"""

    # —— 闭合链在办案件 ——
    for i, case in enumerate(FRAME_SEED_CASES, start=1):
        cid = f"fc-{i}"
        cur = max(r[0] for r in case["rings"]) + 1
        store.insert("frame_chain_case", {
            "case_id": cid, "title": case["title"], "issue_no": case["issue_no"],
            "status": "in_progress", "current_ring": cur, "owner": "admin",
            "created_by": "admin", "created_at": now, "updated_at": now})
        for ring_no, ring_name, output, evidence in case["rings"]:
            store.insert("frame_ring_record", {
                "record_id": f"fr-{cid}-{ring_no}", "case_id": cid, "ring_no": ring_no,
                "ring_name": ring_name, "output": output, "evidence": evidence,
                "operator": "admin", "created_at": now})

    # —— 现状诊断在填批次（后三个维度证据说明留空，用于演示提交校验）——
    aid = "da-1"
    store.insert("diag_assessment", {
        "assessment_id": aid, "title": DIAG_SEED_TITLE, "status": "draft",
        "owner": "admin", "created_by": "admin", "created_at": now,
        "updated_at": now, "submitted_at": None})
    for d in DIAG_DIMENSIONS:
        for k, a in enumerate(d["answers"], start=1):
            ev = "已归集沟通、派单与复核记录（演示材料）" if d["no"] in DIAG_SEED_EVIDENCE_FILLED else ""
            store.insert("diag_answer", {
                "answer_id": f"ans-{aid}-{d['no']}-{k}", "assessment_id": aid,
                "dim_no": d["no"], "dim_name": d["name"], "q": a["q"],
                "state": a["state"], "note": d["note"], "evidence": ev, "updated_at": now})

    # —— 应用与业务层台账 ——
    for i, r in enumerate(LEDGER_ROWS, start=1):
        store.insert("ledger_row", {
            "row_id": f"lr-{i}", "scene": r["scene"], "level": r["level"],
            "should": r["should"], "actual": r["actual"], "result": r["result"],
            "owner": "admin", "created_by": "admin", "created_at": now, "updated_at": now})

    # —— 逐类问题处置工单 ——
    issue_by_no = {c["no"]: c for c in ISSUE_CLASSES}
    for i, d in enumerate(ISSUE_SEED_DISPOSALS, start=1):
        c = issue_by_no.get(d["issue_no"], {})
        store.insert("issue_disposal", {
            "disposal_id": f"disp-{i}", "issue_no": d["issue_no"],
            "issue_name": c.get("name", ""), "layer": c.get("layer", ""),
            "status": d["status"], "org_name": d["org_name"], "position": d["position"],
            "plan": d["plan"], "evidence": "", "owner": "admin", "created_by": "admin",
            "created_at": now, "updated_at": now, "closed_at": None})


def _seed_audit(now):
    base = datetime.datetime.fromisoformat(now)
    entries = [
        ("admin", "系统管理员（演示）", "auth.login", "session", {"ip": "10.0.0.10"}, "ok"),
        ("admin", "系统管理员（演示）", "role.update", "角色：L1 复核", {"capabilities": 6}, "ok"),
        ("kbops", "刘运营（演示）", "kb.publish", "run-20261110", {"mode": "incremental"}, "ok"),
        ("kbops", "刘运营（演示）", "kb.fetch", "checks:jg24", {"n": 116}, "ok"),
        ("kbops", "刘运营（演示）", "kb.collect.run", "collect", {"new": 2}, "ok"),
        ("kbops", "刘运营（演示）", "kb.rollback", "v2026.11.05", {"ok": True}, "ok"),
        ("wangzong", "王总（演示）", "selfcheck.create", "t-bank-2026q4", {"industry": "bank"}, "ok"),
        ("chenzong", "陈总（演示）", "selfcheck.report", "t-bank-2026q3", {"fmt": "json"}, "ok"),
        ("lijb", "李经办（演示）", "selfcheck.item.update", "t-bank-2026q4#15.5", {"status": "fail"}, "ok"),
        ("lijb", "李经办（演示）", "assignment.preview", "t-bank-2026q4", {"coverage": 87.5}, "ok"),
        ("lijb", "李经办（演示）", "assignment.dispatch", "batch-t-bank-2026q4-1", {"n": 8}, "ok"),
        ("lifh", "李复核（演示）", "selfcheck.signoff", "t-bank-2026q3", {"decision": "approve"}, "ok"),
        ("fengsh", "冯审查（演示）", "review.decision", "p-5", {"decision": "reject"}, "ok"),
        ("zhangjb", "张经办（演示）", "finding.create", "f-7", {"severity": "high"}, "ok"),
        ("zhangjb", "张经办（演示）", "remediation.update", "rem-2", {"status": "done"}, "ok"),
        ("lijb", "李经办（演示）", "recheck.run", "t-bank-2026q3", {"runType": "recheck"}, "ok"),
        ("kbops", "刘运营（演示）", "admin.doc.register", "pboc8", {"status": "pending"}, "ok"),
        ("admin", "系统管理员（演示）", "admin.user.status", "hantq", {"status": "disabled"}, "ok"),
        ("admin", "系统管理员（演示）", "plugin.invoke", "pl-scan", {"status": "degraded"}, "degraded"),
        ("lijb", "李经办（演示）", "plugin.invoke", "pl-grading", {"status": "ok"}, "ok"),
        ("sunjc", "孙检查（演示）", "selfcheck.view", "t-bank-2026q4", {}, "ok"),
        ("kbops", "刘运营（演示）", "review.proposal", "p-3", {"decision": "approve"}, "ok"),
        ("lijb", "李经办（演示）", "evidence.upload", "ev-t1-1", {"size": 245678}, "ok"),
        ("lifh", "李复核（演示）", "hitl.decide", "h-3", {"decision": "approve"}, "ok"),
        ("admin", "系统管理员（演示）", "gov.issue.create", "GY-2026-001", {"severity": "high"}, "ok"),
        ("admin", "系统管理员（演示）", "gov.issue.triage", "GY-2026-001", {"category": "资产层"}, "ok"),
        ("admin", "系统管理员（演示）", "gov.issue.dispatch", "GY-2026-001", {"dept": "数据管理部"}, "ok"),
        ("admin", "系统管理员（演示）", "frame.ring.record", "fc-1", {"ringNo": 3}, "ok"),
        ("admin", "系统管理员（演示）", "diag.answer.save", "da-1", {"dimNo": 1}, "ok"),
        ("admin", "系统管理员（演示）", "diag.generate", "da-1", {"inputs": 4}, "ok"),
        ("admin", "系统管理员（演示）", "asset.create", "中国银联接口清单", {"category": "接口清单"}, "ok"),
        ("kbops", "刘运营（演示）", "kb.doc.publish", "数据分类分级操作指引", {"kb": "内部制度知识库"}, "ok"),
        ("kbops", "刘运营（演示）", "asset.kb.upload", "数据安全管理办法", {"kb": "内部制度知识库"}, "ok"),
    ]
    # 复制一轮并逐条错开时间，凑足 ≥60 条（真实感）
    all_rows = []
    for rep in range(3):
        for actor, name, action, target, params, result in entries:
            all_rows.append((actor, name, action, target, params, result))
    for i, (actor, name, action, target, params, result) in enumerate(all_rows):
        ts = (base - datetime.timedelta(minutes=(len(all_rows) - i) * 7)).isoformat(timespec="seconds")
        store.write_audit(actor, action, target, params, result=result, actor_name=name, ts=ts)


# ===========================================================================
# 第九轮：闭环工作流 / 知识发布治理 / 资产台账 / 插件治理 / 权限精细化
# ===========================================================================
# 权限菜单目录（与左侧功能菜单一一对应；菜单键保持机器可读）
MENU_CATALOG = [
    ("selfcheck", "合规自查"), ("dsc", "安全自查"), ("rep", "报告与看板"),
    ("diag", "现状诊断"), ("ledger", "资产台账"), ("issues", "安全治理"),
    ("kbdash", "知识库"), ("pipeline", "知识发布"),
    ("scenario", "场景包"), ("plugin", "工具插件"),
    ("gov", "权限与组织"), ("dsk", "运行驾驶舱"), ("frame", "治理框架"),
]

# 角色 → 可见菜单（其余角色未列出的菜单默认不可见）
ROLE_MENUS = {
    "sys_admin": [m[0] for m in MENU_CATALOG],
    "kb_ops": ["kbdash", "pipeline", "scenario", "plugin", "dsk"],
    "l0_lead": ["selfcheck", "dsc", "rep", "diag", "ledger", "issues", "dsk"],
    "l1_handle": ["dsc", "rep", "issues", "ledger", "kbdash"],
    "l1_review": ["dsc", "rep", "issues", "ledger"],
    "l2_handle": ["dsc", "rep", "issues"],
    "l3_exec": ["dsc", "rep"],
    "manager": ["rep", "dsk", "diag"],
}
# 角色 → 数据可见范围（ALL 全部 / ORG_AND_CHILD 本级及下级 / ORG_ONLY 本级 / SELF 本人）
ROLE_DATA_SCOPE = {
    "sys_admin": "ALL", "kb_ops": "ALL", "l0_lead": "ORG_AND_CHILD",
    "l1_handle": "ORG_AND_CHILD", "l1_review": "ORG_AND_CHILD",
    "l2_handle": "ORG_ONLY", "l3_exec": "SELF", "manager": "ORG_AND_CHILD",
}

# 插件默认配置（config 键值随能力而异；schema 由后端按能力给出）
_PLUGIN_SEEDS = [
    ("pl-grading", "grading", 1, "builtin",
     {"levels": "四级（核心/重要/敏感/内部）", "defaultLevel": "内部", "autoApply": True}),
    ("pl-class", "classification", 1, "builtin",
     {"taxonomy": "行业数据分类目录", "minConfidence": 0.75, "reviewLowConfidence": True}),
    ("pl-mask", "masking", 1, "builtin",
     {"algorithm": "掩码（保留首尾）", "fields": "证件号、手机号、银行卡号", "reversible": False}),
    ("pl-scan", "scan", 1, "builtin",
     {"ruleset": "行业敏感数据识别规则集", "deepScan": True, "timeout": 30}),
    ("pl-watermark", "watermark", 1, "builtin",
     {"text": "内部资料·仅限授权使用", "opacity": 0.18, "tile": True}),
    ("pl-ocr", "ocr", 1, "builtin",
     {"lang": "中文（简体）", "layout": True, "tableExtract": True}),
    ("pl-dlp", "dlp", 0, "uploaded",
     {"channel": "邮件、终端外发", "action": "告警并留痕", "whitelist": "已授权报送通道"}),
]

# 安全治理闭环工单（多角色、多部门流转）
_GOV_ISSUES = [
    ("gv-1", "GY-2026-001", "数据分类分级覆盖不完整", "自查发现", "资产层", "high",
     "bank-hq", "数据管理部", "pos-datagov", "数据治理岗", "pending_confirm",
     "2026-12-05", "补齐数据分类分级目录，覆盖核心与重要数据", "已复检，判定通过"),
    ("gv-2", "GY-2026-002", "重要数据目录未与责任矩阵对齐", "监管检查", "治理层", "high",
     "bank-hq", "风险管理部", "pos-risk", "风险管理岗", "rechecking",
     "2026-12-10", "重排重要数据目录与责任矩阵映射，明确到岗", ""),
    ("gv-3", "GY-2026-003", "数据共享审批留痕不完整", "内部审计", "流程层", "medium",
     "bank-acct", "零售业务部", "pos-acct", "业务经办岗", "remediating",
     "2026-12-15", "补齐数据共享审批流转记录，统一留痕口径", ""),
    ("gv-4", "GY-2026-004", "离职账号回收不及时", "自查发现", "技术层", "medium",
     "bank-hq", "信息科技部", "pos-ops", "运维岗", "dispatched",
     "2026-12-18", "建立离职即时停用与定期复核机制", ""),
    ("gv-5", "GY-2026-005", "敏感数据外发未脱敏", "事件驱动", "技术层", "high",
     "bank-credit", "信贷管理部", "pos-credit", "信贷管理岗", "closed",
     "2026-11-20", "外发通道强制脱敏并留痕", "已复检，判定通过"),
    ("gv-6", "GY-2026-006", "外包人员数据访问权限过宽", "自查发现", "治理层", "medium",
     "bank-hq", "信息科技部", "pos-outsrc", "外包管理岗", "accepted",
     "2026-12-22", "按最小必要重排外包人员数据权限", ""),
]
# 工单流转记录（每一步动作与操作角色，体现多角色互动）
_GOV_TRANSITIONS = [
    ("gv-1", "open", "triaged", "triage", "admin", "系统管理员（演示）", "定级为高，归入资产层"),
    ("gv-1", "triaged", "dispatched", "dispatch", "admin", "系统管理员（演示）", "下发数据管理部"),
    ("gv-1", "dispatched", "accepted", "accept", "inszhou", "周总保（演示）", "数据管理部已接收"),
    ("gv-1", "accepted", "remediating", "start", "inszhou", "周总保（演示）", "启动整改"),
    ("gv-1", "remediating", "responded", "respond", "inszhou", "周总保（演示）", "提交整改回复与佐证"),
    ("gv-1", "responded", "rechecking", "recheck", "lifh", "李复核（演示）", "提交复检反馈"),
    ("gv-1", "rechecking", "pending_confirm", "confirm", "admin", "系统管理员（演示）", "待数据安全管理部门核查确认"),
    ("gv-2", "open", "triaged", "triage", "admin", "系统管理员（演示）", "定级为高，归入治理层"),
    ("gv-2", "triaged", "dispatched", "dispatch", "admin", "系统管理员（演示）", "下发风险管理部"),
    ("gv-2", "dispatched", "accepted", "accept", "fengsh", "冯审查（演示）", "风险管理部已接收"),
    ("gv-2", "accepted", "remediating", "start", "fengsh", "冯审查（演示）", "启动整改"),
    ("gv-2", "remediating", "responded", "respond", "fengsh", "冯审查（演示）", "提交整改回复"),
    ("gv-2", "responded", "rechecking", "recheck", "admin", "系统管理员（演示）", "复检中，核对映射台账"),
    ("gv-3", "open", "triaged", "triage", "admin", "系统管理员（演示）", "定级为中，归入流程层"),
    ("gv-3", "triaged", "dispatched", "dispatch", "admin", "系统管理员（演示）", "下发零售业务部"),
    ("gv-3", "dispatched", "accepted", "accept", "zhaogui", "赵柜员（演示）", "零售业务部已接收"),
    ("gv-3", "accepted", "remediating", "start", "zhaogui", "赵柜员（演示）", "启动整改"),
    ("gv-4", "open", "triaged", "triage", "admin", "系统管理员（演示）", "定级为中，归入技术层"),
    ("gv-4", "triaged", "dispatched", "dispatch", "admin", "系统管理员（演示）", "下发信息科技部"),
    ("gv-5", "open", "triaged", "triage", "admin", "系统管理员（演示）", "定级为高，归入技术层"),
    ("gv-5", "triaged", "dispatched", "dispatch", "admin", "系统管理员（演示）", "下发信贷管理部"),
    ("gv-5", "dispatched", "accepted", "accept", "zhangjb", "张经办（演示）", "信贷管理部已接收"),
    ("gv-5", "accepted", "remediating", "start", "zhangjb", "张经办（演示）", "启动整改"),
    ("gv-5", "remediating", "responded", "respond", "zhangjb", "张经办（演示）", "提交整改回复与佐证"),
    ("gv-5", "responded", "rechecking", "recheck", "lifh", "李复核（演示）", "提交复检反馈"),
    ("gv-5", "rechecking", "pending_confirm", "confirm", "admin", "系统管理员（演示）", "提交核查确认"),
    ("gv-5", "pending_confirm", "closed", "close", "admin", "系统管理员（演示）", "确认整改完成，归档"),
    ("gv-6", "open", "triaged", "triage", "admin", "系统管理员（演示）", "定级为中，归入治理层"),
    ("gv-6", "triaged", "dispatched", "dispatch", "admin", "系统管理员（演示）", "下发信息科技部"),
    ("gv-6", "dispatched", "accepted", "accept", "kbops", "刘运营（演示）", "信息科技部已接收"),
]
_GOV_EVIDENCE = [
    ("gv-1", "整改回复", "分类分级目录（修订版）.pdf", "覆盖核心与重要数据共 86 项", "inszhou"),
    ("gv-1", "复检反馈", "复检记录-分类分级.xlsx", "抽查 20 项，判定与佐证一致", "lifh"),
    ("gv-2", "整改回复", "责任矩阵映射表.xlsx", "重排后的目录-责任映射", "fengsh"),
    ("gv-3", "整改回复", "共享审批流转记录.pdf", "近三个月审批留痕补齐", "zhaogui"),
    ("gv-5", "整改回复", "外发通道脱敏配置说明.pdf", "强制脱敏策略与留痕截图", "zhangjb"),
    ("gv-5", "复检反馈", "复检记录-外发脱敏.pdf", "抽测 10 条外发样本，均已脱敏", "lifh"),
]

# 目标知识库（对接后台知识库平台后同步得出）
_KB_TARGETS = [
    ("kt-reg", "监管法规知识库", "法规", 216),
    ("kt-inner", "内部制度知识库", "制度", 148),
    ("kt-case", "案例与检查知识库", "案例", 97),
]
# 知识文档（含审核状态与版本）
_KB_DOCS = [
    ("doc-1", "kt-inner", "数据安全管理办法", "制度", "manual", "v3", "published", "kbops"),
    ("doc-2", "kt-inner", "重要数据目录（2026版）", "目录", "auto", "v1", "pending_review", "kbops"),
    ("doc-3", "kt-reg", "银行保险数据安全办法要点解读", "解读", "auto", "v2", "published", "kbops"),
    ("doc-4", "kt-inner", "数据分类分级操作指引", "指引", "manual", "v1", "published", "lijb"),
    ("doc-5", "kt-case", "典型违规案例汇编", "案例", "manual", "v1", "published", "kbops"),
    ("doc-6", "kt-reg", "个人信息保护合规审计要点", "解读", "auto", "v1", "pending_review", "kbops"),
    ("doc-7", "kt-inner", "数据共享与委托处理规范", "制度", "manual", "v1", "draft", "lijb"),
]
_KB_REVIEWS = [
    ("doc-1", "fengsh", "冯审查（演示）", "approve", "内容准确，同意入库", "published"),
    ("doc-3", "fengsh", "冯审查（演示）", "approve", "与监管口径一致", "published"),
    ("doc-4", "fengsh", "冯审查（演示）", "approve", "分类分级口径清晰", "published"),
    ("doc-5", "fengsh", "冯审查（演示）", "approve", "案例已脱敏，同意入库", "published"),
    ("doc-6", "fengsh", "冯审查（演示）", "pending", "", "pending_review"),
]
_KB_CALLS = [
    ("doc-1", "lijb", "安全自查", "数据安全管理办法 责任分工"),
    ("doc-1", "fengsh", "现状诊断", "制度条款与证据要求"),
    ("doc-3", "wangzong", "安全自查", "数据分类分级监管要求"),
    ("doc-4", "lijb", "安全自查", "分类分级落地方法"),
    ("doc-5", "admin", "安全治理", "同类问题处置范例"),
    ("doc-2", "chenzong", "报告与看板", "重要数据目录口径"),
]

# 资产台账（应用资产 / 配置管理 / 制度办法 / 数据资产 / 接口清单）
_ASSET_SEED = [
    ("应用资产", "银行卡核心业务系统", "系统对接", "bank-hq", "信息科技部", "v2.4", "在册"),
    ("应用资产", "信贷管理系统", "系统对接", "bank-credit", "信贷管理部", "v3.1", "在册"),
    ("应用资产", "客户关系管理系统", "手工上传", "bank-acct", "零售业务部", "v1.8", "在册"),
    ("配置管理", "生产环境网络拓扑", "系统对接", "bank-hq", "信息科技部", "v5", "在册"),
    ("配置管理", "服务器与中间件清单", "系统对接", "bank-hq", "信息科技部", "v12", "在册"),
    ("数据资产", "重要数据目录", "手工上传", "bank-hq", "数据管理部", "v2", "在册"),
    ("数据资产", "客户主数据模型", "系统对接", "bank-hq", "数据管理部", "v4", "在册"),
    ("制度办法", "数据安全管理办法", "手工上传", "bank-hq", "数据管理部", "v3", "在册"),
    ("制度办法", "数据分类分级操作指引", "手工上传", "bank-hq", "数据管理部", "v1", "在册"),
    ("制度办法", "数据共享与委托处理规范", "手工上传", "bank-hq", "数据管理部", "v1", "待更新"),
    ("接口清单", "对外开放接口台账", "系统对接", "bank-open", "开放银行部", "v2", "在册"),
    ("接口清单", "第三方数据交互清单", "手工上传", "bank-hq", "信息科技部", "v1", "待更新"),
]

# 场最包扩展明细（知识来源 / 知识库 / 部门岗位角色 / 工具 / 系统 / 模板）
_SCENARIO_DETAIL = {
    "sp-selfcheck": ("知识库 + 内部制度", ["kt-inner", "kt-reg"],
                     ["数据管理部", "合规部"], ["数据治理岗", "合规审查岗"],
                     ["l1_handle", "l1_review"], ["数据分级插件", "敏感数据识别插件"],
                     ["数据资产目录", "自查管理"], ["自查报告模板（标准版）"]),
    "sp-report": ("监管法规", ["kt-reg"],
                  ["数据管理部"], ["数据治理岗"], ["l0_lead"],
                  ["数据分类插件"], ["报送管理"], ["监管报送模板"]),
    "sp-itgrading": ("内部制度 + 案例", ["kt-inner", "kt-case"],
                     ["信息科技部", "风险管理部"], ["运维岗", "风险管理岗"],
                     ["l1_handle", "manager"], ["数据分类插件"], ["配置管理", "运维审计"],
                     ["信息科技评级模板"]),
    "sp-dsra": ("监管法规 + 案例", ["kt-reg", "kt-case"],
                ["风险管理部", "理赔部"], ["风险管理岗", "业务经办岗"],
                ["l1_handle", "manager"], ["数据脱敏插件"], ["理赔系统"],
                ["数据安全风险评估模板"]),
    "sp-rating": ("监管法规", ["kt-reg"],
                  ["数据管理部", "风险管理部"], ["数据治理岗", "风险管理岗"],
                  ["l0_lead"], ["数据分级插件"], ["指标管理"], ["机构评级模板"]),
    "sp-compliance": ("监管法规 + 内部制度", ["kt-reg", "kt-inner"],
                      ["信息科技部", "数据管理部"], ["运维岗", "数据治理岗"],
                      ["l1_handle", "l1_review"], ["OCR 识别插件"], ["等保管理", "密评管理"],
                      ["等保自评估模板"]),
    "sp-pipl": ("监管法规", ["kt-reg"],
                ["合规部", "零售业务部"], ["合规审查岗", "业务经办岗"],
                ["l1_review", "manager"], ["数据脱敏插件"], ["个人信息管理"],
                ["合规审计模板"]),
    "sp-vendor": ("内部制度 + 案例", ["kt-inner", "kt-case"],
                  ["信息科技部", "合规部"], ["外包管理岗", "合规审查岗"],
                  ["l1_handle", "l1_review"], ["数据分类插件"], ["供应商管理"],
                  ["供应商尽调模板"]),
}


def _seed_round9(now: str) -> None:
    """第九轮作业种子：闭环工作流 / 知识发布治理 / 资产台账 / 插件治理 / 权限精细化。"""
    # —— 插件治理：注册 OCR / 防泄漏两个增量插件 + 逐插件启停与配置 ——
    for pid, name, cap, status, lat in [
            ("pl-ocr", "OCR 识别插件", "ocr", "在线", 260),
            ("pl-dlp", "数据防泄漏插件", "dlp", "降级", 640)]:
        store.insert("plugin_registry", {
            "plugin_id": pid, "name": name, "capability": cap,
            "io_schema_json": json.dumps({"input": {"type": "object"}, "output": {"type": "object"}},
                                         ensure_ascii=False),
            "auth_type": "bearer", "rate_limit": "600/min", "status": status,
            "vendor": "平台自研" if status == "在线" else "第三方（离线）", "latency_ms": lat})
    for pid, cap, enabled, kind, cfg in _PLUGIN_SEEDS:
        store.insert("plugin_setting", {
            "plugin_id": pid, "enabled": enabled, "kind": kind,
            "config_json": json.dumps(cfg, ensure_ascii=False),
            "config_schema_json": None, "loaded_at": now, "updated_by": "admin", "updated_at": now})

    # —— 安全治理闭环：工单 + 流转 + 证据 ——
    for (iid, no, title, source, cat, sev, dept_id, dept_name, pos_id, pos_name,
         status, due, plan, recheck) in _GOV_ISSUES:
        closed = now if status == "closed" else None
        store.insert("gov_issue", {
            "issue_id": iid, "issue_no": no, "title": title, "source": source, "category": cat,
            "severity": sev, "dept_id": dept_id, "dept_name": dept_name,
            "position_id": pos_id, "position_name": pos_name, "owner": "admin", "status": status,
            "due_date": due, "plan": plan, "recheck_result": recheck,
            "created_by": "admin", "created_at": now, "updated_at": now, "closed_at": closed})
    for i, (iid, frm, to, action, actor, name, comment) in enumerate(_GOV_TRANSITIONS, start=1):
        store.insert("gov_transition", {
            "transition_id": f"gt-{i}", "issue_id": iid, "from_status": frm, "to_status": to,
            "action": action, "actor": actor, "actor_name": name, "comment": comment,
            "created_at": now})
    for i, (iid, step, fname, note, by) in enumerate(_GOV_EVIDENCE, start=1):
        store.insert("gov_evidence", {
            "evidence_id": f"ge-{i}", "issue_id": iid, "step": step, "file_name": fname,
            "note": note, "uploaded_by": by, "uploaded_at": now})

    # —— 知识发布治理：目标库 / 文档 / 版本 / 变更 / 调用 / 审核 ——
    for kb_id, name, kind, cnt in _KB_TARGETS:
        store.insert("kb_target", {"kb_id": kb_id, "name": name, "kind": kind,
                                   "doc_count": cnt, "synced_at": now})
    for doc_id, kb_id, title, dtype, src, ver, status, by in _KB_DOCS:
        store.insert("kb_document", {
            "doc_id": doc_id, "kb_id": kb_id, "title": title, "doc_type": dtype, "source": src,
            "version": ver, "status": status, "owner": by, "uploaded_by": by,
            "created_at": now, "updated_at": now})
        store.insert("kb_doc_version", {
            "version_id": f"kv-{doc_id}-{ver}", "doc_id": doc_id, "version": ver,
            "content_hash": _synthetic_hash(f"{doc_id}|{ver}"), "note": "初始版本（演示）",
            "created_by": by, "created_at": now})
        store.insert("kb_change_log", {
            "change_id": f"kc-{doc_id}-1", "doc_id": doc_id, "change_type": "create",
            "summary": f"新建《{title}》", "actor": by, "created_at": now})
    for i, (doc_id, rev, revname, decision, comment, status) in enumerate(_KB_REVIEWS, start=1):
        store.insert("kb_review", {
            "review_id": f"kr-{i}", "doc_id": doc_id, "reviewer": rev, "reviewer_name": revname,
            "decision": decision, "comment": comment, "created_at": now,
            "decided_at": now if decision != "pending" else None})
    for i, (doc_id, caller, scene, query) in enumerate(_KB_CALLS, start=1):
        store.insert("kb_call_log", {
            "call_id": f"kl-{i}", "doc_id": doc_id, "caller": caller, "scene": scene,
            "query": query, "created_at": now})

    # —— 资产台账 ——
    for i, (cat, name, src, dept_id, dept_name, ver, status) in enumerate(_ASSET_SEED, start=1):
        store.insert("asset_record", {
            "asset_id": f"as-{i}", "name": name, "category": cat, "source": src,
            "dept_id": dept_id, "dept_name": dept_name, "owner": "admin", "version": ver,
            "status": status, "kb_doc_id": None, "note": "",
            "created_by": "admin", "created_at": now, "updated_at": now})

    # —— 场景包扩展明细 ——
    for pack_id, (ks, kbs, depts, positions, roles, tools, systems, templates) in _SCENARIO_DETAIL.items():
        store.insert("scenario_detail", {
            "pack_id": pack_id, "knowledge_source": ks,
            "kb_ids_json": json.dumps(kbs, ensure_ascii=False),
            "depts_json": json.dumps(depts, ensure_ascii=False),
            "positions_json": json.dumps(positions, ensure_ascii=False),
            "roles_json": json.dumps(roles, ensure_ascii=False),
            "tools_json": json.dumps(tools, ensure_ascii=False),
            "systems_json": json.dumps(systems, ensure_ascii=False),
            "templates_json": json.dumps(templates, ensure_ascii=False),
            "updated_by": "admin", "updated_at": now})

    # —— 权限精细化：角色-菜单操作权限 + 角色-数据权限 ——
    actions_all = json.dumps(["view", "create", "update", "delete", "approve", "export"],
                             ensure_ascii=False)
    for rid, menus in ROLE_MENUS.items():
        for mk in menus:
            acts = actions_all if rid == "sys_admin" else json.dumps(
                ["view"] + (["create", "update"] if rid in ("l0_lead", "l1_handle", "kb_ops") else []),
                ensure_ascii=False)
            store.insert("role_menu_perm", {
                "perm_id": f"rmp-{rid}-{mk}", "role_id": rid, "menu_key": mk, "actions_json": acts})
        st = ROLE_DATA_SCOPE.get(rid, "ORG_ONLY")
        store.insert("role_data_scope", {
            "scope_id": f"rds-{rid}", "role_id": rid, "scope_type": st,
            "scope_json": json.dumps({}, ensure_ascii=False), "updated_by": "admin",
            "updated_at": now})

    # —— 轻量单点登录配置 ——
    for k, v in [("enabled", True), ("protocol", "OIDC 授权码"),
                 ("issuer", "https://sso.demo.example.com/realms/datasec"),
                 ("clientId", "datasec-platform"), ("mapping", "账号由身份源的账号标识映射"),
                 ("syncMode", "定时同步 + 登录时即时更新"), ("jitProvision", True),
                 ("updatedBy", "admin"), ("updatedAt", now)]:
        store.insert("sso_config", {"k": k, "v": json.dumps(v, ensure_ascii=False)})

    # —— 现状诊断输入材料（历史自查报告 / 工作佐证 / 资产配置 / 资产清单）——
    for i, (kind, fname, note) in enumerate([
            ("历史自查报告", "2026Q3 银行自查报告.pdf", "上季度自查结论与问题清单"),
            ("工作佐证", "数据分类分级培训与宣贯记录.pdf", "责任分工宣贯留痕"),
            ("资产配置信息", "数据资产目录（导出）.xlsx", "含分级与责任人"),
            ("资产清单", "重要数据清单.xlsx", "重要数据项与责任部门")], start=1):
        store.insert("diag_input", {
            "input_id": f"din-{i}", "assessment_id": "da-1", "kind": kind, "file_name": fname,
            "note": note, "size": 180000 + i * 24000, "uploaded_by": "admin", "uploaded_at": now})
