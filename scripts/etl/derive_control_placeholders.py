# -*- coding: utf-8 -*-
"""
从 116 项金规24号检查结果（jg24-checks.json）推导"检查侧需要哪些控制"的语义占位目录，
并完成与 10_知识库工程 v1.5 权威控制编码（CT-<层码>-序号）的正式对齐。

【架构约束】控制(control)权威词汇与 CT-<层码>-序号 编码的唯一事实源在
  10_知识库工程 v1.5（data/control-codes.csv）。本脚本 **绝不自造 CT 编码、不并行控制词表**：
  - 能认领的：占位 → CT 码正式对齐（status=aligned，ct_code/ct_layer/id/title 从 CSV 回填）；
  - 认领不了的：保持需求缺口（status=gap），附补建反馈供 10 工程 v1.6 参考。

依赖：仅 Python 标准库（json/os/re/datetime/collections/csv）。
只读：jg24-checks.json、10_知识库工程/data/knowledge.json、10_知识库工程/data/control-codes.csv。
只写：本脚本 OUTPUT_JSON（幂等覆盖）。

复跑：python3 scripts/etl/derive_control_placeholders.py
"""

import json
import os
import re
from datetime import datetime, timezone, timedelta
from collections import Counter

BASE = "/Users/FYP/Documents/WorkSpace/OntoRegGov"
CHECKS_JSON = os.path.join(BASE, "data", "checks", "jg24-checks.json")
KB10_JSON = "/Users/FYP/Documents/@西北人的成长/20-Areas/信息安全/数据安全/10_知识库工程/data/knowledge.json"
CT_CODES_CSV = "/Users/FYP/Documents/@西北人的成长/20-Areas/信息安全/数据安全/10_知识库工程/data/control-codes.csv"
OUTPUT_JSON = os.path.join(BASE, "data", "checks", "control-placeholders.json")


def load_ct_codes(csv_path: str) -> dict:
    """读 v1.5 权威控制编码表 → {code: {id, title, layer}}；空表或缺列直接失败（防静默降级）。
    layer 列是英文全称（endpoint/management/network/protocol/service），统一映射为平台层码。"""
    import csv as _csv
    layer_map = {"endpoint": "EP", "management": "MGMT", "network": "NW",
                 "protocol": "PROTO", "service": "SVC"}
    out = {}
    with open(csv_path, encoding="utf-8", newline="") as f:
        for row in _csv.DictReader(f):
            code = (row.get("code") or "").strip()
            if not code:
                continue
            raw_layer = (row.get("layer") or "").strip()
            out[code] = {"id": (row.get("id") or "").strip(),
                         "title": (row.get("title") or "").strip(),
                         "layer": layer_map.get(raw_layer, raw_layer.upper()[:4])}
    assert out, f"control-codes.csv 为空或解析失败: {csv_path}"
    return out

