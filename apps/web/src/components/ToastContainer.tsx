import React from "react";
import { Icon } from "./SvgIcons";
import { useInvoiceFlow } from "../context/InvoiceFlowContext";

export const ToastContainer: React.FC = () => {
  const { toasts } = useInvoiceFlow();

  if (!toasts.length) return null;

  return (
    <div id="toasts">
      {toasts.map((t) => {
        const iconName =
          t.type === "err" ? "alert" : t.type === "warn" ? "info" : "circlecheck";
        return (
          <div key={t.id} className={`toast ${t.type}`}>
            <Icon name={iconName} />
            <span>{t.msg}</span>
          </div>
        );
      })}
    </div>
  );
};
