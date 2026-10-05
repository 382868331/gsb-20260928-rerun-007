import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { BatchPanel } from "./BatchPanel";
import { api } from "../api";
import type { MeasurementMapping } from "../types";

vi.mock("../api", () => ({
  api: {
    appendBatch: vi.fn(),
    analyzeBatchMappings: vi.fn(),
    confirmBatchMapping: vi.fn(),
    revokeBatchMapping: vi.fn(),
  },
}));

const mockApi = vi.mocked(api);

const proposal: MeasurementMapping = {
  id: "b1:temperature",
  batch: 1,
  target_column: "temperature",
  status: "needs_mapping",
  rule_inheritance: "needs_mapping",
  candidate_columns: ["reading"],
  value_columns: ["reading"],
  unit_candidates: ["uom"],
  unit_column: "uom",
  unit_mode: "per_row",
  sample_units: ["F", ""],
  default_unit: null,
  reason: "数值/单位结构变化，需要确认测量对应关系。",
};

function renderPanel(mappings: Record<string, MeasurementMapping> = {}) {
  return render(
    <BatchPanel
      project="p"
      steps={[]}
      appended={[{ _id: "r0004", batch: 1, columns: ["reading", "uom"] }]}
      mappings={mappings}
      onAppended={() => {}}
      onMappingsChanged={() => {}}
    />
  );
}

describe("BatchPanel default units", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("offers a per-row unit column and a separate column default unit", async () => {
    mockApi.analyzeBatchMappings.mockResolvedValue({
      old_columns: [], new_columns: [], added_columns: [], removed_columns: [],
      mappings: [proposal], confirmed_mappings: [],
      summary: { reusable: 0, needs_mapping: 1, conflicting: 0 },
    });
    mockApi.confirmBatchMapping.mockResolvedValue({
      ok: true, mapping: proposal, mappings: {},
    });
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "分析结构对应" }));
    const defaultInput = await screen.findByPlaceholderText("如 F；留空则空单位报错");
    expect(defaultInput).toBeTruthy();
    fireEvent.change(defaultInput, { target: { value: " C " } });
    fireEvent.click(screen.getByRole("button", { name: "确认对应" }));
    await waitFor(() => expect(mockApi.confirmBatchMapping).toHaveBeenCalledTimes(1));
    expect(mockApi.confirmBatchMapping).toHaveBeenCalledWith("p", 1,
      expect.objectContaining({
        value_column: "reading",
        unit_column: "uom",
        default_unit: "C",
      }));
  });

  it("prefills the saved default and marks blank samples distinctly", async () => {
    mockApi.analyzeBatchMappings.mockResolvedValue({
      old_columns: [], new_columns: [], added_columns: [], removed_columns: [],
      mappings: [proposal], confirmed_mappings: [],
      summary: { reusable: 0, needs_mapping: 1, conflicting: 0 },
    });
    const saved = { ...proposal, status: "confirmed", default_unit: "F",
                    value_column: "reading" };
    renderPanel({ "b1:temperature": saved });
    fireEvent.click(screen.getByRole("button", { name: "分析结构对应" }));
    await screen.findByText(/^已确认：/);
    const defaultInput = screen.getByDisplayValue("F");
    expect(defaultInput).toBeTruthy();
    expect(screen.getByText("（空白）")).toBeTruthy();
    expect(screen.getByText(/只有逐行单位为空时才使用默认单位/)).toBeTruthy();
  });
});
