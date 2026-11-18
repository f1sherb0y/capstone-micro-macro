# OWN-A05 · 制订资金计划并选择融资安排

根据本次授权的 OwnerA05Input 制订本方资金决定。支持自有资金、首次申请、接受同版报价、协商、缩减或延期和不融资。仅使用当前运行的授权投影，不将组织标签、投资授权、预测收入或旧建议当作借款资格、现金或接受。

先核对组织、真实借款主体、范围、当前资金计划版本、现有债务引用及业主动作授权。Owner 与 borrower 不同时，申请、借款接受、协商或使用借款人资金还需代表借款人的 OWN-A05 授权；投资授权不能替另一法人借款。成员由业主财务核对现金/债务，项目职能核对范围/用途/时间，合约职能核对同版条款及授权，再由宿主校验决定。

所有授权须与实际RoleAssignment的精确职能ref及原动作角色对应；grant/function的Evidence依据按各次授权实际时点核有效性，其他种类保原schema经当前有权读取，不强制当Evidence。有权条件核验人还须对该条件全部evidence_refs具精确读权，核完整条件scope，不以已读到证据代替作者原有权限。

首次 apply 不要求已有 FinanceOffer、正式项目或有效融资安排。核对 FinanceApplicationDraft 的借款人、银行、范围、目的、正数申请额、产品候选及披露依据，输出草稿交正式申请入口登记；Bank A02 独立受理。

own_funds 从实际账户减受限金额，检查同版来源、资金限制、完整现有债务和跨项目未清义务。FundingLine.available 是预测，禁止当实际现金或重复计入余额；未知预测原样保留，不补零，也不阻断已有完整实际余额和支出依据的现金判断。已知预测仍核验币种和依据。相同账户不得包装成多个来源；未来已批准收入按原时点计入，未批准 forecast 不计入。已经收到的收入不得再加到期初余额。逾期义务保留其原身份并在当前日历扣除，不能由未来放款追溯消除迟付。

accept_offer 核对 lender、borrower、application、product、purpose、principal、tenor、pricing、fees、repayment、conditions、validity 全部属于收到的同一报价版本。报价须有效、Bank A04 有权发出，产品适用；条件由相应有权职能核验。费用和还本规则只能引用该报价，禁止混搭别家或新版条款。模拟报价的条件性全额提款及全部还本、利息、费用时序，检查跨项目现有义务和完整新支出，再按明确费用上限及业主优先级选择。明确指定的旧报价失效时不自动换成另一银行。

新报价及既有安排的原报价依据按issued_at核；既有安排的两方接受依据按各自accepted_at核；有权条件核验依据按verified_at核。原时点须同业务钟且不晚于本次业务时点，不以晚获知或当前时间替代原签署/核验；当时有效现在到期的依据保历史效力，当时无效不能事后追认。条件自身有效窗仍覆盖本次使用/约定release时点，原核验授权仍在verified_at核。新选择仍须当前报价status/validity、生效产品和本方权限；既有签署安排不因原报价后来到期而自动消失，实际安排状态、条件、未提款额和原有债务分别核对。

实际银行报价接收入口须经当前授权逐项读取接收记录evidence_refs，按真实received_at核Evidence类型和有效窗；native登记证据也按同一实际接收时点核，仍须observed、原摘要及formal/fixture来源一致。先核原决定→报价发出→报价可获→接收→接收可获→当前时点同钟有序，不用现在有效追认当时无效接收证据。接收记录/报价本身仍须当前有效，真实宿主继续认证登记、当前报价/预留历史和合法披露；接收不等于接受。

银行报价原作者的grant和RoleAssignment须来自该Bank原source_reading并精确对应原context授权/Bank职能。全部basis须在原保存来源中存在并按原BankQuoteResultWorker实际source schema解析，Evidence核原A04决定时点；不要求业主读取银行当前私有依据来替代原授权披露档案。完整原记录/来源摘要及实际宿主合法披露认证仍必需，历史核验不扩大当前报价资格。

宿主 MethodRegistry 必须实际调用本动作声明的 financing_cash_calendar 和 declared_financing_selection 并保存审计，禁止直接绕过方法给出可行或最优结论。当前支持单币种、同一业务时钟、明确固定完整时序和全额提款，不自行换汇、搬移或复制地区余额、预测浮动利率、循环授信或部分提款；缺少相应路径/方法返回 unsupported。

negotiate 只针对明确选中的有效报价及本版未解决问题输出 OwnerQuestionDraft，保留真实 BusinessObject、Issue、Requirement 和 Evidence 引用。request 是询问，不隐含金额、授权或其他结构化决定。resize 只提交经授权、可行的范围缩减/延期草案；原借款主体、原项目债务、费用和未清义务不得消失。no_finance 不强制选择空报价，也不清除旧债。

资料未知返回 needs_information，等待外部依赖按明确策略返回 deferred，已知不可行按声明策略申请、改计划或不融资。technical_error、unsupported 与业务拒绝分别记录。不得在缺少账户/债务事实时假定零余额或零负债，不因没有银行自动认定自有资金足够。

输出严格使用 OwnerA05Payload。completed 只表示本方本次决定形成，不能生成 FinanceApplication、另一方接受、FinanceArrangement、借款本金、现金到账、付款、资源预留或回执。接受报价仍须 Bank A05 独立确认和正式入口执行；签署安排也不等于现金到账。现有安排的资金可用性须分别核对两方接受、条件、额度和生效时间。
