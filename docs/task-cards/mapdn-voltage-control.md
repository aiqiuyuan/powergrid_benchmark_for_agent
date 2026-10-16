# MAPDN：局部信息下的光伏逆变器电压控制

> **任务 ID：`mapdn-voltage-control`。状态：`design / certification-pending / release_ready=false`。** 扩展家族尚未完成正式认证。另已实现[真实33节点 canary 运行包](../../task-packages/mapdn-voltage-control-canary-v1/README.md)，通过全天本地校准、GitHub Linux检查及2026-10-16目标集群真实后端/候选隔离验收。MAPDN n=0/1两组v2均已完成并通过原生审计，反馈受理/收集分别为0/0和1/1，最终校准质量分别为0.8972437326和0.8915242407；全网同时电压合规率均100%，实际网损分别为1.056688/1.185213 MWh，均完成480步。两题四组均已完成终评，其中PowerGym n=0因末能量违规记0分、原生审计未通过；其余三组通过。候选哈希与失败历史见[运行记录](../experiments/distribution-canary-20261015.md)。流程完成不代表正式严格n或扩展家族认证完成，也不自动加入原75-run清单。

## 1. 研究定位

**2026-10-16正式扩展：** 已按[决定0008](../decisions/0008-distribution-formal-fixed-cases.md)冻结33节点2012-02-03完整480步，新增[正式运行包](../../task-packages/mapdn-voltage-control-formal-v1/README.md)。全日电压合规的解优先，再比较实际有功损耗；共同starter为已核验的单步松弛局部策略，损耗1.835251MWh。每题n=0/1/3/5/10、各3次独立开发、12小时且无累计token cap。新包已通过本地真实后端和独立代码审查；集群与原生验收、提交状态单列在[正式实验记录](../experiments/distribution-formal-20261016.md)。本卡其余“尚未冻结”描述保留家族早期设计背景，固定案例以决定0008和正式协议为准。

候选算法控制光伏逆变器的无功功率，在局部观测下协调各节点电压，并减少实际有功损耗。开发阶段可以演化分段 droop、局部仿射规则、历史状态估计、合法通信策略或离线训练控制器；默认推理阶段不调用在线 LLM。

相对已有 L2RPN 家族，本任务的独立价值是**局部信息约束和连续无功协同**。MAPDN 每步进行稳态潮流计算，下一步负荷与光伏有功来自外生序列；原实现没有电池 SOC、无功爬坡约束或动作次数成本。历史可以帮助处理局部可观测性，但不能因此预先声称该任务需要 MARL 或长期规划。

可信执行侧必须限制每个控制单元实际能读取的信息。若将整个环境对象或全部控制单元的观测传给任意候选代码，应另列集中式赛道，不能继续称其为局部信息主比较。

## 2. 第一阶段固定 case 与严格 n

遵循[决定0005](../decisions/0005-fixed-case-evolution-first.md)：固定一个困难、完整、可重放的 case，开发反馈与截止后的独立复核使用同一个 case。结果解释为同 case 算法演化；跨 case 泛化留到第二阶段。

本节表格是正式家族合同。当前流程canary另冻结33节点、2012-01-02完整480个间隔、600秒开发时限及每题各一次n=0/1，使用稳定低增益droop作为共同starter；该流程校准不替代正式选难例、强基线或严格n认证。

| 项目 | 本任务合同 |
|---|---|
| case 单位 | 固定网络、完整运行时域、原始时间来源、外生负荷/PV 实现、初始无功和采样映射的完整轨迹；不是随机截取的若干相邻时间行 |
| 正式选例准备 | 33/141 节点已完成多日选例及强基线补充；33节点2012-02-03保留为安全约束下降损候选，已不能用旧电压缺口认定其困难。322 节点导入兼容及正式主case冻结仍待完成；流程canary继续为33节点2012-01-02完整日 |
| 完整性 | 若定义完整自然日，3 分钟采样应覆盖该日全部 480 个间隔；不能把上游默认 240 步随机片段直接称为完整日 |
| 开发 T | 按当前阶段政策每 run 上限 43200 秒；不设累计 token cap 或累计 token 预留截断，记录实际用量 |
| 过程 n | 完整目标评分只能通过框架计数作业；候选非法动作、超时或错误仍按已受理作业计 n。基础设施原样重试保留同一逻辑作业 |
| n=0 | 不提供完整目标过程评分；仍对截止时唯一冻结候选执行独立终评 |
| 最终产物 | 截止时 artifacts 中的唯一源码、参数和权重；未修改时保留 starter。终评不回流开发、不计过程 n、不择优重跑 |
| 正式扩展实验 | n 档位、独立开发重复、模型、资源和执行限额需单独形成冻结清单；本次登记不启动实验，也不改写原 75-run 规模 |

