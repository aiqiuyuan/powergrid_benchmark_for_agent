# RTE 检修排程算法自主开发：反馈v2

请阅读 `/app/problem.md`，在 `/app/submission/solver.py` 开发通用算法。A/B/C共45个完整官方实例位于 `/app/public`；官方checker和公开评测器位于 `/app/support`，可无限次本地评分，不消耗受保护反馈n。最终只收集solver.py。

**主目标是900秒／例的X15表现。** 先比较可行例数k，相同k再比较质量Q：每个可行例的q为 `0.5-atan(F/scale)/pi`，固定15例分母Q=sum(q)/15，无效例贡献0。框架标量是 `(k+Q)/16`，一个额外可行例优先于任何质量变化。F沿用官方越低越好的目标，scale仅根据输入确定并冻结；这不是原赛积分。

每次受保护反馈通过原计数接口完整运行X15，然后一次性返回JSON，含候选SHA256、900秒预算、评测是否完整、可行数／比例、Q、reward、全部可行标记、状态与约束分类计数，以及全部15个稳定实例ID的具体诊断。每例有AC／WA／RE／TLE、退出码、候选墙钟秒数、候选子进程峰值RSS及单位；有效例有官方F、mean_risk、expected_excess、q，无效例这些目标字段为null，汇总仍按质量0贡献。无效提交规范为RE并附invalid_submission。基础设施故障会明确标记evaluation_completed=false，不能当作15例算法失败的可用0分。不会返回输入、解文件、原始stdout/stderr、checker原文或私有路径。请自行比较已收到的反馈和保留候选版本。

每例900秒墙钟包括启动、导入、解析、求解及写出，单核、16GiB地址空间；数据复制／官方检查另有基础设施余量。开发2CPU、32GiB，最长12小时，原生框架保留终验余量并记录实际开发时间。反馈配额由启动时n控制；终验和显式反馈的具体计费遵循统一运行时账本，不得绕过。不得读取受保护环境、获取X输入、参考解、旧实验产物或排行榜答案。

最终提交是开发截止时工作区文件，框架不会自动恢复历史最高分版本。原生截止后900秒终验是主成绩，不向开发agent回流。**5400秒／例只对同一冻结源码作补充评测**，不占n、不回流、不选优。你的设计和最终版本应围绕900秒主目标。

接口：`python solver.py --instance INPUT.json --output OUTPUT.txt --time-limit SECONDS --seed 2020`。只用标准库、NumPy 2.2.6、SciPy 1.15.3；最终镜像不安装新增依赖。输出每行 `intervention_name start_time`，每项恰好一次，不要自报分数。

公开示例：`python /app/support/public_eval.py --case A_01 --seconds 30 --workers 1`。省略--case评估ABC45；完整面板可能很久。ABC工具使用同样的“可行数优先、面板大小固定分母”规则，但分母是本次ABC面板数量，不能直接当作X15分数。完整JSON含逐例结果，供本地调试。
