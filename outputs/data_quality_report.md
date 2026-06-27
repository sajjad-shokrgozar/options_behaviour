# Data Quality Report

*Generated: 2026-06-27 21:05*

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
- Zero-volume rate (within active lifetime): 55.8% (raw: 56.8%)
- Call-put pair availability: 50.4%

## Band & Queue
- Empirical band: 4.00%
- Episodes detected: 1877
- Regime counts: {'free': 7395032, 'buy_queue': 6880, 'sell_queue': 2007}

## Pricing & IV
- Daily-eligible rows priced: 18368
- IV flag counts: {'ok': 14590, 'no_arb': 3321, 'invalid_input': 356, 'numerical': 101}
- Parity pairs: 6972