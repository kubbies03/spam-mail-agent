# Hướng dẫn chọn dataset, xử lý dữ liệu và train DistilBERT trên Kaggle

Tài liệu này dùng cho hướng classifier 3 lớp:

```text
safe | spam | phishing
```

Notebook chạy đầy đủ nằm tại: [`docs/kaggle-distilbert-email-security-notebook.ipynb`](kaggle-distilbert-email-security-notebook.ipynb).

Trong project, `phishing` là loại nguy cơ do model phát hiện, còn `suspicious` nên là quyết định cuối cùng của router/agent khi confidence thấp hoặc có tín hiệu rủi ro bổ sung.

## Dataset khuyến nghị

Dataset phù hợp nhất là **The Biggest Spam Ham Phish Email Dataset (250000+)** trên Kaggle.

- Kaggle slug: `akshatsharma2/the-biggest-spam-ham-phish-email-dataset-300000`
- Link: <https://www.kaggle.com/datasets/akshatsharma2/the-biggest-spam-ham-phish-email-dataset-300000>
- Ngôn ngữ: tiếng Anh.
- Quy mô: khoảng 250K+ mẫu.
- Nhãn gốc: `0 -> ham`, `1 -> phish`, `2 -> spam`.
- License: MIT.

Dataset này phù hợp hơn dataset 190K spam/ham vì có sẵn lớp phishing. Dataset 190K chỉ nên dùng khi train bài toán nhị phân `safe/spam`.

## Mapping Label

Chuẩn label dùng trong project:

```text
0, ham, safe, legitimate       -> safe
1, phish, phishing, scam       -> phishing
2, spam                        -> spam
```

Không nên train trực tiếp label `suspicious`. `suspicious` là trạng thái vận hành sau khi kết hợp model confidence, URL reputation, sender domain, rule signals và agent reasoning.

## Chuẩn Bị Dataset Trên Kaggle

Bật GPU trong Kaggle Notebook: `Settings > Accelerator > GPU`.

Tải dataset bằng Kaggle API:

```bash
kaggle datasets download \
  -d akshatsharma2/the-biggest-spam-ham-phish-email-dataset-300000 \
  -p /kaggle/working/dataset \
  --unzip
```

Nếu add dataset trực tiếp trong notebook UI, Kaggle thường mount tại:

```text
/kaggle/input/the-biggest-spam-ham-phish-email-dataset-300000
```

## Pipeline Kaggle End-to-End

Thứ tự cell nên chạy trên Kaggle:

```text
1. Bật GPU.
2. Add hoặc download dataset Kaggle.
3. Upload repo hoặc ít nhất upload notebook/script train.
4. Cài dependencies, nhưng không cài lại `torch` trên Kaggle vì runtime GPU đã có PyTorch CUDA.
5. Chạy cell xử lý dữ liệu để tạo `train.csv`, `valid.csv`, `test.csv`.
6. Train baseline với `--class-weights auto`.
7. Đọc `metrics.json`, kiểm tra `test_phishing_recall`.
8. Nếu recall thấp, tạo `train_oversampled.csv` và train lại.
9. Zip model artifact trong `/kaggle/working`.
```

Pipeline này giữ validation/test theo phân phối thật. Chỉ train set được oversample.

Nếu `torch.cuda.is_available()` trả `False`, vào `Settings > Accelerator > GPU`, bật GPU rồi restart session. Không tiếp tục train khi notebook đang chạy CPU.

## Xử Lý Dữ Liệu

Script train của project cần CSV cuối cùng có đúng hai cột:

```csv
text,label
"Please review the meeting notes",safe
"Congratulations, claim your prize now",spam
"Verify your password at this login page",phishing
```

Dùng đoạn xử lý sau trong Kaggle Notebook:

