// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// The only thing the league needs from its oracle: the latest price of a ticker (ExposureOracle has this).
interface IPriceOracle {
    function priceOf(bytes32 ticker) external view returns (uint256 price, uint256 timestamp);
}

/// @title FundLeague ("Fantasy Funds League")
/// @notice A game played with TESTNET MON only (no real money). Players build their OWN mini-ETF from a pool
///         of stocks, stake the entry fee and race each other over a random window of real past prices.
///
///         A round, step by step:
///         1. openRound  (operator) sets the stock pool as a Merkle root (one storage slot, so a round with the
///                       full ~666-stock universe costs the same to open as one with 10), the entry stake, the entry deadline, how long the race
///                       lasts, the hash of the replay price file (fixed BEFORE anyone enters, so it can't be
///                       swapped later) and how many replay windows that file contains.
///         2. enter      anyone, before the deadline, once per wallet: a name, 3-8 tickers from the pool, each
///                       with a Merkle proof that it is in the pool (no duplicates) and weights in basis points (each >= 5%, adding up to exactly 100%), paying
///                       exactly the entry stake. Stored on-chain; there are no fund tokens and no trading.
///         3. lock       anyone, after the deadline: records a target block LOCK_DELAY blocks in the future.
///                       With fewer than 2 entries there's no race: the round is cancelled and stakes refunded.
///         4. start      anyone, after the target block: that block's hash picks the replay window (nobody could
///                       know it while entries were open) and starting prices are recorded from the League's
///                       oracle ONLY for the tickers some entry uses (deduplicated as entries come in). Pool stocks
///                       nobody picked never need a price. The off-chain replayer then posts that window's prices
///                       day by day for the used tickers only.
///         5. settle     anyone, once the race time is over: end prices for the same used tickers; each entry's
///                       return is the weighted average of its stocks' price returns (end vs start). The highest return wins; ties split the pot.
///         6. claim      the winner(s) pull the whole pot (split evenly on a tie). In a cancelled round
///                       (single entrant, no race, or stalled) everyone pulls their own stake back.
///
///         Safety: pull payments, one claim per wallet per round, a reentrancy guard, prices must be fresh, and a
///         timeout so a round that never gets locked/started can be cancelled by anyone. Rounding dust (at most a
///         few wei when a pot is split) stays in the contract.
///
///         Testnet / hackathon code: not audited.
contract FundLeague {
    enum Phase {
        None,
        Open, // taking entries
        Locked, // entries closed, waiting for the target block
        Started, // window picked, starting prices recorded, race running
        Settled, // winners known
        Cancelled // no race (fewer than 2 entries, or stalled): everyone refunded
    }

    struct Entry {
        address owner;
        string name;
        uint16[] stocks; // indexes into the round's used-ticker list
        uint16[] weightsBps;
        int256 score; // return x 1e18 after settle (0.05e18 = +5%)
    }

    struct Round {
        bytes32 poolRoot; // Merkle root of the pool's tickers
        uint32 poolSize;
        bytes32[] used; // tickers used by at least one entry, in first-use order (deduplicated)
        uint256 entryStake;
        uint64 deadline;
        uint64 roundDuration;
        uint64 startedAt;
        uint64 targetBlock;
        uint32 windowCount;
        uint32 windowIndex;
        bytes32 dataHash;
        bytes32 seed;
        Phase phase;
        uint32 winnerCount;
        int256 bestScore;
        uint256 pot;
        uint256[] startPrice;
        uint256[] endPrice;
        Entry[] entries;
    }

    /// Everything about a round except the per-stock prices and the entries. `used` = tickers some entry uses
    /// (the only ones that get prices); the pool itself is the Merkle root at the end.
    struct RoundInfo {
        bytes32[] used;
        uint256 entryStake;
        uint256 deadline;
        uint256 roundDuration;
        uint256 startedAt;
        uint256 targetBlock;
        uint256 windowCount;
        uint256 windowIndex;
        bytes32 dataHash;
        bytes32 seed;
        Phase phase;
        uint256 entryCount;
        uint256 winnerCount;
        int256 bestScore;
        uint256 pot;
        bytes32 poolRoot;
        uint256 poolSize;
    }

    uint256 public constant LOCK_DELAY = 3;
    uint256 public constant STALL_TIMEOUT = 1 days;
    uint256 public constant MAX_PROOF = 32; // Merkle proof length limit (a 2^32-stock pool)
    uint256 public constant MAX_ENTRIES = 200;
    uint256 public constant MIN_STOCKS = 3;
    uint256 public constant MAX_STOCKS = 8;
    uint256 public constant MIN_WEIGHT_BPS = 500;
    uint256 public constant BPS = 10_000;
    uint256 public constant MAX_PRICE_AGE = 1 days;

    address public immutable operator;
    IPriceOracle public immutable oracle;
    uint256 public roundCount;

    mapping(uint256 => Round) private _rounds;
    mapping(uint256 => mapping(bytes32 => uint256)) private _usedIndexPlus1; // round => ticker => used index + 1
    mapping(uint256 => mapping(address => uint256)) public entryOf; // round => wallet => entry index + 1
    mapping(uint256 => mapping(address => bool)) public claimed;

    uint256 private _lock = 1;

    event RoundOpened(uint256 indexed roundId, bytes32 poolRoot, uint256 poolSize, uint256 entryStake, uint256 deadline,
        uint256 roundDuration, bytes32 dataHash, uint256 windowCount);
    event Entered(uint256 indexed roundId, address indexed owner, uint256 indexed entryIndex, string name,
        bytes32[] tickers, uint16[] weightsBps);
    event Locked(uint256 indexed roundId, uint256 targetBlock);
    event Started(uint256 indexed roundId, uint256 windowIndex, bytes32 seed);
    event Settled(uint256 indexed roundId, int256 bestScore, uint256 winnerCount, uint256 pot);
    event Cancelled(uint256 indexed roundId, string reason);
    event Claimed(uint256 indexed roundId, address indexed owner, uint256 amount, bool refund);

    modifier onlyOperator() {
        require(msg.sender == operator, "League: only the operator");
        _;
    }

    modifier nonReentrant() {
        require(_lock == 1, "League: reentrant call");
        _lock = 2;
        _;
        _lock = 1;
    }

    constructor(IPriceOracle oracle_) {
        require(address(oracle_) != address(0), "League: oracle is zero");
        operator = msg.sender;
        oracle = oracle_;
    }

    // ───────────── round lifecycle ─────────────

    /// poolRoot: Merkle root of the pool (leaf = keccak256(abi.encodePacked(ticker)), pairs hashed in sorted order).
    function openRound(
        bytes32 poolRoot,
        uint256 poolSize,
        uint256 entryStake,
        uint256 deadline,
        uint256 roundDuration,
        bytes32 dataHash,
        uint256 windowCount
    ) external onlyOperator returns (uint256 roundId) {
        require(poolRoot != bytes32(0), "League: missing pool root");
        require(poolSize >= MIN_STOCKS && poolSize <= type(uint32).max, "League: pool must have at least 3 stocks");
        require(entryStake > 0, "League: entry stake must be > 0");
        require(deadline > block.timestamp, "League: deadline must be in the future");
        require(roundDuration > 0, "League: round duration must be > 0");
        require(dataHash != bytes32(0), "League: missing replay data hash");
        require(windowCount > 0 && windowCount <= type(uint32).max, "League: need at least one replay window");
        roundId = ++roundCount;
        Round storage r = _rounds[roundId];
        r.poolRoot = poolRoot;
        r.poolSize = uint32(poolSize);
        r.entryStake = entryStake;
        r.deadline = uint64(deadline);
        r.roundDuration = uint64(roundDuration);
        r.dataHash = dataHash;
        r.windowCount = uint32(windowCount);
        r.phase = Phase.Open;
        emit RoundOpened(roundId, poolRoot, poolSize, entryStake, deadline, roundDuration, dataHash, windowCount);
    }

    /// Enter your own ETF: 3-8 tickers from the pool, weights in basis points (each >= 500, total 10,000), and
    /// one Merkle proof per ticker showing it's in the pool.
    function enter(
        uint256 roundId,
        string calldata name,
        bytes32[] calldata tickers,
        uint16[] calldata weightsBps,
        bytes32[][] calldata proofs
    )
        external
        payable
        nonReentrant
    {
        Round storage r = _rounds[roundId];
        require(r.phase == Phase.Open, "League: round is not open");
        require(block.timestamp < r.deadline, "League: entries are closed");
        require(msg.value == r.entryStake, "League: send exactly the entry stake");
        require(entryOf[roundId][msg.sender] == 0, "League: this wallet already entered");
        require(r.entries.length < MAX_ENTRIES, "League: round is full");
        require(bytes(name).length > 0 && bytes(name).length <= 32, "League: name must be 1 to 32 bytes");
        require(tickers.length >= MIN_STOCKS && tickers.length <= MAX_STOCKS, "League: pick 3 to 8 stocks");
        require(weightsBps.length == tickers.length && proofs.length == tickers.length,
            "League: one weight and one proof per stock");
        {
            uint16[] memory idx = _checkStocks(roundId, r, tickers, weightsBps, proofs);
            Entry storage e = r.entries.push();
            e.owner = msg.sender;
            e.name = name;
            e.stocks = idx;
            e.weightsBps = weightsBps;
        }
        entryOf[roundId][msg.sender] = r.entries.length;
        r.pot += msg.value;
        emit Entered(roundId, msg.sender, r.entries.length - 1, name, tickers, weightsBps);
    }

    /// After the deadline: commit to a future block whose hash picks the window. Fewer than 2 entries: refund.
    function lock(uint256 roundId) external {
        Round storage r = _rounds[roundId];
        require(r.phase == Phase.Open, "League: round is not open");
        require(block.timestamp >= r.deadline, "League: entries are still open");
        if (r.entries.length < 2) {
            r.phase = Phase.Cancelled;
            emit Cancelled(roundId, "fewer than 2 entries");
            return;
        }
        r.targetBlock = uint64(block.number + LOCK_DELAY);
        r.phase = Phase.Locked;
        emit Locked(roundId, r.targetBlock);
    }

    /// After the target block: pick the window and record starting prices for the used tickers only.
    function start(uint256 roundId) external {
        Round storage r = _rounds[roundId];
        require(r.phase == Phase.Locked, "League: round is not locked");
        require(block.number > r.targetBlock, "League: target block not reached yet");
        bytes32 h = blockhash(r.targetBlock);
        // blockhash is only available for the last 256 blocks; after that fall back to prevrandao.
        if (h == bytes32(0)) h = bytes32(block.prevrandao);
        r.seed = keccak256(abi.encode(h, roundId, r.dataHash));
        r.windowIndex = uint32(uint256(r.seed) % r.windowCount);
        r.startPrice = _pricesNow(r.used);
        r.startedAt = uint64(block.timestamp);
        r.phase = Phase.Started;
        emit Started(roundId, r.windowIndex, r.seed);
    }

    /// Anyone, once the race is over: score every entry; the highest return wins, ties split the pot.
    function settle(uint256 roundId) external {
        Round storage r = _rounds[roundId];
        require(r.phase == Phase.Started, "League: round has not started");
        require(block.timestamp >= uint256(r.startedAt) + r.roundDuration, "League: race is not over yet");
        r.endPrice = _pricesNow(r.used);
        int256 best = type(int256).min;
        uint256 n = r.entries.length;
        for (uint256 i = 0; i < n; i++) {
            int256 s = _score(r.entries[i], r.startPrice, r.endPrice);
            r.entries[i].score = s;
            if (s > best) best = s;
        }
        uint32 winners;
        for (uint256 i = 0; i < n; i++) {
            if (r.entries[i].score == best) winners++;
        }
        r.bestScore = best;
        r.winnerCount = winners;
        r.phase = Phase.Settled;
        emit Settled(roundId, best, winners, r.pot);
    }

    /// Anyone: if a round wasn't locked AND started within STALL_TIMEOUT after the deadline, refund everyone.
    function cancelStalled(uint256 roundId) external {
        Round storage r = _rounds[roundId];
        require(r.phase == Phase.Open || r.phase == Phase.Locked, "League: round can't be cancelled");
        require(block.timestamp >= uint256(r.deadline) + STALL_TIMEOUT, "League: not stalled yet");
        r.phase = Phase.Cancelled;
        emit Cancelled(roundId, "stalled");
    }

    // ───────────── payouts ─────────────

    /// Winners pull their share of the pot; in a cancelled round everyone pulls their stake back. Once per round.
    function claim(uint256 roundId) external nonReentrant returns (uint256 amount) {
        Round storage r = _rounds[roundId];
        require(r.phase == Phase.Settled || r.phase == Phase.Cancelled, "League: round is not finished");
        require(!claimed[roundId][msg.sender], "League: already claimed");
        bool refund = r.phase == Phase.Cancelled;
        amount = _claimable(roundId, msg.sender);
        require(amount > 0, "League: nothing to claim");
        claimed[roundId][msg.sender] = true; // effects before the transfer
        (bool ok,) = payable(msg.sender).call{value: amount}("");
        require(ok, "League: transfer failed");
        emit Claimed(roundId, msg.sender, amount, refund);
    }

    // ───────────── views ─────────────

    function claimable(uint256 roundId, address who) external view returns (uint256) {
        return claimed[roundId][who] ? 0 : _claimable(roundId, who);
    }

    function getRound(uint256 roundId) external view returns (RoundInfo memory info) {
        Round storage r = _rounds[roundId];
        info.used = r.used;
        info.entryStake = r.entryStake;
        info.deadline = r.deadline;
        info.roundDuration = r.roundDuration;
        info.startedAt = r.startedAt;
        info.targetBlock = r.targetBlock;
        info.windowCount = r.windowCount;
        info.windowIndex = r.windowIndex;
        info.dataHash = r.dataHash;
        info.seed = r.seed;
        info.phase = r.phase;
        info.entryCount = r.entries.length;
        info.winnerCount = r.winnerCount;
        info.bestScore = r.bestScore;
        info.pot = r.pot;
        info.poolRoot = r.poolRoot;
        info.poolSize = r.poolSize;
    }

    function getEntry(uint256 roundId, uint256 index)
        external
        view
        returns (address owner, string memory name, bytes32[] memory tickers, uint16[] memory weightsBps, int256 score)
    {
        Round storage r = _rounds[roundId];
        Entry storage e = r.entries[index];
        tickers = new bytes32[](e.stocks.length);
        for (uint256 i = 0; i < e.stocks.length; i++) tickers[i] = r.used[e.stocks[i]];
        return (e.owner, e.name, tickers, e.weightsBps, e.score);
    }

    function getPrices(uint256 roundId) external view returns (uint256[] memory startPrice, uint256[] memory endPrice) {
        return (_rounds[roundId].startPrice, _rounds[roundId].endPrice);
    }

    /// Is this ticker in the round's pool? (Same check enter() makes.)
    function inPool(uint256 roundId, bytes32 ticker, bytes32[] calldata proof) external view returns (bool) {
        return _inPool(_rounds[roundId].poolRoot, ticker, proof);
    }

    /// Every entry's return right now (x 1e18) from the oracle's current prices: the live leaderboard.
    function liveScores(uint256 roundId) external view returns (int256[] memory scores) {
        Round storage r = _rounds[roundId];
        require(r.phase == Phase.Started || r.phase == Phase.Settled, "League: race has not started");
        uint256[] memory nowPrice = r.phase == Phase.Settled ? r.endPrice : _pricesNow(r.used);
        scores = new int256[](r.entries.length);
        for (uint256 i = 0; i < r.entries.length; i++) scores[i] = _score(r.entries[i], r.startPrice, nowPrice);
    }

    // ───────────── internals ─────────────

    /// Checks each stock (in the pool, no duplicates, weight >= 5%, total 100%) and adds new ones to the used list.
    function _checkStocks(
        uint256 roundId,
        Round storage r,
        bytes32[] calldata tickers,
        uint16[] calldata weightsBps,
        bytes32[][] calldata proofs
    ) private returns (uint16[] memory idx) {
        idx = new uint16[](tickers.length);
        uint256 total;
        for (uint256 i = 0; i < tickers.length; i++) {
            require(_inPool(r.poolRoot, tickers[i], proofs[i]), "League: stock is not in the pool");
            for (uint256 j = 0; j < i; j++) require(tickers[j] != tickers[i], "League: duplicate stock");
            require(weightsBps[i] >= MIN_WEIGHT_BPS, "League: each weight must be at least 5%");
            idx[i] = _use(roundId, r, tickers[i]);
            total += weightsBps[i];
        }
        require(total == BPS, "League: weights must add up to 100%");
    }

    /// The ticker's place in the used list; the first entry to use a ticker adds it (it now needs prices).
    function _use(uint256 roundId, Round storage r, bytes32 t) private returns (uint16) {
        uint256 u = _usedIndexPlus1[roundId][t];
        if (u == 0) {
            r.used.push(t);
            u = r.used.length;
            _usedIndexPlus1[roundId][t] = u;
        }
        return uint16(u - 1);
    }

    /// Merkle check: leaf = keccak256(ticker); each step hashes the pair in sorted order (no left/right flags).
    function _inPool(bytes32 root, bytes32 ticker, bytes32[] calldata proof) private pure returns (bool) {
        if (ticker == bytes32(0) || proof.length > MAX_PROOF) return false;
        bytes32 h = keccak256(abi.encodePacked(ticker));
        for (uint256 i = 0; i < proof.length; i++) {
            bytes32 s = proof[i];
            h = h < s ? keccak256(abi.encodePacked(h, s)) : keccak256(abi.encodePacked(s, h));
        }
        return h == root;
    }

    function _pricesNow(bytes32[] storage tickers) private view returns (uint256[] memory out) {
        out = new uint256[](tickers.length);
        for (uint256 i = 0; i < tickers.length; i++) {
            (uint256 p, uint256 ts) = oracle.priceOf(tickers[i]);
            require(p > 0, "League: a picked stock has no price");
            require(block.timestamp - ts <= MAX_PRICE_AGE, "League: a picked stock's price is stale");
            out[i] = p;
        }
    }

    /// Return x 1e18 = sum(weight_i x end_i / start_i) - 1, with weights in basis points.
    function _score(Entry storage e, uint256[] memory startP, uint256[] memory endP) private view returns (int256) {
        uint256 value; // portfolio value relative to start, x 1e18 x BPS
        for (uint256 i = 0; i < e.stocks.length; i++) {
            uint256 k = e.stocks[i];
            value += (uint256(e.weightsBps[i]) * endP[k] * 1e18) / startP[k];
        }
        return int256(value / BPS) - 1e18;
    }

    function _claimable(uint256 roundId, address who) private view returns (uint256) {
        Round storage r = _rounds[roundId];
        uint256 idx = entryOf[roundId][who];
        if (idx == 0) return 0;
        if (r.phase == Phase.Cancelled) return r.entryStake;
        if (r.phase != Phase.Settled || r.entries[idx - 1].score != r.bestScore) return 0;
        return r.pot / r.winnerCount;
    }
}
