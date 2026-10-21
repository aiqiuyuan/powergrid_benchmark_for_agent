# UC56：跨三类公开实例的共享机组组合算法

> 整理日期：2026-10-21（北京时间）。本卡记录当前正式协议、比较基线和资源预算，不汇总正式演化结果。

## 1. 当前版本与研究对象

开发一份可复用算法，在 **RTS／CAISO／FERC 的全部 56 个公开实例**上选择 formulation／solver policy，并可产生完整物理 warm start。每例重新执行同一冻结源码；不再只为一个 RTS 日期调优。

| 项目 | 当前配置 |
|---|---|
| 任务族 | `unit-commitment`，公开 copperplate UC，不含网络潮流／N−1 安全约束 |
| 输入面板 | RTS 12 例、CAISO 20 例、FERC 24 例，每例 48 个一小时时段 |
| 当前目标模型 | `paper-elastic-public-parser` |
| 开发矩阵 | `n ∈ {0,1,3,5,10}`，每档 3 次独立开发，共 15 次 |
| 数值 seed | 所有实例统一 seed0；三个开发重复不是三个求解 seed |
| 固定模型 | `bedrock/gpt-5.6-sol` |
| 当前冻结 campaign | `experiments/uc56-shared-48h-20261021-v4` |
| Campaign SHA-256 | `a311e7829cdefa8e36ea9cba3a8301443c3d16691c9fb37ffb978be63121727c` |
| 冻结 reference-bounds SHA-256 | `f279e455f1d030c839b07642cbc0a0afdd2269702559ffd78f4d747136b3840a` |

精确文件名、输入哈希和各例预算见公开[UC56 输入清单](evidence/uc56-panel.json)。

当前协议对应 2026-10-21 提交的 15 次共享算法开发。此前单 RTS 的 12 h 开发、三 seed 时间奖励、硬模型补评和历史 56 例固定算法重放均另行保留，不混作本实验的开发重复、主模型或评分规则。

全部 56 个输入在开发期公开，`held_out=false`。本任务衡量公开面板内的共同算法开发收益，不建立未见实例泛化结论；若展示 best-of-three，必须选择一份完整面板 artifact／开发重复，保留另外两次结果，禁止逐实例拼接。

## 2. 问题定义与模型语义

目标是在负荷、备用需求、机组初始状态和成本给定时，确定每小时启停、有功出力、备用及可再生出力。保留最小开停时间、启动成本、爬坡、启停爬坡、出力边界和 must-run 等原始物理语义。CAISO 保留全部 **610 台热机组，包括 200 台 must-run**，不删减为仅 410 台可调机组。

主模型允许显式非负 energy shortage／surplus 和 reserve shortfall，按小时计价：

$$\min C_{\mathrm{operation+startup}}+\sum_{t=1}^{48}\bigl[10000(s_t^++s_t^-)+1000r_t^{\mathrm{short}}\bigr].$$

每时段一小时，因此 MW 数量对应本时段 MWh。这里 `model_valid` 表示通过当前弹性目标模型的独立检查；`hard_feasible` 另行表示没有依靠平衡／备用 slack 逃避硬需求。**弹性模型有效不等于硬模型可行**。必须同时报告 operating cost、penalty cost、各类 slack 与 hard feasibility。

六种 formulation 统一显式弹性约束与一次每小时罚项，修正上游 copperplate helper 的 flag 处理及重复 mismatch cost；这些修正对 baseline 和候选对称生效。Tight／KOW 的 startup matching 按已验证适用条件作为原目标有效松弛；native objective／gap 不替代独立重建的物理目标和证明。Random2 证明权限限于受审的冻结输入域。

## 3. 算法接口、权限与共同起点

提交 `/app/submission/solver.py` 或 `solver.jl`；同时存在时选 Python。参数为 `INPUT_JSON OUTPUT_POLICY_JSON REMAINING_SECONDS SEED`，输出必须是新建 JSON 文件，源码闭包最多 **60 MiB／10,000 个普通文件，无链接**。