开发端只开放 schema、接口说明、获准的 toy 数据与非目标材料。完整目标拓扑加精确外生轨迹和公开 Pandapower 足以重建评分，因此仅隐藏 checker 不足以保证严格 n。可信侧保管精确目标实现和评分记录；候选在执行时可以对合法当前信息做内部物理计算，但不能通过日志、文件、网络或额外仿真通道向开发 agent 回传完整目标轨迹或等价分数。

## 3. 控制单元、动作与局部观测合同

MAPDN 两个 mode 的命名按原代码保留，不互换含义。

| 上游 mode | 控制单元 | 动作 | 默认局部信息 |
|---|---|---|---|
| `distributed` | 每台 PV 逆变器一个；33/141/322 分别为 6/22/38 个 | 各自一个归一化无功命令 | 本区域各母线有功/无功负荷重建、电压幅值与相角；本逆变器自身 PV 有功与无功 |
| `decentralised` | 每个区域一个；分别为 4/9/22 个 | 本区域所有 PV 的无功向量，按设备映射检查 | 区域母线量和区域 PV 有功/无功向量 |

上游 `distributed` 观测不是仅有自身母线数据，也没有显式附带区域所有 PV 的独立有功/无功向量。区域负荷重建与设备顺序必须经过独立小例核对；零填充不能代替设备和母线索引元数据。[观测源码](https://github.com/Future-Power-Networks/MAPDN/blob/6895f1f0630b112745a3f681d7685d454407f9cb/environments/var_voltage_control/voltage_control_env.py#L232-L319)

拟定局部主线使用 `distributed`；实际发布时必须冻结 mode、区域、设备顺序、单位、相角表示、历史长度和可见静态参数。候选的每个控制单元只接收自己的当前观测和私有历史状态；可共享离线参数，不能通过共享运行内存、全部观测 batch 或 evaluator 文件交换全网信息。通信扩展需另行固定消息字段、方向、频率与字节预算，并与无通信主线分表报告。

物理映射为：

\[
q_{i,t}=a_{i,t}\sqrt{S_{i,\max}^{2}-P_{i,t}^{2}}.
\]

上游容量为整份 PV 数据最大值的 1.2 倍；训练辅助代码将归一化动作限制为 33/322 的 ±0.8、141 的 ±0.6。正式 task 需冻结可见额定容量与共同动作界，所有方法使用同一范围。可信侧检查设备数量、顺序、有限数、归一化范围和物理容量，拒绝或按预注册规则处理非法动作；不能依赖候选自行截断。上游 `_clip_reactive_power` 实际只做乘法，直接调用 `step` 可绕过训练辅助代码中的截断。[容量与映射](https://github.com/Future-Power-Networks/MAPDN/blob/6895f1f0630b112745a3f681d7685d454407f9cb/environments/var_voltage_control/voltage_control_env.py#L518-L575)、[动作尺度](https://github.com/Future-Power-Networks/MAPDN/blob/6895f1f0630b112745a3f681d7685d454407f9cb/utilities/util.py#L123-L132)、[分网络设置](https://github.com/Future-Power-Networks/MAPDN/blob/6895f1f0630b112745a3f681d7685d454407f9cb/utilities/util.py#L202-L216)

控制器接口为 `Controller(metadata).act(observation)`，返回该控制单元对应的扁平归一化动作列表；私有历史放在实例自身状态中。metadata 只包含获准的局部设备边界、额定容量与索引，不能夹带全网观测或目标轨迹。外层源码包继续使用仓库的 `{input}` / `{output}` argv 设计声明；逐步观测与动作由可信运行器负责传输。

`powergrid_bench.distribution.mapdn` 的动作检查、物理无功映射和局部字段投影属于基础合同模块，不是完整 MAPDN 仿真运行器；字段投影本身不证明进程安全隔离。准备工具只向可信评测侧暂存和核验上游源码，不能将完整上游仓库放入开发镜像。具体传输格式、worker 隔离和运行绑定以[配电网接入说明](../framework/distribution-control-integration.md)及后续验收为准。

## 4. 物理指标与排名

电压安全范围沿用候选默认值 0.95–1.05 p.u.，正式发布冻结边界、受评母线集合与数值容差。至少分别记录：

- CR：全体受评母线同时合规的时间间隔比例。
- 母线 × 时间的电压越界比例、最大欠压与最大过压幅度。
- 实际有功损耗功率及全时域损耗电量 MWh；按每个间隔真实长度积分。
- 无功使用量、非法动作、潮流不收敛、完成间隔数、运行时间、内存和内部潮流调用次数。

上游默认训练 reward 为电压 barrier 加 `0.1 × mean(abs(Q))`；Q 项是代理量，不能直接报告为真实网损。其 `total_line_loss` 仅求和 `res_line.pl_mw`，尚未覆盖变压器等其他损耗元件。可信侧需按实际网络元素计算总有功损耗，并与全网功率平衡交叉检查，特别核对多电压等级网络。[reward 源码](https://github.com/Future-Power-Networks/MAPDN/blob/6895f1f0630b112745a3f681d7685d454407f9cb/environments/var_voltage_control/voltage_control_env.py#L577-L626)

建议先比较电压可行性，再在相同可行性合同下比较实际损耗；**正式家族的最终排名规则、权重、失败分与反馈精度尚未冻结**。canary使用其运行包内预先固定的校准公式，不能外推为正式主指标。不能在看到正式结果后选择更有利的指标。候选自报 reward 或损耗不具权威性；基础设施失败应记录为缺失并按恢复政策处理，不编造算法分数。

## 5. 环境、数据与版本准备

| 资源 | 已核查版本或准备要求 |
|---|---|
| MAPDN 源码 | `Future-Power-Networks/MAPDN@6895f1f0630b112745a3f681d7685d454407f9cb`，2026-05-10 提交 |
| 上游依赖 | Python 3.10、Pandapower 3.3.0、Pandas 2.3.3、NumPy 2.2.6、Gym 0.26.2、PyTorch 2.9.0；该整套上游训练环境与canary独立运行镜像分别记录 |
| 数据快照 | HF `hsvgbkhgbv/Multi-Agent-Power-Distribution-Networks@a41d8c269e402a827d36d9a153a4bce73a990e53` |
| 电压控制数据 | `voltage_control_data.zip`：3,763,536,396 字节；LFS SHA-256 `002de887013e8a2dbd2d79e5b6e2ed2c00584f3cf1ae81947f986061cfd81de2` |
| 传统控制数据 | `traditional_control_data.zip`：2,241,575,724 字节；LFS SHA-256 `467bc1c04611dbc9f66cae3d614cbc4e1c2936f5e78033bc6804da28e6ec7bc8` |
| 运行输入 | `model.p`、`pv_active.csv`、`load_active.csv`、`load_reactive.csv`，分别记录解压文件哈希、原始时标、网络和设备映射 |

上述压缩包大小与 SHA-256 来自公开元数据，**不是本仓库下载后的本地校验凭证**。准备时应显式选择网络，只在可信环境获取和核验数据；不要在包导入或普通测试中自动下载数 GB 文件。仓库基础包要求 Python ≥3.11，而上游环境为 Python 3.10，应使用隔离运行环境，不能直接假定二者已兼容。[依赖文件](https://github.com/Future-Power-Networks/MAPDN/blob/6895f1f0630b112745a3f681d7685d454407f9cb/environment.yml)、[锁定数据目录](https://huggingface.co/datasets/hsvgbkhgbv/Multi-Agent-Power-Distribution-Networks/tree/a41d8c269e402a827d36d9a153a4bce73a990e53)

canary已获取并校验选定33节点的四个完整ZIP成员，保留CRC32、成员SHA256与case manifest，不宣称校验整份3.7GB压缩包。其Python3.12/Pandapower3.3.0运行依赖使用[独立离线锁](../../task-packages/mapdn-voltage-control-canary-v1/images/requirements.lock)，实际镜像ID、归档哈希和目标集群验收见[流程记录](../experiments/distribution-canary-20261015.md)。

MAPDN 代码与 HF 数据卡声明 MIT；原始 UCI 用电数据标为 CC BY 4.0，Elia 历史 PV 数据列有独立 Open Data Licence。还需核对实际历史导出、改造网络、MATPOWER case 与 SimBench 来源的许可和署名，不能用顶层 MIT 抹去所有来源义务。数据与权重许可审计完成前不将完整数据重打包发布。[MAPDN LICENSE](https://github.com/Future-Power-Networks/MAPDN/blob/6895f1f0630b112745a3f681d7685d454407f9cb/LICENSE)、[UCI 来源](https://archive.ics.uci.edu/dataset/321/electricityloaddiagrams20112014)、[Elia 数据说明](https://opendata.elia.be/explore/dataset/ods032/)

## 6. 时序、重放与失败处理的必修项

1. **时序对齐。** 上游先求解/计分，随后修改外生输入而未重算结果表，再递增步数，可能形成新 PV 值与旧母线潮流结果混用。重置从 `steps=1` 开始，按源代码逻辑 limit=240 对应 239 次有奖转移；自然日测试 limit=480 也不能直接当作 480 次计分。正式运行器需定义观测、决策、求解、计分和前进的唯一时间顺序，并验收首末间隔。[源码顺序](https://github.com/Future-Power-Networks/MAPDN/blob/6895f1f0630b112745a3f681d7685d454407f9cb/environments/var_voltage_control/voltage_control_env.py#L96-L211)
2. **固定外生实现。** 提前冻结完整 P/Q 负荷、PV、噪声和初始 Q；使用 evaluator 私有随机流。上游使用全局 NumPy RNG、随机日期和正半正态噪声，同进程候选 RNG 会改变后续实现。仅保存 seed 不足以证明与候选代码无关的重放。[输入更新](https://github.com/Future-Power-Networks/MAPDN/blob/6895f1f0630b112745a3f681d7685d454407f9cb/environments/var_voltage_control/voltage_control_env.py#L494-L516)
3. **观测不因读取次数改变。** 验证区域负荷重建的 Pandas 链式赋值；历史仅在物理步前进时更新；保留独立的逐步指标副本，避免共享字典别名。
4. **失败不可获利。** 上游失败后固定扣 200 并提前终止，不能直接用截短累计 reward 排行；正式合同应规定完整时域的失败处理。重置重试需有限，不能遇到固定不可解初态无限循环。
5. **进程与目录隔离。** 输入只读，控制单元状态相互隔离，每作业独立工作目录；禁用共享绘图输出。不能复用会删除同名日志的训练驱动作为评测入口。
6. **322 导入单独验收。** [上游 issue #51](https://github.com/Future-Power-Networks/MAPDN/issues/51)报告 Pandapower 3.3.0 读取该网络 pickle 时出现 `KeyError: 'type'`；这是未在本 task 重现的报告，不能既当作已修复，也不能当作数学难度证据。

前期审计仅用提取的上游函数和替身验证“未截断映射”和“239 次调用”的局部逻辑。后续canary已修正因果步序，并在真实Pandapower中完成33节点全天480步、动作边界、功率平衡、总损耗、重放和隔离检查；这些证据不自动覆盖141/322节点或原上游训练驱动。

## 7. 基线与难度校准

2026-10-16的[选例基础实验](../experiments/distribution-case-selection-20261016.md)后已完成[强基线补充](../experiments/distribution-baseline-qualification-20261016.md)：四候选日各运行源码对齐迭代droop、单步松弛及两档积分反馈，共16条完整480步轨迹，全部电压CR100%。因此撤回此前由弱单步droop得出的“2月日仍有30.83个百分点电压缺口”判断。33节点2012-02-03可保留为安全约束下降损候选：已测同CR最低局部损耗1.835251MWh，全信息OPF为1.298685MWh；33最大PV日和141节点7月日为备选，后者仍需完整局部进程资源验收。其他141节点OPF复核欠压或失败不能解释为物理不可行。旧canary和失败记录不改写，正式主case尚未冻结。

新增迭代droop保留原曲线、0.1松弛、100次上限及停止机制，但使用共同动作边界和Python后端，是算法移植而非原MATLAB论文分数复现；其重复物理反馈与全PV停止判据单列权限。新增单步策略只用各actor合法当前观测。完整参数、真实网损、内部潮流及证据见补充报告。

最低基线为零无功、单次分段 droop、调参 droop、局部仿射规则、短历史局部规则；再加入可复现 MARL 控制器和集中式 AC OPF 参考。OPF 的全网测量与拓扑权限必须显式列出，不与局部策略混称同信息公平排行；非线性求解器未证全局最优时不称最优上界。

仓库提供 MATLAB/MATPOWER droop 与 OPF 源码，但不能直接搬用早期论文数值：传统脚本使用完整 ±Qmax、带符号高斯噪声和独立随机起点，droop 每个外生时刻最多 100 次内部潮流迭代；Python 训练辅助动作只有 60%/80% 容量且噪声实现不同。需要统一轨迹、初始化、容量、控制频率、内部计算机会和损耗口径，检查 OPF `success` 与实际约束。[droop 实现](https://github.com/Future-Power-Networks/MAPDN/blob/6895f1f0630b112745a3f681d7685d454407f9cb/traditional_control/pf_droop_matpower_all.m#L121-L160)、[OPF 实现](https://github.com/Future-Power-Networks/MAPDN/blob/6895f1f0630b112745a3f681d7685d454407f9cb/traditional_control/opf_matpower_all.m#L56-L99)

MATPOWER/MIPS 有 BSD-3-Clause 许可和 GNU Octave 路径，不天然要求商用优化 solver；确切脚本的 Octave 与统计包兼容性尚未验证。若使用 MATLAB 或其他 solver，版本、许可、线程与资源需锁定。[MATPOWER 安装](https://matpower.org/about/get-started/)、[MIPS](https://github.com/MATPOWER/mips)

原论文在历史采样中报告 33/141 的 droop 与 OPF 电压 CR 达到 100%；这提示电压指标可能饱和，不证明新固定轨迹仍难，也不证明局部规则必输 MARL。2024 年 PV 分配修复与 2025 年依赖更新后应重跑基线。[论文](https://arxiv.org/html/2110.14300)、[维护记录](https://github.com/Future-Power-Networks/MAPDN/blob/6895f1f0630b112745a3f681d7685d454407f9cb/README.md#L15-L19)

准入先导必须证明：强局部基线仍有实质改进空间；电压与真实损耗形成可解释差异；完整时域在统一计算限额内可运行。若调参 droop 已饱和，应保留证据并重新评估家族价值，不能削弱基线或改用代理奖励制造差距。

## 8. 发布与实验准入

以下全部完成前保持 `release_ready=false`：

- 数据与许可核验；冻结一个完整 case、容量、时域、噪声、初始条件和选择理由。
- 锁定运行环境并完成真实导入、动作界、观测时标、能量平衡、总损耗、首末间隔和失败处理验收。
- 实现局部信息传输与隔离；验证开发镜像、文件、日志、共享内存和网络均无完整目标评分旁路。
- 统一条件重跑强基线并测量 CPU、内存、加载、每步与全时域成本；冻结原始指标、排名与反馈 schema。
- 使用实际后端验证 n=0、n=1、超额拒绝、候选错误计数、共同截止、唯一 artifact 冻结和同 case 独立复核。

原[家族包骨架](../../task-packages/mapdn-voltage-control/README.md)继续保留待认证状态。新canary已有真实运行器、冻结完整日、物理校准、同一评分入口及目标集群Linux隔离验收；MAPDN n=0/1模型开发、反馈计数、截止候选哈希和同case终评已通过原生审计，但单次流程校准不替代正式扩展认证。首个旧版本n=0作业因Harbor参数类型在调用模型前失败，保留记录后用新准备版本完成；该失败、构造预检和环境验收均未冒充已完成实验。具体版本及证据见[流程校准记录](../experiments/distribution-canary-20261015.md)。[机器声明](../../manifests/task-adapters/mapdn-voltage-control.json)、[接入说明](../framework/distribution-control-integration.md)
