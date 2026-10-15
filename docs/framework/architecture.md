# 第三步：统一实验生命周期与模块边界

**当前个人运行路线（2026-10-15）：** 原生eval-in-loop及既有task优先；本页独立基础实现保留为参考，不要求个人另建运行时或迁移五任务。原框架已有账本、快照、恢复计时和agent续跑；扩展应针对实际缺口。具体边界见[最小测试设计](../decisions/0004-minimal-local-testing.md)，实际RTE集群证据见[完成说明](../completion-step3-cluster-20261015.md)。

初版日期：2026-10-14；实现核对更新：2026-10-15。范围：把配置、Task Adapter 和可靠性保障层整理成统一合同，并提供不依赖私有代码的基础实现与低成本认证夹具。真实能源任务、Harbor／模型服务和集群接入分别验收；本地夹具成功不等于五个能源任务已认证。

## 1. 用户提出的三类划分如何落地

这一划分正确。需要补充的是：**生命周期协调器负责权限和不可变记录；搜索方法只负责如何产生候选；Task Adapter 负责问题语义。** 保障层不能代替题目评分，也不能根据观察到的最终分数追加开发时间。

| 部分 | 应确定的内容 | 本次交付边界 |
|---|---|---|
| Configuration | 参数名称、类型、适用范围、谁决定、何时冻结、缺值时的处理 | 建立待定字段与校验；研究参数保留待定，夹具数值只用于测试 |
| Task adapters | 每个任务的数据角色、算法提交格式、执行入口、独立检查器、原始指标、公平排行协议 | 逐任务合同与就绪状态；真实数据、镜像、基线和评分校准单独认证 |
| Reliability extensions | 共同计时、提交受理、持久账本、重试、候选选择、冻结、终评、审计以及外部服务故障控制 | 可本地验证的通用基础层；模型网关、容器硬截止、集群资源和密封数据访问仍需部署验收 |

参数值尚未决定不妨碍把字段、状态、错误处理和接口搭好。正式运行必须拒绝未填实的配置；不能从预实验旧值、测试夹具或代码默认值自动补齐。

## 2. 现有代码与这次新增代码的关系

现有能源 coding-agent 实验基于 `eval-in-loop`，由 Harbor 管理开发环境、agent 和 trial。下面的归属是本地基础版本核对后的职责归属，不能推断上游后续版本或每一行代码的个人作者。

| 层 | 已有来源 | 应保留或整合的内容 |
|---|---|---|
| 调度与计划 | `eval-in-loop` 的 `exp/` | 配置解析、计划生成、本机／fm-job 启动、环境准备；保留作执行桥 |
| Agent 与 trial | 外部 Harbor、Claude Code；基础库 `PersistentAgent` | Harbor 管环境；agent 管代码搜索；续跑器读取可信记录，不能自定新预算 |
| 运行中反馈 | 基础库 `runtime/judge` 与 `submit/result/status` | 已有提交、快照、串行评测与账本；接桥时统一受理、幂等、终态和投递语义 |
| 能源适配 | 能源 task 和实验目录 | 官方 checker／数值库连接、数据转换、输入输出、基线、task 原始分数 |
| 实验专用保障 | 分散的 gateway、bridge、deadline、checkpoint、broker、freeze／export 脚本 | 抽出共同合同；特定数值执行器留在 adapter，平台凭据与配置留在部署侧 |
| 本仓库新增基础层 | [powergrid_bench](../../src/powergrid_bench/) | 独立的配置／状态／账本／产物／执行合同参考实现；不复制或发布私有底座源码 |

新基础层提供共享语义，不自动接管现有 Harbor 作业。它与私有底座之间的桥需要显式适配和验收。保留 task 各自的 Python、Julia、仿真及 solver 环境，不要求五个任务共用一套数值依赖。

### 2.1 可以直接核对的实现入口

