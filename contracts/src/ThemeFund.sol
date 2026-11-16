// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {SimpleERC20} from "./SimpleERC20.sol";
import {ExposureOracle} from "./ExposureOracle.sol";
import {MockExchange} from "./MockExchange.sol";
import {MockUSDC} from "./MockUSDC.sol";
import {MockStock} from "./MockStock.sol";

/// @title ThemeFund
/// @notice A fund whose share token (e.g. $AIXO) is this contract. It holds a basket of
///         test stocks at target weights and follows a mandate that can never be changed.
///
///         How it works:
///         - deposit:  you pay test dollars, the fund buys the basket at its target weights
///                     and gives you shares at the current value per share (NAV).
///                     The very first deposit sets 1 share = $1.
///         - redeem:   you return shares, the fund sells your slice of every holding and
///                     pays you the dollars.
///         - NAV:      what everything the fund holds is worth = sum(shares held x oracle
///                     price) + cash.
///         - mandate:  the rules chosen at launch. They match the Python builder:
///             Avoid a theme -> every holding must be proven low for that theme
///                              (Limited or Limited (lower confidence)).
///             Want a theme  -> at least a set share of the fund's weight must be in
///                              High or Moderate names for that theme.
///           Any basket change is checked against the ExposureOracle BEFORE trading and
///           is rejected with a plain reason, e.g. "Mandate: Oil exposure too high".
///
///         Weights are in basis points: 10_000 = 100%, 1_500 = 15%. If the weights add up
///         to less than 100%, the rest is kept as cash (test dollars).
///         Dollar amounts use USDC's 6 decimals. Shares use 18 decimals.
///
///         Testnet / hackathon code: not audited.
contract ThemeFund is SimpleERC20 {
    enum RuleKind {
        Want,
        Avoid
    }

    struct Rule {
        bytes32 theme; // the theme's key in the oracle, e.g. bytes32("oil")
        string label; // the name shown in messages, e.g. "Oil"
        RuleKind kind;
        uint16 minWeightBps; // Want only: minimum weight in High + Moderate names. 0 for Avoid.
    }

    uint256 private constant BPS = 10_000;
    uint256 public constant MAX_HOLDINGS = 40;
    uint256 public constant MIN_DEPOSIT = 1e6; // $1

    /// Turns a first deposit of USDC (6 decimals) into shares (18 decimals) at $1 a share.
    uint256 private constant FIRST_SHARE_SCALE = 1e12;

    MockExchange public immutable exchange;
    ExposureOracle public immutable oracle;
    MockUSDC public immutable usdc;
    address public immutable manager;

    address[] private _stocks;
    uint16[] private _weights;
    Rule[] private _rules; // set once at launch; there is no function that changes them

    event Deposited(address indexed investor, uint256 usdcIn, uint256 sharesOut);
    event Redeemed(address indexed investor, uint256 sharesIn, uint256 usdcOut);
    event BasketChanged(address[] stocks, uint16[] weights);

    modifier onlyManager() {
        require(msg.sender == manager, "Fund: caller is not the manager");
        _;
    }

    constructor(
        string memory name_,
        string memory symbol_,
        address manager_,
        MockExchange exchange_,
        address[] memory stocks_,
        uint16[] memory weights_,
        Rule[] memory rules_
    ) SimpleERC20(name_, symbol_, 18) {
        require(manager_ != address(0), "Fund: manager is the zero address");
        manager = manager_;
        exchange = exchange_;
        oracle = exchange_.oracle();
        usdc = exchange_.usdc();

        for (uint256 i = 0; i < rules_.length; i++) {
            Rule memory rule = rules_[i];
            require(rule.theme != bytes32(0), "Fund: rule has no theme");
            require(bytes(rule.label).length > 0, "Fund: rule has no label");
            if (rule.kind == RuleKind.Want) {
                require(rule.minWeightBps > 0 && rule.minWeightBps <= BPS, "Fund: Want rule needs a minimum of 1-10000");
            } else {
                require(rule.minWeightBps == 0, "Fund: Avoid rule takes no minimum");
            }
            _rules.push(rule);
        }

        // The starting basket has to obey the mandate too.
        _checkBasket(stocks_, weights_);
        _stocks = stocks_;
        _weights = weights_;
        emit BasketChanged(stocks_, weights_);
    }

    // ───────────── buy in / cash out ─────────────

    /// Pay `usdcAmount` test dollars (approve the fund first) and receive shares at NAV.
    function deposit(uint256 usdcAmount) external returns (uint256 shares) {
        require(usdcAmount >= MIN_DEPOSIT, "Fund: deposit is below $1");

        // Value the fund BEFORE the new money arrives, so the price per share is fair.
        uint256 supply = totalSupply;
        uint256 navBefore = supply == 0 ? 0 : nav();
        shares = (supply == 0 || navBefore == 0) ? usdcAmount * FIRST_SHARE_SCALE : (usdcAmount * supply) / navBefore;
        require(shares > 0, "Fund: deposit too small for one share unit");

        require(usdc.transferFrom(msg.sender, address(this), usdcAmount), "Fund: USDC transfer failed");
        _buyBasket(usdcAmount);

        _mint(msg.sender, shares);
        emit Deposited(msg.sender, usdcAmount, shares);
    }

    /// Return `shares` and receive your slice of the fund's value in test dollars.
    function redeem(uint256 shares) external returns (uint256 usdcOut) {
        require(shares > 0, "Fund: redeem amount is zero");
        uint256 supply = totalSupply;
        require(balanceOf[msg.sender] >= shares, "Fund: not enough shares");

        // Your slice of the cash, measured before any sales add to it.
        usdcOut = (usdc.balanceOf(address(this)) * shares) / supply;

        // Your slice of every holding, sold at the oracle price.
        for (uint256 i = 0; i < _stocks.length; i++) {
            uint256 slice = (MockStock(_stocks[i]).balanceOf(address(this)) * shares) / supply;
            if (slice > 0) usdcOut += exchange.sell(_stocks[i], slice);
        }

        _burn(msg.sender, shares);
        require(usdc.transfer(msg.sender, usdcOut), "Fund: USDC transfer failed");
        emit Redeemed(msg.sender, shares, usdcOut);
    }

    // ───────────── changing the basket (manager only) ─────────────

    /// Add one stock at `weightBps`. Existing weights shrink in proportion to make room.
    /// Reverts with the mandate's reason if the new basket would break a rule.
    function addHolding(address stock, uint16 weightBps) external onlyManager {
        require(weightBps > 0 && weightBps <= BPS, "Fund: weight must be 1-10000");
        uint256 n = _stocks.length;
        address[] memory stocks_ = new address[](n + 1);
        uint16[] memory weights_ = new uint16[](n + 1);
        for (uint256 i = 0; i < n; i++) {
            stocks_[i] = _stocks[i];
            weights_[i] = uint16((uint256(_weights[i]) * (BPS - weightBps)) / BPS);
        }
        stocks_[n] = stock;
        weights_[n] = weightBps;
        _setBasket(stocks_, weights_);
    }

    /// Replace the whole basket. Reverts with the mandate's reason if it would break a rule.
    function rebalance(address[] calldata stocks_, uint16[] calldata weights_) external onlyManager {
        _setBasket(stocks_, weights_);
    }

    function _setBasket(address[] memory stocks_, uint16[] memory weights_) private {
        // 1. Check the mandate first. Nothing is traded if this fails.
        _checkBasket(stocks_, weights_);

        // 2. Sell everything the fund holds.
        for (uint256 i = 0; i < _stocks.length; i++) {
            uint256 qty = MockStock(_stocks[i]).balanceOf(address(this));
            if (qty > 0) exchange.sell(_stocks[i], qty);
        }

        // 3. Switch to the new basket and buy it with all the cash.
        _stocks = stocks_;
        _weights = weights_;
        _buyBasket(usdc.balanceOf(address(this)));
        emit BasketChanged(stocks_, weights_);
    }

    // ───────────── views ─────────────

    /// What the fund is worth in test dollars (6 decimals): holdings at oracle prices + cash.
    /// Reverts if any holding's price is missing or stale.
    function nav() public view returns (uint256 value) {
        value = usdc.balanceOf(address(this));
        for (uint256 i = 0; i < _stocks.length; i++) {
            uint256 qty = MockStock(_stocks[i]).balanceOf(address(this));
            if (qty > 0) value += exchange.quoteSell(_stocks[i], qty);
        }
    }

    /// Value of one whole share in test dollars (6 decimals). $1.00 before the first deposit.
    function navPerShare() external view returns (uint256) {
        return totalSupply == 0 ? 1e6 : (nav() * 1e18) / totalSupply;
    }

    /// Dry-run a basket against the mandate without sending a transaction (for the dashboard).
    /// ok = true and reason = "" if it passes, otherwise the plain-English reason.
    function checkMandate(address[] memory stocks_, uint16[] memory weights_)
        public
        view
        returns (bool ok, string memory reason)
    {
        if (stocks_.length != weights_.length) return (false, "Fund: list lengths differ");

        for (uint256 r = 0; r < _rules.length; r++) {
            Rule storage rule = _rules[r];
            uint256 exposedWeight; // weight in High + Moderate names for this theme

            for (uint256 i = 0; i < stocks_.length; i++) {
                ExposureOracle.Tier tier = oracle.tierOf(MockStock(stocks_[i]).ticker(), rule.theme);
                bool exposed = tier == ExposureOracle.Tier.High || tier == ExposureOracle.Tier.Moderate;
                bool provenLow =
                    tier == ExposureOracle.Tier.Limited || tier == ExposureOracle.Tier.LimitedLowerConfidence;

                if (rule.kind == RuleKind.Avoid) {
                    if (exposed) return (false, string.concat("Mandate: ", rule.label, " exposure too high"));
                    // Not determined (or never posted) means "the data can't tell", which is not zero.
                    if (!provenLow) {
                        return (false, string.concat("Mandate: ", rule.label, " exposure can't be ruled out"));
                    }
                } else if (exposed) {
                    exposedWeight += weights_[i];
                }
            }

            if (rule.kind == RuleKind.Want && exposedWeight < rule.minWeightBps) {
                return (false, string.concat("Mandate: ", rule.label, " exposure too low"));
            }
        }
        return (true, "");
    }

    /// Does the current basket still obey the mandate? (Tiers can change in the oracle.)
    function isCompliant() external view returns (bool ok, string memory reason) {
        return checkMandate(_stocks, _weights);
    }

    function basket() external view returns (address[] memory stocks_, uint16[] memory weights_) {
        return (_stocks, _weights);
    }

    function rules() external view returns (Rule[] memory) {
        return _rules;
    }

    // ───────────── internals ─────────────

    /// Reverts unless the basket is well formed AND obeys the mandate.
    function _checkBasket(address[] memory stocks_, uint16[] memory weights_) private view {
        uint256 n = stocks_.length;
        require(n > 0, "Fund: basket is empty");
        require(n == weights_.length, "Fund: list lengths differ");
        require(n <= MAX_HOLDINGS, "Fund: too many holdings");

        uint256 total;
        for (uint256 i = 0; i < n; i++) {
            require(exchange.isListed(stocks_[i]), "Fund: stock not listed on the exchange");
            require(weights_[i] > 0, "Fund: weight is zero");
            for (uint256 j = 0; j < i; j++) {
                require(stocks_[j] != stocks_[i], "Fund: stock appears twice");
            }
            total += weights_[i];
        }
        require(total <= BPS, "Fund: weights add up to more than 100%");

        (bool ok, string memory reason) = checkMandate(stocks_, weights_);
        require(ok, reason);
    }

    /// Spend `usdcAmount` across the basket at target weights. Any unallocated weight stays as cash.
    function _buyBasket(uint256 usdcAmount) private {
        for (uint256 i = 0; i < _stocks.length; i++) {
            uint256 spend = (usdcAmount * _weights[i]) / BPS;
            if (spend > 0) exchange.buy(_stocks[i], spend);
        }
    }
}
