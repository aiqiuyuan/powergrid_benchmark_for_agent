# MAPDN / PowerGym 真实后端流程校准（2026-10-15）

本轮只验证两个配电网任务的真实运行及原生实验生命周期。每题各一次 `n=0/1`，开发时限均为600秒，不设累计 token cap；不加入原五任务的75-run清单，不据此报告 n 的效果或原论文复现。

| 角色 | 原生 task | 完整 episode | 状态 |
|---|---|---|---|
| MAPDN n=0 | `mapdn-voltage-control-canary-v1` | 480 × 3分钟 | 本地及Linux完整仿真通过；集群提交被SSH阻断 |
| MAPDN n=1 | 同上 | 同上 | 同上 |
| PowerGym n=0 | `powergym-volt-var-control-canary-v1` | 24 × 1小时 | 本地及Linux完整仿真通过；集群提交被SSH阻断 |
| PowerGym n=1 | 同上 | 同上 | 同上 |

`n=0` 使用原生 `terminal`，没有过程 judge；`n=1` 使用 `eval-budget --n 1`。同题两组共享 case、起始策略、资源与评分入口，终评使用截止时唯一的 `controller.py`，并校验其 SHA256；不从历史反馈中挑最佳版本。已受理的候选失败计次并记0分，基础设施失败单独记录。

## 已完成的数值准备

MAPDN 使用锁定上游的真实33节点模型、原始 P/Q 负荷与 PV 数据，冻结最早完整对齐自然日2012-01-02，无额外噪声。每个间隔先更新外生量、求解当前观测、再接收动作并求解评分，独立核对总损耗与全网功率平衡。容量按原始完整 PV CSV 的每列最大值乘1.2确定。下载四个完整 ZIP 成员并核对 CRC32 和成员 SHA256，未声称验证未完整下载的3.7GB压缩包。

PowerGym 使用真实34Bus资产、固定文件顺序打包的 profile0、显式24步负荷；直接调用锁定 OpenDSS 后端，关闭自动设备控制。它是带硬终态能量约束的适配轨，保留并披露整数 kWh 电池更新和 Generator P/Q 语义，不能当作原始 Gym reward 的逐位复现。

以下是 Python3.12.14/macOS 的完整真实潮流校准，**不构成 Linux sandbox 或集群运行证据**：

| 任务 / 控制器 | 校准质量（越高越好） | 电压点×时刻合规率 | 实际有功网损 | 完成步数 |
|---|---:|---:|---:|---:|
| MAPDN zero-Q | 0.8335003 | 92.87% | 1.209444 MWh | 480 |
| MAPDN 稳定低增益 droop starter | 0.87572194 | 97.42% | 1.07623947 MWh | 480 |
| PowerGym hold + battery idle | 0.0136978968 | 21.49% | 3548.8588 kWh | 24 |
| PowerGym 电压滞环 starter | 0.0346429222 | 56.62% | 2750.2122 kWh | 24 |

两题质量映射不同，不能跨任务直接比较数值。MAPDN starter 的所有母线同时合规时间占比为87.08%。PowerGym两种合法基线初末SOC均为1.0，耗尽电池的策略判为无效；并行独立进程与串行重放一致。低合规的 hold 基线来自上游最大 tap 初始化，不以该弱基线作为两组共同 starter。

可信冻结标识：

| 标识 | SHA256 |
|---|---|
| MAPDN case manifest | `9c4a40c3c01a9f5e4a5d93a13ecad711abf09472856d4649cf504af8886b1386` |
| MAPDN starter | `f20d2001116be460e9190e0a7b9e8f3473affd72699c15ce857e95d23c93afff` |
| PowerGym case.json | `3b76c39e38dddb552ae4d53fd06838e5b5caa35cce5309f3ca611fa12cb2791f` |
| PowerGym starter | `2e1770c370a9af7e26cf2301cb6091287e9339528fb347d4a4ced2cd855b0577` |

## 原生运行包与剩余验收

2026-10-15，源码 `f0f3111911ea96d285331b06858cbce888a87b2e` 的 [GitHub Linux 验收](https://github.com/aiqiuyuan/powergrid_benchmark_for_agent/actions/runs/38726605525) 七项全部通过：Python3.11/3.12/3.13 基础检查、既有 RTE 检查、配电任务文件/IPC隔离探针、MAPDN真实480步和PowerGym真实24小时Docker检查。后两项包含候选失败、重放及物理约束；公开artifact只保留布尔验收，不发布完整目标轨迹。运行清单见[机器记录](verification/distribution-linux-20261015.json)。

这证明上述代码在GitHub Linux环境通过验证，尚不证明目标集群内核、模型代理和Harbor反馈计数链路已经通过。本轮两张任务卡继续标记 `release_ready=false`；原生开发环境的直接网络旁路仍需正式认证。

- [MAPDN canary 包](../../task-packages/mapdn-voltage-control-canary-v1/README.md)：真实 Pandapower runner、当前局部 JSON 观测、各 PV 私有进程、因果步序、实际损耗、同一评分入口。
- [PowerGym canary 包](../../task-packages/powergym-volt-var-control-canary-v1/README.md)：真实 OpenDSS runner、设备动作校验、24小时损耗积分、硬末SOC与独立目录。
- 两包分别准备锁定的 Linux amd64/Python312 离线 wheels；镜像构建后须记录真实 image ID / archive SHA256。
- Linux执行必须通过 Landlock文件白名单、独立UID、seccomp网络/共享内存限制和恶意候选探针；本地Mac数值运行明确不具该隔离认证。
- 实际提交前需通过可信Linux镜像验收，再冻结任务源码、精确case、镜像与原生launcher。提交采用create-only intent及持久回执，SSH异常时先对账，禁止盲目重复提交。

当前SSH relay在登录握手阶段超时。四个角色尚无作业回执，不能把本地校准、计划角色或待执行命令记为已提交实验。完整来源许可、强基线、难例与泛化拆分仍属于正式release待验收项。
