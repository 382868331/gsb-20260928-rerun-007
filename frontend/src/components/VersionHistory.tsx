import { History } from "lucide-react";
import type { Manifest } from "../types";

interface Props {
  manifest: Manifest;
  selected: number;
  onSelect: (version: number) => void;
}

export function VersionHistory({ manifest, selected, onSelect }: Props) {
  return (
    <div className="version-history">
      <h3>
        <History size={15} /> 版本历史
      </h3>
      {manifest.versions.map((v) => (
        <button
          key={v.version}
          className={`version-item ${selected === v.version ? "active" : ""}`}
          onClick={() => onSelect(v.version)}
        >
          <span className="version-no">v{v.version}</span>
          <span className="muted small">
            {v.version === 0
              ? "原始数据（不可变）"
              : `${v.steps.length} 步 · 基于 v${v.created_from} · ${v.label || "未命名"}`}
          </span>
        </button>
      ))}
    </div>
  )
}
