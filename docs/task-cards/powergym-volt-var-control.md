# PowerGym 配电网混合设备 Volt-Var 控制

> 扩展家族，状态：`design / certification-pending / release_ready=false`。2026-10-15 已完成上游源码与数据打包逻辑核查；尚未安装锁定仿真环境、运行完整 case、校准参考方法或完成原生 task runner。本文不是可启动的正式实验配置。

## 1. 家族定位与演化对象

**家族 ID：`powergym-volt-var-control`。** 在配电网内联合控制电容器开关、调压器分接头和电池充放电，研究离散与连续动作的协调、设备操作代价、跨时段 SOC 管理以及电压与实际有功网损的权衡。它给现有 L2RPN 输电网拓扑控制增加不同的设备和能量约束，不以“又一个 RL 环境”作为加入理由。

演化对象是可执行控制算法：电压滞环、设备优先级、候选动作筛选、坐标搜索、短视规划、SOC-aware 规则，或具有可追溯训练流程的策略。提交源码、参数、依赖和可选权重；截止后重新执行冻结算法，不接受以保存好的动作轨迹替代算法。默认推理阶段不调用在线 LLM。

这是新增的**待验收扩展家族**，没有自动加入原五任务的 75 个正式开发 run。后续增加实验需另行冻结配置和启动清单；本次新增文档与基础合同不构成提交集群实验的授权。

## 2. 上游版本与事实边界

