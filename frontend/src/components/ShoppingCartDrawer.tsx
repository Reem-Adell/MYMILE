import React from 'react';
import { CartItem } from '../types';
import { formatMoney } from '../services/exploreView';
import { buyLink, cartSubtotal, productPrice, productSource } from '../services/productView';

interface ShoppingCartDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  items: CartItem[];
  onUpdateQuantity: (productId: string, delta: number) => void;
  onRemoveItem: (productId: string) => void;
  onUpgrade?: () => void;
}

// A shopping list of Channel3 products. Each item is bought on its own retailer's site:
// MYMILE has no unified checkout for products (Premium checkout via PayPal is separate).
export const ShoppingCartDrawer: React.FC<ShoppingCartDrawerProps> = ({
  isOpen,
  onClose,
  items,
  onUpdateQuantity,
  onRemoveItem,
  onUpgrade,
}) => {
  if (!isOpen) return null;

  const subtotal = cartSubtotal(items);
  // purchase_url is null when the backend does not allow retailer links (Free plan).
  const anyLinkMissing = items.some((item) => !item.product.purchase_url);

  return (
    <div className="fixed inset-0 z-50 overflow-hidden">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />

      <div className="fixed inset-y-0 right-0 max-w-full flex pl-10">
        <div className="w-screen max-w-md bg-white shadow-2xl flex flex-col">
          {/* Header */}
          <div className="p-6 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-yellow-400 text-gray-900 flex items-center justify-center font-bold">
                🛍
              </div>
              <div>
                <h2 className="text-lg font-bold text-gray-900">Your Travel Bag</h2>
                <span className="text-xs text-gray-500">
                  {items.length} {items.length === 1 ? 'item' : 'items'} saved for your trip
                </span>
              </div>
            </div>
            <button
              onClick={onClose}
              aria-label="Close"
              className="w-8 h-8 rounded-full bg-gray-200 hover:bg-gray-300 text-gray-700 flex items-center justify-center transition-colors"
            >
              ✕
            </button>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto p-6 space-y-4">
            {items.length === 0 ? (
              <div className="text-center py-12">
                <div className="text-4xl mb-3">🎒</div>
                <h3 className="font-bold text-gray-900">Your bag is empty</h3>
                <p className="text-sm text-gray-500 mt-1 max-w-xs mx-auto">
                  Add products suggested for your trip to keep them in one place.
                </p>
              </div>
            ) : (
              items.map(({ product, quantity }) => {
                const link = buyLink(product);
                return (
                  <div key={product.id} className="flex gap-4 p-3.5 rounded-xl border border-slate-100 bg-white shadow-sm hover:border-slate-300 transition-all">
                    {product.image_url ? (
                      <img
                        src={product.image_url}
                        alt={product.name}
                        className="w-20 h-20 object-cover rounded-lg border border-gray-100 shrink-0"
                      />
                    ) : (
                      <div className="w-20 h-20 rounded-lg border border-gray-100 bg-slate-50 shrink-0" aria-hidden="true" />
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-start justify-between gap-2">
                        <h4 className="text-sm font-bold text-gray-900 truncate">{product.name}</h4>
                        <button
                          onClick={() => onRemoveItem(product.id)}
                          aria-label={`Remove ${product.name}`}
                          className="text-gray-400 hover:text-red-500 text-xs transition-colors"
                        >
                          ✕
                        </button>
                      </div>
                      {productSource(product) && (
                        <span className="text-xs text-gray-500 block mt-0.5 truncate">{productSource(product)}</span>
                      )}
                      <div className="flex items-center justify-between mt-3">
                        <span className="font-extrabold text-sm text-gray-900">
                          {product.price == null
                            ? productPrice(product)
                            : formatMoney(product.price * quantity, product.currency || 'USD')}
                        </span>
                        <div className="flex items-center gap-2 border border-gray-200 rounded-lg px-2 py-0.5">
                          <button
                            onClick={() => onUpdateQuantity(product.id, -1)}
                            aria-label="Decrease quantity"
                            className="text-gray-500 hover:text-gray-900 font-bold text-sm px-1"
                          >
                            -
                          </button>
                          <span className="text-xs font-bold text-gray-800">{quantity}</span>
                          <button
                            onClick={() => onUpdateQuantity(product.id, 1)}
                            aria-label="Increase quantity"
                            className="text-gray-500 hover:text-gray-900 font-bold text-sm px-1"
                          >
                            +
                          </button>
                        </div>
                      </div>
                      {link && (
                        <a
                          href={link.href}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-block mt-2 text-xs font-bold text-blue-600 hover:underline"
                        >
                          {link.label} ↗
                        </a>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {/* Footer */}
          {items.length > 0 && (
            <div className="p-6 bg-slate-50 border-t border-slate-200 space-y-3">
              {subtotal && (
                <div className="flex justify-between text-sm text-gray-600">
                  <span>Estimated subtotal{subtotal.complete ? '' : ' (items with a listed price)'}</span>
                  <span className="font-bold text-gray-900">{formatMoney(subtotal.amount, subtotal.currency)}</span>
                </div>
              )}
              {anyLinkMissing && onUpgrade && (
                <div className="rounded-xl border border-yellow-300 bg-yellow-50 p-3 text-center text-xs text-gray-800">
                  Retailer links are included with Premium.
                  <button
                    onClick={onUpgrade}
                    className="mt-2 w-full bg-yellow-400 hover:bg-yellow-300 text-gray-900 font-bold py-2 px-4 rounded-lg transition-all"
                  >
                    See Premium
                  </button>
                </div>
              )}
              <p className="text-[11px] text-center text-gray-500">
                Each item is bought separately on its retailer&apos;s site, where prices and availability are
                confirmed. MYMILE doesn&apos;t process product purchases.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
