# RTE ABC开放 / X15保护评测任务 v1

本目录是新建任务，不改变旧A4/X04任务或正在运行的实验。它沿用 ROADEF/EURO 2020 RTE 原始JSON、固定官方checker及先导任务的归一化公式，重建更完整的开发与反馈边界。

| 项目 | 配置 |
|---|---|
| 开放开发 | A/B/C各15例，共45例；完整输入、官方checker、本地评分开放 |
| 受保护反馈 | X15完整面板；每次接受的评分请求计1次受保护调用 |
| 反馈资源 | 15个独立worker进程；每个候选固定一个不同CPU、900秒墙钟、8GiB `RLIMIT_AS` |
| 反馈内容 | 仅聚合分数、可行比例、verdict和约束错误分类计数；全部可行时再返回平均目标组成 |
| 开发资源 | 12小时、2CPU、32GiB内存，无GPU |
| verifier资源 | 15CPU、128GiB容器共享内存；暂定试配，未做完整面板峰值测量 |
| 冻结最终重评 | 同一X15、5400秒/例、15并行；独立离线工具，结果不返agent，不调用反馈账本 |

每例900秒包括候选进程启动、导入、JSON解析、求解和写出；复制输入/启动worker与官方checker另留120秒和180秒基础设施预算。反馈runner外层1500秒，native verifier1800秒。基础设施超时/错误会使评测失败，不能伪装为算法低分。900秒求解超时按TLE记入面板；任一例不合法则组合分数为0，可行比例仍返回。15CPU是任务配置；实际集群容量和外层资源上限仍须验证，不能据此宣称已申请成功。

`n`统计受保护X面板调用，不统计ABC本地评分。运行时账本负责请求准入/次数；本任务评分脚本不另建账本。一次调用内部并行15个实例，连续反馈轮次仍按agent的自适应顺序发生。冻结重评前应停止开发controller并冻结候选；同一X用于反馈和重评，因此最终成绩不是 untouched test。历史竞赛平台、编译器、硬件和排名计分均未复现，归一化分数也不等于历史排行榜排名。

## 数据和源代码锁

官方仓库固定commit：`052def4d47271f913f89a68169083059732360f3`。`source-lock.json`锁定官方checker和许可证；`data-lock.json`锁定60个原始JSON字节、角色、大小及仅由输入计算的scale。`starter-lock.json`标记旧先导starter的来源与hash，其完整面板可行性和性能仍待实测。官方checker保持原样，额外输出完整性/格式检查位于`support/official.py`。

候选进程通过seccomp禁止网络和新建子进程，允许受限线程。不同UID及root拥有的0710 scratch父目录限制各自输入目录的访问，候选只拥有700权限的output子目录；共享`/tmp`、`/dev/shm`等文件系统仍存在主动共享文件的残余通道。本包不提供完整逐实例文件系统隔离，也未完成Linux沙箱认证。应将这些限制与验收结果一并报告，不把它们作为已证明防止恶意候选串通或所有信息泄漏的依据。

准备数据可使用受信任的数据inventory：

```sh
python prepare.py --inventory /absolute/path/data-inventory.json
```

可移植源码包不携带巨型实例；`data-archives-lock.json`提供固定官方commit的5个archive URL、字节、SHA256与git blob。B原包目录名为`B_set_rounded`；C为`C_compact.7z`，X由`X_compact_1_1.7z`及`X_compact_1_2.7z`共同组成，保留这些官方原始字节，不重新数值舍入。从官方取得全部5个原包后：

```sh
python prepare.py --archives-dir /data/official-archives
```

也可使用已解压目录，其中X目录必须包含两个X原包的全部15例，按随包`data-lock.json`逐例验证：

```sh
python prepare.py --a /data/A_set --b /data/B_set --c /data/C_set --x /data/X_set
```

准备环境可先安装`python -m pip install ijson==3.4.0.post0 py7zr`。7z解压需`py7zr`；缺少已验证scale receipt时，准备脚本使用`ijson`逐检修流式计算scale，避免一次解析数GB原始JSON。构建阶段可硬链接受信任原始JSON，跨文件系统退回复制；不会chmod/chown原始链接inode。开发镜像构建上下文仅`environment/`，其中只有ABC45；verifier上下文仅`tests/`，其中只有X15。`/tests`对候选UID不可遍历；每个并行候选的scratch父目录由root拥有，配属该候选的独立GID且权限0710；output子目录由候选UID:GID拥有、权限700，候选不能替换父目录中的output入口。候选标准输出不作为反馈，也不进入评分器的输出解析。并行使用进程而非线程，避免官方checker的stdout重定向交叉。

## 构建与验收

```sh
docker build -t rte-abc-x15-runtime:1 images
docker build -t rte-abc-x15-developer:1 environment
docker build -t rte-abc-x15-verifier:1 tests
```

运行时固定Python 3.12镜像标签、NumPy2.2.6、SciPy1.15.3；基础镜像标签和apt依赖尚未锁digest，正式批量比较前应记录实际镜像ID/digest。参见`deployment/README.md`配置17CPU以上外层预算和启用egress。task的域名屏蔽加agent搜索禁用是尽力降低公开X/旧结果检索风险，不能证明历史公开数据完全保密。


原生Harbor终验仍调用本task的900秒入口，形成截止源码的不回流900秒记录；5400秒档由独立工具随后运行，不会因改变过程反馈时限而自动执行。两者都必须绑定同一截止产物。

离线最终评测：

```sh
python tools/freeze_candidate.py --candidate /absolute/solver.py --output-dir /private/frozen
docker run --rm --network none --cpus 15 --memory 128g \
  -v /private/frozen:/frozen:ro -v /private/reports:/reports \
  rte-abc-x15-verifier:1 python /tests/offline/final_evaluate.py \
  --candidate /frozen/solver.py --freeze-receipt /frozen/freeze-receipt.json \
  --manifest /tests/data/manifest.json --output /reports/final.json
```

该工具要求Linux root及seccomp沙箱，不提供不安全最终评分开关。报告只能由实验控制者保管，禁止挂载给仍在运行的开发agent。当前完成的是任务包与可审核协议准备；完整ABC/X算法运行、15CPU沙箱与内存峰值校准、真实egress有效性、基线可行性均须另行验收后才能称为可批量稳定运行。

已确认B15原始JSON约4GB；常规`json.load`展开后的内存可能远大于文件大小。开发32GiB与每候选8GiB地址空间均是待校准试配，继承starter可能无法处理最大实例；这属于明确的验收阻塞项，不能用TLE/RE掩盖资源不充分。
