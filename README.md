# SirfBill Backend (Restaurant Edition)

A high-performance, multi-tenant, enterprise-grade restaurant management backend engineered with **FastAPI**, **SQLAlchemy 2.0**, **PostgreSQL**, and **Pydantic**. Built specifically for **Fine Dine, Cafes, Quick Service Restaurants (QSR), Cloud Kitchens, Bars, and Multi-Branch Restaurant Chains**.

---

## 🏗️ Architecture & Tech Stack

- **Framework:** FastAPI (Python 3.11+) with Async routing
- **Database:** PostgreSQL 15+ (Multi-Tenant with tenant-isolated row scoping)
- **ORM & Migrations:** SQLAlchemy 2.0 & Alembic (Latest migration: `f2d4b6a8c0e2`)
- **Thermal Print Engine:** Jinja2 + ReportLab (58mm & 80mm ESC/POS compatible thermal receipt and KOT generators)
- **Authentication & Security:** JWT (JSON Web Tokens), Password Hashing (Bcrypt), RBAC (`ADMIN`, `CASHIER`, `WAITER`, `KITCHEN_STAFF`), and SMS OTP
- **Containerization:** Docker & Docker Compose (Portainer / Production Ready)

---

## 🏛️ The 6 Core Modules

```
┌────────────────────────────────────────────────────────────────────────┐
│                        SirfBill Restaurant Platform                    │
└────────────────────────────────────────────────────────────────────────┘
     │                    │                   │                     │
┌────▼─────────────┐ ┌────▼──────────┐ ┌──────▼───────────┐ ┌───────▼────────────┐
│ 1. Restaurant    │ │ 2. Kitchen    │ │ 3. Restaurant    │ │ 4. CRM & Executive │
│    POS Module    │ │    Module     │ │    Inventory     │ │    Reports Module  │
│ (Order & Tenders)│ │ (KDS & KOT)   │ │ (Recipes & Stock)│ │ (RFM, Ledgers & BCG│
└──────────────────┘ └───────────────┘ └──────────────────┘ └────────────────────┘
     │                                                              │
┌────▼─────────────┐                                           ┌────▼────────────┐
│ 5. Captain/Waiter│                                           │ 6. Admin & Multi│
│    Module        │                                           │    Tenant Module│
│ (Floor & Tables) │                                           │ (RBAC, Sub, Pay)│
└──────────────────┘                                           └─────────────────┘
```

---

## 1. 🧾 Restaurant POS Module

Handles real-time table billing, counter takeaway sales, delivery orders, tender settlements, and thermal receipt generation.

