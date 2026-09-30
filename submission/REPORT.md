# Báo cáo cá nhân — K4-L3B Day13 Monitoring & LLMOps

## 1. Thông tin
- Họ tên: Nguyễn Thành Vinh; MSSV: **2A202602889**; lớp: **K4-L3B**.
- Repository: https://github.com/v1rtuos024/K4-L3B-Day13-NguyenThanhVinh-2A202602889-Monitoring-LLMOps
- Commit SHA cuối: **chưa tạo**.
- Challenge ID: **day13-k4-l3b-monitoring-llmops-v1**. File chính thức được Gitignore.
- Langfuse project: **day13-k4-l3b-2A202602889**.

## 2. Evidence index

| # | Evidence hiện có | Trạng thái |
|---|---|---|
| 01 | [24/24 test](evidence/01-pytest.png) | .png |
| 02 | [Log score 100/100](evidence/02-log-validator.png) | .png |
| 03 | [Dashboard 6/6](evidence/03-dashboard-validator..png) | .png |
| 04 | [Structured log](evidence/04-structured-log.json) | File .json |
| 05 | [PII redaction](evidence/05-pii-redaction.txt) | Text from terminal |
| 06 | [Ảnh 10 trace](evidence/06-trace-list.png)| File .png |
| 07 | [Waterfall](evidence/07-trace-waterfall.png) | File .png |
| 08 | [Metadata](evidence/08a-trace-metadata.png), [generation](evidence/08b-generation-details.png), [API](evidence/08-current-trace.json) | File .png, .json |
| 09 | [v1](evidence/09a-prompt-v1.png), [v2](evidence/09b-prompt-v2.png), [API](evidence/09-prompt-versions.txt) | 2 labels |
| 10 | [ảnh rollback](evidence/10a-production-rolled-back.png) | File .png |
| 11 | [Ảnh dashboard](evidence/11-dashboard-overview.png) | File .png đủ header/range/6panel |
| 12 | [Metrics](evidence/12-incident-metric.json), [Ảnh](evidence/12-incident-dashboard.png) | File .json, .png |
| 13 | [Log](evidence/13-incident-log.txt) | Text from terminal |
| 14 | [Trace](evidence/14-incident-trace.png) | Ảnh trace span |

## 3. Baseline và kết quả cuối

| Kiểm tra | Baseline | Kết quả cuối |
|---|---|---|
| Log validator | [Starter 30/100](evidence/00-baseline-log-validator.txt) | 100/100, 52 records, 0 thiếu schema/context,0 PII leak |
| Dashboard | Contract starter | 6/6 |
| Tests | Không lưu trước sửa | 24 passed |
| Traces | CP2 xác minh 14 | CP3 xác minh 10 baseline mới + trace04/incident/recovery, đúng parent/I/O trống |

Latency dưới đây lấy **latency_ms trong log**, không lấy thời gian client khi concurrency = 5.

| Metric | Baseline10requests | Incident5requests | Recovery5requests |
|---|---:|---:|---:|
| P50 ms | 281 | 2781 | 546 |
| P95/P99 ms | 828/828 | 2836/2836 | 949/949 |
| TTFT P95 ms | 50 | 50 | 50 |
| Error/retrieval success | 0%/100% | 0%/100% | 0%/100% |
| Cost USD | 0.019239 | 0.009795 | 0.010515 |
| Input/output tokens | 338/1215 | 175/618 | 175/666 |
| Quality proxy | 0.88 | 0.84 | 0.84 |

Recovery P95 giảm 66.5%, 5/5 dưới2000ms. Recovery chưa bằng baseline do workload/prompt fetch/network; không khẳng định bằng nhau. Đây là fake LLM/workload nhỏ, không đại diện production.

## 4. Logging và PII

Middleware clear context mỗi request, nhận req-8hex hoặc sinh ID, bind correlation_id và trả x-request-id/x-response-time-ms. Chat bind user/session hash, feature/model/env trước request_received. response_sent có latency/TTFT/token/cost/quality/tool_success/trace_id.

Scrub đệ quy trước JSONL và renderer; preview che email/phoneVN/CCCD/card/passport. Request preview đủ dài giữ cả 4 markers. Evidence 05 chứa REDACTED_EMAIL, REDACTED_PHONE_VN, REDACTED_CCCD, REDACTED_CREDIT_CARD. Không log raw message.

## 5. Tracing và prompt

Root lab-agent-run(AGENT) là cha retrieval(RETRIEVER) và generation(GENERATION). **Input/Output trống**; preview đã scrub ở metadata. Root metadata có correlation_id và prompt name/label/version/source. Generation có model/token/cost và managed prompt thật. 10 baseline trace mới và 04 được đọc lại API để xác minh.

Prompt day13-chat giữ feature/docs/message; local fallback được đánh dấu rõ. Cache TTL0 dùng trong lab để đổi label ngay.

| CP2 | Version/label | Trace ID |
|---|---|---|
| Baseline | v1/baseline | 6e3efc0770723f88fba2bf85262604fd |
| Candidate cùng input | v2/candidate | d9ac1e500b7e4bcb8e748b0c80d6a7dd |
| Promote | v2/production | f53b6f971b84b128af8f513610262b2d |
| Rollback | v1/production | 4c4fed57e5d45daf084d7798fff76650 |

## 6. Dashboard/SLO/error budget/alerts