```python
from pathlib import Path
import pandas as pd

input_dir = Path("/kaggle/input/the-biggest-spam-ham-phish-email-dataset-300000")
if not input_dir.exists():
    input_dir = Path("/kaggle/working/dataset")

csv_files = list(input_dir.glob("*.csv"))
assert csv_files, f"No CSV files found in {input_dir}"

df = pd.read_csv(csv_files[0])
df.columns = [c.strip().lower() for c in df.columns]

text_candidates = {"text", "email", "message", "body", "content"}
label_candidates = {"label", "class", "category", "target"}

text_col = next(c for c in df.columns if c in text_candidates)
label_col = next(c for c in df.columns if c in label_candidates)

df = df.rename(columns={text_col: "text", label_col: "label"})
df["text"] = df["text"].fillna("").astype(str)
df["label"] = df["label"].astype(str).str.lower().str.strip()

label_map = {
    "0": "safe",
    "ham": "safe",
    "safe": "safe",
    "legitimate": "safe",
    "1": "phishing",
    "phish": "phishing",
    "phishing": "phishing",
    "scam": "phishing",
    "2": "spam",
    "spam": "spam",
}

df["label"] = df["label"].map(label_map)
df = df.dropna(subset=["label"])
df["text"] = df["text"].str.replace(r"\s+", " ", regex=True).str.strip()
df = df[df["text"].str.len() >= 20]
df = df.drop_duplicates(subset=["text"])

df = df[["text", "label"]].sample(frac=1, random_state=42)
df.to_csv("/kaggle/working/spam_phishing_dataset.csv", index=False)

print(df["label"].value_counts())
print(df.head())
```

Với phân phối thường gặp của dataset này:

```text
safe        127340
spam        107590
phishing     42820
```

Không nên downsample toàn bộ dataset xuống theo class nhỏ nhất ngay từ đầu, vì sẽ bỏ phí nhiều mẫu `safe` và `spam`. Pipeline nên là:

```text
clean data
 -> stratified train/valid/test split
 -> dùng class weights khi train
 -> chỉ oversample phishing trong train set nếu recall chưa đạt
```

## Split Train/Validation/Test

Chia dữ liệu trước khi oversample để tránh leakage. Validation và test phải giữ phân phối thật.

```python
from sklearn.model_selection import train_test_split

train_df, temp_df = train_test_split(
    df,
    test_size=0.2,
    stratify=df["label"],
    random_state=42,
)

valid_df, test_df = train_test_split(
    temp_df,
    test_size=0.5,
    stratify=temp_df["label"],
    random_state=42,
)

train_df.to_csv("/kaggle/working/train.csv", index=False)
valid_df.to_csv("/kaggle/working/valid.csv", index=False)
test_df.to_csv("/kaggle/working/test.csv", index=False)

print("train")
print(train_df["label"].value_counts())
print("valid")
print(valid_df["label"].value_counts())
print("test")
print(test_df["label"].value_counts())
```

## Xử Lý Imbalance

Ưu tiên dùng class weights trong training loss. Với phân phối trên, trọng số xấp xỉ:

```text
safe       0.73
spam       0.86
phishing   2.16
```

Công thức:

```python
counts = train_df["label"].value_counts()
total = counts.sum()
num_classes = len(counts)
class_weights = {
    label: total / (num_classes * count)
    for label, count in counts.items()
}
print(class_weights)
```

`scripts/train_distilbert.py` đã hỗ trợ `--class-weights auto` và dùng `torch.nn.CrossEntropyLoss(weight=...)` trong custom `Trainer.compute_loss`.

Chỉ oversample phishing nếu sau lần train đầu tiên `phishing_recall` chưa đạt mục tiêu. Oversample chỉ áp dụng cho `train_df`, không áp dụng cho `valid_df` hoặc `test_df`.

```python
target_phishing = 85000

phishing_df = train_df[train_df["label"] == "phishing"]
other_df = train_df[train_df["label"] != "phishing"]

phishing_up = phishing_df.sample(
    n=target_phishing,
    replace=True,
    random_state=42,
)

train_oversampled = (
    pd.concat([other_df, phishing_up], ignore_index=True)
    .sample(frac=1, random_state=42)
)

train_oversampled.to_csv("/kaggle/working/train_oversampled.csv", index=False)
print(train_oversampled["label"].value_counts())
```