| 公开模块 | 当前接口和行为 | 验证入口 |
|---|---|---|
| [config.py](../../src/powergrid_bench/config.py) | `validate_configuration` 区分 draft、字段填实与可执行配置；不填默认研究值；完整性不是生产任务／backend认证 | [配置测试](../../tests/test_config.py) |
| [artifacts.py](../../src/powergrid_bench/artifacts.py) | `ArtifactStore.snapshot / verify / freeze`；摘要包括文件内容和可执行位，拒绝链接／缺必需文件／越界路径，读取时校验 | [产物测试](../../tests/test_artifacts.py) |
| [clock.py](../../src/powergrid_bench/clock.py) | `RunClock` 持久开始、截止和原始 duration；拒绝无效时间，恢复不根据浮点时间差重建 T | [生命周期测试](../../tests/test_lifecycle.py)、[账本测试](../../tests/test_ledger.py) |
| [ledger.py](../../src/powergrid_bench/ledger.py) | `Ledger` 用 SQLite 事务保存 run、job、attempt、selection 和 delivery；同键幂等、串行、有限 retry、稳定终态；持久 `last_seen_at` 防止已观测截止后倒退 | [账本测试](../../tests/test_ledger.py) |
| [lifecycle.py](../../src/powergrid_bench/lifecycle.py) | `Lifecycle.prepare / start / submit / record_selection / freeze / final_start / final_retry / final_finish`；恢复、公共选择、基线回退、固定 final身份、拒绝旧attempt的晚到终态 | [生命周期测试](../../tests/test_lifecycle.py) |
| [process.py](../../src/powergrid_bench/process.py) | `run_process` 用 argv、不启动 shell；有界输出与超时；POSIX进程组清理，仅用于可信本地夹具 | [进程测试](../../tests/test_process.py) |
| [adapters.py](../../src/powergrid_bench/adapters.py) | `validate_candidate / execute_algorithm`；`candidate.json` 绑定 task和源码，要求输入／输出占位，新工作目录执行，独立 checker拒绝自评分；执行须显式 `trusted_local=True` | [Adapter测试](../../tests/test_adapters.py) |
| [broker.py](../../src/powergrid_bench/broker.py) | 有界 Unix socket、安全算法包、task 校验钩子、保护反馈幂等／聚合白名单、显式 ACK、控制器恢复和冻结前对账 | [Broker 测试](../../tests/test_broker.py) |
| [rte.py](../../src/powergrid_bench/rte.py) | 严格声明的原生 solver、新输入执行、完整冻结包、固定外部原始 checker、独立约束与风险目标；可信本地原型 | [RTE 测试](../../tests/test_rte.py)、[真实题目验收](rte-integration-acceptance.md) |

`Lifecycle.prepare` 接收调用方已完成 preflight 的上下文与基线，它本身不证明外部资源已经准备，也不从 task卡自动生成证书。核心持久状态是 `planned → prepared → developing → freezing → frozen → final-evaluating → complete/failed`；八阶段图是职责流程，不能把这些状态误当生产部署全部已实现。

本地账本记录的 delivery 是可信调用方提交的交付凭据。新增 broker 使用实际 Unix socket 和客户端 ACK，可证明客户端确认相同结果；它仍不能证明真实模型已读取。所有请求／拒绝的完整日志、实际 token／资源、整批计划槽位和可信 task／backend证据由 CLI／部署桥补齐；接口校验与生产准入须各有证据。

## 3. 一个 run 的八个阶段

```mermaid
flowchart LR
    A[1 声明配置与协议] --> B[2 启动前校验]
    B --> C[3 准备共同环境]
    C --> D[4 开发与公共选择]
    D --> E[5 受控反馈]
    E -->|同一 T 与 n 内| D
    D --> F[6 截止与冻结]
    E -->|晚到结果只留档| F
    F --> G[7 执行最终测试]
    G --> H[8 审计归档与重放]
```

| 阶段 | 输入与操作 | 必须产生的记录 | 离开此阶段的条件 |
|---|---|---|---|
| 1 声明 | task／split／protocol／方法版本、模型、资源、T、n、重复与选择政策 | 不可变运行配置摘要、run／cohort／slot 关系 | 正式配置字段填实，夹具显式标为非研究用途 |
| 2 校验 | 核对任务合同、必需文件、依赖声明、摘要和认证状态 | preflight 报告及准入／拒绝原因 | 缺包、坏摘要、未认证任务不能被默认为可正式运行 |
| 3 准备 | 部署桥拉取镜像、挂载合法开发材料、检查资源 | 环境与资源实际供给证据、准备完成记录 | 共同环境完成后协调器一次性设定开始和截止；此前不能搜索 |
| 4 开发 | 搜索 backend 编辑／训练／调试，执行公共 selection | 候选快照与公共选择记录，绑定产物和运行版本 | 选择计算必须在 T 内；结果不能来自 final-test |
| 5 反馈 | 先验证快照，再原子受理／扣次，执行并投递 | request、accepted、attempt、terminal、delivery | n=0 拒绝；重发不重复扣次；每次投递再次检查截止 |
| 6 冻结 | 停止开发计算，依预声明公共选择记录选定产物 | freeze receipt、选中摘要、选择依据、停止证据 | 候选字节固定；外部桥必须证明开发进程已停止 |
| 7 终评 | 在新隔离工作目录执行冻结算法，独立检查其输出 | 原始指标、有效性、输出摘要、评测上下文和终态 | 全面板完成或明确失败；候选自报分不能取代 checker |
| 8 审计 | 对账槽位、预算、时钟、产物、失败；按固定上下文重放 | 运行／批次报告、缺失项、replay 记录 | 不用较好重放分替换第一次有效终评，不静默删除失败 |

