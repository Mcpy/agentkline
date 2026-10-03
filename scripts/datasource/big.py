NAME="六万"
CAPS={"backfill": False, "symbols": False, "ticker": False}
IDENTITY=["symbol"]
def main(params):
    return [{"timestamp": 1600000000000+i*60000, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0} for i in range(60000)]
