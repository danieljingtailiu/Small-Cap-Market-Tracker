# 🔄 System Flow Diagram

## Overview

This diagram shows how data flows through the Small-Cap Market Tracker system, from initial stock screening to final recommendations.

## Main System Flow

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           SMALL-CAP MARKET TRACKER                            │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Data Sources  │    │   Processing    │    │   Output        │
│                 │    │   Pipeline      │    │                 │
├─────────────────┤    ├─────────────────┤    ├─────────────────┤
│ • Yahoo Finance │    │ • Market Scanner│    │ • Top 10        │
│ • Polygon.io    │───▶│ • Options Analyzer│───▶│   Recommendations│
│ • Alpha Vantage │    │ • Risk Manager  │    │ • Risk Metrics  │
│ • NASDAQ API    │    │ • Portfolio Mgr │    │ • Performance   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Rate Limiting │    │   Scoring &     │    │   Monitoring    │
│   & Caching     │    │   Ranking       │    │   & Alerts      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Detailed Process Flow

### Phase 1: Stock Discovery
```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              STOCK DISCOVERY                                   │
└─────────────────────────────────────────────────────────────────────────────────┘

1. Fetch Stock Universe
   ├── NASDAQ Screener API (5,000+ stocks)
   ├── Yahoo Finance Trending (500 stocks)
   ├── Known High-Volume Stocks (100 stocks)
   └── Total: ~5,600 unique tickers

2. Apply Market Cap Filter
   ├── Market Cap: $1B - $100B
   ├── Volume: >2M daily volume
   ├── Price: >$1.00 per share
   └── Result: ~1,200 candidates

3. Enrich with Current Data
   ├── Real-time quotes
   ├── Fundamental data
   ├── Technical indicators
   └── Options availability
```

### Phase 2: Technical Analysis
```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           TECHNICAL ANALYSIS                                   │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│   RSI       │  │   Moving    │  │   Volume    │  │   Pattern    │
│   Analysis  │  │   Averages  │  │   Analysis  │  │ Recognition │
└─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘
       │                │                │                │
       ▼                ▼                ▼                ▼
┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│ Oversold    │  │ Price > MA  │  │ Volume >    │  │ Breakout    │
│ < 30        │  │ 20 & 50     │  │ Avg Volume  │  │ Patterns    │
└─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘
       │                │                │                │
       └────────────────┼────────────────┼────────────────┘
                        ▼
              ┌─────────────────┐
              │   Technical     │
              │   Score         │
              │   (0-100)       │
              └─────────────────┘
```

### Phase 3: Options Analysis
```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            OPTIONS ANALYSIS                                    │
└─────────────────────────────────────────────────────────────────────────────────┘

For each stock with options:

┌─────────────────┐
│  Get Options    │
│  Chain          │
└─────────────────┘
         │
         ▼
┌─────────────────┐
│  Filter by      │
│  Expiration     │
│  (20-70 days)   │
└─────────────────┘
         │
         ▼
┌─────────────────┐
│  Filter by      │
│  Strike Range   │
│  (85%-120%)     │
└─────────────────┘
         │
         ▼
┌─────────────────┐
│  Calculate      │
│  Greeks         │
│  (Delta, Theta, │
│   Gamma, Vega)  │
└─────────────────┘
         │
         ▼
┌─────────────────┐
│  Score Option   │
│  (0-100)        │
└─────────────────┘
```

### Phase 4: Risk Management
```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           RISK MANAGEMENT                                     │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  Position   │  │  Portfolio  │  │  Market     │  │  Greeks     │
│  Sizing     │  │  Risk       │  │  Risk       │  │  Risk       │
└─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘
       │                │                │                │
       ▼                ▼                ▼                ▼
┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│ Kelly       │  │ VaR/CVaR    │  │ Correlation │  │ Theta Decay │
│ Criterion   │  │ Calculation  │  │ Analysis    │  │ Monitoring  │
└─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘
       │                │                │                │
       └────────────────┼────────────────┼────────────────┘
                        ▼
              ┌─────────────────┐
              │   Risk Score    │
              │   (0-100)       │
              └─────────────────┘
```

### Phase 5: Final Ranking
```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              FINAL RANKING                                    │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  Technical  │  │  Options    │  │  Risk       │  │  Portfolio  │
│  Score      │  │  Score      │  │  Score      │  │  Fit        │
│  (25%)      │  │  (50%)      │  │  (15%)      │  │  (10%)      │
└─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘
       │                │                │                │
       └────────────────┼────────────────┼────────────────┘
                        ▼
              ┌─────────────────┐
              │   Final Score   │
              │   (0-100)       │
              └─────────────────┘
                        │
                        ▼
              ┌─────────────────┐
              │   Top 10        │
              │   Recommendations│
              └─────────────────┘
```

## Data Flow Timeline

```
Time: 0s    5s    10s   15s   20s   25s   30s
      │     │     │     │     │     │     │
      ▼     ▼     ▼     ▼     ▼     ▼     ▼
┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐
│Fetch│ │Filter│ │Enrich│ │Tech  │ │Options│ │Risk  │ │Rank  │
│Stocks│ │Market│ │Data  │ │Analysis│ │Analysis│ │Score │ │& Sort│
│      │ │Cap   │ │      │ │      │ │      │ │      │ │      │
└─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘
```

## Performance Metrics

### Processing Speed
- **Stock Discovery**: ~5 seconds (5,600 tickers)
- **Technical Analysis**: ~10 seconds (1,200 candidates)
- **Options Analysis**: ~15 seconds (25 stocks)
- **Risk Scoring**: ~5 seconds
- **Total Time**: ~35 seconds

### Memory Usage
- **Peak Memory**: ~500MB
- **Cache Size**: ~100MB
- **Data Structures**: Efficient pandas/numpy arrays

### API Efficiency
- **Rate Limiting**: 10 requests/minute
- **Caching**: 24-hour cache for stock data
- **Retry Logic**: Exponential backoff
- **Fallback**: Multiple data sources

## Error Handling

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   API Error     │    │   Retry Logic   │    │   Fallback      │
│                 │    │                 │    │                 │
├─────────────────┤    ├─────────────────┤    ├─────────────────┤
│ • Rate Limit    │    │ • Exponential   │    │ • Cached Data   │
│ • Network Error │───▶│   Backoff       │───▶│ • Default Values│
│ • Timeout       │    │ • Max 3 Retries │    │ • Estimates     │
│ • Invalid Data  │    │ • 2s, 4s, 8s   │    │ • Skip Option   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Monitoring & Alerts

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              MONITORING                                        │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  Position   │  │  Portfolio  │  │  Market     │  │  System     │
│  Monitoring │  │  Risk       │  │  Conditions │  │  Health     │
└─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘
       │                │                │                │
       ▼                ▼                ▼                ▼
┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│ • P&L Track │  │ • VaR Alert │  │ • Volatility│  │ • API Status│
│ • Exit Sig  │  │ • Correlat. │  │ • Sector    │  │ • Memory    │
│ • Theta Dec │  │ • Drawdown  │  │ • Momentum  │  │ • Cache     │
└─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘
```

This flow diagram shows how the system processes data from multiple sources, applies various filters and analyses, and produces ranked recommendations while maintaining risk management throughout the process. 