上游仓库锁定为 `siemens/powergym`，提交 **`c9fc6d8357308a1f2bd2389474b56089c2a6bd78`**。该提交日期为 2022-08-03（上游时区）；2026-10-15 核查时仍是 master HEAD。论文为 PMLR 168:21–33，2022；扩展技术说明为 arXiv:2109.03970v3。[固定源码](https://github.com/siemens/powergym/tree/c9fc6d8357308a1f2bd2389474b56089c2a6bd78)、[正式论文](https://proceedings.mlr.press/v168/fan22a.html)、[扩展说明](https://arxiv.org/pdf/2109.03970v3)。

| 项目 | 34Bus | 123Bus |
|---|---:|---:|
| 电容器 / 调压器 / 电池 | **2 / 6 / 2** | 4 / 7 / 4 |
| 默认完整 episode | 24 步，每步 1 小时 | 24 步，每步 1 小时 |
| vanilla 动作 | 电容器 0/1；分接头及电池均为 33 档 | 同左 |
| `_cbat` | 电池改为 [-1,1] 连续功率命令 | 同左 |
| 电池额定功率 / 容量，每台 | 500 kW / 4000 kWh | 100 kW / 1000 kWh |
| 上游初始 SOC | 每台 1.0 | 每台 1.0 |
| vanilla 终端 SOC 权重 | 0 | 0 |
| `_soc` 终端 SOC 权重 | 500/33 | 500/33 |

34Bus 的 README 写成 4 个电容器，但实际日模式 DSS 只有 C844 和 C848；本卡采用源码的 2 个。设备数量不直接代表控制难度。[34Bus 设备定义](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/systems/34Bus/ieee34Mod1_daily.dss#L59-L78)、[34Bus 电池](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/systems/34Bus/Battery.csv#L1-L3)、[123Bus 电池](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/systems/123Bus/Battery.csv#L1-L5)。

## 3. 第一阶段：完整固定 case 与严格 n

采用[决定 0005](../decisions/0005-fixed-case-evolution-first.md)：同一个完整 case 用于开发面向的目标、计数过程反馈和截止后的独立重执行。跨 case 泛化放到第二阶段。候选 case 是完整的一天及冻结的 feeder、负荷数组、初态、设备、动作和评分合同，不随机裁取一天中的若干时间行。

| 研究项 | 本扩展采用的政策 |
|---|---|
| 开发上限 | T=43200 秒，即 12 小时；与单步或整 episode 执行预算分别记录 |
| 过程反馈 | n=0/1/3/5/10，每档 3 次独立算法开发；只有后续启动该扩展时才形成其运行清单 |
| token | 无累计 token cap，无累计 token 预留截断；记录实际 provider 用量 |
| 唯一最终产物 | T 内放入原生 artifacts 路径的最终版本，截止冻结；无修改保留 starter |
| 选模 | 依据已消耗 n 获得的反馈；取消免费完整 public-selection 算分 |
| 最终复核 | 同 case 执行唯一冻结算法并独立评分，不占过程 n，不回流开发，不择优重复终评 |
| 当前未定 | 具体 case / track、模型、硬件、执行时限、搜索权限、seed、反馈精度与字段 |

完整目标评分只能通过框架计数入口取得。n=0 没有过程完整目标评分；非法候选或算法超时仍消耗已经受理的作业。基础设施故障的原样重试保留同一逻辑作业。语法、导入、动作格式和 toy 数据检查允许；不能借这些工具重算完整目标分数。

**PowerGym 的特殊隔离缺口：** 完整公开负荷、完整仿真器和目标公式足以重建完整评分；原生 `step()` 的 reward、完整电压/损耗轨迹和可重构诊断也能泄露等价结果。只隐藏一个 `score` 字段或删掉一个 checker 文件不足以证明严格 n。开发可见完整目标数据的范围必须在 release 中冻结，并实际检查文件、包、日志、网络与搜索权限。完整 target 环境及完整 checker 不随开发包分发；若提供公开物理模型或搜索辅助接口，须确保其输出不把完整目标评价免费送回开发 agent。候选在受信执行阶段的获准内部物理计算与优化不按完整评分次数逐次计 n，但其反馈和副产物遵守相同的信息边界。

## 4. 选例与完整性

优先在 34Bus / 123Bus 候选及预先声明的负荷尺度中，以同条件参考方法测可行性、控制质量、耗时和动态设备贡献，再选一个尽可能困难、完整且可运行的 case。不能按母线数量、原始 reward 大小或一次运行失败直接选“最难”，也不能先观察 n 效应再挑 case。123Bus 不自动比 34Bus 更难。

**上游尺度名不是单变量变化：** `_sK` 将负荷乘 K，同时把 `soc_w` 乘 K²；`_soc` 除终端 SOC 代价外还改变放电权重。case manifest 必须保存所有实际权重，不能只写一个环境名。[34/123 配置](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/env_register.py#L96-L198)、[尺度解析](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/env_register.py#L262-L276)。

完整性要求保留全部选定设备、全日负荷时序、24 个动作转移、初始能量和指定终端规则。若使用更长时域，须新冻结步长、负荷打包与日间状态衔接，不能悄悄把更多步当成原始 24 小时任务。所有 n 档采用相同 case、动作能力和算法执行预算。

## 5. 原生与物理适配分轨

| 轨道 | 冻结内容 | 可作出的结论 |
|---|---|---|
| `powergym-native-v1-proposed` | 锁定上游物理实现、动作、有效权重与 native return，明确 vanilla / `_soc` / `_cbat` 选择 | 所选上游语义下的固定 case 算法表现；不能声称已经消除终端能量优势 |
| `powergym-physical-adapted-v1-proposed` | 独立定义初末 SOC、公差、P/Q 关系、效率、动作有效性、失败与主指标 | 新物理适配合同下的表现；须全方法同合同重跑，不能沿用论文分数 |

两轨均为提议版本，**尚未选择正式主轨**，不能混排。原生轨的 `_soc` 只是最后一步的 `soc_w × sum(|SOC_H−SOC_0|)` **软惩罚，没有硬终端等式**。vanilla 的 `soc_w=0`，允许终端能量下降，只收逐步正向放电代价。若新轨要求末 SOC 回到初值，应先校准再冻结容差与不可行处理，不在此随意写一个数值。[原生控制奖励](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/env.py#L337-L348)。

上游电池是 Generator 加 Python 能量账本，不是 OpenDSS Storage：命令先按剩余容量投影，解潮流后用实际有功积分更新能量，再裁到容量内并四舍五入到整数 kWh。账本没有独立充放电效率。源码把 `pf` 标为 power factor，但实际设置 `kvar=kw/pf`；通常固定功率因数的幅值关系应为 `|Q|=|P|tan(acos(pf))`。这是需要物理验证的源码疑点，本次没有运行仿真证明其具体后果。不能未经说明把它修正后仍称原生复现。[命令与能量更新](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/circuit.py#L256-L318)、[pf 与投影](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/circuit.py#L775-L840)。

## 6. 信息、动作与执行接口

默认 observation 是全网各相电压幅值、电容器状态、调压器分接头和电池 SOC/归一化实际功率，属于集中观测。当前负荷默认不在 flattened observation 中；时刻和 loss 虽在内部字典中，也默认不进入扁平向量。是否显式提供时刻、当前负荷或预测，必须对所有方法一致冻结。不能将本轨称为 MAPDN 式局部观测比较。[观测配置](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/env.py#L226-L314)、[flatten](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/env.py#L563-L587)。

基础 starter 控制器合同为 `Controller(metadata).act(observation) -> flat_action`，动作依次为 caps、regs、batteries；episode 内状态保存在 controller 实例中，每次复核新建实例。metadata 包含动作数量、电池是否连续、tap/battery 最大档位等 schema 信息；observation 只提供当前 caps/taps/SOC 和获准电压，额外信息须另行冻结。对象顺序、相序、单位、动作整数性和范围必须明确。原生 Env 在 `all_load_profiles` 中保存完整未来负荷，**不得直接把可信评测 Env 对象交给任意候选代码**。在线控制仅给当时合法观测与获准 forecast；若另开先知全日优化参考，需单独标记信息优势。[reset 保存全日数据](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/env.py#L457-L503)。

原生分接头可直接跳任意合法档位，并以移动档数收费；若加入爬坡、最小驻留或操作次数硬限制，属于适配轨的新约束。检查器必须在写入设备前拒绝非有限、错误长度、非法类型或越界动作；不能靠投影悄悄修复后仍计作原合法动作。源码还在设置 Tap 时写入 `NumTaps=tapnum`，须用锁定后端验证分接头实际语义。[调压器 setter](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/circuit.py#L218-L254)。

基础合同模块为 `powergrid_bench.distribution.powergym`，提供动作检查、保持当前设备且电池 idle 的动作构造及终端 SOC 容差判定；`powergrid_bench.distribution.profiles.pack_profiles` 接收显式有序的源 CSV，纯标准库打包并记录 raw hash、跨文件源行映射、未用尾行与 packed hash，不运行评分。完整范围与当前验收证据见[配电控制接入说明](../framework/distribution-control-integration.md)。它们不等于已接通的 OpenDSS runner、完整潮流仿真或完整目标评分服务。source 准备工具只向可信评分侧复制并核对上游版本，不把完整上游仓库装入开发镜像。原生接入目录为[task-packages/powergym-volt-var-control](../../task-packages/powergym-volt-var-control/)；机器声明中的 argv 是待实现模板，不能据此启动正式实验。

## 7. 评分与实际有功网损

原生 return 是电压违约、控制代价与加权损耗比的负和。电压项对每个 bus 计最坏高相超出 1.05 pu 与最坏低相低于 0.95 pu 的幅度，并不是电压合规率。原生损耗比为：

`rho_t = −(ActiveCircuit.Losses[0]/1000) / ActiveCircuit.TotalPower[0]`。

reward 使用前将其截到 [0,1]；分母是当前源端有功，随电池调度变化，并非固定需求。比值之和不等于实际损耗电量；反向潮流或接近零的分母还需明确失败/数值政策。不能把 native return 或 `sum(rho_t)` 标成 kWh 网损。[损耗单位](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/circuit.py#L618-L624)、[比值与逐步评分](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/env.py#L330-L373)。

每次可信完整评估至少保存以下原始量；开发端只获得批次前批准的反馈字段与精度：

- 原生轨的准确 native return 与所有有效权重；适配轨独立主指标/排序规则，尚待校准冻结。
- 实际有功损耗电量 `sum(P_loss_kW × delta_t_h)`；注明采用 whole-circuit loss，包含被 OpenDSS 计入的变压器等损耗，不能误写成仅线路损耗。
- 相位×时刻电压合规率、最差电压及累计违约幅度；电压窗口和统计分母固定。
- 电容器切换次数、分接头移动档数、命令与实际电池功率、吞吐电量及每台初末 SOC。
- 完成步数、求解收敛、无效动作、算法耗时与资源；算法失败和基础设施失败分别记录。

上游直接 Solve 后取值，未显式检查 `Solution.Converged`，done 只看时域。适配验收须定义不收敛、NaN、分母异常、非法动作、越界时间调用和超时的处理，不给无效轨迹静默生成正常分数。[原生 step](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/env.py#L375-L455)。

## 8. 原始数据打包、来源与第二阶段

当前日模式源码中，34Bus 有 68 个 load，123Bus 有 91 个。上游把文件名含 loadshape 的 CSV 按 **未排序的 `os.listdir`** 次序串联，再依 load、episode、step 分块；episode 数为 `floor(总行数/(24×load数))`。本次对固定源码与原始单列 CSV 静态清点得到：

| feeder | 原始 CSV | 24 步 packed profile 数，非原始日历日；静态推导 | 未使用尾行 |
|---|---|---:|---:|
| 34Bus | LoadShape1/2/3，各 8760 行，共 26280 行 | **16** | 168 |
| 123Bus | 同上，另有 8760 行 PaperLoadShape，共 35040 行 | **16** | 96 |

这不是已经实例化 Env 的运行结果；8760 行也不证明一年同步的全网实测负荷。输入没有 timestamp 或来源标识，本次未找到足以确认采集地点、日期、原始序列许可的 manifest。三份 LoadShape 文件在 13/34/123 feeder 间字节一致。[文件发现与打包](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/loadprofile.py#L10-L28)、[分配与截尾](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/loadprofile.py#L168-L218)、[34 输入目录](https://github.com/siemens/powergym/tree/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/systems/34Bus/loadshape)、[123 输入目录](https://github.com/siemens/powergym/tree/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/systems/123Bus/loadshape)。

release 必须冻结原始文件顺序与 SHA-256、active load 顺序、打包算法版本、截尾、生成数组、选定 profile、初态和 effective scale。若改为排序文件以消除平台差异，应标记新的打包版本并重跑基线，不能假设原 profile ID 仍指同一日。第二阶段按原始序列来源和连续时间组件分组；来源尚不明确时不得宣称独立时间泛化，不能随机拆相邻或插值时间行。

DSS 日模式从 hour=0、stepsize=3600 开始；reset 用 SolveNoControl，后续 step 用 Solve，并可能以 `t % horizon` 提取当前负荷。第一步、最后一步与负荷行的确切时序尚未实测，须用可辨识 toy ramp 逐步核对，防止错位或尾行环回。[日模式设置](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/systems/34Bus/ieee34Mod1_daily.dss#L249-L253)。

## 9. 基线与论文可复现性

最低参考面板：seeded random、保持当前设备状态且电池 idle、native DSS、电压滞环加 SOC-aware 控制、受限坐标/短视搜索；RL 作为另外实现并同合同重跑的可选强基线。**全零动作不是 DoNothing**：它关电容器、取最小 tap，并在离散电池中请求充电；离散电池 idle index 为 16，连续为 0。初始化 regulator 在最大 tap，caps on。[动作映射](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/env.py#L143-L157)、[电池档位](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/circuit.py#L788-L801)。

native DSS 模式和直接算法模式必须区分。默认 `dss_act=False` 关闭自动控制；`dss_step()` 开启原 DSS 控制，但明确不控制电池。34/123 active daily 文件没有 CapControl，因此该参考主要是调压器自动控制、其余按初态/idle，而非全设备最优基线。直接动作赛道不得无意叠加自动控制。[ControlMode](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/circuit.py#L78-L100)、[dss_step](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/env.py#L513-L561)。

论文比较 PPO、SAC、连续电池 SAC 和 random，但当前仓库没有对应训练代码或权重；维护者也明确说明未发布这些 agent。不能把外部通用 SAC 直接当原论文多离散/混合动作实现。论文随机 profile halves 与十 seed 的总表不是本固定 case 的基线分数，PowerGym 也没有可供本单日成绩插入的官方竞赛榜。[维护者确认](https://github.com/siemens/powergym/issues/4#issuecomment-1128028790)、[正式论文 §6.1](https://proceedings.mlr.press/v168/fan22a/fan22a.pdf)。

校准应同时比较 static-only、no-battery 和 full-device 控制：若静态 tap/cap 已解决问题，或提升仅来自花掉初始能量，则尚不足以证明这个 case 测出了混合设备跨期控制。先报告该情况，再按预先规则选其他完整可运行候选，不削弱基线或观察 n 效应后再挑选。

## 10. 依赖、并发与许可

上游声明 Python 3.8；requirements 锁 pandas 1.2.4、dss_python 0.10.7、gym 0.18.0、imageio 2.9.0、matplotlib 3.4.3、networkx 2.5、numpy 1.22.0。后端是 `import dss` 的 `opendss.DSS` 全局对象。仓库的 Python ≥3.11 基础合同不能证明这套旧仿真依赖已兼容；原生运行应在独立锁定镜像中安装并做数值回归。镜像、DSS C 引擎和完整 transitive lock 尚未冻结。[依赖](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/requirements.txt#L1-L7)、[后端](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/circuit.py#L4-L19)。

`worker_idx` 仅区分 main/profile-selection DSS 文件；生成 CSV 与 scale.txt 仍共享，reset 会重写选择文件。不同 scale 并发及同进程多个全局 DSS Env 不可据此宣布安全。每 worker/run 采用独立进程与完整私有工作目录，生成后冻结 profile；验证串行/并行复核一致性。[worker 文件](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/env_register.py#L283-L314)、[共享写入](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/loadprofile.py#L184-L230)。

代码仓库声明 MIT，分发须保留版权和许可；它不自动完成每份继承 IEEE/EPRI feeder、未知来源 CSV 与 DSS 依赖的独立来源核查。数据/资产许可核查尚待完成。[上游 LICENSE](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/LICENSE#L1-L7)。

## 11. 验收门槛与当前缺口

1. 锁定 34/123 候选、完整打包数据与有效权重；完成来源、许可、时序、原生/适配选择和选难例记录。
2. 独立安装镜像；验证 Solve 收敛检查、tap 实际档位、P/Q、命令投影、实际能量积分/舍入、初末 SOC、边界与异常动作。
3. 在可信端执行完整参考方法并重算 raw 指标；校准单步搜索、初始化、整日时间、CPU/内存与失败值；完成 static/no-battery/full 消融。
4. 将候选控制器接入真实 OpenDSS runner，隔离未来矩阵、开发文件/日志与完整 checker；检查同进程/目录共享和并发污染。
5. 走原生 task 生命周期短验：n=0 无完整目标过程反馈，正 n 计数、超额拒绝、失败计费、截止冻结、唯一 artifacts 同 case 复核；记录实际防旁路覆盖。
6. 冻结模型/资源、seed、反馈 schema/精度、release 摘要和新扩展的运行清单后，才可进入正式开发比较。

**本次没有运行上述 simulator / baseline / 集群验收，也没有新分数。** 基础合同通过本地 toy 检查也不能替代这些门槛。机器声明：[powergym-volt-var-control.json](../../manifests/task-adapters/powergym-volt-var-control.json)；接入说明：[distribution-control-integration.md](../framework/distribution-control-integration.md)。
