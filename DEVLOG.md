# NghiaType Development Log / Nhật ký phát triển

This log records the Kerning Studio milestones, release-level changes, and safety constraints. It is intended to accompany [README.md](README.md).

Tài liệu ghi lại những cột mốc phát triển Kerning Studio, thay đổi theo từng phiên bản và các nguyên tắc an toàn. Đọc cùng với [README.md](README.md) để có đầy đủ bối cảnh.

## 23 November 2026 — Glyph Studio 1.9.5 UI milestone / 23.11.2026

**Status: Glyph Studio UI/UX provisionally approved in FontLab 8; wider engine coverage still requires real-font validation.**  
**Trạng thái: Tạm chốt giao diện và workflow Glyph Studio trên FontLab 8; chưa xem toàn bộ khả năng của engine là đã kiểm chứng.**

### Completed today / Kết quả hôm nay

- Separated **Glyph Studio tab UI** (`NghiaType_GlyphStudio_Tab_V2.py`) from **Glyph Studio engine** (`NghiaType_GlyphStudio_Engine_V2.py`), with one main GUI entry point. Existing Kerning Studio logic was retained.  
  Tách **UI của tab Glyph Studio** khỏi **engine Glyph Studio**, giữ một GUI chính và không viết lại logic Kerning Studio đã hoạt động.
- Refined the visual system against an **interactive HTML reference** and screenshots from FontLab 8: compact mode tabs, balanced controls, native/system icons, cleaner family rows, aligned dropdowns and buttons, and consistent sizing with Kerning Studio.  
  Tinh chỉnh giao diện theo **HTML tương tác** và ảnh chụp FontLab 8: chuyển chế độ gọn, nút đồng đều, icon hệ thống, danh sách family rõ ràng, đồng bộ kích thước với Kerning Studio.
- Made **Scan → review/select → Apply** easier to understand: show a useful empty state before selection, distinguish pre-scan from completed results, show actionable targets, and report **All set** only when the scan finds no pending or review items.  
  Làm rõ luồng **Scan → xem/chọn → Apply**: hướng dẫn khi chưa chọn family, phân biệt trạng thái chưa quét với đã hoàn tất, tập trung vào target cần xử lý; chỉ báo **All set** khi đã quét và không còn mục cần tạo hoặc xem lại.
- Improved the display of already-matching recipes and the explanation of **REVIEW** results, including potential recipe aliases such as `dotbelow` / `dotbelowcomb`.  
  Cải thiện cách nhận diện và giải thích recipe đã khớp hoặc cần xem lại, gồm những tên mark có thể là alias như `dotbelow` / `dotbelowcomb`.
- Added or expanded code paths for **Base Diacritics**, language-group recipe proposals, mark-style choices (`.case`/standard), selectable targets, and multi-family planning. These are implementation milestones, not a claim of full FontLab runtime coverage.  
  Bổ sung/mở rộng mã cho **Base Diacritics**, nhóm ngôn ngữ, cách chọn mark (`.case`/standard), chọn target và multi-family; chưa xem đây là chứng nhận tương thích toàn bộ trên FontLab.
- Added an optional **Kerning visual layout companion** (`NghiaType_Kerning_Layout.py`) so the existing Kerning workflow can share the Glyph Studio visual language without rewriting its writer.  
  Thêm module **Kerning Layout** chỉ phụ trách trình bày để giao diện đồng bộ, không viết lại writer Kerning.

### Verification and boundaries / Kiểm chứng và giới hạn

- The user reviewed the evolving UI directly in **FontLab 8**, and accepted the compact mode tabs and overall visual direction.  
  Giao diện đã được xem và tinh chỉnh trực tiếp trong **FontLab 8**; đã tạm thống nhất bố cục và định hướng chung.
- Earlier **Glyph Studio Alpha 09** successfully created 22 E/E.001-related glyphs with readback PASS for 11/11 targets. This is earlier verified evidence, not a new end-to-end test of all features today.  
  Kết quả đã có từ **Alpha 09**: tạo 22 glyph liên quan nhóm E/E.001, readback PASS 11/11 target; không đồng nghĩa mọi chức năng mới đều đã kiểm chứng.
