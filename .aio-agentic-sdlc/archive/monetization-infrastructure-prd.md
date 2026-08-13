# Product Requirement Document (PRD)

## Feature
Monetization & Key Generation Infrastructure

## Summary
To enforce the commercial licensing model within the `aio-sdlc` CLI, the project requires a backend infrastructure to securely process payments, handle global taxes, and dynamically generate cryptographic license keys. This infrastructure will serve as the source of truth for the CLI to validate whether a commercial user has an active, paying subscription.

## User Stories
- As the product owner, I want a hands-off payment portal where businesses can buy a license, so I don't have to manually invoice them or generate keys.
- As a commercial user, I want to purchase a license via a standard checkout flow and instantly receive my license key via email so I can unlock the CLI.
- As the CLI runtime, I need a secure, highly available API endpoint to ping to verify if a provided license key is valid, expired, or revoked.

## Requirements
- **Zero-Infra Merchant of Record (MoR)**: Integrate a platform like **Lemon Squeezy** or **Paddle** to handle checkout, subscriptions, and global tax compliance (VAT) via their *hosted* storefronts. The implementation MUST NOT require building a custom website or checkout portal.
- **Managed Key Generation**: Utilize the MoR's native Software Licensing API (e.g., Lemon Squeezy's built-in licensing) to automatically issue keys upon successful payment without needing a custom backend.
- **SaaS Validation Endpoint**: The CLI MUST directly ping the MoR's provided cloud API endpoint to verify the key, eliminating the need to host a custom validation server.
- **Offline Validation (Optional)**: Support cryptographically signed keys (e.g., RSA-signed JWTs) so the CLI can verify the key's authenticity locally without requiring a network request on every single boot.
- **Product Tiers**: Define clear purchasing tiers:
  - Personal / Hobbyist (Free, No Key Required)
  - Commercial Seat (Monthly/Annual Subscription, Key Required)

## Out of Scope
- Building a custom payment gateway from scratch using raw Stripe APIs (using an MoR is required for tax compliance and simplicity).
- A complex web portal for users to manage seats (rely on the MoR's default customer portal).

## Acceptance Criteria
1. A user can navigate to a hosted checkout page and purchase a Commercial Seat.
2. The system automatically emails the user a valid license key upon successful payment.
3. The `aio-sdlc` CLI can programmatically validate that generated key against the licensing API.
