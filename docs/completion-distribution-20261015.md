# MAPDN / PowerGym 基础适配完成记录

2026-10-15，在最新 RTE ABC/X15 主分支基础上新增两个配电网扩展；不覆盖 RTE 新协议，也不改变原五任务75-run设计。任务仍为 `design / certification-pending / release_ready=false`。

已交付：

- [MAPDN card](task-cards/mapdn-voltage-control.md)与[PowerGym card](task-cards/powergym-volt-var-control.md)，分别说明演化对象、合法信息、设备动作、完整case选择、基线、物理指标、已知上游差异和待验收项。
- 两个机器声明、扩展ID、配置目录、README/来源索引与[固定来源锁](../configs/distribution-sources.json)。五项核心实验范围与两个待校准扩展分开记录。
- 依赖标准库的动作与有限数值检查、MAPDN无功能力转换/局部字段投影、PowerGym正确idle/SOC终态、真实有功损耗能量积分、电压合规及完整时域检查。
- 显式文件顺序的PowerGym负荷打包，保留逐load/profile/step的源行、跨文件映射、尾部弃行与原始/打包SHA-256。
- 可信源码准备工具：检查实际commit、逐文件Git blob与SHA-256、拒绝隐藏修改和链接、独立worker副本及回执。不向开发端复制完整上游环境或目标数据。
- [两套原生task骨架](../task-packages/README.md)、可执行standalone starter、合成接口输入和小检查；完整task资源、case、私有运行评分程序均未填实，模板不可直接启动。

本机 Python 3.12.14 验证：**125项单元测试全部通过，整体行覆盖率超过89%，Ruff及构建通过。** 两个固定上游源码实际准备成功，分别核验71与93个已跟踪文件；PowerGym额外核验10份负荷CSV摘要。34Bus与123Bus真实公开负荷按显式顺序分别打包16份24步profile，弃行168和96，不能称16个有已验来源日期的独立日。模板shell语法、未填私有评分摘要的失败退出和未渲染配置不可启动均已检查。

独立代码审查发现并修复了特殊Git index标记隐藏修改、复制期间源变动、开发镜像漏support和非root用户无法编辑submission的问题。审查后没有未解决的P1/P2。机器记录见[基础验证摘要](evidence/distribution-foundation-validation-20261015.json)。通用生命周期夹具仍是历史参考合同，只作回归检查，不作为两题严格n验收证据。

**尚未完成完整任务运行接入。** MAPDN大型数据及模型加载、修正时序的真实潮流runner、PowerGym实际OpenDSS与电池/分接头物理核验、两题私有完整评分器、最终case、资源/算法限额、主指标/reward、同条件基线和原生n=0/n=1 canary都需要真实运行后验收。本轮没有Docker/Harbor/集群实验或新基线分数。具体接入顺序、命令与剩余责任见[基础适配说明](framework/distribution-control-integration.md)。
