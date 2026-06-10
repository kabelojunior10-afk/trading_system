═══════════════════════════════════════════════════════════════════
  MULTI-SPEED EWMAC TREND FOLLOWING WITH VOLATILITY POSITION SIZING
═══════════════════════════════════════════════════════════════════

Components:
├── Signals: 4-speed EWMAC (4/16, 8/32, 16/64, 32/128)
├── Entry:   ±3.0 forecast threshold (amplified 1.5× FDM)
├── Exit:    2.0× ATR trailing stop + Stop & Reverse
├── Sizing:  (1/N) × Capital × (T/V) × (F/10) × IDM
├── Risk:    35% annual volatility target
├── IDM:     2.00 (for 3 instruments)
├── Timeframe: M15 (15-minute candles)
└── Market:  Cryptocurrency-only (BTC, ETH, SOL)
