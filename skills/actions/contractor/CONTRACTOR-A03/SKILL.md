# CONTRACTOR-A03 处理澄清、修改和撤回

读取己方原 Bid、原 SubmissionExecution、当前 ProcurementPackage/TenderRound、原 TenderAmendmentRule、收到的 ClarificationRequest 和完整本次临时 ResourceReservation。规则显式连接原包件/轮次与当前替代版本，保留通知接收时点、原模板的分支时限和拒收/待处理依据。己方选择沿原有权 ContractorRevisionProfile，不从问题或发送失败推断商业选择。

未知/待定发送先按原 command_id、报价及包件/轮次身份请求 query/reconcile，返回 deferred，不生成新发送或伪造回执；技术失败保留原关联身份。过期、迟交、拒收和待处理保留模板依据与续办条件。已拒绝报价仅允许按原模板提出撤回及本次预留处置。

explain 回答全部原问题，原证据有来源；纯解释不能改价/范围，发现范围改变或问题要求修订时转信息缺口，要求完整 revise。maintain 须读全部新要求且原模板明确允许维持有效旧版，只保留旧报价，不把旧报价自动套到新范围。

revise 使用完整已保存的原新包件量价/策略/施工方案输入，复用 A02 的纯报价核验，真实读取上下文与己方策略授权保持 A03。专业/成本/方案原作者保持各自原授权。新报价须可计价且完整核对原范围、资格、成熟度、工效/量纲/地区、全部当前真实队伍占用及方案覆盖，保留旧 Bid 与明确变更 Requirement。方法仅精确声明量价/商业参数和同地容量，无猜测价格或真实模型调用。

withdraw 只生成原报价撤回提案，核对全部己方本次临时预留。其他合同、已转换预留或其他报价不得纳入释放；实际释放由宿主依据有效拒绝/撤回结果执行，处理器不操作资源池。completed 只表示决定草稿，不代表提交已收、旧版已替换或预留已释放。

CHECK-CONTRACTOR-002/031 待集中验证。正式原输入生产者、submit/query/reconcile、拒收回执、原子替代/释放及反馈仍待集成。