Không nên oversample phishing lên bằng `safe` ngay từ đầu nếu chỉ duplicate dữ liệu, vì model có thể overfit các mẫu phishing lặp lại. Mốc hợp lý ban đầu là khoảng `70K-90K` phishing trong train set.

## Train DistilBERT 3 Lớp Trên Kaggle

Pipeline train hiện tại dùng 3 label trong `scripts/train_distilbert.py`:

```python
id2label = {0: "safe", 1: "phishing", 2: "spam"}
label2id = {"safe": 0, "phishing": 1, "spam": 2}
```

Chạy baseline với class weights và split thật:

```bash
python scripts/train_distilbert.py \
  --csv /kaggle/working/train.csv \
  --validation-csv /kaggle/working/valid.csv \
  --test-csv /kaggle/working/test.csv \
  --text-col text \
  --label-col label \
  --base-model distilbert-base-uncased \
  --output /kaggle/working/distilbert_email_security \
  --epochs 2 \
  --batch-size 8 \
  --class-weights auto
```

Nếu muốn giữ multilingual model:

```bash
--base-model distilbert-base-multilingual-cased
```

Với dataset tiếng Anh, `distilbert-base-uncased` thường là lựa chọn gọn và phù hợp hơn.

Nếu lần train đầu có `phishing_recall` thấp, chạy lại với train oversampled:

```bash
python scripts/train_distilbert.py \
  --csv /kaggle/working/train_oversampled.csv \
  --validation-csv /kaggle/working/valid.csv \
  --test-csv /kaggle/working/test.csv \
  --text-col text \
  --label-col label \
  --base-model distilbert-base-uncased \
  --output /kaggle/working/distilbert_email_security_oversampled \
  --epochs 2 \
  --batch-size 8 \
  --class-weights auto
```

## Đánh Giá Model

Ưu tiên xem macro metrics, không chỉ accuracy:

- `macro_f1`: chất lượng tổng thể khi có nhiều class.
- `phishing_recall`: khả năng không bỏ sót phishing.
- `phishing_precision`: khả năng tránh báo nhầm phishing.
- confusion matrix: kiểm tra phishing có bị nhầm sang spam hay safe không.

Ngưỡng kỳ vọng ban đầu:

```text
macro_f1 >= 0.90
phishing_recall >= 0.90
```

Nếu phishing hay bị nhầm thành spam, tăng dữ liệu phishing hoặc dùng class weight/focal loss trong training.

Lỗi nguy hiểm nhất là:

```text
phishing -> safe
```

Nếu phishing bị nhầm sang spam, router vẫn có thể escalate. Nếu phishing bị nhầm sang safe, cần tăng `phishing_recall` bằng class weights mạnh hơn, oversampling train set, hoặc bổ sung dữ liệu phishing thật.

## Lưu Artifact Về Project

Nén model trên Kaggle:

```bash
cd /kaggle/working
zip -r distilbert_email_security.zip distilbert_email_security
```

Tải zip về máy và giải nén vào:

```text
models/distilbert_multilingual/
```

Tên thư mục local vẫn giữ `distilbert_multilingual` để khớp runtime hiện tại của `SpamClassifier`.

Thư mục model nên có:

```text
config.json
model.safetensors hoặc pytorch_model.bin
tokenizer.json
tokenizer_config.json
special_tokens_map.json
metrics.json
```

Kiểm tra local:

```bash
python main.py classify-text --text "verify your password at http://login-example.xyz"
```

Kỳ vọng model trả class gần với `phishing`. Router/agent sau đó có thể quyết định final verdict là `spam` hoặc `suspicious` tùy risk score và rule signals.

## Ghi Chú Versioning

Không commit model lớn nếu repo chưa dùng Git LFS. Nên lưu artifact ở Kaggle output, release, cloud storage hoặc model registry. Commit các thông tin nhỏ sau:

- Dataset slug và version.
- Base model.
- Số epoch, batch size, max length.
- Label mapping.
- Metrics chính.
- Ngày train.
