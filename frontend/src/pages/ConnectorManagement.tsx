import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../utils/api";
import { PageHeader } from "../components/ui/PageHeader";
import { StatsCard } from "../components/ui/StatsCard";
import { Badge } from "../components/ui/Badge";

interface Connector {
  id: string;
  name: string;
  connector_type: string;
  status: string;
  last_sync_at: string | null;
  sync_count: number;
  error_count: number;
}

const TYPE_ICONS: Record<string, string> = {
  ldap: "🗄️",
  active_directory: "🏢",
  scim: "🔗",
  m365: "📧",
  google_workspace: "🔍",
  salesforce: "☁️",
  servicenow: "🎫",
  slack: "💬",
  database: "🗃️",
  rest: "🌐",
};

const ConnectorManagement: React.FC = () => {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: "", connector_type: "ldap", description: "" });

  const { data, isLoading } = useQuery<{ data: Connector[] }>({
    queryKey: ["connectors"],
    queryFn: () => api.get("/api/v1/connectors").then((r) => r.data),
  });

  const testMutation = useMutation({
    mutationFn: (id: string) => api.post(`/api/v1/connectors/${id}/test`),
  });

  const syncMutation = useMutation({
    mutationFn: (id: string) => api.post(`/api/v1/connectors/${id}/sync`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["connectors"] }),
  });

  const createMutation = useMutation({
    mutationFn: (payload: typeof form) => api.post("/api/v1/connectors", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["connectors"] });
      setShowCreate(false);
    },
  });

  const statusVariant: Record<string, "default" | "success" | "warning" | "danger"> = {
    active: "success",
    inactive: "default",
    error: "danger",
    syncing: "warning",
  };

  const connectors = data?.data ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Connector Management"
        subtitle="Manage integrations with identity sources and target systems"
        actions={
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium"
          >
            + Add Connector
          </button>
        }
      />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatsCard title="Total Connectors" value={connectors.length} />
        <StatsCard title="Active" value={connectors.filter((c) => c.status === "active").length} color="green" />
        <StatsCard title="Errors" value={connectors.filter((c) => c.status === "error").length} color="red" />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {isLoading
          ? Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="bg-white dark:bg-gray-800 rounded-xl shadow p-5 animate-pulse h-36" />
            ))
          : connectors.map((connector) => (
              <div key={connector.id} className="bg-white dark:bg-gray-800 rounded-xl shadow p-5 space-y-3">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-2xl">{TYPE_ICONS[connector.connector_type] ?? "🔌"}</span>
                    <div>
                      <div className="font-medium">{connector.name}</div>
                      <div className="text-xs text-gray-500 capitalize">{connector.connector_type.replace("_", " ")}</div>
                    </div>
                  </div>
                  <Badge variant={statusVariant[connector.status] ?? "default"}>{connector.status}</Badge>
                </div>
                <div className="text-xs text-gray-500">
                  Last sync: {connector.last_sync_at ? new Date(connector.last_sync_at).toLocaleString() : "Never"}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => testMutation.mutate(connector.id)}
                    className="flex-1 px-2 py-1.5 border rounded text-xs hover:bg-gray-50 dark:hover:bg-gray-700"
                  >
                    Test
                  </button>
                  <button
                    onClick={() => syncMutation.mutate(connector.id)}
                    disabled={syncMutation.isPending}
                    className="flex-1 px-2 py-1.5 bg-blue-600 text-white rounded text-xs hover:bg-blue-700 disabled:opacity-50"
                  >
                    Sync Now
                  </button>
                </div>
              </div>
            ))}
      </div>

      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-800 rounded-xl p-6 w-full max-w-md space-y-4">
            <h2 className="text-lg font-semibold">Add Connector</h2>
            <div>
              <label className="block text-sm font-medium mb-1">Name</label>
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
                value={form.connector_type}
                onChange={(e) => setForm((f) => ({ ...f, connector_type: e.target.value }))}
              >
                {Object.keys(TYPE_ICONS).map((t) => (
                  <option key={t} value={t}>{t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}</option>
                ))}
              </select>
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

export default ConnectorManagement;
