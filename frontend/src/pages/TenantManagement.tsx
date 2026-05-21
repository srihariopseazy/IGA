import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../utils/api";
import { PageHeader } from "../components/ui/PageHeader";
import { StatsCard } from "../components/ui/StatsCard";
import { DataTable } from "../components/ui/DataTable";
import { Badge } from "../components/ui/Badge";

interface Tenant {
  id: string;
  name: string;
  slug: string;
  plan: string;
  status: string;
  user_count: number;
  created_at: string;
  admin_email: string;
}

const TenantManagement: React.FC = () => {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: "", slug: "", admin_email: "", plan: "starter" });

  const { data, isLoading } = useQuery<{ data: Tenant[] }>({
    queryKey: ["tenants"],
    queryFn: () => api.get("/api/v1/tenants").then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: (payload: typeof form) => api.post("/api/v1/tenants", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
      setShowCreate(false);
    },
  });

  const suspendMutation = useMutation({
    mutationFn: ({ id, suspend }: { id: string; suspend: boolean }) =>
      api.post(`/api/v1/tenants/${id}/${suspend ? "suspend" : "activate"}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tenants"] }),
  });

  const statusVariant: Record<string, "default" | "success" | "warning" | "danger"> = {
    active: "success",
    suspended: "danger",
    trial: "warning",
  };

  const planVariant: Record<string, "default" | "info" | "warning"> = {
    starter: "default",
    professional: "info",
    enterprise: "warning",
  };

  const columns = [
    { key: "name", header: "Tenant Name" },
    { key: "slug", header: "Slug" },
    { key: "admin_email", header: "Admin Email" },
    {
      key: "plan",
      header: "Plan",
      render: (v: string) => <Badge variant={planVariant[v] ?? "default"}>{v}</Badge>,
    },
    {
      key: "status",
      header: "Status",
      render: (v: string) => <Badge variant={statusVariant[v] ?? "default"}>{v}</Badge>,
    },
    { key: "user_count", header: "Users" },
    {
      key: "created_at",
      header: "Created",
      render: (v: string) => new Date(v).toLocaleDateString(),
    },
    {
      key: "id",
      header: "Actions",
      render: (v: string, row: Tenant) => (
        <div className="flex gap-2">
          <button
            onClick={() => suspendMutation.mutate({ id: v, suspend: row.status === "active" })}
            className={`px-2 py-1 text-white text-xs rounded ${row.status === "active" ? "bg-red-600 hover:bg-red-700" : "bg-green-600 hover:bg-green-700"}`}
          >
            {row.status === "active" ? "Suspend" : "Activate"}
          </button>
        </div>
      ),
    },
  ];

  const tenants = data?.data ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Tenant Management"
        description="Manage multi-tenant organizations"
        actions={
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium"
          >
            + New Tenant
          </button>
        }
      />

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatsCard label="Total Tenants" value={tenants.length} />
        <StatsCard label="Active" value={tenants.filter((t) => t.status === "active").length} />
        <StatsCard label="Trial" value={tenants.filter((t) => t.status === "trial").length} />
        <StatsCard label="Suspended" value={tenants.filter((t) => t.status === "suspended").length} />
      </div>

      <div className="bg-white dark:bg-gray-800 rounded-xl shadow">
        <DataTable columns={columns} data={tenants} loading={isLoading} />
      </div>

      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-800 rounded-xl p-6 w-full max-w-md space-y-4">
            <h2 className="text-lg font-semibold">Create Tenant</h2>
            {[
              { key: "name", label: "Organization Name", type: "text" },
              { key: "slug", label: "Slug (unique identifier)", type: "text" },
              { key: "admin_email", label: "Admin Email", type: "email" },
            ].map((f) => (
              <div key={f.key}>
                <label className="block text-sm font-medium mb-1">{f.label}</label>
                <input
                  type={f.type}
                  className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600"
                  value={form[f.key as keyof typeof form]}
                  onChange={(e) => setForm((prev) => ({ ...prev, [f.key]: e.target.value }))}
                />
              </div>
            ))}
            <div>
              <label className="block text-sm font-medium mb-1">Plan</label>
              <select
                className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600"
                value={form.plan}
                onChange={(e) => setForm((f) => ({ ...f, plan: e.target.value }))}
              >
                <option value="starter">Starter</option>
                <option value="professional">Professional</option>
                <option value="enterprise">Enterprise</option>
              </select>
            </div>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setShowCreate(false)} className="px-4 py-2 border rounded-lg text-sm">Cancel</button>
              <button
                onClick={() => createMutation.mutate(form)}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm"
              >
                Create Tenant
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default TenantManagement;