### 🔌 API Endpoints
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/restaurant/orders` | List active & past orders (filters: `outlet_id`, `status`, `order_type`, date range) |
| `POST` | `/api/restaurant/orders` | Create order header (Dine-in, Takeaway, Delivery) |
| `GET` | `/api/restaurant/orders/{order_id}` | Fetch order details, line items, version, and financial breakdown |
| `POST` | `/api/restaurant/orders/{order_id}/lines` | Append items, variants, modifiers, and prep notes to cart |
| `PATCH` | `/api/restaurant/orders/{order_id}/lines/{line_id}` | Update quantity or cancel an order line |
| `POST` | `/api/restaurant/orders/{order_id}/transitions` | Order state transitions (`SENT_TO_KITCHEN`, `READY`, `SERVED`, `CANCELLED`) |
| `POST` | `/api/restaurant/orders/{order_id}/settle` | Settle counter bill, record tender, auto-deduct stock, free table, trigger thermal receipt |
| `POST` | `/api/restaurant/tenders/{order_id}/settle` | Mixed / split tender checkout (Cash + UPI + Card + Khata) in single transaction |
| `GET` | `/api/restaurant/tenders/{order_id}/receipt` | Printable thermal invoice dataset with reprint audit counter |
| `GET` | `/api/restaurant/shifts/current` | Get active cashier shift details |
| `POST` | `/api/restaurant/shifts/open` | Open cashier shift with initial cash float |
| `POST` | `/api/restaurant/shifts/close` | Reconcile and close cashier shift with X/Z report output |

### 📐 Mathematical Formulas

#### A. Pre-Tax Line Item Subtotal
$$\text{Line Subtotal} = (\text{Unit Price} \times \text{Quantity}) + \sum_{m=1}^{k} \text{Modifier Price}_m$$

#### B. Order Discount Computation
- **Percentage Discount:**
  $$\text{Discount Amount} = \text{Order Subtotal} \times \left(\frac{\text{Discount Rate}}{100}\right)$$
- **Fixed / Flat Discount:**
  $$\text{Discount Amount} = \min(\text{Order Subtotal}, \text{Flat Discount Value})$$

#### C. Taxable Base & GST (CGST / SGST / IGST)
$$\text{Taxable Base} = \text{Order Subtotal} - \text{Discount Amount}$$

$$\text{CGST} = \text{Taxable Base} \times \left(\frac{\text{Tax Rate}}{2 \times 100}\right)$$

$$\text{SGST} = \text{Taxable Base} \times \left(\frac{\text{Tax Rate}}{2 \times 100}\right)$$

$$\text{Total Tax} = \text{CGST} + \text{SGST}$$

#### D. Rounding & Grand Total
$$\text{Raw Total} = \text{Taxable Base} + \text{Total Tax}$$

$$\text{Grand Total} = \operatorname{round}(\text{Raw Total}, 0)$$

$$\text{Rounding Adjustment} = \text{Grand Total} - \text{Raw Total}$$

#### E. Cashier Drawer Reconciliation (Shift Closing)
$$\text{Expected Cash} = \text{Opening Cash Float} + \sum \text{Cash Tender Receipts} - \sum \text{Cash Payouts}$$

$$\text{Cash Variance} = \text{Actual Counted Cash} - \text{Expected Cash}$$

---

## 2. 🍳 Kitchen Display System (KDS) & KOT Module

Manages Kitchen Order Tickets (KOTs), prep station line item routing, and kitchen status updates.

### 🔌 API Endpoints
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/restaurant/kitchen/kots` | Real-time active KOT tickets filtered by outlet, station, or status |
| `POST` | `/api/restaurant/kitchen/orders/{order_id}/send-kot` | Generate numerical `KOT-XXXXXX`, route items to stations, print thermal KOT |
| `PATCH` | `/api/restaurant/kitchen/kots/{kot_id}/items/{item_id}/status` | Item-level state transition (`PREPARING` → `READY` → `SERVED`) |
| `POST` | `/api/restaurant/kitchen/kots/{kot_id}/complete` | Mark complete KOT batch ready for runner dispatch |
| `POST` | `/api/restaurant/kitchen/kots/{kot_id}/reprint` | Reprint physical KOT slip with reprint audit flag |
| `GET` | `/api/restaurant/kitchen/stations` | List configured prep stations (*Main Kitchen, Tandoor, Bar, Pantry, Desserts*) |

### 📐 Mathematical & Routing Logic
- **KOT Ticket Numbering Sequence:**
  ```text
  KOT Code = "KOT-" + Date(YYYYMMDD) + "-" + PadZero(Sequence, 4)
  Example: KOT-20261120-0001
  ```
- **Station Split Routing Logic:**
  ```text
  KOT(Station) = { order_line in Order | order_line.item.prep_station == Station }
  ```

---

## 3. 📦 Restaurant Inventory, Recipes & Procurement Module

Tracks raw materials, Unit of Measure (UOM) conversions, recipes (Bill of Materials), Moving Weighted Average Cost (WAC), physical count audits, and inter-branch transfers.

