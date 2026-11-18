# ARCHITECT-A10 外部服务费与应收核对

claim/correct/dispute/reconcile/remind沿本方原Engagement、BillingClause、实际付款主体及独立A10权限。内部任务或同组织付款保持内部实际WorkFact成本归集，不能进入自我外部收费；本角色不写现金、合同接受或到期应收。

claim/correct要求已成功原FeeCalculation，绑定计费业务键/原条款/真实WorkFact和prior_claim。同币种固定/阶段/预付款或投入×原单价，按条款明确精度half_even复算，实际分片investment_key去重、阈值和条件有证满足、累计条款限额核对。已有同业务键先query，同一工作不能重复收费；内部成本不当计费金额。更正须原允许规则及明确依据，按同业务项替代总额，不另加一笔债务，不删除已发生收款，超收另走退款/抵扣。

dispute/reconcile/remind无需本次新计算但必须原本方FeeClaim；争议Question/ResponseRequirement保持原申报和合法接收者，催收须原已确认逾期且仍未收足，未收款不自动撤销已交成果或用途。收费争议与继续服务限制分别按合同核对，不以文本默增权利。

reconcile要求完整本行已收到原PaymentReceipt集合，逐原claim/engagement/付款人/真实收款方/execution/command/business/event/sequence核对。重复event同内容不重加，累计不倒退、增量逐事件，unknown/failed不得认实际正金额；原recognized_event_ids与已确认actual_received精确匹配。部分收款、未知结果及未清保留，超收不能抹掉现金或自动退款。

completed仅外部申报/更正/争议/催收/对账草稿；合同条件后核心才记录申报/确认/到期，资金核对回执才清偿一次。真实委任/计费条件/工作分片/计算/申报及付款投影生产者、跨动作兼容、正式submit/query、原子费用义务/更正/资金后果及反馈仍待集成。CHECK-ARCHITECT-026/029/031待集中测试；当前明确单币种固定或投入计费口径，不猜税/汇率/其他产品。
