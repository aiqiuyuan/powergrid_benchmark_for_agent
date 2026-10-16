# PowerGym PPO / SAC 复现核验（2026-10-16）

这次可完成的是基于公开论文与冻结数值合同的算法重实现和单 seed pilot。作者训练代码与权重未在核验的官方仓库中公开，当前 benchmark 的物理执行、终末能量约束及质量评分也有变化，因此不能把新结果标成论文 Figure 2 数值复现。以下页码均为 PDF 文件从 1 开始的页码。

## 可复现性判断

PowerGym 的环境与数据公开程度足以支持固定源码后的环境复跑；PPO / SAC 的描述足以指导独立重实现，但不足以唯一恢复作者完整训练过程。主要缺口是作者训练源码与权重、实际 train / test profile 身份、10 个随机 seed 的编号、完整运行配置以及若干网络 / 更新设置。Figure 2 标题的 40k 与横轴 20k 差异也未消除。因此，本次尚不能认证原论文曲线的数值可复现性；这不等于证明论文结果无法复现。

本项目新基线应称为“参照论文公开设置的独立重实现，在当前 benchmark 条件下重训”。单 seed pilot 只能验证流程和暴露合同问题，不能替代论文多 seed 的统计比较。我们自身的运行固定源码、数据、配置、依赖和计数，并保留失败记录，以便其他人复查同一实验。

## 论文明确公开的设置

