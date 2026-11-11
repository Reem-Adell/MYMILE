import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AgGridReact } from 'ag-grid-react';
import {
  ModuleRegistry, AllCommunityModule, ColDef, GridApi, GridReadyEvent, RowClickedEvent, RowSelectionOptions,
} from 'ag-grid-community';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-quartz.css';
import { Hotel } from '../types';
import { PRICE_VARIES_NOTE, formatMoney } from '../services/exploreView';
import { createSelectionGate, hotelSearchText, nullsLastComparator, ratingValue } from '../services/hotelComparison';

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
  const apiRef = useRef<GridApi<Hotel> | null>(null);
  const [search, setSearch] = useState('');
  // On phones the hotel column scrolls with the others, so pinned columns don't fill the screen.
  const [narrow, setNarrow] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(max-width: 640px)').matches);
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 640px)');
    const update = () => setNarrow(mq.matches);
    mq.addEventListener('change', update);
    return () => mq.removeEventListener('change', update);
  }, []);
  // Latest values for cell renderers, so column definitions (and the user's sort/filter
  // state) never need to be rebuilt when the selection changes.
  const selectedRef = useRef<string | undefined>(selectedHotelId);
  selectedRef.current = selectedHotelId;
  const onSelectRef = useRef(onSelectHotel);
  onSelectRef.current = onSelectHotel;
  const gateRef = useRef(createSelectionGate(selectedHotelId));

  // Row clicks and the Choose button share this path; the gate drops repeats.
  const choose = useCallback((hotel: Hotel | undefined) => {
    if (!hotel || hotel.is_placeholder) return;
    if (gateRef.current.select(hotel.id)) onSelectRef.current(hotel);
  }, []);

  // Mirror the app's selected hotel into AG Grid's row selection (source 'api'),
  // whether it came from this grid, the assistant, or a new plan.
  const syncSelection = useCallback(() => {
    const api = apiRef.current;
    const id = selectedRef.current;
    gateRef.current.sync(id);
    if (!api) return;
    const node = id ? api.getRowNode(id) : undefined;
    if (node) node.setSelected(true, true, 'api');
    else api.deselectAll();
    api.refreshCells({ columns: ['select'], force: true });
  }, []);

  useEffect(syncSelection, [selectedHotelId, hotels, syncSelection]);

  const onGridReady = useCallback((e: GridReadyEvent<Hotel>) => {
    apiRef.current = e.api;
    syncSelection();
  }, [syncSelection]);

  const onRowClicked = useCallback((e: RowClickedEvent<Hotel>) => {
    const target = e.event?.target as HTMLElement | null;
    // Links open the provider; the Choose button selects on its own.
    if (target?.closest('a, button')) return;
    choose(e.data);
  }, [choose]);

  const rowSelection = useMemo<RowSelectionOptions<Hotel>>(() => ({
    mode: 'singleRow',
    checkboxes: false,
    enableClickSelection: false, // clicks go through choose(); AG Grid selection follows the app state
    isRowSelectable: (node) => !node.data?.is_placeholder,
  }), []);

  const columnDefs: ColDef<Hotel>[] = useMemo(() => [
    {
      colId: 'select',
      headerName: '',
      width: 108,
      pinned: 'left',
      sortable: false,
      resizable: false,
      getQuickFilterText: () => '',
      cellRenderer: (params: any) => {
        const hotel = params.data as Hotel;
        const isSelected = hotel.id === selectedRef.current;
        return (
          <button
            type="button"
            aria-pressed={isSelected}
            onClick={() => choose(hotel)}
            className={`mm-choose${isSelected ? ' selected' : ''}`}
          >
            {isSelected ? 'Selected' : 'Choose'}
          </button>
        );
      }
    },
    {
      headerName: 'Hotel',
      field: 'name',
      width: narrow ? 220 : 270,
      pinned: narrow ? null : 'left',
      getQuickFilterText: (params) => (params.data ? hotelSearchText(params.data) : ''),
      cellRenderer: (params: any) => {
        const h = params.data as Hotel;
        return (
          <div className="mm-cell-stack" title={`${h.name} · ${h.location}`}>
            <span className="mm-cell-title">{h.name}</span>
            <span className="mm-cell-sub">
              {h.is_best_match && <span className="mm-best">Best match</span>}
              <span className="mm-truncate">{h.location}</span>
            </span>
          </div>
        );
      }
    },
    {
      colId: 'rating',
      headerName: 'Rating',
      valueGetter: (params) => ratingValue(params.data),
      width: 108,
      sortable: true,
      sortingOrder: ['desc', 'asc', null],
      comparator: nullsLastComparator,
      filter: 'agNumberColumnFilter',
      filterParams: { maxNumConditions: 1 },
      getQuickFilterText: () => '',
      cellRenderer: (params: any) => (params.value == null ? (
        <span className="mm-muted">—</span>
      ) : (
        <span className="mm-rating"
              title={params.data.reviews_count ? `${Number(params.data.reviews_count).toLocaleString()} reviews` : undefined}>
          <span aria-hidden="true">★</span> {params.value}
        </span>
      ))
    },
    {
      headerName: 'Per night',
      headerTooltip: `Estimated. ${PRICE_VARIES_NOTE}`,
      field: 'price_per_night',
      width: 128,
      sortable: true,
      sortingOrder: ['asc', 'desc', null],
      comparator: nullsLastComparator,
      filter: 'agNumberColumnFilter',
      filterParams: { maxNumConditions: 1 },
      getQuickFilterText: () => '',
      cellRenderer: (params: any) => (params.value == null
        ? <span className="mm-muted">Not listed</span>
        : <span>{formatMoney(params.value, params.data.currency)}</span>)
    },
    {
      headerName: 'Total',
      headerTooltip: `Estimated total for ${totalNights} night${totalNights === 1 ? '' : 's'}. ${PRICE_VARIES_NOTE}`,
      field: 'total_price',
      width: 128,
      sortable: true,
      sortingOrder: ['asc', 'desc', null],
      comparator: nullsLastComparator,
      filter: 'agNumberColumnFilter',
      filterParams: { maxNumConditions: 1 },
      getQuickFilterText: () => '',
      cellRenderer: (params: any) => (params.value == null
        ? <span className="mm-muted">—</span>
        : <span className="mm-total">{formatMoney(params.value, params.data.currency)}</span>)
    },
    {
      headerName: 'Nearby',
      field: 'distance_to_center',
      minWidth: 180,
      flex: 1,
      sortable: false,
      cellRenderer: (params: any) => (params.value
        ? <span className="mm-truncate mm-muted" title={params.value}>{params.value}</span>
        : <span className="mm-muted">—</span>)
    },
    {
      headerName: 'Amenities',
      field: 'amenities',
      minWidth: 190,
      flex: 1,
      sortable: false,
      getQuickFilterText: () => '',
      cellRenderer: (params: any) => {
        const amenities = (params.value || []) as string[];
        if (!amenities.length) return <span className="mm-muted">—</span>;
        return (
          <span className="mm-truncate mm-muted" title={amenities.join(', ')}>
            {amenities.slice(0, 2).join(' · ')}
            {amenities.length > 2 && <span className="mm-more"> +{amenities.length - 2}</span>}
          </span>
        );
      }
    },
    {
      headerName: 'Book',
      width: 150,
      sortable: false,
      getQuickFilterText: () => '',
      cellRenderer: (params: any) => {
        const h = params.data as Hotel;
        if (!isPremium) return <span className="mm-muted">Premium only</span>;
        if (h.booking_link) {
          return (
            <a href={h.booking_link} target="_blank" rel="noopener noreferrer" className="mm-book">
              {h.booking_link_type === 'provider' && h.booking_provider ? h.booking_provider : 'Book stay'} ↗
            </a>
          );
        }
        return h.data_source === 'serpapi' && h.property_token && !h.is_placeholder
          // Live hotel: provider links are looked up when it is chosen (one cached lookup).
          ? <span className="mm-muted">Choose to see sites</span>
          : <span className="mm-muted">Unavailable</span>;
      }
    }
  ], [isPremium, totalNights, choose, narrow]);

  return (
    <div className="mm-grid-shell">
      <div className="mm-grid-toolbar">
        <input
          type="search"
          className="mm-grid-search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search hotels, areas or amenities"
          aria-label="Search hotels"
        />
        <span className="mm-grid-meta">
          {hotels.length} stay{hotels.length === 1 ? '' : 's'} · Powered by AG Grid
        </span>
      </div>
      <div className="ag-theme-quartz mm-grid mm-hotel-grid">
        <AgGridReact
          theme="legacy"
          rowData={hotels}
          columnDefs={columnDefs}
          defaultColDef={{
            resizable: true,
            sortable: true,
          }}
          getRowId={(p) => p.data.id}
          rowSelection={rowSelection}
          quickFilterText={search}
          overlayNoRowsTemplate="No hotels match your search or filters."
          domLayout="autoHeight"
          rowHeight={60}
          headerHeight={42}
          tooltipShowDelay={300}
          animateRows={true}
          onGridReady={onGridReady}
          onRowClicked={onRowClicked}
        />
      </div>
    </div>
  );
};
