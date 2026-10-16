# RTE正式实验启动与当前完成情况

创建日期：2026-10-15；更新日期：2026-10-16。以下时间均为Asia/Shanghai，Kubernetes状态快照为16:13:29，早期模型活动检查另取16:19:00。

**15个正式run已提交，6个Running、9个Pending排队；正式完成数为0。** 16:10:10—17完成启动门禁落盘与15个Job创建。6个运行Pod已进入`harbor_running`，分布于6个不同节点，实际资源均为21 CPU／296GiB；required anti-affinity已实际admitted，Pod ownerUID与Job对应关系核对通过，未见错误。16:19从已回收的Claude记录片段另确认这6组均有预期模型响应及Read／Bash等工具调用。`release_ready=true`仅表示RTE本批启动门禁已通过，最终分数和研究结论仍待12小时开发及冻结后90分钟／例评分。

## 本批设置与已完成工作

- **正式研究设置。** n=0／1／3／5／10各3次独立开发，共15个run；每次开发43200秒，累计token不限。ABC45与官方checker开放自测，完整X15一次受理计一次反馈，900秒／例、15路并行。截止产物使用最后工作区的`solver.py`，另做5400秒／例评分，不回流开发。
- **数据与数值环境。** relay恢复后，五个归档、60例及23,313,374,069字节已核验。原始输入、data-lock、官方checker和共同starter保持不变；数值runtime与源码清单绑定记录。
- **资源验收。** 候选16GiB地址空间（17179869184字节），verifier15 CPU／256GiB，Pod21 CPU／296GiB；开发端2 CPU／32GiB、外层4 CPU／8GiB、共享内存8GiB。v5真实完整X15资源门禁通过，无MemoryError／OOM，90条有效采样，采样最大`memory.current`为95,561,768,960字节；90条`memory.peak`均不可用，采样最大值不是内核真实峰值。
- **实际微型生命周期通过。** v6真实n0／n1均completed／passed，响应模型为`global.openai.gpt-5.6-sol`，assistant消息分别14／13，成功使用Read／Bash，各有6次模型路由允许及HTTP200，API错误0。每个微型终验15 AC；n0无反馈账本，n1恰好1次done／counted／collected且valid。它们使用人工微型数据，不是原始X15正式成绩。
- **网络旁路修复并实测。** 默认开发Compose网络设为内部网络，原生egress连接内部与出网网络，模型适配沿用现有egress，不另建broker。独立可信operator逐个确认14项代理拒绝及父域阻断原因、14项直连关闭、PyPI获准请求的实际字节和6项模型路由允许；冻结探针SHA一致，精确探针Bash各调用一次且输出等于artifact。

15个正式角色的实际Job ID、提交时刻和状态见[完整运行表](experiments/rte-abc-x15-formal-20261015.md)与[脱敏机器证据](evidence/rte-formal-launch-20261015.json)。此前10个验收job（4个完整面板、6个微型生命周期）分开计数，不算入15个正式run。

## 修复历史与证据边界

首次完整面板因旧Site字段在Docker前失败；v2因sandbox探针PID1路径失败；v3沙箱通过并完成真实X15，但汇总7 AC／8 RE、3次MemoryError，资源采样0条，不能认证。v3两个微型run因工具禁用参数表示错误在模型前失败。v4服务器dry-run被部署标记预检拒绝，没有实际Job。v5固定原生Job创建、部署标签与节点反亲和；其微型模型／反馈链路成功，但发现直连旁路，整体仍失败，随后才进行v6网络修复和重验。kernel5.15缺失可选`memory.peak`时现逐文件保留必需读数并记录`unavailable`，空采样、必需缺失或OOM仍拒绝。

v5完整X15资源验收墙钟924.564532秒，汇总8 AC／2 RE／5 TLE、aggregate=0（starter_validity=0），8例经过checker。通过的是资源门禁，starter并非全部可行，也没有本批正式研究成绩。公开仅保留汇总，不发布受保护X逐例诊断、stderr、模型轨迹或私有连接信息。

v6仅有5个已审网络相关源码／测试差异，task不变；149文件冻结清单SHA256为`b09b93de42f8bf35aa657d50fbb12b86cbddd0f68f19b1dd67573195c340264b`。资源凭据的donor为v5、recipient为v6：50个小文件SHA一致，58个大原始文件inode／大小一致、2个小原始文件逐字节一致，相关运行及验收文件摘要一致，runtime归档inode一致。来源证据SHA256为`ad6e8003b80b32527177dfed6855298e55266dac8cf7a9ee84d5811997f3d2de`；这是有来源核对的复用，不是v6新跑的完整面板。

公开task包23项测试通过；私有v6为61项测试／77项子测试，另有旧gateway29项回归。v5的55项／60项子测试、v2的35项／14项子测试保留为历史。capture测试不执行真实CONNECT／TLS，网络结论另以实际微型run与独立operator检查为据。启动gate SHA256为`aaaf24331e2b03d171e5d00d795ca43c58e3b6983608cbd48becc8c7d62f81bf`，绑定上述冻结源码；operator复核及验收部署位置证据摘要见机器记录。

公开提交`67a1fbcaceaaae219cc45d6e5eeecdff366fe4aa`的[GitHub PR检查](https://github.com/aiqiuyuan/powergrid_benchmark_for_agent/actions/runs/38875115384)及[推送检查](https://github.com/aiqiuyuan/powergrid_benchmark_for_agent/actions/runs/38874915118)均已通过，覆盖Python3.11／3.12／3.13基础框架测试、portable RTE及真实Linux沙箱探针。后续补充此检查链接仅修改文档，不改变上述已验收任务源码或运行批次。

## 当前运行与后续结果

16:13 Kubernetes快照的6个Running和9个Pending是观察状态，不承诺后续运行结果；Pending不计为完成或失败。16:19早期检查中，6组已运行角色均配置43200秒开发时间；可用Claude记录片段分别有43—69条assistant消息，模型均为`global.openai.gpt-5.6-sol`，未见API或生命周期错误。正式gateway日志尚未回收，投影中的HTTP200计数0不作无模型响应解释。接下来继续核对模型活动和反馈计数，按各run实际开发开始时刻执行12小时截止，冻结各自最终源码，再完成不回流的90分钟／例X15评分。构建、排队及截止后评分不等于开发T，Pod总存活时间可能超过12小时。

本次只完成RTE批次启动，尚无正式最终分数。X同时用于反馈与冻结后评分，不构成独立未见测试；所验路由通过也不等于证明历史公开X数据绝对保密。
