# 配电网扩展原生 task 包

另有两套真实后端流程校准包：[MAPDN 33节点](mapdn-voltage-control-canary-v1/README.md)、[PowerGym 34Bus](powergym-volt-var-control-canary-v1/README.md)。两包已完成本地完整日数值校准，Linux隔离及集群 n=0/1 状态见[运行记录](../docs/experiments/distribution-canary-20261015.md)。它们保持 `release_ready=false`，不改变正式75-run清单。

这里新增两套 **`design / certification-pending / release_ready=false`** 原生任务骨架：

| 家族 | 公开 starter | 当前状态 |
|---|---|---|
| [MAPDN](mapdn-voltage-control/README.md) | 局部逆变器 droop，私有控制单元状态 | 完整局部观测、潮流、因果时序与实际损耗 runner 待接入 |
| [PowerGym](powergym-volt-var-control/README.md) | 保持本步 caps/taps，电池 idle | 混合设备/OpenDSS、SOC 分轨与完整计分 runner 待接入 |

**两包均不可直接启动。** `task.toml`、Dockerfile、可信 test 与 oracle 仅有 `.template`，case、资源、私有完整 runner、反馈/计分和实际镜像均未冻结；没有公开完整 `score.py`。将模板改名不等于完成接入或验收，新增家族不改变原五任务的 75-run 实验清单。

在仓库根目录使用 Python 运行以下两条合成接口检查：

```bash
python3 task-packages/mapdn-voltage-control/environment/app/support/check_interface.py
python3 task-packages/powergym-volt-var-control/environment/app/support/check_interface.py
```

这些命令只导入公开 starter 并执行 toy 观测，不安装/调用 Pandapower 或 OpenDSS，不运行目标 case，不产生物理成绩。输出的 `scope` 为 `synthetic-interface-only-no-target-case`；它们不能替代真实环境 smoke 或完整任务验收。

上游源码准备工具只向**可信评测侧**复制和核对版本，不将完整环境、完整 checker 或精确目标轨迹送入开发镜像。开发镜像仅复制 submission、public 与轻量 support。私有 verifier 使用固定可信路径及发布时锁定的 SHA-256；缺失即失败退出，不产生伪 reward，候选不能通过参数或环境变量替换评分器。

发布前仍需：冻结一个完整 case 与合法信息、核查数据/许可、完成真实后端与物理/因果回归、同条件强基线和资源校准、验收目标评分旁路、原生 n=0/n=1 计数/截止/冻结/独立复核。详见[配电控制接入说明](../docs/framework/distribution-control-integration.md)、[原生 task 包约定](../docs/framework/native-task-package.md)和各任务卡。
