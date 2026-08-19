# Quickstart: Trading Dashboard

## Prerequisites

1. Ensure the `market_data.duckdb` database exists in the project root and contains strategy run data.
2. Install Python dependencies for the backend.
3. Install Node.js dependencies for the frontend.

## Local Validation

1. **Start the API Server**:
   ```bash
   cd tools/dashboard/api
   uvicorn main:app --reload --port 8000
   ```

2. **Start the Frontend Application**:
   ```bash
   cd tools/dashboard/ui
   npm install
   npm run dev
   ```

3. **Verify the UI**:
   - Open `http://localhost:5173` in a web browser.
   - Assert that the "Overview" table populates with strategies.
   - Click a strategy and assert the equity curve renders.
   - Navigate to the "Stock Performance" tab and assert the table renders grouped by ticker.
   - Navigate to the "Paper Trading" tab and assert reconciliation health is displayed.
