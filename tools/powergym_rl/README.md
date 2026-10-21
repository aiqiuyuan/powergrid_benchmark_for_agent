# PowerGym PPO / 整数 SAC 独立重训练

本目录实现论文方法在当前冻结物理合同上的独立训练。它不依赖未公开的作者权重，也不宣称复现原Gym环境、论文分数、十seed统计或全部网络。已公开设置、实现假设和合同差异见[来源核验](../../docs/experiments/powergym-rl-paper-audit-20261016.md)；[v2 pilot协议](../../configs/powergym-rl-pilot-20261016-v2.json)分别标注论文参数与重实现假设。

已完成[34Bus、seed0、每算法40k pilot及独立检查点评测](../../docs/experiments/powergym-rl-pilot-20261016.md)。两条固定40k最终策略均未满足8个留出日的末能量门槛，quality=0；结果和首次适配失败完整保留，不能据此将原论文的数值复现或正式选例认证标记为完成。

PPO使用按设备分解的categorical策略和联合log probability。SAC用straight-through Gumbel-Softmax采样独立one-hot，再映射到每设备一个整数标量供critic使用；没有用普通连续SAC取整代替该方法。两者仅读取当前合法观测，无在线潮流搜索或未来负荷。新增实现未复制作者训练源码；继承物理与数据的上游版权见[第三方声明](../distribution_qualification/THIRD_PARTY_NOTICES.md)。

## 数据与训练

由固定上游提交重建两网络各16条完整24小时profile，排序、分配、逐文件SHA及split进入独立池；旧选例池不改。seed0的训练索引为`[0,2,3,4,5,7,10,11]`，留出为`[1,6,8,9,12,13,14,15]`。这是packed-profile留出，不保证日历来源独立。p0已见，p6/p15留出，不能混称盲测。

pilot只运行34Bus标准负荷、每算法seed0、40000次真实训练交互。每120次交互评测全部留出profile，只作诊断；固定使用40000步最终权重，禁止按test择优或调参。20000步保存未满PPO rollout，最终40000步才flush。SAC warmup、网络初始化等未公开项在协议中列作假设。

训练采用论文vanilla reward，其末SOC权重为0；终评分别报告原账面末能量±1kWh有效性及额外实际净能量±1kWh的强参照门槛。无效轨迹保留真实指标、原因和0质量分，不能拿训练reward替代硬约束。该训练目标并未声称已经针对benchmark质量与末能量门槛调参。

## 运行

使用独立Python3.12环境。提供本批macOS arm64依赖哈希锁；其他平台须另行解析、锁定并记录环境，不能声称复用同一运行身份。

```sh
uv venv --python 3.12 RL_ENV
uv pip sync --python RL_ENV/bin/python --require-hashes \
  tools/powergym_rl/requirements-macos-arm64.lock

RL_ENV/bin/python tools/powergym_rl/train.py prepare \
  --source VERIFIED_SOURCE --pool NEW_POOL --split-seed 0

RL_ENV/bin/python tools/powergym_rl/train.py train \
  --algorithm ppo --protocol configs/powergym-rl-pilot-20261016-v2.json \
  --protocol-sha256 PROTOCOL_SHA --pool NEW_POOL --pool-sha256 POOL_SHA \
  --output NEW_RUN
```

SAC改用`--algorithm sac`和独立输出目录。协议须经过审查并标记`frozen`，输入SHA必须匹配；已有输出拒绝覆写或静默续跑。

```sh
RL_ENV/bin/python tools/powergym_rl/train.py evaluate \
  --run NEW_RUN --checkpoint NEW_RUN/checkpoint-020000.pt \
  --pool NEW_POOL --output NEW_CHECKPOINT_EVALUATION
```

检查点包含策略、优化器、随机流、未完成buffer和可重放的物理episode状态。已提供hash校验后的独立检查点评测；没有宣称完成端到端训练恢复入口。仅加载本运行产生且SHA匹配的可信检查点。

每次评测均保留完整24步，并用新后端核对重放；训练交互、评测交互、初始化、查询复核和实际重放潮流分开计数。私有逐时轨迹、模型权重和训练日志留在忽略目录；公开证据仅给指标、协议、来源及文件摘要。训练集反馈预算与正式Famou n轨道不同，只作为额外算法参照，不与n=0开发过程混称同预算公平排名。

## 首次运行与奖励适配修复

[v1协议](../../configs/powergym-rl-pilot-20261016.json)及首次失败输出完整保留。PPO / SAC 分别在第1109 / 1660个训练物理步遇到合法反向潮流；旧可选诊断将净反送电的损耗比记为`None`，训练适配因此停止。独立审计确认物理量有限，失败与算法数值发散无关。

v2仅在新RL层按原NumPy除法和`max(0,min(1,ratio))`顺序重建奖励，另存`rl_paper_vanilla_reward`与累计return，保留旧诊断。正损耗/+0取1，正损耗/-0取0，0/0按原clamp顺序取1；拒绝非有限物理输入，无分母epsilon。真实24小时反送电、独立重放和零点边界已加入回归验证。物理模型、算法、数据、超参数和预算不改；v2用新运行身份从头训练。
