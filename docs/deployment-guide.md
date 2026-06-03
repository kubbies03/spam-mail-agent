# Deployment Guide — GitOps on k3s

Production-like deployment của spam-mail-agent sử dụng:
**GitHub Actions CI → Docker Hub → ArgoCD → k3s cluster → Prometheus + Grafana**

---

## Prerequisites

| Thứ | Yêu cầu |
|---|---|
| VM | Ubuntu 22.04, tối thiểu 2 CPU / 4 GB RAM |
| GitHub repo | Fork hoặc push code lên `github.com/<you>/spam-mail-agent` |
| Docker Hub | Account tại hub.docker.com, tạo repo `<you>/spam-agent` |
| API keys | Google Gemini, VirusTotal, Telegram bot token (tuỳ chọn) |
| Gmail | App Password cho IMAP (tuỳ chọn nếu chỉ dùng HTTP API) |

---

## Bước 1 — Cài k3s trên VM

```bash
# SSH vào VM
ssh user@<VM_IP>

# Cài k3s (lightweight Kubernetes)
curl -sfL https://get.k3s.io | sh -

# Cho phép user thường dùng kubectl
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $USER:$USER ~/.kube/config

# Verify
kubectl get nodes
# Expected: NAME   STATUS   ROLES                  AGE   VERSION
#           vm     Ready    control-plane,master   1m    v1.x.x
```

---

## Bước 2 — Cài Nginx Ingress Controller

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.1/deploy/static/provider/cloud/deploy.yaml

# Đợi controller ready
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=120s
```

---

## Bước 3 — Cài ArgoCD

```bash
kubectl create namespace argocd
kubectl apply -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Lấy initial admin password
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d && echo

# Port-forward để truy cập UI (chạy trên máy local)
kubectl port-forward svc/argocd-server -n argocd 8080:443
# Mở browser: https://localhost:8080  (admin / <password vừa lấy>)
```

---

## Bước 4 — Cài Prometheus + Grafana

```bash
# Cài Helm nếu chưa có
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set grafana.adminPassword=admin123 \
  --set grafana.sidecar.dashboards.enabled=true \
  --set grafana.sidecar.dashboards.label=grafana_dashboard

# Port-forward Grafana (máy local)
kubectl port-forward svc/monitoring-grafana -n monitoring 3000:80
# Mở browser: http://localhost:3000  (admin / admin123)
```

---

## Bước 5 — Cấu hình GitHub Secrets

Trong GitHub repo → Settings → Secrets and variables → Actions, thêm:

| Secret | Value |
|---|---|
| `DOCKERHUB_USERNAME` | Docker Hub username của bạn |
| `DOCKERHUB_TOKEN` | Docker Hub Access Token (tạo tại hub.docker.com → Account Settings → Security) |

> `GITHUB_TOKEN` được GitHub tự inject, không cần thêm thủ công.

---

## Bước 6 — Điền secrets vào k8s/secret.yaml

```bash
# Encode từng giá trị
echo -n "your-gmail@gmail.com" | base64
echo -n "your-app-password"    | base64
echo -n "your-telegram-token"  | base64
echo -n "your-chat-id"         | base64
echo -n "your-google-api-key"  | base64
echo -n "your-vt-api-key"      | base64
```

Paste kết quả vào các trường `<base64-encoded-value>` trong [k8s/secret.yaml](../k8s/secret.yaml).

**Lưu ý**: Không commit file secret.yaml có giá trị thật. Thay vào đó dùng:
```bash
# Apply trực tiếp mà không commit
kubectl apply -f k8s/secret.yaml -n spam-agent
```

---

## Bước 7 — Cập nhật domain trong Ingress

Mở [k8s/ingress.yaml](../k8s/ingress.yaml), đổi:
```yaml
host: spam-agent.example.com
```
thành IP của VM hoặc domain thật. Nếu không có domain:
```yaml
# Xoá dòng host để dùng IP trực tiếp
# hoặc thêm vào /etc/hosts trên máy client:
# <VM_IP>  spam-agent.local
```

---

## Bước 8 — Apply ArgoCD Application

```bash
# Trên VM hoặc máy local đã có kubectl context
kubectl apply -f argocd-app.yaml
```

ArgoCD sẽ tự động sync toàn bộ folder `k8s/` lên cluster.

Kiểm tra trạng thái:
```bash
kubectl get application spam-agent -n argocd
# Expected: STATUS=Synced  HEALTH=Healthy
```

---

## Bước 9 — Push code để trigger CI/CD

```bash
git add .
git commit -m "feat: initial GitOps deployment"
git push origin main
```

Pipeline sẽ tự động chạy:
1. **Test** — `pytest tests/`
2. **Build & Push** — build Docker image → push `kubbies03/spam-agent:<sha>`
3. **Update manifest** — sửa `k8s/deployment.yaml` image tag → commit `[skip ci]`
4. **ArgoCD detects** — thấy manifest thay đổi → sync lên cluster
5. **Rolling update** — k8s replace pod cũ bằng pod mới (zero downtime)

---

## Bước 10 — Áp dụng Grafana dashboard

```bash
kubectl apply -f k8s/monitoring/grafana-dashboard.yaml
kubectl apply -f k8s/monitoring/servicemonitor.yaml
```

Mở Grafana → Dashboards → "Spam Mail Agent" để xem metrics.

---

## Kiểm tra sau deploy

```bash
# Lấy IP của Ingress
kubectl get ingress -n spam-agent

