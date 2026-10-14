# 第三步完成说明：统一实验生命周期基础框架

日期：2026-10-15。对应工作：**Consolidate the framework around one reliable experiment lifecycle**。

本次完成了三类模块的合同、独立通用参考实现和本地验收，使后续接入能源任务与Harbor有共同依据。未决定正式研究参数，也未把尚未接入的生产能力标为通过。仓库入口为[README](../README.md)。

## 1. Configuration：哪些值需要定

交付[配置说明](framework/configuration.md)、[49字段目录](../configs/configuration-catalog.json)、[待定模板](../configs/experiment.template.json)及对应校验器。模板的研究与部署字段全部保持`null`，没有用预实验设置或fixture值回填。

覆盖run／cohort／task／版本与摘要、排行与能力范围、搜索backend、模型与单响应限制、开发T、反馈n、构建／反馈／单例／批次时限、三阶段CPU／内存／磁盘／GPU、选择／反馈规则、恢复次数、产物限额、正式重复与配对seed、评测容差及部署认证字段。

先前已决定的协议另列：无累计token cap、无累计token预留、n=0为零受保护反馈、best-public-selection、并列按较早完成、final-test不选候选。字段填实与生产认证分开；draft可审阅，缺值不能静默执行。

## 2. Task adapters：怎么提交、怎么公平排行

读取并落实用户引用的《电网算法演化Benchmark的原赛可比性与公平排行说明》，形成[公平排行路线](framework/fair-ranking.md)、[逐任务Adapter合同](framework/task-adapters.md)、[五个机器声明](../manifests/task-adapters/)及任务卡§10。原任务卡§1–9、原始排行榜／数据说明与历史结果保留。

| Task | 本次选择的路线 | 正式提交要求与当前条件 |
|---|---|---|
| GOC SC-AC-OPF | 公开合成面板的新统一排行；保留历史参照 | 完整Code1／Code2求解器、全部故障、独立原目标；工业全量榜条件不足，强基线同平台重评待认证 |
| UC／SCUC | 原UC求解器排行；派生DC-SCUC独立赛道 | 运行冻结源码生成新排程，独立核约束／成本；已有MILP和validator可复用，静态schedule grader须改执行入口 |
| RTE检修排程 | C+X历史参照优先；新泛化面板单独建设 | 完整JSON、原风险checker、15／90分钟历史节点证据；强基线源码存在，构建／许可／资源／完整重评未认证 |
| L2RPN | 同动作、simulate和资源条件的新统一排行 | 新episode执行控制器、可信simulate通道、锁定scorer；旧公开24周结果权限不一致，不能直接作为公平新榜 |
| HEFTCom | 测试前冻结模型的逐日因果重放新排行，Trading为主 | 执行冻结预测／交易流水线、0–1800 MWh边界、独立结算；需训练截止／数据到达审计、强基线因果重评及独立时期 |

所有提交都要求可执行算法源码包与依赖声明；权重、状态、训练配方按task披露。算法输出由独立checker评分，静态调度、报价或动作轨迹不能代替正式算法。区分最终算法质量与智能体开发性能，历史排名／历史数据重评／新Benchmark排行分别报告。

五份声明均为`design`、`certification_status=pending`、`release_ready=false`，每份列出可复用条件、缺失证据与验收门槛；没有宣称五个真实Adapter已完成或已有正式榜。

## 3. Reliability extensions：已构建的共同保障

新增[powergrid_bench](../src/powergrid_bench/)独立标准库实现，没有复制私有底座代码：

| 模块 | 已实现行为 |
|---|---|
| Configuration／CLI | 待定字段校验、设计声明核对、认证门槛拒绝、可信fixture入口 |
| Artifact Store | 必需文件、路径／链接、文件数／字节限额、逐文件SHA-256、可执行位、内容寻址快照、重验与冻结 |
| Clock／Ledger | 持久唯一开始／截止、恢复不重置、已观察时间不倒退、n=0、原子受理、同键幂等、串行protected作业 |
| Attempts／Delivery | 保存尝试及终态、有限基础设施重试、不重复扣n、旧attempt拒绝、晚到结果可留档而不能投递 |
| Selector／Lifecycle | 截止前公共选择、并列可复查、基线回退、不可变freeze receipt、稳定final作业与同上下文恢复 |
| Algorithm ABI／Process | argv执行、新输入／新工作目录、显式trusted-local、输出有界、超时及普通POSIX子进程清理、外部独立checker |
| Fixture／报告 | 真实执行小算法，贯穿准备、开发、反馈、恢复、冻结、新输入final与审计，保留SQLite和JSON证据 |

详见[架构与底座归属](framework/architecture.md)、[历史失败→保障行为](framework/reliability-layer.md)和[验收矩阵](framework/acceptance.md)。

## 4. 检查、修复与证据

本地最终验证结果在[机器可读摘要](evidence/framework-validation-20261015.json)中保存：46项自动化测试通过，语句覆盖率89%；静态与格式检查通过；发行包构建和安装后CLI／端到端fixture经核对。配置目录与实现一致，五个task声明均未认证，伪造`certified`字段不能绕过当前拒绝门槛。

独立代码审查发现并修复了旧终评worker可能提交到新attempt、重试次数未强制限制、final恢复转态非原子、小数T恢复受浮点差影响、较大权重快照验证上限不一致等问题。还补了截止时间回拨、相对工作目录和fixture数据承诺一致性的检查。回归断言保存在测试中。

补充检查包括Markdown相对路径／锚点、JSON格式、任务卡原有内容保留、私有路径／凭据扫描、构建包内容与Git差异。新增GitHub Actions覆盖Python3.11／3.12／3.13；远端执行状态以Actions页面为准，不由本地报告代替。

## 5. 完成边界与接下来的实装顺序

**已完成：** 三类模块的清晰划分与统一合同、49个配置字段、五任务公平提交／排行选择、通用参考实现、本地无模型闭环、独立审查、README与中文完成记录。

**仍须真实环境认证：** 私有eval-in-loop／Harbor接桥、模型Gateway与实际工具往返、开发容器硬停止、网络／数据隔离、资源配额、远端broker、完整请求／拒绝日志与真实agent投递回执、五任务真实harness／checker／baseline及目标并发。逻辑时钟测试不是宿主硬截止；只读快照不是恶意代码沙箱；delivery记录不证明agent已读取。

G1的本地无模型部分已有证据，G1整体及G2–G4尚未通过。后续先在真实Harbor环境接通一个低成本task，验证共同截止、n=0与正n、真实投递和恢复；再逐任务完成真实数据／强基线／checker parity和资源校准，最后进行跨任务批次认证。正式配置值在这些测量之后另行决定。

## 6. 后续真实题目验收更新

本文第4节的46项／89%为已发布基础版本0.1.0的历史检查，绑定main提交`e04c613`，对应GitHub Actions三种Python版本均已通过。随后根据用户要求继续实现broker、RTE适配与真实实验接桥；新增实现、本地真实题目结果、最终检查和远端阻塞情况见[本轮中文完成说明](completion-step3-live-20261015.md)。本节不把新代码或真实模型运行归入旧检查证据。
