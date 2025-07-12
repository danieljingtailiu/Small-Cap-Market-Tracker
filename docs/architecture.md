# 🏗️ System Architecture

## Overview

The Small-Cap Market Tracker follows a modular architecture designed for scalability, maintainability, and real-time performance.

## Core Components

### 1. Data Layer
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Yahoo Finance │    │   Polygon.io    │    │  Alpha Vantage  │
│   (Primary)     │    │   (Optional)    │    │   (Optional)    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                    ┌─────────────────┐
                    │   Data Fetcher  │
                    │   (Rate Limited)│
                    └─────────────────┘
```

### 2. Processing Pipeline
```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│   Market    │  │   Options   │  │    Risk     │  │  Portfolio  │
│   Scanner   │─▶│  Analyzer   │─▶│   Manager   │─▶│   Manager   │
└─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘
       │                │                │                │
       ▼                ▼                ▼                ▼
┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│ Stock Filter│  │ Greeks Calc │  │ VaR/CVaR    │  │ P&L Track   │
│ Technical   │  │ Liquidity   │  │ Correlation │  │ Position    │
│ Patterns    │  │ Scoring     │  │ Risk        │  │ Sizing      │
└─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘
```

### 3. Configuration Management
```
┌─────────────────────────────────────────────────────────────┐
│                    Configuration Layer                      │
├─────────────────────────────────────────────────────────────┤
│  Trading Config  │  Scanner Config  │  Data Config       │
│  • Market Caps   │  • Growth Rates  │  • API Keys        │
│  • Position Size │  • PE Ratios     │  • Cache Settings  │
│  • Stop Losses   │  • Patterns      │  • Rate Limits     │
│  • Profit Targets│  • Ownership     │  • Refresh Intervals│
└─────────────────────────────────────────────────────────────┘
```

## Data Flow

### 1. Market Scanning Flow
```
1. Fetch Stock Universe
   ├── NASDAQ API (screener)
   ├── Yahoo Finance (trending)
   └── Known high-volume stocks

2. Apply Filters
   ├── Market cap range
   ├── Volume requirements
   ├── Fundamental criteria
   └── Technical indicators

3. Enrich Data
   ├── Current quotes
   ├── Options chains
   ├── Greeks calculation
   └── Risk metrics

4. Score & Rank
   ├── Liquidity scoring
   ├── Risk/reward analysis
   ├── Expected returns
   └── Portfolio fit
```

### 2. Options Analysis Flow
```
Option Contract
       │
       ▼
┌─────────────────┐
│  Moneyness      │ ← Strike vs Current Price
│  Analysis       │
└─────────────────┘
       │
       ▼
┌─────────────────┐
│  Time Value     │ ← Days to Expiration
│  Analysis       │   Theta Decay
└─────────────────┘
       │
       ▼
┌─────────────────┐
│  Liquidity      │ ← Volume, OI, Spread
│  Analysis       │
└─────────────────┘
       │
       ▼
┌─────────────────┐
│  Greeks         │ ← Delta, Gamma, Vega
│  Analysis       │
└─────────────────┘
       │
       ▼
┌─────────────────┐
│  Volatility     │ ← IV, IV Percentile
│  Analysis       │
└─────────────────┘
       │
       ▼
┌─────────────────┐
│  Risk/Reward    │ ← Expected Return
│  Analysis       │   Probability of Profit
└─────────────────┘
       │
       ▼
┌─────────────────┐
│  Final Score    │ ← Weighted Combination
│  & Ranking      │
└─────────────────┘
```

## Risk Management Architecture

### Portfolio Risk Metrics
```
┌─────────────────────────────────────────────────────────────┐
│                    Risk Dashboard                          │
├─────────────────────────────────────────────────────────────┤
│  Position Risk  │  Portfolio Risk  │  Market Risk        │
│  • Greeks       │  • VaR (95%)     │  • Correlation      │
│  • Theta Decay  │  • CVaR (95%)    │  • Sector Exposure  │
│  • IV Percentile│  • Max Drawdown  │  • Concentration    │
│  • Liquidity    │  • Sharpe Ratio  │  • Volatility       │
└─────────────────────────────────────────────────────────────┘
```

### Risk Calculation Pipeline
```
1. Position-Level Risk
   ├── Greeks aggregation
   ├── Theta decay calculation
   ├── Liquidity assessment
   └── Individual VaR

2. Portfolio-Level Risk
   ├── Correlation matrix
   ├── Sector concentration
   ├── Total portfolio VaR
   └── Maximum drawdown

3. Market-Level Risk
   ├── Volatility regime
   ├── Market correlation
   ├── Sector rotation
   └── Macro indicators
```

## Performance Monitoring

### Real-Time Metrics
```
┌─────────────────────────────────────────────────────────────┐
│                    Performance Dashboard                    │
├─────────────────────────────────────────────────────────────┤
│  Daily P&L      │  Total P&L      │  Win Rate           │
│  $1,250         │  $15,750        │  62.2%              │
├─────────────────────────────────────────────────────────────┤
│  Sharpe Ratio   │  Max Drawdown   │  Profit Factor      │
│  1.85           │  8.5%           │  1.95               │
├─────────────────────────────────────────────────────────────┤
│  Active Positions│  Avg Position   │  Largest Position   │
│  12             │  $8,500         │  5.2%               │
└─────────────────────────────────────────────────────────────┘
```

## Caching Strategy

### Multi-Level Caching
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Memory Cache  │    │   File Cache    │    │   API Cache     │
│   (Short-term)  │    │   (Medium-term) │    │   (Rate Limit)  │
│   • Quotes      │    │   • Stock Data  │    │   • Options     │
│   • Greeks      │    │   • Fundamentals│    │   • Historical  │
│   • 5 min TTL   │    │   • 24h TTL    │    │   • 1h TTL      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Error Handling & Resilience

### Fault Tolerance
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Rate Limiting │    │   Retry Logic   │    │   Fallback Data │
│   • API Limits  │    │   • Exponential │    │   • Cached Data │
│   • Jitter      │    │   • Backoff     │    │   • Defaults    │
│   • Queuing     │    │   • Max Retries │    │   • Estimates   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Scalability Considerations

### Horizontal Scaling
- **Data Processing**: Batch processing with configurable batch sizes
- **API Calls**: Rate limiting and connection pooling
- **Caching**: Multi-level cache with TTL management
- **Monitoring**: Real-time metrics with minimal overhead

### Performance Optimization
- **Lazy Loading**: Load data only when needed
- **Parallel Processing**: Concurrent API calls where possible
- **Memory Management**: Efficient data structures and cleanup
- **Database**: File-based storage with JSON serialization 