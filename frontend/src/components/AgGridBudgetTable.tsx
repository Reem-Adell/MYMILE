import React, { useMemo } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, ColDef } from 'ag-grid-community';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-quartz.css';
import { BudgetBreakdown } from '../types';
import { formatMoney } from '../services/exploreView';
import { budgetView } from '../services/budgetView';

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
      category: 'Travel Essentials',
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

  const currency = breakdown.currency || 'USD';
  const columnDefs: ColDef<BudgetRow>[] = useMemo(() => [
    {
      headerName: 'Category',
      field: 'category',
      minWidth: 210,
      flex: 1.3,
      cellRenderer: (params: any) => <span className="mm-cell-title">{params.value}</span>
    },
    {
      headerName: 'Amount',
      field: 'amount',
      width: 130,
      sortable: true,
      filter: 'agNumberColumnFilter',
      filterParams: { maxNumConditions: 1 },
      enableCellChangeFlash: true, // briefly highlights the amount that changed after a hotel switch
      cellRenderer: (params: any) => <span className="mm-total">{formatMoney(params.value ?? 0, currency)}</span>
    },
    {
      headerName: 'Share',
      field: 'share',
      width: 150,
      sortable: true,
      cellRenderer: (params: any) => {
        const val = params.value || 0;
        return (
          <span className="mm-share">
            <span className="mm-share-track"><span style={{ width: `${Math.min(val, 100)}%` }} /></span>
            <span className="mm-share-value">{val}%</span>
          </span>
        );
      }
    },
    {
      headerName: 'Details',
      field: 'description',
      minWidth: 220,
      flex: 2,
      sortable: false,
      cellRenderer: (params: any) => <span className="mm-truncate mm-muted" title={params.value}>{params.value}</span>
    }
  ], [currency]);

  const remaining = breakdown.remaining_balance !== undefined && breakdown.remaining_balance !== null
    ? breakdown.remaining_balance
    : (targetBudget - total);

  const isPositive = remaining >= 0;
  const view = budgetView(breakdown); // labels only; the grid and its numbers are unchanged

  // Target and remaining are shown only when the traveler set a budget (no fallback figures).
  const hasUserBudget = !!(userBudget || breakdown.user_budget);

  return (
    <div className="mm-grid-shell">
      <div className="mm-grid-toolbar mm-budget-summary">
        {hasUserBudget && (
          <div>
            <small>Total budget</small>
            <b>{formatMoney(targetBudget, currency)}</b>
          </div>
        )}
        <div>
          <small>{view.totalLabel}</small>
          <b>{formatMoney(breakdown.total_estimated, currency)}</b>
        </div>
        {hasUserBudget && (
          <div>
            <small title={view.note}>{view.unallocatedLabel}</small>
            <b className={isPositive ? 'good' : 'bad'}>{formatMoney(Math.abs(remaining), currency)}</b>
          </div>
        )}
        <span className="mm-grid-meta">Powered by AG Grid</span>
      </div>
      <div className="ag-theme-quartz mm-grid">
        <AgGridReact
          theme="legacy"
          rowData={rowData}
          getRowId={(p) => p.data.category}
          columnDefs={columnDefs}
          defaultColDef={{ resizable: true, sortable: true }}
          domLayout="autoHeight"
          rowHeight={52}
          headerHeight={42}
          animateRows={true}
        />
      </div>
    </div>
  );
};
