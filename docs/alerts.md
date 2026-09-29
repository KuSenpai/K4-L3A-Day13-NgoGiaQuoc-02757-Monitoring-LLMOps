# Alert và Runbook

Mỗi alert dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ. Rule máy đọc nằm trong [`../config/alert_rules.yaml`](../config/alert_rules.yaml); SLO trong [`../config/slo.yaml`](../config/slo.yaml). Nguồn dữ liệu: `data/logs.jsonl` (dashboard) và project Langfuse cá nhân (trace).

Quy trình chung cho mọi alert: **Metrics → Logs → Traces** — xác định khoảng thời gian trên dashboard, lọc log lấy `correlation_id`, mở trace có cùng `correlation_id` và so sánh các span.

## Alert 1

- Tên: `HighLatencyP95`
- Severity: P2-warning
- Duration: 5m
- Kênh thông báo: Slack `#day13-l3a-oncall`
- SLI/SLO liên quan: `fast_successful_requests` — 99.5% request thành công với `latency_ms <= 3000` trong 28 ngày. Alert bắn ở 2000 ms để cảnh báo trước khi chạm SLO line 3000 ms.
- Điều kiện và thời gian duy trì: P95 `response_sent.latency_ms` trong cửa sổ 5 phút > 2000 ms, kéo dài liên tục 5 phút.
- Ảnh hưởng tới người dùng: câu trả lời chậm rõ rệt, người dùng chờ lâu hoặc bỏ đi; nếu tiếp tục tăng sẽ tiêu error budget.
- Ba bước kiểm tra đầu tiên:
  1. Dashboard panel Latency: P95/P99 tăng từ lúc nào, TTFT P95 có tăng theo không (TTFT không đổi → chậm nằm ngoài LLM).
  2. Lọc log: `event == "response_sent" and latency_ms > 2000` trong khoảng đó, lấy vài `correlation_id`, xem có tập trung ở một `feature`/`model` không.
  3. Mở trace có cùng `correlation_id` trên Langfuse, so sánh thời lượng `rag-retrieve` và `llm-generate` với trace bình thường.
- Mitigation tạm thời: nếu span retrieval chậm → giảm top-k/bật cache kết quả retrieval, chuyển sang index dự phòng; nếu generation chậm → giảm `max_tokens` hoặc chuyển model nhanh hơn; rollback deploy/prompt gần nhất nếu trùng thời điểm.
- Owner: ngo-gia-quoc (on-call AI platform)

## Alert 2

- Tên: `HighErrorRateOrRetrievalFailure`
- Severity: P1-critical
- Duration: 5m
- Kênh thông báo: Slack `#day13-l3a-incidents`
- SLI/SLO liên quan: `fast_successful_requests` (request lỗi là bad event) và guardrail `error_rate_pct_max = 2`, `retrieval_success_rate_pct_min = 90`.
- Điều kiện và thời gian duy trì: `request_failed / request_received * 100 > 2` HOẶC tỷ lệ `tool_success == true` < 90% trong cửa sổ 5 phút, kéo dài 5 phút.
- Ảnh hưởng tới người dùng: người dùng nhận HTTP 500 hoặc câu trả lời không có ngữ cảnh; error budget 28 ngày có thể cạn trong vài giờ.
- Ba bước kiểm tra đầu tiên:
  1. Dashboard panel Errors: error rate, breakdown theo `error_type` và retrieval success bắt đầu xấu từ lúc nào.
  2. Lọc log `event == "request_failed"`: đọc `error_type`, `tool_name`, `payload.detail` và lấy `correlation_id`.
  3. Mở trace cùng `correlation_id`: observation nào có level `ERROR` (thường là `rag-retrieve`), lỗi xảy ra trước hay sau khi gọi LLM.
- Mitigation tạm thời: nếu vector store timeout → bật fallback trả lời không có retrieval hoặc dùng cache, tăng timeout/retry có giới hạn; tạm tắt feature bị ảnh hưởng; rollback thay đổi gần nhất.
- Owner: ngo-gia-quoc (on-call AI platform)

## Alert 3

- Tên: `CostBurnSpike`
- Severity: P2-warning
- Duration: 15m
- Kênh thông báo: Slack `#day13-l3a-oncall`
- SLI/SLO liên quan: guardrail `daily_cost_usd_max = 2.5`; 0.21 USD/giờ ≈ gấp đôi tốc độ chi tiêu cho phép (2.5 / 24 ≈ 0.104 USD/giờ).
- Điều kiện và thời gian duy trì: tổng `cost_usd` trong 1 giờ > 0.21 USD HOẶC `tokens_out` trung bình 15 phút > 2 lần trung bình 24 giờ trước, kéo dài 15 phút.
- Ảnh hưởng tới người dùng: chưa lỗi ngay, nhưng vượt ngân sách buộc phải rate-limit/tắt tính năng; câu trả lời dài bất thường có thể giảm chất lượng.
- Ba bước kiểm tra đầu tiên:
  1. Dashboard panel Cost và Tokens: cost tăng do traffic (panel Traffic cũng tăng) hay do token/request tăng (`tokens_out` tăng, traffic không đổi).
  2. Lọc log `response_sent` có `tokens_out` cao, lấy `correlation_id`, kiểm tra `feature`, `model`.
  3. Mở trace cùng `correlation_id`: xem usage/cost của `llm-generate`, `prompt_name`/`prompt_version` — có vừa promote prompt mới hoặc đổi model không.
- Mitigation tạm thời: rollback label `production` về prompt version trước; đặt `max_tokens`; chuyển request ít quan trọng sang model rẻ hơn; bật rate-limit theo user/feature.
- Owner: ngo-gia-quoc (on-call AI platform + FinOps)
