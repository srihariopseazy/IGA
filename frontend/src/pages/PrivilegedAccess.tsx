import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../utils/api";
import { PageHeader } from "../components/ui/PageHeader";
import { StatsCard } from "../components/ui/StatsCard";
import { DataTable } from "../components/ui/DataTable";
import { Badge } from "../components/ui/Badge";

interface PAMSession {
  id: string;
  user_name: string;
  privileged_account_name: string;
  system_name: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  duration_minutes: number | null;
  reason: string;
}

interface BreakGlassRequest {
  id: string;
  requester_name: string;
  target_system: string;
  reason: string;
  status: string;
  created_at: string;
}

const PrivilegedAccess: React.FC = () => {
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState<"sessions" | "breakglass">("sessions");
  const [showBG, setShowBG] = useState(false);
  const [bgForm, setBgForm] = useState({ target_system: "", reason: "", duration_hours: 1 });

  const { data: sessions, isLoading: sessionsLoading } = useQuery<{ data: PAMSession[] }>({
    queryKey: ["pam-sessions"],
    queryFn: () => api.get("/api/v1/pam/sessions").then((r) => r.data),
    enabled: activeTab === "sessions",
  });

  const { data: bgRequests, isLoading: bgLoading } = useQuery<{ data: BreakGlassRequest[] }>({
    queryKey: ["break-glass-requests"],
    queryFn: () => api.get("/api/v1/pam/break-glass").then((r) => r.data),
    enabled: activeTab === "breakglass",
  });

  const terminateMutation = useMutation({
    mutationFn: (id: string) => api.post(`/api/v1/pam/sessions/${id}/terminate`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pam-sessions"] }),
  });

  const bgMutation = useMutation({
    mutationFn: (payload: typeof bgForm) => api.post("/api/v1/pam/break-glass", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["break-glass-requests"] });
      setShowBG(false);
    },
  });

  const sessionColumns = [
    { key: "user_name", header: "User" },
    { key: "privileged_account_name", header: "Privileged Account" },
    { key: "system_name", header: "System" },
    {
      key: "status",
      header: "Status",
      render: (v: string) => (
        <Badge variant={v === "active" ? "success" : v === "terminated" ? "danger" : "default"}>{v}</Badge>
      ),
    },
    {
      key: "started_at",
      header: "Started",
      render: (v: string) => new Date(v).toLocaleString(),
    },
    {
      key: "duration_minutes",
      header: "Duration",
      render: (v: number | null) => v ? `${v}m` : "Active",
    },
    {
      key: "id",
      header: "Actions",
      render: (v: string, row: PAMSession) =>
        row.status === "active" ? (
          <button
            onClick={() => terminateMutation.mutate(v)}
            className="px-2 py-1 bg-red-600 text-white text-xs rounded hover:bg-red-700"
          >
            Terminate
          </button>
        ) : null,
    },
  ];

  const bgColumns = [
    { key: "requester_name", header: "Requester" },
    { key: "target_system", header: "Target System" },
    { key: "reason", header: "Reason" },
    {
      key: "status",
      header: "Status",
      render: (v: string) => (
        <Badge variant={v === "approved" ? "success" : v === "pending" ? "warning" : "danger"}>{v}</Badge>
      ),
    },
    {
      key: "created_at",
      header: "Requested",
      render: (v: string) => new Date(v).toLocaleDateString(),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Privileged Access Management"
        description="Monitor and control privileged account usage"
        actions={
          <button
            onClick={() => setShowBG(true)}
            className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 text-sm font-medium"
          >
            🚨 Break Glass
          </button>
        }
      />

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatsCard label="Active Sessions" value={(sessions?.data ?? []).filter((s: any) => s.status === "active").length ?? 0} />
        <StatsCard label="Total Sessions Today" value={(sessions?.data ?? []).length ?? 0} />
        <StatsCard label="Avg Duration (min)" value={Math.round(((sessions?.data ?? []).reduce((s: number, r: any) => s + (r.duration_minutes ?? 0), 0) ?? 0) / Math.max((sessions?.data ?? []).length ?? 1, 1))} />
        <StatsCard label="Break Glass (pending)" value={(bgRequests?.data ?? []).filter((b: any) => b.status === "pending").length ?? 0} />
      </div>

      <div className="flex gap-2">
        {(["sessions", "breakglass"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setActiveTab(t)}
            className={`px-4 py-2 rounded-lg text-sm font-medium ${
              activeTab === t ? "bg-blue-600 text-white" : "bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300"
            }`}
          >
            {t === "sessions" ? "Active Sessions" : "Break Glass Requests"}
          </button>
        ))}
      </div>

      <div className="bg-white dark:bg-gray-800 rounded-xl shadow">
        {activeTab === "sessions" ? (
          <DataTable columns={sessionColumns} data={sessions?.data ?? []} loading={sessionsLoading} />
        ) : (
          <DataTable columns={bgColumns} data={bgRequests?.data ?? []} loading={bgLoading} />
        )}
      </div>

      {showBG && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-800 rounded-xl p-6 w-full max-w-md space-y-4 border-2 border-red-500">
            <h2 className="text-lg font-semibold text-red-600">⚠️ Break Glass Request</h2>
            <p className="text-sm text-gray-500">This action will be fully logged and requires justification.</p>
            <div>
              <label className="block text-sm font-medium mb-1">Target System</label>
              <input
                className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600"
                value={bgForm.target_system}
                onChange={(e) => setBgForm((f) => ({ ...f, target_system: e.target.value }))}
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Justification</label>
              <textarea
                className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600"
                rows={3}
                value={bgForm.reason}
                onChange={(e) => setBgForm((f) => ({ ...f, reason: e.target.value }))}
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Duration (hours)</label>
              <input
                type="number"
                min={1}
                max={8}
                className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600"
                value={bgForm.duration_hours}
                onChange={(e) => setBgForm((f) => ({ ...f, duration_hours: Number(e.target.value) }))}
              />
            </div>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setShowBG(false)} className="px-4 py-2 border rounded-lg text-sm">Cancel</button>
              <button
                onClick={() => bgMutation.mutate(bgForm)}
                className="px-4 py-2 bg-red-600 text-white rounded-lg text-sm hover:bg-red-700"
              >
                Submit Request
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default PrivilegedAccess;