| 产出 | 合同 |
|---|---|
| Formulation／solver policy | schema `uc56-policy-v1`，选择 MLR／KOW／Tight／Compact／Random1／Random2 之一 |
| 允许的 controls | presolve、symmetry、restart、heuristic effort、伪成本可靠性阈值、节点上限；并行固定关闭 |
| 可选完整 warm start | schema `uc-elastic-schedule-v1`；全部 thermal on／power／reserve、renewable power、三类 slack 数组 |
| 可信后端 | 独立检查 warm start，构造完整未改目标并继续优化；warm start 作为 MIP start，不固定决策变量 |

候选不得更改约束／目标、加入未经认证的新 formulation／cuts、自报下界，或更改时限、线程、seed、目标 gap 与证明规则。研究对象是**通用 warm-start 启发式与 formulation／solver-policy 选择**，不能据此宣称实现新的通用 MILP solver。

开发端读取全部 `/app/cases/` 输入、`/app/panel.json` 精确文件名与哈希、公开 API 和静态校准表。允许按当前输入的负荷、成本及机组特征选择策略；禁止按储存日期／hash 派发预解，禁止逐实例储存答案和跨源码／重复选择赢家。

Python 3.11、Julia 1.10.11 和共同 HiGHS 1.15.1 可用。两种语言使用同一 policy schema、模型、后端、数值时钟及资源。数值候选无网络、capabilities 或进程创建权限，只能写全新输出目录；Python-to-Julia 子进程 wrapper 不属于支持入口。

全部 `n` 组获得相同 `Tight-initial-state-nodes0` starter 与静态校准表。它按初始热机状态／出力、可再生最小值和显式 slack 构造 warm start，使用 `mip_max_nodes=0`、`mip_heuristic_effort=0`。其完整面板弹性有效／时限内资格经过校准，但不保证硬需求满足、低成本或自身最优性证明。

自主依据公开规格实现本地代理／完整检查在所有组都允许，不消耗 `n`。私有可信 solver 实现、原始 solver vectors、模型指纹、服务密钥及其他运行结果不开放；官方反馈是单独计次通道。

## 4. 六个比较 baseline 与可比范围

六种冻结作者 formulation 为 **MLR、KOW、Tight、Compact、Random1、Random2**，来自 EGRET revision `28c324f9bf4fb3913b0a60dba3dd732b46084c3b`。Random1／Random2 是方法名，不是随机 seed。

| 比较维度 | 当前统一处理 |
|---|---|
| 数学输入／目标 | 同一 56 例、48 时段、弹性模型、初始条件与费用语义 |
| 求解后端 | 同一 HiGHS 1.15.1、一线程、seed0；按冻结版本取得可信目标界 |
| 执行预算 | 同一 1 CPU／16 GiB、RTS／CAISO 300 s、FERC 600 s 全流程时钟 |
| 检查／排名 | 相同独立验解、自身证明、固定参考界、完整面板聚合规则 |
| CPU 放置 | baseline／候选共用参与 worker 间的物理核与 SMT sibling 租约策略 |

这是**现代共同开放后端上的作者 formulation 重构重评**。它不等于复现论文历史 Gurobi 8.0.1 时间、未经统一核验的历史计时边界或原始 68 例集合，也不是官方竞赛榜单。

正式发布前冻结的静态记录共 **504 条 method–case 处置**：六 baseline `6×56=336`、两个原 whole starter `2×56=112`，以及当前 nodes0 starter 的 `56` 条补充。失败、OOM、超时和无证明均保留；原始参考界不随新候选或补充 starter 更新。该数量不是 504 次智能体开发，也不表示全部求解成功。

Baseline 与共同 starter 的用途不同：前者提供固定方法对照，后者提供所有 `n` 的共同起点。覆盖优先可能让“更多弹性有效、较少证明”的 starter 排名前移，不能据此解释为成本更低或证明更快。

## 5. 反馈计数、最终测评与指标

