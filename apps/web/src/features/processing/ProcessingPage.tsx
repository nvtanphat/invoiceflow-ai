import React from "react";
import { DocumentList } from "./DocumentList";
import { DocumentViewer } from "./DocumentViewer";
import { ExtractionPanel } from "./ExtractionPanel";

export const ProcessingPage: React.FC = () => {
  return (
    <main className="pg on" id="pg-xu-ly">
      <DocumentList />
      <DocumentViewer />
      <ExtractionPanel />
    </main>
  );
};
