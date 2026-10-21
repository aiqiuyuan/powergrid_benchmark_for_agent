# 版本与来源索引

本目录依据 2026-10-20／21 已确定的合同整理；**不重新选择任务、baseline 或评分规则，不新增正式结果**。当前运行版本、共同起点、历史比较及公开程度分别记录。

## 1. 六项合同绑定

| 任务 | 采用的冻结版本 | Campaign／source manifest SHA-256 |
|---|---|---|
| GOC | `goc500-panel48-20261020-v5` | `4f42f1a6b1cf1f45b6c966af0928cf3fa22ae785b442a3b2607509501d51bc3f` |
| UC | `uc56-shared-48h-20261021-v4` | `a311e7829cdefa8e36ea9cba3a8301443c3d16691c9fb37ffb978be63121727c` |
| MAPDN | `mapdn-rl-cpu-formal-12h-20261021-v9` | `5e6e28bbf1be3982d19bace4967e5eccaec1a3d0f9ee282dbb9f4b051dcd6039` |
| L2RPN | `l2rpn-idf2023-gpu-rl-24h-20261021-v3` | `8f5c1988f53929f2d612431cc4940eda2007c792f18ccaf6366bec8011eab223` |
| HEFTCom | `heftcom-trading-replay-60h-20261021-v5` | `54b7a53b9ea9a08f7d581f6baaccd543a89892a26ebb45cb7f1dac67f6ca3248` |
| RTE | `rte2020-abc-x15-v2`；已有 ABC45/X15 实验 source | `75d9b480cc2105b6831991a8fd65249af5f26f13f90dd8b20f4597bca59fcd1b` |

哈希标识各自运行的完整清单文件，不是本目录任务卡的内容哈希。任务包标识、准备副本版本号和正式 campaign 号可能不同，逐卡解释其关系。RTE 沿用已有实验，当前历史积分展示是后验交付规则，不能追溯替换其开发期 reward。

## 2. 随本目录公开的最小资料

| 文件 | 内容 | 用途及限制 |
|---|---|---|
| [source-index.json](evidence/source-index.json) | 六项版本、开发资源／时限、来源文件 SHA 与公开摘录清单 | 来源快照目录；原始研究文件未一并发布，不把路径当成公开下载链接 |
| [goc500-panel.json](evidence/goc500-panel.json) | 精确 20 个 scenario、每例原始故障数、两阶段及 grader 时限、原始归档 SHA | 确认同网络完整面板；不含历史答案或当前候选解 |
| [uc56-panel.json](evidence/uc56-panel.json) | 56 个精确公开输入名、原始 SHA／Git blob、机组规模、family、seed 与采用的 E2E 时限 | 来自正式开发所用清单的语义投影；仅将原 `proposed_e2e_limit_seconds` 改名为现行 `e2e_limit_seconds`，不更改实例或输入哈希 |
| [mapdn-baseline-anchors.json](evidence/mapdn-baseline-anchors.json) | 已固定作者 baseline 的训练预算、同面板方法均值与归一化定义 | 公开既有 baseline 定标依据；不含新正式智能体结果，不公布受保护测试日期或轨迹 |
| [rte-historical-x15-reference.json](evidence/rte-historical-x15-reference.json) | 原 13 队 X15 双档参照、公开工作簿 SHA、149／6 固定积分端点 | 从既有可信参考文件原字节复制；只用于历史积分核算，不向开发沙箱安装答案 |

公开摘录均不含模型服务凭据、私有运行配置或正式开发轨迹。其 source hash 指向用于整理的本地文件快照；原始 mutable 报告的 hash 与不可变 campaign hash 是不同层级。L2RPN baseline 原始资源由正式配置固定为 SHA `c7be5b76aca7ee3138fc4a9291633fb108bffd52d2706cf44f7d4d155c3bb618`，本地未包含原始资源文件，本目录仅公开卡内锚点及来源绑定，不声称附有该原文件。

## 3. 一手公开来源与比较角色

