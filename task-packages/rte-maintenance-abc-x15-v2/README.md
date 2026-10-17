# RTE ABC开放／X15保护评测任务v2

本包实现[反馈v2协议](../../docs/protocol/rte-feedback-v2.md)，与v1独立版本化，不改动旧包、旧候选及成绩。ABC45、官方checker、输入尺度、starter和候选沙箱沿用v1；改变的是任务聚合、完整结构化反馈、统一900秒主目标及相应题面。

| 项目 | 合同 |
|---|---|
| 开放开发 | 官方ABC45、checker及本地评分，不计n |
| 保护反馈 | 一次完整X15计一次n，900秒／例，15并行 |
| 排行 | 可行数k优先；相同k比Q=sum(valid q)/15；reward=(k+Q)/16 |
| 逐例质量 | 官方F、mean_risk、expected_excess、q；失败目标字段null，汇总贡献0 |
| 反馈 | 15例完整白名单JSON，候选摘要、汇总、状态、约束计数、退出码、wall秒、RSS与单位，最多16KiB |
| 主成绩 | 原生截止后900秒终验；同一冻结摘要，不回流，不重放取最大值 |
| 补充 | 同一冻结源5400秒／例，独立启动、不回流、不计n、不选优 |
| 开发资源 | 2CPU／32GiB、最长43200秒，原生终验余量与实际时长记录保留 |
| 评测资源 | 15CPU／256GiB；每候选单核／16GiB地址空间 |
| 最终选择 | 截止工作区solver.py；不会自动回滚历史最好反馈 |

`validity`和`reward-details.valid`仍表示全板可行；部分可行面板可以是完整评测并获得正reward。应结合`evaluation_completed`、`metric.feasible_count`及`all_cases_feasible`解读，不能把valid=false等同于基础设施失败。`rte_x15_coverage_quality_900_v2`是原生指标名。900秒是候选进程墙钟，包含启动、导入、解析、求解和写出；复制输入与官方检查有独立120／180秒预算。RE/TLE仍不计有效目标，即使输出过中间解。

## 重建与验证

只提交可移植源码及来源元数据，不携带大型实例或私有运行产物。来源固定官方commit `052def4d47271f913f89a68169083059732360f3`。checker和许可证锁在`source-lock.json`；数据原字节、角色和尺度锁在`data-lock.json`；starter锁在`starter-lock.json`。v2自己的整任务源码锁由批次准备／验收建立，不能把旧v1整任务锁当作v2。

```sh
python prepare.py --inventory /private/verified-inventory.json
# 或从data-archives-lock.json对应的全部5个官方归档重建
python prepare.py --archives-dir /data/official-archives
python -m unittest discover -s verification -v
docker build -t rte-abc-x15-runtime:1 images
docker build -t rte-abc-x15-developer:2 environment
docker build -t rte-abc-x15-verifier:2 tests
```

准备脚本校验全部60例原字节与尺度，不改上游checker／starter；物化`environment/app/support`、`tests/support`、题面和`tests/offline`。开发上下文只有ABC45，verifier上下文只有X15。不要把完整任务目录或私有inventory挂载给开发agent。

候选沙箱沿用v1的不同UID、root拥有scratch父目录、单核绑定、地址空间和seccomp策略；共享临时目录存在残余主动共享通道，域名阻断也不是完全保密证明。验收应报告实际边界。详见[验证说明](verification/README.md)和[部署说明](deployment/README.md)。本地合成验证不替代当前v2真实模型、计数、镜像和服务器资源验收，正式状态以本批提交记录为准。

## 冻结与补充评测

```sh
python tools/freeze_candidate.py --candidate /private/cutoff/solver.py --output-dir /private/frozen
# 在可信verifier容器执行；禁止给仍在运行的agent挂载报告
python tools/final_evaluate.py --candidate /private/frozen/solver.py \
  --freeze-receipt /private/frozen/freeze-receipt.json \
  --manifest /tests/data/manifest.json --output /private/reports/supplemental.json --seconds 5400
```

冻结receipt的stage是`frozen_final_source`，两档共享同一候选SHA256。离线工具也支持`--seconds 900`作明确标记的主评测重放，默认批次不重复原生900秒终验；若另行使用，须预先声明哪次权威，禁止两次取高。5400秒结果stage保留`frozen_final_5400`，assessment_role为supplemental。工具拒绝候选摘要不匹配、非v2完整面板或覆盖既有报告。
