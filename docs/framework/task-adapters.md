# 五个任务的可执行Adapter合同

**RTE后续决定（2026-10-15）：** 当前RTE采用ABC45开放开发、X15隔离反馈，900秒／例、评测端15 CPU并行；冻结后5400秒／例评测且不回流。ABC允许官方checker本地自测，n仅统计完整X面板受理次数。RTE以[决定0006](../decisions/0006-rte-abc-open-x15-protected.md)和[新配置](../protocol/rte-abc-x15-configuration.md)为准；下文X04单例及禁止全部本地评分条款保留为被覆盖的历史设计，其他任务不受此例外影响。

> **其他四task的第一阶段政策（2026-10-15）：以[决定0005](../decisions/0005-fixed-case-evolution-first.md)为准。** RTE另按[决定0006](../decisions/0006-rte-abc-open-x15-protected.md)采用ABC开放、X15受保护评测，允许ABC完整checker自测。其他四task固定一个高难完整case，同case开发、计n反馈与冻结复核；开发端禁止完整checker和本地完整目标评分，不设免费public-selection。下文四角色／独立留出、公开checker、best-public-selection等属于较早设计或第二阶段参考，不是本阶段默认。原生入口的实现与验收状态见当前决定和各任务卡§12。

**当前实施顺序（2026-10-15）：先填写[公平比较设置](fair-ranking.md)，再按[原生task包格式](native-task-package.md)整理已有eval-in-loop任务，只补实际缺口。** 下文保留上一版详细参考合同；七个职责是评测需要覆盖的行为，不要求新建七个组件。通用JSON ABI、独立内核、RPC和完整生产认证不是个人小测的必建项。原生入口与配置能够满足的直接复用；本轮没有将五个task迁移到下述设计。

**状态：2026-10-14，设计合同已构建，生产任务实现与认证待完成。** 统一生命周期管理预算、受理、冻结和证据；Task Adapter负责本任务的输入、算法调用、原生输出、独立checker与原始指标。RTE原生task源码已在[独立任务包](../../task-packages/rte-maintenance-abc-x15-v1/README.md)公开；大型竞赛数据和既有内部部署代码仍由操作者分别准备。

每个家族有[机器可读声明](../../manifests/task-adapters/)及任务卡§10。声明中的`implementation.argv`是要实现的调用模板；`status=design`阻止它被当成已认证生产Adapter。[公平排行路线](fair-ranking.md)解释为什么采用这些合同。

## 1. 同一生命周期上的七个职责

| Adapter职责 | 必须产出的证据 | 谁拥有控制权 |
|---|---|---|
| `prepare` | 数据来源、许可、分组、依赖、必需文件、原生checker锁定记录 | 可信评测端；准备不运行候选搜索 |
| `package` | `candidate.json`、源码、dependency lock、参数、权重及训练配方、文件清单 | 开发候选写入后由共同artifact层快照 |
| `run` | 冻结算法在实例/episode/市场日输入上新生成原生输出 | 可信harness控制环境与时间；候选只执行算法 |
| `verify` | 完整性、物理/信息约束、独立原目标复算、失败分类 | 独立checker，不能信任候选自报分数 |
| `feedback` | 固定schema的聚合反馈与使用的面板/评分版本 | 共同judge控制n和投递截止，Adapter仅解释任务指标 |
| `select` | 在public-selection上属于同一artifact的质量证据 | 共同selector；不得用final-test或测试反馈选候选 |
| `finalize` | 同冻结artifact的逐例指标、统计、运行日志、来源与receipt | 共同finalizer；Adapter不再修改算法 |

Configuration中的开发模型、重复、`T/n`及CPU/GPU/内存不由Adapter暗中设置。Adapter声明必需项与物理限制，配置模块填实并校准；同任务的所有方法引用同一发布版本。

## 2. 公共算法ABI与安全边界

提交的是`kind=algorithm`的源码包，可带合法权重，不能仅交调度、报价或动作轨迹。`candidate.json`至少关联`task_id`、以列表表示的`entrypoint`、源码与dependency lock。入口必须显式含`{input}`和`{output}`占位符，例如：

