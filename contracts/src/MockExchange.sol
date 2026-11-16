// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {ExposureOracle} from "./ExposureOracle.sol";
import {MockUSDC} from "./MockUSDC.sol";
import {MockStock} from "./MockStock.sol";

/// @title MockExchange
/// @notice A pretend stock market for testnet. There are no other traders: buying
///         destroys your test dollars and creates test shares at the oracle's price, and
///         selling does the reverse. No fees, no slippage.
///
///         It refuses to trade when a stock's price is missing or more than 7 days old,
///         so nobody can trade on a price the engine has stopped updating.
///
///         Listing new stocks is for the owner or an approved publisher (the same team
///         wallets that post to the oracle). The owner can hand ownership to another wallet.
///
///         Units: USDC has 6 decimals, stocks have 18, oracle prices have 8.
///           shares = dollars / price   ->  qty  = usdcAmount * 1e20 / price
///           dollars = shares * price   ->  usdc = qty * price / 1e20
contract MockExchange {
    uint256 public constant MAX_PRICE_AGE = 7 days;

    /// 10^(18 stock decimals + 8 price decimals - 6 USDC decimals)
    uint256 private constant SCALE = 1e20;

    ExposureOracle public immutable oracle;
    MockUSDC public immutable usdc;
    address public owner;
    mapping(address account => bool) public isPublisher;

    mapping(bytes32 ticker => address stock) public stockOf;
    mapping(address stock => bool) public isListed;
    address[] private _stocks;

    event StockListed(bytes32 indexed ticker, address stock);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event PublisherSet(address indexed account, bool allowed);
    event Bought(address indexed buyer, address indexed stock, uint256 usdcIn, uint256 qtyOut, uint256 price);
    event Sold(address indexed seller, address indexed stock, uint256 qtyIn, uint256 usdcOut, uint256 price);

    modifier onlyOwner() {
        require(msg.sender == owner, "Exchange: caller is not the owner");
        _;
    }

    modifier onlyPublisher() {
        require(canPublish(msg.sender), "Exchange: caller is not a publisher");
        _;
    }

    constructor(ExposureOracle oracle_) {
        oracle = oracle_;
        owner = msg.sender;
        usdc = new MockUSDC(address(this));
        emit OwnershipTransferred(address(0), msg.sender);
    }

    // ───────────── access (owner only) ─────────────

    /// Approve (true) or remove (false) a wallet that may list stocks.
    function setPublisher(address account, bool allowed) external onlyOwner {
        require(account != address(0), "Exchange: publisher is the zero address");
        isPublisher[account] = allowed;
        emit PublisherSet(account, allowed);
    }

    /// True for the owner and for every approved publisher.
    function canPublish(address account) public view returns (bool) {
        return account == owner || isPublisher[account];
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "Exchange: new owner is the zero address");
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    // ───────────── listing (owner or approved publishers) ─────────────

    /// Create the test token for one ticker, e.g. listStock("NVIDIA Corporation", "NVDA").
    function listStock(string calldata name, string calldata symbol) external onlyPublisher returns (address stock) {
        MockStock created = new MockStock(name, symbol, address(this));
        bytes32 ticker = created.ticker();
        require(stockOf[ticker] == address(0), "Exchange: ticker already listed");
        stock = address(created);
        stockOf[ticker] = stock;
        isListed[stock] = true;
        _stocks.push(stock);
        emit StockListed(ticker, stock);
    }

    function allStocks() external view returns (address[] memory) {
        return _stocks;
    }

    // ───────────── prices ─────────────

    /// The oracle price for a listed stock (USD per whole share, 8 decimals).
    /// Reverts if the stock isn't listed, has no price, or the price is over 7 days old.
    function priceOf(address stock) public view returns (uint256 price) {
        require(isListed[stock], "Exchange: stock not listed");
        uint256 timestamp;
        (price, timestamp) = oracle.priceOf(MockStock(stock).ticker());
        require(price > 0, "Exchange: no price posted");
        require(block.timestamp - timestamp <= MAX_PRICE_AGE, "Exchange: price is stale");
    }

    /// How many share units `usdcAmount` buys right now.
    function quoteBuy(address stock, uint256 usdcAmount) public view returns (uint256 qty) {
        return (usdcAmount * SCALE) / priceOf(stock);
    }

    /// How many USDC units selling `qty` share units pays right now.
    function quoteSell(address stock, uint256 qty) public view returns (uint256 usdcAmount) {
        return (qty * priceOf(stock)) / SCALE;
    }

    // ───────────── trading (anyone) ─────────────

    /// Spend `usdcAmount` of the caller's test dollars on `stock` at the oracle price.
    function buy(address stock, uint256 usdcAmount) external returns (uint256 qty) {
        uint256 price = priceOf(stock);
        qty = (usdcAmount * SCALE) / price;
        require(qty > 0, "Exchange: amount too small");
        usdc.burn(msg.sender, usdcAmount);
        MockStock(stock).mint(msg.sender, qty);
        emit Bought(msg.sender, stock, usdcAmount, qty, price);
    }

    /// Sell `qty` share units of the caller's `stock` for test dollars at the oracle price.
    function sell(address stock, uint256 qty) external returns (uint256 usdcAmount) {
        uint256 price = priceOf(stock);
        require(qty > 0, "Exchange: amount too small");
        usdcAmount = (qty * price) / SCALE;
        MockStock(stock).burn(msg.sender, qty);
        usdc.mint(msg.sender, usdcAmount);
        emit Sold(msg.sender, stock, qty, usdcAmount, price);
    }
}
