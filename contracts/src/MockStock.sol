// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {SimpleERC20} from "./SimpleERC20.sol";

/// @title MockStock
/// @notice A simulated share of one company (one contract per ticker), 18 decimals, so
///         1 whole share = 1e18 units and fractions are allowed. Real shares can't live
///         on Monad, so these stand in for them on testnet. Only the MockExchange can
///         create or destroy them.
contract MockStock is SimpleERC20 {
    address public immutable exchange;

    /// The ticker packed into bytes32, e.g. bytes32("NVDA"): the key used in ExposureOracle.
    bytes32 public immutable ticker;

    modifier onlyExchange() {
        require(msg.sender == exchange, "MockStock: only the exchange can mint or burn");
        _;
    }

    constructor(string memory name_, string memory symbol_, address exchange_) SimpleERC20(name_, symbol_, 18) {
        require(bytes(symbol_).length > 0 && bytes(symbol_).length <= 32, "MockStock: ticker must be 1-32 characters");
        exchange = exchange_;
        ticker = bytes32(bytes(symbol_));
    }

    function mint(address to, uint256 amount) external onlyExchange {
        _mint(to, amount);
    }

    function burn(address from, uint256 amount) external onlyExchange {
        _burn(from, amount);
    }
}