```json
{
  "kind": "algorithm",
  "task_id": "unit-commitment",
  "entrypoint": ["python3", "main.py", "--request", "{input}", "--output", "{output}"],
  "source": ["main.py", "solver.jl"],
  "dependency_lock": "dependency-lock.json"
}
```

此例仅说明ABI，不提供真实求解器。外层入口可以调用Julia或C++；语言选择不改变资源与solver许可合同。argv不经shell解释，相对源码/产物路径按冻结artifact根目录解析；真实runner需在经过认证的隔离环境执行，不能依赖候选自己遵守安全边界。

**生产task harness的拟定输入请求**使用`schema=task-request-v1`，包含`task_id/task_version/track_id`、`artifact_sha256`、当前单例/episode/day ID、随机种子、候选可读的`input_root`、可写的`output_root`、阶段与该阶段算法执行限额。预算字段只从填实的发布配置读取；不能从本模板推导默认值。公共ABI要求传入请求文件`{input}`并生成响应JSON`{output}`；当前通用参考实现的fixture只证明这一入口合同，任务专用请求构造、容器与物理checker尚待接入。

**生产响应的拟定结构**使用`schema=task-output-v1`，声明`task_id`、`instance_id`、原生输出相对路径及诊断元数据。可信checker读取这些原生文件；候选提交的`objective/status/dual_bound`不直接授予得分。输出路径必须局限于指定目录，拒绝符号链接逃逸、绝对宿主路径、缺文件、重复ID、非有限数与越界。

Protected-feedback及final-test输入只在可信评测环境提供给冻结算法。开发智能体没有该环境或日志的直接读取权限；算法确实需要读物理输入，但不能通过网络、共享目录、异常日志或跨run缓存把数据送回开发端。HEFTCom的真实未来标签以及L2RPN的未来真实轨迹始终不进入算法请求。

**状态规则：** UC/RTE每例fresh process且不可写跨例共享缓存；GOC只允许同一实例的Code1→Code2白名单状态；L2RPN同episode允许控制器记忆、跨episode重置；HEFTCom只由因果replay规则开放历史与允许状态。共同准备可缓存依赖；候选学习、统计或解缓存必须随协议披露，不能隐藏在公共准备中。

## 3. GOC：完整两阶段求解器

### 3.1 输入、执行与输出

| 项 | 拟定合同 |
|---|---|
| 输入 | 单个官方网络/场景的`case.raw / case.rop / case.inl / case.con`，来源/哈希和故障ID全清单；不向开发侧公开protected/final面板 |
| 外层入口 | `python3 main.py --request {input} --output {output}`；可信GOC harness调用同一artifact的两个stage |
| Code1请求 | `stage=code1`、当前实例native input路径、Code1执行限额；候选输出官方`solution1.txt`及列明的中间状态 |
| Code2请求 | `stage=code2`、同实例输入、只读Code1 state和其hash、完整故障清单、Code2总执行限额；fresh container生成`solution2.txt` |
| 输出 | 外层响应指向本次生成的`solution1.txt / solution2.txt`及状态清单；对每个原故障恰好提供规定响应，Code2不得修改基态 |
| 训练/依赖 | 披露初始化模型、参数或预训练来源；PowerModels/PMSC/JuMP/Ipopt或其他solver版本、许可证、线程及外部服务边界必须锁定 |

Native Code1/Code2可以有语言特定入口，Adapter负责转成共同argv合同，不能改变原物理输入和目标。分片Code2必须绑定同一artifact、输入、基态、故障子集及资源账本；续跑只补该作业缺片，不拼接不同候选较优片。

### 3.2 验证、排行与认证

先检查输入完整、两阶段hash、全部故障覆盖、输出格式；再调用锁定官方evaluator检查有效性、硬可行性及软惩罚，保存`J`与分项、耗时/内存。软惩罚不直接判作硬不可行，缺故障不以子集低目标计分。官方输入/评测器缺失属于基础设施失败；候选未产生完整合法输出属于算法失败。

选择公开合成面板的新统一排行，历史单场景/合成division另列。当前完整中等规模结果可复用为calibration，gollnlp为强基线候选；要补clean build、同平台全故障重放、数值容差与资源校准、来源分组留出、固定聚合及失败政策。GOC30000是规模扩展，不把其局部故障救回视为全量验收。

