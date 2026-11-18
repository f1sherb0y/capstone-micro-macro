# 有据 Architect 调查工作估算

`micro.architect.declared_research_estimate@1` 仅供 ARCHITECT-A13。原工作数量 q 与每工作单位工时 e 相乘得到工时 E=q×e；原每工时价格 p 与固定费用 f 得到费用 C=E×p+f。复用 Engineer 调查估算的精确数学实现，角色方法声明独立。

数量与每单位工时须为正，费率和固定费用非负。数量单位须匹配声明的工作单位，工时单位须匹配费率的工时单位；费率和固定费用同币种。使用 Fraction 与 exact_decimal，不进行单位/币种转换或舍入。保原 WorkProfile 和全部数值 Evidence 引用；工时 basis 保每单位工时依据，费用 basis 保费率依据，报告另保完整 source_refs。

输入源须独立提供原工作数量、工时、费率、固定费用，并限定设计类型、地区和 investigation/preparation 目的。宿主须核当前授权、原研究委任、数值适用范围及剩余额度，不能猜测生产率、现场条件、日历、工期或市场价格。数学结果不产生调查任务、资源占用、实际投入、收费权利、现金或专业认可。与原请求的费用/工时及依据不一致时不能作为原请求结果。
