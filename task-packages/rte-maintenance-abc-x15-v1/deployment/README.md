# 启动配置示例与本批验收状态

以下片段应合并到操作者私有`site.toml`，不携带服务地址或密钥。

2026-10-16 v5真实完整X15已通过16GiB候选／256GiB verifier／296GiB Pod资源门禁，v6在任务、数据、runtime与资源一致性核对后复用该凭据；真实n0／n1微型生命周期均通过。15个正式run已于16:10提交，最终研究结果尚待。实际部署与来源关系见[实验记录](../../../docs/experiments/rte-abc-x15-formal-20261015.md)及[中文完成说明](../../../docs/completion-rte-formal-launch-20261015.md)。本页配置片段本身不执行提交。

```toml
[egress]
enabled = true

[agent."codex"]
flags = { reasoning_effort = "high", web_search = "disabled" }

[agent."claude-code"]
flags = { reasoning_effort = "high", disallowed_tools = "WebSearch,WebFetch" }

[fmjob]
# 单个实验需要 developer 2CPU + verifier 15CPU，再加框架/Docker开销。
# 例如留4CPU、8GiB开销：至少21CPU、296GiB；按实际site调度校准。
max_cpus = 21
max_memory_mb = 303104
overhead_cpus = 4
overhead_memory_mb = 8192
```

这些字段是外层上限，不能截低任务的2+15CPU与32+256GiB需求；包含4CPU／8GiB开销后，外层为21CPU／296GiB。`max_cpus=15`会不足。每候选地址空间统一为16GiB；这次调整源于旧8GiB额度下真实X15出现`MemoryError`。新额度的v5完整X15资源门禁已通过，无MemoryError／OOM、90条有效采样；结果8 AC／2 RE／5 TLE，不代表算法全例可行。实际节点、模型profile、镜像摘要、egress和解析计划已按本批门禁记录；后续更换部署或资源时仍须重新核对。

反馈次数用现有启动器的`n`参数设置；`n=0/3/10/...`是完整X15面板的准入次数。不要同时运行同一trial的多个自适应反馈请求以替代顺序交互。900秒反馈与5400秒冻结最终评分使用两个独立入口，不能把最终工具作为额外免费开发反馈。

域名阻断目前针对官方RTE来源和主要GitHub入口；不能覆盖所有镜像/代理/模型记忆。开发容器不携带X、旧候选、旧成绩、排行榜工作簿、私有inventory或freeze报告。记录实际egress探针和来源审计，不能只凭配置宣称防泄漏已验证。

v6本批已将Compose默认网络设为内部网络，main／judge只连接内部网络，egress另连出网网络；模型兼容适配显式经原生egress。真实微型run及可信operator已核对14项代理拒绝、14项直连关闭和PyPI／模型允许，结论限于所验路由与本批配置。

## agent安装与既有生命周期

Codex运行前须预装与Harbor配置相容的CLI，并验证`codex --version`。本地核查的Harbor在Debian上默认通过`raw.githubusercontent.com`安装NVM；该域已被本task封禁，不能靠临时放开X来源解决安装。应在镜像构建／后端基础镜像准备阶段预装CLI；正式启动前检查，不把静态计划通过当作安装成功。Claude Code也须核验既有CLI或其合法安装入口。

原生PersistentAgent按verifier超时设置1800秒的再次唤醒余量；它影响最后阶段是否续跑，不把已运行会话的开发上限改成固定11.5小时。各n档须记录并统一persist／max_resumes和实际开发时长。当前未修改该框架行为。

原生Harbor结束后的终验仍使用900秒评分入口，不向开发反馈；5400秒最终档需对同一截止源码单独执行`tools/final_evaluate.py`。独立工具只校验冻结摘要，开发停止与截止产物来源仍需原框架记录证明。