| 项目 | 已确认内容 | 一手来源 |
|---|---|---|
| 动作与观测 | PPO / SAC 默认 MultiDiscrete；cbat_SAC 仅电池连续。电容 2 档，tap / 离散电池各 33 档；全网电压、设备状态、SOC、归一化实际放电功率 | [PowerGym p5](https://proceedings.mlr.press/v168/fan22a/fan22a.pdf#page=5)、[扩展版 A.2 p18](https://arxiv.org/pdf/2109.03970#page=18) |
| episode / 划分 | H=24，一小时一步；profiles 随机对半 train / test；每 5 episodes 评测；10 seeds。具体 split / seed IDs 未给 | [p8](https://proceedings.mlr.press/v168/fan22a/fan22a.pdf#page=8) |
| 训练量 | Figure 2 标题写 40k steps，横轴至 20k；Figure 5 为 20k。123Bus连续电池个案提到1000随机步，不能当作34Bus离散SAC的已知设置 | [p8–10](https://proceedings.mlr.press/v168/fan22a/fan22a.pdf#page=8) |
| PPO | Adam；lr=3e-4，gamma=.95，clip=.2，batch=64，update_interval=512，entropy=.01 | [扩展版 Table 6 p19](https://arxiv.org/pdf/2109.03970#page=19) |
| SAC | Adam；lr=3e-4，gamma=.95，batch=256，hidden width=512 / depth=3，entropy=.4；独立 policy / Q 网络 | [Table 6 p19](https://arxiv.org/pdf/2109.03970#page=19) |

Table 6 是 suggested hyperparameters，未给完整 launch manifest。PPO width / depth、activation、epochs、GAE λ、value coefficient、gradient clip、normalization，以及 SAC replay / tau / update ratio / 温度与精确初始化等均需显式记录为重实现假设，不能声称已由作者参数确认。

## SAC 的关键机制

SAC 的论文来源是 [Soft Actor-Critic With Integer Actions，§4 / Eq.9](https://arxiv.org/html/2109.08512#S4)。每个设备产生独立 categorical logits，straight-through Gumbel-Softmax 得到 hard one-hot，和 `[0,…,N−1]` 内积形成可微整数动作；critic 使用每设备一个标量。它不是把普通连续 Gaussian SAC 的输出四舍五入。cbat 还需要连续电池分支，公开 PowerGym 资料没有足以唯一重建该混合分支的全部实现设置；本轮先实现 PPO 和整数 SAC，cbat_SAC 单列为尚未完成。

## 作者实现 / 权重公开状态

[官方 issue #4，维护者 2022-05-16 回复](https://github.com/siemens/powergym/issues/4#issuecomment-1128028790)明确说明仓库只有 random controller，PPO / SAC 代码尚未公开，并指向两篇算法论文。截至本次核验，官方 `master` 为 `c9fc6d8357308a1f2bd2389474b56089c2a6bd78`；GitHub API 树有 93 个 blobs，仅 master branch，无 tags / releases，未发现 PPO / SAC 训练文件或 `.pt/.pth/.ckpt/.pkl/.h5` 权重。这个结论限定于本次核验的官方仓库，不推断作者私有实现。

issue #4 指向的另一篇 [Graph Policy Network 论文 p5](https://arxiv.org/pdf/2109.12073#page=5)采用 20,000 **episodes**、5 seeds、每 bus 最小相电压；它不是 PowerGym Figure 2 的完整配置，不能移植为 20,000 steps 或混用其观测设置。

## 冻结官方源码核对

核对本地 `work/distribution/powergym-verified` 与固定 commit；以下为直接代码事实。

- [random_agent.py](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/random_agent.py)按 profile index 随机抽一半训练，余下测试；每 5 episodes 评测。其计数器在每步加 1，episode 完成又加 24。它可能解释图中 40k / 20k 差异，但真实训练代码未公开，这只是推测。新运行必须记录真实 `env.step` 次数，不能靠复制计数错误达到预算。脚本默认 seed 123456 不能当作论文的 10 个 seeds。
- [env.py](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/env.py)默认 wrapped observation 包含所有相电压；min-phase 代码被注释，`observe_load=False`，无未来负荷、无时钟特征。vanilla reward 为电压越限、损耗比、开关 / tap 操作、正放电惩罚的负和。SOC 项仅最后一步生效，vanilla 的权重为 0；soc 变体仍是软惩罚。
- [env_register.py](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/env_register.py)的 34Bus vanilla 权重为 power=1、cap=reg=1/33、dis=10/33、soc=0；123Bus 为 power=10、dis=7/33，其余同上。34 / 123 的 soc 变体 soc=500/33，dis 分别 4/33、5/33；负荷 scaling 还会把 soc 权重乘 scale²。
- [circuit.py](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/circuit.py)的离散电池动作 `i` 对应 `(i−16)*Pmax/16`，idle=16；先按 SOC 投影可行动作，求解后使用实际 terminal P 更新整数 kWh 能量。原 regulator setter 同时把动作 tap number 写入 OpenDSS `NumTaps`；本 benchmark 固定 `NumTaps=32` 并设置物理 tap，属于执行差异。

## 数据与当前 benchmark 的区别

原始负荷文件可以重建 34Bus 和 123Bus 各 16 个完整的 24 步 packed profiles。旧 selection pool 只保存 0/3/6/9/12/15，不能用这六条冒称论文完整训练集；新 RL pool 由固定源重建全部 16 条，显式 CSV 排序与模型 load 顺序、source SHA / row assignment、split seed / IDs 均进入独立 manifest。旧 pool / task 不变。

[原 loadprofile.py](https://github.com/siemens/powergym/blob/c9fc6d8357308a1f2bd2389474b56089c2a6bd78/powergym/loadprofile.py)先以未排序的 `os.listdir()` 收集 CSV，再拼接 / 分配 profile。新 pool 的文件名排序是可复现适配，同一 profile index 未必对应作者当时目录枚举顺序的相同数据，不能声称恢复了作者 split 的字节身份。

[官方 issue #3](https://github.com/siemens/powergym/issues/3#issuecomment-1089656223)说明一小时采样、24 行为一个 nominal day，并给出 13Bus 的 profile 数量示例。这不证明当前不同 packed profiles 来自独立日历日。新 8/8 划分只能称 packed-profile holdout；源时间独立性仍未证实。任何在训练 split 中的固定案例，都不能作为 heldout 泛化结果。

| 合同 | 原论文 / 官方环境 | 当前正式案例合同 |
|---|---|---|
| 控制 | 每小时一次动作，全网观测 | 相同权限；无 oracle / 搜索，RL actor 无未来负荷 |
| 物理后端 | 当时 daily OpenDSS / Python 依赖 | 冻结 snapshot 执行；tap 设置、依赖版本等有差异 |
| 电池 | vanilla 无末 SOC 项；soc variant 软罚 | 初末能量差每电池 ≤1 kWh 为硬有效性条件 |
| 排名目标 | episode reward 的均值 ± 跨 seeds 波动 | 完整有效日后 `1/(1+V_puh+loss_kwh/1000+operations/33)`；无效 0 |
| 数据 | 多 profile 随机一半 / 一半 | 正式案例是固定单日；另建全 16 条 8/8 RL pool |

因此应同时报告论文 vanilla reward 诊断、真实 kWh 损耗、越限、操作、末能量、硬有效性和 benchmark quality；不同指标不互相替代。当前单 seed pilot 训练目标采用 vanilla reward，终评仍使用冻结的硬能量合同。这可以显示论文目标在新合同下是否产生可行解，但不能代表已针对新 quality / terminal 目标完成调参。

当前 qualification 还额外要求每电池实际 terminal-kW 的全天积分绝对值 ≤1 kWh，检查整数能量台账舍入可能掩盖的净放电；需同时报告原 benchmark valid gate 与额外 qualification gate，不能以新增 gate 冒充原 task 的评分定义。

## 本轮可执行复现安排

本轮冻结的是 34Bus 标准负荷、seed=0、PPO / 整数 SAC 两算法的 40k pilot；123Bus、更多 seeds 与 cbat_SAC 均未在本文件中声称完成。

1. 先测 factorized categorical PPO、整数 SAC 的动作 / 梯度 / episode 边界 / checkpoint 恢复与数据隔离，独立 code review 通过后训练。
2. 固定同一 8/8 split；训练 seed 与 split seed 分开。每算法先一个 seed、40,000 **真实训练 transitions**，20,000 保存包含未满 buffer 的 checkpoint，40,000 最终 flush。checkpoint 本身不改变 20k 时训练路径。
3. 每 120 个真实 train steps 做完整 heldout 8×24 诊断；20k 保存检查点后通过独立入口评测，40k 训练结束后最终评测，不用 test 选最优 checkpoint。40k 训练预计另需约 64k 评测 transitions；评测步数、reset / 初始化 PF、最终独立 replay 单独计数和计时，不混入训练 budget。
4. 论文 123Bus continuous-battery case study 明确提到 1000 随机探索步；pilot 把它作为整数 SAC 的 warmup，不能据此声称作者 34Bus 离散 SAC 的完整 launch 参数已知。PPO 直接 on-policy，不能用无策略标注的随机样本训练 PPO buffer。
5. pilot 结果按算法重实现与同合同评测报告。若要声称论文完整统计复现，还需解决 20k / 40k 计数歧义、原执行后端差异、完整配置缺失，覆盖原 13 / 34 / 123 / 8500 系统、10 seeds 并增加 cbat_SAC。正式案例冻结也需综合非 RL 的强参照，不能只看一个 seed 的成功与否。

本文件是来源核验和执行边界记录，不是训练完成收据。冻结 MAPDN 与原 selection 文件未因本审计改变。

## 本轮 PPO 显式实现假设

pilot 预设：独立 actor / value MLP 均 64×2、tanh、epochs=10、GAE λ=.95、value_coef=.5、max_grad_norm=.5、normalize_advantages=true。固定物理单位的观测缩放由 Env / train 完成，不从 heldout 数据估计统计量。这些值未被标为作者 PPO 训练默认值。20k checkpoint 不调用 `finish()`，40k 最终调用，state 保存 partial rollout、policy / value、optimizer、独立 RNG 与准确 update / transition 计数。

初始化采用 PyTorch 2.9 `nn.Linear` 默认值，Adam betas=(.9,.999)、eps=1e-8；联合 actor / value 梯度裁剪，无 value clipping / KL early stop。24 步 episode 作为真正 terminal、末状态 bootstrap=0；512 步 rollout 的非 terminal 末状态保留 bootstrap。这些也是实现选择。

当前独立 RL pool 以 `numpy.random.default_rng(0).permutation(16)` 固定 split：train `[0,2,3,4,5,7,10,11]`，heldout `[1,6,8,9,12,13,14,15]`。34Bus 固定案例 p000 在训练集，p006 / p015 在 heldout；任何对 p000 的结果只作为已见 profile 描述，不能与 heldout 平均混合。最终运行身份以冻结的协议 / pool SHA 为准。

## 首次运行的适配失败与纠正版本

首次 v1 运行分别在 PPO 第1109步、SAC 第1660步停止，此前完整训练日志为1108 / 1659条；尚未生成20k / 40k checkpoint。独立逐行复演确认，触发动作产生有限的反向潮流，源有功分别为−5.240503517 / −13.413255547 kW。旧可选诊断只为正源有功计算损耗比，反送电记为`None`，新训练入口错误地依赖该诊断作为必需奖励。此次失败属于训练适配缺口，不能据此评价 PPO / SAC 性能。

[v2协议](../../configs/powergym-rl-pilot-20261016-v2.json)在新的 RL 奖励层按固定上游的 NumPy 除法与原 `max(0,min(1,ratio))` 顺序重建损耗比：负源有功裁剪为0；正损耗除以+0为1、除以−0为0，0/0按原clamp参数顺序为1。非有限物理输入拒绝执行，不加分母epsilon。旧物理后端、旧诊断、算法、超参数、数据、随机 seed 和预算不变；新字段为`rl_paper_vanilla_reward`及累计return。

v1协议、源码快照、失败收据与日志均保留；v2用新的冻结身份从头运行。回归验证覆盖正向潮流逐步奖励、完整24小时反送电及独立物理重放、signed zero边界和错误记录。独立审查确认v2在旧停止点之前与v1训练逐项一致。该修复不构成基于留出成绩调参。
