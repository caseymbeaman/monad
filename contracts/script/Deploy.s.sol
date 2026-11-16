// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Script, console} from "forge-std/Script.sol";
import {ExposureOracle} from "../src/ExposureOracle.sol";
import {MockExchange} from "../src/MockExchange.sol";
import {ThemeFundFactory} from "../src/ThemeFundFactory.sol";

/// Deploys the three long-lived contracts to Monad testnet. Run from contracts/ with the
/// deployer wallet stored in a Foundry keystore (never paste a private key):
///
///   forge script script/Deploy.s.sol --rpc-url monad --account <keystore-name> --broadcast
///
/// Then copy the printed ORACLE_ADDRESS and FACTORY_ADDRESS into .env.
/// The deployer becomes the owner of the oracle (can post results) and of the exchange
/// (can list stocks). Stocks are listed and results posted afterwards by chain/publish.py.
///
/// Optional: PUBLISHERS=0xabc...,0xdef... (comma-separated public addresses) approves team
/// wallets to post results and list stocks too, in the same run. Ownership can be handed to
/// another wallet later with transferOwnership on both the oracle and the exchange.
contract Deploy is Script {
    function run() external {
        address[] memory publishers = vm.envOr("PUBLISHERS", ",", new address[](0));

        vm.startBroadcast();
        ExposureOracle oracle = new ExposureOracle();
        MockExchange exchange = new MockExchange(oracle);
        ThemeFundFactory factory = new ThemeFundFactory(exchange);
        for (uint256 i = 0; i < publishers.length; i++) {
            oracle.setPublisher(publishers[i], true);
            exchange.setPublisher(publishers[i], true);
        }
        vm.stopBroadcast();

        for (uint256 i = 0; i < publishers.length; i++) {
            console.log("PUBLISHER=%s", publishers[i]);
        }

        console.log("ORACLE_ADDRESS=%s", address(oracle));
        console.log("EXCHANGE_ADDRESS=%s", address(exchange));
        console.log("USDC_ADDRESS=%s", address(exchange.usdc()));
        console.log("FACTORY_ADDRESS=%s", address(factory));
    }
}