### 🔌 API Endpoints
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET`, `POST` | `/api/restaurant/inventory/categories` | Ingredient storage categories and temperature zones (Walk-in chiller, Ambient, etc.) |
| `GET`, `POST`, `PATCH` | `/api/restaurant/inventory/ingredients` | Ingredient master with UOM, par levels, and Moving Average Cost |
| `GET` | `/api/restaurant/inventory/stock-summary` | Real-time stock levels, valuation, and reorder alerts |
| `GET`, `POST`, `PATCH` | `/api/restaurant/inventory/recipes` | Recipe (BOM) mapping: menu item to raw ingredients |
| `GET` | `/api/restaurant/inventory/ledger` | Append-only inventory transaction ledger |
| `POST` | `/api/restaurant/inventory/audits/start` | Initialize physical inventory stock audit batch |
| `POST` | `/api/restaurant/inventory/audits/{id}/items` | Enter physical count (recipe UOM or purchase UOM) |
| `POST` | `/api/restaurant/inventory/audits/{id}/commit` | Post audit variances to ledger, adjusting book balances |
| `POST` | `/api/restaurant/inventory/wastage/log` | Record raw material spoilage / kitchen wastage with financial loss snapshot |
| `POST` | `/api/restaurant/stock-transfers` | Transfer ingredients between outlets (Source Dispatch → Destination Receipt) |
| `POST` | `/api/restaurant/procurement/grn` | Inward Goods Received Note (GRN) from vendor invoices |

### 📐 Mathematical Formulas

#### A. UOM Normalization
$$\text{Normalized Qty} = \text{Input Quantity} \times \text{UOM Conversion Factor}$$

*(e.g., $2.5\text{ KG Chicken} \times 1000 = 2500\text{ G}$)*

#### B. Moving Weighted Average Cost (WAC / MAC)
When new stock enters via GRN:
$$\text{New WAC} = \frac{(\text{Current Qty} \times \text{Old WAC}) + (\text{GRN Qty} \times \text{GRN Purchase Price})}{\text{Current Qty} + \text{GRN Qty}}$$

#### C. Recipe Bill of Materials (BOM) Plate Cost
$$\text{Plate Cost} = \sum_{i=1}^{n} \left(\frac{\text{Quantity Required}_i}{\text{Yield Servings}} \times \text{WAC Unit Cost}_i\right)$$

#### D. Physical Stock Audit Variance
$$\text{Variance Qty} = \text{Physical Count} - \text{Expected Book Stock}$$

$$\text{Rupee Variance Impact} = \text{Variance Qty} \times \text{WAC Unit Cost}$$

- **Surplus:** $\text{Variance Qty} > 0$
- **Deficit (Shrinkage):** $\text{Variance Qty} < 0$

---

## 4. 👥 CRM, Loyalty & Executive Reports Module

Unified multi-branch guest wallet, append-only loyalty points ledger, store credit (Khata), automated marketing notifications, and 5 executive financial costing reports.

### 🔌 API Endpoints (CRM & Loyalty)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/restaurant/crm/customers` | Search guests by phone/name, filter by RFM segment (`ALL`, `VIP`, `REGULAR`, `NEW`, `AT_RISK`) |
| `POST` | `/api/restaurant/crm/customers` | Register or update guest profile with dietary preferences, special dates, and GSTIN |
| `GET`, `PATCH` | `/api/restaurant/crm/customers/{id}` | Read or modify customer profile and credit limit |
| `GET` | `/api/restaurant/crm/customers/{id}/insights` | 360° guest insights: RFM metrics, Top 5 dishes, recent bills |
| `GET`, `POST` | `/api/restaurant/crm/loyalty-rules` | Fetch or configure brand loyalty earn/burn rules |
| `POST` | `/api/restaurant/crm/customers/{id}/loyalty/adjust` | Idempotent points earn/burn with balance verification |
| `GET` | `/api/restaurant/crm/customers/{id}/loyalty/history` | Immutable loyalty transaction ledger audit trail |
| `GET` | `/api/restaurant/crm/customers/{id}/khata` | Khata credit balance and detailed ledger statement |
| `POST` | `/api/restaurant/crm/customers/{id}/khata/settle` | Settle outstanding credit dues with partial/full payment |
| `POST` | `/api/restaurant/crm/customers/{id}/notify` | Dispatch WhatsApp / SMS / Email receipt or promo message |
| `POST` | `/api/restaurant/crm/scheduled/run-automations` | Daily cron: birthday rewards, anniversary offers, 30-day win-back alerts |