反馈是开发期的子循环，不是另一次开发 run。截止后允许判分作业完成并保存结果，但不能继续将该结果提供给开发智能体或恢复其写权限。

## 4. 模块接口与权限

| 模块 | 负责什么 | 不应掌握或决定什么 |
|---|---|---|
| Config / Preflight | 校验版本、待定项、任务证据与运行参数；给出准入报告 | 不替研究者选择 T、n、正式重复数或补造校准证据 |
| Run Coordinator / Clock | 记录唯一 run 上下文、共同开始／截止和阶段；恢复原记录 | 不因重启给额外时间；不根据高分调整配置 |
| Search Backend | coding agent、传统训练、ES 或未来人口演化如何产生候选 | 不直接读取密封面板；不绕过账本扣次／冻结 |
| Evaluation Ledger | 请求、受理与计数、执行尝试、终态及送达对账 | 不解释电网物理；不把基础设施故障当合法零分 |
| Artifact Store / Selector | 快照内容校验、公共选择证据、确定并冻结候选 | 不根据终评或晚到 protected 反馈选择候选 |
| Task Adapter | 真实输入→冻结算法→实际输出→独立 checker；保留 raw 指标 | 不变更共同 T／n；不自行宣称已进入历史原赛榜单 |
| Execution / Model Bridge | Harbor、模型协议、容器资源、进程停止、远端 broker | 不把调度器 Running 等同算法已运行；不隐藏重试与资源不足 |
| Audit / Reporting | 对账状态、记录缺失、合法零分、方法重复与任务族指标 | 不直接平均成本／GBP／控制分数，不挑最好重放 |

Task Adapter 是问题执行接口，Search Backend 是研究变量接口。人口演化可在未来接入同一生命周期；当前接口不把另一个 Famou 引擎的能力算作已接入功能。

## 5. Harbor 接桥必须消除的差异

1. **n 的零值：**基础 judge 内部 `EVAL_BUDGET=0` 表示 unlimited；原框架的 `terminal` 模式已提供不挂judge／反馈工具的零保护反馈路径。研究合同的`n=0`应正确映射到该模式，正n使用相应in-loop预算；这一差异本身不要求另建账本。
2. **共同计时：**Harbor 超时、agent 续跑、host watchdog、judge 和训练进程都读取相同截止。Harbor 的总 trial 耗时不能代替共同准备完成后的开发 T。
3. **结果可见性：**旧 collected／查询时间不能自动称为成功送达，更不能称为模型已理解。桥在开发截止前把持久结果写入 agent 可见通道后才记录 delivery；无读取确认能力时 acknowledgment 为 unknown。
4. **快照与终评：**Harbor 收尾必须转移选定的冻结快照，不能重新从可变工作目录复制另一份程序。GOC broker 的结果收据同样绑定冻结摘要与上下文。
5. **算法执行：**UC 的 schedule 和 HEFT 的 bids 是输出，正式提交还要有可执行求解器／流水线。桥不能把旧静态 grader 的成功升级为算法重放认证。
6. **退出与停止：**应用冻结和调用超时检查不等于杀停整个开发容器。平台桥需证明剩余子进程、训练和写入已经停止；断电／强制 kill 后从同一账本恢复。

接桥应先在无模型夹具完成上述检查，再做一次真实模型工具往返，最后迁移低成本能源任务。不会因为接入 Harbor 就重新获得 T 或 n。

## 6. 本次完成与后续认证的边界

本次交付对应 G1 的通用基础部分和本地无模型夹具。正式参数、真实 task release 和平台部署仍按原[实施门槛](../implementation-plan.md)推进。详细历史故障对应见[可靠性层](reliability-layer.md)，可证实的验收层级与尚未运行的项目见[验收说明](acceptance.md)。

真实数据与镜像没有冻结时，不能把设计 JSON 当正式配置；仅有任务卡时不能颁发 task certificate；仅有本地执行证据时不能声称集群硬截止、模型网关和五任务公平排行已经可用。