# 10 工程 v1.5 正式对齐表：占位 hint → 权威 CT 编码。
# 【唯一事实源】data/control-codes.csv（10_知识库工程 v1.5，92 条）。本表不新增编码，
# 仅做"占位需求 ↔ v1.5 控制"的语义认领；CT 码/id/标题一律从 CSV 解析回填，脚本启动时全量校验。
# 判定口径：仅当与 v1.5 控制确为同一控制（或明确为其子场景）时对齐；拿不准一律保持缺口并反馈。
CT_ALIGN = {
    # ---- MGMT 管理 ----
    "governance_org_responsibility":   "CT-MGMT-002",  # 数据安全责任制与组织（三道防线）
    "accountability_disciplinary":     "CT-MGMT-021",  # 数据安全考核与问责
    "security_awareness_training":     "CT-MGMT-007",  # 数据安全意识与技能培训
    "data_security_policy_framework":  "CT-MGMT-004",  # 数据全生命周期安全管理制度
    "cross_business_rules":            "CT-MGMT-008",  # 外包与第三方服务商数据安全管理（外部引入/合作共享主落点）
    "classification_policy":           "CT-MGMT-003",  # 数据分类分级管理制度（流程）
    "data_catalog_inventory":          "CT-MGMT-018",  # 数据资产与介质管理制度
    "tiered_protection_matrix":        "CT-MGMT-001",  # 基于分类分级的差异化管控
    "aggregation_reclassification":    "CT-MGMT-003",  # 分类分级流程含"汇聚后级别重评估"
    "data_risk_assessment":            "CT-MGMT-020",  # 数据安全风险评估机制
    "audit_remediation_loop":          "CT-MGMT-015",  # 数据安全审计与自查整改
    "security_monitoring_ops":         "CT-SVC-023",   # 日志集中与安全审计关联（SIEM 平台侧，7×24监测载体）
    "incident_response_emergency":     "CT-MGMT-012",  # 数据安全应急响应预案与演练
    "vendor_supplier_risk":            "CT-MGMT-008",  # 外包与第三方服务商数据安全管理
    "processing_contract_terms":       "CT-MGMT-008",  # 委托处理合同条款属外包/第三方管理
    "processor_oversight_audit":       "CT-MGMT-008",  # 受托方监督属外包/第三方管理
    "privacy_notice_consent_pia":      "CT-MGMT-011",  # 个人信息保护合规制度
    "cross_border_transfer_assessment": "CT-MGMT-010", # 数据出境合规管理
    "data_transfer_deletion":          "CT-MGMT-019",  # 数据销毁与加密粉碎管理制度（转移终止删除落点）
    "retention_destruction_policy":    "CT-MGMT-019",  # 数据销毁与加密粉碎管理制度
    "sdlc_data_security":              "CT-SVC-010",   # 安全开发生命周期（SDL）
    "mlps_critical_system_compliance": "CT-MGMT-016",  # 网络安全等级保护工作机制（关基/密评机制另见 CT-MGMT-017）
    # ---- SVC 服务 ----
    "access_rights_lifecycle":         "CT-MGMT-005",  # 账号与权限申请审批流程（申请-审批-回收闭环）
    "privileged_access_management":    "CT-SVC-001",   # 特权访问管理（PAM）
    "data_access_audit_logging":       "CT-SVC-002",   # 数据库审计与访问控制（敏感操作审计/日志留存载体）
    "encryption_at_rest_key_mgmt":     "CT-SVC-016",   # 数据库存储加密（TDE/列加密）；密钥管理另涉 CT-SVC-025 KMS/HSM
    "masking_anonymization":           "CT-SVC-017",   # 动态脱敏与掩码服务
    "backup_recovery_dr":              "CT-SVC-024",   # 数据备份与可恢复性
    "bigdata_platform_hardening":      "CT-SVC-014",   # 数据库安全配置基线（数据平台加固类）
    # ---- NW 链路 ----
    "secure_data_transmission":        "CT-NW-012",    # 传输加密（TLS/IPsec 链路）
    "network_zone_boundary_protection": "CT-NW-001",   # 网络分区与安全域隔离
    "external_interaction_api_gateway": "CT-SVC-011",  # API 安全与 API 网关（统一外联平台落点）
    # ---- EP 端侧 ----
    "endpoint_dlp_media_control":      "CT-EP-005",    # 终端 DLP 数据防泄漏（USB/介质管控另见 CT-EP-007）
    "endpoint_edr_ransomware":         "CT-EP-003",    # EDR/XDR 与防病毒
    # ---- PROTO 协议 ----
    "api_lifecycle_security":          "CT-SVC-011",   # API 安全与 API 网关（API 全生命周期）
}