一次受理冻结一个不可变 source，对**全部 56 例**执行，消耗一次过程 `n`。相同源码及上下文的幂等重读、已完成报告读取不再扣额。算法崩溃、非法 policy、无 incumbent、数值超时及已证实算法 OOM 都保留失败行；基础设施未完成不能生成成功子集分数。

全部行处置完成后，摘要和报告原子开放。反馈有完整 56 行 JSON／CSV、family 汇总、model validity／hard feasibility、运行成本／罚分／slack、三类 gap、proof time、全流程／建模／求解／检查时间、资源与失败诊断及相对上次反馈变化。客户端 `/app/feedback.py BATCH_ID DIR` 校验全部公开报告文件／页的哈希。

`n=0` 无官方过程反馈 bridge，仍有共同公开输入、starter、静态表和自写本地检查。基础设施恢复沿用原请求身份、源码与数值预算，不增加新候选机会；截止后补齐的结果不能回流开发。

权威排名按完整 artifact 的词典序：

1. 最大化 `model_valid` 实例数。
2. 最大化拥有**自身可信目标相对 gap ≤0.01%** 证明的实例数。
3. 最小化 RTS／CAISO／FERC 等权的 fixed-reference gap 聚合。
4. 最小化三类等权的 capped proof time。

每例固定参考 gap 为

$$g_i^{\mathrm{ref}}=\frac{\max(0,UB_i-LB_i^{\mathrm{ref}})}{\max(|LB_i^{\mathrm{ref}}|,1)}.$$

family 内计算 `geomean(1+max(g_ref,10⁻⁴))−1`，三类结果再算等权算术均值，避免 FERC 例数较多就获得更大权重。Proof time 在 family 内及 family 间取几何平均；未证明实例计满额 300／600 s，包括提前算法失败。缺失 cost／bound／gap 为 `null`，不从完整统计中消失。任一实例缺少参考 gap 时，相应 family／macro gap 为 `null`，排名时按 `+∞` 处理；有效／证明覆盖相同且该项并列时再以 proof time 破同分，不能改用可用实例的子集 gap。

**自身证明、fixed-reference gap 和 native solver gap 分开记录。** 自身证明只接受完整未改 `highs.run()` 安全返回的可信下界，结合独立物理目标上界；内部 MIP-start／启发式回调下界不授予证明。固定参考 gap 用于成本比较，不授予自身证明；scalar reward 只作显示。若新有效解反驳冻结参考下界，进入 benchmark 审计，不靠截断掩盖。

开发停止后冻结唯一 source，再进行一次 **fresh 全 56 例终评**，不占过程 `n`，不允许终评后修改。保留全部三次开发重复和失败；best-of-three 只能选一份整面板程序。

## 6. 开发与数值资源

| 层次 | CPU | 内存 | 说明 |
|---|---:|---:|---|
| 开发 inner | 3 | 8 GiB | 无 GPU，无累计 token 上限 |
| 开发 dev outer | request=limit 4 | 20 GiB | 三槽 required anti-affinity，排除已确认不适用的 4 个节点，串行初始化 |
| 每例数值 inner | 1 | 16 GiB | no swap，单 HiGHS 线程，固定一个逻辑 CPU |
| 每例数值 center outer | request=limit 3 | 24 GiB | 包含候选、可信求解及检查的执行边界 |
| Campaign 并发 | 最多 12 个数值 Job | 最多 288 GiB outer 请求 | 每参与节点最多 3 个；满配 outer 请求 36 CPU |

参与 UC56 worker 的私有 CPU 租约避免相互占用同一物理核／SMT sibling；不保证与其他无关集群工作负载隔离。节点拓扑、CPU 用量／throttling、内存及耗时另留资源证据。

数值 Job 使用 **64 GiB node-local scratch emptyDir**，归档与执行分开。外层 ephemeral-storage request／limit 为 **128／256 GiB**，不代表物理磁盘空闲保证。采样峰值内存仅为连续真实峰值的下界。

## 7. 时间预算、校准与调用规模

