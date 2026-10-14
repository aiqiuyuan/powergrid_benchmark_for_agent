# L2RPN 电网序贯控制

> 状态：已有小划分反馈实验和较大正式n=0方法比较；后者仅完成开发与策略导出，最终测试未执行。v0.1统一协议仍待校准和验收。历史证据截止北京时间 2026-10-13 23:32；修复准备核对至 23:38。

## 1. 家族定位与研究能力

**家族 ID：`l2rpn-grid-control`。** 基于Grid2Op与L2RPN场景，评测过载管理、断线恢复与拓扑决策的序贯控制。它连接规则搜索、仿真规划、RL及混合控制，提供与静态优化任务不同的智能体设计问题。

本benchmark研究的是开发阶段的算法演化。默认冻结控制器在推理阶段不调用LLM；如研究在线LLM控制，必须另立资源与延迟协议。

## 2. 演化对象与执行合同

- 演化控制器源码、规则参数、允许的训练流程及模型权重；算法接收合法当前观测并返回环境允许的动作。
- 终评在留出完整场景执行冻结控制器。保持初始化、随机种子、动作空间、模拟限额与超时一致；权重与源码均哈希锁定。
- 使用锁定Grid2Op原生评分实现，保留经济分数与successful-step生存率；不能把高经济分数等同于完整存活。
- 控制器无效动作、合同失败、单步超时有预定处理；环境或参考评分计算失败属于基础设施失败，不能静默发明一个算法分数。
- 控制器不得读未来真实观测、未来结算或评测端reference轨迹。允许的环境forecast与`simulate`接口属于任务信息，应明确而非笼统禁止。

## 3. 已有预实验与限制

| 协议 | 已有配置与结果 |
|---|---|
| 小划分反馈实验 | `l2rpn_neurips_2020_track1_small`，train 6周 / feedback 3周 / test 3周；n=0/1/3/5/20各3次；12小时开发；15份终评有效 |
| 小划分均分 | 各n终评分均值33.6093、44.2411、31.3634、32.5685、33.9697；正n全部用满，共87次反馈 |
| 小划分基线 | 同协议SafeReconnect 1.8074；GreedyLine16 33.9228；不能据此换算历史排行榜名次 |
| 较大方法比较 | train 144周 / public-select 48周 / feedback 24周 / final-test 96周；n=0；Famou、ES、PPO各5次，种子1001–1005 |
| 已完成的比较 | 15份开发导出有效；PPO+Search复用对应PPO权重，共20份策略；96周终评尚未执行 |

较大比较公开select均值：Famou 27.5793、ES 31.5072、PPO 6.6740、PPO+Search 8.2637。它们是选模数据上的成绩，不能宣布最终胜负。五份Famou因1600万token守卫在1.58–4.70小时停止，ES/PPO接近12小时；尚不构成相同完整开发时间比较。

小划分的开发时长与样本量也有限；n=1高于n=20不能推出反馈次数越少越好。三个测试周的多次执行不是更多独立开发重复。PPO分数低或搜索两对下降需要诊断，现有证据不直接证明代码bug。

## 4. v0.1 数据与反馈协议（拟定）

| 数据角色 | 拟定安排 |
|---|---|
| Public development | 固定训练场景，允许离线训练与公开模拟 |
| Public selection | 独立公开场景，按预定指标选一个候选；公开选择评测计入开发时间 |
| Protected feedback | 独立周/场景组，仅服务端运行候选；n控制返回的信息 |
| Final test | 未用于开发或反馈的场景组，冻结后执行控制器 |

较大先导四组数量可作候选设计起点，**不能把它直接称为已接受的v0.1冻结manifest**。需要核对来源、场景时间关系、近重复、季节覆盖、隐藏面板实际访问与许可。不同种子重放同一场景不能当独立场景泛化；划分应按场景来源/时间组，记录重复关系。

