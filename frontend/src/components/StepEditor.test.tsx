import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { StepEditor } from "./StepEditor";
import type { PipelineStep } from "../types";

describe("StepEditor", () => {
  it("edits dedup keys and conflict policy", () => {
    const step: PipelineStep = {
      id: "s1",
      type: "dedup_merge",
      params: { merge: "mean", on_conflict: "keep_all" },
    };
    const onChange = vi.fn();
    render(
      <StepEditor
        step={step}
        index={0}
        columns={["sample_id", "temp"]}
        onChange={onChange}
        onRemove={() => {}}
      />
    );
    fireEvent.click(screen.getAllByRole("checkbox", { name: "sample_id" })[0]);
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        params: expect.objectContaining({ keys: ["sample_id"] }),
      })
    );
    fireEvent.change(screen.getByDisplayValue("按合并策略保留结果"), {
      target: { value: "error" },
    });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        params: expect.objectContaining({ on_conflict: "error" }),
      })
    );
  });

  it("switches step type and resets params", () => {
    const onChange = vi.fn();
    render(
      <StepEditor
        step={{ id: "s2", type: "missing_values", params: { strategy: "x" } }}
        index={1}
        columns={[]}
        onChange={onChange}
        onRemove={() => {}}
      />
    );
    fireEvent.change(screen.getByDisplayValue("2. 缺失值处理"), {
      target: { value: "unit_convert" },
    });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ type: "unit_convert", params: {} })
    );
  });

  it("edits per-source anomaly rules for validate_numbers", () => {
    const onChange = vi.fn();
    render(
      <StepEditor
        step={{
          id: "s3",
          type: "validate_numbers",
          params: {
            columns: ["v"],
            source_column: "source",
            strict: true,
            rules: [
              { kind: "invalid", source: "lab-b", action: "replace", value: "" },
            ],
          },
        }}
        index={2}
        columns={["source", "v"]}
        onChange={onChange}
        onRemove={() => {}}
      />
    );
    fireEvent.click(screen.getByText("添加异常策略"));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        params: expect.objectContaining({
          rules: expect.arrayContaining([
            expect.objectContaining({ action: "flag", kind: "invalid" }),
          ]),
        }),
      })
    );
    // replacement value input is enabled only for the replace policy
    const valueInput = screen.getByPlaceholderText("必须明确给出");
    fireEvent.change(valueInput, { target: { value: "-99" } });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        params: expect.objectContaining({
          rules: [expect.objectContaining({ value: "-99" })],
        }),
      })
    );
  });
});
