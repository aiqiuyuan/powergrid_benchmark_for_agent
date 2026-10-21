# 待补基线：2026-10-19 独立数值复现批次

本批次根据“把所有待补的基线开始补充”新增固定数值程序和训练参照。六个任务族、八个子 case 均有实现／构建核验和实际执行入口；可执行的方法进入原 case 运行，商业求解器或未发布依赖阻塞的方法保留具体原因。**提交、开始执行、程序完成、候选有效是不同状态。** 最新核对时间、实际 Job／UID、冻结源码、原始结果摘要与哈希见[机器可读证据](evidence/baseline-reproductions-20261019.json)。这是一次人工请求触发的记录，没有安装持续监控或自动重试。

**完成核对：2026-10-20 14:48 北京时间。** 本批 35 个当前正式数值／训练 Job 全部完成，0 个运行、0 个排队；最后一个于 **2026-10-19 22:04:03** 完成。计数不含保留的失败准备、UC v4 适配缺陷运行或 native 验收；一个 Job 可含多个固定方法或 seed，Job 成功不等于候选有效。以下为实际终态，不再沿用启动快照。

这些运行不新增 LLM 开发重复、模型请求或开发期计数反馈。原开发截止源码、历史结果和 `normalized-v1` 均保留；本批基线也不用于事后替换演化终态或重选训练检查点。公开[算法入口及依赖说明](../../tools/baseline_reproductions/README.md)可供核对；私有执行包、受保护标签、集群控制器和凭证不发布，公开适配器本身不等于完整可执行评测绑定。

## 1. 当前补齐范围

| 任务 | 已安排的方法 | 比较层次及执行状态 |
|---|---|---|
| GOC2000 / GOC2312 | PMSC 完整 Code1 + soft fixed-point／strict fixed-point Code2，各 case 两份 | **4/4 完成、有效且硬可行**；全量 2421／982 故障、原 checker、当前资源与限额 |
| UC / RTS-GMLC | 原始 MILP starter 与只改注释的控制，3 个交错 block × 3 solver seeds；EGRET Tight／Compact／Random1 | **18/18 原始 MILP 执行达标；EGRET v5 三方法、9/9 seed 有效且达标**，Random1 平均首次达标 25.259 s；v4 适配失败保留 |
| RTE X04 / X15 | 当前 starter、独立均值风险 MILP、独立可行性 MILP；每方法分别跑 900／5400 s | **3 个 Job、12 个阶段全部完成**；X15 六份完整面板均保留 15 例及失败，最好可行覆盖 14/15 |
| HEFTCom | generation ridge、price-aware ridge、generation HGB、direct-bid HGB、GEB-inspired quantiles、organizer-spline 受限适配 | **6/6 原运行时方法＋CatBoost 扩展参考均已完成且有效**，各完整 90 市场日／4318 period；扩展权限单列 |
| MAPDN | 原作者 MADDPG+Bowl、MATD3+Bowl，各 5 seeds、400 episodes | **10/10 完成训练及全 480 步有效重放**，每份 95600 次真实训练转移；电压安全率另报，均非全日全部节点安全 |
| PowerGym | Random、PPO、integer SAC、cbat-SAC-projected，各 3 seeds | **12/12 完成全 24 步，3/12 通过双能量条件**，仅 cbat 三 seeds 有效；另 9 份正式 quality=0；Random 无训练，其余各 40000 次转移 |

所有首次发布的结果都来自独立执行和原 case 验解，预检的小步训练／合成数据分数不填入正式基线表。依赖阻塞项仍未获得数值成绩，不与已完成 Job 混淆。

## 2. GOC：完整强数值参考已完成