- FontLab runtime behavior for multi-master, all languages/aliases, mark placement, UI repaint after Apply, and every new engine branch remains to be confirmed where relevant.  
  Còn cần xác minh những trường hợp multi-master, các nhóm ngôn ngữ/alias, vị trí dấu, cập nhật Font Window và các nhánh engine mới khi sử dụng thực tế.
- No automatic Save/Compile. Preserve existing hand-drawn glyphs, avoid arbitrary Apply locks, and allow users to rescan after partial operations.  
  Không tự Save/Compile; tôn trọng glyph đã vẽ tay, tránh khóa Apply vô lý, cho phép quét lại để tiếp tục sau thao tác một phần.
- Keep stable modules and historical `.py` files unchanged for now; reorganize into `modules/<feature>/` only after the features stabilize.  
  Chưa dọn hoặc thay đổi các module/file cũ đã ổn định; chỉ tổ chức lại thành thư mục module khi các tính năng đã vững.

### Next / Việc tiếp theo

- Prioritize **OpenType Studio**: clear feature/class inspection, missing/extra glyph detection, ordering and references, then a practical editing workflow.  
  Ưu tiên **OpenType Studio**: đọc class/feature trực quan, tìm glyph thiếu/thừa, kiểm tra thứ tự và tham chiếu, sau đó mới mở rộng thao tác sửa.
- Later revisit existing modules for broader glyph/recipe support and **Specific-first Native Kerning** proposals. The Specific-first rules are ideas under review, **not implemented or released yet**.  
  Sau đó mở rộng hỗ trợ recipe/glyph và cân nhắc **Specific-first Native Kerning**; đây mới là đề xuất, **chưa phải chức năng đã triển khai**.
- When shipping a stable release, use a clear main entry point such as `NghiaType_1.9.5.py`; companion filenames remain as expected by imports.  
  Khi phát hành ổn định, dùng tên file GUI chính đơn giản như `NghiaType_1.9.5.py`; giữ đúng tên các module mà GUI import.

---

## 1.9.5 — 20 November 2026 / 20.11.2026

**Status: Kerning Studio workflow finalized.**  
**Trạng thái: Hoàn thiện quy trình làm việc của Kerning Studio.**

### Added and refined / Hoàn thiện giao diện

- Completed the three-step **Native classes → Cross-check → OpenType sync** workflow.  
  Hoàn thiện quy trình ba bước **Native classes → Cross-check → OpenType sync**.
- Simplified workspace lists: clear glyph names, compact `Left` / `Right` and `+N` capsules, and subtle row dividers.  
  Tinh giản danh sách: làm nổi bật tên glyph, gom nhãn `Left` / `Right` và số lượng `+N` vào capsule, thêm đường chia nhẹ giữa các hàng.
- Improved Cross-check hierarchy: **In sync** has a green background and white text, while **Differs** and review warnings use distinct colors.  
  Làm rõ mức độ ưu tiên trong Cross-check: **In sync** nền xanh chữ trắng; **Differs** và các cảnh báo dùng màu riêng, dễ nhận biết.
- Separated shared-class explanations into **dedicated warning cards**.  
  Đưa lý do class OpenType dùng chung vào **khung cảnh báo riêng**, tránh lẫn trong một đoạn mô tả dài.
- Locked selections use a system icon and disabled/muted controls. Locked table surfaces stay white rather than forming a square pink overlay.  
  Khi khóa lựa chọn, giao diện dùng icon hệ thống, vô hiệu hóa và làm mờ vùng chọn; nền bảng vẫn trắng, không tạo mảng hồng hình vuông.
- Removed redundant table headings, duplicate status messages, bottom notes, and the **NATIVE + OPENTYPE** chip.  
  Loại bỏ hàng tiêu đề thừa, thông báo trạng thái trùng lặp, ghi chú dưới thanh Close và chip **NATIVE + OPENTYPE**.
- Added the stable subtitle **“Keep your Native and OpenType kerning classes in sync.”**  
  Sử dụng câu giới thiệu cố định **“Keep your Native and OpenType kerning classes in sync.”**
- Retained contextual **Report / Details / FEA details** controls for technical information.  
  Giữ báo cáo kỹ thuật trong các nút **Report / Details / FEA details** đúng ngữ cảnh.

