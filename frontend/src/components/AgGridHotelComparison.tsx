import React, { useMemo } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, ColDef, RowSelectedEvent } from 'ag-grid-community';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-quartz.css';
import { Hotel } from '../types';

ModuleRegistry.registerModules([AllCommunityModule]);

interface AgGridHotelComparisonProps {
  hotels: Hotel[];
  selectedHotelId?: string;
  onSelectHotel: (hotel: Hotel) => void;
  isPremium: boolean;
  totalNights: number;
}

export const AgGridHotelComparison: React.FC<AgGridHotelComparisonProps> = ({
  hotels,
  selectedHotelId,
  onSelectHotel,
  isPremium,
  totalNights
}) => {
  const columnDefs: ColDef<Hotel>[] = useMemo(() => [
    {
      headerName: 'Select',
      width: 100,
      pinned: 'left',
      cellRenderer: (params: any) => {
        const hotel = params.data as Hotel;
        const isSelected = hotel.id === selectedHotelId || (hotel.is_best_match && !selectedHotelId);
        return (
          <div className="flex items-center justify-center h-full">
            <button
              onClick={() => onSelectHotel(hotel)}
              className={`px-3 py-1 rounded-full text-xs font-bold transition-all ${
                isSelected
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'bg-gray-100 text-gray-700 hover:bg-yellow-400 hover:text-gray-900'
              }`}
            >
              {isSelected ? 'Selected' : 'Choose'}
            </button>
          </div>
        );
      }
    },
    {
      headerName: 'Hotel Name & Match',
      field: 'name',
      minWidth: 240,
      flex: 2,
      cellRenderer: (params: any) => {
        const h = params.data as Hotel;
        return (
          <div className="flex flex-col justify-center h-full py-1">
            <div className="flex items-center gap-2">
              <span className="font-bold text-gray-900">{h.name}</span>
              {h.is_best_match && (
                <span className="bg-yellow-100 text-yellow-800 text-[10px] font-extrabold px-2 py-0.5 rounded-full border border-yellow-300">
                  BEST MATCH
                </span>
              )}
            </div>
            <span className="text-xs text-gray-500 truncate">{h.location}</span>
          </div>
        );
      }
    },
    {
      headerName: 'Rating',
      field: 'rating',
      width: 110,
      sortable: true,
      filter: 'agNumberColumnFilter',
      cellRenderer: (params: any) => (
        <div className="flex items-center gap-1 h-full text-sm font-semibold text-gray-800">
          <span className="text-yellow-500 font-bold">★</span>
          <span>{params.value}</span>
          <span className="text-xs text-gray-400">({params.data.reviews_count})</span>
        </div>
      )
    },
    {
      headerName: 'Nightly Rate',
      field: 'price_per_night',
      width: 130,
      sortable: true,
      filter: 'agNumberColumnFilter',
      valueFormatter: (params) => `$${params.value}/nt`
    },
    {
      headerName: `Total (${totalNights} nts)`,
      field: 'total_price',
      width: 140,
      sortable: true,
      filter: 'agNumberColumnFilter',
      cellRenderer: (params: any) => (
        <div className="flex items-center h-full font-bold text-blue-700">
          ${params.value.toLocaleString()}
        </div>
      )
    },
    {
      headerName: 'Distance / Location',
      field: 'distance_to_center',
      minWidth: 200,
      flex: 1,
      cellRenderer: (params: any) => (
        <div className="flex items-center h-full text-xs text-gray-600 truncate">
          {params.value || 'Central location'}
        </div>
      )
    },
    {
      headerName: 'Key Amenities',
      field: 'amenities',
      minWidth: 220,
      flex: 1.5,
      cellRenderer: (params: any) => {
        const amenities = (params.value || []) as string[];
        return (
          <div className="flex items-center gap-1 h-full overflow-hidden">
            {amenities.slice(0, 2).map((a, i) => (
              <span key={i} className="text-[11px] bg-slate-100 text-slate-700 px-2 py-0.5 rounded border border-slate-200 whitespace-nowrap">
                {a}
              </span>
            ))}
            {amenities.length > 2 && (
              <span className="text-[10px] text-gray-400">+{amenities.length - 2}</span>
            )}
          </div>
        );
      }
    },
    {
      headerName: 'Booking Provider',
      width: 140,
      cellRenderer: (params: any) => {
        const link = params.data.booking_link;
        if (!isPremium) {
          return (
            <div className="flex items-center h-full text-xs text-gray-400 italic">
              Premium only
            </div>
          );
        }
        return link ? (
          <div className="flex items-center h-full">
            <a
              href={link}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs bg-yellow-400 hover:bg-yellow-500 text-gray-900 font-bold px-3 py-1.5 rounded-lg flex items-center gap-1 transition-all shadow-sm"
            >
              Book Stay ↗
            </a>
          </div>
        ) : (
          <span className="text-xs text-gray-400">Unavailable</span>
        );
      }
    }
  ], [selectedHotelId, isPremium, totalNights, onSelectHotel]);

  return (
    <div className="w-full bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
      <div className="p-4 bg-slate-50 border-b border-slate-200 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="bg-blue-600 text-white text-[11px] font-bold px-2 py-0.5 rounded">AG GRID PREMIUM</span>
            <h3 className="text-base font-bold text-gray-900">Hotel Comparison & Live Trade-Off Matrix</h3>
          </div>
          <p className="text-xs text-gray-500 mt-0.5">
            Sort by rating or price. Selecting any hotel updates your budget balance dynamically.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-gray-600">
          <span className="w-2.5 h-2.5 rounded-full bg-green-500"></span>
          <span>Verified Accommodations Data</span>
        </div>
      </div>
      <div className="ag-theme-quartz" style={{ height: '360px', width: '100%' }}>
        <AgGridReact
          rowData={hotels}
          columnDefs={columnDefs}
          defaultColDef={{
            resizable: true,
            sortable: true,
          }}
          rowHeight={56}
          headerHeight={44}
          animateRows={true}
          onRowSelected={(e: RowSelectedEvent<Hotel>) => {
            if (e.node.isSelected() && e.data) {
              onSelectHotel(e.data);
            }
          }}
        />
      </div>
    </div>
  );
};
