# Run And Test Guide

## Muc tieu

Tai lieu nay mo ta:

- cach chay project o local/dev
- cach kiem tra nhanh tung luong chinh
- cach test end-to-end voi Gmail that
- cac dau hieu de biet he thong dang chay dung

Project hien tai co 2 che do kiem tra quan trong:

- `self-test`: chay end-to-end local, khong phu thuoc Gmail
- `poll-once --limit 1`: kiem tra luong Gmail that voi 1 email

## 1. Chuan bi moi truong

Tao virtual environment va cai dependency:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Neu dung PowerShell va bi chan script:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## 2. Cau hinh `.env`

Copy file mau:

```powershell
Copy-Item .env.example .env
```

Nhung bien quan trong:

- `GMAIL_USER`
- `GMAIL_APP_PASSWORD`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `GOOGLE_API_KEY`
- `VIRUSTOTAL_API_KEY`

Gia tri runtime quan trong hien tai:

```env
DISTILBERT_MODEL_DIR=models/distilbert_multilingual
CLASSIFIER_THRESHOLD=0.82
PHISHING_ESCALATION_THRESHOLD=0.50
SPAM_ESCALATION_THRESHOLD=0.65
URL_ANALYSIS_LIMIT=8
```

## 3. Kiem tra model

Runtime fast classifier uu tien model tai:

`models/distilbert_multilingual`

Thu muc nay can co cac file inference chinh:

- `config.json`
- `model.safetensors`
- `tokenizer.json`
- `tokenizer_config.json`
- `vocab.txt`

Neu khong co model nay, runtime co the fallback ve artifact cu trong:

`docs/22590`

## 4. Chay test local nhanh

### 4.1. Compile check

Dung de kiem tra syntax:

```powershell
python -m compileall main.py src
```

Ky vong:

- khong co syntax error

### 4.2. Classify mot doan text

```powershell
python main.py classify-text --text "urgent verify your account at https://login-example.xyz"
```

Ky vong:

- he thong tra JSON
- co cac truong `route`, `classifier`, `final_verdict`, `risk_score`

### 4.3. Self-test end-to-end local

Day la cach test quan trong nhat de xac nhan pipeline chay tron luong ma khong can Gmail.

```powershell
python main.py self-test
```

Lenh nay tu tao 2 email mau:

- 1 email an toan
- 1 email rui ro

Ky vong:

- output JSON co `results`
- co it nhat 2 ket qua
- mot ket qua co `route=fast`
- mot ket qua co `route=agent`
- co them `analytics`

Neu Gemini hoac VirusTotal loi/quota het:

- pipeline van phai chay xong
- `explanation.raw.source` se la `fallback`

## 5. Test Gmail that

### 5.1. Kiem tra 1 lan voi 1 email

Dung lenh nay truoc:

```powershell
python main.py poll-once --limit 1
```

Lenh nay:

- ket noi Gmail IMAP
- lay toi da 1 email chua doc
- parse
- classify
- luu DB
- in ket qua JSON

Ky vong:

- output la `[]` neu khong co email chua doc
- hoac output la mang JSON co ket qua phan loai

Neu IMAP bi chan hoac loi mang:

- he thong log `gmail_fetch_failed`
- khong crash
- output van la `[]`

### 5.2. Kiem tra nhieu email

```powershell
python main.py poll-once --limit 5
```

Chi nen tang `limit` sau khi da xac nhan `--limit 1` hoat dong on.

### 5.3. Chay lien tuc

```powershell
python main.py run
```

Ky vong:

- scheduler bat dau polling theo `POLL_INTERVAL_SECONDS`
- process tiep tuc chay cho den khi ban dung bang `Ctrl+C`

## 6. Kiem tra analytics

Sau khi da co ket qua trong DB:

```powershell
python main.py analytics
```

Ky vong:

- JSON co `total`
- co `spam_ratio`
- co `agent_ratio`
- co `avg_confidence`

## 7. Cac truong hop fallback binh thuong

Day khong phai loi gay he thong neu lenh van tra ket qua:

- `gmail_fetch_failed`
  Nghia la IMAP dang loi hoac mang bi chan.

- `virustotal_failed`
  Nghia la VirusTotal het quota, bi rate-limit, hoac loi mang.

- `gemini_explainer_failed`
  Nghia la Gemini loi key, billing cap, model, hoac mang.
  He thong se fallback sang explanation local.

- `telegram_disabled`
  Nghia la Telegram chua du dieu kien runtime hoac dependency/token/chat id chua san sang.

## 8. Dau hieu xac nhan he thong dang chay dung

He thong duoc xem la chay dung o local/dev khi:

1. `python -m compileall main.py src` thanh cong.
2. `python main.py self-test` tra du 2 ket qua va khong crash.
3. `python main.py poll-once --limit 1` ket thuc duoc.
4. `python main.py analytics` tra JSON hop le.

He thong duoc xem la chay end-to-end voi Gmail that khi:

1. `poll-once --limit 1` fetch duoc email that.
2. email duoc parse va tra JSON ket qua.
3. ket qua duoc ghi vao DB.
4. `analytics` tang `total`.

## 9. Cac lenh khuyen nghi de demo

Demo local nhanh:

```powershell
python main.py self-test
```

Demo classify text:

```powershell
python main.py classify-text --text "Please review the sprint notes for tomorrow"
python main.py classify-text --text "Urgent verify your password now at https://login-example.xyz"
```

Demo Gmail that:

```powershell
python main.py poll-once --limit 1
python main.py analytics
```

## 10. Ghi chu van hanh

- Neu Gmail inbox co nhieu email marketing chua doc, `poll-once` co the cham hon do URL analysis.
- `URL_ANALYSIS_LIMIT=8` da duoc them de tranh mot email co qua nhieu link gay tac quota VirusTotal.
- Neu muon explanation LLM that, can kiem tra:
  - Gemini billing cap
  - model Gemini hop le
  - outbound network
- Neu muon alert Telegram, can xac nhan:
  - dependency Telegram da cai
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_CHAT_ID`

