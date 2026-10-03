NAME="测试符号源"
DESC="静态符号表(e2e 自给)"
PARAMS={"symbol":"X1"}
CAPS={"backfill": False, "symbols": True, "ticker": False}
IDENTITY=["symbol"]
SYMS=[{"symbol":"AAA/USD","display":"AAA 现货"},{"symbol":"AAC/USD","display":"AAC 现货"}]
def main(params):
    return []
def list_symbols(query=""):
    q=(query or "").upper()
    return [x for x in SYMS if not q or q in x["symbol"]]
