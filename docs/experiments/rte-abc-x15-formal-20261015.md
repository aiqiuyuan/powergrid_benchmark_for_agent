# RTE ABC／X15正式批次：启动配置与验收记录

创建日期：2026-10-15；更新日期：2026-10-16。以下时间均为Asia/Shanghai。本批仅运行RTE，其余四个task不在本批范围内。

**15个正式run已提交，正式完成数为0。** 2026-10-16 16:10:10—17完成启动门禁落盘与15个Job创建；16:13:29的Kubernetes快照为6个Running、9个Pending，6个运行Pod位于不同节点并进入`harbor_running`，实际Pod资源均为21 CPU／296GiB，未见错误。另于16:19:00从已回收的Claude记录片段确认这6组均有预期模型响应及工具调用。`release_ready=true`仅代表RTE本批启动门禁通过，不表示开发、最终评分或研究结果已经完成。v6真实n0／n1微型验收均已完成并通过，v5完整X15资源凭据按已核对的来源关系供v6复用。

## 1. 正式角色与研究协议

| 参数 | 设置 |
|---|---|
| task | `rte-maintenance-abc-x15-v1` |
| 正式矩阵 | n=0、1、3、5、10，每档3次独立开发，共15个逻辑角色 |
| 开发时间 | 每个run 43200秒；不等于整个Pod仅运行12小时 |
| token | 不设累计token／美元预算、轮数或输出token覆盖；服务自身单次限制仍适用 |
| 开发数据 | 原始ABC45、官方checker与本地评分开放；占开发时间和资源，不计n |
| 受保护反馈 | 完整X15一次受理计一次；每例900秒，15进程并行，只回传约定汇总 |
| 截止产物 | 最后工作区中的`solver.py`；未修改则保留共同starter，不根据终验选优 |
| 截止后评分 | 原生900秒终验不回流；同一源码摘要冻结后另做5400秒／例X15评分，不计n、不回流 |
| 随机种子 | task seed=2020；三次重复为独立开发会话 |

15个正式角色及其状态见下表与[机器记录](../evidence/rte-formal-launch-20261015.json)。提交时刻均为2026-10-16 Asia/Shanghai，状态取16:13:29观察快照，不能据此推断后续状态。

| Formal role | Actual Job ID | Submitted at (Asia/Shanghai) | Snapshot status |
|---|---|---|---|
| n0-r1 | `aqy-rtex15-n0-r1-20261016-161010` | 16:10:11.099 | Running / `harbor_running` |
| n1-r1 | `aqy-rtex15-n1-r1-20261016-161011` | 16:10:11.493 | Running / `harbor_running` |
| n3-r1 | `aqy-rtex15-n3-r1-20261016-161011` | 16:10:11.888 | Running / `harbor_running` |
| n5-r1 | `aqy-rtex15-n5-r1-20261016-161012` | 16:10:12.342 | Running / `harbor_running` |
| n10-r1 | `aqy-rtex15-n10-r1-20261016-161012` | 16:10:12.786 | Running / `harbor_running` |
| n0-r2 | `aqy-rtex15-n0-r2-20261016-161013` | 16:10:13.219 | Running / `harbor_running` |
| n1-r2 | `aqy-rtex15-n1-r2-20261016-161013` | 16:10:13.739 | Pending / queued |
| n3-r2 | `aqy-rtex15-n3-r2-20261016-161014` | 16:10:14.221 | Pending / queued |
| n5-r2 | `aqy-rtex15-n5-r2-20261016-161014` | 16:10:14.707 | Pending / queued |
| n10-r2 | `aqy-rtex15-n10-r2-20261016-161014` | 16:10:15.096 | Pending / queued |
| n0-r3 | `aqy-rtex15-n0-r3-20261016-161015` | 16:10:15.512 | Pending / queued |
| n1-r3 | `aqy-rtex15-n1-r3-20261016-161015` | 16:10:15.921 | Pending / queued |
| n3-r3 | `aqy-rtex15-n3-r3-20261016-161016` | 16:10:16.569 | Pending / queued |
| n5-r3 | `aqy-rtex15-n5-r3-20261016-161016` | 16:10:17.058 | Pending / queued |
| n10-r3 | `aqy-rtex15-n10-r3-20261016-161017` | 16:10:17.564 | Pending / queued |