| 时钟 | 当前配置 |
|---|---|
| 开发 | 172,800 s／48 h，包含 15 s freeze reserve，以及过程反馈排队／执行／读取；从实际安全开发开始计 |
| Token | `total_token_cap=null`；记录 provider 实际用量，无累计预留或 token 触发停止 |
| RTS／CAISO 每例 | E2E 300 s，含 15 s 结果证据处理预留 |
| FERC 每例 | E2E 600 s，含同样 15 s 预留 |
| 编排保护 | 数值运行 watchdog 1,200 s、排队保护 172,800 s；不增加可计分数值时间。开发 outer watchdog 518,400 s 也不是开发预算 |
| 截止后终评 | 独立全 56 例；开发时钟外另计排队、执行和归档 |

数值 E2E 包含候选启动、imports／Julia JIT、启发式、模型构建、完整求解和必要独立验解。上界在全部适用验解完成后才可计分，迟到证据不得补记。时钟终点是影响决策的结果对象计算完成；最终 JSON 序列化、报告复制、镜像／容器启停及清理另计。

`solve_seconds` 包含 `highs.run()` 中同步回调验解，不能与 verification time 当成互斥阶段直接相加；比较同时列 E2E、solver-stage、proof time 及超时诊断。

仅用于部署可执行性的已测时间：共同 nodes0 starter 的 family 最大 E2E 为 **RTS 15.370 s、CAISO 90.680 s、FERC 193.196 s**；后续两例生命周期检查为 **86.357 s、164.557 s**。这些是固定源码的校准／验收时间，不是新算法成绩、整批墙钟或最优性证明时间，不能据此推断提速。

按全部例子用满数值上限估算，一面板累计 `32×300+24×600=24,000 s`，即 **6.67 个一核数值小时**。12 槽持续可用时算量／并发为 33.3 min；考虑 300／600 s 分块，理想装箱约 35 min，再加启动、验收、归档和报告交付。共享排队或少于 12 槽时会更长；不作墙钟完成承诺。

| 调用规模 | 过程实例执行 | 终评实例执行 | 合计 |
|---|---:|---:|---:|
| 一次开发，预算 n | `56n` | 56 | `56(n+1)` |
| 五档 n 各 3 次，均用满 | 3,192 | 840 | 4,032 |

最大设计量是 57 个过程面板加 15 个终评面板，对应 **480 个一核数值预算小时**；不含校准、验收、基础设施恢复和启动归档。三个开发重复的 48 h 各自独立；完整 campaign 的排队／终评可延续至其后，不能用提交时间统一推算全部截止。

## 8. 来源与可复核范围

- 输入与原始模型：[PGLib-UC 固定 revision](https://github.com/power-grid-lib/pglib-uc/tree/39a7f38cf4703de92f0291f0c873c2e98c789301)。当前 56 例精确文件名、SHA、family 与时限由运行包 `/app/panel.json` 固定。
- 六种 formulation：[EGRET 固定作者实现](https://github.com/grid-parity-exchange/Egret/blob/28c324f9bf4fb3913b0a60dba3dd732b46084c3b/egret/models/unit_commitment.py)；Knueven、Ostrowski、Watson，*On Mixed-Integer Programming Formulations for the Unit Commitment Problem*，[DOI](https://doi.org/10.1287/ijoc.2019.0944)。
- 当前实现与证据定位：研究工作区 `plan/uc56-formal-evolution-20261020/` 的 `formal-experiment-report.md`、`build/formal-assets-v11/public-app/{problem.md,docs/policy-contract.md,docs/feedback-contract.md}`、`src/orchestration/` 和冻结校准记录；精确实例清单来自 `plan/uc-family-evolution-design-20261020/panel-manifest.json`。
- [v2 任务卡](../task-cards-v2/unit-commitment.md)仅保存历史单 RTS 协议；本卡已经用共享 UC56、弹性模型及当前证明指标取代它作为本阶段设置说明。

当前 campaign 是研究运行的冻结闭包，尚未作为本公开仓库的独立 UC56 task-package 发布。本卡给出当前合同及哈希定位，不把旧公开单 RTS 工具误称完整 UC56 重现包；正式结果另文记录。
