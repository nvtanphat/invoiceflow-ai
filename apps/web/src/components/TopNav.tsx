import React, { useState, useRef, useEffect } from "react";
import { Icon } from "./SvgIcons";
import { useInvoiceFlow, NavPage } from "../context/InvoiceFlowContext";

export const TopNav: React.FC = () => {
  const {
    session,
    activePage,
    setActivePage,
    setIsExportModalOpen,
    events,
    markAllRead,
    logout,
    switchRole,
    showToast,
  } = useInvoiceFlow();

  const [isBellOpen, setIsBellOpen] = useState(false);
  const [isUserOpen, setIsUserOpen] = useState(false);
  const bellRef = useRef<HTMLDivElement>(null);
  const userRef = useRef<HTMLDivElement>(null);

  const hasUnread = events.some((e) => e.unread);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (bellRef.current && !bellRef.current.contains(target)) {
        setIsBellOpen(false);
      }
      if (userRef.current && !userRef.current.contains(target)) {
        setIsUserOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const navItems: { page: NavPage; label: string; icon: string }[] = [
    { page: "tong-quan", label: "Tổng quan", icon: "home" },
    { page: "xu-ly", label: "Xử lý chứng từ", icon: "doc" },
    { page: "doi-soat", label: "Đối soát (3-Way)", icon: "layers" },
    { page: "phe-duyet", label: "Phê duyệt", icon: "approve" },
    { page: "xuat-du-lieu", label: "Xuất dữ liệu", icon: "export" },
    { page: "bao-cao", label: "Báo cáo", icon: "report" },
  ];

  const roleLabels: Record<string, string> = {
    accountant: "Kế toán",
    reviewer: "Kiểm soát",
    admin: "Quản trị",
    viewer: "Ban GĐ",
  };

  const initials =
    session?.role === "admin"
      ? "AD"
      : session?.role === "reviewer"
      ? "KS"
      : session?.role === "viewer"
      ? "GD"
      : "NP";

  return (
    <header className="top">
      {/* Brand logo */}
      <div
        className="logo"
        style={{ cursor: "pointer" }}
        onClick={() => setActivePage("xu-ly")}
      >
        <svg width="52" height="36" viewBox="0 0 52 36" aria-hidden="true">
          <defs>
            <linearGradient id="nav-brand-grad" x1="0" y1="1" x2="1" y2="0">
              <stop offset="0" stopColor="#1b3fb8" />
              <stop offset="1" stopColor="#2f8cff" />
            </linearGradient>
          </defs>
          <path d="M3 34 15 4h9L12 34Z" fill="url(#nav-brand-grad)" />
          <path
            d="M20 34 32 4h18l-3 7.5H37.5l-1.8 4.5H46l-3 7.5H32.7L29 34Z"
            fill="url(#nav-brand-grad)"
          />
        </svg>
        <span className="brand">
          InvoiceFlow <b>AI</b>
        </span>
      </div>

      <span className="vsep"></span>
      <span className="tag">Document AI · Công ty Cổ phần Thương mại Alpha VN</span>

      {/* Navigation Links */}
      <nav id="nav">
        {navItems.map((item) => {
          const isOn = activePage === item.page;
          return (
            <a
              key={item.page}
              className={`ni ${isOn ? "on" : ""}`}
              data-page={item.page}
              href={`#${item.page}`}
              onClick={(e) => {
                e.preventDefault();
                setActivePage(item.page);
              }}
            >
              <Icon name={item.icon} />
              {item.label}
            </a>
          );
        })}
      </nav>

      {/* Header Right */}
      <div className="hr" style={{ position: "relative" }}>
        {/* Role switcher segment */}
        <div className="sg" style={{ marginRight: "10px", height: "32px", padding: "2px" }}>
          {(["accountant", "reviewer", "admin", "viewer"] as const).map((r) => (
            <button
              key={r}
              type="button"
              className={session?.role === r ? "on" : ""}
              onClick={() => switchRole(r)}
              style={{ height: "28px", padding: "0 10px", fontSize: "12px" }}
              title={`Chuyển vai trò sang ${roleLabels[r]}`}
            >
              {roleLabels[r]}
            </button>
          ))}
        </div>

        {/* Export shortcut button */}
        <button
          type="button"
          onClick={() => setIsExportModalOpen(true)}
          className="bt s"
          style={{ marginRight: "14px", height: "32px" }}
        >
          <Icon name="export" /> Xuất dữ liệu
        </button>

        {/* Bell notifications */}
        <div
          ref={bellRef}
          className="bell"
          id="bell"
          style={{ cursor: "pointer" }}
          onClick={() => {
            setIsBellOpen(!isBellOpen);
            setIsUserOpen(false);
          }}
          title="Thông báo hệ thống"
        >
          <Icon name="bell" />
          {hasUnread && <i id="bellDot"></i>}
        </div>

        {/* User avatar and chevron */}
        <div
          ref={userRef}
          style={{ display: "flex", alignItems: "center", cursor: "pointer" }}
          onClick={() => {
            setIsUserOpen(!isUserOpen);
            setIsBellOpen(false);
          }}
          title="Tài khoản người dùng"
        >
          <div className="avatar">{initials}</div>
          <Icon name="chd" className="chev" />
        </div>

        {/* Logout shortcut */}
        <button
          type="button"
          title="Đăng xuất"
          className="bt s d"
          style={{ marginLeft: "12px", height: "32px", padding: "0 10px" }}
          onClick={() => logout()}
        >
          <Icon name="logout" />
        </button>

        {/* Bell Menu Dropdown */}
        {isBellOpen && (
          <div
            className="menu wide"
            style={{
              position: "absolute",
              right: "48px",
              top: "48px",
              zIndex: 130,
            }}
          >
            <div className="nh">
              Thông báo
              <span
                onClick={() => {
                  markAllRead();
                  showToast("Đã đánh dấu tất cả là đã đọc.");
                }}
                style={{ cursor: "pointer" }}
              >
                Đánh dấu đã đọc
              </span>
            </div>
            <div className="nl">
              {events.length === 0 ? (
                <div className="empty" style={{ padding: "30px" }}>
                  Không có thông báo
                </div>
              ) : (
                events.map((ev) => (
                  <div
                    key={ev.id}
                    className={`ni2 ${ev.unread ? "" : "rd"}`}
                    onClick={() => {
                      if (ev.page) setActivePage(ev.page);
                      setIsBellOpen(false);
                    }}
                    style={{ cursor: "pointer" }}
                  >
                    <i className="dot"></i>
                    <div>
                      <b>{ev.txt}</b>
                      <small>Hôm nay, {ev.t}</small>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {/* User Menu Dropdown */}
        {isUserOpen && (
          <div
            className="menu"
            style={{
              position: "absolute",
              right: "0px",
              top: "48px",
              minWidth: "220px",
              zIndex: 130,
            }}
          >
            <div className="uh">
              <b>Phát ({initials})</b>
              <small>
                {session?.role === "admin"
                  ? "Quản trị viên hệ thống"
                  : session?.role === "accountant"
                  ? "Kế toán viên xử lý"
                  : session?.role === "reviewer"
                  ? "Kiểm soát viên đối soát"
                  : "Giám đốc tài chính (Duyệt)"}
              </small>
            </div>
            <div
              className="mi"
              onClick={() => {
                showToast(
                  `Tài khoản: ${session?.role ? roleLabels[session.role] : "Kế toán"} – Hạn mức duyệt đến 50 triệu/chứng từ.`,
                  "warn"
                );
                setIsUserOpen(false);
              }}
            >
              <Icon name="user" />
              <span>Hồ sơ của tôi</span>
            </div>
            <div
              className="mi"
              onClick={() => {
                setActivePage("doi-soat");
                setIsUserOpen(false);
              }}
            >
              <Icon name="sliders" />
              <span>Dung sai đối soát</span>
            </div>
            <div
              className="mi"
              onClick={() => {
                setActivePage("phe-duyet");
                setIsUserOpen(false);
              }}
            >
              <Icon name="approve" />
              <span>Hàng đợi phê duyệt</span>
            </div>
            <div
              className="mi"
              onClick={() => {
                setIsExportModalOpen(true);
                setIsUserOpen(false);
              }}
            >
              <Icon name="export" />
              <span>Xuất dữ liệu kế toán</span>
            </div>
            <div className="msep"></div>
            <div
              className="mi dg"
              onClick={() => {
                logout();
                setIsUserOpen(false);
              }}
            >
              <Icon name="logout" />
              <span>Đăng xuất</span>
            </div>
          </div>
        )}
      </div>
    </header>
  );
};
