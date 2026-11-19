# MetoMenu Partner Program: Page & System Spec

**Site:** metomenu.metora.in
**Stack assumption:** Laravel + Tailwind (adjust if different)
**Status:** Ready for development. Items marked **OPEN** need a final decision.

---

## 1. Program Overview

| Item | Decision |
|---|---|
| Program name | **MetoMenu Partner Program** |
| Track 1 | **Creator Partners** (influencers, food bloggers, restaurant-industry pages) |
| Track 2 | **Referral Partners** (anyone who knows restaurant owners: freelancers, students, consultants) |
| Public URL | `/partners` only |
| Old URL | `/affiliate` is removed and **301 redirects** to `/partners` |
| Attribution | Coupon code and/or link with the coupon attached (same mechanism for both tracks) |
| Customer discount | Optional extra % discount, configured separately on the coupon |
| Commission | **Flat amount per signup**, configurable per track |
| Approval | **Auto-approve** on signup, with basic KYC. Admin can block partners and coupons. |
| Materials | Marketing materials shared with both tracks. Partners are free to promote in their own way. |

The word "affiliate" is dropped from the name, URLs and copy. It may appear once in the body text for SEO if desired.

---

## 2. Routes

| Route | Purpose |
|---|---|
| `GET /partners` | Public landing page |
| `GET /affiliate` | 301 redirect to `/partners` |
| `GET /partners?track=creator` | Landing page with Creator pre-selected in the signup form |
| `GET /partners?track=referral` | Landing page with Referral pre-selected in the signup form |
| `GET /partner/login` | Partner login (301 redirect from old `/applicant/login`) |
| `GET /partner/dashboard` | Partner dashboard (auth required) |
| `GET /partner/materials` | Marketing materials (auth required, or reuse existing `/marketing-materials`) |
| `GET /?ref=CODE` | Referral link landing: stores code in cookie and pre-fills the coupon field at signup |

Also update: sitemap (remove `/affiliate`, add `/partners`), navbar link ("Partners"), footer Company list.

---

## 3. Landing Page (`/partners`)

### 3.1 SEO / Meta

- **Title:** MetoMenu Partner Program - Earn Commissions Today
- **Meta description:** Join the MetoMenu Partner Program. Share your coupon code or link, and earn for every restaurant that signs up for MetoMenu's digital QR menu.
- **Canonical:** `https://metomenu.metora.in/partners`
- **Open Graph / Twitter:** same title and description, with the existing og image
- **Robots:** index, follow

### 3.2 Page Sections (in order)

1. **Navbar:** existing nav, with the "Affiliate with Us" link replaced by "Partners".
2. **Hero**
   - Heading: "MetoMenu Partner Program"
   - Subheading: "Earn for every restaurant you bring to MetoMenu. Share your code or link and get paid."
   - Two CTAs: "Become a Creator Partner" and "Become a Referral Partner". Each scrolls to the signup form and pre-selects the track.
   - Existing "Login" button now points to `/partner/login`.
3. **Two track cards** (side by side on desktop, stacked on mobile)
   - **Creator Partners**
     - For: influencers, food bloggers, restaurant-industry pages
     - Benefits: your own coupon code and link, optional extra discount for your audience, marketing materials, real-time dashboard
     - Earning line: "Earn ₹{CREATOR_AMOUNT} for every restaurant that signs up with your code"
     - Button: "Apply as Creator"
   - **Referral Partners**
     - For: anyone who knows restaurant owners, including freelancers, students and consultants
     - Benefits: your own coupon code and link, pitch material, real-time dashboard
     - Earning line: "Earn ₹{REFERRAL_AMOUNT} for every restaurant that signs up with your code"
     - Button: "Apply as Referral Partner"
4. **How it works** (3 steps)
   1. Sign up and get your unique code and link instantly.
   2. Share it in your own way: posts, reels, WhatsApp, in person.
   3. Get paid when restaurants sign up with your code.
