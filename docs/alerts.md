# Template Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

## Alert mẫu để tham khảo

Ví dụ dưới đây minh họa mức độ cụ thể cần có. Học viên không cần copy nguyên, nhưng ba alert trong bài nộp nên rõ ràng tương tự: điều kiện là gì, kéo dài bao lâu, ảnh hưởng tới user ra sao và người trực cần kiểm tra gì trước.

- Tên: `HighLatencyP95`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: latency P95 của `response_sent.latency_ms`
- Điều kiện và thời gian duy trì: `p95(latency_ms) > 3000ms` trong 5 phút
- Ảnh hưởng tới người dùng: người dùng phải chờ lâu hơn trước khi nhận câu trả lời
- Ba bước kiểm tra đầu tiên:
  1. Mở dashboard latency để xác nhận P95/P99 và khoảng thời gian tăng.
  2. Lọc `data/logs.jsonl` trong khoảng đó, lấy một `correlation_id` có `latency_ms` cao.
  3. Mở trace cùng `correlation_id` trên Langfuse, so sánh các span chính để xác định bước nào bất thường.
- Mitigation tạm thời: dựa trên evidence thực tế để rollback prompt, khôi phục cấu hình liên quan, tắt practice scenario hoặc giảm tải khi demo.
- Owner: `student-<MSSV>`

## Alert 1

- Tên: `HighLatencyP95`; severity: `warning`; duration: `5m`; Slack: `#k4-l3b-alerts`; owner: `student-2A202602889`.
- SLI/SLO: P95 của `response_sent.latency_ms`; cảnh báo khi P95 > 3000 ms trong 5 phút. Người dùng chờ câu trả lời lâu hơn.
- Kiểm tra: (1) Xác định phút P95/P99 tăng trên panel Latency. (2) Lọc `response_sent` có latency cao trong `data/logs.jsonl`, lấy `correlation_id`. (3) Mở trace cùng ID và so thời lượng retrieval/generation.
- Mitigation: nếu generation tăng sau prompt release, rollback label `production`; nếu retrieval tăng, khôi phục dịch vụ retrieval/cấu hình liên quan. Xác nhận P95 trở lại dưới ngưỡng.

## Alert 2

- Tên: `HighErrorRate`; severity: `critical`; duration: `5m`; Slack: `#k4-l3b-alerts`; owner: `student-2A202602889`.
- SLI/SLO: tỷ lệ `request_failed / request_received`; cảnh báo khi > 2% trong 5 phút. Người dùng không nhận được câu trả lời.
- Kiểm tra: (1) Xem panel Errors để xác nhận tỷ lệ và loại lỗi. (2) Lọc `request_failed` trong cùng khoảng, lấy `error_type` và `correlation_id`. (3) Mở trace cùng ID để tìm span lỗi.
- Mitigation: rollback thay đổi gần nhất liên quan span lỗi; kiểm tra dependency trước khi khôi phục traffic. Xác nhận error rate giảm.

## Alert 3

- Tên: `LowRetrievalSuccess`; severity: `warning`; duration: `5m`; Slack: `#k4-l3b-alerts`; owner: `student-2A202602889`.
- SLI/SLO: tỷ lệ `tool_success == true` trên các request có `tool_success` được ghi; cảnh báo khi < 90% trong 5 phút. Câu trả lời thiếu context hoặc lỗi.
- Kiểm tra: (1) Xem retrieval success và error breakdown trong panel Errors. (2) Lọc log `tool_name=retrieval`, `tool_success=false`; lấy `correlation_id`. (3) Mở retrieval span cùng ID để xác định timeout/lỗi.
- Mitigation: khôi phục vector store hoặc cấu hình retrieval; tạm giảm tải nếu dependency quá tải. Xác nhận tỷ lệ thành công trở lại ít nhất 90%.
