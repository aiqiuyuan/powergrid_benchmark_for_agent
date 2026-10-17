# v2可移植验证

仓库根目录运行：

```sh
python -m pip install numpy==2.2.6 scipy==1.15.3 ijson==3.4.0.post0
python -m unittest discover -s task-packages/rte-maintenance-abc-x15-v2/verification -v
```

合成测试不下载能源数据、不使用模型、Docker或私有框架。包括0／1／14／15可行的固定分母排序、跨覆盖优先、同覆盖质量单调、非法或缺失面板／非有限值拒绝、部分有效目标保留、失败目标null、完整15例白名单JSON与16KiB上限、RSS单位、基础设施错误和候选失败区分、原checker／starter／数据来源锁、同一冻结源码与双预算工具。

微型官方schema实例实际经过候选进程、原checker和并行runner；本地采用secure=False。安全命令构造mock和seccomp静态检查只验证策略没有意外移除，不证明目标内核已执行沙箱。`probe_linux_sandbox.py`用于目标Linux真实降权／seccomp探针，源码沿用v1；本包不借用v1运行记录宣称v2验收成功。

完整v2批次仍需独立源码锁、真实n=0／1微型生命周期、可读的完整JSON、反馈计数、X不进入开发端，以及服务器镜像／磁盘／内存资源凭据。实际状态由批次验收和提交报告记录。
