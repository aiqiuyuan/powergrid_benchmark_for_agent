# MAPDN canary problem contract

完整接口与评分合同见 [instruction.md](instruction.md)。本包是 MAPDN 33 节点来源的真实 Pandapower 因果适配，用于 600 秒开发、n=0/1 与独立终评流程 canary；不声明已认证的困难 benchmark 或完整论文复现。

目标 case 在开发前按固定规则选取：三个原始数据表最早共同包含的完整自然日，480 个三分钟间隔、相同源码列序、无噪声、初始归一化动作全部为零。所有 source 成员先验证 CRC32 与本地 SHA-256；额定容量按完整原始 PV 表各列最大值的 1.2 倍冻结。选择规则和 reward 公式均在开发前固定，不能根据 n=0/1 比较调整。

与上游环境的差异是每次观测和计分均绑定同一当前外生时标，完整计分恰好 480 个间隔，候选 RNG 不影响外生实现，动作由可信侧校验，所有线路实际有功损耗与全网平衡交叉验证。每个 PV 的局部 Controller 在不同 UID、独立 Landlock 文件域和 seccomp 进程中运行，仅接收本单元当前局部 JSON 观测。

公开镜像只包含 starter、接口说明、合成检查和数值依赖，不含完整目标数据、上游源码、模型或 scorer。可信 verifier 目录仅 root 可读；反馈只包含已声明 aggregate。网络、文件和模型 gateway 的实际封闭情况仍需部署验收；本包状态不能替代该验收。
