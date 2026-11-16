// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {ThemeFund} from "./ThemeFund.sol";
import {MockExchange} from "./MockExchange.sol";

/// @title ThemeFundFactory
/// @notice The "Launch fund" button. One call creates a new ThemeFund with its name,
///         token symbol, basket and mandate rules. Whoever calls it becomes that fund's
///         manager. The launch fails if the starting basket breaks the fund's own rules.
contract ThemeFundFactory {
    MockExchange public immutable exchange;
    address[] private _funds;

    event FundCreated(address indexed fund, address indexed manager, string name, string symbol);

    constructor(MockExchange exchange_) {
        exchange = exchange_;
    }

    function createFund(
        string memory name,
        string memory symbol,
        address[] memory stocks,
        uint16[] memory weights,
        ThemeFund.Rule[] memory rules
    ) external returns (address fund) {
        fund = address(new ThemeFund(name, symbol, msg.sender, exchange, stocks, weights, rules));
        _funds.push(fund);
        emit FundCreated(fund, msg.sender, name, symbol);
    }

    function allFunds() external view returns (address[] memory) {
        return _funds;
    }

    function fundCount() external view returns (uint256) {
        return _funds.length;
    }
}
