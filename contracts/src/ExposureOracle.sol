// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title ExposureOracle
/// @notice The on-chain copy of the Python engine's results. For every stock it stores
///         the latest price, and for every (stock, theme) pair it stores the exposure
///         tier plus two fingerprints (hashes) of the data and statistics behind it.
///         Only the owner or an approved publisher (a wallet running chain/publish.py) can post.
///         The owner approves and removes publishers, so a team can share the work without
///         sharing a wallet.
///
///         Keys are short text packed into bytes32:
///           ticker = bytes32("NVDA")   theme = bytes32("oil")   (the theme file's `key`)
///         Prices are US dollars per one whole share with 8 decimals: $187.42 = 18_742_000_000.
///
///         Testnet / hackathon code: not audited.
contract ExposureOracle {
    /// The five tiers from the methodology, plus Unposted for "the engine has never
    /// posted a result for this stock and theme" (it is not a tier, just missing data).
    enum Tier {
        Unposted,
        High,
        Moderate,
        Limited,
        LimitedLowerConfidence,
        NotDetermined
    }

    struct Price {
        uint256 price; // USD per whole share, 8 decimals
        uint256 timestamp; // block time when it was posted
    }

    struct Exposure {
        Tier tier;
        bytes32 baselineHash; // fingerprint of the price data the regression used
        bytes32 statsHash; // fingerprint of the regression statistics
        uint256 timestamp; // block time when it was posted
    }

    uint8 public constant PRICE_DECIMALS = 8;

    address public owner;
    mapping(address account => bool) public isPublisher;
    mapping(bytes32 ticker => Price) private _prices;
    mapping(bytes32 ticker => mapping(bytes32 theme => Exposure)) private _exposures;

    event PricePosted(bytes32 indexed ticker, uint256 price, uint256 timestamp);
    event ExposurePosted(
        bytes32 indexed ticker,
        bytes32 indexed theme,
        Tier tier,
        bytes32 baselineHash,
        bytes32 statsHash,
        uint256 timestamp
    );
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event PublisherSet(address indexed account, bool allowed);

    modifier onlyOwner() {
        require(msg.sender == owner, "Oracle: caller is not the owner");
        _;
    }

    modifier onlyPublisher() {
        require(canPublish(msg.sender), "Oracle: caller is not a publisher");
        _;
    }

    constructor() {
        owner = msg.sender;
        emit OwnershipTransferred(address(0), msg.sender);
    }

    // ───────────── posting (owner or approved publishers) ─────────────

    function postPrice(bytes32 ticker, uint256 price) public onlyPublisher {
        require(ticker != bytes32(0), "Oracle: empty ticker");
        require(price > 0, "Oracle: price must be positive");
        _prices[ticker] = Price(price, block.timestamp);
        emit PricePosted(ticker, price, block.timestamp);
    }

    /// Post many prices in one transaction.
    function postPrices(bytes32[] calldata tickers, uint256[] calldata prices) external onlyPublisher {
        require(tickers.length == prices.length, "Oracle: list lengths differ");
        for (uint256 i = 0; i < tickers.length; i++) {
            postPrice(tickers[i], prices[i]);
        }
    }

    function postExposure(bytes32 ticker, bytes32 theme, Tier tier, bytes32 baselineHash, bytes32 statsHash)
        public
        onlyPublisher
    {
        require(ticker != bytes32(0), "Oracle: empty ticker");
        require(theme != bytes32(0), "Oracle: empty theme");
        require(tier != Tier.Unposted, "Oracle: tier must be one of the five tiers");
        _exposures[ticker][theme] = Exposure(tier, baselineHash, statsHash, block.timestamp);
        emit ExposurePosted(ticker, theme, tier, baselineHash, statsHash, block.timestamp);
    }

    /// Post many exposures in one transaction. Item i of every list belongs together.
    function postExposures(
        bytes32[] calldata tickers,
        bytes32[] calldata themes,
        Tier[] calldata tiers,
        bytes32[] calldata baselineHashes,
        bytes32[] calldata statsHashes
    ) external onlyPublisher {
        uint256 n = tickers.length;
        require(
            themes.length == n && tiers.length == n && baselineHashes.length == n && statsHashes.length == n,
            "Oracle: list lengths differ"
        );
        for (uint256 i = 0; i < n; i++) {
            postExposure(tickers[i], themes[i], tiers[i], baselineHashes[i], statsHashes[i]);
        }
    }

    // ───────────── access (owner only) ─────────────

    /// Approve (true) or remove (false) a wallet that may post prices and tiers.
    function setPublisher(address account, bool allowed) external onlyOwner {
        require(account != address(0), "Oracle: publisher is the zero address");
        isPublisher[account] = allowed;
        emit PublisherSet(account, allowed);
    }

    /// True for the owner and for every approved publisher.
    function canPublish(address account) public view returns (bool) {
        return account == owner || isPublisher[account];
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "Oracle: new owner is the zero address");
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    // ───────────── reading (anyone) ─────────────

    /// Latest price and when it was posted. Both are 0 if no price was ever posted.
    function priceOf(bytes32 ticker) external view returns (uint256 price, uint256 timestamp) {
        Price storage p = _prices[ticker];
        return (p.price, p.timestamp);
    }

    /// The stock's tier for a theme. Tier.Unposted if the engine never posted one.
    function tierOf(bytes32 ticker, bytes32 theme) external view returns (Tier) {
        return _exposures[ticker][theme].tier;
    }

    /// The full record: tier, both hashes and the posting time.
    function exposureOf(bytes32 ticker, bytes32 theme) external view returns (Exposure memory) {
        return _exposures[ticker][theme];
    }
}
