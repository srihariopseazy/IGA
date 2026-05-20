import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../utils/api";
import PageHeader from "../components/ui/PageHeader";
import StatsCard from "../components/ui/StatsCard";
import DataTable from "../components/ui/DataTable";
import Badge from "../components/ui/Badge";

interface SODViolation {
  id: string;
  user_name: string;
  user_email: string;
  rule_name: string;
  conflicting_entitlements: string[];
  severity: string;
  detected_at: string;
  resolved_at: string | null;
  mitigated: boolean;
}

const SODConflicts: React.FC = () => {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<"all" | "open" | "mitigated">("open");

  const { data, isLoading } = useQuery<{ data: SODViolation[] }>({
    queryKey: ["sod-violations", filter],
    queryFn: () =>
      api.get("/api/v1/sod/violations", { params: { status: filter } }).then((r) => r.data),
  });

  const mitigateMutation = useMutation({
    mutationFn: ({ id, note }: { id: string; note: string }) =>
      api.post(`/api/v1/sod/violations/${id}/mitigate`, { note }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sod-violations"] }),
  });

  const runScanMutation = useMutation({
    mutationFn: () => api.post("/api/v1/sod/scan"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sod-violations"] }),
  });

  const severityVariant: Record<string, "default" | "success" | "warning" | "danger"> = {
    low: "warning",
    medium: "warning",
    high: "danger",
    critical: "danger",
  };

  const violations = data?.data ?? [];

  const columns = [
    { key: "user_name", header: "User" },
    { key: "user_email", header: "Email" },
    { key: "rule_name", header: "SoD Rule" },
    {
      key: "conflicting_entitlements",
      header: "Conflicting Access",
      render: (v: string[]) => (
        <div className="flex flex-wrap gap-1">
          {(v ?? []).map((e) => (
            <span key={e} className="px-1.5 py-0.5 bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 rounded text-xs">{e}</span>
          ))}
        </div>
      ),
    },
    {
      key: "severity",
      header: "Severity",
      render: (v: string) => <Badge variant={severityVariant[v] ?? "default"}>{v}</Badge>,
    },
    {
      key: "detected_at",
      header: "Detected",
      render: (v: string) => new Date(v).toLocaleDateString(),
    },
    {
      key: "mitigated",
      header: "Status",
      render: (v: boolean) => <Badge variant={v ? "success" : "danger"}>{v ? "Mitigated" : "Open"}</Badge>,
    },
    {
      key: "id",
      header: "Actions",
      render: (v: string, row: SODViolation) =>
        !row.mitigated ? (
          <button
            onClick={() => {
              const note = prompt("Enter mitigation note:");
              if (note) mitigateMutation.mutate({ id: v, note });
            }}
            className="text-blue-600 hover:underline text-sm"
          >
            Mitigate
          </button>
        ) : (
          <span className="text-gray-400 text-sm">—</span>
        ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="SoD Conflicts"
        subtitle="Segregation of Duties violations and policy enforcement"
        actions={
          <button
            onClick={() => runScanMutation.mutate()}
            disabled={runScanMutation.isPending}
            className="px-4 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700 text-sm font-medium disabled:opacity-50"
          >
            {runScanMutation.isPending ? "Scanning..." : "Run SoD Scan"}
          </button>
        }
      />

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatsCard title="Total Violations" value={violations.length} />
        <StatsCard title="Critical" value={violations.filter((v) => v.severity === "critical").length} color="red" />
        <StatsCard title="Open" value={violations.filter((v) => !v.mitigated).length} color="yellow" />
        <StatsCard title="Mitigated" value={violations.filter((v) => v.mitigated).length} color="green" />
      </div>

      <div className="flex gap-2">
        {(["all", "open", "mitigated"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium capitalize ${
              filter === f
                ? "bg-blue-600 text-white"
                : "bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300"
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      <div className="bg-white dark:bg-gray-800 rounded-xl shadow">
        <DataTable columns={columns} data={violations} isLoading={isLoading} />
      </div>
    </div>
  );
};

export default SODConflicts;