5. **Why partner with us** (4 feature tiles, keep existing)
   - Earn commission on every signup
   - Quick payouts
   - Live performance tracking
   - Marketing materials and support
   - CTA: "Access Marketing Materials"
6. **Earnings example** (replace vague "attractive commission")
   - Example: "Refer 10 restaurants in a month = ₹{10 x AMOUNT}". Use real amounts.
7. **Signup form** (see section 4)
8. **FAQ** (see section 3.3)
9. **Footer:** existing, with the Affiliate link replaced by Partners.

### 3.3 FAQ Content

- **How do I get started?** Choose your track, fill in the form and your account is activated immediately. You'll get your coupon code and link right away.
- **How does tracking work?** Every restaurant that signs up using your code or your link is tagged to you automatically.
- **When do I get paid?** [**OPEN: define payout timing, see section 9**]. Payouts via UPI or bank transfer.
- **Do I need to complete KYC?** Yes. Basic KYC (PAN and UPI/bank details) is required [**OPEN: at signup or before first payout, see section 9**].
- **Can I offer a discount to my audience?** Extra discounts may be added to your code by MetoMenu on request.
- **Do I need technical knowledge?** No. We provide materials and support.
- **Can my account be blocked?** Yes, for fake signups, self-referrals, misleading claims or violation of the terms.

---

## 4. Signup Form

Fields:

| Field | Type | Required | Notes |
|---|---|---|---|
| Partner track | Radio/select: Creator, Referral | Yes | Pre-selected via the card button or `?track=` |
| Full name | text | Yes | |
| Email | email | Yes | Unique across partners |
| Phone | tel | Yes | Unique across partners, validate Indian format |
| Password | password | Yes | Min 8 chars |
| Confirm password | password | Yes | |
| Social profile link | url | Creator: Yes. Referral: No | Instagram/YouTube etc. |
| Preferred coupon code | text | No | 4-12 chars, A-Z and 0-9, must be unique. Auto-generate if empty. |
| Terms checkbox | checkbox | Yes | Links to Partner Terms |

On submit:
1. Create the partner account with `status = active`.
2. Create the coupon (preferred or auto-generated) linked to the partner.
3. Log the partner in and redirect to `/partner/dashboard`.
4. If KYC is required at signup (**OPEN**), show the KYC form as the first step of the dashboard.

---

## 5. Attribution & Coupon Logic

### 5.1 Partner code and link

- Each partner has one primary coupon code, e.g. `RAHUL20`.
- Partner link format: `https://metomenu.metora.in/?ref=RAHUL20`
- Opening the link stores the code in a cookie (**30 days**) and pre-fills the coupon field at restaurant signup.
- A coupon typed manually at signup or checkout overrides the cookie.

### 5.2 Separate discount

- The coupon has an optional `discount_percent` (default `0`).
- A code with 0% discount still tracks and earns commission.
- Discount is configured by admin per coupon, independently of commission.

### 5.3 Attribution priority

1. Coupon code entered by the restaurant
2. `?ref=` cookie
3. No attribution, no commission

### 5.4 Rules

- One restaurant signup is attributed to at most one partner.
- A restaurant keeps its first attribution and it can't be changed afterwards.
- Self-referral is blocked: reject the coupon if the restaurant's email, phone or payment details match the partner's.
- A disabled or blocked partner's code is rejected at signup.

---

## 6. Commission Rules

- **Model:** flat amount per signup, no recurring commission.
- **Amounts:** stored as settings, separate per track:
  - `creator_commission_amount` = ₹{TBD}
  - `referral_commission_amount` = ₹{TBD}
- The amount is **locked at the time the commission is created**, so later changes don't affect existing commissions.
- **Trigger (OPEN):** see section 9. Recommended: create the commission when the restaurant's **first paid plan payment** is collected.
- **Status flow:** `pending` -> `approved` -> `paid`, or `cancelled`.
  - `pending`: created, still inside the refund window
  - `approved`: refund window passed, payable
  - `paid`: included in a payout
  - `cancelled`: refunded, fraudulent or partner blocked
