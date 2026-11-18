# BANK-A11 分别关闭未用承诺、已清范围并保留剩余义务

核本行当前权限、完整原core安排/债务/未用承诺/在途执行/担保/事项和原有权CloseoutProfile。retain/close_unused/close_cleared_scope三分支；原输入pending_execution_refs只当前未知/在途/部分执行，unused_commitment_refs只当前未用承诺，unresolved_refs只未结事项；空未用列表仍允许已清范围核对，不把历史已完成执行混成pending。所有原历史仍读账本并保留。

原本金/利息/费用/承诺费每物理组成、当前账本、实际付款/抵扣及完整现时未清余额分别核对；同现金事件不重复清偿。RemainingObligation由core原源引用/内容摘要提供，完整保留实际未清或未知债务、承诺、担保、交易、事项，漏列不能清债。retain保持未知与尾项并继续调度，项目完工/移交/会计核销不是债务清偿。

完整付款历史中每个原command_id/business_key只能出现一次；已成功命令仍需原回执。每笔回执须同业务时钟，实际生效不晚于核实，核实不晚于来源可获及本次业务时点；未满足时先补原核实资料。原实收须同币种且严格为正；本金效应须指向本安排精确版本的原本金组成，组成不重复、金额非负且合计不超原实收，不把利息/费用或其他安排当本金。终态归档按原等待时点重核同样约束，不能用后来核实的记录补成原已知事实；归档仍不产生清偿、额度或担保释放。终态reader升v2，固定原账本检查及共享终态检查的实际实现摘要，旧声明不静默迁移。

close_unused只有效原未用金额、到期或有权撤销/释放条件、当前来源摘要/读权核验的release candidates；未知执行占用先按原身份查询，其他独立范围可保留，共享整项承诺不按局部直接释放。close_cleared_scope须具体原范围内全部本金/利息/费用已清、截至现在计息完整、在途已核对及事项关闭；附属担保按原有权独立释放条件，不自动随额度到期释放。原无未用承诺仍可关闭已清范围。

原business沿原调用身份续办。completed仅关闭提议，核心从原承诺/未知执行/义务算可释放量，实际生效前剩余源记录继续保留，历史不删除。本批只编码/静态检查；实际生产者、跨动作投影兼容、正式submit/query、原子关闭/释放及回执反馈与功能验收尚待完成。

同一 business 的原 FinanceCloseoutProfile 必须与原 FinanceCloseoutExecution 的精确 arrangement_ref、organization_id、scope、business_key 一致，且 profile.scope_ref 等于 execution.affected_scope，再核保存摘要及本次内容。当前安排版本不替换历史执行。来源装配/保存结果核已供应关联，缺历史仍由动作处理器处理。普通恢复先核原配置/摘要/可获时点，PaymentExecution 保留独立现金回执路线；终态归档同核精确关闭范围。恢复条件升版 2，并固定实际 factory 和共享 finance helper 源码，旧等待不静默迁移。