| 任务 | 原始资料 | 本次使用方式 |
|---|---|---|
| GOC | [ARPA-E Challenge 1 官方归档](https://data.openei.org/submissions/6153)、[官方评分](https://data.openei.org/files/6153/Challenge_1_Scoring.pdf)、[最终逐场景工作簿](https://data.openei.org/files/6153/C1_E4_scenario_results_20200106.xlsx)、[PMSC 上游](https://github.com/lanl-ansi/PowerModelsSecurityConstrained.jl) | 原问题、数据及目标；同完整网络的 Benchmark／gravityx 历史尺度；PMSC 用于共同 starter 的故障路径 |
| UC | [固定 PGLib-UC revision](https://github.com/power-grid-lib/pglib-uc/tree/39a7f38cf4703de92f0291f0c873c2e98c789301)、[固定 EGRET 实现](https://github.com/grid-parity-exchange/Egret/blob/28c324f9bf4fb3913b0a60dba3dd732b46084c3b/egret/models/unit_commitment.py)、[作者论文](https://doi.org/10.1287/ijoc.2019.0944) | 公开 56 例和六种 formulation；在共同 HiGHS 上重构重评，不复用历史 Gurobi 计时 |
| MAPDN | [作者源码](https://github.com/Future-Power-Networks/MAPDN)、[论文](https://arxiv.org/abs/2110.14300) | 原生环境、局部权限、L1 算法；新日期划分和相同面板评价，不把 Table 3 成绩代填新测试结果 |
| L2RPN | [LJN 公开代码／权重](https://github.com/lajavaness/l2rpn-2023-ljn-agent)、[固定 Grid2Op 观测实现](https://github.com/Grid2op/grid2op/blob/v1.10.0/grid2op/Observation/baseObservation.py) | 三个原生合同 baseline、共同初始权重、合法动作／simulate 语义；保留原生不完全可重复的证据边界 |
| HEFTCom | [组织方代码](https://github.com/jbrowell/HEFTcom24)、[原赛分析代码](https://github.com/jbrowell/HEFTcom24-Analysis)、[官方归档](https://zenodo.org/records/13950764)、[原赛回顾](https://arxiv.org/html/2507.01579v2)、[GEB 源码](https://github.com/BigdogManLuo/HEFTcom24) | 原赛 Trading 结算及归档报价；GEB 来源的因果适配共同起点；历史输入到达和整季反馈按当前协议披露 |
| RTE | [官方实例／checker](https://github.com/rte-france/challenge-roadef-2020)、[官方决赛](https://roadef.org/challenge/2020/en/finalresult.php)、[X 工作簿](https://roadef.org/challenge/2020/en/compiler_X.xlsx) | ABC45 开发、X15 反馈与双档终评；独立对照原 13 队的固定 X15 积分 |

## 4. 当前运行证据的定位与公开范围

下表路径属于研究工作区，未随本次目录提交；用于持有相应档案者核验。公开读者应以任务卡、以上公开摘录和官方来源为入口，不能假定这些路径存在于 GitHub。

| 任务 | 本地研究证据根 | 主要核对对象 |
|---|---|---|
| GOC | `plan/goc500-panel-evolution-20261020/` | 当前 instruction 生成器、panel／feedback／comparator、完整报告访问校准、v5 放行绑定 |
| UC | `plan/uc56-formal-evolution-20261020/` | v11 public-app 科学合同、正式 v4 报告、保留原失败的 504 条校准、增量验收与资源协议 |
| MAPDN | `plan/mapdn-rl-formal-release-20261020/` | CPU v9 实际外层配置、三次真实完整测试、作者 baseline 继承与权重来源 |
| L2RPN | `plan/l2rpn-idf2023-gpu-rl-20261021/` | GPU 训练导出、清洁训练划分、原生合同比较、实际 104 周数值 Job 回执和 final v3 资源 |
| HEFTCom | `plan/heftcom-trading-release-20261020/` | 原赛恢复、到达假设、完整增长数据重训校准、60 h／9 h 资源决策和 v5 同源门禁 |
| RTE | `plan/rte-abc-x15-task-package-20261020/` 与已有正式源 | v2 逐例反馈、原 checker／数据资产、双档终评、历史积分交付；无本轮重提交 |

这些记录包含准备与验收，不等于新正式运行全部完成。当前部分完整运行闭包、数据／镜像资产及评分服务未以公开可执行 task-package 发布；本次仅发布 `docs/task-cards-v3`。后续公开执行包或正式结果时，应新增明确绑定与可用入口，保留历史失败、修订和原始合同。
