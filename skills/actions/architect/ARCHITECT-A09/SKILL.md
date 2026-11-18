# ARCHITECT-A09 变更与施工阶段设计支持

explain/propose_change/request_authority沿原现场Issue、已用Deliverable版本、有效Obligation/合同及独立A09权限核对。解释可无影响方法/计算；只有明确保留原内容且无变量变化才解释，实质改变参数/性能转修订申请，不通过聊天修改订单或现场工程。

propose_change按原义务允许范围、独立有权Instruction及当前变量有限目录/范围/精度核对，缺新增授权先request_authority。原义务内已授权缺陷整改可按约申请，不因收费争议一概停止；需求变更、缺陷整改和接口冲突原因分别保留。原影响依赖不得遗漏，修订申请先到变更/任务入口再到A05，新版本及受影响用途须后续核验。

没有已执行影响评估时impact_result_ref=null，并保留明确待核问题；只提供impact_method_ref不表示已计算。已有MethodResult逐原issue/义务/指令完整内容/旧成果摘要/拟改变量/影响范围及依赖输入摘要、方法许可/执行时点/独立作者权限核对。未知/失败不确认金额或工期，未支持保持unsupported，不自动放行用途。

fee_entitlement_ref仅沿原合同、原因和原成果/Issue/Obligation的独立有权EntitlementDecision；费用权利未知保持null，有权已知决定保留原granted/denied，不由成本影响、整改标签或本方主张推定收费/免费。成本/时间影响与费用责任是分别记录，不直接产生应收或现金。

本地 `micro.architect.declared_change_impact@1` 只对原实际数值依据的拟议值与原值做差，金额同币种、工期同单位，不推断价格、关键路径或日历。`DesignChangeImpactBasis` 必须绑定原变更输入摘要及全部已知数值 Evidence；缺依据须补件，对应原值未知则差额未知，不能填零。准备不执行方法，已保存本地影响数值须与原数值依据复算同值；该有限差额不产生费用权利、变更登记或使用许可。

completed只答复或有界修订/授权请求；成果版本、合同变化、采购/施工/用途及费用各自走核心有权提交。真实现场Issue/合同义务/指令/目录/影响方法执行/费用决定生产者、跨动作兼容、正式submit/query、原子修订任务及依赖影响/反馈仍待集成。CHECK-ARCHITECT-010/011/037待集中测试。
