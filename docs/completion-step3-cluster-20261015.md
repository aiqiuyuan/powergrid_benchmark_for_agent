# 第三步实际集群验收完成说明

日期：2026-10-15。目标：**Consolidate the framework around one reliable experiment lifecycle**。

**结论：RTE 的真实模型／Harbor 共同生命周期 canary 已通过 n=0、n=1 两组验收。** 两组都实际调用模型、提交公共 checkpoint、由宿主在共同截止前停止开发、冻结同一已检查算法，并在独立 verifier 中执行新输入和原始 checker。第三步已经取得目标平台主链路的运行证据；完整生产认证、五任务 release 和跨任务批量认证仍未完成。

本次是正式提交到集群的基础设施验收实验，不是正式研究结果或原赛排行榜。公开基础代码固定在 `2ea86ad62240474ce3c0e26911b399549de1341f`；此前的本地证据和失败记录均保留。机器证据见 [集群验收 JSON](evidence/harbor-cluster-acceptance-20261015.json)，历史交付见 [relay 恢复前说明](completion-step3-live-20261015.md)。

## 1. 三类模块目前完成到哪里

| 部分 | 已完成 | 仍需后续决定或认证 |
|---|---|---|
| Configuration | 49 个字段及校验；本次 T/n/模型/资源/重复作为独立验收 profile；实际 T 写入 agent 指令，status 提供唯一 deadline | 正式研究值继续待定，不用本次 180 秒或单次重复填入研究模板 |
| Task adapters | 五任务的算法提交与公平排行合同；RTE 原生算法在真实 Harbor 的公共、保护、最终三个评测入口运行 | 其余任务的原生绑定；完整 RTE C+X、15/90 分钟语义、强基线同平台重评与新泛化面板 |
| Reliability extensions | 同一持久账本与截止；受理/完成/ACK 分离；公共选择、完整包冻结、停止后导出核对；隔离镜像、实际资源和持久状态重开证据 | 开发中整个 Harbor 会话/Pod 中断恢复、真实终评基础设施重试、完整故障矩阵、目标并发和跨节点存储认证 |

三部分通过同一个 Lifecycle/Ledger/ArtifactStore/broker 联结。旧 judge 没有继续维护第二套 n/T。公开基础包仍为 `0.2.0`；本次修复集中在私有部署接桥，GitHub 发布脱敏证据、现状和操作规范。私有上游源码、凭据、实例原文、模型轨迹及内部部署地址未上传。

## 2. 实际实验设置与结果

两组共同设置：开发 T=180 秒、每组重复 1 次、`bedrock/gpt-5.6-sol`，实际响应模型固定核对为 `global.openai.gpt-5.6-sol`。单次响应上限 8192，单请求最多 2 次 provider 尝试；**无累计 token cap、无 token 预留**。

developer 为 2 CPU/4096 MiB、无外部网络；独立反馈和最终评测为 1 CPU/4096 MiB、无网络。每例监督求解时限 10 秒、seed=2020。Harbor 0.20.0；宿主 Python 3.13.15；数值镜像 Python 3.12.15、NumPy 2.2.6、SciPy 1.15.3。developer 使用补齐 procps 的独立派生镜像，公共/保护 evaluator 与 separate final verifier 保留原数值镜像。

四角色为 A07 development、A09 public selection、A08 protected feedback、A12 final test。它们都是历史已暴露的校准实例，不能宣称未见泛化或原赛复现。

| 实际证据 | n=0 | n=1 |
|---|---:|---:|
| 成功真实模型调用 | 5 | 8 |
| 记录 token 总量，包含缓存输入 | 71,614 | 119,583 |
| protected 受理/完成/显式 ACK | 0/0/0 | 1/1/1 |
| 公共 checkpoint 独立检查完成，距开发开始 | 73.398 秒 | 9.787 秒 |
| Docker 实际结束早于共同 deadline | 0.225 秒 | 0.222 秒 |
| 宿主停止原因/退出码 | deadline/137 | deadline/137 |
| 冻结依据 | best public selection | best public selection |
| A12 独立终评约束判定 | AC | AC |
| A12 原始目标，越低越好 | 793.095889937107 | 793.095889937107 |
| 同一 Ledger 的最终状态 | complete | complete |
| 严格 live acceptance | passed | passed |

token 数来自各请求的 provider usage，不能直接当作计费输入或货币成本。ACK 证明客户端明确确认了对应 payload，不证明模型理解了反馈。n=0 本次没有调用 protected 接口；目标平台上的超额拒绝故障演练尚未覆盖。

两个实际 run ID：

- n=0：`rte-live-23d35418179445d4a5c5e699babfefc2`。
- n=1：`rte-live-84a4c9f50e7640799f08347bb4267856`。

真实调度 job/UID 与原始回执保存在私有证据中；公开 JSON 保留调度身份摘要、源文件摘要、开始/截止/结束时间、冻结回执、final job/attempt 及逐项验收结果，可由维护者与原始记录核对。

