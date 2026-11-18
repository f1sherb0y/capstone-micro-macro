# 数据

本目录完整保留原数据目录：项目明细Excel、企业资料Excel，以及项目、企业、历史关系和匹配报告CSV。历史结果标签只用于训练允许范围或事后评价，不能作为待评价项目的输入答案。

CSV位置：`test_sources/casebank_enterprise_matched/`。数据资产为352项目记录、904企业和499历史关系行；433个有效项目与角色单元用于历史匹配评价。

`validation/full_352_cases/data/` 与紧凑验证包的数据也已保留。宏观运行数据库在 `vendor/gba/data/processed/agent_database.sqlite`，约2GB，使用Git LFS；它包含模拟状态，不把其中后验信息当现实招标前事实。

缺失字段保留未知，不能当作无能力、已具备或零风险。