### 🔌 API Endpoints (The 5 Executive Reports)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/restaurant/reports/food-cost-variance` | **Executive Report 1:** Theoretical COGS vs. Actual COGS, isolating Wastage and Audit Shrinkage |
| `GET` | `/api/restaurant/reports/stock-movement` | **Executive Report 2:** Stock Movement: Opening + Inward - Consumed - Wastage $\pm$ Audit = Closing |
| `GET` | `/api/restaurant/reports/menu-engineering` | **Executive Report 3:** BCG Matrix: STAR, PLOWHORSE, PUZZLE, DOG, plate cost, margin, cost alerts |
| `GET` | `/api/restaurant/reports/procurement` | **Executive Report 4:** Vendor spend, GST input tax by slab (5%, 12%, 18%), unpaid GRN aging buckets |
| `GET` | `/api/restaurant/reports/shrinkage` | **Executive Report 5:** Top 20 cost-leaking ingredients across Spoilage, Burnt, Return, and Deficit |

### 📐 Mathematical Formulas

#### A. Recency, Frequency, Monetary (RFM) Metrics
$$\text{Average Order Value (AOV)} = \frac{\text{Total Spend}}{\text{Total Visits}}$$

**Segmentation Criteria:**
- **VIP:** Total Spend $\ge ₹5,000$ or Total Visits $\ge 10$
- **REGULAR:** Total Visits $\ge 3$
- **NEW:** Total Visits $< 3$
- **AT_RISK:** Inactive for $> 30$ days since last visit

#### B. Loyalty Earn & Burn
$$\text{Points Earned} = \left\lfloor\frac{\text{Order Grand Total}}{\text{Earn Per Rupees}}\right\rfloor$$

$$\text{Max Allowed Burn} = \text{Order Grand Total} \times \left(\frac{\text{Max Redeem Pct}}{100}\right)$$

#### C. Theoretical vs. Actual COGS (Food Cost Variance)
$$\text{Theoretical COGS} = \sum (\text{KOT Deducted Recipe Qty} \times \text{WAC at Time})$$

$$\text{Actual COGS} = \text{Theoretical COGS} + \text{Logged Wastage Loss} + \text{Physical Audit Deficit}$$

$$\text{Unexplained Variance} = \text{Actual COGS} - \text{Theoretical COGS}$$

$$\text{Variance Pct of Sales} = \left(\frac{\text{Unexplained Variance}}{\text{Total Food Sales}}\right) \times 100$$

#### D. Menu Engineering BCG Matrix Classification
For every menu item $j$:
$$\text{Gross Margin}_j = \text{Selling Price}_j - \text{Plate Cost}_j$$

$$\text{Food Cost Pct}_j = \left(\frac{\text{Plate Cost}_j}{\text{Selling Price}_j}\right) \times 100 \quad (\text{Alert if } > 35\%)$$

Thresholds:
$$\overline{\text{Margin}} = \frac{\sum \text{Total Margin}}{\sum \text{Total Qty Sold}}, \quad \overline{\text{Popularity}} = \frac{\sum \text{Total Qty Sold}}{\text{Number of Unique Menu Items}}$$

| Quadrant | Volume Condition | Margin Condition | Menu Action Strategy |
| :--- | :--- | :--- | :--- |
| ⭐ **STAR** | $\text{Qty} \ge \overline{\text{Popularity}}$ | $\text{Margin} \ge \overline{\text{Margin}}$ | Maintain high quality; prime menu placement |
| 🐴 **PLOWHORSE** | $\text{Qty} \ge \overline{\text{Popularity}}$ | $\text{Margin} < \overline{\text{Margin}}$ | Repackage, adjust portions, or re-engineer cost |
| 🧩 **PUZZLE** | $\text{Qty} < \overline{\text{Popularity}}$ | $\text{Margin} \ge \overline{\text{Margin}}$ | Upsell, feature on specials board, run promotions |
| 🐕 **DOG** | $\text{Qty} < \overline{\text{Popularity}}$ | $\text{Margin} < \overline{\text{Margin}}$ | Re-engineer recipe or consider eliminating |

#### E. Stock Movement Balance Equation
$$\text{Closing Stock} = \text{Opening} + \text{GRN In} + \text{Net Transfers} - \text{KOT Sold} - \text{Wastage} + \text{Audit Adjust}$$

