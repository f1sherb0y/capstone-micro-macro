# CONTRACTOR-A13 有限前期可建造性与施工组织咨询

读取原 OwnerBrief/ProjectOption、AdvisoryRequest、己方原选择及有权发起方，核对建设目的、地区、对象/特殊条件、规模/结构/运输批次版本、期望交付时间和资料披露许可。没有方案时可沿原简报提供有限意见；缺少可选咨询安排不阻塞主链。

advisory_authority_ref=null 只能请求补资料、propose_paid_study 或 decline。provide_advice 必须原有界有效的 paid/explicit_free 授权、限定输入/接收人、完成的研究 Task 和完整原 WorkExecution。逐原记录核对真实研究努力/内部费用与有限上限；收费工作需原有效费用义务，明确免费交流不产生无限改稿义务或隐藏收费。处理器不创建免费工作或伪造实际投入。

原 ConstructabilityMethod/ContractorCapability/WorkMethod 必须覆盖实际地区、工程对象和特殊条件，原 DurationEstimationMethod 显式绑定声明区间方法。工期仅从原工序时间区间、无环前置关系与明确独立投入假设计算最长路径上下界；未知不填零，循环/混合单位保持不支持。关键规模资料缺失时保留原 unassessed_scope Issue，工期保持未知，可提供其他有界意见。不猜工效，不乘通用复杂度系数。

每个原请求的方案或单独简报生成同版结果，保留实际方法、问题、假设、用途和有效条件；规模/结构/批次变化不套旧意见。SupplyAdvice 明确区分供应方有限意见与承包商估计，估计及其条件保留为假设，不替代供应商确认/报价/承诺。制造可行但现场接收未知或不可行时必须保留 site_receiving 接口问题，不把制造完成当交付完成。

propose_paid_study 只提出原有依据的限定努力/费用与条件，未知保留未知，不扣费或开工；decline 不带意见或研究提案残留。技术执行失败保持 technical_error，不变负面工程结论。所有结果均为前期意见，不能授标、预留队伍、承诺正式交期或放行施工。

CHECK-CONTRACTOR-018/019/020/021/022/023 待集中验证。真实研究授权/任务/执行/费用、供应意见与尺度工效资料生产者，正式提交/查询/接收和反馈恢复仍待集成；数学区间方法未做现实校准。