机器声明：[goc-sc-ac-opf.json](../../manifests/task-adapters/goc-sc-ac-opf.json)。原赛Code1的10/45分钟是历史Real-Time/Offline参照；新release具体执行档位与开发`T`独立待定。公开合成来源与工业数据边界见[任务卡§8](../task-cards/goc-sc-ac-opf.md#8-原始竞赛排行榜与开发--测试数据)。

## 4. UC与派生SCUC：运行源码后验排程

### 4.1 输入、执行与输出

| 项 | 拟定合同 |
|---|---|
| 输入 | 锁定PGLib-UC单例JSON，完整时间窗口、初态、热机/新能源、负荷与备用；派生SCUC额外有网络与固定全部security rows |
| 外层入口 | `python3 main.py --request {input} --output {output}`；wrapper可调用`julia --project=... solver.jl`，Julia包加载/求解/输出均按声明时限计时 |
| 原生排程 | `schema=uc-schedule-v1`；每热机`on[t] / power[t] / reserve[t]`，每新能源`power[t]`；所有数组按完整窗口，单位MW |
| SCUC区别 | `track_id=derived-dc-scuc`，备用可按品种给出，网络注入由排程及冻结数据独立重算；派生安全行、线路限额与允许故障随version固定 |
| 输出 | 响应给出本例`schedule.json`与可选`solver_report.json`；输出从当前实例求解得到，不从包内答案查表 |
| 状态 | 各实例fresh process；不得自动修复原输入的爬坡、startup或成本参数；不得用裁短窗口冒充完整求解 |

### 4.2 验证、排行与认证

独立检查整数开停、初态、负荷平衡、出力、爬坡、最小开停、启停、备用及声明网络/故障约束，并重算真实原目标。算法自报最优状态、dual bound和改变目标后的solver值不进入权威评分；可信独立参考下界须绑定原模型、版本、容差和证据。超时但有可行incumbent与超时无可行排程分别记录。

主线选择原UC求解器排行；SCUC独立扩展和归一化，原库没有竞赛名次。现有完整MILP/HiGHS基线及Python validator可以复用；目前grader只评分已保存排程，必须先改成clean build→运行冻结源码→新排程→独立validator。还需原参数parity、同系统/跨系统分组、强基线校准及solver许可/线程政策。难度被基线饱和时调整预先声明的实例/指标，不能削弱基线制造改进。

机器声明：[unit-commitment.json](../../manifests/task-adapters/unit-commitment.json)。`per-instance`限额、总批次限额、容差、重编译/加载成本和所有资源值待校准；不把已有60秒与30分钟开发变成新默认值。[任务卡](../task-cards/unit-commitment.md)。

## 5. RTE：风险目标求解与C+X历史记录

### 5.1 输入、执行与输出

| 项 | 拟定合同 |
|---|---|
| 输入 | 单个未经裁剪的官方JSON，包括`Interventions / Resources / Exclusions / Seasons / Scenarios_number / T / Alpha / Quantile`及完整风险张量 |
| 外层入口 | `python3 main.py --request {input} --output {output}`；当前solver接口可绑定为`solver.py --instance ... --output ... --time-limit ... --seed ...` |
| 原生输出 | UTF-8文本，每行`intervention_id start_period`；每干预恰好一次，start为原定义1-based整数 |
| checkpoint | 对15/90分钟历史参照保存两个有效时间点的排程/源hash/seed/时间证据；轨迹与独立运行方式认证后固定 |
| 目标 | 原Alpha加权均值风险及分位超额风险；均值MILP可作内部搜索近似，但最终只能按原目标评 |
| 状态/solver | 每例重置；允许的线程/进程与Gurobi或HiGHS能力由赛道明确，同赛道所有方法一致 |

### 5.2 验证、排行与认证

完整必需文件集检查后，官方checker核验所有干预、起止、资源上下限、季节互斥等约束，并独立计算风险分项。重复/缺作业、非法开始、超时没有有效解属于候选失败；包缺JSON、checker依赖缺失、宿主异常属于基础设施失败，不能算算法零分。随机种子与解质量证据对应原样本，不做按结果挑seed。

优先C+X历史参照，保存`F_15/F_90/V`与历史表；新泛化研究另建未用于演化/反馈的面板。当前A4接入和原目标checker基础可复用；曾发生嵌套清单遗漏，因此必须在每个发布包测试必需文件的完备性。S34/S56源码存在，但Gurobi、构建/权限与可运行性仍须认证；已启动历史重评不认定为完成。新积分需按固定方法集合全部重算。[公平路线§6](fair-ranking.md#6-rtecx历史参照先行)。

机器声明：[rte-maintenance.json](../../manifests/task-adapters/rte-maintenance.json)。原15/90分钟、2 CPU/16 GB仅存`original_protocol_reference`；没有替新智能体Configuration填`T/n/资源`。[任务卡](../task-cards/rte-maintenance.md)。

## 6. L2RPN：每步控制器与受控simulate

### 6.1 输入、执行与输出

| 项 | 拟定合同 |
|---|---|
| episode请求 | 环境/动作合同、当前episode seed、初始化限额及episode限额；完整chronics由可信harness保管，不将未来真实序列给controller |
| 入口 | 外层`python3 main.py --request {input} --output {output}`；harness装载`Controller(metadata)`并调用`act(observation, simulate)` |
| 当前观测 | 电网当前状态、合法forecast、冷却/维护信息、已用simulate与剩余限额；字段与动作schema按版本固定 |
| simulate | 只经可信RPC；逐步及逐episode累计，初始化阶段调用也计入声明范围；拒绝绕过RPC调用backend或读未来轨迹 |
| 原生输出 | 逐步合法Grid2Op动作，由harness执行；stdout RPC与日志分离，日志不污染协议。返回episode响应仅引用可信保存的轨迹/诊断 |
| 状态 | 允许同episode记忆；各episode fresh controller和seed；权重只读，不能利用跨episodefinal成绩在线选模 |

动作可以是拓扑/线路或另立允许redispatch的赛道；每条赛道都必须同时适配基线和智能体。旧375动作、每步16/每周2048仅是已测值，本次不固定新配置。拒绝未知动作字段、非法单位、注入篡改、超额simulate、越过单步限额或通过进程读评测状态。每步无效动作如何作用于环境以及合同错误如何赋分随发布固定。

### 6.2 验证、排行与认证

可信环境计算锁定原生经济scorer，reference用同输入/seed/backend新建，记录successful-step生存率、终止原因、实际调用数与成本。基线包括DoNothing/重连、固定Greedy、ES/PPO及公开`rl_agent/binbinchen/lujixiang`；训练型和预训练方法披露权重与训练来源。历史经济分数、现代native分数和逐步训练reward不得混表。

旧公开24周重评和三支领先方法的代码、权重、API适配可复用，但旧方法动作和simulate权限不同。新排行需要每个方法的同权限认证、转换前后回归、现代scorer parity、新独立面板及资源校准；若不能兼容同能力赛道，将该方法列外部参考。原赛隐藏24周尚未核验取得。20份较大比较策略的独立终评缺失保持历史记录，不以此次合同宣称补跑完成。

机器声明：[l2rpn-grid-control.json](../../manifests/task-adapters/l2rpn-grid-control.json)。调用控制与安全由生产task harness负责；通用本地fixture不能证明控制器隔离、原生评分或动作权限已经实现。[任务卡](../task-cards/l2rpn-grid-control.md)。

## 7. HEFTCom：训练证据加逐日因果预测交易

### 7.1 输入、执行与输出

| 项 | 拟定合同 |
|---|---|
| 训练产物 | 来源审计通过的public-development特征/标签、训练配方/seed、训练截止、模型权重与transform统计；selection用于选候选，默认不重新拟合 |
| 市场日请求 | `market_day`、`decision_cutoff_utc`、当前可用NWP和已公布合法历史；每行带`issue_time/available_at/target_timestamp`，不带未来真值/最终结算价 |
| 入口 | `python3 main.py --request {input} --output {output}`；main按一个市场日运行冻结特征/预测/交易代码，输出当日原生文件 |
| Trading输出 | `bids.csv`字段`timestamp,bid_mwh`，该日半小时集合完整，bid为有限数且0–1800 MWh；时区/DST由市场日清单固定 |
| Forecasting输出 | 启用时`forecasts.csv`每行目标UTC timestamp及`q10,...,q90`九分位，单位MWh；有效性、边界及分位顺序按锁定原赛规则/新release合同验收 |
| 外层响应 | 本日bids/可选forecasts路径、权重hash、最大训练标签可用时刻、所用feature版本及诊断；这些声明须由可信来源记录核验 |
| 状态 | 主线测试前冻结参数，逐日执行；允许使用已公布历史作为特征但不更新权重。滚动重训另立version、窗口、频率与计算预算 |

统一响应限额和每个市场日加载/推理/写出预算由配置填实。冷启动是否每日期重新加载或按允许状态复用、训练是否计入终评构建阶段均必须发布，所有方法同条件。D−1 09:20 UTC是原赛因果截止参照；不能让算法先看到整段终测特征再据未来分布重拟合而仍宣称逐日因果预测。

### 7.2 验证、排行与认证

可信replay仅开放截止前available的数据，再执行算法生成当日输出，最后由独立settlement使用真实发电/DA/SS核算；真实标签不写入候选容器。校验完整时间戳、DST/特殊日、单位、边界、缺交政策、清洗与修订版本。外层仅收`bids.csv`做评分的旧grader仍是静态答案检查，必须替换为“运行冻结代码→新输出→结算”。

主线选择因果历史重放的新Trading排行，Forecasting与Combined有独立就绪状态。组织方归档提交用于核算parity；baseline至少常数与重新限制边界/审计后的ridge，GEB公开包为强候选。GEB权重训练截止不合规时重新训练，不把完整赛期训练权重回溯当因果基线。公开历史资料已暴露，旧正n反馈时期不能重称全新终测，需独立期和标签到达证据。

机器声明：[heftcom-forecast-trade.json](../../manifests/task-adapters/heftcom-forecast-trade.json)。新版保留原始0–1800边界，旧±5000成绩另列calibration，不能直接比较榜名。报价截止属于task语义，开发`T/n`、训练资源、replay执行资源仍待确定。[任务卡](../task-cards/heftcom-forecast-trade.md)。

## 8. 五个Adapter的认证记录与交付边界

每个task release的`acceptance_records`至少包括：clean build、必需文件/ABI fixture、原生checker parity、冻结算法新输入重放、合法/非法/缺输出/超时、信息隔离、n=0/n=1反馈及超额拒绝、真实模型最小往返、截止冻结、失败恢复、目标并发完整批次。每条都绑定task版本、image、代码、数据与artifact哈希；旧任务通过不能替新的冻结包签证。

| 状态 | 可以做什么 | 不能声称什么 |
|---|---|---|
| `design` | 审查本合同、补配置、实现绑定、执行可信fixture | 五个任务已能真实评分或已有正式榜 |
| `integration-pending` | 接入已锁定生产任务并逐条补验收证据 | 以静态检查替代容器、模型与物理终评 |
| `certified` | 所有门槛通过，按冻结配置运行声明的任务/赛道 | 自动继承其他task/version的认证 |

本次交付五个design声明、五套输入/输出合同和公平路线；预算具体值依用户要求保持未定。通用生命周期与可信fixture的运行证据和实际覆盖范围另见[生命周期文档](architecture.md)及[可靠性保障](reliability-layer.md)，生产Adapter必须在缺少上述证据时拒绝进入正式排行。

## 新增配电网扩展（2026-10-15）

[MAPDN](../task-cards/mapdn-voltage-control.md)和[PowerGym](../task-cards/powergym-volt-var-control.md)的设计声明已加入`manifests/task-adapters`，可用相同`adapter-check`审阅；原五任务正式计划未扩容。基础代码、公开starter、来源锁及原生骨架见[配电网接入说明](distribution-control-integration.md)。这是控制合同与准备工具，尚未接通完整目标仿真评分器；两题均保持pending/false。
