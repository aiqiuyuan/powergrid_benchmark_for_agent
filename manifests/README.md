# 结构化清单：设计声明与填写规则

这些 JSON 是文档配套的**设计声明/模板**，不是现有框架的运行配置，也不是已填实的正式数据清单。没有执行器、JSON Schema 验证器或正式数据包随本次提交发布。

| 文件 | 用途 |
|---|---|
| [benchmark-v0.1-design.json](benchmark-v0.1-design.json) | 固定任务族、设计状态、默认协议与尚未冻结事项 |
| [task-release.template.json](task-release.template.json) | 逐任务填数据、checker、baseline、资源、超时与验收记录 |
| [split-manifest.template.json](split-manifest.template.json) | 记录同源分组、数据角色、曝光历史和密封清单承诺 |
| [run-manifest.template.json](run-manifest.template.json) | 记录不可变比较条件、共同截止时间、恢复来源与最终产物 |

## 使用规则

1. `status=design` 或 `template` 表示不具备运行准入。`null` 表示未填/未冻结；不是0、空资源、不限次数或可自动推断的默认值。
2. task release 的 evaluator、dataset、artifact 与 runtime 摘要需来自实际文件/镜像的完整 SHA-256 或明确的不可变镜像 digest。不要把任意示例字符串填成真实摘要。
3. 数据角色采用协议中的四个完整名称；calibration 是曝光/校准用途标记。密封数据完整成员可留在评测端，公开仓库只放真正生成的承诺摘要和审计说明。
4. `feedback_budget.mode=limited` 时 `max_accepted_jobs=0` 明确拒绝受保护反馈。显式 unlimited 是独立研究协议，不以0或null代替。
5. `cumulative_token_cap=null` 与 `cumulative_token_reservation_enabled=false` 在新协议中表示不启用累计配额；provider 用量 unknown 不能写0。单响应上限需另填。
6. 公开选择默认不进入训练标签集；若改变拟合/选择/反馈/时限/资源，创建新的协议或release，不覆盖旧manifest。
7. 生成正式清单前需通过[实施验收](../docs/implementation-plan.md)；本次只核查 JSON 格式、字段与文档的一致性，不把语法合法当作发布认证。

模板提供记录结构，字段必需性、类型验证和执行器映射是后续实现工作。增加该验证器时，应按[产物契约](../docs/protocol/artifact-contract.md)冻结版本并覆盖缺字段、错误类型、计时和预算歧义。