$$\text{Closing Valuation} = \text{Closing Stock} \times \text{Cost per Unit}$$

---

## 5. 🧑‍🍳 Captain & Waiter Module

Table-side ordering for captains, real-time floor plan visualization, seating assignments, and table transfers.

### 🔌 API Endpoints
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/restaurant/tables` | Live table matrix across floors/sections (`VACANT`, `OCCUPIED`, `RESERVED`, `CLEANING`) |
| `POST` | `/api/restaurant/tables/{table_id}/seat` | Seat guests, attach party size, bind assigned waiter/captain |
| `POST` | `/api/restaurant/orders` | Captain creates table-bound Dine-in order |
| `POST` | `/api/restaurant/orders/{order_id}/lines` | Add running items or extra rounds to active table |
| `POST` | `/api/restaurant/kitchen/orders/{order_id}/send-kot` | Direct send-to-kitchen from mobile table ordering tablet |
| `POST` | `/api/restaurant/orders/{order_id}/transitions?payload=SERVED` | Mark food served to guests |
| `POST` | `/api/restaurant/tables/{table_id}/transfer` | Transfer or merge party from Table A to Table B |

### 📐 Mathematical Metrics
- **Table Turnover Rate:**
  $$\text{Table Turnover} = \frac{\text{Total Dine-in Orders on Table}}{\text{Operational Shift Hours}}$$
- **Dining Duration:**
  $$\text{Dining Time} = \text{Settlement Time} - \text{Seated Time}$$

---

## 6. 🛡️ Admin, Multi-Tenant & Subscription Module

Role-based access control, tenant branch management, legal configuration, dynamic UPI QR generation, and platform billing.

### 🔌 API Endpoints
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/auth/token` | Staff login, password verification, and JWT access token issuance |
| `POST` | `/api/auth/admin-login` | Administrative dashboard authentication |
| `GET`, `POST` | `/api/admin/users` | Staff directory: create & manage Cashiers, Waiters, and Kitchen staff |
| `GET`, `POST`, `PATCH`| `/api/restaurant/outlets` | Multi-branch management under master tenant |
| `GET`, `PATCH` | `/api/shop-settings/{outlet_id}`| Brand details: GSTIN, FSSAI, logo URL, UPI ID, and thermal bill layout |
| `GET` | `/api/subscriptions/plans` | Platform subscription tiers (Silver, Gold, Platinum) |
| `GET` | `/api/subscriptions/status` | Current tenant subscription validity, active plan, days remaining |
| `POST` | `/api/subscriptions/create-order`| Initiate Razorpay order for platform license renewal |
| `POST` | `/api/subscriptions/verify-payment`| Verify payment signature and extend tenant subscription dates |
| `GET` | `/api/subscriptions/history` | Billing invoices and platform license payment history |

### 📐 Mathematical & Technical Logic

#### A. Dynamic Bharat UPI QR Code Spec
Embedded in customer thermal receipts for immediate cashierless UPI scanning:
```text
upi://pay?pa={UPI_ID}&pn={URL_ENCODED_SHOP_NAME}&am={GRAND_TOTAL}&cu=INR&tn={ORDER_NUMBER}
```

#### B. Subscription Expiry & Grace Window
$$\text{Days Remaining} = \text{End Date} - \text{Current Date}$$

$$\text{Status} = \begin{cases} 
\text{ACTIVE} & \text{if } \text{Days Remaining} > 0 \\ 
\text{GRACE-PERIOD} & \text{if } -3 \le \text{Days Remaining} \le 0 \\ 
\text{EXPIRED} & \text{if } \text{Days Remaining} < -3 
\end{cases}$$

---

## 🚀 Running Locally & Migrations

```bash
# 1. Activate Virtual Environment
source .venv/bin/activate

# 2. Run Database Migrations to Latest Head
alembic upgrade head

# 3. Start Development Server
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Interactive API documentation will be available at:
- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## 🛡️ License
Private and Proprietary to **SirfBill (Naiyo24 Pvt. Ltd.)**. All rights reserved.
