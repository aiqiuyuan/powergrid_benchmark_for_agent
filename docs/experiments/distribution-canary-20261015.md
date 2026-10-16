# MAPDN / PowerGym 真实后端流程校准（2026-10-15）

本轮只验证两个配电网任务的真实运行及原生实验生命周期。每题各一次 `n=0/1`，开发时限均为600秒，不设累计 token cap；不加入原五任务的75-run清单，不据此报告 n 的效果或原论文复现。

截至2026-10-16，四组均已完成终评：三组候选有效且原生审计通过，PowerGym n=0候选因末能量违规记0分。流程完成与候选有效性分别记录。

| 角色 | 原生 task | 完整 episode | 当前作业与状态 |
|---|---|---|---|
| MAPDN n=0 | `mapdn-voltage-control-canary-v1` | 480 × 3分钟 | `aqy-dist-v2-mapdn-n0-r1-20261016-145209` 已完成，原生审计通过 |
| MAPDN n=1 | 同上 | 同上 | `aqy-dist-v2-mapdn-n1-r1-20261016-150237` 已完成，原生审计通过 |
| PowerGym n=0 | `powergym-volt-var-control-canary-v1` | 24 × 1小时 | `aqy-dist-v3-powergym-n0-r1-20261016-154559` 终评完成；候选末能量违规，0分，原生审计未通过 |
| PowerGym n=1 | 同上 | 同上 | `aqy-dist-v3-powergym-n1-r1-20261016-154601` 已完成，候选有效，原生审计通过 |

`n=0` 使用原生 `terminal`，没有过程 judge；`n=1` 使用 `eval-budget --n 1`。同题两组共享 case、起始策略、资源与评分入口，终评使用截止时唯一的 `controller.py`，并校验其 SHA256；不从历史反馈中挑最佳版本。已受理的候选失败计次并记0分，基础设施失败单独记录。

本轮目标模型为 `global.openai.gpt-5.6-sol`，四组模型gate均已确认；集群为 `dev`，每组0 GPU。MAPDN分配8 CPU / 16 GiB，PowerGym分配6 CPU / 12 GiB。T=600秒是开发时限，不是反馈n，也不增加累计token cap。四组均已取得最终候选哈希、反馈计数与终评记录；PowerGym n=0的候选无效结果保留，不作为基础设施故障重提。

MAPDN保留v2已完成作业，PowerGym当前使用v3作业，两批提交回执均为returncode=0，各自绑定独立冻结清单。MAPDN两组均完成，`native audit / evaluation_completed / candidate_feasible`均为true，终评候选哈希与检查器记录一致。MAPDN n=0/1最终审计分别记录183/157条assistant记录，PowerGym为64/7条，模型均为目标模型，四组API错误事件均为0；这些记录数不等于独立provider调用次数。

| 已完成角色 | 最终校准质量（越高越好） | 反馈预算 / 已受理 / 已收集 | 最终候选 SHA256 |
|---|---:|---|---|
| MAPDN n=0 | 0.8972437326134053 | 0 / 0 / 0 | `675e2781698507c247e0d24bcdd5277b21d781abde83dcdfa1dfba0068467250` |
| MAPDN n=1 | 0.8915242407486476 | 1 / 1 / 1 | `f27cb5a1b02c8744e498937384b04ef766683285e6d9d4ffbce1cb99c2448481` |
| PowerGym n=0（候选无效） | 0 | 0 / 0 / 0 | `125d0053acf6370205f0c1cfa7db5e02d9228777f24940e5cafba47e5fc1f32b` |
| PowerGym n=1 | 0.1405541996994321 | 1 / 1 / 1 | `73b9578c63e7097c2bd2e96dd959832f5d6c342e9e9469883ae1bbe2b010a1fe` |

| 已完成角色 | 全网同时 / 母线×时刻电压合规率 | 实际有功网损 | 完成间隔数 |
|---|---|---:|---:|
| MAPDN n=0 | 100% / 100% | 1.0566878155027704 MWh | 480 |
| MAPDN n=1 | 100% / 100% | 1.1852134294045533 MWh | 480 |

