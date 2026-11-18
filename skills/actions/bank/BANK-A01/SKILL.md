# BANK-A01 观察市场并管理融资组合

在本行经营时点读取当前 FinancePortfolio、LendingCapacity、完整原到期义务、可见 MarketObservation/PolicyObservation 和明确 LendingStrategySpace。不读取他行私有组合，不复制容量，不把策略变动当作释放已有承诺。

资金成员核对原 reserved/committed 占用身份、金额及明确 released 证据，原义务按实际 due/paid 保留；义务阈值用于明确经营政策判断，不作为抵销承诺的现金。政策成员核对原 Observation 的接收方、时间、范围和政策允许集合。所有市场/政策输入按源声明完整读取，未知不补零。

先核对本行当前策略是否仍满足独立授权、适用窗口、政策、当前剩余容量、原到期义务阈值及逐维信号。满足时 retain_strategy 不依赖新候选。需要调整时，只考虑明确登记并授权的 profile，按声明优先级选择；并列、阈值跨界或未知资料进入有来源的 investigate。候选未定义或方法/单位不支持保留 unsupported，不用语言猜新策略或模型参数。

成员只能比较配置中的逐维阈值，不允许综合分抵销硬条件；金额采用精确数值，跨币种/单位没有默认转换。这些是确定性经营政策检查，不宣称金融预测、信用校准或专业工作已登记。

合法输出为 retain_strategy / revise_strategy / investigate，均保留原 Ref<Observation> basis_refs。revise_strategy 仅输出原允许 profile；investigate 保留原 Issue 和本行 Scope，实际调查工作和资源仍需正式入口。note 不藏金额、权限或隐式条件。

completed 仅产生经营决定，不更新存量合同利率、撤销承诺、释放预留或形成贷款；策略生效、资源安排、并发容量竞争及后续反馈由正式宿主核验。新业务政策须明确 applies_to，已有条款修改标志必须为 false。
