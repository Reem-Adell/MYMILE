import React, { useMemo } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, ColDef } from 'ag-grid-community';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-quartz.css';
import { BudgetBreakdown, BudgetCategoryDetail } from '../types';

ModuleRegistry.registerModules([AllCommunityModule]);

interface AgGridBudgetTableProps {
  breakdown: BudgetBreakdown;
  userBudget?: number;
}

interface BudgetRow {
  category: string;
  amount: number;
  share: number;
  description: string;
}

export const AgGridBudgetTable: React.FC<AgGridBudgetTableProps> = ({ breakdown, userBudget }) => {
  const total = breakdown.total_estimated || 1;
  const targetBudget = userBudget || breakdown.user_budget || total;

  const rowData: BudgetRow[] = useMemo(() => [
    {
      category: 'Accommodation (Stays)',
      amount: breakdown.accommodation,
      share: Math.round((breakdown.accommodation / total) * 100),
      description: 'Handpicked boutique stay & taxes'
    },
    {
      category: 'Food & Artisan Dining',
      amount: breakdown.food,
      share: Math.round((breakdown.food / total) * 100),
      description: 'Breakfast, lunch cafes, dinner experiences'
    },
    {
      category: 'Local Transportation',
      amount: breakdown.transportation,
      share: Math.round((breakdown.transportation / total) * 100),
      description: 'Subway pass, regional rail, transfers'
    },
    {
      category: 'Sightseeing & Activities',
      amount: breakdown.activities,
      share: Math.round((breakdown.activities / total) * 100),
      description: 'Historic landmarks, tickets, temple entries'
    },
    {
      category: 'Travel Essentials (Channel3)',
      amount: breakdown.travel_essentials,
      share: Math.round((breakdown.travel_essentials / total) * 100),
      description: 'Smart packing gear, adapters, rain shell'
    },
    {
      category: 'Contingency & Other',
      amount: breakdown.contingency_and_other,
      share: Math.round((breakdown.contingency_and_other / total) * 100),
      description: 'Flexible buffer for unexpected incidentals'
    }
  ], [breakdown, total]);

  const columnDefs: ColDef<BudgetRow>[] = useMemo(() => [
    {
      headerName: 'Expense Category',
      field: 'category',
      minWidth: 220,
      flex: 1.5,
      cellRenderer: (params: any) => (
        <span className="font-bold text-gray-900">{params.value}</span>
      )
    },
    {
      headerName: 'Allocated Amount',
      field: 'amount',
      width: 160,
      sortable: true,
      filter: 'agNumberColumnFilter',
      cellRenderer: (params: any) => (
        <span className="font-extrabold text-blue-700 text-sm">
          ${params.value?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </span>
      )
    },
    {
      headerName: 'Share of Total',
      field: 'share',
      width: 140,
      sortable: true,
      cellRenderer: (params: any) => {
        const val = params.value || 0;
        return (
          <div className="flex items-center gap-2 h-full w-full">
            <div className="w-16 bg-gray-200 h-2 rounded-full overflow-hidden">
              <div className="bg-yellow-400 h-full rounded-full" style={{ width: `${Math.min(val, 100)}%` }} />
            </div>
            <span className="text-xs font-semibold text-gray-700">{val}%</span>
          </div>
        );
      }
    },
    {
      headerName: 'Allocation Details & Purpose',
      field: 'description',
      minWidth: 240,
      flex: 2,
      cellRenderer: (params: any) => (
        <span className="text-xs text-gray-600">{params.value}</span>
      )
    }
  ], []);

  const remaining = breakdown.remaining_balance !== undefined && breakdown.remaining_balance !== null
    ? breakdown.remaining_balance
    : (targetBudget - total);

  const isPositive = remaining >= 0;

  return (
    <div className="w-full bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
      <div className="p-4 bg-slate-50 border-b border-slate-200 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="bg-yellow-400 text-gray-900 text-[11px] font-extrabold px-2 py-0.5 rounded">
              AG GRID ANALYTICS
            </span>
            <h3 className="text-base font-bold text-gray-900">Multi-Category Budget Breakdown</h3>
          </div>
          <p className="text-xs text-gray-500 mt-0.5">
            Balanced dynamically by the MYMILE AI Optimization Agent.
          </p>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right">
            <span className="text-[11px] text-gray-500 block uppercase font-bold tracking-wider">Target Budget</span>
            <span className="text-sm font-extrabold text-gray-900">${targetBudget.toLocaleString()}</span>
          </div>
          <div className="text-right">
            <span className="text-[11px] text-gray-500 block uppercase font-bold tracking-wider">Remaining Buffer</span>
            <span className={`text-sm font-extrabold ${isPositive ? 'text-green-600' : 'text-red-500'}`}>
              ${remaining.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
        </div>
      </div>
      <div className="ag-theme-quartz" style={{ height: '320px', width: '100%' }}>
        <AgGridReact
          rowData={rowData}
          columnDefs={columnDefs}
          defaultColDef={{ resizable: true, sortable: true }}
          rowHeight={48}
          headerHeight={42}
          animateRows={true}
        />
      </div>
    </div>
  );
};
