import React from 'react';
import { CartItem } from '../types';

interface ShoppingCartDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  items: CartItem[];
  onUpdateQuantity: (productId: string, delta: number) => void;
  onRemoveItem: (productId: string) => void;
}

export const ShoppingCartDrawer: React.FC<ShoppingCartDrawerProps> = ({
  isOpen,
  onClose,
  items,
  onUpdateQuantity,
  onRemoveItem,
}) => {
  if (!isOpen) return null;

  const subtotal = items.reduce((acc, item) => acc + item.product.price * item.quantity, 0);

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
                  {items.length} {items.length === 1 ? 'essential' : 'essentials'} curated by Channel3
                </span>
              </div>
            </div>
            <button
              onClick={onClose}
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
                <h3 className="font-bold text-gray-900">Your cart is empty</h3>
                <p className="text-sm text-gray-500 mt-1 max-w-xs mx-auto">
                  Explore the essentials recommended for your trip by our Channel3 AI product engine.
                </p>
              </div>
            ) : (
              items.map(({ product, quantity }) => (
                <div key={product.id} className="flex gap-4 p-3.5 rounded-xl border border-slate-100 bg-white shadow-sm hover:border-slate-300 transition-all">
                  <img
                    src={product.image_url}
                    alt={product.name}
                    className="w-20 h-20 object-cover rounded-lg border border-gray-100 shrink-0"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-2">
                      <h4 className="text-sm font-bold text-gray-900 truncate">{product.name}</h4>
                      <button
                        onClick={() => onRemoveItem(product.id)}
                        className="text-gray-400 hover:text-red-500 text-xs transition-colors"
                      >
                        ✕
                      </button>
                    </div>
                    <span className="text-xs text-blue-600 font-semibold block mt-0.5">{product.category}</span>
                    <div className="flex items-center justify-between mt-3">
                      <span className="font-extrabold text-sm text-gray-900">
                        ${(product.price * quantity).toFixed(2)}
                      </span>
                      <div className="flex items-center gap-2 border border-gray-200 rounded-lg px-2 py-0.5">
                        <button
                          onClick={() => onUpdateQuantity(product.id, -1)}
                          className="text-gray-500 hover:text-gray-900 font-bold text-sm px-1"
                        >
                          -
                        </button>
                        <span className="text-xs font-bold text-gray-800">{quantity}</span>
                        <button
                          onClick={() => onUpdateQuantity(product.id, 1)}
                          className="text-gray-500 hover:text-gray-900 font-bold text-sm px-1"
                        >
                          +
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Footer */}
          {items.length > 0 && (
            <div className="p-6 bg-slate-50 border-t border-slate-200 space-y-4">
              <div className="space-y-1.5">
                <div className="flex justify-between text-sm text-gray-600">
                  <span>Subtotal</span>
                  <span className="font-semibold text-gray-900">${subtotal.toFixed(2)}</span>
                </div>
                <div className="flex justify-between text-sm text-gray-600">
                  <span>Channel3 Partner Shipping</span>
                  <span className="text-green-600 font-semibold">Standard Free</span>
                </div>
                <div className="border-t border-gray-200 pt-2 flex justify-between text-base font-extrabold text-gray-900">
                  <span>Estimated Total</span>
                  <span className="text-blue-700">${subtotal.toFixed(2)}</span>
                </div>
              </div>

              <div className="space-y-2">
                {items[0] && (
                  <a
                    href={items[0].product.purchase_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-3 px-4 rounded-xl flex items-center justify-center gap-2 shadow-sm transition-all"
                  >
                    Proceed to Partner Checkout ↗
                  </a>
                )}
                <p className="text-[11px] text-center text-gray-500">
                  Purchases completed securely through verified partner stores via Channel3.
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