此为锁定现代Grid2Op API的适配评测：先导Grid2Op 1.12.5、LightSim2Grid 1.1.0与2020历史比赛环境不同，评分语义也有原生实现细节。保留其原生语义并做parity测试，不称历史服务器精确复现。公开环境与目标允许开发端自测；n针对受保护场景结果。

## 5. 基线、预算与校准

最低校准基线：DoNothing/重连、SafeReconnect、固定GreedyLine；较强方法包括规则ES、MaskablePPO与PPO+Search。现有ES为6参数、μ=4、λ=16；PPO为128×128 MLP。正式配置需重新锁定，并对传统训练与LLM开发说明总资源和选模花费。

较大先导固定375动作（1不操作、118线路、256拓扑）；模拟限额16次/步、2048次/周；算法合计4 CPU/16 GiB、0 GPU；每步5秒、初始化300秒、单episode1800秒。小划分用episode180秒和初始化20秒，二者不能混称同协议。

v0.1优先统一动作与模拟限制，开发墙钟上限且**无累计token cap**，独立单响应上限与模型用量记录；若设置有GPU的RL赛道须单独声明。最终时间与资源方案需通过场景成本和基线质量校准，不在本卡声称已完成公平比较。

## 6. 核心验收门槛

- 锁定环境、场景、backend、原生scorer和reference生成；同配置重复执行满足声明的确定性或随机性合同。
- 验证原生评分parity、最后失败转移与successful-step生存率的区别；reference不依赖错误缓存。
- 对无效动作、超时、模拟超额、未来信息访问和控制器合同错误做验收。
- 训练/选模/反馈/终评各自来源记录完整；PPO+Search配对权重哈希一致，统计配对而非另算独立训练。
- 统一预算后，所有方法能生成可执行候选并完成独立终评；再解释方法优劣。

## 7. 待定与阻塞项

核心选择small环境还是正式较大场景；动作空间与是否允许redispatch；最终场景manifest、时间与GPU赛道；PPO训练诊断；最后评分与生存率的主次指标。**已有20份策略的独立终评缺失**必须保留在状态表中。

## 8. 原始竞赛排行榜与开发 / 测试数据

> 官方来源核验日期：北京时间 **2026-10-14**。以下是原竞赛资料；本卡第3–5节是我们的预实验与拟定benchmark协议，二者的数据划分、环境和资源不能互换。

### 8.1 竞赛身份与阶段

