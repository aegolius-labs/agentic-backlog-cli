# Product Requirement Document (PRD)

## Feature
Commercial Licensing Enforcement & AI Disclaimers

## Summary
As a powerful autonomous software factory, `aio-sdlc` presents significant commercial value while also carrying inherent risks regarding AI-generated code. This feature introduces the necessary legal and technical mechanisms to ensure the tool remains strictly free for personal, non-commercial use, while requiring businesses to pay a licensing fee. It also adds necessary AI liability disclaimers to protect the creator.

## User Stories
- As the creator, I want to allow hobbyists to use the tool for free, but legally and technically require corporations to purchase a commercial license.
- As the creator, I want to ensure users are explicitly warned that AI-generated code can contain bugs and vulnerabilities, removing liability from me.
- As a commercial user, I want a clear mechanism to input my purchased license key to unlock the software for enterprise use.

## Requirements
- **Legal License File**: Add a strict source-available, non-commercial license file (e.g., PolyForm Noncommercial 1.0.0 or a custom Dual License) to the repository root.
- **AI Disclaimer**: A permanent disclaimer MUST be added to the `README.md` and the initial startup output of the CLI, stating that the software autonomously generates code using LLMs, which requires human review, and the creator is not liable for damages.
- **EULA & Privacy Clickwrap**: Upon first launch of the CLI, the user MUST be prompted to explicitly accept the Non-Commercial Terms of Service and the Privacy Policy. The prompt MUST clearly disclose the collection of anonymous telemetry data, provide a link to the full terms (which MUST be hosted as simple `TERMS.md` and `PRIVACY.md` files in the public GitHub repository to avoid needing a website), and explain how to opt out. The user MUST type `yes` to agree before proceeding.
- **Commercial License Key API (Technical Enforcement)**: Integrate a lightweight software licensing API (such as Keygen.sh or Cryptlex). 
  - The `.aio-agentic-sdlc/config.json` configuration MUST support a `commercial_license_key` field.
  - If the CLI detects it is running in an enterprise environment (e.g., via the standalone BYOK Daemon mode, CI/CD environment variables, or specific enterprise OS flags), it MUST block execution unless a valid license key is verified via the API.

## Out of Scope
- Heavy Digital Rights Management (DRM) or code obfuscation. The codebase will remain readable, relying on standard "honest-actor" checks and legal copyright enforcement rather than uncrackable encryption.

## Acceptance Criteria
1. The repository contains a clear Non-Commercial `LICENSE` file and an AI disclaimer in the `README.md`.
2. First-time users are blocked from executing the CLI until they agree to the Terms of Service and Privacy Policy regarding data collection.
3. Enterprise users running the headless daemon MUST provide a valid license key, which the CLI validates via an external licensing API before booting.