- On refund or cancellation inside the window, the commission is set to `cancelled` automatically.

---

## 7. Partner Dashboard (`/partner/dashboard`)

Sections:

1. **Summary cards:** link clicks, signups, paid conversions, pending earnings, approved earnings, total paid.
2. **My code and link:** copy buttons, plus a share-via-WhatsApp button.
3. **Referrals table:** date, restaurant name (masked, e.g. "Spice H***"), status, commission amount, commission status.
4. **Payouts:** history with date, amount, method, reference.
5. **KYC / payout details:** PAN, UPI ID or bank account (name, account number, IFSC). Status badge: Not submitted, Under review, Verified.
6. **Marketing materials:** link to downloads (logo, banners, reel/story templates, demo video, pitch script, brochure).
7. **Profile and password:** edit name, phone and social link.

If the partner is blocked, the dashboard shows a clear "Account suspended, contact support" message.

---

## 8. Admin Panel

### 8.1 Partners list

- Columns: name, track, email, phone, code, status, KYC status, signups, total earned, joined date.
- Filters: track, status, KYC status. Search by name, email, code.
- Actions: **Block / Unblock** (with a required reason), view detail, reset password.

### 8.2 Coupon management

- Per code: partner, discount percent, usage limit, expiry, active toggle.
- Actions: **Disable / Enable code**, edit discount, create extra codes for a partner (campaigns).

### 8.3 Commissions

- List with filters by status, partner and date.
- Actions: approve, cancel (with a reason), mark paid. Bulk actions.

### 8.4 Payouts

- Generate a payout batch of all `approved` commissions for partners with verified KYC and a balance of at least the minimum.
- Export to CSV (name, UPI/bank details, amount) for manual payment.
- Mark the batch as paid with a reference number.

### 8.5 Settings

- Commission amount per track
- Minimum payout amount
- Refund window (days)
- Cookie duration (days)

### 8.6 Audit log

Record every block, unblock, coupon disable, commission cancel and settings change, with admin id, timestamp and reason.

---

## 9. OPEN Decisions

| # | Question | Recommended default |
|---|---|---|
| 1 | **When is a commission created?** On restaurant registration, or on first paid plan payment? | On the first paid payment. Registration-based commission invites fake-account abuse. If registration is chosen, require verified phone/email and keep self-referral blocks. |
| 2 | **When is KYC enforced?** At signup, or before first payout? | Dashboard access immediately, but no payout until KYC is verified. Earnings accumulate meanwhile. |
| 3 | Flat commission amount per track | Set `creator_commission_amount` and `referral_commission_amount` |
| 4 | Minimum payout and payout timing | Suggested: minimum ₹500-1000, monthly or within 7 days of approval |
| 5 | Refund window length | Match the Refund Policy page |

---

## 10. Database Schema (suggested)

### `partners`
| Column | Type | Notes |
|---|---|---|
| id | bigint PK | |
| track | enum(`creator`,`referral`) | |
| name | string | |
| email | string unique | |
| phone | string unique | |
| password | string | hashed |
| social_url | string nullable | required for creator |
| status | enum(`active`,`blocked`) | default `active` |
| blocked_reason | text nullable | |
| kyc_status | enum(`not_submitted`,`pending`,`verified`,`rejected`) | |
| pan | string nullable | encrypted at rest |
| upi_id | string nullable | |
| bank_name / bank_account / bank_ifsc | string nullable | account number encrypted |
| timestamps | | |

### `coupons`
| Column | Type | Notes |
|---|---|---|
| id | bigint PK | |
| partner_id | FK partners | |
| code | string unique | uppercase |
| discount_percent | decimal(5,2) | default 0 |
| usage_limit | int nullable | |
| expires_at | datetime nullable | |
| is_active | boolean | default true |
| timestamps | | |

