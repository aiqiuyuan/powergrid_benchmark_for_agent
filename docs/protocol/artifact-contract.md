# 算法产物与记录契约

**状态：v0.1-design。** 本文件声明正式版本应采用的产物与记录语义，不表示相关接口或 schema 已实现。配合[评测协议](evaluation-protocol.md)与[研究契约](../benchmark-spec.md)使用。

## 1. 交付单位是可执行算法

Benchmark 的研究对象是算法演化。正式评测输入是一份冻结的算法产物，输出是该算法对新实例产生的解、预测或动作序列。开发阶段产生的结果文件可作为证据保存，不能代替算法产物。

| 任务族 | 必需产物 | 最终执行与独立检查 |
|---|---|---|
| [GOC](../task-cards/goc-sc-ac-opf.md) | 求解器代码、配置、已声明依赖和入口点 | 提供新电网实例与场景，执行求解，独立计算约束与官方目标 |
| [UC/SCUC](../task-cards/unit-commitment.md) | 求解器代码、模型构建配置、依赖锁定文件 | 提供新机组/时段/网络输入，执行求解，独立检查调度与成本 |
| [RTE](../task-cards/rte-maintenance.md) | 维护排程算法、配置和入口点 | 提供新维护实例，独立检查资源、起始时间、排斥与风险目标 |
| [L2RPN](../task-cards/l2rpn-grid-control.md) | 控制器代码、动作编码、已训练权重（若有）、推理配置 | 在新 chronics 中逐步执行，遵守动作与 simulate 配额，独立汇总 episode 分数 |
| [HEFTCom](../task-cards/heftcom-forecast-trade.md) | 特征/预测/交易代码、已训练权重、训练 recipe 与推理配置 | 在固定信息时序下预测与出价，评测器用私有真值进行历史回测 |

UC/SCUC 现有静态 schedule 验证与 HEFTCom 现有静态 `bids.csv` 评分保留为 calibration 与 checker 验证。新的通用求解器入口、HEFTCom 特征/预测/交易流水线执行入口尚需实现并验收，不能把旧输出格式直接视作已满足正式算法契约。

## 2. 产物清单

正式 artifact 必须有一个唯一、冻结的清单。以下为逻辑字段，不指定现有实现必须立即采用某种文件格式。

| 字段 | 要求 |
|---|---|
| `artifact_id` / `artifact_sha256` | 稳定内容标识与完整 SHA-256；不得只用文件大小判断候选不同 |
| `task_id` / `task_version` / `protocol_id` | 明确兼容的任务发布与协议 |
| `entrypoint` | 在任务统一约定下可执行的入口；不可引用开发机器绝对路径 |
| `source_files` | 相对路径、类型、字节数、逐文件 SHA-256；声明禁止包含的内容 |
| `dependency_lock` | 固定的依赖、版本、来源摘要与许可证/归属记录 |
| `runtime_image_digest` | 执行镜像的不可变摘要；tag 仅作为展示名称 |
| `configuration` | 求解/训练/推理参数，线程、数值精度与资源假设 |
| `weights` | 所有实际使用权重的摘要、来源和训练配置；没有权重时明确为空 |
| `training_recipe` | 数据角色、训练代码、seed、超参数与训练日志索引；没有训练时声明不适用 |
| `state_initialization` | 每实例/episode 的状态初始化与允许的无标签适应规则 |
| `output_contract` | 文件或数据结构、单位、索引、时间顺序、可行性字段 |
| `build_policy` | 允许的构建步骤、缓存策略、构建时限与资源；不能在构建时搜索或读取 final-test |

主线已训练权重只使用 `public-development` 拟合；selection 标签用于选择。若独立协议允许在开发时限内用 selection 数据重新拟合，必须记录该权限、形成新的权重与 artifact 摘要、在 `T` 内完成新产物的 selection 评测，并让 freeze receipt 关联新证据。不能把旧模型的 selection 记录沿用到重新训练后的权重；受保护或最终标签始终禁止用于拟合。

不得包含密钥、私有端点、机器路径、内部集群配置、受保护样本、标签、judge 账本或其他算法的结果。外部预训练权重、公开库和商用 solver 的访问政策由 task release 明示；不能让各算法自行选择未披露的额外资源。

## 3. 快照、摘要与幂等性

每次受理 protected-feedback 前，客户端先生成并持久保存稳定的 `submission_id`，作为 run 内的 idempotency key，再发起网络请求。评测端验证完整提交契约、保存不可变候选快照，受理时原子化写入 `submission_id → evaluation_job_id` 映射、acceptance receipt 和计数。快照不可留存时，正式协议拒绝受理且不扣次数；不能仅保存一个“快照失败”标志就继续产生无法重放的正式成绩。

应分别记录：

- `upload_sha256`：传输归档的完整字节摘要，用于验证上传与留档一致。
- `artifact_sha256`：按固定顺序对相对路径、文件内容摘要和影响执行的清单计算的内容摘要；不受归档时间戳、压缩参数和目录遍历顺序影响。
- `source_tree_sha256`：仅代码内容的摘要，用于区分代码和权重/配置变化。
- `environment_digest`、`evaluator_digest`、`split_digest`：影响执行与评分的外部固定状态。

不同 `artifact_sha256` 只表示内容变化，不自动表示算法实质变化。相同摘要的新主动提交仍计一次反馈。只有网络重发或基础设施恢复使用同一 idempotency key，才返回原受理记录而不新增计数。

