import '@testing-library/jest-dom';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeAll, afterAll } from 'vitest';
import { server } from './mocks/server';

// Polyfill URL.createObjectURL / revokeObjectURL for jsdom (needed by ShareCardDialog)
if (typeof URL.createObjectURL === 'undefined') {
  let _urlCounter = 0;
  URL.createObjectURL = (_blob: Blob) => `blob:http://test/${++_urlCounter}`;
  URL.revokeObjectURL = (_url: string) => {};
}

// Polyfill ClipboardItem for jsdom
if (typeof globalThis.ClipboardItem === 'undefined') {
  (globalThis as unknown as Record<string, unknown>).ClipboardItem = class ClipboardItem {
    private _items: Record<string, Blob>;
    constructor(items: Record<string, Blob>) {
      this._items = items;
    }
    get types() {
      return Object.keys(this._items);
    }
    getType(type: string) {
      return Promise.resolve(this._items[type]);
    }
  };
}

// Polyfill ResizeObserver for Recharts — fires callback immediately with a synthetic size
global.ResizeObserver = class ResizeObserver {
  private cb: ResizeObserverCallback;
  constructor(cb: ResizeObserverCallback) {
    this.cb = cb;
  }
  observe(target: Element) {
    // Immediately invoke with a synthetic entry so Recharts gets dimensions
    this.cb(
      [
        {
          target,
          contentRect: { width: 800, height: 300, top: 0, left: 0, bottom: 300, right: 800, x: 0, y: 0 } as DOMRectReadOnly,
          borderBoxSize: [{ inlineSize: 800, blockSize: 300 }] as unknown as readonly ResizeObserverSize[],
          contentBoxSize: [{ inlineSize: 800, blockSize: 300 }] as unknown as readonly ResizeObserverSize[],
          devicePixelContentBoxSize: [] as unknown as readonly ResizeObserverSize[],
        } as ResizeObserverEntry,
      ],
      this,
    );
  }
  unobserve() {}
  disconnect() {}
};

// Polyfill scrollIntoView
Element.prototype.scrollIntoView = function () {};

// Polyfill HTMLDialogElement.showModal/close for jsdom
if (!HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '');
  };
}
if (!HTMLDialogElement.prototype.close) {
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open');
  };
}

// Polyfill EventSource for jsdom (no-op by default; tests that need it provide their own mock)
if (typeof global.EventSource === 'undefined') {
  (global as unknown as Record<string, unknown>).EventSource = class EventSource {
    url: string;
    readyState = 0;
    constructor(url: string) {
      this.url = url;
      this.readyState = 1;
    }
    addEventListener() {}
    removeEventListener() {}
    close() { this.readyState = 2; }
    set onerror(_fn: unknown) {}
    set onmessage(_fn: unknown) {}
    set onopen(_fn: unknown) {}
  };
}

// Polyfill File.prototype.text() for jsdom (File inherits from Blob which has .text() in newer environments)
if (!File.prototype.text) {
  File.prototype.text = function () {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = () => reject(reader.error);
      reader.readAsText(this);
    });
  };
}

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
});
afterAll(() => server.close());
