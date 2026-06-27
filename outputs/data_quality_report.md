# Data Quality Report

*Generated: 2026-06-27 13:39*

## Ingestion
- Instruments ingested: 146
- CSV files read: 13531
- Total rows: 28033239

## Order Book
- Snapshots reconstructed: ?
- RefIDs missing all 5 levels: ? (?%)
- Bid ordering violations: ?
- Ask ordering violations: ?
- OBI bounds OK: ?

## Cleaning
- Empty-level cells zeroed: ?
- Crossed book rows: 0
- Instruments with derived tick size: 0

## Session
- Fallback open: 09:00:00
- Fallback close: 12:30:00
- Pre-open rows: 0
- Continuous rows: 0

## Synchronization
- Synced rows: 0
- Fresh rate: 0.0%
- Staleness window: 120s

## Liquidity
- Zero-volume contract-day rate: 56.8%
- Call-put pair availability: 50.4%

## Band & Queue
- Empirical band: 9.95%
- Episodes detected: 1827
- Regime counts: {'free': 7395224, 'buy_queue': 6740, 'sell_queue': 1955}

## Pricing & IV
- Daily-eligible rows priced: 18368
- IV flag counts: {'ok': 16074, 'no_arb': 1841, 'invalid_input': 356, 'numerical': 97}
- Parity pairs: 6972