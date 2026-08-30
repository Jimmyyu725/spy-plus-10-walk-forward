# 冻结评价协议

## 判定边界

本轮历史模拟使用同一个不可变代码提交运行两次：基础成本一次，双倍滑点一次。预热期固定为 `2012-01-01` 至 `2015-01-01`，允许成交及评分区间固定为 `2015-01-02` 至 `2026-08-28`，初始资金固定为 `1,000,000 USD`。

基础成本回测决定收益目标是否通过。每个自然年分别要求：

`策略回报 >= SPY 含分红总回报 + 0.10`

其中 `0.10` 是 10 个百分点。2026 年按截至 `2026-08-28` 的部分年份计算。双倍滑点是必须完成的敏感性测试，其数据和安全门禁必须可验证；它的年度收益不会事后改变基础成本回测的目标定义。

结论只能由结构化结果生成：

- `PASS`：基础成本的所有年度均通过，数据、时间因果、成本、风险和独立复算门禁完整；压力测试也具备完整数据和安全证据。
- `FAIL`：可验证的基础成本年度至少一个未达标，或者任一必须满足的风险/安全限制被违反。
- `UNVERIFIED`：回测未完成、许可不足、证据未保存、少于十个严格时间样本，或独立复算不能在 `0.01` 个百分点内对齐。

第一次正式结果出现后，不允许根据年度结果修改参数、删年份、换基准或覆盖结果。任何后续经济假设只能成为保留本轮结果的新版本。

## 唯一允许的运行参数

基础成本：

```text
evaluation_mode=frozen-evaluation
slippage_multiplier=1
evaluation_run_label=base
```

双倍滑点：

```text
evaluation_mode=frozen-evaluation
slippage_multiplier=2
evaluation_run_label=double
```

运行标签和滑点不匹配、缺少参数、日期变化、`formal_evaluation` 关闭或 `live_trading` 开启都会在初始化阶段失败关闭。

## 云端证据

回测结束时，算法只写一次 gzip JSON，键名为：

```text
<project-id>/frozen-evaluation-v1/<base|double>-<algorithm-id>.json.gz
```

每份文件至少包含：

- 项目、算法、模式、日期、标签和滑点参数；
- 每个共同交易日的策略权益与独立 SPY 总回报权益；
- 累计费用、保证金、实际总敞口、回撤、预测 Beta 和风险贡献；
- 每日所有非零持仓的代码、资产类型、数量、价格和持仓价值；
- 期货/期权信号的 `data_cutoff < signal_time < order_time < fill_time` 审计样本；
- 股票与期权数据许可状态以及所有不可逆门禁失败代码。

Object Store 键包含算法 ID，不能覆盖另一正式运行的文件。项目不会删除 Object Store 对象。

## 独立下载与复算

Atlas 使用 QuantConnect API 的时间戳哈希认证，只读获取回测元数据、全部分页订单、全部分页已平仓交易和指定 Object Store 文件。凭据只从用户级 `~/.lean/credentials` 读取，不写入报告或命令输出。

下载命令模板：

```bash
python scripts/fetch_quantconnect_evidence.py \
  --project-id 35858890 \
  --backtest-id <backtest-id> \
  --organization-id <organization-id> \
  --output-dir docs/evidence/frozen-evaluation-v1/<base|double>
```

独立复算命令：

```bash
python scripts/verify_frozen_evaluation.py \
  docs/evidence/frozen-evaluation-v1/<base|double>
```

复算器不导入云端策略的 `metrics.py`，而是从每日权益重新实现年度收益、SPY+10 门槛和最大回撤。它逐年比对云端结构化统计，绝对误差不得大于 `0.0001` 回报单位，也就是 `0.01` 个百分点。

## 非实盘边界

本协议只授权 QuantConnect Cloud 历史回测和证据读取。代码没有实时节点、券商账户或实盘权限；不会连接 Webull、Robinhood、IBKR，也不会发出真实订单。购买额外数据、存储或计算资源仍需用户单独确认。
