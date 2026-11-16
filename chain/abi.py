"""Contract interfaces (ABIs) for the Phase 7 contracts: just the functions the Python side calls.

Written out by hand so the Python code works without running `forge build` first. If a contract's
function changes in contracts/src/, change it here too (tests/test_publish.py checks they still match
when the compiled contracts are available).
"""

_EXPOSURE = {
    "type": "tuple",
    "components": [
        {"name": "tier", "type": "uint8"},
        {"name": "baselineHash", "type": "bytes32"},
        {"name": "statsHash", "type": "bytes32"},
        {"name": "timestamp", "type": "uint256"},
    ],
}


def _fn(name: str, inputs: list[tuple[str, str]], outputs: list, mutability: str = "view") -> dict:
    return {
        "type": "function",
        "name": name,
        "stateMutability": mutability,
        "inputs": [{"name": n, "type": t} for n, t in inputs],
        "outputs": [o if isinstance(o, dict) else {"name": "", "type": o} for o in outputs],
    }


_RULES = {
    "name": "rules",
    "type": "tuple[]",
    "components": [
        {"name": "theme", "type": "bytes32"},
        {"name": "label", "type": "string"},
        {"name": "kind", "type": "uint8"},  # 0 = Want, 1 = Avoid
        {"name": "minWeightBps", "type": "uint16"},
    ],
}

FACTORY_ABI = [
    _fn("exchange", [], ["address"]),
    _fn("allFunds", [], ["address[]"]),
    {
        "type": "function",
        "name": "createFund",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "name", "type": "string"},
            {"name": "symbol", "type": "string"},
            {"name": "stocks", "type": "address[]"},
            {"name": "weights", "type": "uint16[]"},
            _RULES,
        ],
        "outputs": [{"name": "fund", "type": "address"}],
    },
    {
        "type": "event",
        "name": "FundCreated",
        "anonymous": False,
        "inputs": [
            {"name": "fund", "type": "address", "indexed": True},
            {"name": "manager", "type": "address", "indexed": True},
            {"name": "name", "type": "string", "indexed": False},
            {"name": "symbol", "type": "string", "indexed": False},
        ],
    },
]

FUND_ABI = [
    _fn("name", [], ["string"]),
    _fn("symbol", [], ["string"]),
    _fn("manager", [], ["address"]),
    _fn("totalSupply", [], ["uint256"]),
    _fn("balanceOf", [("account", "address")], ["uint256"]),
    _fn("nav", [], ["uint256"]),
    _fn("navPerShare", [], ["uint256"]),
    _fn("basket", [], ["address[]", "uint16[]"]),
    _fn("isCompliant", [], ["bool", "string"]),
    _fn("checkMandate", [("stocks_", "address[]"), ("weights_", "uint16[]")], ["bool", "string"]),
    _fn("deposit", [("usdcAmount", "uint256")], ["uint256"], "nonpayable"),
    _fn("redeem", [("shares", "uint256")], ["uint256"], "nonpayable"),
    _fn("addHolding", [("stock", "address"), ("weightBps", "uint16")], [], "nonpayable"),
]

USDC_ABI = [
    _fn("balanceOf", [("account", "address")], ["uint256"]),
    _fn("allowance", [("owner", "address"), ("spender", "address")], ["uint256"]),
    _fn("faucet", [], [], "nonpayable"),
    _fn("approve", [("spender", "address"), ("amount", "uint256")], ["bool"], "nonpayable"),
]

EXCHANGE_ABI = [
    _fn("oracle", [], ["address"]),
    _fn("usdc", [], ["address"]),
    _fn("owner", [], ["address"]),
    _fn("stockOf", [("ticker", "bytes32")], ["address"]),
    _fn("allStocks", [], ["address[]"]),
    _fn("listStock", [("name", "string"), ("symbol", "string")], ["address"], "nonpayable"),
    _fn("isPublisher", [("account", "address")], ["bool"]),
    _fn("canPublish", [("account", "address")], ["bool"]),
    _fn("setPublisher", [("account", "address"), ("allowed", "bool")], [], "nonpayable"),
    _fn("transferOwnership", [("newOwner", "address")], [], "nonpayable"),
]

ORACLE_ABI = [
    _fn("owner", [], ["address"]),
    _fn("isPublisher", [("account", "address")], ["bool"]),
    _fn("canPublish", [("account", "address")], ["bool"]),
    _fn("setPublisher", [("account", "address"), ("allowed", "bool")], [], "nonpayable"),
    _fn("transferOwnership", [("newOwner", "address")], [], "nonpayable"),
    _fn("priceOf", [("ticker", "bytes32")], ["uint256", "uint256"]),
    _fn("tierOf", [("ticker", "bytes32"), ("theme", "bytes32")], ["uint8"]),
    _fn("exposureOf", [("ticker", "bytes32"), ("theme", "bytes32")], [_EXPOSURE]),
    _fn("postPrices", [("tickers", "bytes32[]"), ("prices", "uint256[]")], [], "nonpayable"),
    _fn(
        "postExposures",
        [
            ("tickers", "bytes32[]"),
            ("themes", "bytes32[]"),
            ("tiers", "uint8[]"),
            ("baselineHashes", "bytes32[]"),
            ("statsHashes", "bytes32[]"),
        ],
        [],
        "nonpayable",
    ),
]