### `referrals`
| Column | Type | Notes |
|---|---|---|
| id | bigint PK | |
| partner_id | FK | |
| coupon_id | FK | |
| restaurant_id | FK unique | one attribution per restaurant |
| source | enum(`coupon`,`link`) | |
| created_at | | |

### `commissions`
| Column | Type | Notes |
|---|---|---|
| id | bigint PK | |
| partner_id | FK | |
| referral_id | FK unique | one commission per referral |
| amount | decimal(10,2) | locked at creation |
| status | enum(`pending`,`approved`,`paid`,`cancelled`) | |
| approvable_at | datetime | creation + refund window |
| payout_id | FK nullable | |
| cancelled_reason | string nullable | |
| timestamps | | |

### `payouts`
| Column | Type | Notes |
|---|---|---|
| id | bigint PK | |
| partner_id | FK | |
| amount | decimal(10,2) | |
| method | enum(`upi`,`bank`) | |
| reference | string nullable | |
| paid_at | datetime nullable | |
| timestamps | | |

### `partner_link_clicks` (optional, for the clicks metric)
| Column | Type |
|---|---|
| id, partner_id, coupon_id, ip_hash, user_agent, created_at | |

### `audit_logs`
| Column | Type |
|---|---|
| id, admin_id, action, subject_type, subject_id, reason, meta (json), created_at | |

---

## 11. Anti-Abuse Checklist

- [ ] Unique email, phone, PAN and UPI/bank account across partner accounts
- [ ] Block a coupon if the restaurant's email, phone or payment details match the partner
- [ ] Commission held as `pending` through the refund window
- [ ] Rate-limit signup, login and coupon validation endpoints
- [ ] Encrypt PAN and bank account number at rest
- [ ] Mask restaurant names in the partner dashboard
- [ ] Audit log for all admin actions
- [ ] Admin one-click block and coupon disable

---

## 12. Legal / Terms Points

- Partners must not make misleading claims about MetoMenu.
- Creators must disclose the paid partnership in their content (ASCI guidelines).
- No self-referral, fake signups or paid ads bidding on the MetoMenu brand name.
- MetoMenu can block a partner and cancel commissions for violations.
- PAN is collected for payout. TDS (Section 194H) may apply, so confirm the current threshold and rate with a CA.
- Create a **Partner Terms** page and link it from the signup form and footer.

---

## 13. Email / Notification Templates

1. **Welcome:** account active, with code, link and a dashboard link
2. **New signup attributed:** "A restaurant signed up using your code"
3. **Commission approved**
4. **Payout sent**
5. **KYC reminder / KYC verified / KYC rejected**
6. **Account blocked** (with a support contact)

---

## 14. Build Order

1. Rename route to `/partners`, add `/affiliate` 301, update nav, footer, sitemap and meta
2. Landing page with two track cards and updated copy
3. Migrations: partners, coupons, referrals, commissions, payouts, audit_logs
4. Signup form, auto-activation and code generation
5. Coupon validation and attribution (cookie plus manual entry) at restaurant signup
6. Commission creation on the trigger event and refund-window job
7. Partner dashboard
8. Admin: partners, coupons (block/disable), commissions, settings
9. KYC form and verification flow
10. Payout batches and CSV export
11. Emails and audit log
12. Partner Terms page, then QA with test partners and coupons

---

## 15. Acceptance Criteria

- [ ] `/affiliate` redirects with 301 to `/partners`
- [ ] A visitor can sign up as Creator or Referral and instantly get a working code and link
- [ ] A restaurant signing up with a code or link is attributed to exactly one partner
- [ ] A 0% discount code tracks and earns commission
- [ ] A blocked partner can't log in and their code is rejected at signup
- [ ] A disabled coupon is rejected at signup
- [ ] Self-referral is rejected
- [ ] A refund inside the window cancels the commission automatically
- [ ] Admin can generate a payout CSV for verified-KYC partners only
- [ ] All admin actions appear in the audit log