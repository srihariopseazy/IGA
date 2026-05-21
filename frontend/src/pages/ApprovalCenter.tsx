import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../utils/api";
import { PageHeader } from "../components/ui/PageHeader";
import { StatsCard } from "../components/ui/StatsCard";
import { DataTable } from "../components/ui/DataTable";
import { Badge } from "../components/ui/Badge";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";

interface PendingApproval {
  id: string;
  access_request_id: string;
  requester_name: string;
  entitlement_name: string;
  application_name: string;
  business_justification: string;
  risk_level: string;
  created_at: string;
}

const ApprovalCenter: React.FC = () => {
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [action, setAction] = useState<"approve" | "reject" | null>(null);
  const [comment, setComment] = useState("");
  const [bulkSelected, setBulkSelected] = useState<string[]>([]);

  const { data, isLoading } = useQuery<{ data: PendingApproval[] }>({
    queryKey: ["pending-approvals"],
    queryFn: () => api.get("/api/v1/access-requests/pending-approvals").then((r) => r.data),
  });

  const actionMutation = useMutation({
    mutationFn: ({ id, act, cmt }: { id: string; act: string; cmt: string }) =>
      api.post(`/api/v1/access-requests/${id}/approve`, { action: act, comment: cmt }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pending-approvals"] });
      setSelectedId(null);
      setAction(null);
      setComment("");
    },
  });

  const bulkMutation = useMutation({
    mutationFn: ({ ids, act }: { ids: string[]; act: string }) =>
      api.post("/api/v1/access-requests/bulk-approve", { request_ids: ids, action: act }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pending-approvals"] });
      setBulkSelected([]);
    },
  });

  const columns = [
    {
      key: "id",
      header: "",
      render: (v: string) => (
        <input
          type="checkbox"
          checked={bulkSelected.includes(v)}
          onChange={(e) =>
            setBulkSelected((prev) =>
              e.target.checked ? [...prev, v] : prev.filter((id) => id !== v)
            )
          }
        />
      ),
    },
    { key: "requester_name", header: "Requester" },
    { key: "entitlement_name", header: "Entitlement" },
    { key: "application_name", header: "Application" },
    {
      key: "risk_level",
      header: "Risk",
      render: (v: string) => (
        <Badge variant={v === "high" ? "danger" : v === "medium" ? "warning" : "success"}>{v}</Badge>
      ),
    },
    {
      key: "created_at",
      header: "Requested",
      render: (v: string) => new Date(v).toLocaleDateString(),
    },
    {
      key: "id",
      header: "Actions",
      render: (v: string, row: PendingApproval) => (
        <div className="flex gap-2">
          <button
            onClick={() => { setSelectedId(v); setAction("approve"); }}
            className="px-2 py-1 bg-green-600 text-white text-xs rounded hover:bg-green-700"
          >
            Approve
          </button>
          <button
            onClick={() => { setSelectedId(v); setAction("reject"); }}
            className="px-2 py-1 bg-red-600 text-white text-xs rounded hover:bg-red-700"
          >
            Reject
          </button>
        </div>
      ),
    },
  ];

  const pending = data?.data ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Approval Center"
        description="Review and action pending access requests"
      />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatsCard label="Pending Approvals" value={pending.length} />
        <StatsCard label="High Risk" value={pending.filter((p) => p.risk_level === "high").length} />
        <StatsCard label="Overdue (>48h)" value={pending.filter((p) => new Date(p.created_at) < new Date(Date.now() - 48 * 3600000)).length} />
      </div>

      {bulkSelected.length > 0 && (
        <div className="flex items-center gap-3 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
          <span className="text-sm font-medium">{bulkSelected.length} selected</span>
          <button
            onClick={() => bulkMutation.mutate({ ids: bulkSelected, act: "approve" })}
            className="px-3 py-1 bg-green-600 text-white text-sm rounded hover:bg-green-700"
          >
            Bulk Approve
          </button>
          <button
            onClick={() => bulkMutation.mutate({ ids: bulkSelected, act: "reject" })}
            className="px-3 py-1 bg-red-600 text-white text-sm rounded hover:bg-red-700"
          >
            Bulk Reject
          </button>
        </div>
      )}

      <div className="bg-white dark:bg-gray-800 rounded-xl shadow">
        <DataTable columns={columns} data={pending} loading={isLoading} />
      </div>

      {selectedId && action && (
        <ConfirmDialog
          open={true}
          title={action === "approve" ? "Approve Request" : "Reject Request"}
          message={
            <div className="space-y-3">
              <p className="text-sm text-gray-600 dark:text-gray-400">
                {action === "approve"
                  ? "Are you sure you want to approve this access request?"
                  : "Please provide a reason for rejection."}
              </p>
              <textarea
                className="w-full border rounded p-2 text-sm dark:bg-gray-700 dark:border-gray-600"
                rows={3}
                placeholder="Comments (optional)"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
              />
            </div>
          }
          confirmLabel={action === "approve" ? "Approve" : "Reject"}
          confirmVariant={action === "approve" ? "success" : "danger"}
          onConfirm={() => actionMutation.mutate({ id: selectedId, act: action, cmt: comment })}
          onCancel={() => { setSelectedId(null); setAction(null); }}
        />
      )}
    </div>
  );
};

export default ApprovalCenter;
