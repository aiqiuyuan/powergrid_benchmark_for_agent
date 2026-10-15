# 决定 0002：反馈、选择与独立留出

> **当前第一阶段政策（2026-10-15）：以[决定0005](0005-fixed-case-evolution-first.md)为准。** 每task固定一个高难完整case，同case开发、计n反馈与冻结复核；开发端禁止完整checker和本地完整目标评分，不设免费public-selection。下文四角色／独立留出、公开checker、best-public-selection等属于较早设计或第二阶段参考，不是本阶段默认。原生入口的实现与验收状态见当前决定和各任务卡§12。

**状态：已采纳为设计决定；执行隔离与真实 split 待完成。日期：2026-10-14。**

## 背景

多组旧实验的反馈与终评面板重合；部分输入和评分在开发端可直接获取。限制服务调用次数因此不一定限制实际信息。公开 checker 访问本身不构成泄漏，真正的边界是受保护数据和结果。L2RPN 主比较目前只有公开选择分数，不能作为最终泛化结果。

## 决定

采用 public-development、public-selection、protected-feedback、final-test 四种数据角色，先按来源、拓扑或时间窗口分组，再切分。原暴露数据标记 calibration。跨拓扑与同拓扑时间泛化采用不同 split_id。

评分实现、物理定义和数值容差在反馈与终评间一致，数据成员独立。公开目标与 checker 合法；受保护面板由评测端保管。n 定义为最多受理的作业数，n=0 禁止受保护调用；旧内部参数 0=unlimited 不得直接迁移。

默认 best-public-selection，选择在 T 内完成公开选择评测的候选；终评不选模。protected-feedback 的内容/粒度或候选选择方式改变时使用不同 protocol_id。公共数据的模型预训练暴露不能通过目录隔离排除，必须披露。

## 影响与待冻结事项

旧成绩保留为 calibration，不能重命名为未触碰测试。真实 split 成员、承诺摘要、HEFTCom 特征公布时序、反馈字段与各任务聚合仍需审计校准。执行验收需覆盖目录、缓存、日志、出网和迟到反馈。

完整规则见[评测协议](../protocol/evaluation-protocol.md)。仅文档约束不表示访问边界已实际生效。
