// Strategy knowledge base — descriptions, logic, and parameters for each strategy
// Used in the Strategy Overview panel on Level 2 drill-down

export interface StrategyInfo {
  displayName: string
  tagline: string
  description: string
  howItWorks: string[]
  signals: { buy: string; sell: string }
  bestConditions: string
  riskProfile: 'Low' | 'Medium' | 'High'
  typicalHoldDays: string
  keyParams: { name: string; description: string }[]
  category: 'Momentum' | 'Mean Reversion' | 'Breakout' | 'Trend Following' | 'Factor' | 'Volatility'
}

export const STRATEGY_KNOWLEDGE: Record<string, StrategyInfo> = {
  bollinger_pullback: {
    displayName: 'Bollinger Band Pullback',
    tagline: 'Buy the dip within the trend using Bollinger Band mean reversion',
    category: 'Mean Reversion',
    description:
      'A mean-reversion strategy that exploits temporary price dislocations from the 20-period Bollinger Band midline. When a stock is in an uptrend but price temporarily pulls back to the lower band, the system enters long expecting a rebound to the mean.',
    howItWorks: [
      'Computes 20-period SMA and 2× standard-deviation Bollinger Bands.',
      'Confirms a bullish macro trend using a longer 50-period moving average filter.',
      'Enters long when close price touches or crosses below the lower band in a rising trend.',
      'Exits when price returns to the upper band or the trend filter flips bearish.',
      'Applies a hard stop-loss at 2× ATR below entry to cap downside.',
    ],
    signals: {
      buy: 'Close ≤ Lower Band AND Close > 50-SMA (trend filter) AND RSI < 40',
      sell: 'Close ≥ Upper Band OR Close < 50-SMA OR Stop-Loss hit',
    },
    bestConditions: 'Range-bound to mildly trending markets. Struggles in strong trending phases when price rides the lower band.',
    riskProfile: 'Medium',
    typicalHoldDays: '5–20 days',
    keyParams: [
      { name: 'BB Period', description: '20 bars for band calculation' },
      { name: 'Multiplier', description: '2× standard deviations' },
      { name: 'Trend Filter', description: '50-period SMA' },
      { name: 'Stop', description: '2× ATR trailing stop' },
    ],
  },

  trend_following: {
    displayName: 'Trend Following',
    tagline: 'Ride sustained price momentum using dual moving average crossovers',
    category: 'Trend Following',
    description:
      'A classic dual-moving-average crossover system designed to capture large, sustained directional moves. The strategy accepts many small whipsaw losses in exchange for riding occasional large trends — producing a positively skewed return distribution.',
    howItWorks: [
      'Tracks a fast EMA (10-period) and a slow EMA (40-period) simultaneously.',
      'Generates a buy signal when the fast EMA crosses above the slow EMA.',
      'Generates a sell signal when the fast EMA crosses back below the slow EMA.',
      'Optionally confirms the signal with a volume surge filter to avoid false breakouts.',
      'Scales position size inversely to recent ATR so volatile stocks get smaller allocations.',
    ],
    signals: {
      buy: 'EMA(10) crosses above EMA(40) AND Volume > 1.5× 20-day avg volume',
      sell: 'EMA(10) crosses below EMA(40) OR Time-based stop (max hold = 60 days)',
    },
    bestConditions: 'Strongly trending, low-reversal markets (bull or bear runs). Poor in choppy sideways markets.',
    riskProfile: 'Medium',
    typicalHoldDays: '20–60 days',
    keyParams: [
      { name: 'Fast EMA', description: '10 bars' },
      { name: 'Slow EMA', description: '40 bars' },
      { name: 'Volume Filter', description: '1.5× 20-day average' },
      { name: 'Max Hold', description: '60 calendar days' },
    ],
  },

  rsi_pullback: {
    displayName: 'RSI Pullback',
    tagline: 'Capture oversold bounces using RSI momentum oscillator',
    category: 'Mean Reversion',
    description:
      'An oscillator-based mean-reversion strategy that buys short-term oversold dips within a bullish structural trend. The RSI is used purely as a timing tool — the 200-SMA ensures trades are only taken in stocks with positive long-term momentum.',
    howItWorks: [
      'Calculates 14-period RSI to measure short-term momentum exhaustion.',
      'Requires the stock to be above its 200-day SMA (long-term bullish bias).',
      'Enters long when RSI drops below 30 (oversold territory).',
      'Exits when RSI recovers above 60 or a time-based stop triggers after 15 days.',
      'Uses a fixed 5% stop-loss below the entry price as emergency protection.',
    ],
    signals: {
      buy: 'RSI(14) < 30 AND Close > SMA(200)',
      sell: 'RSI(14) > 60 OR Days held > 15 OR Price drops 5% from entry',
    },
    bestConditions: 'Healthy bull markets with frequent minor pullbacks. Underperforms in deep bear markets where RSI stays oversold for extended periods.',
    riskProfile: 'Low',
    typicalHoldDays: '5–15 days',
    keyParams: [
      { name: 'RSI Period', description: '14 bars' },
      { name: 'Oversold Threshold', description: 'RSI < 30' },
      { name: 'Exit Threshold', description: 'RSI > 60' },
      { name: 'Trend Filter', description: '200-period SMA' },
    ],
  },

  cross_sectional_momentum: {
    displayName: 'Cross-Sectional Momentum',
    tagline: 'Long the top-decile and short the bottom-decile performers in the universe',
    category: 'Momentum',
    description:
      'A systematic factor strategy that ranks all stocks in the universe by their 12-1 month price momentum (total return from 12 months ago to 1 month ago). It goes long the top 10% (winners) and can optionally short the bottom 10% (losers). Rebalanced monthly.',
    howItWorks: [
      'At each monthly rebalance, calculates 12-1 month trailing returns for all universe stocks.',
      'Sorts all stocks by momentum score and assigns decile ranks.',
      'Allocates equal weight to the top decile (long book) and bottom decile (short book).',
      'Holds for one calendar month before the next rebalance signal.',
      'Transaction costs are factored into trade sizing to avoid over-trading small positions.',
    ],
    signals: {
      buy: 'Stock rank in top 10% by 12-1 month return at monthly rebalance date',
      sell: 'Stock drops out of top 20% at next rebalance date OR held > 1 month',
    },
    bestConditions: 'Any sustained trending environment. Momentum crashes during sharp market reversals after extended rallies.',
    riskProfile: 'High',
    typicalHoldDays: '20–30 days (monthly rebalance)',
    keyParams: [
      { name: 'Lookback', description: '12-month return, skip last month' },
      { name: 'Long Pct', description: 'Top 10% of universe' },
      { name: 'Rebalance', description: 'Monthly' },
      { name: 'Universe', description: 'NIFTY 200 stocks' },
    ],
  },

  donchian_trend: {
    displayName: 'Donchian Channel Trend',
    tagline: 'Enter on 20-day high breakouts, exit on 10-day low breakdown',
    category: 'Breakout',
    description:
      'A classical Turtle-trading style breakout system using Donchian Channels. The strategy enters when price makes a 20-bar high (breakout) and exits when it makes a 10-bar low (breakdown). This asymmetry between entry and exit channels creates a wider net for catching trends.',
    howItWorks: [
      'Computes Donchian Channels: Upper = 20-bar high, Lower = 10-bar low.',
      'Generates a buy when today\'s close exceeds the 20-bar high.',
      'Trail stop is set at the 10-bar low, which tightens as price rises.',
      'Position size is set using a 1% risk-per-trade rule based on ATR.',
      'No profit target — the trade is held until the trailing stop fires.',
    ],
    signals: {
      buy: 'Close > Highest High of last 20 bars',
      sell: 'Close < Lowest Low of last 10 bars (trailing)',
    },
    bestConditions: 'Trending markets with good follow-through. Generates frequent false breakouts in choppy or range-bound conditions.',
    riskProfile: 'High',
    typicalHoldDays: '20–90 days',
    keyParams: [
      { name: 'Entry Channel', description: '20-bar highest high' },
      { name: 'Exit Channel', description: '10-bar lowest low' },
      { name: 'Risk per Trade', description: '1% of portfolio' },
      { name: 'Sizing', description: 'ATR-normalized units' },
    ],
  },

  donchian_breakout: {
    displayName: 'Donchian Breakout',
    tagline: 'Symmetrical breakout system using 55-day Donchian channels',
    category: 'Breakout',
    description:
      'A longer-period variant of the Donchian breakout system that uses symmetrical 55-bar channels for both entry and exit. Designed to catch only the largest, highest-conviction breakouts while filtering out short-term noise.',
    howItWorks: [
      'Computes 55-bar highest high and lowest low to form the channel.',
      'Enters long on a close above the 55-bar high (major breakout).',
      'Enters short on a close below the 55-bar low (major breakdown).',
      'Exit is triggered when price closes beyond the opposite boundary.',
      'Uses unit-based position sizing with a maximum of 4 units per position.',
    ],
    signals: {
      buy: 'Close > Max High(55 bars)',
      sell: 'Close < Min Low(55 bars) OR Reversal signal',
    },
    bestConditions: 'Major trending markets. Very patient system — expects few trades per year per stock.',
    riskProfile: 'High',
    typicalHoldDays: '30–180 days',
    keyParams: [
      { name: 'Channel Period', description: '55 bars (symmetric)' },
      { name: 'Max Units', description: '4 per position' },
      { name: 'Add-on Rule', description: 'Add 1 unit every 0.5× ATR move in favour' },
    ],
  },

  mean_reversion: {
    displayName: 'Mean Reversion',
    tagline: 'Statistical arbitrage on short-term price deviations from rolling mean',
    category: 'Mean Reversion',
    description:
      'A statistically driven strategy that exploits price deviations from a rolling mean. It measures how many standard deviations the current price is from its 20-day average and bets on reversion when the z-score exceeds a threshold.',
    howItWorks: [
      'Calculates a 20-period rolling mean and standard deviation.',
      'Computes z-score = (Price - Mean) / StdDev at every bar.',
      'Enters long when z-score < -2 (price is 2 std-devs below mean).',
      'Enters short when z-score > +2 (price is 2 std-devs above mean).',
      'Exits when z-score reverts to 0 (price returns to mean) or time stop hits.',
    ],
    signals: {
      buy: 'Z-Score < -2.0',
      sell: 'Z-Score > 0 OR days held > 10',
    },
    bestConditions: 'Calm, sideways markets. Severely underperforms in trending markets where price moves away from mean indefinitely.',
    riskProfile: 'Medium',
    typicalHoldDays: '3–10 days',
    keyParams: [
      { name: 'Lookback', description: '20 bars for mean/std calculation' },
      { name: 'Entry Z-score', description: '±2.0 standard deviations' },
      { name: 'Exit Z-score', description: '0 (return to mean)' },
      { name: 'Max Hold', description: '10 days time stop' },
    ],
  },

  volume_confirmed_breakout: {
    displayName: 'Volume Confirmed Breakout',
    tagline: 'Only act on breakouts backed by a surge in trading volume',
    category: 'Breakout',
    description:
      'A price breakout strategy with a volume confirmation filter. The thesis is that valid breakouts are accompanied by large institutional participation, visible as a volume surge. Without the volume spike, the breakout is considered suspect.',
    howItWorks: [
      'Identifies 20-bar resistance levels using rolling highs.',
      'Triggers a buy signal only when price breaks the resistance AND volume exceeds 2× its 20-day average.',
      'Sets initial stop-loss at the resistance level that was just broken (now support).',
      'Scales up position size on the second day if price continues to rise.',
      'Exits when the stock closes below its 10-bar EMA.',
    ],
    signals: {
      buy: 'Close > Highest High(20) AND Volume > 2× Avg Volume(20)',
      sell: 'Close < EMA(10) OR Stop at prior resistance',
    },
    bestConditions: 'Breakout-heavy markets with good volume participation. Performs best after consolidation periods.',
    riskProfile: 'Medium',
    typicalHoldDays: '10–30 days',
    keyParams: [
      { name: 'Resistance Period', description: '20 bars' },
      { name: 'Volume Multiplier', description: '2× 20-day average' },
      { name: 'Exit EMA', description: '10 periods' },
    ],
  },

  volatility_contraction_breakout: {
    displayName: 'Volatility Contraction Breakout',
    tagline: 'Buy when volatility squeezes then expands — catching the spring-loaded move',
    category: 'Volatility',
    description:
      'Inspired by Mark Minervini\'s Volatility Contraction Pattern (VCP), this strategy identifies stocks in a multi-week tightening pattern where price ranges and volume are contracting. When the stock breaks out of this pattern on volume, a large move tends to follow.',
    howItWorks: [
      'Detects volatility contractions by measuring the ratio of current ATR to 50-day average ATR.',
      'Confirms the squeeze: current ATR < 0.5× 50-day ATR for at least 10 consecutive bars.',
      'Waits for a breakout candle where price closes above the recent 10-bar high.',
      'Volume on the breakout bar must be > 1.5× 20-day average volume.',
      'Stop is placed below the lowest low of the contraction zone.',
    ],
    signals: {
      buy: 'ATR(14)/AvgATR(50) < 0.5 for 10+ bars AND Close > High(10) AND Volume > 1.5× avg',
      sell: 'Close < Contraction zone low OR ATR expands without price followthrough',
    },
    bestConditions: 'Post-consolidation breakouts in bull markets. Excellent in environments where leading stocks are setting up.',
    riskProfile: 'Medium',
    typicalHoldDays: '15–45 days',
    keyParams: [
      { name: 'ATR Period', description: '14 bars' },
      { name: 'Squeeze Ratio', description: 'ATR/AvgATR < 0.5' },
      { name: 'Min Squeeze Bars', description: '10 consecutive bars' },
      { name: 'Volume Confirmation', description: '1.5× 20-day average' },
    ],
  },

  time_series_momentum: {
    displayName: 'Time-Series Momentum',
    tagline: 'Bet on the direction of each stock\'s own recent trend (TSMOM)',
    category: 'Momentum',
    description:
      'Unlike cross-sectional momentum which ranks stocks against each other, time-series momentum looks at each stock independently. If a stock\'s own 12-month return is positive, go long. If negative, go short (or stay flat). Rebalanced monthly.',
    howItWorks: [
      'At monthly rebalance: if 12-1 month return is positive, take a long position.',
      'If 12-1 month return is negative, take a short position (or move to cash).',
      'Position size is inverse-volatility weighted (allocate more to low-vol stocks).',
      'Holds for one month before re-evaluating.',
      'Cap on maximum exposure per stock at 10% of total portfolio.',
    ],
    signals: {
      buy: 'Own 12-month return > 0 at monthly rebalance',
      sell: 'Own 12-month return < 0 at next rebalance OR Risk limit hit',
    },
    bestConditions: 'Markets with persistent trends at the individual stock level. Struggles in reversal environments.',
    riskProfile: 'Medium',
    typicalHoldDays: '20–30 days',
    keyParams: [
      { name: 'Lookback', description: '12 months, skip last month' },
      { name: 'Sizing', description: 'Inverse volatility weighted' },
      { name: 'Rebalance', description: 'Monthly' },
      { name: 'Max per stock', description: '10% of portfolio' },
    ],
  },

  opening_range_breakout: {
    displayName: 'Opening Range Breakout',
    tagline: 'Trade the first 30-minute range breakout at market open',
    category: 'Breakout',
    description:
      'A day-trading/swing strategy that uses the first 30 minutes of the trading session to define a range. A breakout above the range high is a long signal; below the range low is a short signal. Most effective on liquid large-cap stocks.',
    howItWorks: [
      'Defines the Opening Range (OR) as the High and Low of the first 30-minute bar.',
      'Enters long when intraday price breaks above the OR High with above-average volume.',
      'Enters short when intraday price breaks below the OR Low.',
      'Sets a 1:2 risk-reward target: stop = OR width, target = 2× OR width.',
      'All positions are closed at end of day if not already stopped or targeted.',
    ],
    signals: {
      buy: 'Price > OR High AND Volume > 1.2× 5-day average',
      sell: 'Price Target hit (entry + 2× OR width) OR Stop hit OR EOD exit',
    },
    bestConditions: 'High-volatility opens, earnings releases, major news events. Poor on quiet, low-volume days.',
    riskProfile: 'High',
    typicalHoldDays: 'Intraday to 1–2 days',
    keyParams: [
      { name: 'OR Window', description: 'First 30 minutes' },
      { name: 'Risk:Reward', description: '1:2 target' },
      { name: 'Volume Filter', description: '1.2× 5-day average' },
      { name: 'Exit', description: 'EOD hard exit' },
    ],
  },

  walk_forward_logistic: {
    displayName: 'Walk-Forward Logistic Regression',
    tagline: 'ML model trained on rolling windows predicts next-day direction',
    category: 'Factor',
    description:
      'A machine-learning strategy using logistic regression trained on a rolling 252-day window of technical features (RSI, MACD, volume ratios, ATR). It predicts the probability of an up-day for the next session, going long when probability > 55%.',
    howItWorks: [
      'Computes a feature vector of 8 technical indicators at each bar.',
      'Trains a logistic regression model on the prior 252-day window.',
      'Predicts probability of next-day up-move.',
      'Goes long if P(up) > 55%, flat/short if P(up) < 45%.',
      'Re-trains the model every 21 trading days (monthly walk-forward).',
    ],
    signals: {
      buy: 'Logistic model P(up) > 0.55',
      sell: 'P(up) < 0.45 OR Max hold 5 days',
    },
    bestConditions: 'Markets with persistent short-term predictability from technical factors.',
    riskProfile: 'Medium',
    typicalHoldDays: '1–5 days',
    keyParams: [
      { name: 'Training Window', description: '252 trading days' },
      { name: 'Retrain Frequency', description: 'Every 21 days' },
      { name: 'Long Threshold', description: 'P(up) > 55%' },
      { name: 'Features', description: 'RSI, MACD, Vol ratio, ATR, BB position' },
    ],
  },

  low_volatility: {
    displayName: 'Low Volatility Factor',
    tagline: 'Own the calmest stocks — low vol anomaly generates risk-adjusted alpha',
    category: 'Factor',
    description:
      'Based on the empirical low-volatility anomaly: historically, lower-volatility stocks outperform higher-volatility stocks on a risk-adjusted basis. The strategy ranks all stocks by 252-day realized volatility and holds the bottom quintile.',
    howItWorks: [
      'Ranks all universe stocks by 252-day realized volatility (annualized).',
      'Holds the bottom quintile (20% lowest-volatility stocks).',
      'Equal-weights the portfolio across selected stocks.',
      'Rebalances monthly, replacing any stock that exits the bottom quintile.',
    ],
    signals: {
      buy: 'Stock in bottom 20% by 252-day annualized vol at rebalance',
      sell: 'Stock exits bottom 30% at next rebalance',
    },
    bestConditions: 'Defensive market environments. Outperforms during high-uncertainty periods and underperforms in strong bull markets.',
    riskProfile: 'Low',
    typicalHoldDays: '30+ days',
    keyParams: [
      { name: 'Vol Lookback', description: '252 trading days' },
      { name: 'Selection', description: 'Bottom 20% by volatility' },
      { name: 'Weighting', description: 'Equal weight' },
      { name: 'Rebalance', description: 'Monthly' },
    ],
  },
}

// Fallback for unknown strategies
export function getStrategyInfo(name: string): StrategyInfo {
  if (STRATEGY_KNOWLEDGE[name]) return STRATEGY_KNOWLEDGE[name]

  // Generate a reasonable fallback
  const words = name.split('_').map((w) => w.charAt(0).toUpperCase() + w.slice(1))
  return {
    displayName: words.join(' '),
    tagline: `Quantitative ${name} strategy`,
    category: 'Momentum',
    description: `The ${words.join(' ')} strategy is a systematic quantitative approach implemented in the trading platform. Run the strategy to populate detailed analytics.`,
    howItWorks: ['Strategy details not yet documented. Check strategy source code for implementation details.'],
    signals: { buy: 'See strategy source code', sell: 'See strategy source code' },
    bestConditions: 'Refer to strategy documentation.',
    riskProfile: 'Medium',
    typicalHoldDays: 'Varies',
    keyParams: [],
  }
}
