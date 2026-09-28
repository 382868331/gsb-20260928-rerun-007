import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DataTable } from "./DataTable";

describe("DataTable", () => {
  it("renders values and source record ids", () => {
    render(
      <DataTable
        columns={["experiment_id", "reading"]}
        rows={[
          { sources: ["r2", "r3"], values: { experiment_id: "E-003", reading: 101.6 } },
          { sources: ["r0"], values: { experiment_id: "E-001", reading: null } },
        ]}
      />
    );
    expect(screen.getByText("E-003")).toBeTruthy();
    expect(screen.getByText("r2, r3")).toBeTruthy();
    expect(screen.getByText("∅")).toBeTruthy();
  });
});
