// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {ExposureOracle} from "../src/ExposureOracle.sol";
import {MockExchange} from "../src/MockExchange.sol";
import {MockUSDC} from "../src/MockUSDC.sol";
import {MockStock} from "../src/MockStock.sol";

/// Tests for the oracle, the test tokens and the pretend exchange (Phase 7a).
contract Phase7aTest is Test {
    ExposureOracle oracle;
    MockExchange exchange;
    MockUSDC usdc;
    MockStock nvda;

    address alice = makeAddr("alice");
    address stranger = makeAddr("stranger");

    bytes32 constant NVDA = bytes32("NVDA");
    bytes32 constant XOM = bytes32("XOM");
    bytes32 constant OIL = bytes32("oil");
    uint256 constant NVDA_PRICE = 200e8; // $200.00

    function setUp() public {
        vm.warp(1_800_000_000); // a realistic clock so "7 days ago" is a valid time
        oracle = new ExposureOracle();
        exchange = new MockExchange(oracle);
        usdc = exchange.usdc();
        nvda = MockStock(exchange.listStock("NVIDIA Corporation", "NVDA"));
        oracle.postPrice(NVDA, NVDA_PRICE);
    }

    // ───────────── oracle ─────────────

    function test_oracle_stores_price_and_timestamp() public view {
        (uint256 price, uint256 timestamp) = oracle.priceOf(NVDA);
        assertEq(price, NVDA_PRICE);
        assertEq(timestamp, block.timestamp);
    }

    function test_oracle_unknown_ticker_reads_zero() public view {
        (uint256 price, uint256 timestamp) = oracle.priceOf(XOM);
        assertEq(price, 0);
        assertEq(timestamp, 0);
        assertEq(uint8(oracle.tierOf(XOM, OIL)), uint8(ExposureOracle.Tier.Unposted));
    }

    function test_oracle_stores_exposure_with_hashes() public {
        bytes32 baseline = keccak256("prices");
        bytes32 stats = keccak256("stats");
        oracle.postExposure(XOM, OIL, ExposureOracle.Tier.High, baseline, stats);

        ExposureOracle.Exposure memory e = oracle.exposureOf(XOM, OIL);
        assertEq(uint8(e.tier), uint8(ExposureOracle.Tier.High));
        assertEq(e.baselineHash, baseline);
        assertEq(e.statsHash, stats);
        assertEq(e.timestamp, block.timestamp);
        assertEq(uint8(oracle.tierOf(XOM, OIL)), uint8(ExposureOracle.Tier.High));
        // A different theme for the same stock is untouched.
        assertEq(uint8(oracle.tierOf(XOM, bytes32("ai"))), uint8(ExposureOracle.Tier.Unposted));
    }

    function test_oracle_batch_posting() public {
        bytes32[] memory tickers = new bytes32[](2);
        uint256[] memory prices = new uint256[](2);
        (tickers[0], prices[0]) = (NVDA, 210e8);
        (tickers[1], prices[1]) = (XOM, 109.05e8);
        oracle.postPrices(tickers, prices);
        (uint256 p0,) = oracle.priceOf(NVDA);
        (uint256 p1,) = oracle.priceOf(XOM);
        assertEq(p0, 210e8);
        assertEq(p1, 109.05e8);

        bytes32[] memory themes = new bytes32[](2);
        ExposureOracle.Tier[] memory tiers = new ExposureOracle.Tier[](2);
        bytes32[] memory hashes = new bytes32[](2);
        (themes[0], tiers[0]) = (OIL, ExposureOracle.Tier.Limited);
        (themes[1], tiers[1]) = (OIL, ExposureOracle.Tier.High);
        oracle.postExposures(tickers, themes, tiers, hashes, hashes);
        assertEq(uint8(oracle.tierOf(NVDA, OIL)), uint8(ExposureOracle.Tier.Limited));
        assertEq(uint8(oracle.tierOf(XOM, OIL)), uint8(ExposureOracle.Tier.High));
    }

    function test_oracle_rejects_bad_posts() public {
        vm.expectRevert("Oracle: price must be positive");
        oracle.postPrice(NVDA, 0);

        vm.expectRevert("Oracle: empty ticker");
        oracle.postPrice(bytes32(0), 1e8);

        vm.expectRevert("Oracle: tier must be one of the five tiers");
        oracle.postExposure(XOM, OIL, ExposureOracle.Tier.Unposted, 0, 0);

        bytes32[] memory tickers = new bytes32[](2);
        uint256[] memory prices = new uint256[](1);
        vm.expectRevert("Oracle: list lengths differ");
        oracle.postPrices(tickers, prices);
    }

    function test_oracle_only_owner_can_post() public {
        vm.startPrank(stranger);
        vm.expectRevert("Oracle: caller is not a publisher");
        oracle.postPrice(NVDA, 1e8);
        vm.expectRevert("Oracle: caller is not a publisher");
        oracle.postExposure(XOM, OIL, ExposureOracle.Tier.High, 0, 0);
        vm.stopPrank();
    }

    function test_oracle_ownership_transfer() public {
        oracle.transferOwnership(alice);
        vm.expectRevert("Oracle: caller is not a publisher");
        oracle.postPrice(NVDA, 1e8);
        vm.prank(alice);
        oracle.postPrice(NVDA, 1e8);
    }

    // ───────────── tokens ─────────────

    function test_usdc_faucet_and_decimals() public {
        assertEq(usdc.decimals(), 6);
        vm.prank(alice);
        usdc.faucet();
        assertEq(usdc.balanceOf(alice), 10_000e6);
    }

    function test_only_exchange_can_mint_or_burn() public {
        vm.startPrank(stranger);
        vm.expectRevert("MockUSDC: only the exchange can mint or burn");
        usdc.mint(stranger, 1e6);
        vm.expectRevert("MockUSDC: only the exchange can mint or burn");
        usdc.burn(alice, 1e6);
        vm.expectRevert("MockStock: only the exchange can mint or burn");
        nvda.mint(stranger, 1e18);
        vm.expectRevert("MockStock: only the exchange can mint or burn");
        nvda.burn(alice, 1e18);
        vm.stopPrank();
    }

    function test_stock_token_details() public view {
        assertEq(nvda.decimals(), 18);
        assertEq(nvda.symbol(), "NVDA");
        assertEq(nvda.ticker(), NVDA);
        assertEq(exchange.stockOf(NVDA), address(nvda));
        assertEq(exchange.allStocks().length, 1);
    }

    function test_token_transfer_and_allowance() public {
        vm.startPrank(alice);
        usdc.faucet();
        usdc.transfer(stranger, 100e6);
        usdc.approve(stranger, 50e6);
        vm.expectRevert("Token: balance too low");
        usdc.transfer(stranger, 1_000_000e6);
        vm.stopPrank();

        vm.startPrank(stranger);
        usdc.transferFrom(alice, stranger, 50e6);
        vm.expectRevert("Token: allowance too low");
        usdc.transferFrom(alice, stranger, 1);
        vm.stopPrank();
        assertEq(usdc.balanceOf(stranger), 150e6);
    }

    // ───────────── exchange ─────────────

    function test_buy_then_sell_round_trip() public {
        vm.startPrank(alice);
        usdc.faucet();

        // $1,000 at $200 a share = exactly 5 shares.
        uint256 qty = exchange.buy(address(nvda), 1_000e6);
        assertEq(qty, 5e18);
        assertEq(nvda.balanceOf(alice), 5e18);
        assertEq(usdc.balanceOf(alice), 9_000e6);

        uint256 usdcBack = exchange.sell(address(nvda), 5e18);
        assertEq(usdcBack, 1_000e6);
        assertEq(usdc.balanceOf(alice), 10_000e6);
        assertEq(nvda.totalSupply(), 0);
        vm.stopPrank();
    }

    function test_sell_after_price_rise_pays_more() public {
        vm.startPrank(alice);
        usdc.faucet();
        exchange.buy(address(nvda), 1_000e6);
        vm.stopPrank();

        oracle.postPrice(NVDA, 250e8);
        assertEq(exchange.quoteSell(address(nvda), 5e18), 1_250e6);
    }

    function test_quotes_match_trades() public {
        vm.startPrank(alice);
        usdc.faucet();
        uint256 quoted = exchange.quoteBuy(address(nvda), 333e6);
        assertEq(exchange.buy(address(nvda), 333e6), quoted);
        vm.stopPrank();
    }

    function test_listing_rules() public {
        vm.expectRevert("Exchange: ticker already listed");
        exchange.listStock("Duplicate", "NVDA");

        vm.prank(stranger);
        vm.expectRevert("Exchange: caller is not a publisher");
        exchange.listStock("Exxon Mobil Corporation", "XOM");
    }

    function test_trade_reverts_for_unlisted_stock() public {
        vm.prank(alice);
        vm.expectRevert("Exchange: stock not listed");
        exchange.buy(address(0xBEEF), 1e6);
    }

    function test_trade_reverts_when_no_price() public {
        address xom = exchange.listStock("Exxon Mobil Corporation", "XOM");
        vm.startPrank(alice);
        usdc.faucet();
        vm.expectRevert("Exchange: no price posted");
        exchange.buy(xom, 100e6);
        vm.stopPrank();
    }

    function test_trade_reverts_when_price_is_stale() public {
        vm.startPrank(alice);
        usdc.faucet();
        exchange.buy(address(nvda), 1_000e6);

        // Exactly 7 days old is still fine.
        vm.warp(block.timestamp + 7 days);
        exchange.buy(address(nvda), 100e6);

        // One second past 7 days is refused, for buying and for selling.
        vm.warp(block.timestamp + 1);
        vm.expectRevert("Exchange: price is stale");
        exchange.buy(address(nvda), 100e6);
        vm.expectRevert("Exchange: price is stale");
        exchange.sell(address(nvda), 1e18);
        vm.stopPrank();

        // A fresh price makes it tradable again.
        oracle.postPrice(NVDA, NVDA_PRICE);
        vm.prank(alice);
        exchange.sell(address(nvda), 1e18);
    }

    function test_trade_reverts_for_dust_and_overspend() public {
        vm.startPrank(alice);
        usdc.faucet();
        vm.expectRevert("Exchange: amount too small");
        exchange.buy(address(nvda), 0);
        vm.expectRevert("Exchange: amount too small");
        exchange.sell(address(nvda), 0);
        vm.expectRevert("Token: balance too low");
        exchange.buy(address(nvda), 10_001e6);
        vm.expectRevert("Token: balance too low");
        exchange.sell(address(nvda), 1e18);
        vm.stopPrank();
    }

    /// Any buy followed by selling everything returns the money, minus at most 1 unit of rounding.
    function testFuzz_round_trip_never_creates_money(uint256 usdcAmount, uint256 price) public {
        usdcAmount = bound(usdcAmount, 1e6, 10_000e6);
        price = bound(price, 1e6, 1_000_000e8); // $0.01 to $1,000,000 a share
        oracle.postPrice(NVDA, price);

        vm.startPrank(alice);
        usdc.faucet();
        uint256 qty = exchange.buy(address(nvda), usdcAmount);
        uint256 back = exchange.sell(address(nvda), qty);
        vm.stopPrank();

        assertLe(back, usdcAmount);
        assertApproxEqAbs(back, usdcAmount, 1);
    }
}
