NAME="TenP"
DESC="10 参数压测"
PARAMS={"p1": 1, "p2": 2, "p3": 3, "p4": 4, "p5": 5, "p6": 6, "p7": 7, "p8": 8, "p9": 9, "p10": 10}
def main(params, ohlcv):
    n=int(params.get("p1",1))
    return [None]*len(ohlcv) if n<2 else [float(i) for i in range(len(ohlcv))]
