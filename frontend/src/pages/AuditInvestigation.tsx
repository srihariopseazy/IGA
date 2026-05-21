import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "../utils/api";
import { PageHeader } from "../components/ui/PageHeader";
import { DataTable } from "../components/ui/DataTable";
import { Badge } from "../components/ui/Badge";

interface AuditLog {
  id: string;
  actor_name: string;
  action: string;
  resource_type: string;
  resource_id: string;
  status: string;
  ip_address: string;
  created_at: string;
  metadata: Record<string, unknown>;
}

const AuditInvestigation: React.FC = () => {
  const [filters, setFilters] = useState({
    actor_id: "",
    action: "",
    resource_type: "",
    date_from: "",
    date_to: "",
    status: "",
  });
  const [applied, setApplied] = useState(filters);
  const [page, setPage] = useState(1);

  const { data, isLoading } = useQuery<{ data: AuditLog[]; total: number }>({
    queryKey: ["audit-logs", applied, page],
    queryFn: () =>
      api
        .get("/api/v1/audit/logs", {
          params: { ...applied, page, limit: 50 },
        })
        .then((r) => r.data),
  });

  const exportLogs = () => {
    api.get("/api/v1/audit/export", { params: applied, responseType: "blob" }).then((r) => {
      const url = window.URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `audit-logs-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
    });
  };

  const columns = [
    {
      key: "created_at",
      header: "Timestamp",
      render: (v: string) => new Date(v).toLocaleString(),
    },
    { key: "actor_name", header: "Actor" },
    { key: "action", header: "Action" },
    { key: "resource_type", header: "Resource Type" },
    {
      key: "resource_id",
      header: "Resource ID",
      render: (v: string) => v ? v.slice(0, 8) + "..." : "—",
    },
    {
      key: "status",
      header: "Status",
      render: (v: string) => (
        <Badge variant={v === "success" ? "success" : "danger"}>{v}</Badge>
      ),
    },
    { key: "ip_address", header: "IP Address" },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Audit Investigation"
        subtitle="Search and analyze immutable audit trail"
        actions={
          <button
            onClick={exportLogs}
            className="px-4 py-2 bg-gray-600 text-white rounded-lg hover:bg-gray-700 text-sm font-medium"
          >
            Export CSV
          </button>
        }
      />

      <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-4">
        <h3 className="font-medium mb-3 text-sm">Filters</h3>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <input
            className="border rounded-lg px-3 py-2 text-sm dark:bg-gray-700 dark:border-gray-600"
            placeholder="Actor ID"
            value={filters.actor_id}
            onChange={(e) => setFilters((f) => ({ ...f, actor_id: e.target.value }))}
          />
          <input
            className="border rounded-lg px-3 py-2 text-sm dark:bg-gray-700 dark:border-gray-600"
            placeholder="Action"
            value={filters.action}
            onChange={(e) => setFilters((f) => ({ ...f, action: e.target.value }))}
          />
          <input
            className="border rounded-lg px-3 py-2 text-sm dark:bg-gray-700 dark:border-gray-600"
            placeholder="Resource Type"
            value={filters.resource_type}
            onChange={(e) => setFilters((f) => ({ ...f, resource_type: e.target.value }))}
          />
          <input
            type="date"
            className="border rounded-lg px-3 py-2 text-sm dark:bg-gray-700 dark:border-gray-600"
            value={filters.date_from}
            onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value }))}
          />
          <input
            type="date"
            className="border rounded-lg px-3 py-2 text-sm dark:bg-gray-700 dark:border-gray-600"
            value={filters.date_to}
            onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value }))}
          />
          <button
            onClick={() => { setApplied(filters); setPage(1); }}
            className="px-3 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
          >
            Apply
          </button>
        </div>
      </div>

      <div className="bg-white dark:bg-gray-800 rounded-xl shadow">
        <div className="px-4 py-3 border-b dark:border-gray-700 flex justify-between items-center">
          <span className="text-sm text-gray-500">{data?.total ?? 0} records found</span>
          <div className="flex gap-2">
            <button
              disabled={page === 1}
              onClick={() => setPage((p) => p - 1)}
              className="px-3 py-1 border rounded text-sm disabled:opacity-50"
            >
              Prev
            </button>
            <span className="px-3 py-1 text-sm">Page {page}</span>
            <button
              onClick={() => setPage((p) => p + 1)}
              className="px-3 py-1 border rounded text-sm"
            >
              Next
            </button>
          </div>
        </div>
        <DataTable columns={columns} data={data?.data ?? []} isLoading={isLoading} />
      </div>
    </div>
  );
};

export default AuditInvestigation;
