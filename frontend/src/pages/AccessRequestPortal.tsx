import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../utils/api";
import PageHeader from "../components/ui/PageHeader";
import StatsCard from "../components/ui/StatsCard";
import DataTable from "../components/ui/DataTable";
import Badge from "../components/ui/Badge";

interface AccessRequest {
  id: string;
  status: string;
  business_justification: string;
  created_at: string;
  items: { entitlement_name: string; application_name: string }[];
}

interface Entitlement {
  id: string;
  name: string;
  application_name: string;
  risk_level: string;
}

const AccessRequestPortal: React.FC = () => {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [justification, setJustification] = useState("");

  const { data: requests, isLoading } = useQuery<{ data: AccessRequest[] }>({
    queryKey: ["access-requests"],
    queryFn: () => api.get("/api/v1/access-requests").then((r) => r.data),
  });

  const { data: entitlements } = useQuery<{ data: Entitlement[] }>({
    queryKey: ["entitlements-catalog"],
    queryFn: () => api.get("/api/v1/applications/entitlements/catalog").then((r) => r.data),
    enabled: showForm,
  });

  const submitMutation = useMutation({
    mutationFn: (payload: { entitlement_ids: string[]; business_justification: string }) =>
      api.post("/api/v1/access-requests", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["access-requests"] });
      setShowForm(false);
      setSelected([]);
      setJustification("");
    },
  });

  const statusVariant: Record<string, "default" | "success" | "warning" | "danger" | "info"> = {
    pending: "warning",
    approved: "success",
    rejected: "danger",
    provisioning: "info",
    completed: "success",
  };

  const columns = [
    { key: "id", header: "Request ID", render: (v: string) => v.slice(0, 8) + "..." },
    {
      key: "items",
      header: "Items",
      render: (v: { entitlement_name: string }[]) => v?.length ?? 0,
    },
    {
      key: "status",
      header: "Status",
      render: (v: string) => <Badge variant={statusVariant[v] ?? "default"}>{v}</Badge>,
    },
    {
      key: "created_at",
      header: "Submitted",
      render: (v: string) => new Date(v).toLocaleDateString(),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Access Request Portal"
        subtitle="Request access to applications and entitlements"
        actions={
          <button
            onClick={() => setShowForm(true)}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium"
          >
            + New Request
          </button>
        }
      />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatsCard title="Pending" value={requests?.data.filter((r) => r.status === "pending").length ?? 0} />
        <StatsCard title="Approved" value={requests?.data.filter((r) => r.status === "approved").length ?? 0} color="green" />
        <StatsCard title="Rejected" value={requests?.data.filter((r) => r.status === "rejected").length ?? 0} color="red" />
      </div>

      {showForm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-800 rounded-xl p-6 w-full max-w-2xl space-y-4">
            <h2 className="text-lg font-semibold">New Access Request</h2>
            <div>
              <label className="block text-sm font-medium mb-1">Select Entitlements</label>
              <div className="max-h-60 overflow-y-auto border rounded-lg divide-y dark:border-gray-600">
                {entitlements?.data.map((e) => (
                  <label key={e.id} className="flex items-center gap-3 p-3 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={selected.includes(e.id)}
                      onChange={(ev) =>
                        setSelected((prev) =>
                          ev.target.checked ? [...prev, e.id] : prev.filter((id) => id !== e.id)
                        )
                      }
                    />
                    <div>
                      <div className="text-sm font-medium">{e.name}</div>
                      <div className="text-xs text-gray-500">{e.application_name}</div>
                    </div>
                    <Badge variant={e.risk_level === "high" ? "danger" : e.risk_level === "medium" ? "warning" : "success"} className="ml-auto">
                      {e.risk_level}
                    </Badge>
                  </label>
                ))}
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Business Justification</label>
              <textarea
                className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600"
                rows={3}
                value={justification}
                onChange={(e) => setJustification(e.target.value)}
                placeholder="Explain why you need this access..."
              />
            </div>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setShowForm(false)} className="px-4 py-2 border rounded-lg text-sm">Cancel</button>
              <button
                onClick={() => submitMutation.mutate({ entitlement_ids: selected, business_justification: justification })}
                disabled={selected.length === 0 || !justification}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm disabled:opacity-50"
              >
                Submit Request
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="bg-white dark:bg-gray-800 rounded-xl shadow">
        <div className="p-4 border-b dark:border-gray-700">
          <h2 className="font-semibold">My Requests</h2>
        </div>
        <DataTable columns={columns} data={requests?.data ?? []} isLoading={isLoading} />
      </div>
    </div>
  );
};

export default AccessRequestPortal;
