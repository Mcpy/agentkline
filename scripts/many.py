# 测试用：10 个可调参数的指标（验证命名截断 + 弹窗双列/滚动）
PARAMS = {"p1": 1, "p2": 2, "p3": 3, "p4": 4, "p5": 5,
          "p6": 6, "p7": 7, "p8": 8, "p9": 9, "p10": 10}


def main(params, ohlcv):
    n = int(params.get("p1", 1)) + int(params.get("p2", 2))
    closes = [b["close"] for b in ohlcv]
    out = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        out[i] = round(sum(closes[i - n + 1:i + 1]) / n, 2)
    return out