[PMSC](https://github.com/lanl-ansi/PowerModelsSecurityConstrained.jl/tree/5239af613f6bee3bcb0e86a78449115711c8cb87) 版本 0.12.0 与原生 Julia manifest 的包树一致。Code1 保留 DC 初始化、AC 恢复、故障筛选／cuts 和 AC polish；Code2 两种版本分别调用上游 soft／strict fixed-point 实现，均独立覆盖全部故障，不拼接不同基态或按成绩选响应。

| case／方法 | J ↓ | cost | soft penalty | valid／feasible | Code1／Code2 墙钟 s | 阶段采样峰值内存 GiB |
|---|---:|---:|---:|---|---:|---:|
| GOC2000／soft FP | 1,368,436.433290 | 1,002,745.229916 | 365,691.203374 | 是／是 | 79.229／214.634 | 4.690／7.870 |
| GOC2000／strict FP | **1,002,774.015027** | 1,002,745.229916 | 28.785111 | 是／是 | 77.371／653.958 | 4.661／10.405 |
| GOC2312／soft FP | 506,801.999439 | 381,408.791059 | 125,393.208380 | 是／是 | 60.543／98.239 | 4.671／7.628 |
| GOC2312／strict FP | **381,423.195821** | 381,408.791059 | 14.404762 | 是／是 | 63.915／232.484 | 4.800／8.710 |

使用当前 Code1 4800 s、Code2 38736／15712 s、24 CPU／56 GiB；峰值来自阶段采样，是实际峰值的下界。两方法的基态成本相同，strict companion 显著减少软惩罚，同时花费更多 Code2 时间；这只描述两次完整程序执行，不是对所有实现因素的受控消融。每个结果均为一次执行，不伪造多 seed 统计。

[LANL 最终报告](https://www.osti.gov/servlets/purl/2532332)将 PMSC 对应到公开 ARPA-E Benchmark 家族。本次重放调用完整 `compute_c1_solution2`，省略历史 MyJulia2 包装器的 preliminary fast fallback，且时间／CPU 与原赛不同。因此它是**当前合同下固定版本的完整方法重放**，不是 2019 原提交逐字节复现；不能把 PMSC 与 ARPA-E Benchmark 当成两套独立算法。

gollnlp 已固定到 `38b5b22c…` 并进行构建依赖核验。原程序需要作者定制的静态 Ipopt、HSL MA57／MA27、METIS 以及未随源码提供定义的 timer symbols；现有环境无对应库，HSL 另有许可条件。保留此项为**依赖阻塞**，没有把当前 MUMPS／SPRAL 环境或新写 shim 冒充原赛优胜程序。gollnlp 同时是竞赛与 Petra／Aravena 论文实现，两种来源身份不额外增加方法数。

<a id="3-uc校准完成论文-formulation-已启动"></a>

## 3. UC：校准与论文 formulation 均已完成

原始 Julia／JuMP／HiGHS 完整模型与注释控制按固定随机种子 `20261019` 决定每个 block 的次序；每角色启动全新容器，分别执行 solver seeds 0／1／2，资源保持 1 CPU／8 GiB、每 seed 300 s，原 checker 和质量门槛不变。容器独立不表示节点镜像／文件缓存全部冷启动；此次仍未测量或控制宿主缓存。

| block／角色 | seed0／seed1／seed2 首次达标接收时间 s | 平均惩罚时间 s | reward | 有效／全命中 |
|---|---|---:|---:|---|
| 1／starter | 54.867／64.284／63.081 | 60.744284 | 0.898759527 | 是／是 |
| 1／comment control | 55.790／63.650／63.057 | 60.832107 | 0.898613154 | 是／是 |
| 2／comment control | 55.709／64.122／62.982 | 60.937912 | 0.898436814 | 是／是 |
| 2／starter | 54.979／60.757／59.291 | 58.342289 | 0.902762851 | 是／是 |
| 3／comment control | 51.114／59.212／58.523 | 56.283247 | 0.906194589 | 是／是 |
| 3／starter | 51.087／59.036／58.735 | 56.286179 | 0.906189702 | 是／是 |

两角色各 9 个 seed 执行均值分别约 **58.458 s／59.351 s**；原历史 224.359 s 的验收量级在此次没有复现。注释不改变算法，上述变化不能解释为算法加速；也不能拿旧 224.359 s 当作固定分母。正式演化最好 43.361 s 来自另一批执行，只作原始观测并列，不由本表推出稳定加速比。

[EGRET 作者实现](https://github.com/grid-parity-exchange/Egret/tree/28c324f9bf4fb3913b0a60dba3dd732b46084c3b)已固定 commit，适配原 73 台 thermal／81 台 renewable、48 时段铜板实例。Tight／Compact／Random1 均关闭 demand slack，并**显式固定 ReserveShortfall=0**；已对备用、初始状态、启停、hot／warm／cold startup 和分段成本完成小例核对。原 checker 的已知成本及不可行例用于合同验证，不用目标分数挑参数。

v4 三 formulation 的完整目标执行均产生快照，但被原物理 checker 拒绝。诊断定位为作者铜板接口传入 `relax_balance=False` 后，底层按关键字存在判定放松，生成了“发电≥需求”而非本题要求的等式，允许多余发电。这是适配合同缺陷，不作为论文方法质量结论；v4 全部源码／失败保留。新冻结 **v5 在适配器显式绑定等式，作者源码与原 checker 不改**，并对三种 formulation 分别加入强制过发电不可行、可再生能源削减可行的原生验收。

论文 formulation 使用 Python／Pyomo，与 Julia／JuMP 的启动及建模接口不同；两者 HiGHS 后端版本均为 1.15.1，但这不消除运行时差异。新参考镜像离线安装锁定依赖，导入、建模、求解、回调序列化均在 300 s 内。早期 native gate 暴露 EGRET parser 隐式依赖 pandas，已在 v4 补齐。**v5 同源 native gate 于 2026-10-19 18:53:26 北京时间完成：三份已知成本小例、三份可再生能源削减例、三份强制过发电拒绝例及原沙箱探针全部通过，随后才提交三份正式 Job，各执行 seeds0/1/2。** 三份完整 case 结果均已完成，9/9 seed 经原 checker 验解有效且命中门槛；早期失败不合并成论文方法重复统计。回调发布前 63 个改善 incumbent 及第 64 个最终快照；如果 cap 用尽，可信接收的首次达标时刻可能晚于内部首次达标，仍按原监督器观测计时，不重写内部时间戳。

| EGRET v5 方法 | seed0／seed1／seed2 首次达标接收时间 s | 平均惩罚时间 s ↓ | reward ↑ | 有效／命中 |
|---|---|---:|---:|---|
| Tight | 71.877536／70.484365／67.395412 | 69.919104 | 0.883468160 | 3/3 |
| Compact | 95.064006／63.803503／83.069477 | 80.645662 | 0.865590563 | 3/3 |
| Random1 | 45.342455／15.983200／14.450795 | **25.258817** | **0.957901972** | 3/3 |

这三组是同一固定论文 formulation 的 solver seeds，不是新增三次独立智能体开发。Random1 的本次观测均值优于此处其他 formulation 与正式演化最好 43.361 s，但语言接口、缓存、节点和执行批次不同；仅并列原始时间，不由单批结果给出稳定加速比或普遍方法排名。完整精度与逐 seed 执行状态见[UC card](unit-commitment.md#baseline-anchors)及 JSON。

<a id="4-rte原-case-三方法并行启动"></a>

## 4. RTE：原 case 三方法、两时间档均已完成

固定三套方法：原始均值风险 MILP＋分位风险局部搜索 starter、独立 mean-risk MILP、独立 feasibility MILP。后两者是独立简化参考，不声称仅从 starter 删除一项得到的严格消融；最终均由原 checker 计算官方目标 `F`。

每个方法对 X04 和完整 X15 分别独立启动 900 s 与 5400 s；长时运行不接续短时轨迹，也不据其选择候选。X04 保持 2 CPU／16 GiB；X15 每实例 1 CPU／16 GiB、15 例并行，使用原 solver seed 2020 和全部启动／建模时间。源一致 native gate 在原两个运行时执行 48 个合成检查并全部 AC，之后才提交三份实际 Job。合成目标 2.5 不作为目标实例基线。

三个 Job 的全部 12 个阶段均已完成，最后一个于 2026-10-19 22:04:03 北京时间结束。X04／900 s starter **F=11,560.512**，候选墙钟约 533.273 s，重现原起点；mean-risk MILP 未取得可行 incumbent，原 checker 返回 RE、score0，候选约 896.337 s。完整面板如下，RE／TLE 保留原槽位并在 15 例质量均值中计零，不重选方法或时间档。

| 方法 | 每例限额 s | 独立 X04 F ↓ | X15 AC／RE／TLE | X15 全 15 例质量 Q ↑ |
|---|---:|---:|---|---:|
| starter | 900 | 11,560.512 | 9／2／4 | 0.139133 |
| starter | 5400 | **11,494.032** | 14／1／0 | **0.209740** |
| mean-risk MILP | 900 | RE：无可行 incumbent | 9／2／4 | 0.125843 |
| mean-risk MILP | 5400 | 11,606.222 | 14／0／1 | 0.198337 |
| feasibility MILP | 900 | 12,188.572 | 6／4／5 | 0.093719 |
| feasibility MILP | 5400 | 12,188.572 | 11／1／3 | 0.158711 |

六份 X15 面板均未达到 15/15 可行；JSON 的 `mean_official_objective` 只对可行子集计算，是诊断量，不能当成完整面板质量。X04 单独运行与 X15 内的 X04 是不同资源下独立执行，数值可不同；例如 mean／5400 的单例 F=11606.222，面板内为 11606.178，不互相替换。逐例 90 个状态／目标、覆盖优先 reward 与完整精度见[RTE card](rte-maintenance.md#baseline-anchors)。

已对公开竞赛／论文源码进行实际依赖探测：S34 缺 `gurobi_c++.h`，S56 缺 `ilcplex/ilocplex.h`，Gouvine 缺 CPLEX／docplex；无已配置商业求解器许可。S56 的依赖为 **CPLEX**，修正前次卡片误写的 Gurobi。商业库缺失不能通过下载历史排程来冒充程序复跑；也不静默换 HiGHS 后称原冠军复现。

## 5. HEFTCom：七种固定训练方法已完成

所有方法用原训练截止、DWD 聚合输入、seed0、90 日／4318 period、1 CPU／8 GiB 和训练 300 s／每日 10 s／合计 600 s。参数预先固定，目标期结果不用于调参。七者均 valid；前六者使用原运行时，CatBoost 为单列的依赖／沙箱扩展参考。

| 方法 | 累计收益 GBP ↑ | 训练＋逐日回放 s | 方法身份 |
|---|---:|---:|---|
| nonlinear ridge，generation-only | 84,994,909.13 | 11.217 | 传统预测直接报价 |
| nonlinear ridge，generation＋price spread | **85,657,916.25** | 15.680 | 条件均值与二次结算决策 |
| HGB，generation-only | 84,011,172.55 | 89.729 | 固定树模型 |
| HGB，direct optimal-bid target | 85,488,636.29 | 90.574 | 用训练历史事后最优报价标签直接学习 |
| GEB-inspired quantile spread | 84,331,760.93 | 103.420 | 受限输入的方法适配 |
| organizer-spline-adapted | 83,361,378.29 | 220.423 | 组织方 spline 思路的受限输入适配 |
| SVK-inspired direct CatBoost | 84,604,672.88 | 43.984 | 受限方法适配＋own-statm-only 参考运行时 |

价格差定义为 `DA−SS`。固定结算系数 0.07 对应期望最优报价 `clip(E[generation]+E[DA−SS]/0.14, 0, 1800)`。ridge 使用固定 λ=100；HGB 为 200 iterations／31 leaves，无目标期 early stopping。GEB-inspired 方法用五个固定分位数 0.1／0.3／0.5／0.7／0.9 及等权中点积分、常数尾部近似；它不是原参赛 GEB 的完整重训。

组织方适配固定 [HEFTcom24](https://github.com/jbrowell/HEFTcom24/tree/2cdf695d6365e90704a3afca141ce366e7cb65db) notebook 的 cubic B-spline／median 思路，改用 sklearn SplineTransformer＋HiGHS quantile regression。输入、冻结训练和样条边界外延规则与原赛不同，不能把该收益写成原 Benchmark 报价再现。

最好正式演化收益 88,060,765.82 GBP 相对本轮已完成最强传统参考 ridge-spread 高约 **2.805%**。这是同固定期的描述性差值，不是新时期泛化、显著性或原赛名次。SVK 历史 88,882,213.67 GBP 仍属于原输入／滚动开发历史记录。

SVK-inspired CatBoost 采用固定 600 iterations／depth6／learning rate0.05 的单阶段 direct-bid 学习，缺少原队伍多源天气与 stacking，明确属于受限适配。离线依赖导入成功，但 native tiny fit 实际报 `/proc/self/statm` 读取被原沙箱拒绝；先保留失败，再在独立参考运行时验证仅允许本进程内存统计的兼容性扩展，原演化镜像和历史分数不变。v5 已通过 source-matched gate：68 项拒绝探针、本进程 statm 7 字段读取和两迭代合成 CatBoost fit 均通过，随后才进入完整 90 日评分；当前原始沙箱以外仅新增该精确文件 READ_FILE 权限，其他进程／proc 目录／写权限均未开放。完整评分随后完成，**valid=true、84,604,672.87810947 GBP、43.984 s**；Job／UID、终态回执和文件摘要可在 JSON 核对。

<a id="6-mapdnpowergym固定种子训练已启动"></a>

## 6. MAPDN／PowerGym：固定种子训练已完成

MAPDN 直接使用 hash 核验的原作者 MADDPG／MATD3 trainer 与 Bowl reward，各 seeds 0–4、400 episodes。上游每 episode 的 240 时刻约定产生 **239 次实际训练转移**，记录真实计数；保留原生周期性随机 10-episode tests，但不据其选权重。仅第 400 episode 最终检查点用于本卡 480 间隔因果重放，分别报告安全率和真实 MWh。原作者未发布使用的具体 seed 编号，0–4 是本次明确的重建选择。

**10/10 已完成**，每份 95600 次真实训练转移、480 个因果评测间隔和 960 次评测 PF。下表为各方法预定五 seeds 的等权均值；每份重放有效，但没有一份满足全日全部节点电压安全。bus-time 安全率与所有节点同时安全的时段比例不同，不能将前者写成后者。

| 方法 | 有效完整重放 | bus-time 安全率均值 | 全节点同时安全率均值 | 实际网损均值 MWh ↓ | quality 均值 ↑ |
|---|---:|---:|---:|---:|---:|
| MADDPG+Bowl | 5/5 | 93.719697% | 44.458333% | 1.73071848 | 0.468598485 |
| MATD3+Bowl | 5/5 | 87.474747% | 37.250000% | 1.77730739 | 0.437373737 |

逐 seed 指标和样本标准差见[MAPDN card](mapdn-voltage-control.md#baseline-anchors)。较低网损不能单独证明控制更优，仍须结合安全率；本轨道具有额外训练信息，不与正式开发预算 n 等同。

PowerGym 作者公开环境不含原训练器／权重，PPO／integer SAC／cbat 由独立实现重建。训练使用当前 123Bus、2.5 倍负荷、全部八条训练 profile，**目标 profile0 包含在训练中**，故不是未见日泛化。各三个 seed，PPO／SAC／cbat 均训练 40000 次真实转移，Random 为 0 次；只采用最终检查点。

cbat 的训练电池分支是真正 Gaussian 连续动作，电容器／tap 使用 straight-through Gumbel 分支；最终 benchmark 推断显式投影到最近的 33 档电池网格，命名为 **cbat-SAC-projected**。这是披露结构假设的重建，不能称原作者连续电池 Gym 曲线复现。

训练保留原生 vanilla reward，未添加硬末能量奖励修补或终态动作修复。**12/12 完成全部 24 步；仅 3/12 满足每台电池账面及实际积分两项末能量误差各≤1 kWh，另 9 份正式 quality=0。** 未删 seed 或换中间较好检查点。

| 方法 | 完成数 | 双能量条件通过 | 各 seed 正式 quality | 三 seeds 均值（失败计零） |
|---|---:|---:|---|---:|
| Random | 3/3 | 0/3 | 0／0／0 | 0 |
| PPO | 3/3 | 0/3 | 0／0／0 | 0 |
| integer SAC | 3/3 | 0/3 | 0／0／0 | 0 |
| cbat-SAC-projected | 3/3 | **3/3** | 0.018854125／0.059648916／0.021571889 | **0.033358310** |

八份记录直接报 `terminal_energy_violation`。integer SAC seed1 的原始 `valid=true` 只表示账面末能量恢复；其第 3／4 电池实际净能量为 **−151.125／−48.714 kWh**，`qualification_valid=false`，必须按正式失败计零。原始 `canary_quality=0.010873126` 保留作诊断，不能当作有效基线。JSON 同时保留原始字段和明确的 `formal_valid / formal_quality / formal_error`，原始运行文件不改写。

三份 cbat 虽通过硬能量条件，全网同时电压合规的时段比例均为 0；有效不代表电压安全。其最好 seed 的 quality=0.059648916，正式演化最好为 **0.104470297**；本参考具有额外训练权限且三 seed 波动较大，不由单 seed 最好值推出稳定方法结论。逐 seed 安全、kWh、动作和吞吐见[PowerGym card](powergym-volt-var-control.md#baseline-anchors)。

两个任务的训练容器为 2 CPU／8 GiB、无 GPU／网络，输入只读，保留训练与 PF 计数。训练模拟器、reward、集中 critic、外部权重和依赖给予的信息／计算多于正式 n 预算或 stdlib-only 提交合同，因此单列为**额外训练／权重参考轨道**；不是新增 n=0/1/3/5/10 的同预算开发样本。已完成六个 native smokes只证明训练与物理接口可执行，不充当 400 episodes／40000 steps 成绩。

## 7. 版本、失败与可复现边界

冻结 manifest、源码 pin、Job／UID、已完成结果及各证据文件 SHA256 均在[本批 JSON](evidence/baseline-reproductions-20261019.json)。提交控制器使用 create-only 意图／回执和同名 UID 对账；不因 SSH 退出码不确定而再提交新身份。失败准备版本和不兼容运行都保留，不计算成独立算法重复，也不据失败推定算法质量。

本轮 tabular v1 的 macOS tar 额外带入未执行的 `._*` 元数据文件。实际 grader 收到的完整文件清单已逐结果保存，包含这些 sidecars；实际执行的 Julia／Python 文件哈希仍与冻结声明一致。这里不将它描述为洁净的两文件包。后续版本改用 Python tarfile，并在执行前验证**实际文件集合及每个哈希**，不改写已完成包或成绩。

原 checker、物理输入和分数公式固定；为作者依赖新增解释器／训练权重／兼容性沙箱的参考轨道分别披露。仍缺少的商业求解器许可、作者定制库和原参赛完整流水线继续显示具体缺口，不以历史成绩或适配版成绩代填。2026-10-20 的追加只收录已完成回执与结果哈希匹配的终态；没有新增求解、训练、开发或过程反馈，也没有改动历史归一化范围。