15个Pod的required anti-affinity配置已实际admitted，已分配的6个Pod分布于6个不同节点；Pod ownerUID与预期Job的对应关系已核对。Pending表示本快照尚未运行，不计为完成或失败。下文10个完整面板／微型job属于验收，与这里15个正式job分开计数。

## 2. 框架、客户端与网络路径

继续复用eval-in-loop `chufan_dev@c1fffbf839c449d7d35952da37664b5a67ea3df6`、Harbor0.20.0及原生PersistentAgent。n=0用terminal，正n用eval-budget；`max_resumes=1000`，关闭额外snapshot评分。不新建评分broker、反馈账本或实验管理平台。

固定Claude Code2.1.280，CLI摘要为`1e08503dbdf3c2cb0d706d32f3408277388d1c76ef108673e8fe42c1b322925b`。请求profile为`bedrock/gpt-5.6-sol`；v5两个微型run实际得到`global.openai.gpt-5.6-sol`响应并成功使用Read／Bash。关闭thinking和prompt caching，兼容适配保留有限临时错误重试。v6两个微型run现也实际得到同一预期响应模型并成功使用Read／Bash，assistant消息数分别14／13；各有6次模型egress路由允许记录及6个HTTP200，API错误为0。

正式run的早期活动另取16:19:00证据：已运行的6组均配置43200秒开发时间并处于`harbor_running`；已回收Claude记录片段中每组有43—69条assistant消息，响应模型均为`global.openai.gpt-5.6-sol`，已有Read／Bash／Agent等工具调用，未见API或生命周期错误。该检查只覆盖当时可用片段，不代表开发完成。正式run的gateway日志尚未回收，投影中的HTTP200计数0不作为“没有模型响应”的证据，也不用于计算正式成功请求总数。

v5经原生egress发出的14项竞赛来源请求均被代理拒绝，但直连探针发现外网旁路。因此“启用了egress、禁用了WebSearch／WebFetch”仍不足以通过网络验收。v6已将默认开发网络配置为Compose内部网络，仅由原生egress容器连接内部网络与出网网络；模型适配沿用现有egress路径。与v5相比仅5个网络相关源码／测试文件有已审差异，任务内容不变。源码已冻结，真实n0／n1重验现均通过。独立可信operator逐个复核：14项代理拒绝均带父域阻断原因、14项直连均关闭、PyPI获准请求有实际字节，6项模型路径经egress允许；冻结探针SHA一致，精确探针Bash各执行一次且输出与artifact一致。该结论限于所验路由及本批配置。

## 3. 当前资源与计时

旧8GiB候选／128GiB verifier试配在v3完整X15中出现明确内存故障，不能认证。后续资源已统一改为以下配置，并完成对应源码审查；v5真实完整面板已通过这组资源的验收，v6通过明确的来源与一致性证据复用该资源凭据。

| 层次 | CPU | 内存／限制 |
|---|---|---|
| 开发容器 | 2 | 32GiB，即32768MiB |
| 候选进程 | 每例固定一个不同CPU | `RLIMIT_AS=17179869184`字节，即16GiB地址空间；不是RSS测量值 |
| verifier容器 | 15 | 256GiB，即262144MiB；15个worker共享容器总内存 |
| 外层预留 | 4 | 8GiB |
| 单Pod总量 | 21 | 296GiB，即303104MiB；目标集群`dev` |
| Pod共享内存 | — | `/dev/shm`配置仍为8GiB |

当前提交器使用原生Job创建，并以required Pod anti-affinity约束同一批次分组内的作业使用不同节点。这不证明节点对其他租户独占，也不证明CPU物理独占。

