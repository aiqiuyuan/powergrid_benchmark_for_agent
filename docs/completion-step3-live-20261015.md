# 第三步追加完成说明：真实题目集成与正式实验验收进度

> **历史快照提示（2026-10-15 更新）：本文保留 relay 恢复前的交付状态。** 下文“远端尚未提交／连接阻塞”描述的是当时情况，不代表当前进度。随后 RTE 真实模型／Harbor n=0、n=1 canary 已通过，详见[实际集群完成说明](completion-step3-cluster-20261015.md)与[机器证据](evidence/harbor-cluster-acceptance-20261015.json)。两组均选择未修改 starter；完成后记录重开已检查，开发中完整会话／Pod 恢复、跨节点 WAL、完整五任务及 benchmark 生产认证仍未完成。本文历史正文不作回写。

日期：2026-10-15。对应目标：**Consolidate the framework around one reliable experiment lifecycle**。

本轮将三类模块的合同进一步落实到公开基础框架、真实 RTE 算法适配和私有 Harbor 接桥。真实 RTE 的本地 n=0/n=1 生命周期已经跑通；**实际远端 Harbor／模型实验尚未提交，因此第三步的生产验收尚未完成。** 四个已配置远端通道均在 relay／SSH 连接阶段失败，本机没有 Docker 或集群执行环境。本文区分已经取得的证据与仍需执行的检查。

入口：[README](../README.md)；前一版交付：[基础框架完成说明](completion-step3-20261015.md)。

## 1. 三类模块如何落地

| 类别 | 已完成的工作 | 当前保留的决定或门槛 |
|---|---|---|
| Configuration | 49 个字段、类型与校验；draft／可执行配置区分；版本、摘要、时限、预算、资源、模型、重复和恢复字段完整列出 | 正式研究数值仍为 null。本轮验收参数独立记录，不成为研究默认值 |
| Task adapters | 五任务的算法提交、独立 checker、公平排行路线、四类数据和缺失条件；新增可执行 RTE 原生适配 | RTE 本地原型通过不提升其他任务资格；完整 C+X、强基线同平台重评和新泛化面板未认证 |
| Reliability extensions | 共同绝对截止、持久账本、同键受理、保护反馈配额、完整快照、公共选择、冻结、同上下文重试、显式客户端 ACK 与恢复 | 容器硬停止、真实模型网关、实际资源／隔离、远端部署与批次并发需要目标平台证据 |

Configuration 是对已有能力的选择；Task Adapter 定义题目如何执行和评分；Reliability extensions 负责共同生命周期中的失败与恢复。生产部署必须调用同一个账本和截止，不能让旧 judge 继续维护第二套 n/T。

## 2. 本轮新增实现

| 文件或模块 | 具体行为 |
|---|---|
| [broker.py](../src/powergrid_bench/broker.py) | 有界 Unix socket、安全 tar.gz 算法提交、task 受理前校验、串行评测、受理幂等、保护反馈聚合白名单、显式 ACK、控制器恢复与冻结前对账 |
| [rte.py](../src/powergrid_bench/rte.py) | 声明与执行一致的原生 solver ABI；完整冻结包、新输入／新目录、显式时限和种子、原始 checker 与来源锁校验、独立约束和目标评分 |
| [ledger.py](../src/powergrid_bench/ledger.py)、[lifecycle.py](../src/powergrid_bench/lifecycle.py) | 对已持久保存的公共选择证据进行控制器恢复；保留原完成时间，允许截止后恢复有效旧证据，拒绝新的迟到证据和冻结后改动 |
| 私有 Harbor 接桥 | 新 agent/controller、host-only 模型网关、离线 socket bridge、宿主截止监督、冻结导出 SHA 核对、同一 final job／attempt 收集、部署准备与执行门槛 |
| 文档与结构化状态 | [RTE 真实题目说明](framework/rte-integration-acceptance.md)、[Harbor 验收要求](framework/harbor-live-acceptance.md)、README、CHANGELOG、基础框架和 RTE 原型状态 |

公开基础包为独立编写的标准库实现。私有部署包保留在本地工作目录，复用已有 eval-in-loop／Harbor 接口；私有源码、凭据、机器配置和原始能源数据没有上传到公共 GitHub 仓库。

## 3. 真实 RTE 的本地闭环

本轮验收使用真实原始实例和来源锁固定的独立 checker。数据角色互不重叠：A07 development、A09 public selection、A08 protected feedback、A12 final test。四个实例都曾在预实验中暴露，因此只能验证运行行为，不能作为未见泛化测试或原赛榜单复现。

显式本地验收参数：每组开发墙钟 T=12 秒，反馈预算分别 n=0／n=1，每例求解监督时限 10 秒，种子 2020，单线程原生基线。环境为 Python 3.12.14、NumPy 2.2.6、SciPy 1.15.3；模型调用为 0，没有累计 token cap。

