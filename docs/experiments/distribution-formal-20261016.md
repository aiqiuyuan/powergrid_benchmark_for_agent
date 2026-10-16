# MAPDN / PowerGym 正式固定案例实验

本轮是独立于原五任务75次实验与600秒canary的新30次扩展。协议、案例和评分在正式开发前冻结；目前完成任务包、本地数值对齐与代码审查，状态为 **awaiting_cluster_acceptance，正式开发已提交0/30**。固定角色、验证范围和准备作业状态见[实验ledger](../../manifests/experiments/distribution-formal-20261016.json)。

冻结协议SHA为 `a2562a41f9c4bf89134b167b8496d2d20c1c1f1d3ed46c8d5855a4ebc5c67a2f`，任务包提交为 `4ff98fe174da3dfb0b0df589bc5cecf2d830ba27`。生成执行矩阵SHA为 `3b2696e9e6260ae5ab705c69b7a0a316a4bd0f019c6c25eed4ce1d08021f7df5`；公开ledger仅列协议层面的30个角色，不发布包含私有生成参数的完整矩阵。最终来源闭包已冻结并复验，SHA为 `0505a78ff4b9eae1c19a72f7b531617cc07987bc774c2c24c3c4e53a37fcb9c8`；63个公开任务包文件与运行副本逐一核对一致。

| 设置 | MAPDN | PowerGym |
|---|---|---|
| 新包 | `mapdn-voltage-control-formal-v1` | `powergym-volt-var-control-formal-v1` |
| 固定案例 | 33节点2012-02-03，480×3分钟 | 123Bus，profile0×2.5，24×1小时 |
| 相同观测的共同starter | 单步松弛局部droop | coordinated_voltage，电池idle |
| 新评分器中的starter质量 | 0.6763512272400023 | 0.057844021683668784 |
| 指标 | 全日电压安全优先，继而实际有功网损 | 电压违规、实际有功网损与操作综合代价 |
| 硬末能量要求 | 无电池 | 每台账面能量差及真实端口净能量均≤1kWh |
| 外层资源 | 8CPU / 16GiB / 0GPU | 6CPU / 12GiB / 0GPU |

每题n=0/1/3/5/10、各3次独立开发，T=43200秒。共享模型`global.openai.gpt-5.6-sol`、客户端2.1.280、Harbor0.20.0；不设累计token cap。重复编号代表独立开发进程，不宣称控制不可配置的provider seed。n是最多受理的过程评分次数，允许未用满；受理后的候选错误计次并返回0分。最终重放开发截止时唯一候选，不从反馈历史择优。具体公式与权限见[冻结协议](../../configs/distribution-formal-20261016.json)、[决定0008](../decisions/0008-distribution-formal-fixed-cases.md)。

本地真实后端核对：MAPDN完整480步/960次潮流、全日电压合规，损耗1.835251037519195MWh；PowerGym9组参照逐小时物理指标与既有资格实验精确一致，另独立重放仅用合法观测的coordinated控制器。current-load优化和全日oracle信息权限更多，单列参照，不作为同信息策略排行。PPO/SAC pilot与本轮不共享开发预算，也不是本轮启动前置条件。

| 本地验证范围 | 已通过 | 能证明什么及其限制 |
|---|---:|---|
| 两个正式任务包 | 18（MAPDN11、PowerGym7） | 单元检查和真实后端数值对齐；不能替代目标集群隔离验收 |
| 新launcher | 31 | 固定矩阵、整组预检顺序、幂等提交、计次、截止快照、代理规则和模型验收失败处理；外部执行使用stub |
| 验收辅助流程 | 7 | 基础镜像归档绑定、持久提交意图、未知状态保留和验收顺序；未据此宣称实际集群通过 |
| 冻结框架核心 | 63（真实本地judge/CLI21、stub续跑包装层42） | 计数、提交快照、并发拒绝、崩溃扣次、重启时钟及账本安全；不是Docker/native Harbor或真实模型验收 |

框架核心测试运行前后29个冻结文件的SHA一致。原始plan测试因未携带原题和site夹具未执行，指定的live-stack测试文件在远端不存在；二者均未计入63项通过数。各组证据摘要SHA见ledger，私有配置、路径、凭据和日志正文不公开。

迁移已核对非GOC目录完整内容校验、独立Relay登录和新集群运行证据。新批次使用迁移后的个人工作区，保留旧源码、canary、资格实验与失败记录；迁移检查不等于本轮任务的验收完成。

正式网络和截止逻辑设计为：开发容器仅挂内部网络，外联经允许模型网关的代理；代理拒绝把任意单标签、整数或hex形式IP当作内部服务放行。可信截止watchdog暂停整个开发容器、核验Docker的Paused状态，再以限时限长tar流导出唯一源码；最终Harbor读取该快照，并核对deadline、artifact和checker三者SHA一致。这些保护已有本地回归，仍须真实Linux/native回执。

准备版v1作业 `aqy-dist-formal-build-v1-20261016-200303` 保留为准备历史；其继承代理存在旁路缺口，不用于正式启动。修改只应用于新v2副本。v2 bootstrap作业 `aqy-dist-formal-build-v2-20261016-200713` 最初排队，2026-10-16 20:16（UTC+8）的日志显示容器尚未启动、状态为 `Unschedulable`；当时作业列表的 `Running` 标签不能解释为容器已运行。

随后v2实际启动，并于20:19:47完成真实runtime验收，v1/v2准备作业均已 `Succeeded`。v2回执确认两题的真实完整案例数值检查和sandbox否定检查通过，回执SHA为 `0cd871de7bb1bb604683e92adf03083d7b1269365912504bfd9083e88b68bb20`；具体数值镜像ID与归档SHA见ledger。此前排队观测作为历史保留，不再作为当前阻塞原因。

短时验收作业 `aqy-dist-formal-accept-v2-20261016-202438` 已确认受理，顺序执行配置构造、受保护网络下的确定性原生四角色生命周期、真实模型网络与截止验收。源码和镜像已冻结登记；其余门槛通过后才能提交30个正式角色。准备作业不计入正式开发次数；真实runtime通过也不代表后续native/model门槛已通过。
