# Tổng Quan Agent Spam Mail

Tài liệu này tổng hợp ngắn gọn cách project hoạt động theo đúng code hiện tại trong repo.

## 1. `VIRUSTOTAL_API_KEY` là gì

`VIRUSTOTAL_API_KEY` là khóa API dùng để gọi dịch vụ VirusTotal nhằm kiểm tra độ uy tín và mức độ nguy hiểm của URL xuất hiện trong email.

Trong project này:

- Cấu hình nằm ở `src/config.py`.
- Logic sử dụng nằm ở `src/security.py`.
- Nếu có API key, hệ thống gửi URL lên VirusTotal và đọc về các chỉ số như `malicious` và `suspicious`.
- Nếu không có API key, hệ thống vẫn chạy bình thường và dùng heuristic nội bộ để đánh giá URL.

Các heuristic hiện có gồm:

- URL dùng địa chỉ IP thay vì domain
- URL shortener như `bit.ly`
- TLD đáng nghi như `.zip`, `.top`, `.xyz`
- Domain có nhiều dấu gạch nối
- Mẫu giả mạo thương hiệu
- Link không dùng HTTPS

Kết luận: `VIRUSTOTAL_API_KEY` là thành phần bổ sung để tăng tín hiệu bảo mật, không phải điều kiện bắt buộc để agent hoạt động.

## 2. Agent hoạt động như thế nào

Luồng chính của hệ thống:

1. Email được nhận từ Gmail IMAP hoặc từ lệnh CLI trong `main.py`.
2. `SpamEmailPipeline` kiểm tra email đã được xử lý chưa.
3. `HybridRouter` chạy bộ phân loại cục bộ, phân tích URL, và kiểm tra domain người gửi.
4. Nếu email đủ rõ ràng thì đi `fast path`.
5. Nếu email mơ hồ hoặc có tín hiệu rủi ro thì đi `agent path`.
6. Kết quả cuối cùng được lưu vào DB.
7. Nếu verdict là `spam` hoặc `suspicious` thì có thể gửi cảnh báo Telegram.

## 3. “Não” của hệ thống là gì

Project này không có một “não” duy nhất. Nó là một kiến trúc lai gồm nhiều lớp:

- `SpamClassifier`: bộ phân loại chính để chấm điểm spam/phishing.
- `security.py`: lớp phân tích bảo mật cho URL và domain người gửi.
- `LangGraph` trong `src/agent.py`: lớp điều phối các bước phân tích khi cần agent path.
- `GeminiExplainer`: lớp tạo giải thích bằng tiếng Việt nếu có `GOOGLE_API_KEY`.

Nói ngắn gọn:

- Não phân loại chính: model classifier cục bộ, theo README là DistilBERT fine-tuned.
- Não điều phối: LangGraph.
- Não giải thích: Gemini hoặc fallback rule-based explanation.

## 4. Mô hình này có được gọi là agent không

Có thể gọi là agent, nhưng chính xác hơn là một hệ thống lai có thành phần agentic.

Lý do có thể gọi là agent:

- Có nhiều bước phối hợp với nhau.
- Có các tool riêng cho classify, URL check, sender lookup.
- Có graph điều hướng luồng xử lý.
- Có bước tổng hợp để ra verdict cuối.

Nhưng cũng cần phân biệt:

- Đây không phải autonomous agent mạnh theo kiểu tự lập kế hoạch dài hạn.
- Nó không có mục tiêu mở rộng liên tục hay tự quyết định hành động phức tạp trên nhiều hệ thống.
- Thành phần “agent” chủ yếu nằm ở `src/agent.py`, không phải toàn bộ hệ thống đều agentic.

Tên gọi phù hợp hơn:

- hybrid spam detection pipeline
- agentic spam detection workflow
- hybrid system with LangGraph orchestration

## 5. Nếu tăng mức đóng góp của agent thì sao

Nếu tăng mức đóng góp của agent, hệ thống sẽ linh hoạt hơn nhưng cũng chậm hơn và khó kiểm soát hơn.

Các cách tăng vai trò agent:

- Hạ ngưỡng escalation để nhiều email đi vào `agent path` hơn.
- Cho agent tham gia nhiều hơn vào quyết định cuối thay vì chỉ dùng classifier và heuristic.
- Bổ sung thêm tool như SPF/DKIM/DMARC, reputation service, attachment scanning, header anomaly detection.
- Cho agent thực hiện thêm hành động sau phân loại.

Lợi ích:

- Bắt được nhiều case phishing hoặc spam tinh vi hơn.
- Xử lý tốt hơn các email khó phân loại bằng rule cứng.
- Có thể mở rộng logic theo hướng linh hoạt hơn.

Rủi ro:

- Tăng latency.
- Tăng chi phí nếu phụ thuộc LLM hoặc API ngoài.
- Kết quả có thể kém deterministic hơn.
- Việc test, audit, và debug sẽ khó hơn.

Khuyến nghị cho project này:

- Giữ classifier và heuristic làm lớp nền.
- Chỉ tăng vai trò agent cho vùng mơ hồ hoặc high-risk.
- Ưu tiên thêm tool tín hiệu mạnh trước khi tăng mức tự do suy luận.

## 6. Agent tự đánh giá và lưu vào DB thì sao

Hiện tại repo đã gần như làm điều này, nhưng tách rõ trách nhiệm:

- Router hoặc agent tạo `ProcessingResult`.
- Pipeline gọi `save_result(result)` để lưu DB.

Thiết kế này tốt vì:

- Agent tập trung vào suy luận.
- Pipeline chịu trách nhiệm side effects như lưu DB, metrics, và gửi alert.

Nếu muốn đẩy mạnh tính agentic hơn, có thể thêm tool kiểu `save_result_tool` để agent tự gọi ghi DB. Tuy nhiên cần cẩn thận vì:

- Dễ phát sinh ghi trùng nếu retry hoặc graph chạy lại.
- Khó test hơn.
- Khó audit hơn nếu agent vừa suy luận vừa trực tiếp gây side effect.

Thiết kế production an toàn hơn:

1. Agent trả về JSON có cấu trúc chặt.
2. Pipeline validate output bằng schema.
3. Pipeline mới thực hiện ghi DB.
4. Các hành động phụ như alert, queue review, feedback logging vẫn nên đi qua layer kiểm soát.

## 7. Kết luận

Project này là một hệ thống phát hiện spam email theo kiến trúc lai:

- classifier cục bộ để xử lý nhanh
- heuristic và security checks để tăng độ tin cậy
- LangGraph agent để xử lý các case khó
- Gemini để giải thích kết quả khi có cấu hình
- DB và Telegram để phục vụ vận hành

`VIRUSTOTAL_API_KEY` chỉ là thành phần hỗ trợ cho URL reputation, không phải “não” của agent và cũng không bắt buộc để hệ thống chạy.