[Dashboard](../scripts/dashboard.py) đọc JSONL thật, 6 panel: latency P50/P95/P99/TTFT; traffic; error breakdown/retrieval success; cost; tokens; quality. Có units/thresholds,60 min,refresh 30s. Timeline latency/TTFT theo UTC phân màu baseline/incident/recovery. /cp3?phase=incident cố định cửa sổ lịch sử incident; /cp3 gồm recovery. Không dựng dữ liệu.

[SLO](../config/slo.yaml):99.5% successful latency≤3000ms trong 28 ngày. Budget 0.5%=50 bad/10.000 request. CP3 20/20 successful≤3000ms,observed 100%,0 bad; không đủ dữ liệu đánh giá 28 ngày. Challenge threshold 2000ms khác SLO 3000ms: incident bất thường nhưng chưa vi phạm SLO.

[Alerts](../config/alert_rules.yaml):P95>3000ms/5m, error>2%/5m, retrieval success<90%/5m; ownerstudent-2A202602889, Slack#k4-l3b-alerts, [runbook](../docs/alerts.md). Chưa có service gửi Slack; incident ngắn/dưới 3000ms không chứng minh alert đã fire.

## 7. Điều tra challenge — Metrics → Logs → Traces

Chuẩn bị: chuyển log cũ ra thư mục tạm ngoài repo, health tất cả `false`, API uvicorn không `--reload`. Chạy `load_test` baseline rồi default `inject_incident` và `load_test --challenge --concurrency 5`. File đề không sửa. [Manifest](evidence/cp3-run.json).

1. **Metrics:** baseline 30/09/2026 **04:12:50 – 04:12:54 UTC**; incident **04:12:54 – 04:13:09 UTC** (= 11:12:54 – 11:13:09 VN). P95 **828 → 2836 ms** (tăng 3.43 lần); P50 281 → 2781 ms. 5/5 request vượt 2000 ms. TTFT 50 ms / errors 0 / retrieval 100 ổn định.
2. **Logs:** lọc `response_sent > 2000ms` trong cửa sổ đó, chọn slowest. ID **req-5c7c1266**, ts **2026-09-30T04:13:00.917692Z** (= 11:13:00.917692 VN), latency_ms **2836**, `tool_success=true`, trace **106939ffb1db3460d70f968be5fef36d**. Evidence 13 là log thật bỏ payload query riêng.
3. **Traces:** đúng trace log: root **2837 ms**, retrieval **2501 ms**, generation **151 ms**, status `DEFAULT`. Baseline median `req-d0c49dc6`, trace **f4a1b1ebafb2d5ac927f7cf63c25ab11**: root 282 / retrieval 2 / generation 152 ms. Retrieval chiếm 88.2% root; generation ổn định. Root/log chênh 1 ms do ranh giới đo/làm tròn; metadata `correlation_id` khớp.
4. **Root cause:** retrieval delay mô phỏng ~2.5 giây từ `rag_slow` trong [mock_rag](/app/mock_rag.py). Ba bằng chứng chỉ cùng bước retrieval; không quy lỗi LLM hay database thật.
5. **Fix:** disable incident chính thức, health cả 3 `false`; chạy lại cùng challenge / concurrency 5. Recovery **04:17:38 – 04:17:42 UTC**, P95 **949 ms**, 5/5 dưới 2000 ms. Slowest recovery root 950 / retrieval **1** / generation 151 ms. [Action](evidence/cp3-recovery-action.txt), [recovery trace](evidence/cp3-recovery-trace.json).
6. **Prevent:** đề xuất retrieval budget / timeout 1000 ms và fallback kiểm soát, warning latency 2000 ms / retrieval duration theo feature / baseline. Giữ correlation để điều tra. Đây là đề xuất, chưa triển khai timeout / fallback trong mock.

## 8. Quyết định / blocker / bài học

* **Quyết định:** I/O trống, metadata preview scrub; export API dùng allowlist bỏ trường SDK nội bộ. Correlation vẫn nối metric → request → span.
* **Blocker:** venv launcher không dùng trong sandbox; dùng Python 3.12 + package path. Server venv chạy ngoài sandbox. Legacy trace API 410 được xử lý bằng Observations API v2. Chủ project đã đổi tên đúng MSSV. Dashboard thêm timeline vì số tổng hợp không thể chỉ rõ thời điểm.
* **Quan sát & Vận hành:** Prompt version giúp đối chiếu cùng input / rollback label; token / cost phát hiện tăng chi phí; SLO / budget định mức sai lệch. Metrics khoanh thời gian, logs khoanh request, traces khoanh bước trước khi kết luận.
* **Bài học:** Success 100% vẫn có latency incident; validator pass không bảo đảm privacy UI / ảnh đúng trace / alert gửi được.
* **Hạn chế:** Fake LLM / workload nhỏ, chưa đo 28 ngày, Slack chưa gửi; học viên còn cần chụp ảnh và commit / nộp LMS.

## 9. Checklist cuối

- [x] Code/logging/PII/tracing/prompt/dashboard/SLO/alerts/runbook và CP3 hoàn thành với evidence thật.
- [x] Tests 24/log 100/dashboard; challenge ignored;project đúng MSSV.
- [x] Incident metric/log/trace cùng request; disable/recovery đã kiểm chứng.
- [x] Commit cuối,chạy lại tests/validators kèm commit,cập nhật SHA,push/nộp URL+SHA.
