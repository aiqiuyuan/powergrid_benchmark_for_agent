# 前两步建设完成说明

**日期：2026-10-14；交付版本：v0.1-design。**

本次根据已有多组预实验，完成了能源领域算法演化 Benchmark 的前两步文档建设：**研究契约与任务范围**，以及**五个任务族的任务卡和统一评测契约**。同时整理了后续框架修复、任务实现和批量认证的顺序与验收标准。

交付仓库：[aiqiuyuan/powergrid_benchmark_for_agent](https://github.com/aiqiuyuan/powergrid_benchmark_for_agent)。

**发布核验：已上传至 GitHub 的 `main` 分支，并从 GitHub 独立下载核对全部23个文件；远端提交与本地一致，README存在，文件内容逐一一致。** 首批上传核验对象为提交 [29ab99a](https://github.com/aiqiuyuan/powergrid_benchmark_for_agent/commit/29ab99a236e5db1ba66db625d5d209bccb0cb58d)。本说明随后更新发布，最终交付另留完整提交号与复核记录。

## 1. 完成的任务

| 工作 | 具体完成内容 | 入口 |
|---|---|---|
| 中文 README | 项目目的、当前版本、五任务入口、共同生命周期、完成边界、后续六阶段顺序与公开政策 | [README](../README.md) |
| 第一步：研究契约 | 研究对象、五家族选择理由、主线/扩展、R1–R5问题、比较单位、公平预算、评分统计、版本与发布要求 | [研究契约](benchmark-spec.md) |
| 第二步：五张任务卡 | 每个任务是什么、演化什么、已有设置/结果、目标数据与接口、baseline/预算、验收与待定项 | [GOC](task-cards/goc-sc-ac-opf.md)、[UC/SCUC](task-cards/unit-commitment.md)、[RTE](task-cards/rte-maintenance.md)、[L2RPN](task-cards/l2rpn-grid-control.md)、[HEFTCom](task-cards/heftcom-forecast-trade.md) |
| 第二步：评测协议 | 四角色数据、分组切分、共同时钟、n计数、投递、选择、冻结、终评、失败和恢复 | [评测协议](protocol/evaluation-protocol.md) |
| 第二步：产物契约 | 可执行算法、完整摘要、依赖/权重/训练配方、提交幂等性、run/反馈/freeze记录与重放闭包 | [产物契约](protocol/artifact-contract.md) |
| 预实验事实统计 | 98槽位状态核对、各家族分数与实际预算、故障/修复边界、错误结论防护 | [中文预实验统计](evidence/preliminary-experiments-20261013.md) |
| 证据与来源 | 公开一手来源、内部脱敏证据标签、分级、曝光与可复现限制 | [来源索引](evidence/source-index.md) |
| 三个设计决定 | 五家族范围、反馈/留出、墙钟预算与可执行产物/恢复 | [决定1](decisions/0001-benchmark-scope.md)、[决定2](decisions/0002-feedback-and-holdout.md)、[决定3](decisions/0003-budget-and-artifact-policy.md) |
| 后续施工与验收 | G0–G4门槛、12项框架修复、逐任务交付、参数校准、契约测试与目标并发验收 | [实施与验收](implementation-plan.md) |
| 结构化声明 | Benchmark设计清单，以及task release、split、run三种JSON模板和填写规则 | [清单说明](../manifests/README.md) |
| 仓库维护 | 变更记录、避免误传数据/密钥/原始日志的忽略规则 | [变更记录](../CHANGELOG.md) |

本次文档包共 **23个文件：18个Markdown、4个JSON、1个.gitignore**。数量不包含 Git 内部文件，也不包含原始实验数据或私有框架代码。

## 2. 根据已有实验做出的关键决定

1. 核心建设五个任务族：GOC、UC/SCUC、RTE、L2RPN、HEFTCom。GOC多规模不重复计为独立家族；UC为核心、受限SCUC为扩展；GOC30000和AHC024不进入五家族核心总分。
2. 正式评测必须执行冻结算法处理留出输入。已有UC/SCUC静态调度和HEFTCom静态报价评分不足以证明算法泛化，这两类迁移均列为P0问题。
3. 公开开发、公开选择、受保护反馈和最终测试分开；旧暴露面板进入calibration，公开checker合法，保护的是面板和结果访问。
4. 采用统一开发墙钟T，准备完成后起算，训练、编译、本地评测、公开选择和反馈等待计入；不设累计token cap、不预留累计token、不按累计用量提前停止。
5. n为受保护评测作业受理上限；n=0禁止受保护反馈，明确修复旧内部0代表unlimited的歧义。受理、完成、投递、读取确认分别记录。
6. 默认在T内按公开selection选候选，到时冻结；最终测试不选模。ML主线只用public-development标签拟合，selection标签重拟合需要另立协议。
7. 故障恢复不增发预算；原样重试保留同一job；整体开发重跑属于新run/cohort。候选失败与基础设施缺失分开，合法零分保留。
8. 正式研究先通过框架与任务认证，再做n、agent组织与演化机制消融；资源、真实split、baseline与统计方案通过校准后冻结。

## 3. 已核查的范围

文档审查包括：五家族范围与相互引用、历史分数/计数、98槽位总账、n=0与时间/token语义、四数据角色、默认拟合/选择规则、静态答案迁移、幂等重试、冻结与最终执行、design与runtime状态边界。独立审阅已解决UC范围待定措辞、HEFT静态报价漏列和提交幂等键生成顺序等问题。

格式核查包括：UTF-8可读性、Markdown代码块、仓库相对文件链接、4份JSON可解析、5个唯一家族与权重、59+15+14+3+7=98、设计状态和待冻结字段。公开来源已核对；文档未复制上游数据/checker。

公开信息核查包括：不含私有机器绝对路径、内部端点、私有框架地址、访问密钥、集群身份、原始模型轨迹或未核验数据。GitHub上传只使用这个新建文档目录，不使用私有框架checkout的提交历史。

**这些是文档与发布检查，不是运行框架、物理评分正确性或task稳定性认证。** 没有新增演化实验，也没有执行新框架的端到端测试。

## 4. 当前状态与未完成事项

| 层次 | 状态 |
|---|---|
| 前两步的中文文档、任务卡、协议与设计声明 | 已完成；设计要求明确、未知量单独列出 |
| GitHub发布 | 已上传main；独立下载与23文件内容核对通过，README可取得 |
| 历史证据 | 截至2026-10-13 23:32 UTC+8，修复准备至23:38；没有假设后来运行已成功 |
| 基础框架修复 | 本次未执行；待按F01–F12实施验收 |
| 五个可运行稳定任务包 | 本次未认证；需真实算法执行、切分/许可、基线、资源与checker校准 |
| 正式密封final-test与release | 尚未冻结；JSON占位不是真实数据清单或可执行配置 |
| 正式公平方法比较/排行榜 | 尚未建立；现有成绩保留为预实验/calibration |

以上边界保证“前两步完成”不会被误读成“基础框架与五任务已经稳定”。后者需要另外的实际实施、故障注入、目标并发和重放证据。

## 5. 下一步最优先做什么

先完成任务包完整性、共同时钟与无累计token cap、n=0适配、反馈账本/投递、不可变快照、截止冻结和算法执行这组P0问题。在低成本夹具和一个能源task上完成无模型闭环与真实模型往返，再逐个迁移五家族。

随后审计真实数据与许可、冻结独立切分、校准简单/强基线和资源；全部task通过清洁环境、非法产物、正n/n=0、重放与目标并发批次后，再发布正式Benchmark并开展研究。完整实施顺序见[实施与验收矩阵](implementation-plan.md)。
