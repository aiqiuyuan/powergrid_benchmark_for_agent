# 证据与公开来源索引

本索引用于区分公开问题定义、已核验的内部实验事实和未来设计要求。预实验摘要见[2026-10-13 快照](preliminary-experiments-20261013.md)；目标合同见[Benchmark 规格](../benchmark-spec.md)和[评测协议](../protocol/evaluation-protocol.md)。

## 证据分级

| 分类 | 含义 | 可以支持的结论 |
|---|---|---|
| P：公开一手来源 | 数据发布方、原赛题或官方 checker / 仿真平台 | 问题定义、公共数据入口、原始检查语义 |
| R：运行产物只读核验 | 当时配置、完成记录、正式评分、导出审计的固定快照 | 某次运行的状态、成绩及实际预算记录 |
| L：本地实验归档 | 批次分析、已归档结果与任务说明 | 历史汇总、故障背景；与 R 冲突时需逐条核对 |
| A：修复准备记录 | 本地检查、代码审查、验收提交记录 | 修复准备已经发生；不能证明远端完整验收已通过 |
| D：设计判断 | 从观察推导的任务选择与协议要求 | 说明为何采用目标设计；不是实验观测事实 |

内部原始证据由项目私有归档保存；本仓库不公开原始轨迹、访问配置、私有框架代码或实验数据。下面的“来源标签”是**脱敏归档索引，不是本仓库文件链接**。公开读者可以核对上游问题定义，但无法仅凭本仓库重新计算内部历史结果。因此，摘要不能替代正式 release 应有的公开可复现产物。

## 公开一手来源

链接核对日期：2026-10-14。历史预实验使用的适配、版本和划分以冻结记录为准，不能由当前上游主分支反推。

