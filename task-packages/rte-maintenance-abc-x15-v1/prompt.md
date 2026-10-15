# RTE 检修排程算法自主开发

请阅读 `/app/problem.md`，在 `/app/submission/solver.py` 中开发一个通用排程算法。A/B/C共45个完整官方实例位于 `/app/public`；官方 checker 及公开评测器位于 `/app/support`，可无限次本地运行和修改开发辅助代码。最终提交仅收集 `solver.py`。

受保护评分服务每次都会完整评估X15，反馈只有面板归一化分数、可行比例、verdict/约束错误分类计数，以及全部可行时的平均官方目标/均值风险/超额风险。不会返回单实例、解文件、原始输入、候选标准输出、逐例分数或排行榜答案。反馈限额由启动时的n参数控制；ABC本地评分不消耗该限额。终端提交和显式反馈的具体计费遵循运行时账本，不能额外向服务绕过计数。

每例正式反馈执行900秒墙钟，1CPU、8GiB地址空间上限；启动、导入、解析和输出都计时。开发环境2CPU，32GiB内存，最长12小时。允许更换搜索设计、初始化、建模和修复策略；不能修改或读取保护评测环境，不能下载X数据、官方/第三方参考答案或旧实验候选与成绩。网络控制只是辅助约束，请遵守上述实验规则。

接口：`python solver.py --instance INPUT.json --output OUTPUT.txt --time-limit SECONDS --seed 2020`。使用标准库、NumPy 2.2.6、SciPy 1.15.3；最终评分镜像不会安装开发时新增的依赖。输出每行 `intervention_name start_time`，每项恰好一次。不要自报分数。

公开评分示例：`python /app/support/public_eval.py --case A_01 --seconds 30 --workers 1`。省略`--case`评估ABC45；完整本地面板可能需要数小时，自行分配开发时间。公开工具返回ABC的详细结果供调试。