候选900秒墙钟包含启动、导入、解析、建模、求解和写出。每worker总基础设施预算1200秒，由候选900秒、staging120秒与checker180秒余量相加；checker180秒并非单独硬截止。面板runner1500秒、verifier1800秒；5400秒冻结后档使用6300秒runner。构建和截止后评分可使Pod运行超过12小时，不延长开发T。

资源门禁至少需要一条完整有效采样，所有保留采样均须满足必需内存／CPU读数、指定限额及零OOM事件；候选出现明确资源故障也不能通过。`memory.peak`为可选项：当前节点缺失时明确记为`unavailable`，不以`memory.current`或采样最大值冒充内核峰值。空采样、必需读数缺失或OOM仍拒绝认证。

## 4. 真实验收历史

10月15日relay曾返回`token invalid`，当日部署中断。10月16日连接恢复后，五个原始归档与60例已经核验，共23,313,374,069字节。数据来源、字节和摘要保持不变；后续修复不覆盖原始data-lock。数值runtime固定镜像ID为`sha256:8914ca3a8bc7c12d5be7377b899b6dc555dddad24088a68e293019c9d06eecb9`，归档SHA256为`df5cda6c13954cbdb66819689b24ab3d3e1e63f1be69f902e7a4b5d0cc1d9fcf`。

| 版本／真实验收job | 实际结果 | 后续处理与边界 |
|---|---|---|
| 首次完整面板：`aqy-rtex15-full-panel-20261016-141216` | Docker启动前失败，旧model字段不被当前Site schema接受 | 保留失败批次；v2移除旧输出token覆盖并通过站点／计划预检。没有X15运行结果。 |
| v2完整面板：`aqy-rtex15-full-panel-20261016-141748` | Linux sandbox探针因PID1父进程路径失败 | 修正探针启动方式；构建成功不能代替沙箱验收。 |
| v3完整面板：`aqy-rtex15-full-panel-20261016-143328` | sandbox通过；完整X15汇总7 AC／8 RE，其中3次明确MemoryError；有效资源采样0条 | 8GiB候选配置不通过。节点kernel5.15缺少可选`memory.peak`使旧整组采样失败；修复逐文件读取并保留必需读数门禁。公开仅保留汇总，不发布X逐例或受限stderr。 |
| v3微型n0：`aqy-rtex15-acceptance-n0-r1-20261016-143329`；n1：`aqy-rtex15-acceptance-n1-r1-20261016-143329` | 模型调用前失败：`disallowed_tools`列表被错误转为列表字符串 | 修正实际CLI参数表示；未获得真实模型链路验收。 |
| v4服务器dry-run | 缺少fm-job版本／集群标记，被预检拒绝；没有实际job | 保留该拒绝记录，不计作服务器作业。随后v5固定部署标签，并使用原生Job创建与节点分组反亲和。 |
| v5完整面板：`aqy-rtex15-full-panel-20261016-152317` | 已完成且资源验收通过，墙钟924.564532秒；X15汇总8 AC／2 RE／5 TLE、aggregate=0（starter_validity=0），8例经过checker；无MemoryError／OOM，90条有效采样 | 采样最大`memory.current`为95,561,768,960字节，90条`memory.peak`均明确不可用。资源通过不表示starter全部可行，也不是正式研究成绩；采样最大值不是内核真实峰值。 |
| v5微型n0：`aqy-rtex15-acceptance-n0-r1-20261016-152513`；n1：`aqy-rtex15-acceptance-n1-r1-20261016-152513` | 均有真实指定模型、Read／Bash；微型starter终验均15／15可行。保护反馈计数分别0／1，n1结果已领取；代理拒绝14项来源请求，但检测到直连旁路 | 两个微型验收整体失败；其算法／计数成功部分保留，不能替代网络门禁。微型数据是人工夹具，不是原始X15研究成绩。 |
| v6微型n0：`aqy-rtex15-acceptance-n0-r1-20261016-154757`；n1：`aqy-rtex15-acceptance-n1-r1-20261016-154758` | 均completed／passed：指定模型、Read／Bash、每个微型终验15 AC；n0无反馈账本，n1恰好一次done／counted／collected且valid | 每个run的14项代理请求被拒、14项直连关闭，PyPI与6项模型路由获准；独立operator核对冻结探针、实际Bash输出及来源证据。人工微型数据通过不构成原始X15成绩。 |

