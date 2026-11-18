# 组员接手与完整克隆检查

本仓库按完整项目交接整理。组员需要Git、Git LFS、Python 3.12及uv；无需原作者的虚拟环境或旧 `codedemo_v2` 目录。

```powershell
git lfs install
git -c core.longpaths=true clone https://github.com/XiongBT49/capstone-micro-macro.git
cd capstone-micro-macro
git config core.longpaths true
git lfs pull
uv sync --locked
uv run python capstone.py doctor
uv run python capstone.py data
uv run python capstone.py results
uv run pytest tests -q
uv run python capstone.py micro-demo
uv run python capstone.py macro-demo
```

`doctor` 应显示空的missing和asset_errors列表，以及 `independent_root: true`。数据应为352条项目记录、904条企业记录，另有两份499行的关系/匹配CSV。`results` 应能找到已索引的原始文件。

宏观数据库应是约2GB的真实SQLite文件，不能是百余字节的Git LFS指针文本。`macro-demo` 使用新的可写数据库副本并在第1步保存检查点；完整48步入口为 `macro-demo --full`，耗时更长。

两个demo均采用离线模式，不需要模型密钥，不能用作新的研究效果结果。真实模型实验需要组员自行配置本地 `.env`；密钥不会随仓库分发，暂停的旧实验不会自动恢复。

迁移时的原始完整工作区检查见[历史验收](verification.md)。本次远程克隆的实际验收结果如下。


## 实际验收结果（2026-11-15）

| 检查 | 结果 |
|---|---|
| 独立完整副本回归 | 512项全部通过；使用独立环境并拦截外网 |
| GitHub全新克隆 | 成功，下载10个LFS对象，共487,840,688字节 |
| LFS未下载时检查 | doctor明确拒绝指针文件，提示执行git lfs pull |
| 数据库首次还原 | 成功，原始大小2,086,227,968字节，SHA256与原件一致 |
| 原始载荷完整性 | 对15,635项迁移清单逐项核对适用载荷；适配文件和明确未分发的行政/缓存文件单列排除，无哈希错误 |
| 已有结果索引 | 所有索引原件均可找到 |
| 微观离线示例 | 完成，336条讨论、28份投标文档、4个包的决策 |
| 宏观离线示例 | 原生执行到第1步，生成结果与检查点；未宣称重新运行全部48步 |
| 原始数据库保护 | 示例结束后仍与原件SHA256相同，运行写入位于独立副本 |

测试代码提交为 `6d34bff`，其后仅补充交接记录。机器可读摘要见[交接检查记录](../provenance/team_handoff_checks.json)，完整回归记录见[JUnit结果](../provenance/team_handoff_tests.xml)。本次没有新增真实模型调用或研究效果结果。
