// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {ExposureOracle} from "../src/ExposureOracle.sol";
import {MockExchange} from "../src/MockExchange.sol";

/// The team-publisher rules: the owner approves wallets that may post prices/tiers and list
/// stocks; only the owner can change that list or hand over ownership.
contract PublishersTest is Test {
    ExposureOracle oracle;
    MockExchange exchange;
    address owner = address(this);
    address friend = makeAddr("friend");
    address stranger = makeAddr("stranger");
    address newOwner = makeAddr("newOwner");
    bytes32 constant NVDA = bytes32("NVDA");
    bytes32 constant OIL = bytes32("oil");

    event PublisherSet(address indexed account, bool allowed);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    function setUp() public {
        oracle = new ExposureOracle();
        exchange = new MockExchange(oracle);
    }

    function test_owner_can_always_publish() public {
        assertTrue(oracle.canPublish(owner));
        assertTrue(exchange.canPublish(owner));
        oracle.postPrice(NVDA, 1e8);
        exchange.listStock("NVIDIA", "NVDA");
    }

    function test_approved_friend_can_post_and_list() public {
        vm.expectEmit(true, false, false, true, address(oracle));
        emit PublisherSet(friend, true);
        oracle.setPublisher(friend, true);
        exchange.setPublisher(friend, true);
        assertTrue(oracle.isPublisher(friend) && oracle.canPublish(friend));

        vm.startPrank(friend);
        oracle.postPrice(NVDA, 18_742_000_000);
        oracle.postExposure(NVDA, OIL, ExposureOracle.Tier.Limited, bytes32("b"), bytes32("s"));
        exchange.listStock("NVIDIA", "NVDA");
        vm.stopPrank();

        (uint256 price,) = oracle.priceOf(NVDA);
        assertEq(price, 18_742_000_000);
        assertEq(uint256(oracle.tierOf(NVDA, OIL)), uint256(ExposureOracle.Tier.Limited));
        assertTrue(exchange.stockOf(NVDA) != address(0));
    }

    function test_removed_publisher_is_locked_out() public {
        oracle.setPublisher(friend, true);
        oracle.setPublisher(friend, false);
        assertFalse(oracle.canPublish(friend));
        vm.prank(friend);
        vm.expectRevert("Oracle: caller is not a publisher");
        oracle.postPrice(NVDA, 1e8);
    }

    function test_approvals_are_per_contract() public {
        oracle.setPublisher(friend, true); // oracle only
        vm.prank(friend);
        vm.expectRevert("Exchange: caller is not a publisher");
        exchange.listStock("NVIDIA", "NVDA");
    }

    function test_only_owner_manages_publishers() public {
        oracle.setPublisher(friend, true);
        exchange.setPublisher(friend, true);
        vm.startPrank(friend); // a publisher can't add others or promote itself
        vm.expectRevert("Oracle: caller is not the owner");
        oracle.setPublisher(stranger, true);
        vm.expectRevert("Exchange: caller is not the owner");
        exchange.setPublisher(stranger, true);
        vm.expectRevert("Oracle: caller is not the owner");
        oracle.transferOwnership(friend);
        vm.expectRevert("Exchange: caller is not the owner");
        exchange.transferOwnership(friend);
        vm.stopPrank();
    }

    function test_zero_address_rejected() public {
        vm.expectRevert("Oracle: publisher is the zero address");
        oracle.setPublisher(address(0), true);
        vm.expectRevert("Exchange: publisher is the zero address");
        exchange.setPublisher(address(0), true);
        vm.expectRevert("Exchange: new owner is the zero address");
        exchange.transferOwnership(address(0));
    }

    function test_exchange_ownership_transfer() public {
        vm.expectEmit(true, true, false, false, address(exchange));
        emit OwnershipTransferred(owner, newOwner);
        exchange.transferOwnership(newOwner);
        assertEq(exchange.owner(), newOwner);
        vm.expectRevert("Exchange: caller is not a publisher"); // the old owner is now nobody special
        exchange.listStock("NVIDIA", "NVDA");
        vm.prank(newOwner);
        exchange.listStock("NVIDIA", "NVDA");
    }

    function test_publishers_survive_an_ownership_handover() public {
        oracle.setPublisher(friend, true);
        oracle.transferOwnership(newOwner);
        vm.prank(friend);
        oracle.postPrice(NVDA, 1e8); // still approved
        vm.prank(newOwner);
        oracle.setPublisher(friend, false); // and the new owner can remove them
        assertFalse(oracle.canPublish(friend));
    }
}
