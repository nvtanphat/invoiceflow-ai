import React, { useEffect } from "react";
import { SvgDefs } from "../components/SvgIcons";
import { TopNav } from "../components/TopNav";
import { ToastContainer } from "../components/ToastContainer";
import { InvoiceFlowProvider, useInvoiceFlow } from "../context/InvoiceFlowContext";
import { LoginPage } from "../features/auth/LoginPage";
import { ProcessingPage } from "../features/processing/ProcessingPage";
import { DashboardPage } from "../features/dashboard/DashboardPage";
import { MatchingPage } from "../features/matching/MatchingPage";
import { ApprovalsPage } from "../features/approvals/ApprovalsPage";
import { ExportPage } from "../features/exports/ExportPage";
import { ReportsPage } from "../features/reports/ReportsPage";
import { ExportModal } from "../features/exports/ExportModal";

const MainLayout: React.FC = () => {
  const { session, activePage, isExportModalOpen, setIsExportModalOpen } = useInvoiceFlow();

  useEffect(() => {
    const W = 1672;
    const H = 941;
    const fit = () => {
      const stage = document.getElementById("stage");
      if (!stage) return;
      const vw = window.innerWidth;
      const vh = window.innerHeight;

      if (vw < 1024) {
        stage.style.transform = "";
        stage.style.width = "100%";
        stage.style.height = "auto";
        stage.style.minWidth = "1180px";
        document.body.style.overflow = "auto";
        return;
      }

      document.body.style.overflow = "hidden";
      const s = Math.min(vw / W, vh / H);
      stage.style.transform = `scale(${s})`;
      stage.style.width = `${vw / s}px`;
      stage.style.height = `${vh / s}px`;
      stage.style.minWidth = "";
    };

    fit();
    window.addEventListener("resize", fit);
    return () => {
      window.removeEventListener("resize", fit);
      document.body.style.overflow = "auto";
    };
  }, [session]);

  if (!session) {
    return <LoginPage />;
  }

  return (
    <div id="stage">
      <TopNav />
      {activePage === "xu-ly" && <ProcessingPage />}
      {activePage === "tong-quan" && <DashboardPage />}
      {activePage === "doi-soat" && <MatchingPage />}
      {activePage === "phe-duyet" && <ApprovalsPage />}
      {activePage === "xuat-du-lieu" && <ExportPage />}
      {activePage === "bao-cao" && <ReportsPage />}
      <ExportModal isOpen={isExportModalOpen} onClose={() => setIsExportModalOpen(false)} />
      <ToastContainer />
    </div>
  );
};

export const App: React.FC = () => {
  return (
    <InvoiceFlowProvider>
      <SvgDefs />
      <MainLayout />
    </InvoiceFlowProvider>
  );
};
