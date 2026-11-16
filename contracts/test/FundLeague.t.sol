// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {FundLeague, IPriceOracle} from "../src/FundLeague.sol";
import {ExposureOracle} from "../src/ExposureOracle.sol";

/// Tries to re-enter claim() while being paid.
contract GreedyPlayer {
    FundLeague public league;
    uint256 public roundId;
    uint256 public reentryAttempts;

    constructor(FundLeague l) {
        league = l;
    }

    function play(uint256 id, bytes32[] calldata tickers, uint16[] calldata weights, bytes32[][] calldata proofs)
        external
        payable
    {
        roundId = id;
        league.enter{ value: msg.value }(id, "Greedy", tickers, weights, proofs);
    }

    function grab() external {
        league.claim(roundId);
    }

    receive() external payable {
        if (reentryAttempts == 0) {
            reentryAttempts++;
            try league.claim(roundId) {} catch {}
        }
    }
}

contract FundLeagueTest is Test {
    FundLeague league;
    ExposureOracle oracle;

    address alice = makeAddr("alice");
    address bob = makeAddr("bob");
    address carol = makeAddr("carol");
    address dave = makeAddr("dave");

    bytes32 constant DATA = keccak256("replay-prices-v2.json");
    uint256 constant WINDOWS = 400;
    uint256 constant DURATION = 60; // 20 replay days x 3 seconds
    uint256 constant STAKE = 1 ether;

    bytes32[] pool;

    function setUp() public {
        vm.warp(1_800_000_000);
        vm.roll(100);
        oracle = new ExposureOracle();
        league = new FundLeague(IPriceOracle(address(oracle)));
        string[8] memory names = ["NVDA", "AVGO", "NEM", "GOLD", "LLY", "MRK", "LMT", "XOM"];
        for (uint256 i = 0; i < names.length; i++) pool.push(bytes32(bytes(names[i])));
        _postAll(100e8);
        for (uint256 i = 0; i < 4; i++) vm.deal([alice, bob, carol, dave][i], 100 ether);
    }

    // ───────────── helpers ─────────────

    function _postAll(uint256 price) internal {
        uint256[] memory p = new uint256[](pool.length);
        for (uint256 i = 0; i < p.length; i++) p[i] = price;
        oracle.postPrices(pool, p);
    }

    function _post(string memory t, uint256 price) internal {
        oracle.postPrice(bytes32(bytes(t)), price);
    }

    // Merkle tree over `pool`, built the same way as chain/league.py and the page: leaf = keccak256(ticker),
    // pairs hashed in sorted order, an odd node at the end of a level moves up unchanged.
    function _leaves(bytes32[] memory tickers) internal pure returns (bytes32[] memory l) {
        l = new bytes32[](tickers.length);
        for (uint256 i = 0; i < tickers.length; i++) l[i] = keccak256(abi.encodePacked(tickers[i]));
    }

    function _up(bytes32[] memory level) internal pure returns (bytes32[] memory next) {
        next = new bytes32[]((level.length + 1) / 2);
        for (uint256 i = 0; i < next.length; i++) {
            if (2 * i + 1 == level.length) {
                next[i] = level[2 * i];
            } else {
                (bytes32 a, bytes32 b) = (level[2 * i], level[2 * i + 1]);
                next[i] = a < b ? keccak256(abi.encodePacked(a, b)) : keccak256(abi.encodePacked(b, a));
            }
        }
    }

    function _rootOf(bytes32[] memory tickers) internal pure returns (bytes32) {
        bytes32[] memory level = _leaves(tickers);
        while (level.length > 1) level = _up(level);
        return level[0];
    }

    function _proofIn(bytes32[] memory tickers, bytes32 t) internal pure returns (bytes32[] memory proof) {
        uint256 idx = type(uint256).max;
        for (uint256 i = 0; i < tickers.length; i++) if (tickers[i] == t) idx = i;
        if (idx == type(uint256).max) return new bytes32[](0); // not in the pool: an empty proof fails
        bytes32[] memory level = _leaves(tickers);
        bytes32[] memory tmp = new bytes32[](40);
        uint256 n;
        while (level.length > 1) {
            uint256 sib = idx ^ 1;
            if (sib < level.length) tmp[n++] = level[sib];
            level = _up(level);
            idx /= 2;
        }
        proof = new bytes32[](n);
        for (uint256 i = 0; i < n; i++) proof[i] = tmp[i];
    }

    function _proofs(bytes32[] memory t) internal view returns (bytes32[][] memory pr) {
        pr = new bytes32[][](t.length);
        for (uint256 i = 0; i < t.length; i++) pr[i] = _proofIn(pool, t[i]);
    }

    function _enterV(uint256 v, uint256 id, string memory name, bytes32[] memory t, uint16[] memory w) internal {
        league.enter{ value: v }(id, name, t, w, _proofs(t));
    }

    function _open() internal returns (uint256 id) {
        id = league.openRound(_rootOf(pool), pool.length, STAKE, block.timestamp + 60, DURATION, DATA, WINDOWS);
    }

    function _t3(string memory a, string memory b, string memory c) internal pure returns (bytes32[] memory t) {
        t = new bytes32[](3);
        (t[0], t[1], t[2]) = (bytes32(bytes(a)), bytes32(bytes(b)), bytes32(bytes(c)));
    }

    function _w3(uint16 a, uint16 b, uint16 c) internal pure returns (uint16[] memory w) {
        w = new uint16[](3);
        (w[0], w[1], w[2]) = (a, b, c);
    }

    function _enter(address who, uint256 id, string memory name, bytes32[] memory t, uint16[] memory w) internal {
        bytes32[][] memory pr = _proofs(t);
        vm.prank(who);
        league.enter{ value: STAKE }(id, name, t, w, pr);
    }

    function _enterAiGoldHealth(uint256 id) internal {
        _enter(alice, id, "AI rocket", _t3("NVDA", "AVGO", "LLY"), _w3(5000, 3000, 2000));
        _enter(bob, id, "Gold bug", _t3("NEM", "GOLD", "MRK"), _w3(4000, 4000, 2000));
        _enter(carol, id, "Pharma", _t3("LLY", "MRK", "LMT"), _w3(3400, 3300, 3300));
    }

    /// Close entries, lock, wait for the target block, start (prices are $100 at start).
    function _lockAndStart(uint256 id) internal {
        vm.warp(block.timestamp + 61);
        _postAll(100e8); // the replayer resets the pool to $100 right before start
        league.lock(id);
        vm.roll(block.number + league.LOCK_DELAY() + 1);
        league.start(id);
    }

    function _settle(uint256 id) internal {
        vm.warp(block.timestamp + DURATION);
        league.settle(id);
    }

    function _claim(address who, uint256 id) internal returns (uint256 got) {
        uint256 before = who.balance;
        vm.prank(who);
        league.claim(id);
        got = who.balance - before;
    }

    function _score(uint256 id, uint256 i) internal view returns (int256 s) {
        (,,,, s) = league.getEntry(id, i);
    }

    // ───────────── entering ─────────────

    function test_valid_entry_is_stored_on_chain() public {
        uint256 id = _open();
        _enter(alice, id, "AI rocket", _t3("NVDA", "AVGO", "LLY"), _w3(5000, 3000, 2000));
        (address owner, string memory name, bytes32[] memory t, uint16[] memory w,) = league.getEntry(id, 0);
        assertEq(owner, alice);
        assertEq(name, "AI rocket");
        assertEq(t[0], bytes32("NVDA"));
        assertEq(t[2], bytes32("LLY"));
        assertEq(w[0], 5000);
        assertEq(league.entryOf(id, alice), 1);
        FundLeague.RoundInfo memory info = league.getRound(id);
        assertEq(info.pot, STAKE);
        assertEq(info.entryCount, 1);
    }

    function test_invalid_etfs_are_refused() public {
        uint256 id = _open();
        vm.startPrank(alice);
        vm.expectRevert("League: weights must add up to 100%");
        _enterV(STAKE, id, "x", _t3("NVDA", "AVGO", "LLY"), _w3(5000, 3000, 1999));
        vm.expectRevert("League: each weight must be at least 5%");
        _enterV(STAKE, id, "x", _t3("NVDA", "AVGO", "LLY"), _w3(9100, 499, 401));
        vm.expectRevert("League: stock is not in the pool");
        _enterV(STAKE, id, "x", _t3("NVDA", "AVGO", "TSLA"), _w3(5000, 3000, 2000));
        vm.expectRevert("League: duplicate stock");
        _enterV(STAKE, id, "x", _t3("NVDA", "AVGO", "NVDA"), _w3(5000, 3000, 2000));
        vm.expectRevert("League: one weight and one proof per stock");
        _enterV(STAKE, id, "x", _t3("NVDA", "AVGO", "LLY"), new uint16[](2));
        vm.expectRevert("League: name must be 1 to 32 bytes");
        _enterV(STAKE, id, "", _t3("NVDA", "AVGO", "LLY"), _w3(5000, 3000, 2000));
        vm.expectRevert("League: name must be 1 to 32 bytes");
        _enterV(STAKE, id, "this name is far too long for a fund name", _t3("NVDA", "AVGO", "LLY"),
            _w3(5000, 3000, 2000));

        bytes32[] memory two = new bytes32[](2);
        (two[0], two[1]) = (bytes32("NVDA"), bytes32("AVGO"));
        uint16[] memory w2 = new uint16[](2);
        (w2[0], w2[1]) = (5000, 5000);
        vm.expectRevert("League: pick 3 to 8 stocks");
        _enterV(STAKE, id, "x", two, w2);

        bytes32[] memory nine = new bytes32[](9);
        uint16[] memory w9 = new uint16[](9);
        for (uint256 i = 0; i < 8; i++) (nine[i], w9[i]) = (pool[i], 1000);
        (nine[8], w9[8]) = (bytes32("TSLA"), 2000);
        vm.expectRevert("League: pick 3 to 8 stocks");
        _enterV(STAKE, id, "x", nine, w9);
        vm.stopPrank();
    }

    function test_eight_stocks_and_min_weights_are_allowed() public {
        uint256 id = _open();
        uint16[] memory w = new uint16[](8);
        for (uint256 i = 0; i < 7; i++) w[i] = 500; // 7 x 5% = 35%
        w[7] = 6500;
        vm.prank(alice);
        _enterV(STAKE, id, "Eight", pool, w);
        assertEq(league.entryOf(id, alice), 1);
    }

    function test_wrong_stake_refused() public {
        uint256 id = _open();
        vm.startPrank(alice);
        vm.expectRevert("League: send exactly the entry stake");
        _enterV(0.5 ether, id, "x", _t3("NVDA", "AVGO", "LLY"), _w3(5000, 3000, 2000));
        vm.expectRevert("League: send exactly the entry stake");
        _enterV(2 ether, id, "x", _t3("NVDA", "AVGO", "LLY"), _w3(5000, 3000, 2000));
        vm.expectRevert("League: send exactly the entry stake");
        _enterV(0, id, "x", _t3("NVDA", "AVGO", "LLY"), _w3(5000, 3000, 2000));
        vm.stopPrank();
    }

    function test_second_entry_from_same_wallet_refused() public {
        uint256 id = _open();
        _enter(alice, id, "First", _t3("NVDA", "AVGO", "LLY"), _w3(5000, 3000, 2000));
        vm.prank(alice);
        vm.expectRevert("League: this wallet already entered");
        _enterV(STAKE, id, "Second", _t3("NEM", "GOLD", "MRK"), _w3(5000, 3000, 2000));
    }

    function test_entry_after_deadline_refused() public {
        uint256 id = _open();
        vm.warp(block.timestamp + 60); // exactly at the deadline
        vm.prank(alice);
        vm.expectRevert("League: entries are closed");
        _enterV(STAKE, id, "Late", _t3("NVDA", "AVGO", "LLY"), _w3(5000, 3000, 2000));
    }

    // ───────────── scoring and payouts ─────────────

    function test_return_math_for_a_multi_stock_etf_and_winner_takes_pot() public {
        uint256 id = _open();
        _enterAiGoldHealth(id);
        _lockAndStart(id);
        // NVDA +20%, AVGO +10%, LLY -5%, NEM +15%, GOLD +5%, MRK +2%, LMT +1%
        _post("NVDA", 120e8);
        _post("AVGO", 110e8);
        _post("LLY", 95e8);
        _post("NEM", 115e8);
        _post("GOLD", 105e8);
        _post("MRK", 102e8);
        _post("LMT", 101e8);
        _settle(id);
        // AI rocket: 50% x 20% + 30% x 10% + 20% x -5% = 10% + 3% - 1% = +12%
        assertEq(_score(id, 0), 0.12e18);
        // Gold bug: 40% x 15% + 40% x 5% + 20% x 2% = 6% + 2% + 0.4% = +8.4%
        assertEq(_score(id, 1), 0.084e18);
        // Pharma: 34% x -5% + 33% x 2% + 33% x 1% = -1.7% + 0.66% + 0.33% = -0.71%
        assertEq(_score(id, 2), -0.0071e18);
        assertEq(_claim(alice, id), 3 ether); // the whole pot
        vm.prank(bob);
        vm.expectRevert("League: nothing to claim");
        league.claim(id);
        assertEq(address(league).balance, 0);
    }

    function test_tie_splits_the_pot() public {
        uint256 id = _open();
        _enter(alice, id, "Twin A", _t3("NVDA", "AVGO", "LLY"), _w3(5000, 3000, 2000));
        _enter(bob, id, "Twin B", _t3("AVGO", "NVDA", "LLY"), _w3(3000, 5000, 2000)); // same ETF, other order
        _enter(carol, id, "Gold", _t3("NEM", "GOLD", "MRK"), _w3(4000, 4000, 2000));
        _lockAndStart(id);
        _post("NVDA", 130e8);
        _settle(id);
        assertEq(_score(id, 0), _score(id, 1));
        assertEq(league.getRound(id).winnerCount, 2);
        assertEq(_claim(alice, id), 1.5 ether);
        assertEq(_claim(bob, id), 1.5 ether);
        assertEq(league.claimable(id, carol), 0);
    }

    function test_three_way_tie_leaves_only_dust() public {
        uint256 id = _open();
        _enterAiGoldHealth(id);
        _lockAndStart(id); // nothing moves: all three returns are 0%
        _settle(id);
        assertEq(league.getRound(id).winnerCount, 3);
        assertEq(_claim(alice, id), 1 ether);
        assertEq(_claim(bob, id), 1 ether);
        assertEq(_claim(carol, id), 1 ether);
    }

    function test_single_entrant_is_refunded() public {
        uint256 id = _open();
        _enter(alice, id, "Lonely", _t3("NVDA", "AVGO", "LLY"), _w3(5000, 3000, 2000));
        vm.warp(block.timestamp + 61);
        league.lock(id);
        assertEq(uint256(league.getRound(id).phase), uint256(FundLeague.Phase.Cancelled));
        assertEq(_claim(alice, id), STAKE);
        vm.expectRevert("League: round is not locked");
        league.start(id);
    }

    function test_stalled_round_refunds_everyone() public {
        uint256 id = _open();
        _enterAiGoldHealth(id);
        vm.warp(block.timestamp + 61);
        vm.expectRevert("League: not stalled yet");
        league.cancelStalled(id);
        league.lock(id); // locked but never started
        vm.warp(block.timestamp + league.STALL_TIMEOUT());
        league.cancelStalled(id);
        assertEq(_claim(alice, id), STAKE);
        assertEq(_claim(bob, id), STAKE);
        assertEq(_claim(carol, id), STAKE);
        assertEq(address(league).balance, 0);
    }

    function test_double_claim_refused() public {
        uint256 id = _open();
        _enterAiGoldHealth(id);
        _lockAndStart(id);
        _post("NVDA", 150e8);
        _settle(id);
        _claim(alice, id);
        vm.prank(alice);
        vm.expectRevert("League: already claimed");
        league.claim(id);
    }

    function test_reentrancy_guard_blocks_a_second_payout() public {
        uint256 id = _open();
        GreedyPlayer g = new GreedyPlayer(league);
        g.play{value: STAKE}(id, _t3("NVDA", "AVGO", "LLY"), _w3(5000, 3000, 2000), _proofs(_t3("NVDA", "AVGO", "LLY")));
        _enter(bob, id, "Gold bug", _t3("NEM", "GOLD", "MRK"), _w3(4000, 4000, 2000));
        _lockAndStart(id);
        _post("NVDA", 150e8);
        _settle(id);
        g.grab();
        assertEq(address(g).balance, 2 ether); // paid once: the whole pot
        assertEq(g.reentryAttempts(), 1); // it tried, and the guard stopped it
        assertEq(address(league).balance, 0);
    }

    function test_settle_and_claim_timing() public {
        uint256 id = _open();
        _enterAiGoldHealth(id);
        vm.prank(alice);
        vm.expectRevert("League: round is not finished");
        league.claim(id);
        vm.expectRevert("League: round has not started");
        league.settle(id);
        _lockAndStart(id);
        vm.warp(block.timestamp + DURATION - 1);
        vm.expectRevert("League: race is not over yet");
        league.settle(id);
        vm.warp(block.timestamp + 1);
        league.settle(id);
    }

    function test_stale_price_blocks_start_and_settle() public {
        uint256 id = _open();
        _enterAiGoldHealth(id);
        vm.warp(block.timestamp + 61);
        league.lock(id);
        vm.roll(block.number + 4);
        vm.warp(block.timestamp + 2 days); // prices posted 2 days ago
        vm.expectRevert("League: a picked stock's price is stale");
        league.start(id);
        _postAll(100e8);
        league.start(id);
        vm.warp(block.timestamp + 2 days); // replay stopped posting
        vm.expectRevert("League: a picked stock's price is stale");
        league.settle(id);
    }

    function test_live_scores_follow_the_oracle() public {
        uint256 id = _open();
        _enterAiGoldHealth(id);
        _lockAndStart(id);
        _post("NVDA", 110e8); // day 1
        int256[] memory s = league.liveScores(id);
        assertEq(s[0], 0.05e18); // 50% x +10%
        assertEq(s[1], 0);
    }

    // ───────────── randomness: the window can't be known before lock ─────────────

    function test_window_cannot_be_known_before_lock() public {
        uint256 id = _open();
        _enterAiGoldHealth(id);
        vm.expectRevert("League: round is not locked");
        league.start(id);
        vm.warp(block.timestamp + 61);
        league.lock(id);
        uint256 target = league.getRound(id).targetBlock;
        assertEq(target, block.number + league.LOCK_DELAY());
        assertEq(blockhash(target), bytes32(0)); // the deciding block doesn't exist yet
        vm.expectRevert("League: target block not reached yet");
        league.start(id);
        vm.roll(target);
        vm.expectRevert("League: target block not reached yet");
        league.start(id);

        vm.roll(target + 1);
        uint256 snap = vm.snapshotState();
        vm.setBlockhash(target, keccak256("hash A"));
        league.start(id);
        uint256 windowA = league.getRound(id).windowIndex;
        vm.revertToState(snap);
        vm.setBlockhash(target, keccak256("hash B"));
        league.start(id);
        uint256 windowB = league.getRound(id).windowIndex;
        assertTrue(windowA != windowB);
        assertLt(windowA, WINDOWS);
        assertEq(windowA, uint256(keccak256(abi.encode(keccak256("hash A"), id, DATA))) % WINDOWS);
    }

    function test_start_falls_back_to_prevrandao_after_256_blocks() public {
        uint256 id = _open();
        _enterAiGoldHealth(id);
        vm.warp(block.timestamp + 61);
        league.lock(id);
        vm.roll(block.number + 1000);
        vm.prevrandao(bytes32(uint256(42)));
        _postAll(100e8);
        league.start(id);
        assertEq(league.getRound(id).windowIndex, uint256(keccak256(abi.encode(bytes32(uint256(42)), id, DATA))) % WINDOWS);
    }

    // ───────────── operator and inputs ─────────────

    function test_only_operator_opens_rounds_and_inputs_are_checked() public {
        vm.prank(alice);
        vm.expectRevert("League: only the operator");
        league.openRound(_rootOf(pool), pool.length, STAKE, block.timestamp + 60, DURATION, DATA, WINDOWS);
        vm.expectRevert("League: missing pool root");
        league.openRound(bytes32(0), pool.length, STAKE, block.timestamp + 60, DURATION, DATA, WINDOWS);
        vm.expectRevert("League: pool must have at least 3 stocks");
        league.openRound(_rootOf(pool), 2, STAKE, block.timestamp + 60, DURATION, DATA, WINDOWS);
        vm.expectRevert("League: entry stake must be > 0");
        league.openRound(_rootOf(pool), pool.length, 0, block.timestamp + 60, DURATION, DATA, WINDOWS);
        vm.expectRevert("League: deadline must be in the future");
        league.openRound(_rootOf(pool), pool.length, STAKE, block.timestamp, DURATION, DATA, WINDOWS);
        vm.expectRevert("League: missing replay data hash");
        league.openRound(_rootOf(pool), pool.length, STAKE, block.timestamp + 60, DURATION, bytes32(0), WINDOWS);
        vm.expectRevert("League: need at least one replay window");
        league.openRound(_rootOf(pool), pool.length, STAKE, block.timestamp + 60, DURATION, DATA, 0);
    }

    function test_data_hash_and_pool_are_recorded_before_entries() public {
        uint256 id = _open();
        FundLeague.RoundInfo memory info = league.getRound(id);
        assertEq(info.dataHash, DATA);
        assertEq(info.poolSize, pool.length);
        assertEq(info.poolRoot, _rootOf(pool));
        assertEq(info.used.length, 0); // nothing needs a price until someone enters
        assertEq(uint256(info.phase), uint256(FundLeague.Phase.Open));
    }

    function test_events_are_emitted() public {
        vm.expectEmit(true, false, false, false);
        emit FundLeague.RoundOpened(1, bytes32(0), 0, 0, 0, 0, bytes32(0), 0);
        uint256 id = _open();
        vm.expectEmit(true, true, true, true);
        emit FundLeague.Entered(id, alice, 0, "AI rocket", _t3("NVDA", "AVGO", "LLY"), _w3(5000, 3000, 2000));
        _enter(alice, id, "AI rocket", _t3("NVDA", "AVGO", "LLY"), _w3(5000, 3000, 2000));
        _enter(bob, id, "Gold bug", _t3("NEM", "GOLD", "MRK"), _w3(4000, 4000, 2000));
        vm.warp(block.timestamp + 61);
        vm.expectEmit(true, false, false, true);
        emit FundLeague.Locked(id, block.number + 3);
        league.lock(id);
        vm.roll(block.number + 4);
        league.start(id);
        _post("NVDA", 120e8);
        vm.warp(block.timestamp + DURATION);
        vm.expectEmit(true, false, false, true);
        emit FundLeague.Settled(id, 0.1e18, 1, 2 ether);
        league.settle(id);
        vm.expectEmit(true, true, false, true);
        emit FundLeague.Claimed(id, alice, 2 ether, false);
        vm.prank(alice);
        league.claim(id);
    }
    // ───────────── full-universe pool: prices only for picked stocks ─────────────

    function _bigPool(uint256 n) internal pure returns (bytes32[] memory big) {
        big = new bytes32[](n);
        for (uint256 i = 0; i < n; i++) big[i] = keccak256(abi.encode("ticker", i)) >> 8; // 666 distinct "tickers"
    }

    function test_666_stock_pool_needs_prices_only_for_picked_stocks() public {
        bytes32[] memory big = _bigPool(666);
        delete pool;
        for (uint256 i = 0; i < big.length; i++) pool.push(big[i]); // _proofs() builds proofs from `pool`
        bytes32 root = _rootOf(pool);
        uint256 g0 = gasleft();
        uint256 id = league.openRound(root, pool.length, STAKE, block.timestamp + 60, DURATION, DATA, WINDOWS);
        uint256 openGas = g0 - gasleft();
        emit log_named_uint("openRound gas with a 666-stock pool", openGas);
        assertLt(openGas, 250_000); // one root, not 666 storage writes

        // Two entries, 3 stocks each, sharing one: only 5 distinct tickers are used.
        bytes32[] memory a = new bytes32[](3);
        (a[0], a[1], a[2]) = (big[0], big[100], big[665]);
        bytes32[] memory b = new bytes32[](3);
        (b[0], b[1], b[2]) = (big[100], big[333], big[500]);
        _enter(alice, id, "Few A", a, _w3(5000, 3000, 2000));
        _enter(bob, id, "Few B", b, _w3(4000, 4000, 2000));
        FundLeague.RoundInfo memory info = league.getRound(id);
        assertEq(info.used.length, 5);
        assertEq(info.poolSize, 666);

        // Prices are posted ONLY for the 5 used tickers; the other 661 pool stocks never get one.
        bytes32[] memory used = info.used;
        uint256[] memory p = new uint256[](used.length);
        for (uint256 i = 0; i < p.length; i++) p[i] = 100e8;
        vm.warp(block.timestamp + 61);
        oracle.postPrices(used, p);
        league.lock(id);
        vm.roll(block.number + league.LOCK_DELAY() + 1);
        league.start(id);
        oracle.postPrice(big[665], 200e8); // alice's 20% stock doubles: +20%
        vm.warp(block.timestamp + DURATION);
        league.settle(id);
        (,,,, int256 sa) = league.getEntry(id, 0);
        (,,,, int256 sb) = league.getEntry(id, 1);
        assertEq(sa, 0.2e18);
        assertEq(sb, 0);
        (uint256 unusedPrice,) = oracle.priceOf(big[1]);
        assertEq(unusedPrice, 0); // an unused pool ticker never needed a price
        (uint256[] memory sp, uint256[] memory ep) = league.getPrices(id);
        assertEq(sp.length, 5);
        assertEq(ep.length, 5);
        assertEq(_claim(alice, id), 2 ether);
    }

    function test_a_picked_stock_without_a_price_blocks_start() public {
        bytes32[] memory big = _bigPool(50);
        delete pool;
        for (uint256 i = 0; i < big.length; i++) pool.push(big[i]);
        uint256 id = league.openRound(_rootOf(pool), pool.length, STAKE, block.timestamp + 60, DURATION, DATA, WINDOWS);
        bytes32[] memory a = new bytes32[](3);
        (a[0], a[1], a[2]) = (big[1], big[2], big[3]);
        _enter(alice, id, "A", a, _w3(5000, 3000, 2000));
        _enter(bob, id, "B", a, _w3(4000, 4000, 2000));
        vm.warp(block.timestamp + 61);
        league.lock(id);
        vm.roll(block.number + league.LOCK_DELAY() + 1);
        vm.expectRevert("League: a picked stock has no price");
        league.start(id);
    }

    function test_proof_for_another_ticker_or_another_pool_is_refused() public {
        uint256 id = _open();
        bytes32[] memory t = _t3("NVDA", "AVGO", "LLY");
        bytes32[][] memory pr = _proofs(t);
        pr[2] = _proofIn(pool, bytes32("NEM")); // NEM's proof doesn't prove LLY
        vm.prank(alice);
        vm.expectRevert("League: stock is not in the pool");
        league.enter{ value: STAKE }(id, "x", t, _w3(5000, 3000, 2000), pr);
        assertTrue(league.inPool(id, bytes32("NVDA"), _proofIn(pool, bytes32("NVDA"))));
        assertFalse(league.inPool(id, bytes32("TSLA"), _proofIn(pool, bytes32("NVDA"))));
    }
}
