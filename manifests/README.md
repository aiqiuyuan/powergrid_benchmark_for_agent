# 结构化清单：设计声明与填写规则

这些JSON是文档配套的**设计声明／模板**，不是现有框架的运行配置，也不是已填实的正式数据清单。2026-10-15新增的基础实现只验证`configs/`配置和五个task-adapter设计声明；没有将本目录的全部release／split／run模板映射为生产执行器，也没有发布正式数据包。

| 文件 | 用途 |
|---|---|
| [benchmark-v0.1-design.json](benchmark-v0.1-design.json) | 固定任务族、设计状态、默认协议与尚未冻结事项 |
| [task-release.template.json](task-release.template.json) | 逐任务填数据、checker、baseline、资源、超时与验收记录 |
| [split-manifest.template.json](split-manifest.template.json) | 记录同源分组、数据角色、曝光历史和密封清单承诺 |
| [run-manifest.template.json](run-manifest.template.json) | 记录不可变比较条件、共同截止时间、恢复来源与最终产物 |
| [task-adapters/](task-adapters/) | 五个task的选定公平路线、可执行算法合同、已有条件与缺少证据；均为design/pending |
| [framework-foundation.json](framework-foundation.json) | 通用基础层的实现范围、验证证据与尚未认证的集成能力 |

## 使用规则

1. `status=design` 或 `template` 表示不具备运行准入。`null` 表示未填/未冻结；不是0、空资源、不限次数或可自动推断的默认值。
2. task release 的 evaluator、dataset、artifact 与 runtime 摘要需来自实际文件/镜像的完整 SHA-256 或明确的不可变镜像 digest。不要把任意示例字符串填成真实摘要。
3. 数据角色采用协议中的四个完整名称；calibration 是曝光/校准用途标记。密封数据完整成员可留在评测端，公开仓库只放真正生成的承诺摘要和审计说明。
4. `feedback_budget.mode=limited` 时 `max_accepted_jobs=0` 明确拒绝受保护反馈。显式 unlimited 是独立研究协议，不以0或null代替。
5. `cumulative_token_cap=null` 与 `cumulative_token_reservation_enabled=false` 在新协议中表示不启用累计配额；provider 用量 unknown 不能写0。单响应上限需另填。
6. 公开选择默认不进入训练标签集；若改变拟合/选择/反馈/时限/资源，创建新的协议或release，不覆盖旧manifest。
7. 生成正式清单前需通过[实施验收](../docs/implementation-plan.md)；本次只核查 JSON 格式、字段与文档的一致性，不把语法合法当作发布认证。

`configs/experiment.template.json`已有字段／类型／待定值校验，可用`config-check`审阅。`adapter-check`不验证外部证书真实性，也不运行能源算法。其余正式模板的执行器映射仍待集成；按[产物契约](../docs/protocol/artifact-contract.md)补齐真实证据，不能把JSON格式正确升级为正式release。
