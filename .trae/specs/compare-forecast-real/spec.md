# Parallel Universe Comparison Spec

## Why
Users want to validate the accuracy of the `forecast` mode by comparing the AI-synthesized market trajectory against historical ground truth. Currently, `forecast` mode only shows the synthesized curve, making it hard to benchmark performance against reality for historical scenarios (like the 924 stimulus).

## What Changes
- **Visualization**: Modify `visualize.py` to plot the "Real/Historical HSI" alongside the "Forecast/Synthesized HSI".
- **Data Source**: Extract the real HSI from the `market_data` field within the `event` object in the logs (which comes from the scenario YAML).
- **Metric**: Display the "Real vs Forecast" deviation in the chart legend or title.

## Impact
- **Affected specs**: None.
- **Affected code**: `visualize.py`.
- **User Experience**: When users run a historical scenario in `forecast` mode, the dashboard will now show two lines:
    - **Blue Line**: AI Forecast HSI.
    - **Grey Dashed Line**: Historical Real HSI (if available).

## ADDED Requirements
### Requirement: Real HSI Plotting
The system SHALL check if `log["event"]["market_data"]["hsi_close"]` exists.
- **IF** exists: Plot it as a grey dashed line labeled "真实恒指 (Real HSI)".
- **IF** not exists (e.g. future scenarios): Do nothing (keep existing behavior).

#### Scenario: Historical Backtest in Forecast Mode
- **WHEN** user runs `python run.py --mode forecast --scenario events/924_stimulus.yaml`
- **THEN** the output dashboard `output/reports/dashboard.png` MUST show both the simulated curve and the actual historical curve.