这份记录共列出10个已实际创建的验收job：4个完整面板、6个微型生命周期；v4预检拒绝没有job。版本号、源码冻结、计划解析与验收job分别记录，不能据版本号推算提交数。

v6冻结清单覆盖149个文件，SHA256为`b09b93de42f8bf35aa657d50fbb12b86cbddd0f68f19b1dd67573195c340264b`。资源凭据的donor为v5、recipient为v6：50个小文件SHA一致，58个大原始文件inode及大小一致，2个小原始文件逐字节一致；server-dataready、runtime-manifest、probe、server_acceptance、runtime_env摘要一致，runtime归档inode一致。derived reuse来源证据SHA256为`ad6e8003b80b32527177dfed6855298e55266dac8cf7a9ee84d5811997f3d2de`。这是有来源核对的凭据复用，不新增完整面板job或实测次数。

## 5. 本地验证与正式提交门禁

公开task包23项测试通过。私有v5批次55项测试及60项子测试通过，覆盖计划、提交回执、资源／冻结、可选peak兼容与验收门禁；它们不执行真实模型或原始X15。v2的35项测试／14项子测试属于历史修复记录。v6已有61项测试／77项子测试通过，另有旧gateway29项回归通过；5个网络相关差异已审查。capture测试不执行真实CONNECT／TLS；网络结论另以实际微型run与独立operator检查为据，完整面板资源凭据仅按上述一致性与来源证据复用。

启动门禁已经完成并绑定本批源码：

1. 完整X15资源门禁由v5真实运行通过，并有v6复用来源证据；没有新增v6完整面板实测。
2. v6真实n0／n1均通过模型、工具、反馈计数／领取、截止、微型终验与可信网络检查，修复了v5已知直连旁路。
3. 独立operator复核通过，创建正式Job前先写入绑定冻结清单的acceptance gate，再以该gate创建15个正式角色。

| 证据 | SHA256 |
|---|---|
| 冻结源码清单（149文件） | `b09b93de42f8bf35aa657d50fbb12b86cbddd0f68f19b1dd67573195c340264b` |
| 启动acceptance gate | `aaaf24331e2b03d171e5d00d795ca43c58e3b6983608cbd48becc8c7d62f81bf` |
| 独立operator复核 | `a98023e106d3f773afa8872b78be75078ed6b73ae64eb02ad0f2bd448ce98825` |
| 资源凭据复用来源 | `ad6e8003b80b32527177dfed6855298e55266dac8cf7a9ee84d5811997f3d2de` |
| 验收部署位置核查 | `e0a1aba55493a201b7a7f374bd772021f50c1bbd4675caa077766ec89ac89df5` |

后续仍须观察正式模型活动、受理／完成／领取及运行状态，按各run实际开发开始时刻执行43200秒共同截止，冻结各自最终源码，再做不回流的5400秒／例X15评分。Pod启动或`harbor_running`本身不表示模型已经响应。

当前不存在本批正式分数。X同时用于反馈与冻结后评测，不构成独立未见测试；域名阻断也不能证明历史公开X数据绝对保密。私有逐例诊断仅供操作者审计，公开报告只包含协议允许的汇总。

相关入口：[任务包](../../task-packages/rte-maintenance-abc-x15-v1/README.md)、[配置协议](../protocol/rte-abc-x15-configuration.md)、[中文完成说明](../completion-rte-formal-launch-20261015.md)、[机器记录](../evidence/rte-formal-launch-20261015.json)。
