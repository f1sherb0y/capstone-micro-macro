# ARCHITECT-A06 原作者接口整合

读取原DesignOption及完整本行收到的Assessment/CostPlan/SupplyAdvice/开放Issue集合和显式IntegrationProfile，逐原方案版本、获知/作者时点、范围、独立作者职能/权限核对；只读取已授权公开投影，不查他人私有判断。

raise_interfaces/request_inputs提出原EvidenceTarget和ResponseRequirement登记的具体ArchitectQuestion，接收者限原许可名单。escalate保持原非空问题身份，接收者须独立有权处理对应范围。本输出是草稿，不实际发送消息。

integrate同时需要独立原委任Authority、准确方案/范围/接收者、允许作者输入及接口；缺权、过期或明确未准则按本行原策略报告/升级，不自封总审批者。逐原保存MethodResult的执行时点、来源摘要、接口与开放Issue核对，只检验原版本/作者内容/未决项保留的一致性，不能把其结果当技术批准。

ArchitectIntegration仅保留原Assessment/CostPlan引用，不复制或覆盖专业、造价结论；供货资料保留在原接口及一致性来源中。冲突、未知或尚无回复必须保留具体原开放Issue，会议结束不关问题，不产生“全部专业通过”。未知输入/方法结果分别保留信息缺口/unsupported，不以沉默代同意。

显式声明纯方法 `micro.architect.original_interface_reference_consistency:1`，仅供生产入口在原有整合授权及来源复核后调用。输入保原对象、内容摘要、接口和全部未决问题；方法只报告引用一致或unknown，不改专业结论。原具体Method投影仍声明本方案的checked_fields，不能由输入选择执行器。报告须保存和发布后才供普通integrate消费；生产、保存发布和正式接线尚待补齐。

completed仅整合/协调草稿，问题创建/关闭、作者成果版本、正式整合保存及用途放行各有核心入口。真实收到专业/成本/供货投影、独立整合委任、接口/问题及一致性执行生产者、跨动作兼容、正式submit/query、原子版本与问题后果及反馈仍待集成。CHECK-ARCHITECT-009/021/036待集中测试。
