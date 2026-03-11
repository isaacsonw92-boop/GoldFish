# Tasks

- [x] Task 1: Modify `visualize.py` to extract "Real HSI" data.
    - [x] Iterate through logs and extract `event.market_data.hsi_close` if available.
    - [x] Handle cases where data is missing (e.g. future scenarios).
- [x] Task 2: Update the plotting logic in `visualize.py`.
    - [x] Plot "Real HSI" as a grey dashed line on the main chart (`ax1`).
    - [x] Update the legend to include "Real HSI".
- [x] Task 3: Verify the feature with a historical scenario.
    - [x] Run `924_stimulus.yaml` in forecast mode (short run or full).
    - [x] Generate the dashboard.
