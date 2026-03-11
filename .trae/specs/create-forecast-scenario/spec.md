# Forecast Scenario Spec

## Why
Currently, the `forecast` mode (prediction mode) relies on existing historical scenarios like `924_stimulus.yaml`. To properly test the forecasting capabilities, we need a hypothetical scenario that is specifically designed to stress-test the agents' reactions to new, unseen events without relying on historical market data as a crutch.

## What Changes
- Create a new scenario file: `events/tech_boom_2025.yaml`.
- The scenario will simulate a hypothetical "Tech Sector Stimulus" event in 2025.
- It will include 5 distinct event days:
    1.  **Baseline**: Normal market conditions.
    2.  **Shock**: Sudden announcement of a major tech subsidy.
    3.  **Reaction**: Market digestion of the news.
    4.  **Correction**: Profit-taking or reality check.
    5.  **Stabilization**: New equilibrium.

## Impact
- **Affected specs**: None (new file).
- **Affected code**: None (data file only).
- **User Experience**: Users can run `python run.py --mode forecast --scenario events/tech_boom_2025.yaml` to see how agents react to a pure news-driven event.

## ADDED Requirements
### Requirement: New Forecast Scenario
The system SHALL provide a valid YAML scenario file `events/tech_boom_2025.yaml` that:
- Defines a 5-day timeline.
- Includes `initial_market` state.
- Includes `events` with `description` and `policy_signal_strength`.
- Does NOT require `market_data` for each day (as it is for forecasting), but may include placeholder or expected data for reference.

#### Scenario: Tech Boom
- **WHEN** user runs with this scenario in forecast mode.
- **THEN** agents should react to the "Tech Subsidy" event by buying tech stocks, pushing the synthetic index up.