为优先验证接口，canary 要求模型先发布 starter，再完成允许的反馈与 ACK。**两组最终选中的都是未修改 starter；这次没有证明算法提升或 n=1 优于 n=0。** A09 公共目标均为 1507.2847843137256；原始目标不是原赛积分。模型完成协议后停止继续请求，控制器保留原 T 等待宿主计时器，以实际 Docker FinishedAt 证明停止，而非仅检查应用层拒绝。

## 3. 真实部署发现并修复的四类问题

| 问题 | 本次修复 | 取得的证据 |
|---|---|---|
| 迁移后 runtime 与 Git checkout 分离；数值镜像缺少 ps/pgrep | 私有源 commit 与 frozen manifest 分别核验；单独构建、锁定并装载 developer 镜像，不改评分镜像 | 无模型 runner preflight 与派生镜像构建均在集群成功；固定 procps `2:4.0.2-3`、镜像 ID、归档/构建文件/包版本摘要 |
| 长 CFS 路径导致 `AF_UNIX path too long` | 使用短、私有、唯一 socket 目录；启动前检查完整字节长度、目录类型、权限与挂载路径；禁止覆盖旧 socket | v4 n0 在模型调用前失败；v6 同一 broker/gateway 真实运行通过 |
| 实际 T 未明确告诉 agent，继承题面仍写 12 小时 | 从运行配置渲染准确 T，明确覆盖原题预算；先读 status、发布 starter、完成反馈与 ACK，再考虑优化 | v5 两组真实调用模型但未完成公共 checkpoint/反馈；v6 两组完成必需步骤，原 T 未延长 |
| scheduler 成功被误当成 acceptance 成功 | 严格检查模型、公共选择、预算/ACK、实际停止、冻结与终评；先持久写入失败回执，再以非零状态结束 launcher | v5 两组 scheduler 成功但严格验收 false，未计为通过；新版失败退出行为通过回归测试，尚未在集群另行强制失败演练 |

共实际创建 7 个作业：2 个无模型准备作业、3 个失败的 canary 尝试、2 个最终通过的 canary。失败没有删除、换数据或放宽门槛；最终两组同代码、同模型、同 T、同资源与同面板。v5 已有真实截止和终评证据，但缺少公共选择/反馈，因此不能用终评分数代替通过结论。

## 4. 恢复、隔离与最终检查

在新的独立 Python 进程中重新打开两组真实 CFS 记录，核对了原 started/deadline/duration、不再开放的开发时钟、相同冻结回执与内容摘要、相同 final job/attempt、未增加的反馈计数，以及结束后新提交被拒绝。这是**完成后持久状态恢复检查**，不是开发中整个 Harbor/会话/Pod 被杀后续跑的认证。

实际 runner 的同 Pod、独立进程 SQLite WAL 读写排他与 flock 排他检查通过；未认证跨节点 WAL。Docker 实际挂载、CPU/RAM、network=none、停止状态和未挂载 private controller 都有回执；不能据此宣称已通过完整恶意候选/逃逸测试。

最终私有接桥 23 项测试通过，并经独立审查；真实两组原始证据和公开报告另经独立审查，未留阻塞问题。公开基础代码、测试与研究配置模板未改变，本轮重新运行 84 项测试全部通过；保留先前 88% 覆盖率、构建/安装和三 Python 版本 CI 的证据。文档/JSON/链接/历史任务卡与隐私检查通过，记录见[本轮发布检查](evidence/cluster-publication-validation-20261015.json)。五张任务卡的原有内容保留，研究配置没有自动填值。验收源码、私有 capsule 与原始证据都以 SHA 固定。

## 5. 后续研究基础还需要完成什么

1. **完成 G1 其余故障演练。** 开发中 controller/Harbor/Pod kill、断流、丢回执、磁盘满、实际终评重试、超额接口拒绝；逐项核对原 n/T、attempt、冻结身份和实际进程状态。
2. **推进 G2 逐任务认证。** 将 RTE 从 A4 canary 扩到完整任务合同；其余四任务各自实现真实 adapter、校准基线与资源、冻结数据角色与评分。原赛公平排行条件独立验收。
3. **推进 G3 批次认证。** 目标并发、跨任务完整槽位、故障分类、报告和重放全部通过，再冻结 benchmark release。跨节点使用 SQLite 前另行验证存储条件或采用合适的单写控制服务。
4. **最后进入 G4 正式研究。** 决定配置值、固定版本与重复计划，再做反馈预算、agent 与演化设计的比较。当前不能从一次基础设施 canary 推断研究稳定性或方法优劣。

当前可确认的是：**统一生命周期已经在 RTE 的真实模型/Harbor 主链路运行并通过配对验收；完整可靠性与五任务 benchmark 的后续门槛继续明确保留。**