# 缺口反馈：v1.5 无语义对应控制 → 保持 gap，向 10 工程 v1.6 提补建建议（不造权威 CT 码）
GAP_FEEDBACK = {
    "collection_minimization": "建议 10 工程新增『数据收集管理』类控制（收集目的范围告知/超范围合规/最小字段）",
    "important_data_collection_approval": "建议 10 工程新增『行业重要数据识别与收集审批』控制",
    "data_sharing_governance": "建议 10 工程新增『数据共享集中管控』控制（共享台账/审批/四维评估）",
    "affiliate_data_firewall": "建议 10 工程新增『母子公司与跨主体流动管控』控制",
    "public_disclosure_approval": "建议 10 工程新增『对外公开披露审批』控制",
    "data_service_management": "建议 10 工程新增『企业级数据服务管理』控制（集中率/专职团队）",
    "ai_model_governance": "建议 10 工程新增『AI/模型全生命周期治理』控制（金规24号第十七条新增领域）",
    "production_data_extraction": "建议 10 工程新增『生产数据提取审批管控』控制",
    "test_prod_isolation": "建议 10 工程新增『测试与生产环境隔离』控制",
    "shared_security_components_platform": "建议 10 工程新增『统一安全组件服务平台』控制（IAM/脱敏/监测/日志组件化）",
    "collection_system_protection": "建议 10 工程新增『数据收集系统安全防护』控制（接口HTTPS/审计/可用性）",
    "physical_datacenter_security": "建议 10 工程新增『机房物理安全防护』控制（物理边界）",
    "consent_management_system": "建议 10 工程新增『同意管理系统』控制（告知/撤回/留痕平台侧）",
}

