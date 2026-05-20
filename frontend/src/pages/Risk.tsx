import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../utils/api";
import PageHeader from "../components/ui/PageHeader";
import StatsCard from "../components/ui/StatsCard";
import DataTable from "../components/ui/DataTable";
import Badge from "../components/ui/Badge";

interface RiskScore {
  id: string;
  user_name: string;
  user_email: string;
  overall_score: number;
  risk_level: string;
  sod_score: number;
  anomaly_score: number;
  over_provisioning_score: number;
  cert_failure_score: number;
  peer_deviation_score: number;
  calculated_at: string;
}

const RISK_COLORS: Record<string, string> = {
  critical: "bg-red-600",
  high: "bg-orange-500",
  medium: "bg-yellow-500",
  low: "bg-green-500",
};

const Risk: React.FC = () => {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<string>("all");

  const { data, isLoading } = useQuery<{ data: RiskScore[] }>({
    queryKey: ["risk-scores", filter],
    queryFn: () =>
      api
        .get("/api/v1/risk/scores", { params: filter !== "all" ? { risk_level: filter } : {} })
        .then((r) => r.data),
  });

  const recalcMutation = useMutation({
    mutationFn: () => api.post("/api/v1/risk/recalculate-all"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["risk-scores"] }),
  });

  const riskVariant: Record<string, "default" | "success" | "warning" | "danger"> = {
    critical: "danger",
    high: "danger",
    medium: "warning",
    low: "success",
  };

  const scores = data?.data ?? [];

  const columns = [
    { key: "user_name", header: "User" },
    { key: "user_email", header: "Email" },
    {
      key: "overall_score",
      header: "Risk Score",
      render: (v: number, row: RiskScore) => (
        <div className="flex items-center gap-2">
          <div className="w-24 bg-gray-200 dark:bg-gray-600 rounded-full h-2">
            <div
              className={`${RISK_COLORS[row.risk_level] ?? "bg-gray-400"} rounded-full h-2`}
              style={{ width: `${v}%` }}
            />
          </div>
          <span className="text-sm font-medium">{v.toFixed(1)}</span>
        </div>
      ),
    },
    {
      key: "risk_level",
      header: "Level",
      render: (v: string) => <Badge variant={riskVariant[v] ?? "default"}>{v}</Badge>,
    },
    {
      key: "sod_score",
      header: "SoD",
      render: (v: number) => v.toFixed(1),
    },
    {
      key: "anomaly_score",
      header: "Anomaly",
      render: (v: number) => v.toFixed(1),
    },
    {
      key: "over_provisioning_score",
      header: "Over-Prov",
      render: (v: number) => v.toFixed(1),
    },
    {
      key: "calculated_at",
      header: "Last Calculated",
      render: (v: string) => new Date(v).toLocaleString(),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Risk Dashboard"
        subtitle="Identity risk scores and anomaly detection"
        actions={
          <button
            onClick={() => recalcMutation.mutate()}
            disabled={recalcMutation.isPending}
            className="px-4 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700 text-sm font-medium disabled:opacity-50"
          >
            {recalcMutation.isPending ? "Recalculating..." : "Recalculate All"}
          </button>
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {(["critical", "high", "medium", "low"] as const).map((level) => (
          <StatsCard
            key={level}
            title={level.charAt(0).toUpperCase() + level.slice(1) + " Risk"}
            value={scores.filter((s) => s.risk_level === level).length}
            color={level === "critical" || level === "high" ? "red" : level === "medium" ? "yellow" : "green"}
          />
        ))}
      </div>

      <div className="flex gap-2">
        {["all", "critical", "high", "medium", "low"].map((f) => (
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
        <DataTable columns={columns} data={scores} isLoading={isLoading} />
      </div>
    </div>
  );
};

export default Risk;
