import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../utils/api";
import { PageHeader } from "../components/ui/PageHeader";
import { StatsCard } from "../components/ui/StatsCard";
import { DataTable } from "../components/ui/DataTable";
import { Badge } from "../components/ui/Badge";

interface SyncJob {
  id: string;
  job_type: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  records_processed: number;
  records_created: number;
  records_updated: number;
  records_failed: number;
  error_message: string | null;
}

const HRMSSync: React.FC = () => {
  const qc = useQueryClient();

  const { data: jobs, isLoading } = useQuery<{ data: SyncJob[] }>({
    queryKey: ["hrms-sync-jobs"],
    queryFn: () => api.get("/api/v1/connectors/hrms/sync-jobs").then((r) => r.data),
    refetchInterval: 10000,
  });

  const { data: config } = useQuery({
    queryKey: ["hrms-config"],
    queryFn: () => api.get("/api/v1/connectors/hrms/config").then((r) => r.data),
  });

  const triggerMutation = useMutation({
    mutationFn: () => api.post("/api/v1/connectors/hrms/sync"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["hrms-sync-jobs"] });
    },
  });

  const statusVariant: Record<string, "default" | "success" | "warning" | "danger" | "info"> = {
    pending: "warning",
    running: "info",
    completed: "success",
    failed: "danger",
  };

  const columns = [
    {
      key: "started_at",
      header: "Started",
      render: (v: string) => new Date(v).toLocaleString(),
    },
    { key: "job_type", header: "Type" },
    {
      key: "status",
      header: "Status",
      render: (v: string) => <Badge variant={statusVariant[v] ?? "default"}>{v}</Badge>,
    },
    { key: "records_processed", header: "Processed" },
    { key: "records_created", header: "Created" },
    { key: "records_updated", header: "Updated" },
    {
      key: "records_failed",
      header: "Failed",
      render: (v: number) => <span className={v > 0 ? "text-red-600 font-medium" : ""}>{v}</span>,
    },
    {
      key: "completed_at",
      header: "Duration",
      render: (v: string | null, row: SyncJob) => {
        if (!v) return row.status === "running" ? "Running..." : "—";
        const ms = new Date(v).getTime() - new Date(row.started_at).getTime();
        return `${Math.round(ms / 1000)}s`;
      },
    },
  ];

  const jobs_ = jobs?.data ?? [];
  const lastJob = jobs_[0];

  return (
    <div className="space-y-6">
      <PageHeader
        title="HRMS Sync"
        description="Synchronize identity data from Human Resource Management Systems"
        actions={
          <button
            onClick={() => triggerMutation.mutate()}
            disabled={triggerMutation.isPending || lastJob?.status === "running"}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium disabled:opacity-50"
          >
            {triggerMutation.isPending ? "Triggering..." : "▶ Run Sync Now"}
          </button>
        }
      />

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatsCard
          label="Last Sync"
          value={lastJob ? new Date(lastJob.started_at).toLocaleDateString() : "Never"}
        />
        <StatsCard
          label="Records Processed"
          value={lastJob?.records_processed ?? 0}
         
        />
        <StatsCard label="Created" value={lastJob?.records_created ?? 0} />
        <StatsCard label="Failed" value={lastJob?.records_failed ?? 0} />
      </div>

      {config?.data && (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-5">
          <h3 className="font-semibold mb-3">HRMS Configuration</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <div className="text-gray-500 text-xs">Provider</div>
              <div className="font-medium mt-1">{config.data.provider ?? "Not configured"}</div>
            </div>
            <div>
              <div className="text-gray-500 text-xs">Sync Schedule</div>
              <div className="font-medium mt-1">{config.data.schedule ?? "Manual"}</div>
            </div>
            <div>
              <div className="text-gray-500 text-xs">Sync Mode</div>
              <div className="font-medium mt-1">{config.data.sync_mode ?? "Full"}</div>
            </div>
            <div>
              <div className="text-gray-500 text-xs">Status</div>
              <div className="font-medium mt-1">
                <Badge variant={config.data.enabled ? "success" : "default"}>
                  {config.data.enabled ? "Enabled" : "Disabled"}
                </Badge>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="bg-white dark:bg-gray-800 rounded-xl shadow">
        <div className="p-4 border-b dark:border-gray-700">
          <h2 className="font-semibold">Sync History</h2>
        </div>
        <DataTable columns={columns} data={jobs_} loading={isLoading} />
      </div>
    </div>
  );
};

export default HRMSSync;