### OpenType confirmation and backup UX / Xác nhận và sao lưu

- **Changed the order:** explain the operation in a confirmation dialog **before** the Save As picker appears.  
  **Đổi thứ tự UX:** hiển thị hộp thoại giải thích và xác nhận **trước khi** mở cửa sổ chọn nơi lưu.
- The backup is explicitly a separate **OpenType `kern` `.fea` file**, not a font save operation.  
  Nói rõ đây là **file backup `.fea` của tính năng OpenType `kern`**, không phải lưu file font.
- Users choose a **new backup destination** after confirming; the guarded writer then handles the update.  
  Người dùng chọn **nơi lưu bản backup mới** sau khi xác nhận; sau đó bộ ghi dữ liệu có bảo vệ mới được phép tiếp tục.
- Canceling either confirmation or file selection stops the operation without adding glyphs.  
  Hủy ở một trong hai cửa sổ sẽ dừng thao tác và **không thêm glyph**.
- Kept acknowledgment, fresh preflight, exact readback, and manual font Save.  
  Giữ nguyên xác nhận bắt buộc, kiểm tra an toàn mới nhất, đọc lại kết quả chính xác và lưu font bằng tay.

### Reliability fixes carried into 1.9.5 / Các lỗi đã khắc phục

- Kept **Scan again** in the main guidance banner, preventing a duplicate floating button after a completed round.  
  Giữ **Scan again** trong khung hướng dẫn chính, không để nút quét bị trôi lên góc trên sau khi hoàn thành workflow.
- Preserved completed OpenType results until the user deliberately starts a new Native scan.  
  Giữ kết quả OpenType đã hoàn thành cho đến khi người dùng chủ động quét Native lại.
- Prevented verified readback rows from becoming editable selections.  
  Không cho các hàng kết quả đã xác minh quay lại trạng thái chỉnh sửa.
- Fixed secondary-dialog **Close** callbacks that received PythonQt's `clicked(False)` argument incorrectly.  
  Sửa lỗi nút **Close** do PythonQt truyền tham số `clicked(False)` không phù hợp với `accept()`.
- Removed the unused Qt `?` title-bar hint in report and confirmation dialogs.  
  Bỏ dấu `?` không có tác dụng cạnh nút đóng ở các hộp thoại.
- Fixed duplicated/overlapping status capsules by rendering one badge per result cell.  
  Sửa tình trạng capsule chồng chữ hoặc xuất hiện hai lần trong cùng ô kết quả.
- Avoided opacity effects that previously painted old table contents over another tab.  
  Bỏ hiệu ứng làm mờ gây lỗi nội dung bảng cũ bị vẽ đè lên tab khác.

### Safety boundaries retained / Nguyên tắc an toàn giữ nguyên

- **Native V2:** retains its scanner, planner, guarded writer, and live safety recheck before changes.  
  **Native V2:** giữ nguyên bộ quét, lập kế hoạch và bộ ghi an toàn; luôn kiểm tra lại dữ liệu đang mở trước khi thêm glyph.
- **Cross-check:** is read-only; comparing never grants write permission.  
  **Cross-check:** chỉ đọc; kết quả đối chiếu không tự cấp quyền ghi dữ liệu.
- **OpenType sync:** requires eligible selections, matching preflight, a new `.fea` backup path, FontLab 8 copy-only guarded writing, and readback.  
  **OpenType sync:** chỉ ghi khi lựa chọn hợp lệ, preflight khớp, có nơi lưu backup `.fea` mới, đúng bản COPY FontLab 8 và xác minh kết quả sau khi ghi.
- **No automatic Save or Compile.** Unverified or possibly partial writes produce **DO NOT SAVE**.  
  **Không tự Save hoặc Compile.** Nếu kết quả không xác minh được hoặc có nguy cơ ghi một phần, giao diện sẽ báo **DO NOT SAVE**.
- Shared and ambiguous classes cannot be force-synced automatically.  
  Class dùng chung hoặc không xác định rõ không được tự ép đồng bộ.

### Verification / Kiểm thử

- Nine offline regression suites passed in the development workspace, including selection locking, cancellation of both confirmation stages, Native re-scan, row and capsule rendering logic, round-completion state, and the backup-dialog sequence.
  
  Đã vượt qua chín bộ kiểm thử offline, bao gồm khóa lựa chọn, hủy ở cả hai bước xác nhận, quét lại Native, trạng thái hàng/capsule, kết thúc workflow và thứ tự hộp thoại backup.
