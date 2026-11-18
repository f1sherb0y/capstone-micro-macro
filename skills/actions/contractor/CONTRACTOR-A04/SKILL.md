# CONTRACTOR-A04 判断授标与形成合同承诺

读取同版 ContractOffer、ContractTerms、原 Bid/提交身份、己方明确 ContractFormationProfile 和独立 Authorization。核对真实采购方与承包方、当前未替代包件/轮次、原报价身份及响应窗；原提交未知先按原 command_id 核对，不机械重发。原报价失败保留技术错误。

accept 必须己方 explicit_acceptance 为已知真，选择与明确接受冲突保持信息缺口；offer_ref 必须在当前 CandidateSet 中明确允许 accept，收到授标条款不自动扩大候选权限，空候选不签约。独立核对全部最终支付/工期/设计/责任条款及完整协议摘要；价格变更须同源明确 ContractChangeRequest，范围/设计/方案改变须完整新报价。counterpart_acceptance_refs 可为空，仅表示尚无对方有效接受；旧版、撤回或非同摘要决定不形成接受。每个已收到有效对方决定须独立角色、授权、run、组织、时点及明确结果一致。

精确核 RoleAssignment.function_ref；己方权限覆盖完整最终条款，报价/方案/接受作者权限覆盖各原记录完整范围。对方接受范围须与最终条款一致，其证据及原作者 grant/function 的 Evidence 依据按真实 decided_at 核有效窗，不能以 historical 标记跳过当时有效性；决定≤可获≤当前且同业务钟。其他类型授权依据按原类型有权解析并保来源引用；当前接受使用窗、己方权限和资金/资质/资源条件保持独立。报价和方案无独立作者发生时点，保原 available_at 检查，不补造作者时间。

按当前完整跨项目 ContractorCapacity 重新核对地区/工程资格、原真实 ResourcePool 总量、全部原 ResourceCommitment 和原报价所有拟分配。每个物理队伍分别核算全部叠加需求，不复制容量、不按遍历顺序超配；只产出拟分配，不永久锁队伍。最终合同窗口覆盖原方案的所有分配且不倒填过去投入。

原 FundingPosition 和 FundingSource 必须完整且为当前时点；从实际余额扣原受限现金，原许可用途显式覆盖本合同。原已有义务、可用未来收款、全部合同付款和本合同工作成本逐 SettlementComponent 排重、核对原金额和时点；现金计划覆盖原报价所有成本，不用报价收入当作当前现金。复用精确现金日历按每账户每时点核算，未来收入只在原到期时、明确允许的规划假设下参与，不跨账户/币种借用，不当作实际收款。

跨已有/拟议、支出/收入的整组现金流按 SettlementComponent 的 kind/id 排重；同一原组成不同 version 也不能重复计入现金日历或报价成本覆盖。装配与保存结果复用同一已供应来源校验；缺少可选原投影不补造现金流或组成，仍交原处理器读取。

revise 只输出同源明确 requirement_changes，reject 不带接受/分配残留字段。资源或资金不足返回信息缺口，要求己方明确调整，不自动替人签约或拒绝。completed 只表示决定可提交；签署/生效/施工放行条件、共享队伍竞争、有效拒绝后的本次临时预留释放、合同/承诺登记由宿主统一提交核对。

CHECK-CONTRACTOR-003/004/030/031 待集中验证。真实投影生产者、跨角色Offer/ContractOffer与条款兼容、正式submit/query、原子竞争/预留转换或释放及反馈仍待集成。
