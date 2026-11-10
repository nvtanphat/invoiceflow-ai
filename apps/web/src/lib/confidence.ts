// Evidence confidence is only reported when an engine measured it (OCR); model and
// deterministic values carry none, so absent values are shown as unknown, never as 100%.
export type ConfidenceCarrier = { confidence?: number | null };

export const meanConfidence = (evidence: ConfidenceCarrier[] | undefined | null): number | null => {
  const known = (evidence ?? [])
    .map((e) => e.confidence)
    .filter((c): c is number => typeof c === "number");
  return known.length > 0 ? known.reduce((sum, c) => sum + c, 0) / known.length : null;
};

export const formatConfidence = (confidence: number | null | undefined): string =>
  typeof confidence === "number" ? `${Math.round(confidence * 100)}%` : "—";
