# BANK-A12 保留判断、记录本行经验及修订未来策略

按本行当前权限/完整私有BankLearningState，核原观察、判断、结果和允许策略。retain_judgment允许未启用学习及结果未成熟，不制造经验或改历史。record_lesson/revise_strategy须所选LearningMethod、原本行已获知成熟核验结果和保存学习报告；未成熟保持未评价，不用未来或他行私有结果。

原BankJudgment保留当时预测概率、风险维度、事件与期间及原可知信息版本/摘要/获知时间；VerifiedOutcome必须绑定原判断内容与相同事件/维度/期间，Observation获知在核验可用之后。原已应用物理结果、重复事件/原business及未知执行分别核对，不在重启/新报告中重复记录同结果。

登记纯数学micro.bank.verified_prediction_error：对明确原概率和已核验二元事件按风险维度精确计算平均平方误差，分数用有理数保留，不作舍入。它只是误差摘要，不等于风险校准或证明有效学习；未知概率/结果不填零。输入/保存报告/原来源读权和时点复核。

策略修订仅原allowed_strategy_refs、BANK-A12有权未来策略及明确原学习政策/误差证据阈值；strategy_ref 还须在当前 CandidateSet 中明确允许 revise_strategy，输入可见或策略空间包含不自动扩大本次选择权限。原目的、条款、债务、现金和他行认知不改变。候选信号需本行原实际测量及同单位阈值。策略可由BANK-A01后续消费，专业校准/现实学习效果另验。

本批仅编码和静态检查，未功能验收。真实结果/判断/私有状态/政策生产者、跨动作投影兼容、正式认知/策略submit/query、一次经验应用与反馈尚待集成。

同一 business 的原 BankLearningProfile 必须与原 BankLearningExecution 的 organization_id、scope、business_key 一致，再核保存摘要及本次内容；执行 schema 没有 state_ref，不新增或推断这个字段，也不把历史 state 版本换成当前版本。装配/保存结果核已供应关联，普通恢复和终态归档同核原配置/摘要；普通恢复在 pending/unknown 前核配置，原已知终态不能退回等待。恢复条件升版 2 并固定实际 factory 源码，旧等待不静默迁移；已应用结果、原判断和已知信息继续保留。
