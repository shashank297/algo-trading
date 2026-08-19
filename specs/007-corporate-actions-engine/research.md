# Research & Mathematical Specification: Corporate Actions & Total Return

## 1. Canonical Share Multiplier Formulation

For any share-restructuring event (stock split, bonus issue, or consolidation), define:
$$R = \frac{\text{shares after event}}{\text{shares before event}}$$

| Event Type | Example | Shares Before | Shares Added/Subdivided | Shares After | Canonical `share_multiplier` ($R$) |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Stock Split** | 1:10 split (Tata Steel) | 1 | Subdivided to 10 | 10 | **10.0** |
| **Stock Split** | 1:2 split (HDFC Bank) | 1 | Subdivided to 2 | 2 | **2.0** |
| **Bonus Issue** | Bonus 1:1 (Reliance, Infy) | 1 | +1 bonus | 2 | **2.0** |
| **Bonus Issue** | Bonus 1:3 (PowerGrid) | 3 | +1 bonus | 4 | **$4/3 \approx 1.333333$** |
| **Bonus Issue** | Bonus 1:2 (BPCL, IOC) | 2 | +1 bonus | 3 | **$3/2 = 1.5$** |
| **Bonus Issue** | Bonus 2:1 (BEL) | 1 | +2 bonus | 3 | **3.0** |
| **Bonus Issue** | Bonus 1:10 (ICICI Bank) | 10 | +1 bonus | 11 | **$11/10 = 1.1$** |
| **Consolidation**| 5-for-1 Reverse Split | 5 | Consolidated to 1 | 1 | **$1/5 = 0.2$** |
| **Cash Dividend**| Pure Cash Distribution | 1 | 0 | 1 | **1.0** |

---

## 2. Cumulative Multipliers and Backward Adjustment

For a series of historical bars $t \in \{1, \dots, T\}$, evaluate the exchange session date $D(t)$ in `Asia/Kolkata`.

For all future events $j$ where $\text{ex\_date}_j > D(t)$:
$$S_t = \prod_{j: \text{ex\_date}_j > D(t)} R_j$$

### A. Split-Adjusted Series (`SPLIT_ADJUSTED`)
* Applied to splits, bonuses, and consolidations.
* **Prices**:
  $$P_t^{\text{split}} = \frac{P_t^{\text{raw}}}{S_t} \quad \forall P \in \{\text{Open}, \text{High}, \text{Low}, \text{Close}\}$$
* **Volume**:
  $$V_t^{\text{split}} = V_t^{\text{raw}} \times S_t$$
* **Turnover Property**:
  $$P_t^{\text{split}} \times V_t^{\text{split}} = \left(\frac{P_t^{\text{raw}}}{S_t}\right) \times (V_t^{\text{raw}} S_t) = P_t^{\text{raw}} \times V_t^{\text{raw}}$$
  *(Strictly Invariant!)*

---

### B. Continuous Back-Adjusted Series (`BACK_ADJUSTED`)
* Applied to splits, bonuses, consolidations, AND cash dividends.
* For each dividend $k$, compute the continuity discount factor:
  $$F_k = 1 - \frac{D_k}{P_{\text{prev}, k}}$$
  where $P_{\text{prev}, k}$ is the official closing price of the **active trading session immediately prior to $\text{ex\_date}_k$**.
* Cumulative dividend factor:
  $$C_t = \prod_{k: \text{ex\_date}_k > D(t)} F_k$$
* **Prices**:
  $$P_t^{\text{back}} = \frac{P_t^{\text{raw}}}{S_t} \times C_t$$
* **Volume**:
  $$V_t^{\text{back}} = V_t^{\text{raw}} \times S_t \quad (\text{Dividends do NOT scale volume!})$$

---

### C. Exact Total Return Series (`TOTAL_RETURN`)
* Discrete shareholder economic return between session $t-1$ and $t$:
  $$r_t^{\text{TR}} = \frac{P_t^{\text{split}} + D_t^{\text{split}}}{P_{t-1}^{\text{split}}} - 1$$
* Total Return Index ($\text{TRI}$):
  $$\text{TRI}_0 = 100.0$$
  $$\text{TRI}_t = \text{TRI}_{t-1} \times (1 + r_t^{\text{TR}})$$
