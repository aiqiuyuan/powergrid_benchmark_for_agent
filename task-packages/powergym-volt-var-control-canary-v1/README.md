# PowerGym 34Bus energy-neutral canary v1

本包用于先跑通真实仿真与n=0/1实验生命周期，开发时限600秒、每档一次。
它不代表原五任务或12小时正式比较的扩展验收。完整合同见
[instruction.md](instruction.md)和[problem.md](problem.md)。

准备与执行（仓库Python≥3.11，仿真Python3.12）：

```sh
python prepare.py --source /trusted/powergym-verified --output tests/data
python stage.py --wheelhouse /trusted/powergym-wheels-linux-amd64
docker build -f images/Dockerfile -t powergym-canary-runtime:1 .
docker build -f tests/Dockerfile -t powergym-canary-verifier:1 tests
docker build -t powergym-canary-development:1 environment
mkdir -p verification/output
docker run --rm --network none \
  -v "$PWD/environment/app/submission:/app/submission:ro" \
  -v "$PWD/verification/output:/logs/verifier" powergym-canary-verifier:1 \
  /tests/test.sh
```

镜像部署时记录实际base image digest、Linux wheel/软件清单和最终镜像digest。
源码与原CSV摘要在[source-lock.json](source-lock.json)，准备工具拒绝修改过的
任一复制资产并生成`tests/data/data-lock.json`。完整数据目录在Git忽略范围，不进入
开发镜像；远端上传须保留其root-only权限。

实际数值与隔离验收：

```sh
python verification/validate_runtime.py --data tests/data --output /trusted/local-receipt.json
# Linux verifier image, as root, using compiled seccomp launcher:
python verification/validate_runtime.py --data tests/data --secure --output /trusted/linux-receipt.json
# Equivalent inside the built verifier image:
# python /tests/_validation/validate_runtime.py --data /tests/data --secure
```

不带`--secure`仅证实真实潮流与评分，不构成隔离验收。检查覆盖完整24步、hold+idle、
电压规则、耗尽电池拒绝、异常动作、实际tap档位、显式负荷时序、独立进程并行重放。
平台的计n/超额拒绝/截止唯一产物/终评回流隔离须另由实验启动验收记录覆盖。

上游代码/资产来自Siemens PowerGym提交
`c9fc6d8357308a1f2bd2389474b56089c2a6bd78`，准备副本保留原MIT LICENSE。
继承feeder和原始负荷CSV来源的完整独立许可仍是正式release的待验收项。