| 检查 | n=0 | n=1 |
|---|---|---|
| 开发前基线独立可行性检查 | 真实 A07 通过 | 真实 A07 通过 |
| protected 受理／完成／确认送达 | 0／0／0 | 1／1／1 |
| 同 key 重发 | 不开放 protected 调用 | 同一 job，不重复执行、不重复扣次 |
| 重启与丢失反馈确认 | 原开始、截止、预算不变 | 原 payload 和 ACK token 恢复，查询不自动计送达 |
| 真实墙钟到期 | 新公共提交被拒绝 | 新公共提交、保护结果查询被拒绝 |
| 冻结依据 | 预先验证的 baseline fallback | 截止前独立 A09 公共选择候选 |
| 独立最终测试 | 冻结算法重新执行 A12 | 冻结算法重新执行 A12 |
| final 基础设施恢复 | 同一 job、第二 attempt、拒绝旧 attempt | 同一 job、第二 attempt、拒绝旧 attempt |

final 的第一次基础设施失败是明确注入的控制器故障，用于验证恢复，不是实际发生的集群事故。第二次 attempt 真正执行冻结算法并由原始 checker 评分。该过程不增加 protected 计数。

| 面板 | 实例 | 独立 checker 原始目标，越低越好 |
|---|---|---:|
| 公共选择 | A09 | 1507.2847843137256 |
| 受保护反馈 | A08 | 744.510294117647 |
| 最终测试，两组均可行 | A12 | 793.095889937107 |

原始目标值是校准结果，不能换算为历史竞赛名次。这次并未研究算法提升；两组使用同一可信基线，n=1 提交包具有独立快照标识，用来核对公共候选选择与最终产物身份。

机器证据：[真实 RTE 生命周期验收记录](evidence/rte-lifecycle-acceptance-20261015.json)。记录实际输入、完整算法／冻结回执、checker／来源锁和测试源码摘要，不包含候选私有日志或内部路径。

## 4. 审查中发现并修复的问题

1. **声明入口与实际执行不一致。** 原生适配现在强制 native solver ABI，受理前检查；控制器注入固定 seed 和时限。
2. **公共选择完成后、注册前崩溃。** 先持久保存结果和原完成时间；截止后的控制器恢复可补入真实旧证据。冻结前对账，未解决的执行异常不能默默变成 baseline fallback。
3. **回调异常提前释放执行租约。** 超时、保存结果失败及其他异常都必须等待真实回调结束；否则禁止启动新评测或恢复。
4. **保护反馈可能携带候选输出。** 开发端只收到固定可信聚合字段，stdout／stderr／排程及逐例路径留在控制器审计。
5. **私有接桥可能遗漏依赖文件。** 本次 Harbor canary 明确限定单个 solver 与固定元数据；额外辅助模块或权重受理前拒绝。公开 RTE 适配支持完整包，本次 canary 不认证通用多文件 Harbor 导出。
6. **模型网关恢复可能清空用量历史或重试确定性错误。** 恢复保留此前请求／usage，使用账本时间高水位；确定性 HTTP 4xx 不重试，有界重试分别留档。

新增回归检查与独立审查覆盖这些问题。Docker 清理、宿主停止时间和网关实际运行的证据仍要在真实部署取得，不能由本地 stub 测试替代。

## 5. 最终检查

公开包 84 项自动化测试全部通过，语句覆盖率 88%；格式与静态检查通过，源码包和 wheel 构建通过。安装后的 84 项测试、CLI 和独立端到端夹具也通过。详细证据见[本轮软件检查记录](evidence/framework-integration-validation-20261015.json)。先前 46 项测试／89% 覆盖率的基础版本是独立历史证据，不用于认证本轮新代码。

此外检查 Markdown 链接与锚点、JSON、版本一致、原任务卡历史内容保留、私有路径／凭据、Git 差异和发行包内容。GitHub Actions 继续在 Python 3.11／3.12／3.13 上核对公开包；最新远端状态以仓库 Actions 为准。

## 6. 实际正式实验仍待完成的部分

用户已经授权提交实际验收实验；阻塞是执行环境连接，无需再次申请提交授权。当前四个既有 SSH／relay 通道不能进入远端 shell，本机没有 Docker／Harbor／集群执行环境，因此没有新的远端 job ID、真实模型调用、Docker FinishedAt 或 live-acceptance 回执。

连接恢复后，按新的固定代码包创建独立 n=0/n=1 作业，先核对迁移后的运行时、离线 developer 依赖、镜像／client 摘要和四类输入。然后完成真实模型工具往返、保护 ACK、宿主硬停止、选中产物导出一致性、独立最终测试与进程级故障恢复。只有新的真实回执全部满足[Harbor 成功条件](framework/harbor-live-acceptance.md)，才宣布 G1 真实链路通过。

**当前结论：三类模块的整理与基础实现、真实 RTE 本地集成和 GitHub 文档已完成；第三步的实际 Harbor／模型验收仍受连接阻塞。** 五任务 release、强基线公平重评和批量研究准入继续保持 pending，不自动继承本次本地通过状态。
