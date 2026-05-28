# Few-Shot Tet Email Examples

This file provides English few-shot examples for Tet-season emails in the same classification space used by the project:

- `safe`
- `spam`
- `phishing`

The source dataset `docs/df.csv` is English, so these examples are also written in English to stay closer to the model's expected distribution.

## Suggested System Usage

Use this file as supporting context in the system prompt or agent prompt:

```text
Below are labeled email examples for the classes safe, spam, and phishing. Learn the intent, tone, and risk patterns from these examples. When classifying a new email, return only one label: safe, spam, or phishing.
```

## Dataset Alignment

The dataset in `docs/df.csv` is stored in `label,text` format. This Markdown file is prompt-friendly, but the examples below can also be converted into the same two-column structure if needed.

Recommended label mapping for prompt-side generation:

- `safe` -> legitimate email, normal communication
- `spam` -> unsolicited promotion, bulk marketing, low-trust advertising
- `phishing` -> credential theft, payment fraud, account verification scam, malicious impersonation

## Few-Shot Examples

### Example 1

**Label:** `safe`

**Subject:** `Tet holiday schedule for all employees`

**Body:**

```text
Hello team,

Please note that the company will be closed for the Tet holiday from February 14 through February 20.
Normal operations will resume on February 21.

If you are supporting any critical customer issue during the holiday period, please coordinate directly with your department manager.

Wishing you and your family a happy, healthy, and prosperous new year.

HR Department
```

**Why:** `Legitimate internal notice, no pressure, no suspicious link, no request for credentials or payment details.`

### Example 2

**Label:** `safe`

**Subject:** `Happy Lunar New Year from ABC Logistics`

**Body:**

```text
Dear valued customer,

As we welcome the Lunar New Year, everyone at ABC Logistics would like to thank you for your support throughout the past year.

We wish you peace, prosperity, and continued success in the year ahead.

Our post-holiday operating schedule will be shared separately by your account representative.

Best regards,
ABC Logistics
```

**Why:** `Normal business greeting with no risky action requested.`

### Example 3

**Label:** `safe`

**Subject:** `Order confirmation for your Tet gift basket`

**Body:**

```text
Hello Ms. Nguyen,

Your Tet gift basket order has been successfully confirmed.

Order summary:
- Product: Prosperity Tet Basket
- Quantity: 1
- Total: 890,000 VND
- Estimated delivery: before 5:00 PM on February 8

If you need to update your delivery address, please reply to this email or contact our official customer support line.

Thank you for shopping with us.
```

**Why:** `Specific transactional content, no urgent credential request, no fake account verification language.`

### Example 4

**Label:** `spam`

**Subject:** `Tet Mega Sale 70 percent off today only`

**Body:**

```text
HAPPY NEW YEAR.

Enjoy our Tet Mega Sale with discounts of up to 70 percent on all seasonal gift products.
Limited inventory. Buy now before the promotion ends tonight.

Click here to browse the latest catalog and place your order now.
Free nationwide shipping and bonus gifts available for early buyers.
```

**Why:** `Bulk promotional language, aggressive sales style, unsolicited marketing, but not directly asking for passwords, OTPs, or payment verification.`

### Example 5

**Label:** `spam`

**Subject:** `Claim your Lunar New Year shopping voucher now`

**Body:**

```text
Dear customer,

To celebrate Tet, we are sending a 500,000 VND shopping voucher to selected customers.
Use it today on our holiday combo packages including sweets, tea, and premium gift sets.

Respond now to reserve your discount before the promotion expires at midnight.
```

**Why:** `Promotional mass-mail tone, urgency used for marketing, but no impersonation or credential theft pattern.`

### Example 6

**Label:** `spam`

**Subject:** `Start the new year with a high-return property investment`

**Body:**

```text
Dear investor,

The Lunar New Year is the perfect time to secure high-growth real estate opportunities.
Register today to receive our special launch pricing and priority consultation.

Our sales team will contact you immediately after submission.
```

**Why:** `Broad marketing outreach, commercially aggressive, likely unsolicited, but not phishing by itself.`

### Example 7

**Label:** `phishing`

**Subject:** `Urgent account verification required before Tet`

**Body:**

```text
Dear customer,

We detected unusual activity on your bank account during the holiday period.
To avoid temporary suspension before Tet, you must verify your account within 30 minutes using the secure link below:

http://vietcom-secure-tet-bonus.verify-account.example

Failure to complete verification will result in account restrictions.

Online Support Team
```

**Why:** `Impersonates a bank, creates time pressure, and pushes the user to a suspicious verification link.`

### Example 8

**Label:** `phishing`

**Subject:** `Tet bonus gift confirmation for employees`

**Body:**

```text
Hello,

You have been selected to receive a special Tet bonus gift from the employee welfare program.
To confirm eligibility, please sign in with your company email account and submit your one-time password at the form below:

https://tet-thuong-congdoan-login.example/claim

If you do not complete the form before 11:00 PM tonight, your reward will be canceled.
```

**Why:** `Credential harvesting attempt using a reward pretext and OTP submission request.`

### Example 9

**Label:** `phishing`

**Subject:** `Payment failed for your Tet flower delivery`

**Body:**

```text
Your Tet flower delivery could not be processed because your card was declined.

Please update your payment information before 12:00 PM today to avoid cancellation:

https://payment-update-tet-order.example

If payment is not updated in time, your order will be canceled and a storage fee may apply.
```

**Why:** `Fake payment problem, pressure-based language, and a direct attempt to capture card data.`

## Tet-Specific Patterns Worth Teaching The AI

- Tet greetings, Tet gifts, Tet bonuses, and holiday schedules can be used as a trusted-looking wrapper.
- Phrases like `today only`, `within 30 minutes`, `before 11:00 PM`, and `your account will be suspended` are strong pressure signals.
- Requests to `sign in`, `verify account`, `submit OTP`, `update payment`, or `confirm card details` should strongly raise phishing risk.
- Spam often contains exaggerated promotions, all-caps style, broad offers, and weak personalization.
- Safe emails usually contain operational detail, relationship context, or normal business communication without risky calls to action.

## Prompt-Ready Compact Format

If you want a simpler format for direct insertion into a system prompt, use:

```text
Label: <safe|spam|phishing>
Subject: <email subject>
Body:
<email body>
Why: <brief rationale>
```

## CSV-Style Synthetic Rows

If you want examples closer to `docs/df.csv`, use this compact `label,text` style:

```text
safe,"hello team please note that the company will be closed for the tet holiday from february 14 through february 20 normal operations will resume on february 21 wishing you and your family a prosperous new year hr department"
spam,"happy new year enjoy our tet mega sale with discounts up to 70 percent limited inventory buy now before the promotion ends tonight free shipping available"
phishing,"we detected unusual activity on your bank account during the holiday period verify your account within 30 minutes using the secure link below failure to complete verification will result in account restrictions"
```
