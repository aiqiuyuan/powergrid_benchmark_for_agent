# MAPDN / PowerGym 正式固定案例实验

本轮是独立于原五任务75次实验与600秒canary的新30次扩展。协议、案例和评分在正式开发前冻结；目前完成任务包、本地数值对齐与独立代码审查，正在执行新集群验收，**尚未提交30组正式开发**。

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

本地真实后端核对：MAPDN11项测试、PowerGym7项测试通过，独立审查分别复跑。MAPDN完整480步/960次潮流、全日电压合规，损耗1.835251037519195MWh；PowerGym9组参照逐小时物理指标与既有资格实验精确一致，另独立重放仅用合法观测的coordinated控制器。current-load优化和全日oracle信息权限更多，单列参照，不作为同信息策略排行。PPO/SAC pilot与本轮不共享开发预算，也不是本轮启动前置条件。

迁移已核对非GOC目录完整内容校验、独立Relay登录和新集群运行证据。新批次只使用`/mnt/cfs_bj_fm/workspace/aiqiuyuan`；保留旧源码、canary、资格实验与失败记录。

正式网络和截止验收新增两项具体保护：开发容器仅挂内部网络，所有外联经允许模型网关的代理；代理不再将任意单标签、整数或hex形式IP当作内部服务放行。可信截止watchdog暂停整个开发容器、核验Docker的Paused状态，再以限时限长tar流导出唯一源码；最终Harbor读取该快照，并核对deadline、artifact和checker三者SHA一致。新launcher19项本地回归通过；这些本地检查不能替代真实Linux/native回执。

准备版v1数值镜像验收已完成，但其继承代理的旁路缺口导致不用于正式启动。新的v2修改仅发生在新冻结副本；bootstrap作业`aqy-dist-formal-build-v2-20261016-200713`已受理。待新数值、网络和确定性原生四角色验收完成后，再记录来源清单、镜像、完整30角色矩阵和create-only提交回执。