| PowerGym角色 | 相位×时刻电压合规率 | 实际有功网损 | 末SOC | 末能量偏差 | tap移动 / 电容切换 | 完成步数 |
|---|---:|---:|---|---|---|---:|
| n=0（无效轨迹诊断） | 82.19% | 2850.9477808772126 kWh | [0.9975, 1.0] | [10, 0] kWh | 158 / 0 | 24 |
| n=1 | 95.09% | 2356.9993627724575 kWh | [1.0, 1.0] | [0, 0] kWh | 90 / 0 | 24 |

PowerGym n=0的`evaluation_completed=true`，实际运行全部24步；最终检查器报告`terminal_energy_violation`，第一台电池末能量偏差10 kWh，超过冻结的1 kWh容差，因此`candidate_feasible=false`且reward=0。原生审计保留`passed=false`，entry phase为`failed`，开发阶段还记录600秒截止的`AgentTimeoutError`。该作业保留为已终评的候选失败，不作为基础设施故障重试。n=1的`evaluation_completed / candidate_feasible / native audit`均为true，末能量偏差均为0；两组候选与检查器记录的SHA256分别一致。

这是每档一次的流程校准结果，不能据此判断n的统计效果。MAPDN n=0/1用量文件分别可去重得到57/40条message，PowerGym为22/2条；用量文件覆盖其可取得的trace片段，与最终审计的assistant记录计数分别保留。四组provider token字段均为0，无法确认真实token消耗，不能报告为零消耗；这些message数也不等于独立provider调用次数。

PowerGym两组v2在模型gate前发生容器构建/启动基础设施错误，无gateway、模型trace或最终audit；失败作业保留在下方历史中，不计作候选失败或0分结果，缺少trace也不代表已确认API错误数为0。新版本`distribution-canary-20261016-r3`补齐独立的真实Python开发基础镜像离线归档后，两个v3作业均完成终评；已完成的MAPDN两组未重跑。

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

## Linux与目标集群运行验收