原赛为 **L2RPN NeurIPS 2020，Track 1 / Robustness**，官方平台为[CodaLab竞赛25426](https://competitions.codalab.org/competitions/25426)。本卡不采用Track 2 / Adaptability的榜单。原流程是Warmup、Development / validation和自动Test：开发期可反复提交，在隐藏验证场景获得反馈；最终把开发期最后一次提交的代码自动运行在新的隐藏测试场景。当前平台另外保留Legacy阶段，页面显示的2022年结束日期和Legacy成绩不能替代2020年的最终榜。[官方阶段与规则](https://competitions.codalab.org/competitions/25426#phases)

### 8.2 2020年Robustness最终排行榜

组织方回顾论文表1的Robustness前3名如下；原页面Results入口也保留供检索。此次采用组织方论文中的**2020年最终成绩**，而非今天Legacy阶段的最高分。[组织方回顾论文，表1、§3.1](https://proceedings.mlr.press/v133/marot21a/marot21a.pdf)，[CodaLab Results](https://competitions.codalab.org/competitions/25426#results)

| 最终名次 | 提交账号 / agent名称 | 官方分数（越大越好） |
|---|---|---:|
| 1 | `rl_agent` | 59.26 |
| 2 | `binbinchen` | 46.89 |
| 3 | `lujixiang` | 44.62 |

分数为24个测试周上的归一化运行成本评分均值，**59.26不是59.26%存活率**。原比赛成本包括网损、再调度和停电后未供电的惩罚，使用DoNothing等参考控制器做映射；评分单位也不同于学习时自行设定的逐步reward。[原赛Game Rules](https://competitions.codalab.org/competitions/25426#learn_the_details-rules-of-the-game)

### 8.3 原比赛提供的开发、验证与测试数据

| 原始数据角色 | 提供方式与规模 | 参赛期间可见性及用途 |
|---|---|---|
| 公开训练 / 本地开发 | 原赛Instructions指定下载`l2rpn_neurips_2020_track1_small`；提供电网环境、生产/负荷chronics和starting kit，可在本地反复训练、仿真与调试 | 场景数据可下载；原比赛训练环境在各阶段保持同一来源，不是把隐藏验证集下载到本地开发 |
| 隐藏Development / validation评测 | 代码提交后由服务器在未知场景运行并返回成绩及逐场景行为反馈；验证与终测按同一统计分布和选择规则构造 | 可重复提交看榜，但参赛端不获得验证场景的完整数据。官网统一评测规则写为24个周场景；本次未取得当年逐阶段场景ID清单，不将这条规则替代验证manifest的复核 |
| 隐藏最终Test | **24个独立一周场景，每月2个**；5分钟一个决策步，一周2016步；场景未在训练中提供 | 对开发阶段最后提交自动测试一次；新的隐藏场景决定最终榜，不能再用最终分数选择候选 |
| 当前可下载的同名系列 | Grid2Op官方文档列出small约**48个模拟年**、large约**240个模拟年**，以及同名测试用少量快照环境 | 这是目前公开分发环境的容量说明。它不是对2020服务器训练包哈希或隐藏测试集再发布情况的证明；本地自行留出的3周或96周不自动等于原赛隐藏测试集 |

表中原始提交规则、训练环境入口和24周评测说明来自[CodaLab Instructions / Game Rules](https://competitions.codalab.org/competitions/25426#learn_the_details-evaluation)；隐藏验证、独立测试、每月2周和2016步来自[组织方回顾论文，§2.3.2、§2.4](https://proceedings.mlr.press/v133/marot21a/marot21a.pdf)；当前small / large容量与其原赛训练环境定位来自[Grid2Op官方环境文档](https://grid2op.readthedocs.io/en/latest/available_envs.html#l2rpn-neurips-2020-track1)。这些模拟年数不是现实中48年或240年的电网实测记录。

### 8.4 对本benchmark的意义与可比性边界

我们的6/3/3周小划分，以及144/48/24/96周较大四组设计，是另行构造的本地面板。不能把其中的public selection称为原赛隐藏validation，也不能给本地33.9228等分数插入上述最终榜。原赛官网冻结的是Grid2Op 1.2.2 / LightSim2Grid 0.2.4，本地适配版本和动作、模拟、时限已有变化；要主张历史名次，需要复核当年场景、起始时刻、环境、评分及资源，再运行同条件评测。[原赛环境版本与规则](https://competitions.codalab.org/competitions/25426#learn_the_details-evaluation)

用于后续数据审计时，应同时保存：公开训练环境的版本与哈希、我们四组面板的来源和场景ID，以及能否取得原赛24个隐藏测试场景的证据。此次补充完成公开来源核验，没有下载或宣称复现当年的完整隐藏测试manifest。

## 9. 公开来源

- [Grid2Op文档](https://grid2op.readthedocs.io/en/latest/)：环境与控制器接口。
- [锁定版本原生L2RPN2020 scorer](https://github.com/Grid2op/grid2op/blob/v1.12.5/grid2op/utils/l2rpn_2020_scores.py)与[成本reward](https://github.com/Grid2op/grid2op/blob/v1.12.5/grid2op/Reward/l2RPNSandBoxScore.py)：先导评分语义。
- [L2RPN比赛回顾论文](https://proceedings.mlr.press/v133/marot21a/marot21a.pdf)：历史比赛背景；不作为本地适配成绩的排行依据。
