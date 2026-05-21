import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../utils/api";
import { PageHeader } from "../components/ui/PageHeader";
import { StatsCard } from "../components/ui/StatsCard";
import { DataTable } from "../components/ui/DataTable";
import { Badge } from "../components/ui/Badge";

interface Role {
  id: string;
  name: string;
  description: string;
  role_type: string;
  user_count: number;
  permission_count: number;
  is_active: boolean;
  created_at: string;
}

const Roles: React.FC = () => {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", role_type: "custom" });

  const { data, isLoading } = useQuery<{ data: Role[] }>({
    queryKey: ["roles"],
    queryFn: () => api.get("/api/v1/roles").then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: (payload: typeof form) => api.post("/api/v1/roles", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["roles"] });
      setShowCreate(false);
    },
  });

  const columns = [
    { key: "name", header: "Role Name" },
    { key: "description", header: "Description" },
    {
      key: "role_type",
      header: "Type",
      render: (v: string) => (
        <Badge variant={v === "system" ? "info" : "default"}>{v}</Badge>
      ),
    },
    { key: "user_count", header: "Users" },
    { key: "permission_count", header: "Permissions" },
    {
      key: "is_active",
      header: "Status",
      render: (v: boolean) => <Badge variant={v ? "success" : "default"}>{v ? "Active" : "Inactive"}</Badge>,
    },
  ];

  const roles = data?.data ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Role Management"
        subtitle="Define and manage RBAC roles and permissions"
        actions={
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium"
          >
            + Create Role
          </button>
        }
      />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatsCard title="Total Roles" value={roles.length} />
        <StatsCard title="System Roles" value={roles.filter((r) => r.role_type === "system").length} color="blue" />
        <StatsCard title="Custom Roles" value={roles.filter((r) => r.role_type === "custom").length} color="green" />
      </div>

      <div className="bg-white dark:bg-gray-800 rounded-xl shadow">
        <DataTable columns={columns} data={roles} isLoading={isLoading} />
      </div>

      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-800 rounded-xl p-6 w-full max-w-md space-y-4">
            <h2 className="text-lg font-semibold">Create Role</h2>
            <div>
              <label className="block text-sm font-medium mb-1">Name</label>
              <input
                className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Description</label>
              <textarea
                className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600"
                rows={2}
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
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

export default Roles;
