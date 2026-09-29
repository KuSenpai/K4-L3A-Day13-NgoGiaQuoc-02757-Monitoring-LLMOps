# Báo cáo cá nhân — K4-L3A Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Ngô Gia Quốc
- **MSSV:** 02757
- **Lớp:** K4-L3A
- **Repository URL:** https://github.com/KuSenpai/K4-L3A-Day13-NgoGiaQuoc-02757-Monitoring-LLMOps
- **Commit SHA cuối:** [`adf29aefc3e7ef7be1ecf89b7185b9aa202edca9`](https://github.com/KuSenpai/K4-L3A-Day13-NgoGiaQuoc-02757-Monitoring-LLMOps/commit/adf29aefc3e7ef7be1ecf89b7185b9aa202edca9) (commit chứa toàn bộ source, config và evidence; commit sau đó chỉ cập nhật dòng SHA này trong report)
- **Challenge ID:** `day13-k4-l3a-monitoring-llmops-v1`
- **Tên project Langfuse cá nhân:** `day13-k4-l3a-02757` (Langfuse Cloud, region US)

## 2. Evidence index

| Evidence | Đường dẫn |
|---|---|
| Baseline (trước khi sửa) | [evidence/baseline/](evidence/baseline/) |
| Pytest cuối | [evidence/01-pytest.png](evidence/01-pytest.png) |
| Log validator | [evidence/02-log-validator.png](evidence/02-log-validator.png) |
| Dashboard validator | [evidence/03-dashboard-validator.png](evidence/03-dashboard-validator.png) |
| Structured log | [evidence/04-structured-log.png](evidence/04-structured-log.png) |
| PII redaction | [evidence/05-pii-redaction.png](evidence/05-pii-redaction.png) |
| Trace list | [evidence/06-trace-list.png](evidence/06-trace-list.png) |
| Trace waterfall | [evidence/07-trace-waterfall.png](evidence/07-trace-waterfall.png) |
| Trace metadata | [evidence/08-trace-metadata.png](evidence/08-trace-metadata.png) |
| Prompt versions | [evidence/09-prompt-versions.png](evidence/09-prompt-versions.png) |
| Prompt rollback | [evidence/10a-prompt-promoted.png](evidence/10a-prompt-promoted.png) (production → v2), [evidence/10b-prompt-rollback.png](evidence/10b-prompt-rollback.png) (production → v1) |
| Dashboard runtime | [evidence/11-dashboard-overview.png](evidence/11-dashboard-overview.png) |
| Dashboard runtime (practice `rag_slow` + `tool_fail`) | [evidence/11b-dashboard-practice-rag-slow-tool-fail.png](evidence/11b-dashboard-practice-rag-slow-tool-fail.png) |
| Incident metric | [evidence/12-incident-metric.png](evidence/12-incident-metric.png), sau khi fix: [evidence/12b-incident-recovered.png](evidence/12b-incident-recovered.png) |
| Incident log | [evidence/13-incident-log.png](evidence/13-incident-log.png) |
| Incident trace | [evidence/14-incident-trace.png](evidence/14-incident-trace.png) |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 (20/22 record thiếu `correlation_id`, thiếu enrichment) | 100/100 (124 record, 61 correlation ID) | Sau khi đổi tên log baseline và restart API |
| `validate_dashboard.py` | 6/6 (contract có sẵn) | 6/6 | Dashboard runtime dựng bằng `scripts/build_dashboard.py` |
| `pytest` | 22 passed | 30 passed | Thêm test PII (CCCD, thẻ, passport, scrub lồng nhau) và correlation ID |
| Số traces hợp lệ | 10 trace chỉ có root observation | 36 trace có root + retrieval + generation (67 trace trong 60 phút) | Xem `06-trace-list.png` |
| Số PII leak | 0 (preview đã qua `summarize_text`) | 0 trong log và trace | Processor scrub mọi field string trước khi render |
| Latency P95 / TTFT P95 | P50 852 ms, P95 1144 ms / 50 ms | P50 152 ms, P95 1223 ms / 50 ms | P95 cuối bao gồm request cold-cache prompt; steady-state ~160 ms |
| Retrieval success rate | 100% | 100% (82% khi practice `tool_fail`) | |

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** [`app/middleware.py`](../app/middleware.py) gọi `clear_contextvars()` đầu mỗi request để không rò context, nhận `x-request-id` nếu đúng format `req-<8-hex>`, ngược lại sinh `req-{uuid4().hex[:8]}`. ID được `bind_contextvars`, gán vào `request.state`, truyền vào `LabAgent.run` (ghi vào trace metadata) và trả lại qua header `x-request-id` cùng `x-response-time-ms`.
- **Các metadata được ghi vào structured log:** [`app/main.py`](../app/main.py) bind `user_id_hash` (SHA-256 cắt 12 ký tự, không log user_id thô), `session_id`, `feature`, `model`, `env` trước `request_received`, nên mọi log sau trong request dùng chung context. `response_sent` có `latency_ms`, `ttft_ms`, `tokens_in/out`, `cost_usd`, `quality_score`, `tool_name`, `tool_success`.
- **Cách bảo đảm PII được scrub trước khi ghi:** [`app/logging_config.py`](../app/logging_config.py) đăng ký `scrub_event` sau `TimeStamper` và **trước** `JsonlFileProcessor`/`JSONRenderer`. Processor duyệt đệ quy mọi giá trị string (kể cả dict/list lồng trong `payload`), chỉ bỏ qua các field hệ thống (`ts`, `level`, `correlation_id`, `user_id_hash`) để tránh redact nhầm hash toàn chữ số. [`app/pii.py`](../app/pii.py) có pattern cho thẻ, CCCD, email, điện thoại VN và passport VN; thẻ/CCCD chạy trước phone để không bị cắt nửa chừng.
- **Cách kiểm chứng kết quả:** unit test trong [`tests/test_pii.py`](../tests/test_pii.py) và [`tests/test_correlation_id.py`](../tests/test_correlation_id.py); gửi input có PII giả (thẻ, CCCD, phone, email, passport) và đối chiếu log đầu ra trong [`05-pii-redaction.png`](evidence/05-pii-redaction.png); validator quét độc lập toàn bộ `data/logs.jsonl` báo 0 leak.

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:** `.env` dùng key của project `day13-k4-l3a-02757`; trace chứa `correlation_id` trùng với dòng log trong `data/logs.jsonl` do tôi chạy `load_test.py`, và được truy vấn lại bằng `GET /api/public/v2/observations` với chính key đó ([`06-trace-list.png`](evidence/06-trace-list.png)).
- **Cấu trúc root/retrieval/generation observations:** [`app/agent.py`](../app/agent.py) — root `lab-agent-run` (type `agent`) chứa 2 child: `rag-retrieve` (type `retriever`, input là query preview đã scrub, output `doc_count`) và `llm-generate` (type `generation`, có `model`, `prompt` managed của Langfuse, `usage_details` input/output, `cost_details` input/output/total, `completion_start_time` theo TTFT). Không capture raw prompt/output: `capture_input/capture_output=False`, chỉ gửi preview đã scrub.
- **Cách nối trace với log:** `correlation_id` nằm trong trace metadata (propagate xuống mọi observation) và trong mọi log line. Ví dụ `req-136522d4` ↔ trace `8b7cc2347920af0e32d226dcd7cebeb2` ([`08-trace-metadata.png`](evidence/08-trace-metadata.png), [`04-structured-log.png`](evidence/04-structured-log.png)).
- **Prompt name:** `day13-chat` (text prompt, giữ 3 biến `feature`, `docs`, `message`)
- **Version/label baseline:** v1 — labels `baseline`, `production`
- **Version/label candidate:** v2 — label `candidate` (thêm yêu cầu trả lời tối đa 3 bullet ngắn; `tokens_in` 32 → 49 với cùng input)
- **Trace ID của mỗi version:** cùng input "Explain why metrics traces and logs work together":

  | Bước | correlation_id | label → version | Trace ID |
  |---|---|---|---|
  | baseline | `req-ba5e0001` | baseline → v1 | `be7b60a79d0651e7c5e6626b99480256` |
  | candidate | `req-cafe0002` | candidate → v2 | `831e0d24e2bf5deeb0973853468246c4` |
  | sau promote | `req-a0a0b002` | production → v2 | `f7df4216c6484de855fc57418e146cd5` |
  | sau rollback | `req-a0a0b001` | production → v1 | `7503fbc073f415d4880822822113b62f` |

- **Cách promote và rollback `production`:** [`scripts/manage_prompt.py`](../scripts/manage_prompt.py) gọi `update_prompt(name, version, new_labels)`: `promote 2` gắn `production` cho v2 (Langfuse tự gỡ khỏi v1), `rollback 1` gắn lại cho v1. Restart API sau mỗi lần đổi để bỏ cache prompt 60 s. Trạng thái label trước/sau: [`10a-prompt-promoted.png`](evidence/10a-prompt-promoted.png), [`10b-prompt-rollback.png`](evidence/10b-prompt-rollback.png).

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:** [`scripts/build_dashboard.py`](../scripts/build_dashboard.py) đọc `data/logs.jsonl` và thresholds từ [`config/dashboard.yaml`](../config/dashboard.yaml), sinh HTML tự refresh 30 s, time range 60 phút, 6 panel: Latency P50/P95/P99 + TTFT P95 (ms), Traffic (requests/phút), Error rate + breakdown + retrieval success (%), Cost theo phút + tổng (USD), Tokens in/out, Quality mean; mỗi panel có đơn vị và threshold line. `--png` chụp ảnh bằng Edge/Chrome headless. Kiểm tra runtime: bật `rag_slow` làm P95 tăng từ ~160 ms lên 2652 ms; bật `tool_fail` làm error rate lên 18% và retrieval success xuống 82% ([`11b`](evidence/11b-dashboard-practice-rag-slow-tool-fail.png)).
- **SLO và lý do chọn:** [`config/slo.yaml`](../config/slo.yaml) — 99.5% request trong 28 ngày phải thành công với `latency_ms <= 3000`. Ngưỡng 3000 ms khớp threshold dashboard và cao hơn 2 lần P95 xấu nhất ở baseline (~1.2 s khi cache prompt nguội); 99.5% thay vì 99.9% vì LLM/vector store là dependency ngoài có độ trễ dao động.
- **Cách tính error budget:** budget = 100% − 99.5% = 0.5%. Theo thời gian: 0.005 × 28 × 24 × 60 = 201.6 phút/28 ngày. Theo request: với 10.000 request/28 ngày, cho phép tối đa 50 request lỗi hoặc > 3000 ms. Burn rate 14.4 trong 1 giờ đốt ~2% budget, dùng làm ngưỡng fast-burn.
- **Ba alert và runbook tương ứng:** [`config/alert_rules.yaml`](../config/alert_rules.yaml), [`docs/alerts.md`](../docs/alerts.md)
  1. `HighLatencyP95` (P2, 5m, `#day13-l3a-oncall`): P95 > 2000 ms — cảnh báo sớm trước SLO line 3000 ms.
  2. `HighErrorRateOrRetrievalFailure` (P1, 5m, `#day13-l3a-incidents`): error rate > 2% hoặc retrieval success < 90%.
  3. `CostBurnSpike` (P2, 15m, `#day13-l3a-oncall`): cost 1 giờ > 0.21 USD (≈ 2× tốc độ cho phép của budget 2.5 USD/ngày) hoặc `tokens_out` trung bình tăng gấp đôi.

## 7. Điều tra challenge

- **Challenge ID:** `day13-k4-l3a-monitoring-llmops-v1` (cohort K4, seed 1311, `affected_feature=monitoring`, `latency_threshold_ms=2000`). File do Lab Coach gửi được lưu nguyên vẹn tại `config/challenge.json` (gitignored, không commit). Timeline (UTC): inject 08:21:55, load challenge 08:21:56–08:22:10, disable 08:23:10, chạy lại để xác minh 08:23:11.
- **Khoảng thời gian điều tra:** 2026-09-29 08:21:55 → 08:23:10 UTC (inject 08:21:55, load challenge 08:21:56–08:22:10, fix 08:23:10). Nền so sánh: tải bình thường lúc 08:20:48.
- **Triệu chứng từ metrics:** ([`12-incident-metric.png`](evidence/12-incident-metric.png)) feature `monitoring` có latency P95 **2653 ms** (phút 08:22) so với **152 ms** lúc 08:20, tức gấp ~17 lần; vượt `latency_threshold_ms` 2000 và kích hoạt điều kiện alert `HighLatencyP95`. Các tín hiệu còn lại bình thường: TTFT P95 vẫn 50 ms, `tokens_out` trung bình 118–165 (nền 114–124), cost bình thường, 0 `request_failed`, retrieval `tool_success=true`. Suy ra độ chậm không nằm ở LLM, không phải lỗi, không phải cost/prompt, mà ở bước trước khi LLM bắt đầu sinh token.
- **Log line và correlation ID liên quan:** ([`13-incident-log.png`](evidence/13-incident-log.png)) lọc `event == "response_sent" and latency_ms > 2000` trong cửa sổ: cả 5/5 request của challenge (`feature=monitoring`) đều ~2652 ms. Chọn `req-3ba38462`:
  `{"event": "response_sent", "correlation_id": "req-3ba38462", "feature": "monitoring", "latency_ms": 2652, "ttft_ms": 50, "tokens_out": 165, "tool_name": "retrieval", "tool_success": true, "ts": "2026-09-29T08:21:59.397940Z"}`
- **Trace ID và span gây ảnh hưởng:** ([`14-incident-trace.png`](evidence/14-incident-trace.png)) trace `4e28d547ca42a6beaa90b1aa5a0ec24b` có cùng `correlation_id=req-3ba38462`: root `lab-agent-run` 2654 ms, trong đó **`rag-retrieve` (retriever) 2503 ms = 94.3%** và `llm-generate` 151 ms. Trace bình thường `2bf21eda20ad21a25bf3a46f02eff403` (`req-4437f9dd`): `rag-retrieve` 0 ms, `llm-generate` 154 ms. Cùng prompt `day13-chat` v1/production, nên loại trừ nguyên nhân do đổi prompt.
- **Root cause:** bước retrieval (vector store / RAG) bị chậm thêm ~2.5 s mỗi lần gọi (scenario `rag_slow`), làm latency end-to-end của feature `monitoring` vượt ngưỡng. Metric (P95 tăng, TTFT không đổi), log (5/5 request `monitoring` ~2652 ms, không lỗi) và trace (span `rag-retrieve` chiếm 94%) cùng chỉ về một nguyên nhân. Hiệu ứng phụ: endpoint `async def chat` chạy agent đồng bộ nên chặn event loop, các request đồng thời bị xử lý tuần tự; vì vậy client đo 10.6–13.3 s dù mỗi request chỉ tốn ~2.65 s trên server (các response trong log cách nhau đúng ~2.65 s).
- **Fix action:** khôi phục retrieval backend (trong lab: `python scripts/inject_incident.py --disable` lúc 08:23:10). Xác minh bằng cách chạy lại đúng bộ query của challenge: cả 5 request `monitoring` còn 151–152 ms phía server ([`12b-incident-recovered.png`](evidence/12b-incident-recovered.png)).
- **Preventive measure:**
  1. Đặt timeout cho retrieval (ví dụ 500 ms) kèm fallback (cache kết quả retrieval theo query hoặc trả lời không có context và đánh dấu `tool_success=false`), để vector store chậm không kéo cả request vượt SLO.
  2. Thêm SLI/alert riêng cho thời lượng span retrieval (ví dụ P95 `rag-retrieve` > 500 ms trong 5 phút) bên cạnh `HighLatencyP95`, để cảnh báo trỏ thẳng vào thành phần.
  3. Chuyển endpoint `chat` sang `def` (chạy trong threadpool) hoặc dùng client async cho retrieval/LLM, và đo latency ở middleware (đã có `x-response-time-ms`) để metric phản ánh cả thời gian xếp hàng mà người dùng thực sự chờ.

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:** tạo child observation bằng `@observe` trên hai helper `_retrieve`/`_generate` và gọi client qua module `tracing`, thay vì `start_as_current_observation` trên client của agent. Cách này giữ đúng quan hệ cha-con qua OpenTelemetry context, tự đánh dấu observation `ERROR` khi retrieval ném exception, và không phá contract của test sẵn có (test thay client của agent bằng client giả chỉ có `update_current_span`). Trên generation chỉ gửi preview đã scrub để trace không chứa PII.
- **Một lỗi/blocker đã gặp:** trace vẫn lên Langfuse nhưng prompt luôn `local-fallback`, mỗi request chậm thêm ~700 ms (baseline P50 852 ms).
- **Cách tìm nguyên nhân và xử lý:** log uvicorn báo `SSL: CERTIFICATE_VERIFY_FAILED` khi fetch prompt; biến `SSLKEYLOGFILE=\\.\aswMonFltProxy\...` cho thấy Avast đang quét HTTPS và chèn root CA riêng. `curl` (dùng Windows cert store) chạy được nhưng Python dùng bundle `certifi` nên không tin CA đó. Không tắt verify SSL; thay vào đó tạo bundle = certifi + Windows ROOT store và trỏ `SSL_CERT_FILE` trong `.env` (ghi chú trong `.env.example`). Sau khi sửa, prompt lấy từ Langfuse (`prompt_source=langfuse`) và P50 giảm còn 152 ms. Ngoài ra, API trace v1 (`GET /api/public/traces`) trả 410 cho organization mới nên tôi dùng `GET /api/public/v2/observations` để kiểm tra trace.
- **Cách hiểu luồng Metrics → Logs → Traces:** metrics (dashboard) cho biết *có vấn đề gì và khi nào* — ví dụ P95 vượt 2000 ms trong một phút cụ thể. Logs cho biết *request nào* bị ảnh hưởng: lọc `response_sent` có `latency_ms` cao hoặc `request_failed` trong khoảng đó để lấy `correlation_id`, `feature`, `error_type`. Trace có cùng `correlation_id` cho biết *bước nào* gây ra: so sánh thời lượng/level của `rag-retrieve` và `llm-generate`. Chỉ kết luận root cause khi cả ba lớp cùng chỉ về một nguyên nhân.
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:** prompt là "code" của ứng dụng LLM nhưng thay đổi được mà không cần deploy, nên mỗi trace phải ghi prompt name/version/label để biết một thay đổi hành vi, token hay cost đến từ version nào. Token/cost là tín hiệu sớm: v2 tăng `tokens_in` từ 32 lên 49 (~50%) với cùng input — nhân với traffic thật là tăng chi phí đáng kể. SLO/error budget quyết định khi nào được phép thử prompt/model mới và khi nào phải dừng; label `production` giúp rollback trong vài giây mà không cần deploy lại.
- **Điều quan trọng nhất đã học:** phải đo được cả khi dependency hỏng: fallback prompt che mất lỗi SSL, chỉ phát hiện nhờ metadata `prompt_source` và latency tăng.
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:** endpoint `async def chat` gọi agent đồng bộ nên chặn event loop: khi practice `rag_slow` với concurrency 5, `latency_ms` phía server ~2.65 s nhưng client đo ~13.3 s vì request phải xếp hàng. Metric hiện tại không thấy thời gian chờ này; hướng sửa là chuyển endpoint sang `def` (chạy trong threadpool) hoặc đo latency ở middleware. Dashboard là HTML sinh từ log, chưa phải hệ thống giám sát liên tục; alert rules là đặc tả, chưa gắn vào Alertmanager/Slack thật.

## 9. Checklist trước khi nộp

- [x] Kết quả và evidence thuộc commit SHA cuối.
- [x] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [x] Incident evidence nối đúng metric → log → trace.
- [x] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [x] Repository chạy lại được theo README.
- [x] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [ ] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