客户端不需要在首次提交前知道服务端 `evaluation_job_id`。服务端以 `run_id + submission_id` 查询映射，并将其绑定到 `artifact_sha256 + evaluator_digest + split_id + evaluation_seed + resource_profile` 的固定请求指纹。即使受理后的网络响应或 receipt 丢失，同键重发也返回已映射的原作业，不重复扣次；同键不同快照或请求指纹拒绝。主动再次评测相同 artifact 使用新的 submission key，仍占一次配额。基础设施重试使用新的 `attempt_id`，保持原 `evaluation_job_id` 和反馈计数。

## 4. 运行与反馈记录

### 4.1 run manifest

运行开始前冻结的 manifest 至少包含：

- `run_id`、`cohort_id`、任务发布、split、协议和代码版本。
- 算法/agent 配置、model 标识与可获得的版本、单次输出限制、seed。
- `T`、`n`、开发/反馈/最终资源 profile、所有超时、selection 与反馈 schema。
- 初始基线 artifact 摘要、允许的数据与工具、持久化/记忆/人口策略。
- 准备完成证据、统一 `development_start_at` 与截止时间、无累计 token 上限的声明。
- 恢复政策与计划重复数；若重跑，关联原 run 并说明恢复 cohort。

配置不能因看到结果而改写。历史 manifest 保持原样；修复使用新版本与新运行标识。

### 4.2 每个受保护作业

| 字段组 | 最少记录 |
|---|---|
| 身份 | `run_id`、客户端 `submission_id`、服务端稳定 `evaluation_job_id`、提交序号、幂等键摘要、请求指纹、artifact 摘要 |
| 受理 | 请求时间、受理时间、拒绝原因（若有）、`counted`、占用后的配额 |
| 执行 | evaluator/split/资源/seed、每个 `attempt_id`、开始结束时间、退出原因 |
| 结果 | 状态、有效性、原始指标/方向、reward 映射版本、逐实例诊断、故障分类 |
| 投递 | 允许的反馈原文摘要、截断规则、投递时间/通道、投递 receipt、未投递原因 |
| 归档 | 不可变快照位置、完整评测输出与资源统计的内容摘要 |

`done`、`failed` 等实现状态必须能映射到评测协议的终态与失败类型。worker 完成与账本终态更新应可对账；不能长期把已经结束的作业留作 `running` 后作为正式记录发布。

### 4.3 feedback receipt

成功 receipt 表示评测器已将某作业的反馈写入开发智能体可见的工具通道，且发生在开发截止前。receipt 必须关联作业、候选摘要、payload 摘要和投递时间。读取确认是另一个可选字段；缺失时填 unknown。

开发截止后，评测器保存完整结果供审计，但不能向 agent 通道投递。run 汇总分别报告 counted、completed、delivered 和 read-acknowledged，禁止用一个 `feedback_collected=true/false` 概括多次调用的不同状态。

## 5. freeze receipt 与最终评测记录

freeze receipt 在 final-test 开放前产生，至少包含：

- 冻结时间、统一开发截止时间和冻结原因。
- 最终 artifact 摘要、清单摘要、环境与依赖摘要。
- selection 政策、选中候选及其已完成 selection 证据；无候选时的基线回退原因。
- 已用反馈计数、截止前实际投递数、未完成作业及隔离原因。
- agent/算法开发过程的记录索引与版本。

冻结后原目录转为只读或复制到隔离存储；后续开发目录变化不影响待测 artifact。不能一边跑最终测试，一边改动代码或权重。

最终评测记录绑定 freeze receipt，保存：输入角色和面板承诺摘要、各实例执行与独立验证结果、原始目标/官方分数、可行性、资源用量、退出原因、随机 seed、数值容差与聚合规则。完整密封输入可以留在评测端，公开结果不泄漏仍在使用的保护信息。

默认每个实例在新工作目录与新进程中运行；控制 episode 重置状态。若任务允许跨实例共享固定预处理，应在 release 中列出内容及统一成本规则，不能共享前一个实例的标签或评测结果。训练只能使用声明允许的数据，最终阶段禁止从私有标签训练。

## 6. 算法与 checker 的接口边界

任务包需给出输入 schema、输出 schema、构建契约和最小可运行基线。benchmark 可以统一生命周期与记录，但不必把所有算法强行改成同一个 Python 函数。

正式接口至少确保：

1. 新实例输入从评测器传给候选；候选只获得求解或预测所需的信息。
2. 候选产生输出；checker 在独立环境里验证内容并重算指标。
3. 候选不能修改 checker、参考结果、评分权重、seed 列表或 final-test 清单。
4. 评测控制器提供固定资源、时限与状态初始化；候选超出声明限制按任务规则处理。
5. 模型 provider 接入与开发层接口留在 agent 框架中，任务求解代码不能把受保护输入发送给外部服务，除非另设明确授权的研究协议。

评分代码可以公开，受保护数据与 judge 私有状态不可直接读取。公开优化目标和公开可行性 checker 属于合法开发工具；保护边界由实际隔离与数据可见性建立，不能只依赖 agent 侧包装命令。

## 7. 重放与版本演进

一次可重放评测的最小闭包是：`artifact + environment + evaluator + split + seed + resource profile + timeout policy`。缺少其中任何项，记录标记为 incomplete，不能声称已实现完整重放。

发生数值偏差时，按预先冻结的任务容差核对目标和约束；随机控制/训练任务按预注册 seed 列表核对分布。重放结果用于验证，不能用其更高分替换第一次有效最终成绩。

以下变化必须产生新版本：任务数据、切分、评分、硬约束/软惩罚、数值容差、资源与时限、输出接口、selection 政策、反馈内容或预算语义。文档修正可以保留兼容版本，但需说明是否影响已有实验解释。

仓库中的示例 manifest 和设计文档不得被命名成已经通过验收的 release。只有补齐真实数据清单、不可变摘要、资源校准和契约测试结果后，才可以冻结并发布 Benchmark v1。
