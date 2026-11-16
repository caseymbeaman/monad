// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {ExposureOracle} from "../src/ExposureOracle.sol";
import {MockExchange} from "../src/MockExchange.sol";
import {MockUSDC} from "../src/MockUSDC.sol";
import {MockStock} from "../src/MockStock.sol";
import {ThemeFund} from "../src/ThemeFund.sol";
import {ThemeFundFactory} from "../src/ThemeFundFactory.sol";

/// Tests for the fund and its factory (Phase 7b), built around a "Want AI, Avoid Oil" fund.
contract Phase7bTest is Test {
    ExposureOracle oracle;
    MockExchange exchange;
    MockUSDC usdc;
    ThemeFundFactory factory;
    ThemeFund fund;

    address nvda;
    address msft;
    address jnj;
    address xom;
    address ko; // oil: Not determined
    address newco; // listed and priced, but the engine never posted its tiers

    address manager = makeAddr("manager");
    address alice = makeAddr("alice");
    address bob = makeAddr("bob");

    bytes32 constant AI = bytes32("ai");
    bytes32 constant OIL = bytes32("oil");

    function setUp() public {
        vm.warp(1_800_000_000);
        oracle = new ExposureOracle();
        exchange = new MockExchange(oracle);
        usdc = exchange.usdc();
        factory = new ThemeFundFactory(exchange);

        nvda = _list("NVDA", 200e8, ExposureOracle.Tier.High, ExposureOracle.Tier.Limited);
        msft = _list("MSFT", 500e8, ExposureOracle.Tier.Moderate, ExposureOracle.Tier.LimitedLowerConfidence);
        jnj = _list("JNJ", 150e8, ExposureOracle.Tier.Limited, ExposureOracle.Tier.Limited);
        xom = _list("XOM", 100e8, ExposureOracle.Tier.Limited, ExposureOracle.Tier.High);
        ko = _list("KO", 60e8, ExposureOracle.Tier.Limited, ExposureOracle.Tier.NotDetermined);
        newco = exchange.listStock("NEWCO", "NEWCO");
        oracle.postPrice(bytes32("NEWCO"), 10e8);

        // 40% NVDA, 30% MSFT, 20% JNJ, 10% cash. AI weight = 70%, minimum is 60%.
        vm.prank(manager);
        fund = ThemeFund(
            factory.createFund(
                "AI ex-Oil Fund", "AIXO", _stocks3(nvda, msft, jnj), _weights3(4000, 3000, 2000), _rules()
            )
        );

        _fund(alice);
        _fund(bob);
    }

    // ───────────── the four tests named in the plan ─────────────

    function test_deposit_then_redeem_returns_about_the_same() public {
        vm.startPrank(alice);
        uint256 shares = fund.deposit(1_000e6);
        uint256 back = fund.redeem(shares);
        vm.stopPrank();

        assertLe(back, 1_000e6);
        assertApproxEqAbs(back, 1_000e6, 10); // within a thousandth of a cent
        assertEq(usdc.balanceOf(alice), 10_000e6 - 1_000e6 + back);
        assertEq(fund.totalSupply(), 0);
    }

    function test_price_rise_increases_nav() public {
        vm.prank(alice);
        fund.deposit(1_000e6);
        assertApproxEqAbs(fund.nav(), 1_000e6, 10); // $1,000, give or take rounding dust
        assertApproxEqAbs(fund.navPerShare(), 1e6, 1); // $1.00

        oracle.postPrice(bytes32("NVDA"), 300e8); // NVDA +50%; it is 40% of the fund
        assertApproxEqAbs(fund.nav(), 1_200e6, 10);
        assertApproxEqAbs(fund.navPerShare(), 1.2e6, 1); // $1.20
    }

    function test_adding_xom_to_avoid_oil_fund_reverts() public {
        vm.prank(alice);
        fund.deposit(1_000e6);

        vm.prank(manager);
        vm.expectRevert("Mandate: Oil exposure too high");
        fund.addHolding(xom, 500);

        // Nothing changed: same basket, same value, no XOM bought.
        (address[] memory stocks,) = fund.basket();
        assertEq(stocks.length, 3);
        assertEq(MockStock(xom).balanceOf(address(fund)), 0);
        assertApproxEqAbs(fund.nav(), 1_000e6, 10);
    }

    function test_stale_price_reverts() public {
        vm.prank(alice);
        uint256 shares = fund.deposit(1_000e6);

        vm.warp(block.timestamp + 7 days + 1);

        vm.expectRevert("Exchange: price is stale");
        fund.nav();

        vm.startPrank(alice);
        vm.expectRevert("Exchange: price is stale");
        fund.deposit(100e6);
        vm.expectRevert("Exchange: price is stale");
        fund.redeem(shares);
        vm.stopPrank();

        // Fresh prices bring the fund back to life.
        _repost();
        vm.prank(alice);
        assertApproxEqAbs(fund.redeem(shares), 1_000e6, 10);
    }

    // ───────────── deposits and redemptions ─────────────

    function test_first_deposit_is_one_dollar_per_share_and_buys_the_basket() public {
        vm.prank(alice);
        uint256 shares = fund.deposit(1_000e6);

        assertEq(shares, 1_000e18);
        assertEq(fund.balanceOf(alice), 1_000e18);
        assertEq(MockStock(nvda).balanceOf(address(fund)), 2e18); // $400 at $200
        assertEq(MockStock(msft).balanceOf(address(fund)), 0.6e18); // $300 at $500
        assertEq(usdc.balanceOf(address(fund)), 100e6); // the 10% cash sleeve
    }

    function test_later_depositor_buys_at_nav() public {
        vm.prank(alice);
        fund.deposit(1_000e6);
        oracle.postPrice(bytes32("NVDA"), 300e8); // NAV per share is now $1.20

        vm.prank(bob);
        uint256 bobShares = fund.deposit(600e6);
        assertApproxEqRel(bobShares, 500e18, 1e10); // $600 / $1.20, to within a millionth of a percent

        // Alice's gain is hers alone: she takes out ~$1,200, Bob ~$600.
        vm.prank(alice);
        assertApproxEqAbs(fund.redeem(1_000e18), 1_200e6, 10);
        vm.prank(bob);
        assertApproxEqAbs(fund.redeem(bobShares), 600e6, 10);
    }

    function test_partial_redeem() public {
        vm.startPrank(alice);
        fund.deposit(1_000e6);
        assertApproxEqAbs(fund.redeem(250e18), 250e6, 10);
        vm.stopPrank();
        assertApproxEqAbs(fund.nav(), 750e6, 10);
        assertEq(fund.balanceOf(alice), 750e18);
    }

    function test_deposit_and_redeem_guards() public {
        vm.startPrank(alice);
        vm.expectRevert("Fund: deposit is below $1");
        fund.deposit(999_999);
        vm.expectRevert("Fund: redeem amount is zero");
        fund.redeem(0);
        fund.deposit(100e6);
        vm.expectRevert("Fund: not enough shares");
        fund.redeem(101e18);
        vm.stopPrank();

        vm.prank(bob);
        vm.expectRevert("Fund: not enough shares");
        fund.redeem(1e18);
    }

    function test_deposit_needs_approval() public {
        address carol = makeAddr("carol");
        vm.startPrank(carol);
        usdc.faucet();
        vm.expectRevert("Token: allowance too low");
        fund.deposit(100e6);
        vm.stopPrank();
    }

    function test_shares_are_transferable() public {
        vm.prank(alice);
        fund.deposit(1_000e6);
        vm.prank(alice);
        fund.transfer(bob, 400e18);
        vm.prank(bob);
        assertApproxEqAbs(fund.redeem(400e18), 400e6, 10);
    }

    // ───────────── the mandate ─────────────

    function test_avoid_rejects_moderate_too() public {
        oracle.postExposure(bytes32("JNJ"), OIL, ExposureOracle.Tier.Moderate, 0, 0);
        (bool ok, string memory reason) = fund.isCompliant();
        assertFalse(ok);
        assertEq(reason, "Mandate: Oil exposure too high");
    }

    function test_avoid_rejects_not_determined_and_unposted() public {
        vm.startPrank(manager);
        vm.expectRevert("Mandate: Oil exposure can't be ruled out");
        fund.addHolding(ko, 500); // Not determined: "the data can't tell" is not zero
        vm.expectRevert("Mandate: Oil exposure can't be ruled out");
        fund.addHolding(newco, 500); // the engine never posted a tier
        vm.stopPrank();
    }

    function test_want_rejects_basket_with_too_little_exposure() public {
        // 50% NVDA + 50% JNJ: only 50% of weight is High/Moderate for AI, minimum is 60%.
        uint16[] memory weights = new uint16[](2);
        (weights[0], weights[1]) = (5000, 5000);
        address[] memory stocks = new address[](2);
        (stocks[0], stocks[1]) = (nvda, jnj);

        vm.prank(manager);
        vm.expectRevert("Mandate: AI exposure too low");
        fund.rebalance(stocks, weights);
    }

    function test_adding_a_big_non_ai_holding_dilutes_below_the_minimum() public {
        // JNJ-like stock at 20% scales AI weight from 70% to 56%.
        address pg = _list("PG", 160e8, ExposureOracle.Tier.Limited, ExposureOracle.Tier.Limited);
        vm.startPrank(manager);
        vm.expectRevert("Mandate: AI exposure too low");
        fund.addHolding(pg, 2000);
        fund.addHolding(pg, 1000); // 10% is fine: AI weight becomes 63%
        vm.stopPrank();
    }

    function test_check_mandate_preview() public view {
        address[] memory stocks = new address[](4);
        uint16[] memory weights = new uint16[](4);
        (stocks[0], stocks[1], stocks[2], stocks[3]) = (nvda, msft, jnj, xom);
        (weights[0], weights[1], weights[2], weights[3]) = (4000, 3000, 2000, 500);
        (bool ok, string memory reason) = fund.checkMandate(stocks, weights);
        assertFalse(ok);
        assertEq(reason, "Mandate: Oil exposure too high");

        (ok, reason) = fund.checkMandate(_stocks3(nvda, msft, jnj), _weights3(4000, 3000, 2000));
        assertTrue(ok);
        assertEq(reason, "");

        (ok, reason) = fund.checkMandate(_stocks3(nvda, msft, jnj), new uint16[](2));
        assertFalse(ok);
        assertEq(reason, "Fund: list lengths differ");
    }

    function test_rules_are_readable_and_fixed() public view {
        ThemeFund.Rule[] memory r = fund.rules();
        assertEq(r.length, 2);
        assertEq(r[0].label, "AI");
        assertEq(uint8(r[0].kind), uint8(ThemeFund.RuleKind.Want));
        assertEq(r[0].minWeightBps, 6000);
        assertEq(r[1].label, "Oil");
        assertEq(uint8(r[1].kind), uint8(ThemeFund.RuleKind.Avoid));
    }

    // ───────────── changing the basket ─────────────

    function test_add_holding_that_obeys_the_mandate() public {
        vm.prank(alice);
        fund.deposit(1_000e6);
        address pg = _list("PG", 160e8, ExposureOracle.Tier.Limited, ExposureOracle.Tier.Limited);

        vm.prank(manager);
        fund.addHolding(pg, 1000);

        (address[] memory stocks, uint16[] memory weights) = fund.basket();
        assertEq(stocks.length, 4);
        assertEq(stocks[3], pg);
        assertEq(weights[0], 3600); // 40% scaled by 90%
        assertEq(weights[3], 1000);
        assertApproxEqAbs(fund.nav(), 1_000e6, 10); // trading at oracle prices keeps the value
        assertApproxEqAbs(exchange.quoteSell(pg, MockStock(pg).balanceOf(address(fund))), 100e6, 10);
    }

    function test_rebalance_keeps_value_and_sells_dropped_names() public {
        vm.prank(alice);
        fund.deposit(1_000e6);

        address[] memory stocks = new address[](2);
        uint16[] memory weights = new uint16[](2);
        (stocks[0], stocks[1]) = (nvda, msft);
        (weights[0], weights[1]) = (6000, 4000);
        vm.prank(manager);
        fund.rebalance(stocks, weights);

        assertEq(MockStock(jnj).balanceOf(address(fund)), 0);
        assertApproxEqAbs(fund.nav(), 1_000e6, 10);
        assertApproxEqAbs(usdc.balanceOf(address(fund)), 0, 10); // fully invested now
    }

    function test_only_manager_can_change_the_basket() public {
        vm.startPrank(alice);
        vm.expectRevert("Fund: caller is not the manager");
        fund.addHolding(jnj, 100);
        vm.expectRevert("Fund: caller is not the manager");
        fund.rebalance(_stocks3(nvda, msft, jnj), _weights3(4000, 3000, 2000));
        vm.stopPrank();
    }

    function test_basket_shape_guards() public {
        vm.startPrank(manager);

        vm.expectRevert("Fund: basket is empty");
        fund.rebalance(new address[](0), new uint16[](0));

        vm.expectRevert("Fund: list lengths differ");
        fund.rebalance(_stocks3(nvda, msft, jnj), new uint16[](2));

        vm.expectRevert("Fund: weights add up to more than 100%");
        fund.rebalance(_stocks3(nvda, msft, jnj), _weights3(5000, 4000, 2000));

        vm.expectRevert("Fund: weight is zero");
        fund.rebalance(_stocks3(nvda, msft, jnj), _weights3(5000, 4000, 0));

        vm.expectRevert("Fund: stock appears twice");
        fund.rebalance(_stocks3(nvda, msft, nvda), _weights3(4000, 3000, 2000));

        vm.expectRevert("Fund: stock not listed on the exchange");
        fund.rebalance(_stocks3(nvda, msft, address(0xBEEF)), _weights3(4000, 3000, 2000));

        vm.expectRevert("Fund: stock appears twice");
        fund.addHolding(jnj, 500);

        vm.expectRevert("Fund: weight must be 1-10000");
        fund.addHolding(xom, 0);

        vm.stopPrank();
    }

    function test_too_many_holdings() public {
        address[] memory stocks = new address[](41);
        uint16[] memory weights = new uint16[](41);
        vm.prank(manager);
        vm.expectRevert("Fund: too many holdings");
        fund.rebalance(stocks, weights);
    }

    // ───────────── the factory ─────────────

    function test_factory_records_funds_and_sets_the_manager() public view {
        assertEq(factory.fundCount(), 1);
        assertEq(factory.allFunds()[0], address(fund));
        assertEq(fund.manager(), manager);
        assertEq(fund.name(), "AI ex-Oil Fund");
        assertEq(fund.symbol(), "AIXO");
        assertEq(fund.decimals(), 18);
        assertEq(address(fund.exchange()), address(exchange));
        assertEq(address(fund.oracle()), address(oracle));
    }

    function test_cannot_launch_a_fund_that_breaks_its_own_rules() public {
        vm.expectRevert("Mandate: Oil exposure too high");
        factory.createFund("Bad", "BAD", _stocks3(nvda, msft, xom), _weights3(4000, 3000, 2000), _rules());
        assertEq(factory.fundCount(), 1);
    }

    function test_rule_shape_guards() public {
        ThemeFund.Rule[] memory r = _rules();

        r[0].minWeightBps = 0;
        vm.expectRevert("Fund: Want rule needs a minimum of 1-10000");
        factory.createFund("x", "X", _stocks3(nvda, msft, jnj), _weights3(4000, 3000, 2000), r);

        r = _rules();
        r[1].minWeightBps = 100;
        vm.expectRevert("Fund: Avoid rule takes no minimum");
        factory.createFund("x", "X", _stocks3(nvda, msft, jnj), _weights3(4000, 3000, 2000), r);

        r = _rules();
        r[1].label = "";
        vm.expectRevert("Fund: rule has no label");
        factory.createFund("x", "X", _stocks3(nvda, msft, jnj), _weights3(4000, 3000, 2000), r);

        r = _rules();
        r[1].theme = bytes32(0);
        vm.expectRevert("Fund: rule has no theme");
        factory.createFund("x", "X", _stocks3(nvda, msft, jnj), _weights3(4000, 3000, 2000), r);
    }

    function test_fund_with_no_rules_accepts_anything_listed() public {
        ThemeFund free = ThemeFund(
            factory.createFund(
                "Anything", "ANY", _stocks3(xom, ko, newco), _weights3(3000, 3000, 4000), new ThemeFund.Rule[](0)
            )
        );
        vm.startPrank(alice);
        usdc.approve(address(free), type(uint256).max);
        free.deposit(500e6);
        vm.stopPrank();
        assertApproxEqAbs(free.nav(), 500e6, 10);
    }

    /// Whatever the deposit size and price move, redeeming everything pays out NAV and never more.
    function testFuzz_redeem_pays_nav(uint256 amount, uint256 newNvdaPrice) public {
        amount = bound(amount, 1e6, 10_000e6);
        newNvdaPrice = bound(newNvdaPrice, 1e8, 5_000e8);

        vm.prank(alice);
        uint256 shares = fund.deposit(amount);
        oracle.postPrice(bytes32("NVDA"), newNvdaPrice);

        uint256 navBefore = fund.nav();
        vm.prank(alice);
        uint256 back = fund.redeem(shares);

        assertLe(back, navBefore);
        assertApproxEqAbs(back, navBefore, 10);
    }

    // ───────────── helpers ─────────────

    function _list(string memory symbol, uint256 price, ExposureOracle.Tier aiTier, ExposureOracle.Tier oilTier)
        internal
        returns (address stock)
    {
        stock = exchange.listStock(symbol, symbol);
        bytes32 ticker = bytes32(bytes(symbol));
        oracle.postPrice(ticker, price);
        oracle.postExposure(ticker, AI, aiTier, 0, 0);
        oracle.postExposure(ticker, OIL, oilTier, 0, 0);
    }

    function _repost() internal {
        oracle.postPrice(bytes32("NVDA"), 200e8);
        oracle.postPrice(bytes32("MSFT"), 500e8);
        oracle.postPrice(bytes32("JNJ"), 150e8);
    }

    function _fund(address who) internal {
        vm.startPrank(who);
        usdc.faucet();
        usdc.approve(address(fund), type(uint256).max);
        vm.stopPrank();
    }

    function _rules() internal pure returns (ThemeFund.Rule[] memory r) {
        r = new ThemeFund.Rule[](2);
        r[0] = ThemeFund.Rule({theme: AI, label: "AI", kind: ThemeFund.RuleKind.Want, minWeightBps: 6000});
        r[1] = ThemeFund.Rule({theme: OIL, label: "Oil", kind: ThemeFund.RuleKind.Avoid, minWeightBps: 0});
    }

    function _stocks3(address a, address b, address c) internal pure returns (address[] memory s) {
        s = new address[](3);
        (s[0], s[1], s[2]) = (a, b, c);
    }

    function _weights3(uint16 a, uint16 b, uint16 c) internal pure returns (uint16[] memory w) {
        w = new uint16[](3);
        (w[0], w[1], w[2]) = (a, b, c);
    }
}
