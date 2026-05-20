import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../utils/api";
import PageHeader from "../components/ui/PageHeader";
import StatsCard from "../components/ui/StatsCard";
import DataTable from "../components/ui/DataTable";
import Badge from "../components/ui/Badge";

interface Campaign {
  id: string;
  name: string;
  status: string;
  campaign_type: string;
  start_date: string;
  end_date: string;
  total_items: number;
  certified_items: number;
  revoked_items: number;
  pending_items: number;
}

const Certifications: React.FC = () => {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: "", campaign_type: "user_access", end_date: "" });

  const { data, isLoading } = useQuery<{ data: Campaign[] }>({
    queryKey: ["certifications"],
    queryFn: () => api.get("/api/v1/certifications").then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: (payload: typeof form) => api.post("/api/v1/certifications", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["certifications"] });
      setShowCreate(false);
    },
  });

  const statusVariant: Record<string, "default" | "success" | "warning" | "danger" | "info"> = {
    draft: "default",
    active: "info",
    completed: "success",
    expired: "danger",
  };

  const columns = [
    { key: "name", header: "Campaign Name" },
    { key: "campaign_type", header: "Type" },
    {
      key: "status",
      header: "Status",
      render: (v: string) => <Badge variant={statusVariant[v] ?? "default"}>{v}</Badge>,
    },
    {
      key: "total_items",
      header: "Progress",
      render: (_: number, row: Campaign) => {
        const pct = row.total_items ? Math.round(((row.certified_items + row.revoked_items) / row.total_items) * 100) : 0;
        return (
          <div className="flex items-center gap-2">
            <div className="flex-1 bg-gray-200 dark:bg-gray-600 rounded-full h-2">
              <div className="bg-blue-600 rounded-full h-2" style={{ width: `${pct}%` }} />
            </div>
            <span className="text-xs text-gray-500">{pct}%</span>
          </div>
        );
      },
    },
    {
      key: "end_date",
      header: "Due Date",
      render: (v: string) => new Date(v).toLocaleDateString(),
    },
    {
      key: "id",
      header: "Actions",
      render: (v: string) => (
        <button
          onClick={() => window.location.href = `/certifications/${v}`}
          className="text-blue-600 hover:underline text-sm"
        >
          Review
        </button>
      ),
    },
  ];

  const campaigns = data?.data ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Access Certifications"
        subtitle="Review and certify user access rights"
        actions={
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium"
          >
            + New Campaign
          </button>
        }
      />

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatsCard title="Active Campaigns" value={campaigns.filter((c) => c.status === "active").length} />
        <StatsCard title="Pending Reviews" value={campaigns.reduce((s, c) => s + c.pending_items, 0)} color="yellow" />
        <StatsCard title="Certified" value={campaigns.reduce((s, c) => s + c.certified_items, 0)} color="green" />
        <StatsCard title="Revoked" value={campaigns.reduce((s, c) => s + c.revoked_items, 0)} color="red" />
      </div>

      <div className="bg-white dark:bg-gray-800 rounded-xl shadow">
        <DataTable columns={columns} data={campaigns} isLoading={isLoading} />
      </div>

      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-800 rounded-xl p-6 w-full max-w-md space-y-4">
            <h2 className="text-lg font-semibold">Create Certification Campaign</h2>
            <div>
              <label className="block text-sm font-medium mb-1">Campaign Name</label>
              <input
                className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Type</label>
              <select
                className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600"
                value={form.campaign_type}
                onChange={(e) => setForm((f) => ({ ...f, campaign_type: e.target.value }))}
              >
                <option value="user_access">User Access</option>
                <option value="role_membership">Role Membership</option>
                <option value="privileged_access">Privileged Access</option>
                <option value="sod_conflict">SoD Conflict</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">End Date</label>
              <input
                type="date"
                className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600"
                value={form.end_date}
                onChange={(e) => setForm((f) => ({ ...f, end_date: e.target.value }))}
              />
            </div>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setShowCreate(false)} className="px-4 py-2 border rounded-lg text-sm">Cancel</button>
              <button
                onClick={() => createMutation.mutate(form)}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm"
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Certifications;
