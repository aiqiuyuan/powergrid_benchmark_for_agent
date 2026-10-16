# 配电网强基线补充

这些工具在可信评测侧运行传统控制与数值搜索，用来判断固定案例是否具有足够的控制难度。它们沿用第一次选例的候选池，不向开发 agent 提供额外目标评分入口。旧 canary、原32项封板源码及历史结果不改写。

算法、案例和预算先冻结在[主协议](../../configs/distribution-baseline-qualification-20261016.json)。PowerGym 查询与终评的求解初始化另按运行前冻结的[数值补充协议](../../configs/distribution-baseline-qualification-20261016-numerics.json)执行，并重跑旧四类控制作同设置校准。完整结果与解释见[补充报告](../../docs/experiments/distribution-baseline-qualification-20261016.md)。

## MAPDN

在原选择工具准备的只读候选池上运行。`SOURCE_M` 必须是主协议固定提交的 `pf_droop_matpower_all.m`，程序核验其 SHA256，不执行或下载 MATLAB。

```sh
python tools/distribution_qualification/mapdn_qualification.py \
  --pool-dir POOL --output NEW_OUTPUT \
  --protocol configs/distribution-baseline-qualification-20261016.json \
  --source-matlab SOURCE_M \
  --case-id mapdn33-2012-01-02 \
  --case-id mapdn33-2012-02-03 \
  --case-id mapdn33-2014-05-28
```

141节点使用独立的池和输出目录，指定 `--case-id mapdn141-2012-07-01`。运行需要原 canary 锁定的 Pandapower 环境。

每案例四条参考：源码对齐的迭代 droop、单步松弛反馈、积分反馈 gain=1.0/2.5。迭代 droop 在固定外生快照内最多100次内部潮流，松弛系数0.1，先计算原斜率20曲线再按共同动作界裁剪；每快照从零无功开始。停止条件沿用 PV 电压 L2 变化1e-4，并单独报告是否达到。末次未求解的更新不计分，最后已求解动作再做独立潮流复核。

这是对原算法机制在当前 Python/容量/时序合同下的移植，不能称为原 MATLAB 环境或论文实验复现。迭代参考拥有额外物理反馈机会和全 PV 停止判据，须与每间隔只取一次合法局部观测的单步策略分表比较。全信息 OPF 沿用第一轮完整日结果，另列其信息权限。

## PowerGym

使用第一轮已校验的完整池目录和原 canary 的 dss-python 环境。新输出目录接受全部五案例；`--case-ids` 仅用于显式选择已冻结子集。

```sh
python tools/distribution_qualification/powergym_qualification.py \
  --pool POOL \
  --protocol configs/distribution-baseline-qualification-20261016.json \
  --numerics configs/distribution-baseline-qualification-20261016-numerics.json \
  --output NEW_OUTPUT
```

每案例比较全天固定设备、当前快照强搜索、全天可变设备、允许空闲的含储能搜索、强制实际非零储能吞吐参考；另重跑原四控制器。搜索按电压越界积分优先，再按原 canary 网损与操作项比较。静态和全天搜索可看未来，当前搜索只看当前负荷和模型；它们均不是全局最优证书。

保持原 Generator 无功约定、实际端口有功能量积分、命令投影、整数 kWh 舍入及每电池终态±1 kWh。强储能参照额外要求每电池实际净能量绝对值≤1 kWh；同时报告命令能量、实际净能量、吞吐、逐步舍入/裁剪残差。允许空闲时找到的最佳候选若未用电池，仍保留强制活动的最佳候选，即使后者更差。储能搜索固定在 `oracle_day_idle` 的设备计划上追加充放电，没有联合重搜全部设备与储能动作。

运行前回归发现 DSS 热启动历史会影响半整数能量附近的舍入和后续动作投影。因此本批全部查询与独立24步重放均先设容差1e-10、重建 Y 矩阵并重置求解初始化，再调用原求解与能量逻辑；没有给舍入添加 epsilon。原四控制器在同设置重跑，用来区分求解设置与算法变化。

## 记录、重放与来源

运行锁保存协议、实现、池及依赖身份；结果及失败回执保留 SHA256。MAPDN 保存每次内部潮流与终态复核；PowerGym 搜索后在全新后端实际前进24步，逐项核对搜索与重放结果。预算耗尽和无有效含电池候选保留为失败，不能通过删记录或加预算恢复成成功。

完整目标轨迹和数据仅存本地忽略目录；公开证据保存指标、参数、来源与结果哈希。重放结果不等于正式候选隔离或严格 n 认证。MIT 源码的版权与许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)；这不替代各上游数据、feeder 和依赖的独立许可核查。
