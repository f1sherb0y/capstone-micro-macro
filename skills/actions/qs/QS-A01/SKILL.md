# QS-A01 识别业务并维护可用市场资料

核对己方组织的原 Strategy、独立 QS 权限、可见 Opportunity/Trigger 和原 PriceSource。按原策略明确顺序选择 track、express_interest、prepare、register_source 或 ignore，不推测需求、价格、邀请人或偏好。允许 organization scope，不要求创建项目。

跟踪只引用原机会和有效触发，opportunity_ref 必须在当前 CandidateSet 中明确允许 track；register_source 的非空 source_refs 必须逐项在当前候选集中允许 register_source。可见或列入原输入不等于本次候选授权，空候选不生成跟踪或资料登记选择。表达兴趣只返回原邀请方的决定，不发送消息、不披露私有报价、不承诺服务。竞争者秘密及未经授权来源不得输出来源证据或带入整理申请；问题接收者及输入集合须有独立许可。

仅原报价/指数、有观测证据且完整适用口径的来源可登记。保留原时间、地区、计量规则、交付与包含/排除范围及限制；一次只登记一个源，不转换币种或拼接异地/异期报价。市场评论、推断、缺口径来源保留限制，不产生真实价格、订单或可信度提升。CHECK-QS-006、CHECK-QS-026 待集中验收。

整理申请使用原 ResearchRequestProfile 与独立 Authority、明确目的、当前剩余费用/工作额度、原估计和窗口；超过额度不申请。未取得工作方法可保留 work_profile_ref=null 与未知工时，仅申请，不执行、不占资源、不形成收费。缺当前限额/原估计返回待补信息。

completed 仅为本地主体决定。真实机会/价格/资料生产者、正式登记/提交/查询、研究任务创建和反馈仍需宿主绑定。本批代码待最终集中验证。
