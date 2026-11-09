import React from "react";

interface ReviewNoteModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (note: string) => void;
}

export const ReviewNoteModal: React.FC<ReviewNoteModalProps> = ({
  isOpen,
  onClose,
  onSubmit,
}) => {
  const [note, setNote] = React.useState("");

  if (!isOpen) return null;

  return (
    <div
      className="modal on"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 200,
        background: "rgba(15,27,61,.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div className="mbox" style={{ width: "440px" }}>
        <h3>Đánh dấu cần rà soát</h3>
        <p>Nhập ghi chú yêu cầu kiểm tra đối với chứng từ này:</p>
        <textarea
          className="inp"
          rows={3}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Ví dụ: Kiểm tra lại đơn giá hoặc số lượng..."
        />
        <div className="ft">
          <button type="button" className="bt" onClick={onClose}>
            Hủy
          </button>
          <button
            type="button"
            className="bt d"
            onClick={() => {
              if (note.trim()) {
                onSubmit(note.trim());
              }
            }}
          >
            Từ chối / Cần rà soát
          </button>
        </div>
      </div>
    </div>
  );
};
