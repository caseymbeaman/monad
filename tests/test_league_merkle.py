"""The League's Merkle pool (chain/league.py): every pool stock has a proof that reaches the root, the same check
FundLeague._inPool makes; a stock outside the pool has none."""
import pytest
from web3 import Web3

from chain.league import merkle_proof, merkle_root
from chain.publish import to_bytes32


def _verify(root: bytes, ticker: str, proof: list[bytes]) -> bool:
    h = Web3.keccak(to_bytes32(ticker))
    for s in proof:
        h = Web3.keccak(h + s) if h < s else Web3.keccak(s + h)
    return h == root


@pytest.mark.parametrize("n", [3, 4, 5, 7, 60, 666])
def test_every_pool_stock_proves_membership(n):
    tickers = [f"S{i}" for i in range(n)]
    root = merkle_root(tickers)
    assert all(_verify(root, t, merkle_proof(tickers, t)) for t in tickers)


def test_outsider_and_wrong_proof_fail():
    tickers = [f"S{i}" for i in range(666)]
    root = merkle_root(tickers)
    assert not _verify(root, "TSLA", merkle_proof(tickers, "S1"))
    assert not _verify(root, "S2", merkle_proof(tickers, "S1"))
    with pytest.raises(ValueError):
        merkle_proof(tickers, "TSLA")
    assert len(merkle_proof(tickers, "S0")) <= 10  # 666 stocks: at most 10 hashes per proof
