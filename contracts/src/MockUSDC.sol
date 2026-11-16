// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {SimpleERC20} from "./SimpleERC20.sol";

/// @title MockUSDC
/// @notice Test dollars with 6 decimals, like real USDC (1 dollar = 1_000_000 units).
///         Anyone can call faucet() for free test dollars. Apart from the faucet, only
///         the MockExchange can create or destroy them, which is how it simulates trades.
///         Testnet only: these have no value.
contract MockUSDC is SimpleERC20 {
    uint256 public constant FAUCET_AMOUNT = 10_000e6; // $10,000 per call

    address public immutable exchange;

    modifier onlyExchange() {
        require(msg.sender == exchange, "MockUSDC: only the exchange can mint or burn");
        _;
    }

    constructor(address exchange_) SimpleERC20("Mock USD Coin", "mUSDC", 6) {
        exchange = exchange_;
    }

    /// Free test dollars for whoever calls.
    function faucet() external {
        _mint(msg.sender, FAUCET_AMOUNT);
    }

    function mint(address to, uint256 amount) external onlyExchange {
        _mint(to, amount);
    }

    function burn(address from, uint256 amount) external onlyExchange {
        _burn(from, amount);
    }
}