2026-10-15，源码 `f0f3111911ea96d285331b06858cbce888a87b2e` 的 [GitHub Linux 验收](https://github.com/aiqiuyuan/powergrid_benchmark_for_agent/actions/runs/38726605525) 七项全部通过：Python3.11/3.12/3.13 基础检查、既有 RTE 检查、配电任务文件/IPC隔离探针、MAPDN真实480步和PowerGym真实24小时Docker检查。后两项包含候选失败、重放及物理约束；公开artifact只保留布尔验收，不发布完整目标轨迹。运行清单见[机器记录](verification/distribution-linux-20261015.json)。

后续兼容修复源码 `541fea788910a971eaaf371778f79aeda2dca005` 的 [GitHub Linux 验收](https://github.com/aiqiuyuan/powergrid_benchmark_for_agent/actions/runs/38861479324)七项亦全部通过。旧的[2026-10-15机器记录](verification/distribution-linux-20261015.json)保留其当时状态；最新集群证据见[2026-10-16机器记录](verification/distribution-cluster-20261016.json)。

目标集群 bootstrap `aqy-dist-build-r3-20261016-142843` 已在内核 `5.15.0-72-generic` 上完成两套沙箱负例探针、PowerGym secure完整运行检查和两题完整case评分，最终验收为 `passed=true`。该内核使用Landlock ABI1；除独立UID、文件白名单与网络/IPC限制外，seccomp额外禁止截断、`creat`、`O_TRUNC`和`openat2`入口。专属Docker目录清理发现1个ext4子挂载，普通卸载成功，无清理错误。runner Python为3.13.15，仿真镜像为Python3.12；两者分别记录。

| 集群冻结对象 | SHA256 / image ID |
|---|---|
| r3 runtime acceptance | `6dc486d560d47c5e98ddc23fac288a793c5f8e335a375c20ee7cb18fb011745c` |
| runtime manifest | `09128d1ef1a9fe9777b848b9f438e6b3d89e30c07d6535baf74ff21d4950529d` |
| MAPDN runtime archive | `c4f08ec487e8e8dcb4556cb9e5503da2cee6facdccb8626e4cd34ff6be743a3a` |
| MAPDN runtime image | `sha256:e1f30d331691e841a8dd97078a4e18a3e73309c2692130390d3126eb83cd8f69` |
| PowerGym runtime archive | `7f4cb4861f69a068473337e3b54b21d4205c2018bf328bae1654839f22e2aef4` |
| PowerGym runtime image | `sha256:17e3121db9fb100d59e71c15d07b6a68cafed5af1076f5f5e2ea8e396bc0c595` |

这些证据确认目标集群可以运行已冻结的真实后端与候选隔离，不替代模型代理、Harbor反馈计数、截止与终评的完整生命周期验收。本轮两张任务卡继续标记 `release_ready=false`；严格n和正式扩展认证仍待完成。

- [MAPDN canary 包](../../task-packages/mapdn-voltage-control-canary-v1/README.md)：真实 Pandapower runner、当前局部 JSON 观测、各 PV 私有进程、因果步序、实际损耗、同一评分入口。
- [PowerGym canary 包](../../task-packages/powergym-volt-var-control-canary-v1/README.md)：真实 OpenDSS runner、设备动作校验、24小时损耗积分、硬末SOC与独立目录。
- 两包使用锁定的 Linux amd64/Python312 离线 wheels；目标集群已构建并验收真实镜像，归档与image ID见上表。
- Linux执行已通过 Landlock文件白名单、独立UID、seccomp网络/共享内存限制和恶意候选探针；本地Mac数值与Linux安全证据分别保留。
- 提交采用create-only intent及持久回执；冻结任务源码、精确case、镜像与原生launcher，异常时先对账，禁止盲目重复提交。

## 提交历史与版本边界

早期SSH握手阻断已解除。bootstrap r1 `aqy-dist-build-r1-20261016-140938` 因单次启动探针超时失败；r2 `aqy-dist-build-r2-20261016-141736` 因旧内核Landlock兼容门槛失败，并记录清理EBUSY。两次均未发布成功验收，修复后使用新的r3记录，未覆盖失败历史。

首个模型开发尝试 `aqy-dist-mapdn-n0-r1-20261016-143345` 已进入Harbor，但`disallowed_tools`传入list，而Harbor0.20要求字符串，因而在模型调用前失败，模型调用数为0。该作业不计作已完成的n=0实验。原冻结批次与失败回执保留。

新准备版本为 `distribution-canary-20261016-r2`，修正该参数类型并采用 `aqy-dist-v2-` 作业前缀；任务、case、镜像及私有配置与r3验收同源复用，并有验收复用来源记录。新冻结清单SHA256为 `85b45315cbac0ed37c990d82353b91a74cc8d96d2acf8ec8699e141d38c4c7a0`。真实runner构造预检 `aqy-dist-ctor-v2-20261016-144943` 的四组配置均通过，旧list参数负例被拒绝，模型调用数为0；构造预检不构成模型开发或计n链路完成。

PowerGym v2失败作业为 `aqy-dist-v2-powergym-n0-r1-20261016-150238` 与 `aqy-dist-v2-powergym-n1-r1-20261016-150240`。顶层记录`FileNotFoundError`，trial记录`RuntimeError`，失败发生在模型gate前的容器构建/启动阶段，无有效最终审计。

PowerGym新版本 `distribution-canary-20261016-r3` 的源码清单SHA256为 `bcef4727b53076b59a846b67df6a6f70250d49e328e4ae1b8bd14468c34f254e`，不覆盖MAPDN v2来源。基础镜像缓存作业 `aqy-dist-base-v3-r1-20261016-152617` 已通过，单独归档真实 `python:3.12.14-slim-bookworm`，归档SHA256为 `88bbc6a984de1cbaf65290d9d4b6cd26919674d2e15f1653b08c4ce28c7806f5`，image ID为 `sha256:febd0be41adb897a0ab8f1f1c693d8912669ea60c4940e076e9946b60e210ef0`。加载时检查归档哈希、镜像ID、正确Python tag及原验收中的来源digest；原两套数值runtime acceptance哈希保持 `6dc486d560d47c5e98ddc23fac288a793c5f8e335a375c20ee7cb18fb011745c`。

本轮四角色的模型开发、反馈计数、候选冻结与终评流程已完成；原生审计通过的角色为MAPDN n=0、MAPDN n=1和PowerGym n=1，PowerGym n=0候选违规的未通过状态原样保留。完整来源许可、强基线、难例、泛化拆分及正式严格n认证仍待完成，`release_ready=false`；单次流程校准不构成正式发布认证。
