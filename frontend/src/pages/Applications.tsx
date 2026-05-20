import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../utils/api";
import PageHeader from "../components/ui/PageHeader";
import StatsCard from "../components/ui/StatsCard";
import DataTable from "../components/ui/DataTable";
import Badge from "../components/ui/Badge";

interface Application {
  id: string;
  name: string;
  description: string;
  application_type: string;
  status: string;
  entitlement_count: number;
  user_count: number;
  owner_name: string;
  created_at: string;
}

const Applications: React.FC = () => {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({
    name: "",
    description: "",
    application_type: "web",
    owner_id: "",
  });

  const { data, isLoading } = useQuery<{ data: Application[] }>({
    queryKey: ["applications"],
    queryFn: () => api.get("/api/v1/applications").then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: (payload: typeof form) => api.post("/api/v1/applications", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["applications"] });
      setShowCreate(false);
    },
  });

  const statusVariant: Record<string, "default" | "success" | "warning" | "danger"> = {
    active: "success",
    inactive: "default",
    deprecated: "warning",
  };

  const columns = [
    { key: "name", header: "Application" },
    { key: "description", header: "Description" },
    { key: "application_type", header: "Type" },
    {
      key: "status",
      header: "Status",
      render: (v: string) => <Badge variant={statusVariant[v] ?? "default"}>{v}</Badge>,
    },
    { key: "entitlement_count", header: "Entitlements" },
    { key: "user_count", header: "Users" },
    { key: "owner_name", header: "Owner" },
  ];

  const apps = data?.data ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Applications"
        subtitle="Manage enterprise applications and entitlements"
        actions={
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium"
          >
            + Add Application
          </button>
        }
      />

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatsCard title="Total Applications" value={apps.length} />
        <StatsCard title="Active" value={apps.filter((a) => a.status === "active").length} color="green" />
        <StatsCard title="Total Entitlements" value={apps.reduce((s, a) => s + a.entitlement_count, 0)} color="blue" />
        <StatsCard title="Total Users" value={apps.reduce((s, a) => s + a.user_count, 0)} />
      </div>

      <div className="bg-white dark:bg-gray-800 rounded-xl shadow">
        <DataTable columns={columns} data={apps} isLoading={isLoading} />
      </div>

      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-800 rounded-xl p-6 w-full max-w-md space-y-4">
            <h2 className="text-lg font-semibold">Add Application</h2>
            <div>
              <label className="block text-sm font-medium mb-1">Name</label>
              <input className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Description</label>
              <textarea className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600" rows={2} value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Type</label>
              <select className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600" value={form.application_type} onChange={(e) => setForm((f) => ({ ...f, application_type: e.target.value }))}>
                <option value="web">Web Application</option>
                <option value="saas">SaaS</option>
                <option value="on_premise">On-Premise</option>
                <option value="api">API Service</option>
                <option value="database">Database</option>
              </select>
            </div>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setShowCreate(false)} className="px-4 py-2 border rounded-lg text-sm">Cancel</button>
              <button onClick={() => createMutation.mutate(form)} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm">Create</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Applications;
