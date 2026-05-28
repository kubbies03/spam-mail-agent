# Spam Agent Deployment

## Runtime Architecture

The production runtime is a hybrid pipeline:

1. DistilBERT runs first as the fast classifier.
2. The router decides whether the email can stay on the fast path or must escalate to the agent.
3. The agent/explainer combines classifier output with URL and sender evidence to produce the final operational verdict.

Important distinction:

- DistilBERT predicts a raw classifier label: `safe`, `phishing`, or `spam`.
- The product-level final verdict remains: `safe`, `suspicious`, or `spam`.
- A raw classifier label of `phishing` is preserved in runtime metadata and notifications, but it does not automatically become a new top-level final verdict.

## Production Artifact

The standard DistilBERT runtime artifact path is:

`models/distilbert_multilingual`

For backward compatibility, runtime also supports a legacy artifact under:

`docs/22590`

Relevant runtime setting:

- `DISTILBERT_MODEL_DIR=models/distilbert_multilingual`

The artifact config currently maps labels as:

```json
{
  "0": "safe",
  "1": "phishing",
  "2": "spam"
}
```

## Model Behavior In Production

The classifier returns structured output, not a binary spam score only:

- `verdict`: top predicted classifier label
- `class_probabilities`: per-class probabilities for `safe`, `phishing`, `spam`
- `confidence`: probability of the top class
- `risk_score`: `max(phishing_prob, spam_prob)`
- `signals`: keyword/rule signals gathered alongside the model result

The SVM + TF-IDF path still exists as a local fallback for development and tests, but it is only a binary `safe/spam` fallback and does not match the fidelity of the DistilBERT 3-class path.

## Routing Rules

The router escalates to the agent when any of these are true:

- classifier confidence is below `CLASSIFIER_THRESHOLD`
- `phishing_probability >= PHISHING_ESCALATION_THRESHOLD`
- `spam_probability >= SPAM_ESCALATION_THRESHOLD`
- suspicious URL evidence is present
- sender reputation is weak or unknown
- enough heuristic signals are present

Recommended defaults:

- `CLASSIFIER_THRESHOLD=0.82`
- `PHISHING_ESCALATION_THRESHOLD=0.50`
- `SPAM_ESCALATION_THRESHOLD=0.65`

`phishing` is treated as the stronger signal. A high-confidence phishing prediction can still be routed to the agent even when the classifier itself is confident.

## Final Verdict Logic

The classifier does not own the final verdict.

Final verdicts are decided after combining:

- classifier `risk_score`
- classifier raw label
- URL analysis
- sender analysis
- explanation/agent reasoning

Operational mapping:

- low risk -> `safe`
- medium risk or conflicting evidence -> `suspicious`
- strong spam/phishing evidence -> `spam`

When the classifier predicts `phishing`, runtime metadata should preserve that raw label even if the final verdict becomes `suspicious` or `spam`.

## Notifications

Telegram alerts should include:

- final verdict
- raw classifier label
- overall risk
- short summary of why the message is risky
- key indicators such as suspicious URLs, credential requests, unknown domain age, or high phishing probability

This keeps notifications understandable for operators without exposing the raw model output alone as the final decision.

## Training Setup

The current DistilBERT artifact was trained as a 3-class classifier with labels:

- `safe`
- `phishing`
- `spam`

Training flow:

- dataset preparation and label normalization
- stratified train/validation/test split
- class-weighted DistilBERT fine-tuning
- best checkpoint selection using `macro_f1`
- export of the final Hugging Face artifact used by runtime

This deployment should not describe the model as a binary `ham/spam` system. Any examples using `num_labels=2` or `ham/spam` are out of date for the production DistilBERT path.

## Observed Metrics For Current Artifact

From the repository training artifacts:

- best validation macro F1: about `0.9913`
- phishing recall: about `0.9932`
- weighted F1: about `0.9917`
- validation loss at the best checkpoint: about `0.1289`

The best checkpoint was selected by `macro_f1`, not by binary spam accuracy.

## Environment And Operations

Example environment values:

```env
CLASSIFIER_THRESHOLD=0.82
PHISHING_ESCALATION_THRESHOLD=0.50
SPAM_ESCALATION_THRESHOLD=0.65
DISTILBERT_MODEL_DIR=models/distilbert_multilingual
```

Operational notes:

- keep Redis, Gemini, VirusTotal, Gmail, and Telegram integrations optional
- the system must still classify locally when those services are unavailable
- runtime prefers `models/distilbert_multilingual` and falls back to `docs/22590` if the legacy artifact is the only available one