# ---------------------------------------------------------------------------
# 人工归纳的控制需求目录（粒度适中，去重聚合）。
# 每条：(control_name, code_hint, suggested_layer, control_type_hint, rationale, source_checks)
# suggested_layer: EP端侧 / NW链路 / SVC服务 / PROTO协议 / MGMT管理（建议，最终以 10 工程 v1.5 为准）
# ---------------------------------------------------------------------------
CATALOG = [
    # ===== 治理 / 管理 (MGMT) =====
    ("数据安全治理组织与责任体系", "governance_org_responsibility", "MGMT", "职责流程",
     "由 1.1~2.5 检查党委/董事会主体责任、第一/直接责任人、归口部门七项职责、科技/业务/三道防线职责及实际履职证据推导，需一套贯通四层的责任制度与运作机制。",
     ["1.1","1.2","1.3","1.4","1.5","1.6","1.7","2.1","2.2","2.3","2.4","2.5"]),
    ("违规问责与绩效考核机制", "accountability_disciplinary", "MGMT", "制度规范",
     "由 1.8 违规情形定义、责任追究条款与 1.9 问责流程运行、考核挂钩推导。",
     ["1.8","1.9"]),
    ("数据安全培训与文化建设", "security_awareness_training", "MGMT", "培训",
     "由 3.1 年度培训计划、3.2 全员培训覆盖率≥80%、考核与知晓率推导。",
     ["3.1","3.2"]),
    ("数据安全策略与制度体系", "data_security_policy_framework", "MGMT", "制度规范",
     "由 6.1 策略对标金规24号核心条款≥90%、6.2 管理办法覆盖全生命周期与责任分工推导。",
     ["6.1","6.2"]),
    ("外部引入/合作共享/出境实施细则", "cross_business_rules", "MGMT", "制度规范",
     "由 6.3 三类高敏外部场景（引入/共享/出境）均需可操作细则与合同条款推导。",
     ["6.3"]),
    ("数据分类分级制度与分级标准", "classification_policy", "MGMT", "制度规范",
     "由 4.1 分类分级制度、4.3 覆盖§17四类数据、4.4 四级标准映射、5.3 动态调整审批推导。",
     ["4.1","4.3","4.4","5.3"]),
    ("数据目录与资产登记/资产地图", "data_catalog_inventory", "MGMT", "证据留痕",
     "由 4.2 数据目录覆盖率、5.1 目录动态维护、7.1 企业级数据架构/资产地图、15.1 影子数据排查推导。",
     ["4.2","5.1","7.1","15.1"]),
    ("差异化分级保护策略矩阵", "tiered_protection_matrix", "MGMT", "制度规范",
     "由 5.2 按级别配置加密/脱敏/访问/导出/销毁≥5维矩阵、7.2 保护与分级结果挂钩、14.1 技术保护体系按数据等级覆盖（核心100%/重要≥90%）推导。",
     ["5.2","7.2","14.1"]),
    ("数据汇聚后级别重评估", "aggregation_reclassification", "MGMT", "风险评估",
     "由 9.2 汇聚场景级别重评、15.3 多源汇聚加强措施推导。",
     ["9.2","15.3"]),
    ("数据安全风险评估", "data_risk_assessment", "MGMT", "风险评估",
     "由 7.3 涉敏业务活动评估、21.3 年度风险评估覆盖核心资产推导。",
     ["7.3","21.3"]),
    ("年度审计与整改闭环", "audit_remediation_loop", "MGMT", "监测审计",
     "由 1.7/2.4 三道防线审计、21.3 年度+三年周期全面审计、整改闭环率与 21.4 审计独立性推导。",
     ["1.7","2.4","21.3","21.4"]),
    ("数据安全监测告警运营", "security_monitoring_ops", "MGMT", "监测审计",
     "由 21.1 7×24监测组织与报告时限、21.2 监测覆盖率与告警闭环（高危≤1h）推导。",
     ["21.1","21.2"]),
    ("应急响应与事件分级演练", "incident_response_emergency", "MGMT", "应急与整改",
     "由 22.1 事件四级分级、22.2 应急体系与8小时上报、22.3 预案演练、17.8 AI威胁应急推导。",
     ["22.1","22.2","22.3","17.8"]),
    ("数据收集最小必要与清单", "collection_minimization", "MGMT", "制度规范",
     "由 8.1 收集目的方式范围告知、8.2 超范围收集/SDK合规、19.2 个人信息最小字段推导。",
     ["8.1","8.2","19.2"]),
    ("行业重要数据识别与收集审批", "important_data_collection_approval", "MGMT", "制度规范",
     "由 8.3 行业重要数据识别与总局同意审批推导。",
     ["8.3"]),
    ("供应商与外包风险管理", "vendor_supplier_risk", "MGMT", "供应商管理",
     "由 8.5/8.6 外部数据采购集中审批与供应商准入复评、11.5 委托纳入外包与集中度、11.6 供应链敏感数据准入推导。",
     ["8.5","8.6","11.5","11.6"]),
    ("委托处理合同条款管理", "processing_contract_terms", "MGMT", "合同/法律",
     "由 11.1/11.2 合同六要素、11.4 受托方三不得、20.5 个保合同六要素推导。",
     ["11.1","11.2","11.4","20.5"]),
    ("受托方与共同处理监督", "processor_oversight_audit", "MGMT", "供应商管理",
     "由 11.3 委托处理记录与年度审计、11.7 共同处理最小授权、20.6 受托人定期审查推导。",
     ["11.3","11.7","20.6"]),
    ("数据共享集中管控", "data_sharing_governance", "MGMT", "制度规范",
     "由 10.1 共享台账与审批/加密/脱敏、10.2 共享必要性合规安全伦理四维评估推导。",
     ["10.1","10.2"]),
    ("母子公司与跨主体流动管控", "affiliate_data_firewall", "MGMT", "制度规范",
     "由 10.3 母子公司数据隔离审批、12.4 核心数据跨主体评估审查、20.3 共享第三方名单告知推导。",
     ["10.3","12.4","20.3"]),
    ("个人信息告知同意与PIA合规", "privacy_notice_consent_pia", "MGMT", "制度规范",
     "由 19.3 完整告知、19.4 处理规则公开、20.1 撤回同意即停处理、20.2 PIA、10.4 拒绝同意不拒服务推导。",
     ["19.3","19.4","20.1","20.2","10.4"]),
    ("对外公开披露审批", "public_disclosure_approval", "MGMT", "制度规范",
     "由 12.5 公开披露审批、安全评估与台账推导。",
     ["12.5"]),
    ("数据出境安全评估", "cross_border_transfer_assessment", "MGMT", "风险评估",
     "由 12.6 跨境安全评估与持续监控、20.4 跨境告知与行权方式推导。",
     ["12.6","20.4"]),
    ("数据转移与终止删除", "data_transfer_deletion", "MGMT", "证据留痕",
     "由 12.1 合并分立解散转移协议与验证、13.4 委托终止删除与现场核查推导。",
     ["12.1","13.4"]),
    ("数据保留期限与销毁制度", "retention_destruction_policy", "MGMT", "制度规范",
     "由 13.3 销毁条件/流程/方法/记录、15.10 到期数据删除超期占比0%推导。",
     ["13.3","15.10"]),
    ("企业级数据服务管理", "data_service_management", "MGMT", "职责流程",
     "由 7.4 数据服务集中率≥70%、专职团队与响应时效推导。",
     ["7.4"]),
    ("AI/模型全生命周期治理", "ai_model_governance", "MGMT", "制度规范",
     "由 17.1/17.5/20.9 算法公平可解释与申诉、17.2 模型准入、17.3 版本可追溯、17.6 模型监测、17.7 退出缓释、20.8 训练数据脱敏、17.4 投用前审查推导。",
     ["17.1","17.2","17.3","17.4","17.5","17.6","17.7","20.8","20.9"]),
    ("SDLC数据安全左移", "sdlc_data_security", "MGMT", "职责流程",
     "由 1.5 技术全生命周期职责、14.2 SDLC数据安全章节、16.2 需求安全章节、16.3 投产前安全测试推导。",
     ["1.5","14.2","16.2","16.3"]),
    ("等保关基密评合规", "mlps_critical_system_compliance", "MGMT", "合规",
     "由 9.5 互联网系统等保/关基/密评、14.3 等保纳入数据安全控制项推导。",
     ["9.5","14.3"]),

    # ===== 服务 (SVC) =====
    ("数据访问权限生命周期管理", "access_rights_lifecycle", "SVC", "访问控制",
     "由 9.3 权限申请-审批-回收闭环与年度复核、15.4 RBAC/ABAC最小权限与离职回收≤1工作日推导。",
     ["9.3","15.4"]),
    ("特权账号高权访问管控(PAM)", "privileged_access_management", "SVC", "访问控制",
     "由 15.4 特权账号额外管控、高权账号≤必要最小推导。",
     ["15.4"]),
    ("敏感数据操作审计日志留存", "data_access_audit_logging", "SVC", "监测审计",
     "由 9.3 访问审计、15.5 日志四要素/核心数据留存≥3年/防篡改/半年审计、11.3 委托行为审计推导。",
     ["9.3","15.5","11.3"]),
    ("敏感数据加密存储与密钥管理", "encryption_at_rest_key_mgmt", "SVC", "加密与脱敏",
     "由 15.7 敏感字段加密存储/密钥管理、15.8 密码哈希加盐与敏感字段加密、13.1 备份加密推导。",
     ["15.7","15.8","13.1"]),
    ("数据脱敏与匿名化", "masking_anonymization", "SVC", "加密与脱敏",
     "由 9.1 加工脱敏规则覆盖与效果验证、15.8 页面/API/日志脱敏、16.4 测试数据脱敏、20.8 训练数据脱敏推导。",
     ["9.1","15.8","16.4","20.8"]),
    ("备份容灾与恢复演练", "backup_recovery_dr", "SVC", "应急与整改",
     "由 13.1 备份隔离加密、13.2 备份验证、15.9 容灾RPO/RTO与年度恢复演练推导。",
     ["13.1","13.2","15.9"]),
    ("生产数据提取审批管控", "production_data_extraction", "SVC", "访问控制",
     "由 9.4 生产数据提取审批、用途期限、到期7天内清理推导。",
     ["9.4"]),
    ("测试与生产环境隔离", "test_prod_isolation", "SVC", "技术配置",
     "由 16.4 测试环境网络隔离、开发不可访问生产、测试数据脱敏推导。",
     ["16.4"]),
    ("统一安全组件服务平台", "shared_security_components_platform", "SVC", "技术配置",
     "由 16.1 统一IAM/脱敏组件/行为监测/集中日志审计可被业务调用推导。",
     ["16.1"]),
    ("大数据平台加固与细粒度授权", "bigdata_platform_hardening", "SVC", "技术配置",
     "由 16.5 大数据平台高可用/加固/备份、15.3 汇聚平台行列级权限与最小全量访问人数推导。",
     ["16.5","15.3"]),
    ("数据收集系统安全防护", "collection_system_protection", "SVC", "技术配置",
     "由 8.4 收集接口HTTPS、收集操作审计日志、可用性≥99.9%推导。",
     ["8.4"]),

    # ===== 链路 (NW) =====
    ("敏感数据传输加密与完整性", "secure_data_transmission", "NW", "加密与脱敏",
     "由 8.4/9.5/15.6 TLS1.2+、12.2 转移加密校验、14.5 敏感传输加密、20.7 第三方传输专线/VPN、10.1 外部共享加密、15.2 跨域流转保护一致推导。",
     ["8.4","9.5","12.2","14.5","15.6","20.7","10.1","15.2"]),
    ("网络安全域与边界防护", "network_zone_boundary_protection", "NW", "技术配置",
     "由 14.4 安全域划分与域间访问策略、14.6 边界FW/IDS/IPS与日志集中推导。",
     ["14.4","14.6"]),
    ("机房物理安全防护", "physical_datacenter_security", "NW", "技术配置",
     "由 14.5 核心机房独立物理区域、门禁审批、重点防护推导（物理边界，暂归NW，最终以v1.5为准）。",
     ["14.5"]),
    ("外联统一交互平台与API网关", "external_interaction_api_gateway", "NW", "访问控制",
     "由 18.1 开放银行API网关/沙箱/限流、18.2 统一外联平台消除私接通道推导。",
     ["18.1","18.2"]),

    # ===== 端侧 (EP) =====
    ("终端DLP与移动介质管控", "endpoint_dlp_media_control", "EP", "访问控制",
     "由 15.11 涉敏终端DLP≥90%/USB管控/介质加密、15.12 报废介质擦除与销毁证书推导。",
     ["15.11","15.12"]),
    ("端点EDR与防勒索", "endpoint_edr_ransomware", "EP", "技术配置",
     "由 15.7 终端EDR覆盖率≥95%、离线备份/不可变存储防勒索、高危漏洞修复推导。",
     ["15.7"]),

    # ===== 协议 (PROTO) =====
    ("API全生命周期安全管理", "api_lifecycle_security", "PROTO", "访问控制",
     "由 18.3 API设计安全评审、认证鉴权、流量异常监控、僵尸API下线推导。",
     ["18.3"]),
    ("同意管理系统功能", "consent_management_system", "PROTO", "技术配置",
     "由 19.1 同意模块/告知/撤回/记录留痕、12.3 对外提供同意记录存档推导（系统功能侧，治理侧见隐私合规控制）。",
     ["19.1","12.3"]),
]