- The FontLab/PythonQt rendering and full end-to-end font-writing flow must still be exercised on a **disposable FontLab 8 test copy** when moving the release to a different environment.
  
  Khi chuyển bản phát hành sang môi trường khác, vẫn cần kiểm tra hiển thị PythonQt và luồng ghi font thực tế bằng **bản COPY thử nghiệm trong FontLab 8**.

## 1.9.4 Beta — 18–20 November 2026 / 18–20.11.2026

**Focus: UI/UX refinement and consolidated Kerning Studio shell.**  
**Trọng tâm: tinh chỉnh UI/UX và gom ba bước vào một giao diện Kerning Studio.**

- Consolidated Native classes, Cross-check, and OpenType sync into one desktop workflow.  
  Gom Native classes, Cross-check và OpenType sync vào một workflow chung.
- Introduced contextual guidance, action states, separate reports, and read-only summaries.  
  Bổ sung hướng dẫn theo trạng thái, hành động rõ ràng, cửa sổ report riêng và tóm tắt chỉ đọc.
- Refined colors, class labels, checkboxes, list spacing, window layout, and feedback using the Material 3 light theme.  
  Tinh chỉnh màu sắc, nhãn class, checkbox, khoảng cách, bố cục và thông báo theo Material 3 light theme.
- Added **Check → Lock → Confirm** for Native and independent OpenType preflight safeguards.  
  Hoàn thiện quy trình **Kiểm tra → Khóa → Xác nhận** của Native và kiểm tra độc lập của OpenType.
- Verified fresh-scan behavior after OpenType sync to avoid stale **Add glyphs** actions.  
  Kiểm tra việc quét vòng mới sau OpenType sync để tránh nút **Add glyphs** cũ còn xuất hiện.

## Earlier development milestones / Các cột mốc trước đó — November 2026

- Developed and tested **Native Kerning V2** operations for existing FontLab groups.  
  Phát triển và thử nghiệm **Native Kerning V2** với các nhóm kerning có sẵn trong FontLab.
- Built read-only **Native ↔ OpenType `kern`** Cross-check with kerning-side awareness.  
  Xây dựng Cross-check **Native ↔ OpenType `kern`** ở chế độ chỉ đọc và có phân biệt hai phía kerning.
- Added selective OpenType preview, safety preflight, `.fea` backup, and exact readback for FontLab 8 copies.  
  Bổ sung xem trước OpenType có chọn lọc, kiểm tra an toàn, backup `.fea` và đối chiếu kết quả chính xác trên bản COPY FontLab 8.
- Kept the GUI shell separate from the V1/V2/V3 engines.  
  Tách giao diện khỏi các engine V1/V2/V3 để việc sửa UI không vô tình thay đổi phần xử lý dữ liệu quan trọng.
- Investigated FontLab 9; guarded Native/OT writes remain **experimental**.  
  Nghiên cứu FontLab 9; thao tác ghi Native/OpenType có bảo vệ vẫn ở mức **thử nghiệm**.

## Known limits / next review / Giới hạn và hướng phát triển

- **FontLab 9 writing** requires additional implementation and tests.  
  Cần tiếp tục nghiên cứu và kiểm thử khả năng **ghi dữ liệu trên FontLab 9**.
- Complex `.fea` syntax and compiled GPOS lookups remain outside guaranteed Cross-check coverage.  
  Cross-check chưa bảo đảm hỗ trợ cú pháp `.fea` phức tạp hoặc lookup GPOS đã biên dịch.
- Re-test using a fresh copy after upgrading FontLab or companion engines.  
  Nên kiểm tra lại trên bản COPY sạch khi nâng cấp FontLab hay thay đổi các engine đi kèm.

---

**Release principle:** Never let a prettier interface weaken permission checks, backups, user confirmation, or readback.  
**Nguyên tắc phát hành:** Giao diện đẹp hơn không được đánh đổi bằng việc giảm kiểm tra an toàn, bỏ backup, bỏ xác nhận hoặc bỏ xác minh kết quả.
