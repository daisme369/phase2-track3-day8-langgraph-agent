# Day 08 Lab Tasks: LangGraph Agentic Orchestration

Dựa trên cấu trúc source code hiện tại và hướng dẫn trong `README.md`, dưới đây là danh sách các công việc (tasks) cần hoàn thiện. Bạn có thể sử dụng file này để theo dõi tiến độ công việc của mình.

## Phase 1: Core Graph (Cấu trúc đồ thị và logic xử lý)

### 1. `state.py` (Quản lý trạng thái)
- [ ] Quyết định và thiết lập đúng các trường (fields) nào là "append-only" (sử dụng `Annotated[list, add]`) và trường nào sẽ được ghi đè (overwrite).
- [ ] Đảm bảo trường `evaluation_result` được định nghĩa chính xác để sử dụng làm cờ (gate) cho vòng lặp thử lại (retry loop).

### 2. `nodes.py` (Các hàm xử lý tại mỗi Node)
- [ ] **`intake_node`**: Thêm logic chuẩn hóa dữ liệu, kiểm tra PII (thông tin định danh cá nhân) và trích xuất metadata từ query ban đầu.
- [ ] **`classify_node`**: Thay thế phương pháp dùng heuristics (dựa trên keyword cứng) bằng một chính sách định tuyến (routing policy) rõ ràng và mạnh mẽ hơn (VD: dùng LLM để phân loại).
- [ ] **`ask_clarification_node`**: Sinh ra câu hỏi làm rõ cụ thể dựa trên ngữ cảnh hiện tại của trạng thái (state).
- [ ] **`tool_node`**: Triển khai thực thi công cụ (tool) có tính idempotent (gọi nhiều lần không làm thay đổi kết quả sau lần gọi đầu) và trả về tool results có cấu trúc.
- [ ] **`risky_action_node`**: Xây dựng hành động đề xuất (proposed action) đi kèm với bằng chứng và lý do giải thích rủi ro.
- [ ] **`approval_node`**: Triển khai khả năng cho phép người duyệt từ chối (reject) hoặc chỉnh sửa (edit) quyết định; thêm cơ chế leo thang khi hết thời gian chờ (timeout escalation).
- [ ] **`retry_or_fallback_node`**: Xây dựng cơ chế retry có giới hạn (bounded retry), thông tin về exponential backoff (thời gian lùi tuyến tính/mũ) và luồng dự phòng (fallback route).
- [ ] **`answer_node`**: Dựa (grounding) câu trả lời cuối cùng vào kết quả của `tool_results` và trạng thái `approval`.
- [ ] **`evaluate_node`**: Thay thế logic heuristic hiện tại bằng LLM-as-judge hoặc một cấu trúc đánh giá chuẩn xác (structured validation).
- [ ] **`dead_letter_node`**: Triển khai logic lưu các lỗi không thể xử lý vào dead-letter queue, cảnh báo cho on-call, hoặc tạo support ticket.

### 3. `routing.py` (Các hàm định tuyến cho Conditional Edges)
- [ ] **`route_after_classify`**: Xử lý an toàn cho trường hợp route trả về bị lỗi hoặc không xác định (unknown routes) và thêm test cho các edge cases.
- [ ] **`route_after_evaluate`**: Cập nhật logic đánh giá xem `tool_node` đã chạy thành công chưa (done? check), dựa vào kết quả sau nâng cấp từ `evaluate_node`.
- [ ] **`route_after_retry`**: Triển khai cơ chế retry có giới hạn chặt chẽ và chuyển hướng sang `dead_letter` nếu vượt quá `max_attempts`.
- [ ] **`route_after_approval`**: Hỗ trợ định tuyến dựa trên nhiều kết quả ngoài approve/reject (như trường hợp reject, chỉnh sửa action).

### 4. `graph.py` (Kiến trúc Graph)
- [ ] Xem xét lại kiến trúc đồ thị. Hiện tại đã có bộ khung chuẩn:
  - `intake` -> `classify`
  - `classify` chia các nhánh: `simple`, `tool`, `missing_info`, `risky`, `error`
  - Retry loop: `tool` -> `evaluate` -> `retry` -> `tool` (bị ngắt nếu vượt quá retry và đi vào `dead_letter`)
  - Tất cả các luồng đều dẫn đến `finalize` -> `END`.
- [ ] Chỉ thực hiện thay đổi nodes/edges nếu có lý do kiến trúc thực sự cần thiết.

---

## Phase 2: Persistence (Khả năng lưu trữ và phục hồi)

### `persistence.py`
- [ ] Cập nhật Factory cho SQLite: sửa lỗi API với phiên bản `langgraph-checkpoint-sqlite` 3.x. Không sử dụng `SqliteSaver.from_conn_string()` (vì nó trả về context manager, không phải checkpointer), thay vào đó khởi tạo qua `SqliteSaver(conn=sqlite3.connect(...))`.
- [ ] (Tuỳ chọn/Mở rộng) Thêm tuỳ chọn kết nối Postgres.

---

## Phase 3: Metrics & Báo cáo

- [ ] Chạy `make run-scenarios` để đồ thị xử lý toàn bộ 7 kịch bản (và các kịch bản test thêm của bạn) -> Tạo ra file `outputs/metrics.json`.
- [ ] Chạy `make grade-local` để validate schema của metrics.
- [ ] Viết báo cáo vào `reports/lab_report.md`:
  - Giải thích kiến trúc đồ thị.
  - Phân tích bảng metrics (tỷ lệ thành công, các fail case).
  - Phân tích chi tiết ít nhất 1 failure mode (vì sao bị sai route hoặc treo) và cách cải thiện.

---

## Phase 4: Bonus Extensions (Các tính năng mở rộng - Lựa chọn ít nhất 1 để đạt 90+ điểm)

- [ ] **Parallel fan-out**: Sử dụng phương pháp `Send()` của LangGraph để thực thi 2 tool song song và merge kết quả ở reducer.
- [ ] **Real HITL**: Kích hoạt `LANGGRAPH_INTERRUPT=true` và sử dụng `interrupt()` thực sự thay vì mock decision trong `approval_node`.
- [ ] **Streamlit UI**: Build một UI với Streamlit có chức năng approve/reject/resume cho kịch bản có rủi ro.
- [ ] **Time travel**: Trình diễn việc dùng `get_state_history()` để lấy lại trạng thái tại checkpoint trước đó và chạy lại.
- [ ] **Crash recovery**: Chứng minh SQLite saver có thể sống sót sau khi bị kill tiến trình và tiếp tục chạy.
- [ ] **Graph diagram**: Xuất sơ đồ bằng cách gọi `graph.get_graph().draw_mermaid()`.