# Test /health
curl http://<INGRESS_IP>/health
# {"status":"ok","classifier":"ready"}

# Test /classify
curl -X POST http://<INGRESS_IP>/classify \
  -H "Content-Type: application/json" \
  -d '{
    "sender": "promo@deals-winner2026.top",
    "subject": "CONGRATULATIONS! You won $1000!",
    "body": "Click here to claim your prize NOW: http://bit.ly/win-free"
  }'

# Test /metrics
curl http://<INGRESS_IP>/metrics
```

---

## Cấu trúc files đã tạo

```
spam-mail-agent/
├── app/
│   └── main.py                  # FastAPI app (/classify /health /metrics)
├── Dockerfile                   # Multi-stage build (builder + runtime)
├── docker-compose.yml           # Local dev: api + poller + redis
├── .github/
│   └── workflows/
│       └── ci.yml               # GitHub Actions: test → build → push → update-manifest
├── k8s/
│   ├── namespace.yaml           # spam-agent namespace
│   ├── configmap.yaml           # App config (non-secret env vars)
│   ├── secret.yaml              # Credentials (fill base64 values, don't commit)
│   ├── pvc.yaml                 # PersistentVolumeClaims for data + models
│   ├── deployment.yaml          # api (2 replicas) + poller (1) + redis
│   ├── service.yaml             # ClusterIP services
│   ├── ingress.yaml             # Nginx Ingress
│   └── monitoring/
│       ├── servicemonitor.yaml  # Prometheus ServiceMonitor
│       └── grafana-dashboard.yaml # Grafana dashboard ConfigMap
└── argocd-app.yaml              # ArgoCD Application (apply once)
```

---

## Troubleshooting

| Triệu chứng | Nguyên nhân | Fix |
|---|---|---|
| Pod `CrashLoopBackOff` | Secret thiếu hoặc sai | `kubectl logs -n spam-agent <pod>` kiểm tra lỗi |
| ArgoCD status `OutOfSync` | Manifest khác với cluster | ArgoCD UI → Sync, hoặc `argocd app sync spam-agent` |
| `/health` trả 503 | Pod chưa ready (model loading) | Đợi 60s (initialDelaySeconds), xem log |
| Image pull error | Docker Hub credentials sai | Kiểm tra `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN` secrets |
| Prometheus không scrape | ServiceMonitor label không khớp | Kiểm tra label `release:` trùng với Helm release name |
| PVC `Pending` | StorageClass không có | k3s dùng `local-path` mặc định, kiểm tra `kubectl get sc` |

---

## Local development (không cần k8s)

```bash
# Clone và cài deps
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env  # điền credentials

# Chạy API server
uvicorn app.main:app --reload --port 8000

# Hoặc dùng Docker Compose
docker compose up --build
```
