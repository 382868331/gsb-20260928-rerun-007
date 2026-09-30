import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { PreviewPanel } from "./PreviewPanel";
import type { PreviewResult } from "../types";

const preview: PreviewResult = {
  row_count_before: 8,
  row_count_after: 6,
  sample: [],
  reports: [
    {
      type: "unit_convert",
      label: "单位换算",
      params: {},
      stats: {
        converted_rows: 4,
        affected_rows: [
          { row_id: "r0002", column: "temperature", before: "77.0", after: 25, unit: "F" },
        ],
      },
      actions: [
        { origins: ["r0002"], description: "单位换算：temperature 77.0 F → 25.0", detail: {} },
      ],
      row_count_before: 8,
      row_count_after: 8,
    },
    {
      type: "dedup_merge",
      label: "重复记录合并",
      params: {},
      stats: { duplicate_groups: 2, affected_rows: [] },
      actions: [],
      row_count_before: 8,
      row_count_after: 6,
    },
  ],
};

describe("PreviewPanel", () => {
  afterEach(cleanup);

  it("shows affected rows and lets each step be accepted or rejected", () => {
    const onAccept = vi.fn();
    const onReject = vi.fn();
    render(
      <PreviewPanel
        preview={preview}
        accepted={new Set<number>()}
        onAccept={onAccept}
        onReject={onReject}
      />
    );
    expect(screen.getByText(/r0002/)).toBeTruthy();
    expect(screen.getByText(/77\.0 F → 25/)).toBeTruthy();
    fireEvent.click(screen.getAllByText("接受这一步")[0]);
    expect(onAccept).toHaveBeenCalledWith(0);
    fireEvent.click(screen.getAllByText("退回这一步")[0]);
    expect(onReject).toHaveBeenCalledWith(0);
  });

  it("marks accepted steps and hides their decision buttons", () => {
    const { container } = render(
      <PreviewPanel
        preview={preview}
        accepted={new Set([0])}
        onAccept={() => {}}
        onReject={() => {}}
      />
    );
    expect(screen.getAllByText("已接受").length).toBe(1);
    expect(container.querySelectorAll(".report-item").length).toBe(2);
    expect(container.querySelectorAll(".report-item.accepted").length).toBe(1);
    const acceptButtons = screen
      .getAllByRole("button")
      .filter((b) => b.textContent?.includes("接受这一步"));
    const rejectButtons = screen
      .getAllByRole("button")
      .filter((b) => b.textContent?.includes("退回这一步"));
    expect(acceptButtons.length).toBe(1);
    expect(rejectButtons.length).toBe(1);
  });
});