| 编号 | 任务 / 组件 | 来源与用途 | 使用边界 |
|---|---|---|---|
| P01 | GOC Challenge 1 | [DOE / Data.gov 数据目录](https://catalog.data.gov/dataset/arpa-e-grid-optimization-go-competition-challenge-1)；[问题定义 PDF](https://data.openei.org/files/6153/Challenge_1_Problem_Formulation.pdf)；[评分文档 PDF](https://data.openei.org/files/6153/Challenge_1_Scoring.pdf) | 上游 SC-AC-OPF 与公开合成场景；不能把本项目结果称为官方参赛排名 |
| P02 | GOC evaluator | [GOCompetition / Evaluation](https://github.com/GOCompetition/Evaluation) | 官方解文件检查实现；公共源码可用性本身不等于信息泄漏 |
| P03 | UC | [Power Grid Lib / pglib-uc](https://github.com/power-grid-lib/pglib-uc)；[模型定义](https://github.com/power-grid-lib/pglib-uc/blob/master/MODEL.pdf) | PGLib-UC 的实例与标准模型；本项目 SCUC 适配应另行说明 |
| P04 | RTE maintenance | [RTE / ROADEF 2020 数据、规则与 checker](https://github.com/rte-france/challenge-roadef-2020)；[checker 源码](https://github.com/rte-france/challenge-roadef-2020/blob/master/RTE_ChallengeROADEF2020_checker.py) | 检修排程与风险目标；本地有界 reward 是适配，不是原比赛名次分 |
| P05 | L2RPN / Grid2Op | [Grid2Op 官方文档](https://grid2op.readthedocs.io/en/latest/)；[平台源码](https://github.com/Grid2op/grid2op) | 电网顺序决策平台；正式 task 仍须固定场景包、backend、动作及评分版本 |
| P06 | HEFTCom | [HEFTCom24 发布方仓库](https://github.com/jbrowell/HEFTcom24) | 预测与交易任务及工具；本项目历史回测划分不等于官方在线比赛协议 |
| P07 | AHC024 | [AtCoder Topological Map 原题](https://atcoder.jp/contests/ahc024/tasks/ahc024_a) | 非能源框架测试，排除于五个核心能源任务族之外 |
| P08 | GOC原赛最终名次与阶段数据 | [官方Final Event工作簿](https://data.openei.org/files/6153/C1_E4_scenario_results_20200106.xlsx)；[原始数据归档](https://data.openei.org/submissions/6153)；[评分规则](https://data.openei.org/files/6153/Challenge_1_Scoring.pdf) | 区分全量/合成榜及Division；Dataset2旧文字与当前归档数量冲突已在任务卡注明；不补造Division3/4名次 |
| P09 | UC原始公开实例 | [PGLib-UC固定版本](https://github.com/power-grid-lib/pglib-uc/tree/39a7f38cf4703de92f0291f0c873c2e98c789301)；[UnitCommitment.jl 0.4实例目录](https://anl-ceeesa.github.io/UnitCommitment.jl/0.4/guides/instances/) | 56例公开UC实例、MATPOWER派生SCUC来源；实例库没有本项目意义的原赛排行榜或密封train/test |
| P10 | RTE原赛总榜与A/B/C/X | [官方决赛榜](https://roadef.org/challenge/2020/en/finalresult.php)；[实例页](https://roadef.org/challenge/2020/en/instances.php)；[实际赛程](https://roadef.org/challenge/2020/en/calendrier.php) | 13队总榜、每组15例；C赛前公开、X当时隐藏现在公开；奖项与积分榜区分 |
| P11 | L2RPN 2020 Robustness原赛 | [CodaLab竞赛25426](https://competitions.codalab.org/competitions/25426)；[组织方回顾论文](https://proceedings.mlr.press/v133/marot21a/marot21a.pdf)；[公开环境说明](https://grid2op.readthedocs.io/en/latest/available_envs.html#l2rpn-neurips-2020-track1) | 采用2020最终榜而非Legacy；隐藏24周终测与本地留出不同；当前容量不证明原赛包哈希 |
| P12 | HEFTCom原赛最终榜与实时数据 | [官方leaderboard CSV](https://zenodo.org/records/13950764/files/overall_leaderboard.csv?download=1)；[原赛文档v4.0](https://zenodo.org/records/13950764/files/Competition%20Documentation%20v4.0.pdf?download=1)；[组织方回顾论文](https://arxiv.org/html/2507.01579v2) | 区分预测/交易/Combined；2024实时赛期及0–1800MWh边界不同于本地历史回测/报价限制 |
| P13 | MAPDN | [固定源码6895f1f](https://github.com/Future-Power-Networks/MAPDN/tree/6895f1f0630b112745a3f681d7685d454407f9cb)；[论文](https://arxiv.org/html/2110.14300v5)；[固定数据版本](https://huggingface.co/datasets/hsvgbkhgbv/Multi-Agent-Power-Distribution-Networks/tree/a41d8c269e402a827d36d9a153a4bce73a990e53) | 2026-10-15核查；源码/小方法探针与数据元数据，不是完整潮流或早期论文复现；实际网损与无功代理分报 |
| P14 | PowerGym | [固定源码c9fc6d8](https://github.com/siemens/powergym/tree/c9fc6d8357308a1f2bd2389474b56089c2a6bd78)；[论文](https://proceedings.mlr.press/v168/fan22a.html)；[维护者关于PPO/SAC代码的说明](https://github.com/siemens/powergym/issues/4) | 2026-10-15核查；明确SOC/数据打包/单例与设备语义，未复现PPO/SAC或完成OpenDSS物理核验 |

这些入口用于说明来源；本次规格提交未复制上游数据或 checker。正式数据与代码发布需分别记录上游版本、许可、归属及项目适配差异。

2026-10-15补充的UC/SCUC一手论文如下；具体参数、原文定位和使用边界见[逐篇核对表](uc-scuc-literature-parameters-20261015.md)，研究结论见[UC卡第13节](../task-cards/unit-commitment.md#13-文献对齐的研究目标与配置2026-10-15)。

| 编号 | 来源 | 用途 |
|---|---|---|
| P15 | [Knueven等：On Mixed-Integer Programming Formulations for the Unit Commitment Problem](https://optimization-online.org/wp-content/uploads/2018/11/6930.pdf) | formulation、精度与预算的原始计算实验 |
| P16 | [Xavier等：Learning to Solve Large-Scale Security-Constrained Unit Commitment Problems](https://arxiv.org/pdf/1902.01697) | 学习辅助SCUC加速与质量保证 |
| P17 | [Sugishita等：Primal heuristics for Dantzig-Wolfe decomposition for unit commitment](https://arxiv.org/pdf/2110.12531) | 达标/证明时间与限时质量两种协议 |
| P18 | [Qin、Yu：Solve Large-scale Unit Commitment Problems by Physics-informed Graph Learning，v1](https://arxiv.org/html/2311.15216v1) | 固定时间内成本/gap比较与训练预算区别 |

同日原赛背景补充见五张任务卡第8节。数据规模以明确的文件清点或原始规则为依据，历史榜单只作背景和基线线索，不把本地成绩插入旧榜；本次没有重算完整竞赛榜单或重新构建其隐藏测试集。

## 内部证据摘要索引

2026-10-15第三步补充：用户提供的[公平排行说明Page](https://chatgpt.com/space/page_949f304b2f68819191df113e9be1b7d9)已读取，用作设计依据而非新增运行成绩；Page可能需要访问权限。[公平排行文档](../framework/fair-ranking.md)保留独立可读的决定和公开基线来源。新增本地可复核代码／测试与[验收摘要](framework-validation-20261015.json)属于基础软件证据，不追认历史实验或生产平台认证。

主快照为 2026-10-13 23:32（UTC+8）；GOC30000 的计算进度取自 23:19，修复准备记录至 23:38。类别组合表示交叉使用了不同证据，不表示所有材料均已公开。

| 编号 | 内容 | 脱敏相对来源标签 | 分级 | 核验范围 / 限制 |
|---|---|---|---|---|
| E01 | GOC500 三次修复补跑 | `GOC500/结果汇总.md`；`GOC500/final-result.json` | L + R | 三次正式 J、可行性、故障覆盖；历史导入错误与修复关系 |
| E02 | GOC793 反馈额度实验 | `GOC793/实验分析.md`；`GOC793/final-result.json`；`GOC793/轨迹审计摘要` | L + R | 14 次正式分数；n5-r1 收尾失败；部分信息隔离问题；n20 深度审计未完成 |
| E03 | GOC2000 三次运行 | `GOC2000/收尾结果.md`；`GOC2000/completed-audit.json`；`GOC2000/final-result.json` | L + R | 最终有效结果及 OOM / 导出失败背景；不确定根因保留不确定性 |
| E04 | GOC2312 镜像恢复 | `GOC2312/补跑说明.md`；`GOC2312/recovery/final-result.json` | L + R | r2 恢复已通过；旧“两次有效”汇总已过时 |
| E05 | GOC30000 新批与历史结果 | `GOC30000/状态核查.md`；`GOC30000/status-evidence.json`；`GOC30000/final-result.json` | L + R | 12 个去重槽位的状态；中间分数不当作终评；批数进度不是时间进度 |
| E06 | AHC024 六次重复 | `AHC024/结果汇总.md`；`AHC024/latest-status.json` | L | 两次 TLE 的合法零分保留；未确认具体超时根因 |
| E07 | L2RPN 小划分 | `L2RPN-small/实验结果分析.md`；`L2RPN-small/analysis-data.json` | L | 15 次分数与固定划分；不支持历史排行榜或反馈因果结论 |
| E08 | L2RPN 正式主比较 | `L2RPN-formal/complete.json`；`L2RPN-formal/finished.json`；`L2RPN-formal/export-audit.json` | L + R | 15 次开发、20 份策略、公开 select 成绩；final test 未测 |
| E09 | RTE 原批、新批及修复 | `RTE/combined-experiments.json`；`RTE/verifier-result.json`；`RTE/reliability-plan.json`；`RTE/acceptance-plan.md` | L + R + A | 原三次有效、新包缺清单、验收提交；完整修复尚未认证 |
| E10 | HEFTCom 预算比较 | `HEFTCom/complete.json`；`HEFTCom/final-status.md`；`HEFTCom/time-only/README.md` | L + R + A | 五次收入、实际反馈与旧 token 守卫；无 cap 新版仅有本地验证 |
| E11 | UC / SCUC | `UC-SCUC/manifest.json`；`UC-SCUC/problem.md`；`UC-SCUC/final-status.json`；`UC-SCUC/result.md` | L + R | 静态排程与成本已验；求解代码未重放；SCUC 是受限适配 |
| E12 | 环境与产物迁移 | `operations/迁移进度与交接.md`；`operations/notes.md` | L + A | 用于区分来源和迁移风险；未证明新环境全链路可运行 |

## 冲突、更正与后续更新规则

1. 当旧摘要与明确的正式终态冲突，优先核对正式记录，并在新摘要说明更正。例如 GOC2312 r2 已修复完成；L2RPN 导出成功不等于 final test 成功。
2. 当调度器标签与实际进程状态冲突，以执行开始标记和应用阶段辅助判定，不能仅按作业标签计入“实际运行”。
3. 不把 A 类修复准备提升为完整运行成功；不把中间高分、旧代码补评或恢复补跑改写成原运行成功。
4. 后续结果追加带日期的快照，保留本次日期与冻结设置。目标无累计 token cap 政策不追溯修改旧实验。
5. 将公开公式、公开实例与受保护信息分别审计；需要明确的访问合同和行为证据，不能仅凭下载公共 checker 判为泄漏。
6. 本次所有成绩均用于校准任务难度、估计方差和确定基础合同。正式研究证据须来自完成认证的版本及另行冻结的 final test。

两题基础接入和验证范围见[配电网说明](../framework/distribution-control-integration.md)；[源码/数据锁](../../configs/distribution-sources.json)不等于已验收的依赖锁、数据许可或正式task release。
