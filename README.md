# FANORA — Digital Fan Intelligence & Traceability Platform

A dynamic, database-backed MVP based on the uploaded **Digital Fan Intelligence & Traceability Platform** specification (IB-07 حل.pdf). It is a runnable web application, not a static HTML mockup.

## Included in this MVP

- Fan registration, login/logout, password hashing, role-based access checks.
- Fan profile with unique Fan ID, favorite IP, preferences, engagement score, fan segment and loyalty points.
- Role dashboards for Platform Admin, IP Owner, Distributor/Retailer, Event Organizer, Community Manager and Fan.
- Dynamic CRUD screens for IPs, characters, products, events, communities, campaigns, rewards, official content, partners and notifications.
- Product traceability: unique product ID, authorization status, scan logs, repeat-scan rule-based suspicious flag, live product QR image, product registration and points.
- Event registration, unique ticket code, check-in endpoint and points for successful check-in.
- Community membership, posts, points for joining, and community page.
- Loyalty reward redemption with point balance checks and unique redemption codes.
- Consent preferences and consent history records for analytics and marketing.
- Interaction event tracking, fan CRM search, dynamic analytics dashboard, product scan analytics, event attendance analytics and CSV export.
- Seeded demo data to make the app immediately testable.

## Technology

- Python 3.10+
- Flask
- SQLite (local database file created automatically)
- qrcode + Pillow for real dynamically generated QR images
- Responsive HTML/CSS templates

SQLite is chosen so you can run the project locally without configuring a separate database server. The schema can be migrated to PostgreSQL for production.

## Run locally (Windows PowerShell)

1. Extract the ZIP file.
2. Open PowerShell in the extracted `fan_intelligence_platform` folder.
3. Create a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

4. Install dependencies:

   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

5. Start the server:

   ```powershell
   python app.py
   ```

6. Open `http://127.0.0.1:5000` in your browser. The database and sample data are created automatically on first run.

## Demo logins

| Role | Email | Password |
|---|---|---|
| Platform Admin | `admin@fanintel.demo` | `Admin123!` |
| IP Owner | `owner@fanintel.demo` | `Owner123!` |
| Distributor / Retailer | `partner@fanintel.demo` | `Partner123!` |
| Community Manager | `community@fanintel.demo` | `Community123!` |
| Fan / Customer | `fan@fanintel.demo` | `Fan123!` |

Change all demo credentials and set a strong `SECRET_KEY` before any deployment accessible to other people.

## Main routes

- `/` — landing page
- `/register`, `/login`, `/logout` — account lifecycle
- `/dashboard` — role-based dashboard
- `/explore` — dynamic IP, product, event, community and content catalogue
- `/product/<id>` — product detail
- `/product/<id>/scan` — live product verification and scan event logging
- `/product/<id>/qr.png` — actual QR image for the product verification route
- `/fan/<id>/qr.png` — Fan ID QR (only the fan themselves or admin can view it)
- `/community/<id>` — community feed and posts
- `/analytics` — analytics dashboard
- `/manage/<entity>` — role-restricted management CRUD
- `/manage/fans` — fan CRM search
- `/reports/export.csv` — fan data CSV export (restricted role)
- `/settings` — profile and privacy consent controls

## Important scope notes

The uploaded specification describes a broad platform and explicitly recommends a focused MVP / PoC before rolling out the full ecosystem. This ZIP implements a functional MVP foundation for the core fan journey and the main administrative records. A number of advanced/production items are not yet implemented as complete production integrations, including:

- Native iOS/Android app, social-platform integrations, POS/e-commerce/CRM partner APIs and payment/purchase attribution.
- Trained AI recommendation/purchase propensity models. Current segmentation and suspicious-scan detection are transparent rule-based MVP logic, not trained AI.
- Email/SMS/push delivery. Notification records can be managed but a delivery provider is not connected.
- Advanced moderation workflows, formal surveys/quizzes/challenges, campaign step builder, reward expiry scheduling and configurable score weights.
- Production-grade multi-tenant isolation, password reset, email verification, CSRF protection, rate limiting, audit retention controls, full data deletion/export workflows and a formal privacy/legal review.
- Deployment infrastructure, PostgreSQL migrations, automated tests and production observability.

The QR images are real and dynamic. A product QR opens its verification route. The Fan ID QR currently encodes a profile/dashboard link containing the fan code; it is not a public identity-verification API.

## Production security checklist

Before production: configure `SECRET_KEY` from a secret manager; use HTTPS; enable secure session cookies; add CSRF protection and rate limits; verify email and add password reset; move to PostgreSQL; back up and encrypt data; define retention/deletion policies; review consent and privacy obligations with counsel; use verified authorized IP/product data; and run security and load testing.

## Database reset

Stop the server and delete `fan_platform.db` to reset local demo data. It will be recreated with demo accounts on the next `python app.py` run.
