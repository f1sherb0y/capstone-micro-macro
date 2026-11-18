# 目标函数索引

本索引连接八类角色、世界运行和服务展示的目标函数。函数职责、输入字段、输出分支、副作用和失败处理只在链接的主定义维护。本表不宣称当前代码存在同名函数，也不替代实现后的源码符号清单。

[总入口](../README.md) · [类型和全部函数的登记要求](interface_contracts.md) · [非角色系统接口](system_interfaces.md) · [跨主体交接](../03_projects/collaboration_flow.md)

<!-- page-nav:start -->
**本页导航**

[1. 查找与实现绑定](#1-查找与实现绑定) · [2. 角色动作入口](#2-角色动作入口) · [3. 共同核心与系统入口](#3-共同核心与系统入口)

[4. 变更一致性](#4-变更一致性)
<!-- page-nav:end -->

## 1. 查找与实现绑定

先按角色动作或系统职责查找目标入口，再打开主定义核对输入来源、字段、分支和消费者。`roles.owner.a01` 等逻辑函数ID用于稳定追踪；实现可以使用更具体的名称及多个帮助函数，但需要登记对应关系。

每个目标函数的实现记录绑定：实际文件/符号与签名、Input/Output schema、调用方/被调用方、读写对象、授权/幂等/版本、CHECK和执行证据。所有实际函数含私有帮助函数、页面handler、adapter、回调均须登记；纯帮助函数可以简短说明类型、职责、纯函数性质及异常。没有实现证据的目标保持未实现或未验证。

## 2. 角色动作入口

### Owner 业主

| 目标函数 | 行为与唯一契约 |
|---|---|
| `roles.owner.a01` | [OWN-A01 · 观察机会与建立评估档案](../04_roles/owner.md#own-a01--观察机会与建立评估档案) |
| `roles.owner.a16` | [OWN-A16 · 从需求和条件形成或修订项目提案](../04_roles/owner.md#own-a16--从需求和条件形成或修订项目提案) |
| `roles.owner.a02` | [OWN-A02 · 授权有限调查与前期服务](../04_roles/owner.md#own-a02--授权有限调查与前期服务) |
| `roles.owner.a03` | [OWN-A03 · 比较方案并作投资决定](../04_roles/owner.md#own-a03--比较方案并作投资决定) |
| `roles.owner.a04` | [OWN-A04 · 确定采购安排并委任专业服务](../04_roles/owner.md#own-a04--确定采购安排并委任专业服务) |
| `roles.owner.a05` | [OWN-A05 · 制订资金计划并选择融资安排](../04_roles/owner.md#own-a05--制订资金计划并选择融资安排) |
| `roles.owner.a06` | [OWN-A06 · 申请提款、组织付款与偿还](../04_roles/owner.md#own-a06--申请提款组织付款与偿还) |
| `roles.owner.a07` | [OWN-A07 · 委托设计并确认业主需求与取舍](../04_roles/owner.md#own-a07--委托设计并确认业主需求与取舍) |
| `roles.owner.a08` | [OWN-A08 · 授权申请及回应监管事项](../04_roles/owner.md#own-a08--授权申请及回应监管事项) |
| `roles.owner.a09` | [OWN-A09 · 组织招标与比较投标](../04_roles/owner.md#own-a09--组织招标与比较投标) |
| `roles.owner.a10` | [OWN-A10 · 授予合同并建立履约关系](../04_roles/owner.md#own-a10--授予合同并建立履约关系) |
| `roles.owner.a11` | [OWN-A11 · 管理变更、付款事项与履约冲突](../04_roles/owner.md#own-a11--管理变更付款事项与履约冲突) |
| `roles.owner.a12` | [OWN-A12 · 接收工程并处理缺陷和结算](../04_roles/owner.md#own-a12--接收工程并处理缺陷和结算) |
| `roles.owner.a13` | [OWN-A13 · 暂停、缩减、终止及接续](../04_roles/owner.md#own-a13--暂停缩减终止及接续) |
| `roles.owner.a14` | [OWN-A14 · 管理项目回款及持有资产](../04_roles/owner.md#own-a14--管理项目回款及持有资产) |
| `roles.owner.a15` | [OWN-A15 · 企业经营与经验更新](../04_roles/owner.md#own-a15--企业经营与经验更新) |

### Bank 银行

| 目标函数 | 行为与唯一契约 |
|---|---|
| `roles.bank.a01` | [BANK-A01 · 观察市场并管理融资组合](../04_roles/bank.md#bank-a01--观察市场并管理融资组合) |
| `roles.bank.a02` | [BANK-A02 · 接收申请与核对借款主体](../04_roles/bank.md#bank-a02--接收申请与核对借款主体) |
| `roles.bank.a03` | [BANK-A03 · 审查风险、可负担性和条件](../04_roles/bank.md#bank-a03--审查风险可负担性和条件) |
| `roles.bank.a04` | [BANK-A04 · 批准并提出有版本的报价](../04_roles/bank.md#bank-a04--批准并提出有版本的报价) |
| `roles.bank.a05` | [BANK-A05 · 确认接受并建立融资安排](../04_roles/bank.md#bank-a05--确认接受并建立融资安排) |
| `roles.bank.a06` | [BANK-A06 · 核验提款条件并处理提款申请](../04_roles/bank.md#bank-a06--核验提款条件并处理提款申请) |
| `roles.bank.a07` | [BANK-A07 · 发出资金执行指令并核对结果](../04_roles/bank.md#bank-a07--发出资金执行指令并核对结果) |
| `roles.bank.a08` | [BANK-A08 · 持续监控与管理条款事项](../04_roles/bank.md#bank-a08--持续监控与管理条款事项) |
| `roles.bank.a09` | [BANK-A09 · 应计、到期与偿还核对](../04_roles/bank.md#bank-a09--应计到期与偿还核对) |
| `roles.bank.a10` | [BANK-A10 · 处理违约、重组与处置](../04_roles/bank.md#bank-a10--处理违约重组与处置) |
| `roles.bank.a11` | [BANK-A11 · 关闭安排与保留剩余义务](../04_roles/bank.md#bank-a11--关闭安排与保留剩余义务) |
| `roles.bank.a12` | [BANK-A12 · 更新自身经验与后续选择](../04_roles/bank.md#bank-a12--更新自身经验与后续选择) |
| `roles.bank.a13` | [BANK-A13 · 为前期方案提供融资可行性意见](../04_roles/bank.md#bank-a13--为前期方案提供融资可行性意见) |

### Architect 建筑师

| 目标函数 | 行为与唯一契约 |
|---|---|
| `roles.architect.a01` | [ARCHITECT-A01 · 发现业务并选择是否研究](../04_roles/architect.md#architect-a01--发现业务并选择是否研究) |
| `roles.architect.a02` | [ARCHITECT-A02 · 独立判断接单并提出条件](../04_roles/architect.md#architect-a02--独立判断接单并提出条件) |
| `roles.architect.a03` | [ARCHITECT-A03 · 确认委任范围并承接任务](../04_roles/architect.md#architect-a03--确认委任范围并承接任务) |
| `roles.architect.a04` | [ARCHITECT-A04 · 安排设计人员和实际任务](../04_roles/architect.md#architect-a04--安排设计人员和实际任务) |
| `roles.architect.a05` | [ARCHITECT-A05 · 编制和比较建筑方案](../04_roles/architect.md#architect-a05--编制和比较建筑方案) |
| `roles.architect.a06` | [ARCHITECT-A06 · 整合授权范围内的专业接口](../04_roles/architect.md#architect-a06--整合授权范围内的专业接口) |
| `roles.architect.a07` | [ARCHITECT-A07 · 提交成果并申请相应用途审查](../04_roles/architect.md#architect-a07--提交成果并申请相应用途审查) |
| `roles.architect.a08` | [ARCHITECT-A08 · 审查建筑成果或回应审查意见](../04_roles/architect.md#architect-a08--审查建筑成果或回应审查意见) |
| `roles.architect.a09` | [ARCHITECT-A09 · 处理变更与施工阶段设计支持](../04_roles/architect.md#architect-a09--处理变更与施工阶段设计支持) |
| `roles.architect.a10` | [ARCHITECT-A10 · 申报服务费并处理应收](../04_roles/architect.md#architect-a10--申报服务费并处理应收) |
| `roles.architect.a11` | [ARCHITECT-A11 · 暂停、召回、交接与退出](../04_roles/architect.md#architect-a11--暂停召回交接与退出) |
| `roles.architect.a12` | [ARCHITECT-A12 · 更新经营判断与设计经验](../04_roles/architect.md#architect-a12--更新经营判断与设计经验) |
| `roles.architect.a13` | [ARCHITECT-A13 · 承接有限前期方案比较](../04_roles/architect.md#architect-a13--承接有限前期方案比较) |

### Engineer 工程师

| 目标函数 | 行为与唯一契约 |
|---|---|
| `roles.engineer.a01` | [ENGINEER-A01 · 识别专业需求与经营机会](../04_roles/engineer.md#engineer-a01--识别专业需求与经营机会) |
| `roles.engineer.a02` | [ENGINEER-A02 · 判断是否承接并提出服务方案](../04_roles/engineer.md#engineer-a02--判断是否承接并提出服务方案) |
| `roles.engineer.a03` | [ENGINEER-A03 · 核对委任和检查独立性](../04_roles/engineer.md#engineer-a03--核对委任和检查独立性) |
| `roles.engineer.a04` | [ENGINEER-A04 · 安排专业任务与调查需求](../04_roles/engineer.md#engineer-a04--安排专业任务与调查需求) |
| `roles.engineer.a05` | [ENGINEER-A05 · 分析并形成专业方案](../04_roles/engineer.md#engineer-a05--分析并形成专业方案) |
| `roles.engineer.a06` | [ENGINEER-A06 · 检查指定成果与接口](../04_roles/engineer.md#engineer-a06--检查指定成果与接口) |
| `roles.engineer.a07` | [ENGINEER-A07 · 提交成果、签署及用途说明](../04_roles/engineer.md#engineer-a07--提交成果签署及用途说明) |
| `roles.engineer.a08` | [ENGINEER-A08 · 提供施工检查与技术支持](../04_roles/engineer.md#engineer-a08--提供施工检查与技术支持) |
| `roles.engineer.a09` | [ENGINEER-A09 · 处理修改、调试与缺陷复查](../04_roles/engineer.md#engineer-a09--处理修改调试与缺陷复查) |
| `roles.engineer.a10` | [ENGINEER-A10 · 提交服务费依据并管理应收](../04_roles/engineer.md#engineer-a10--提交服务费依据并管理应收) |
| `roles.engineer.a11` | [ENGINEER-A11 · 暂停、召回与专业交接](../04_roles/engineer.md#engineer-a11--暂停召回与专业交接) |
| `roles.engineer.a12` | [ENGINEER-A12 · 维护资格与专业经验](../04_roles/engineer.md#engineer-a12--维护资格与专业经验) |
| `roles.engineer.a13` | [ENGINEER-A13 · 承接范围明确的前期技术评估](../04_roles/engineer.md#engineer-a13--承接范围明确的前期技术评估) |

### QS 造价顾问

| 目标函数 | 行为与唯一契约 |
|---|---|
| `roles.qs.a01` | [QS-A01 · 识别业务并维护可用市场资料](../04_roles/qs.md#qs-a01--识别业务并维护可用市场资料) |
| `roles.qs.a02` | [QS-A02 · 独立评估服务范围并接单](../04_roles/qs.md#qs-a02--独立评估服务范围并接单) |
| `roles.qs.a03` | [QS-A03 · 确认委任并安排实际任务](../04_roles/qs.md#qs-a03--确认委任并安排实际任务) |
| `roles.qs.a04` | [QS-A04 · 编制方案估算与成本计划](../04_roles/qs.md#qs-a04--编制方案估算与成本计划) |
| `roles.qs.a05` | [QS-A05 · 准备量价与采购成本资料](../04_roles/qs.md#qs-a05--准备量价与采购成本资料) |
| `roles.qs.a06` | [QS-A06 · 评价投标并提出成本意见](../04_roles/qs.md#qs-a06--评价投标并提出成本意见) |
| `roles.qs.a07` | [QS-A07 · 评估变更、索赔与费用影响](../04_roles/qs.md#qs-a07--评估变更索赔与费用影响) |
| `roles.qs.a08` | [QS-A08 · 计量、核实支付申请或获授权核证](../04_roles/qs.md#qs-a08--计量核实支付申请或获授权核证) |
| `roles.qs.a09` | [QS-A09 · 编制最终结算意见与清单](../04_roles/qs.md#qs-a09--编制最终结算意见与清单) |
| `roles.qs.a10` | [QS-A10 · 申报本企业服务费并收款](../04_roles/qs.md#qs-a10--申报本企业服务费并收款) |
| `roles.qs.a11` | [QS-A11 · 暂停、交接及结束服务](../04_roles/qs.md#qs-a11--暂停交接及结束服务) |
| `roles.qs.a12` | [QS-A12 · 从履约反馈更新估算与经营判断](../04_roles/qs.md#qs-a12--从履约反馈更新估算与经营判断) |
| `roles.qs.a13` | [QS-A13 · 接收需求版本并形成前期方案成本比较](../04_roles/qs.md#qs-a13--接收需求版本并形成前期方案成本比较) |

### Government 政府

| 目标函数 | 行为与唯一契约 |
|---|---|
| `roles.government.a01` | [GOV-A01 · 确认职责并回应前期咨询](../04_roles/government.md#gov-a01--确认职责并回应前期咨询) |
| `roles.government.a02` | [GOV-A02 · 收件、完整性检查与受理](../04_roles/government.md#gov-a02--收件完整性检查与受理) |
| `roles.government.a03` | [GOV-A03 · 排队、分派与续办](../04_roles/government.md#gov-a03--排队分派与续办) |
| `roles.government.a04` | [GOV-A04 · 专业审查与证据核验](../04_roles/government.md#gov-a04--专业审查与证据核验) |
| `roles.government.a05` | [GOV-A05 · 组织部门咨询与公众参与](../04_roles/government.md#gov-a05--组织部门咨询与公众参与) |
| `roles.government.a06` | [GOV-A06 · 提出补件要求并检查回应](../04_roles/government.md#gov-a06--提出补件要求并检查回应) |
| `roles.government.a07` | [GOV-A07 · 作出并通知正式决定](../04_roles/government.md#gov-a07--作出并通知正式决定) |
| `roles.government.a08` | [GOV-A08 · 核验条件并提供许可依据](../04_roles/government.md#gov-a08--核验条件并提供许可依据) |
| `roles.government.a09` | [GOV-A09 · 处理变更、到期、续期与复审](../04_roles/government.md#gov-a09--处理变更到期续期与复审) |
| `roles.government.a10` | [GOV-A10 · 安排施工检查与后续处置](../04_roles/government.md#gov-a10--安排施工检查与后续处置) |
| `roles.government.a11` | [GOV-A11 · 审理使用事项并保留持续责任](../04_roles/government.md#gov-a11--审理使用事项并保留持续责任) |
| `roles.government.a12` | [GOV-A12 · 分析反馈与提出可选制度调整](../04_roles/government.md#gov-a12--分析反馈与提出可选制度调整) |

### Contractor 承包商

| 目标函数 | 行为与唯一契约 |
|---|---|
| `roles.contractor.a01` | [CONTRACTOR-A01｜观察机会并筛选是否参投](../04_roles/contractor.md#contractor-a01观察机会并筛选是否参投) |
| `roles.contractor.a02` | [CONTRACTOR-A02｜形成投标方案与报价](../04_roles/contractor.md#contractor-a02形成投标方案与报价) |
| `roles.contractor.a03` | [CONTRACTOR-A03｜处理澄清、修改和撤回](../04_roles/contractor.md#contractor-a03处理澄清修改和撤回) |
| `roles.contractor.a04` | [CONTRACTOR-A04｜判断授标与形成合同承诺](../04_roles/contractor.md#contractor-a04判断授标与形成合同承诺) |
| `roles.contractor.a05` | [CONTRACTOR-A05｜制定履约排期并采购供应](../04_roles/contractor.md#contractor-a05制定履约排期并采购供应) |
| `roles.contractor.a06` | [CONTRACTOR-A06｜核对动员与具体施工放行](../04_roles/contractor.md#contractor-a06核对动员与具体施工放行) |
| `roles.contractor.a07` | [CONTRACTOR-A07｜安排施工、报告进展并调整投入](../04_roles/contractor.md#contractor-a07安排施工报告进展并调整投入) |
| `roles.contractor.a08` | [CONTRACTOR-A08｜检查质量、安全并组织整改](../04_roles/contractor.md#contractor-a08检查质量安全并组织整改) |
| `roles.contractor.a09` | [CONTRACTOR-A09｜处理设计接口、变更与索赔](../04_roles/contractor.md#contractor-a09处理设计接口变更与索赔) |
| `roles.contractor.a10` | [CONTRACTOR-A10｜申请计量、收款并支付下游](../04_roles/contractor.md#contractor-a10申请计量收款并支付下游) |
| `roles.contractor.a11` | [CONTRACTOR-A11｜交付、缺陷责任与最终结算](../04_roles/contractor.md#contractor-a11交付缺陷责任与最终结算) |
| `roles.contractor.a12` | [CONTRACTOR-A12｜暂停、退出、接续与经营反馈](../04_roles/contractor.md#contractor-a12暂停退出接续与经营反馈) |
| `roles.contractor.a13` | [CONTRACTOR-A13｜可选参与前期可建造性与施工组织咨询](../04_roles/contractor.md#contractor-a13可选参与前期可建造性与施工组织咨询) |

### Supplier 供应商

| 目标函数 | 行为与唯一契约 |
|---|---|
| `roles.supplier.a01` | [SUPPLIER-A01｜观察需求并判断是否响应](../04_roles/supplier.md#supplier-a01观察需求并判断是否响应) |
| `roles.supplier.a02` | [SUPPLIER-A02｜审查规格与提出产品方案](../04_roles/supplier.md#supplier-a02审查规格与提出产品方案) |
| `roles.supplier.a03` | [SUPPLIER-A03｜形成报价与交付计划](../04_roles/supplier.md#supplier-a03形成报价与交付计划) |
| `roles.supplier.a04` | [SUPPLIER-A04｜接受订单并提交履约承诺](../04_roles/supplier.md#supplier-a04接受订单并提交履约承诺) |
| `roles.supplier.a05` | [SUPPLIER-A05｜安排备料、采购与生产排期](../04_roles/supplier.md#supplier-a05安排备料采购与生产排期) |
| `roles.supplier.a06` | [SUPPLIER-A06｜执行生产并管理库存](../04_roles/supplier.md#supplier-a06执行生产并管理库存) |
| `roles.supplier.a07` | [SUPPLIER-A07｜检验产品并准备交付证据](../04_roles/supplier.md#supplier-a07检验产品并准备交付证据) |
| `roles.supplier.a08` | [SUPPLIER-A08｜安排发运与处理运输异常](../04_roles/supplier.md#supplier-a08安排发运与处理运输异常) |
| `roles.supplier.a09` | [SUPPLIER-A09｜配合收货、检验与可使用放行](../04_roles/supplier.md#supplier-a09配合收货检验与可使用放行) |
| `roles.supplier.a10` | [SUPPLIER-A10｜提出收款并管理自身付款](../04_roles/supplier.md#supplier-a10提出收款并管理自身付款) |
| `roles.supplier.a11` | [SUPPLIER-A11｜处理变更、退换、质量责任与争议](../04_roles/supplier.md#supplier-a11处理变更退换质量责任与争议) |
| `roles.supplier.a12` | [SUPPLIER-A12｜暂停、取消、收尾与企业学习](../04_roles/supplier.md#supplier-a12暂停取消收尾与企业学习) |
| `roles.supplier.a13` | [SUPPLIER-A13 · 评估需求简报并提供限定用途的供应意见](../04_roles/supplier.md#supplier-a13--评估需求简报并提供限定用途的供应意见) |

## 3. 共同核心与系统入口

### 共同核心

| 目标函数 | 主定义 |
|---|---|
| `core.register_invocation` | [5.2 共用核心函数](interface_contracts.md#52-共用核心函数) |
| `core.validate_action` | [5.2 共用核心函数](interface_contracts.md#52-共用核心函数) |
| `core.bind_command` | [5.2 共用核心函数](interface_contracts.md#52-共用核心函数) |
| `core.commit` | [5.2 共用核心函数](interface_contracts.md#52-共用核心函数) |
| `core.commit_workspace` | [5.2 共用核心函数](interface_contracts.md#52-共用核心函数) |
| `core.read_receipt` | [5.2 共用核心函数](interface_contracts.md#52-共用核心函数) |
| `core.record_decision` | [5.2 共用核心函数](interface_contracts.md#52-共用核心函数) |

### 世界与平台

| 目标函数 | 主定义 |
|---|---|
| `data.normalize_sources` | [2.2 函数](system_interfaces.md#22-函数) |
| `data.resolve_entities` | [2.2 函数](system_interfaces.md#22-函数) |
| `data.audit_release` | [2.2 函数](system_interfaces.md#22-函数) |
| `data.prepare_release` | [2.2 函数](system_interfaces.md#22-函数) |
| `bootstrap.prepare_instance` | [2.2 函数](system_interfaces.md#22-函数) |
| `bootstrap.plan_initial_world` | [2.2 函数](system_interfaces.md#22-函数) |
| `bootstrap.audit_opening` | [2.2 函数](system_interfaces.md#22-函数) |
| `bootstrap.prepare_run` | [2.2 函数](system_interfaces.md#22-函数) |
| `bootstrap.prepare_instance_status` | [2.2 函数](system_interfaces.md#22-函数) |
| `world.sample_exogenous` | [3.2 函数](system_interfaces.md#32-函数) |
| `world.prepare_environment` | [3.2 函数](system_interfaces.md#32-函数) |
| `market.compute_signals` | [3.2 函数](system_interfaces.md#32-函数) |
| `market.prepare_signals` | [3.2 函数](system_interfaces.md#32-函数) |
| `background.compute_claims` | [3.2 函数](system_interfaces.md#32-函数) |
| `assets.compute_utilization` | [3.2 函数](system_interfaces.md#32-函数) |
| `assets.prepare_utilization` | [3.2 函数](system_interfaces.md#32-函数) |
| `organizations.compute_operating_period` | [3.2 函数](system_interfaces.md#32-函数) |
| `organizations.prepare_operating_period` | [3.2 函数](system_interfaces.md#32-函数) |
| `scheduler.find_due_work` | [4. 时间、队列、行动机会与竞争](system_interfaces.md#4-时间队列行动机会与竞争) |
| `scheduler.plan_next_cycle` | [4. 时间、队列、行动机会与竞争](system_interfaces.md#4-时间队列行动机会与竞争) |
| `scheduler.prepare_cycle` | [4. 时间、队列、行动机会与竞争](system_interfaces.md#4-时间队列行动机会与竞争) |
| `scheduler.build_action_slots` | [4. 时间、队列、行动机会与竞争](system_interfaces.md#4-时间队列行动机会与竞争) |
| `scheduler.prepare_action_slots` | [4. 时间、队列、行动机会与竞争](system_interfaces.md#4-时间队列行动机会与竞争) |
| `resources.resolve_competition` | [4. 时间、队列、行动机会与竞争](system_interfaces.md#4-时间队列行动机会与竞争) |
| `policy.extract_clauses` | [5.2 函数](system_interfaces.md#52-函数) |
| `policy.prepare_evidence` | [5.2 函数](system_interfaces.md#52-函数) |
| `policy.structure_mechanisms` | [5.2 函数](system_interfaces.md#52-函数) |
| `policy.compile_configuration` | [5.2 函数](system_interfaces.md#52-函数) |
| `policy.prepare_configuration` | [5.2 函数](system_interfaces.md#52-函数) |
| `policy.evaluate_applicability` | [5.2 函数](system_interfaces.md#52-函数) |
| `policy.prepare_applications` | [5.2 函数](system_interfaces.md#52-函数) |
| `policy.prepare_grant_application` | [5.2 函数](system_interfaces.md#52-函数) |
| `policy.prepare_grant_round` | [5.2 函数](system_interfaces.md#52-函数) |
| `opportunities.prepare_case` | [6.2 函数](system_interfaces.md#62-函数) |
| `proposals.prepare_briefs` | [6.2 函数](system_interfaces.md#62-函数) |
| `procurement.prepare_package` | [6.2 函数](system_interfaces.md#62-函数) |
| `procurement.prepare_round` | [6.2 函数](system_interfaces.md#62-函数) |
| `procurement.prepare_inquiry` | [6.2 函数](system_interfaces.md#62-函数) |
| `procurement.prepare_offer` | [6.2 函数](system_interfaces.md#62-函数) |
| `finance.prepare_application` | [6.2 函数](system_interfaces.md#62-函数) |
| `finance.prepare_offer` | [6.2 函数](system_interfaces.md#62-函数) |
| `finance.prepare_arrangement` | [6.2 函数](system_interfaces.md#62-函数) |
| `finance.prepare_draw_request` | [6.2 函数](system_interfaces.md#62-函数) |
| `work.prepare_request` | [6.2 函数](system_interfaces.md#62-函数) |
| `work.prepare_authorization` | [6.2 函数](system_interfaces.md#62-函数) |
| `project.evaluate_dependencies` | [6.2 函数](system_interfaces.md#62-函数) |
| `project.prepare_task_graph` | [6.2 函数](system_interfaces.md#62-函数) |
| `project.prepare_binding` | [6.2 函数](system_interfaces.md#62-函数) |
| `project.prepare_registration` | [6.2 函数](system_interfaces.md#62-函数) |
| `methods.evaluate_option` | [6.2 函数](system_interfaces.md#62-函数) |
| `work.check_draft` | [6.2 函数](system_interfaces.md#62-函数) |
| `work.prepare_deliverable` | [6.2 函数](system_interfaces.md#62-函数) |
| `work.evaluate_completion` | [6.2 函数](system_interfaces.md#62-函数) |
| `work.prepare_completion` | [6.2 函数](system_interfaces.md#62-函数) |
| `work.prepare_submission` | [6.2 函数](system_interfaces.md#62-函数) |
| `work.prepare_review` | [6.2 函数](system_interfaces.md#62-函数) |
| `work.prepare_use_release` | [6.2 函数](system_interfaces.md#62-函数) |
| `agreements.prepare_effectiveness` | [6.2 函数](system_interfaces.md#62-函数) |
| `matters.prepare_case` | [6.2 函数](system_interfaces.md#62-函数) |
| `matters.prepare_clock_status` | [6.2 函数](system_interfaces.md#62-函数) |
| `matters.prepare_decision` | [6.2 函数](system_interfaces.md#62-函数) |
| `project.evaluate_closure` | [6.2 函数](system_interfaces.md#62-函数) |
| `project.prepare_closure` | [6.2 函数](system_interfaces.md#62-函数) |
| `resources.prepare_reservations` | [7. 资源、批次、实际工程和资产交接](system_interfaces.md#7-资源批次实际工程和资产交接) |
| `resources.prepare_disposition` | [7. 资源、批次、实际工程和资产交接](system_interfaces.md#7-资源批次实际工程和资产交接) |
| `inventory.prepare_movement` | [7. 资源、批次、实际工程和资产交接](system_interfaces.md#7-资源批次实际工程和资产交接) |
| `inventory.prepare_inspection` | [7. 资源、批次、实际工程和资产交接](system_interfaces.md#7-资源批次实际工程和资产交接) |
| `engineering.check_readiness` | [7. 资源、批次、实际工程和资产交接](system_interfaces.md#7-资源批次实际工程和资产交接) |
| `engineering.compute_slice` | [7. 资源、批次、实际工程和资产交接](system_interfaces.md#7-资源批次实际工程和资产交接) |
| `engineering.prepare_execution` | [7. 资源、批次、实际工程和资产交接](system_interfaces.md#7-资源批次实际工程和资产交接) |
| `assets.prepare_handover` | [7. 资源、批次、实际工程和资产交接](system_interfaces.md#7-资源批次实际工程和资产交接) |
| `finance.prepare_obligations` | [8. 成本、债务、付款与外部核对](system_interfaces.md#8-成本债务付款与外部核对) |
| `finance.compute_accrual` | [8. 成本、债务、付款与外部核对](system_interfaces.md#8-成本债务付款与外部核对) |
| `finance.prepare_accrual` | [8. 成本、债务、付款与外部核对](system_interfaces.md#8-成本债务付款与外部核对) |
| `finance.prepare_transfer` | [8. 成本、债务、付款与外部核对](system_interfaces.md#8-成本债务付款与外部核对) |
| `payments.dispatch_instruction` | [8. 成本、债务、付款与外部核对](system_interfaces.md#8-成本债务付款与外部核对) |
| `payments.query_execution` | [8. 成本、债务、付款与外部核对](system_interfaces.md#8-成本债务付款与外部核对) |
| `finance.reconcile_execution` | [8. 成本、债务、付款与外部核对](system_interfaces.md#8-成本债务付款与外部核对) |
| `finance.prepare_settlement` | [8. 成本、债务、付款与外部核对](system_interfaces.md#8-成本债务付款与外部核对) |
| `finance.prepare_adjustment` | [8. 成本、债务、付款与外部核对](system_interfaces.md#8-成本债务付款与外部核对) |
| `observations.project_visible` | [9. 可见信息、候选、认知与技能宿主](system_interfaces.md#9-可见信息候选认知与技能宿主) |
| `observations.prepare_delivery` | [9. 可见信息、候选、认知与技能宿主](system_interfaces.md#9-可见信息候选认知与技能宿主) |
| `candidates.expose` | [9. 可见信息、候选、认知与技能宿主](system_interfaces.md#9-可见信息候选认知与技能宿主) |
| `candidates.prepare_exposure` | [9. 可见信息、候选、认知与技能宿主](system_interfaces.md#9-可见信息候选认知与技能宿主) |
| `cognition.compute_update` | [9. 可见信息、候选、认知与技能宿主](system_interfaces.md#9-可见信息候选认知与技能宿主) |
| `cognition.prepare_update` | [9. 可见信息、候选、认知与技能宿主](system_interfaces.md#9-可见信息候选认知与技能宿主) |
| `skills.invoke` | [9. 可见信息、候选、认知与技能宿主](system_interfaces.md#9-可见信息候选认知与技能宿主) |
| `skills.execute_managed` | [9. 可见信息、候选、认知与技能宿主](system_interfaces.md#9-可见信息候选认知与技能宿主) |
| `skills.prepare_completion` | [9. 可见信息、候选、认知与技能宿主](system_interfaces.md#9-可见信息候选认知与技能宿主) |
| `agents.build_action_input` | [9.1 正式对象与角色 Input 的显式投影](system_interfaces.md#91-正式对象与角色-input-的显式投影) |
| `contracts.validate_payload` | [9.1 正式对象与角色 Input 的显式投影](system_interfaces.md#91-正式对象与角色-input-的显式投影) |
| `contracts.validate_view_binding` | [9.1 正式对象与角色 Input 的显式投影](system_interfaces.md#91-正式对象与角色-input-的显式投影) |
| `contracts.prepare_view_binding` | [9.1 正式对象与角色 Input 的显式投影](system_interfaces.md#91-正式对象与角色-input-的显式投影) |
| `runs.prepare_control` | [10. 运行控制、检查点与恢复](system_interfaces.md#10-运行控制检查点与恢复) |
| `runs.assess_stop` | [10. 运行控制、检查点与恢复](system_interfaces.md#10-运行控制检查点与恢复) |
| `checkpoints.prepare_capture` | [10. 运行控制、检查点与恢复](system_interfaces.md#10-运行控制检查点与恢复) |
| `checkpoints.plan_recovery` | [10. 运行控制、检查点与恢复](system_interfaces.md#10-运行控制检查点与恢复) |
| `checkpoints.prepare_recovery` | [10. 运行控制、检查点与恢复](system_interfaces.md#10-运行控制检查点与恢复) |
| `networks.derive_edges` | [11.2 函数](system_interfaces.md#112-函数) |
| `metrics.compute` | [11.2 函数](system_interfaces.md#112-函数) |
| `results.prepare_projection` | [11.2 函数](system_interfaces.md#112-函数) |
| `experiments.plan_runs` | [11.2 函数](system_interfaces.md#112-函数) |
| `experiments.prepare_job` | [11.2 函数](system_interfaces.md#112-函数) |
| `experiments.prepare_run_set` | [11.2 函数](system_interfaces.md#112-函数) |
| `comparisons.check_pairing` | [11.2 函数](system_interfaces.md#112-函数) |
| `comparisons.align_time` | [11.2 函数](system_interfaces.md#112-函数) |
| `comparisons.compute` | [11.2 函数](system_interfaces.md#112-函数) |
| `comparisons.prepare_result` | [11.2 函数](system_interfaces.md#112-函数) |
| `views.query_catalog` | [12.2 函数](system_interfaces.md#122-函数) |
| `views.query_detail` | [12.2 函数](system_interfaces.md#122-函数) |
| `views.query_world` | [12.2 函数](system_interfaces.md#122-函数) |
| `views.query_comparison` | [12.2 函数](system_interfaces.md#122-函数) |
| `views.query_job` | [12.2 函数](system_interfaces.md#122-函数) |
| `views.query_command` | [12.2 函数](system_interfaces.md#122-函数) |
| `catalog.prepare_organization` | [12.2 函数](system_interfaces.md#122-函数) |
| `catalog.prepare_cluster` | [12.2 函数](system_interfaces.md#122-函数) |
| `workflows.check_definition` | [12.2 函数](system_interfaces.md#122-函数) |
| `workflows.prepare_definition` | [12.2 函数](system_interfaces.md#122-函数) |
| `settings.prepare_preferences` | [12.2 函数](system_interfaces.md#122-函数) |
| `drafts.prepare_revision` | [12.2 函数](system_interfaces.md#122-函数) |
| `contracts.assess_configuration` | [12.2 函数](system_interfaces.md#122-函数) |
| `drafts.prepare_freeze` | [12.2 函数](system_interfaces.md#122-函数) |
| `runs.prepare_manifest` | [12.2 函数](system_interfaces.md#122-函数) |
| `exports.prepare_job` | [12.2 函数](system_interfaces.md#122-函数) |
| `exports.render` | [12.2 函数](system_interfaces.md#122-函数) |
| `exports.prepare_delivery` | [12.2 函数](system_interfaces.md#122-函数) |

## 4. 变更一致性

新增、合并或删除函数时，同步唯一主定义、调用消费者、对象schema、错误/恢复路径、函数索引和实现绑定；不要只改函数名或HTTP路径。生成的源码清单与目标索引分别检查：前者发现实际代码遗漏，后者检查业务能力是否落实。两者的条目数量不要求相等。