def main():
    checks_doc = json.load(open(CHECKS_JSON, encoding="utf-8"))
    checks = {c["id"]: c for c in checks_doc["checks"]}
    all_ids = set(checks)
    ct = load_ct_codes(CT_CODES_CSV)

    # 校验对齐表：每个 CT 码必须真实存在于 v1.5 权威表
    for hint, code in CT_ALIGN.items():
        assert code in ct, f"对齐表引用了不存在的 CT 码: {hint} -> {code}"

    # 读 10 工程现有 control（只读，仅用于统计/比对）
    kb = json.load(open(KB10_JSON, encoding="utf-8"))
    ents = kb if isinstance(kb, list) else kb.get("entities", kb.get("data", []))
    existing_controls = [e for e in ents if e.get("type") == "control"]

    controls = []
    anomalies = []
    covered = set()
    for name, hint, layer, ctype, rationale, src in CATALOG:
        # 校验 source_checks 真实存在
        refs = []
        for sid in src:
            if sid not in all_ids:
                anomalies.append(f"{hint}: source_check {sid} 不存在")
                continue
            covered.add(sid)
            reg = checks[sid].get("regulation") or ""
            refs.append(reg)
        article_refs = sorted({r for r in refs if r})

        if hint in CT_ALIGN:
            code = CT_ALIGN[hint]
            meta = ct[code]
            alignment = {"status": "aligned", "ct_code": code,
                         "ct_layer": meta["layer"],
                         "base_control_id": meta["id"],
                         "base_control_title": meta["title"],
                         "note": f"与 v1.5 权威控制『{meta['title']}』正式对齐（{code}）"}
            # 对齐后以权威层为准
            eff_layer = meta["layer"]
        else:
            alignment = {"status": "gap", "ct_code": None, "ct_layer": None,
                         "base_control_id": None, "base_control_title": None,
                         "feedback": GAP_FEEDBACK.get(hint, ""),
                         "note": "v1.5 权威控制表中无语义对应，保持需求缺口，待 10 工程补建"}
            eff_layer = layer.split("（")[0]

        controls.append({
            "control_name": name,
            "control_code_hint": hint,
            "suggested_layer": f"{eff_layer}（{'v1.5 正式对齐' if hint in CT_ALIGN else '建议，待 v1.5 补建'}）",
            "control_type_hint": ctype,
            "source_checks": src,
            "article_refs": article_refs,
            "rationale": rationale,
            "alignment": alignment,
        })

    by_layer = Counter(c["suggested_layer"].split("（")[0] for c in controls)
    n_aligned = sum(1 for c in controls if c["alignment"]["status"] == "aligned")
    n_gap = sum(1 for c in controls if c["alignment"]["status"] == "gap")

    # 未被任何控制覆盖的 check（应尽量为 0）
    uncovered = sorted(all_ids - covered, key=lambda x: [int(p) for p in x.split(".")])

    cn_tz = timezone(timedelta(hours=8))
    out = {
        "generated_at": datetime.now(cn_tz).isoformat(timespec="seconds"),
        "convention": {
            "single_source": "10_知识库工程 v1.5 CT 编码（CT-<层码>-序号，data/control-codes.csv）",
            "note": "alignment.status=aligned 表示已按 control_name 认领并正式对齐 v1.5 权威控制（ct_code/ct_layer/base_control_id 均来自 control-codes.csv）；status=gap 表示 v1.5 无语义对应，保持需求缺口并附补建反馈。",
        },
        "stats": {
            "controls": len(controls),
            "aligned": n_aligned,
            "gap": n_gap,
            "by_layer": dict(by_layer),
            "checks_covered": len(covered),
            "checks_total": len(all_ids),
            "coverage_ratio": round(len(covered) / len(all_ids), 4),
            "uncovered_checks": uncovered,
            "existing_controls_10proj": [{"id": e.get("id"), "title": e.get("title")} for e in existing_controls],
        },
        "controls": controls,
    }

    os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # 基本断言
    assert len(controls) >= 30, "控制目录过少，疑似过度合并"
    assert all(c["source_checks"] for c in controls), "存在 source_checks 为空的控制"
    assert not anomalies, f"source_checks 引用异常: {anomalies}"
    assert n_gap + n_aligned == len(controls)
    assert all((c["alignment"]["status"] == "aligned") == bool(c["alignment"].get("ct_code"))
               for c in controls), "aligned 状态必须携带 ct_code，gap 不得携带"

    print(f"[OK] 写出 {OUTPUT_JSON}")
    print(f"[OK] 占位控制总数={len(controls)}  aligned={n_aligned}  gap={n_gap}")
    print(f"[OK] by_layer={dict(by_layer)}")
    print(f"[OK] 覆盖 check={len(covered)}/{len(all_ids)} ({len(covered)/len(all_ids)*100:.1f}%)")
    if uncovered:
        print(f"[!] 未覆盖 check: {uncovered}")


if __name__ == "__main__":
    main()
