"""The committed Monad deployment record and the docs must agree, so nobody copies a wrong address."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECORD = json.loads((ROOT / "deployments" / "monad_testnet.json").read_text())


def test_record_is_complete_and_consistent():
    assert RECORD["chain_id"] == 10143
    assert set(RECORD["contracts"]) == {"ExposureOracle", "MockExchange", "ThemeFundFactory", "MockUSDC"}
    approved = {(a["contract"], a["publisher"]) for a in RECORD["publisher_approvals"]}
    for p in RECORD["publishers"]:  # every publisher approved on both contracts
        assert ("ExposureOracle", p) in approved and ("MockExchange", p) in approved
    assert {t["contract"] for t in RECORD["ownership_transfers"]} == {"ExposureOracle", "MockExchange"}
    assert all(t["new_owner"] == RECORD["owner"] for t in RECORD["ownership_transfers"])
    assert RECORD["env"]["FACTORY_ADDRESS"] == RECORD["contracts"]["ThemeFundFactory"]["address"]


def test_docs_quote_the_same_addresses():
    readme = (ROOT / "README.md").read_text()
    claude = (ROOT / "CLAUDE.md").read_text()
    example = (ROOT / ".env.example").read_text()
    for c in RECORD["contracts"].values():
        assert c["address"] in readme
    for name in ("ThemeFundFactory", "ExposureOracle"):
        addr = RECORD["contracts"][name]["address"]
        assert addr in claude and addr in example
    assert RECORD["owner"] in readme and all(p in readme for p in RECORD["publishers"])
